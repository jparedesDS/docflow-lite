"""Vista Seguimiento — parte de estado de un pedido (claro y conciso).

Buscador de pedido + un único informe de ESTADO, sin duplicar lo que ya vive en
otras secciones (no repite la tabla de Documentos ni los KPIs globales de Inicio
ni los gráficos de Analítica). De arriba a abajo:

  1. Cabecera     → identidad + veredicto de estado + % aprobado.
  2. Documentación→ distribución (aprobado/enviado/devuelto/sin enviar) en 1 barra.
  3. Requiere atención → lo accionable (críticos / devueltos / atrasados), corto.
  4. Plazo        → curva-S de ESTE pedido (real vs esperado + fechas).
  5. Fabricación  → fases Fab/Montaje/Envío (ERP).
  6. Equipos      → resumen de tags + tabla compacta de inspección.

Carga pesada (monitoring / Excel) en hilos para no bloquear la UI.
"""

import logging
import re
import threading
from collections import Counter

import customtkinter as ctk

from core.services import erp as erp_service
from core.services import erp_tags
from gui import theme
from gui.views.documentos import _fmt, _status_color, _trunc
from gui.widgets import ui
from gui.widgets.scrollframe import ScrollFrame
from gui.widgets.table import DataTable

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────
_section_header = ui.section_header  # design system compartido


def _phase_color(pct: int) -> str:
    if pct >= 100:
        return theme.GREEN
    if pct > 0:
        return theme.AMBER
    return theme.RED


def _to_int(v) -> int:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _norm_doc(s) -> str:
    """Nº de documento comparable: sin espacios y en mayúsculas."""
    return re.sub(r"\s+", "", str(s or "")).upper()


# ════════════════════════════════════════════════════════════════════════════
#  Vista principal
# ════════════════════════════════════════════════════════════════════════════

class PedidosView(ctk.CTkFrame):
    def __init__(self, master, on_open_documentos=None, on_open_documento=None, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._on_open_documentos = on_open_documentos    # → Documentos filtrado por pedido
        self._on_open_documento = on_open_documento      # → Documentos por Nº de documento
        self._bundle: dict = {}
        self._doc_index: dict = {}
        self._projects: list[dict] = []
        self._label_to_pedido: dict[str, str] = {}
        self._pedido_current: str | None = None
        self._tags_current: list[dict] = []
        self._build_layout()
        self.after(60, self._load_projects)

    # ── Layout raíz ─────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        ui.page_header(
            self, "Seguimiento",
            "Elige un pedido y mira de un vistazo cómo va: documentación, fabricación, "
            "equipos y qué requiere acción.",
            help_key="pedidos")

        # ── Barra de filtros (encontrar el pedido) ───────────────────────
        bar = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=12,
                           border_width=1, border_color=theme.BORDER)
        bar.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_2, theme.SPACE_2))
        row = ctk.CTkFrame(bar, fg_color="transparent")
        row.pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_3)
        ctk.CTkLabel(row, text="🔍", font=theme.font(15)).pack(side="left", padx=(0, theme.SPACE_2))
        self.ent_search = ctk.CTkEntry(
            row, placeholder_text="Nº de pedido o cliente…", height=theme.HEIGHT_INPUT,
            corner_radius=theme.RADIUS_MD, fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_SMALL)
        self.ent_search.pack(side="left", fill="x", expand=True, padx=(0, theme.SPACE_2))
        self.ent_search.bind("<KeyRelease>", lambda e: self._update_matches())
        self.opt_pedido = ctk.CTkOptionMenu(
            row, values=["—"], command=self._on_pick, width=340, height=theme.HEIGHT_INPUT,
            corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL, fg_color=theme.BG_INPUT,
            button_color=theme.BORDER_STRONG, button_hover_color=theme.TEXT_MUTED,
            text_color=theme.TEXT_MAIN)
        self.opt_pedido.pack(side="left", padx=(0, theme.SPACE_2))
        self.lbl_count = ctk.CTkLabel(row, text="", font=theme.FONT_TINY,
                                      text_color=theme.TEXT_MUTED)
        self.lbl_count.pack(side="left")

        # ── Informe de estado (todo el ancho, scrollable) ───────────────
        self.detail = ScrollFrame(self)
        self.detail.pack(fill="both", expand=True, padx=theme.SPACE_6,
                         pady=(0, theme.SPACE_4))
        self._placeholder("Cargando pedidos…")

    def _placeholder(self, msg: str) -> None:
        for w in self.detail.winfo_children():
            w.destroy()
        box = ctk.CTkFrame(self.detail, fg_color="transparent")
        box.pack(expand=True, pady=90)
        ctk.CTkLabel(box, text="▦", font=theme.font(38, "bold"),
                     text_color=theme.BORDER_STRONG).pack()
        ctk.CTkLabel(box, text=msg, font=theme.FONT_BODY_BOLD,
                     text_color=theme.TEXT_SUB).pack(pady=(theme.SPACE_2, 0))
        ctk.CTkLabel(box, text="Elige un pedido para ver su estado: avance, plazo,\n"
                              "fabricación y los documentos que requieren acción.",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                     justify="center").pack(pady=(2, 0))

    # ── Carga del listado (para el buscador) ────────────────────────────────

    def _load_projects(self) -> None:
        def worker():
            try:
                data = erp_service.project_list()
                self.after(0, lambda: self._on_projects(data))
            except Exception as exc:
                logger.exception("Error proyectos")
                msg = str(exc)
                self.after(0, lambda: self._placeholder(f"✗  {msg}"))
        threading.Thread(target=worker, daemon=True).start()

    def _on_projects(self, data: list[dict]) -> None:
        self._projects = data
        self._update_matches()
        if data:
            self._placeholder("Elige un pedido")

    def _update_matches(self) -> None:
        q = self.ent_search.get().strip().lower()
        matches = self._projects if not q else [
            p for p in self._projects
            if q in str(p["pedido"]).lower() or q in str(p["cliente"]).lower()]
        self._label_to_pedido = {}
        labels = []
        for p in matches[:300]:
            lab = f"{p['pedido']}  ·  {p['cliente']}"
            labels.append(lab)
            self._label_to_pedido[lab] = p["pedido"]
        self.opt_pedido.configure(values=labels or ["— sin resultados —"])
        self.lbl_count.configure(text=f"{len(matches)} pedido(s)")
        if len(matches) == 1:
            self.opt_pedido.set(labels[0])
            self._on_pick(labels[0])

    @staticmethod
    def _base_pedido(p) -> str:
        """'P-26/048-S00' → 'P-26/048' (quita el sufijo de suministro)."""
        p = str(p or "").strip()
        return p[:-4] if len(p) > 4 and p[-4:-2].upper() == "-S" and p[-2:].isdigit() else p

    def select_pedido(self, pedido: str, _tries: int = 0) -> None:
        """Selecciona un pedido por su código (salto desde la paleta Ctrl+K).

        Tolera el sufijo -Sxx (la paleta pasa 'P-26/048-S00'; la lista de
        proyectos puede ir con o sin él). Los proyectos cargan en un hilo al
        abrir la vista: si aún no están, reintenta cada 300 ms (máx. ~12 s).
        """
        if not self._projects:
            if _tries < 40:
                self.after(300, lambda: self.select_pedido(pedido, _tries + 1))
            return
        base = self._base_pedido(pedido)
        self.ent_search.delete(0, "end")
        self.ent_search.insert(0, base)
        self._update_matches()          # con 1 match ya lo selecciona solo
        cur = self._pedido_current or ""
        if cur == pedido or self._base_pedido(cur) == base:
            return
        # Varios matches (-S00/-S01…): el exacto → el de mismo base → el primero
        labels = list(self._label_to_pedido)
        exact = [lab for lab in labels if self._label_to_pedido[lab] == pedido]
        same = [lab for lab in labels if self._base_pedido(self._label_to_pedido[lab]) == base]
        pick = (exact or same or labels)[:1]
        if pick:
            self.opt_pedido.set(pick[0])
            self._on_pick(pick[0])

    def _on_pick(self, label: str) -> None:
        pedido = self._label_to_pedido.get(label)
        if not pedido or pedido == self._pedido_current:
            return
        self._pedido_current = pedido
        self._tags_current = []
        self._show_loading(pedido)

        def worker():
            try:
                dash = erp_service.project_dashboard(pedido)
                bundle = erp_tags.fetch_pedido_bundle(pedido)   # equipos + OTs + cabecera (ERP)
                self.after(0, lambda: self._render_detail(pedido, dash, bundle))
            except Exception as exc:
                logger.exception("Error ficha pedido")
                msg = str(exc)
                self.after(0, lambda: self._placeholder(f"✗  {msg}"))
        threading.Thread(target=worker, daemon=True).start()

    def _show_loading(self, pedido: str) -> None:
        for w in self.detail.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.detail, text=f"⏳  Cargando {pedido}…", font=theme.FONT_BODY,
                     text_color=theme.TEXT_MUTED).pack(pady=60)

    # ════════════════════════════════════════════════════════════════════════
    #  INFORME DE ESTADO
    # ════════════════════════════════════════════════════════════════════════

    def _render_detail(self, pedido: str, dash: dict | None, bundle: dict | None = None) -> None:
        if pedido != self._pedido_current:
            return
        for w in self.detail.winfo_children():
            w.destroy()
        if not dash:
            ui.empty_state(self.detail, "Sin datos para este pedido.", icon="▦")
            return
        scroll = self.detail
        kpis = dash["kpis"]
        seg = dash.get("seguimiento") or {}
        consulta = dash.get("consulta") or {}
        docs = dash.get("documents") or []

        verdict = self._status_verdict(kpis, seg)
        self._dash = dash
        self._bundle = bundle or {}
        self._tags = self._bundle.get("tags") or []
        # Índice de documentos del pedido por Nº Doc. EIPSA Y por Nº Doc. Cliente:
        # el ERP guarda en calc/dwg_num_doc_eipsa unas veces el nº EIPSA y otras
        # el del cliente (p.ej. V-1065110910-0124 en TR). Así casa en ambos casos.
        self._doc_index = {}
        for d in docs:
            for key in ("Nº Doc. EIPSA", "Nº Doc. Cliente"):
                k = _norm_doc(d.get(key))
                if k and k not in self._doc_index:
                    self._doc_index[k] = d
        self._subview = "estado"

        self._build_header_card(scroll, pedido, dash, consulta, docs, kpis, verdict)

        # Conmutador (arriba): Estado del pedido  |  Equipos & Tags (subsección)
        n_tags = sum(1 for t in self._tags if t.get("_vigente", True))
        self._seg_sub = ctk.CTkSegmentedButton(
            scroll, values=["Estado del pedido",
                            f"Equipos & Tags ({n_tags})" if n_tags else "Equipos & Tags"],
            command=self._on_subview, height=theme.HEIGHT_BUTTON_SM,
            font=theme.FONT_SMALL_BOLD, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_CARD, selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER, unselected_color=theme.BG_CARD,
            unselected_hover_color=theme.BG_INPUT, text_color=theme.TEXT_MAIN)
        self._seg_sub.set("Estado del pedido")
        self._seg_sub.pack(anchor="center", pady=(0, theme.SPACE_3))

        self._body = ctk.CTkFrame(scroll, fg_color="transparent")
        self._body.pack(fill="both", expand=True)
        self._render_body()

    def _on_subview(self, value: str) -> None:
        self._subview = "tags" if value.startswith("Equipos") else "estado"
        self._render_body()

    def _render_body(self) -> None:
        body = getattr(self, "_body", None)
        if body is None:
            return
        for w in body.winfo_children():
            w.destroy()
        dash = self._dash or {}
        if self._subview == "tags":
            self._render_tags_block(body, self._tags)
            return
        # Estado del pedido: Fabricación (fases + OTs) → Documentación → Atención → Plazo
        self._build_fase_erp(body, dash.get("consulta") or {})
        self._build_ots_block(body, self._bundle)
        self._build_estado_documental(body, dash.get("kpis") or {},
                                      dash.get("avg_dias_respuesta", 0))
        self._build_atencion(body, dash.get("documents") or [])
        self._build_seguimiento_block(body, dash.get("seguimiento") or {})

    # ── Veredicto de estado ──────────────────────────────────────────────────

    def _status_verdict(self, kpis: dict, seg: dict) -> dict:
        total = kpis.get("total", 0)
        if total == 0:
            return {"label": "SIN DOCUMENTOS", "color": theme.TEXT_MUTED,
                    "reason": "Este pedido aún no tiene documentos registrados."}
        aprob = kpis.get("aprobados", 0)
        if aprob >= total:
            return {"label": "COMPLETADO", "color": theme.GREEN,
                    "reason": "Todos los documentos están aprobados."}
        c15 = kpis.get("criticos_15d", 0)
        if c15 > 0:
            return {"label": "EN RIESGO", "color": theme.RED,
                    "reason": f"{c15} documento(s) crítico(s) llevan +15 días sin respuesta del cliente."}
        if seg.get("en_plazo") is False:
            return {"label": "EN RIESGO", "color": theme.RED,
                    "reason": "Ritmo por debajo de lo previsto: el cierre estimado supera la fecha prevista."}
        dev = kpis.get("devoluciones", 0)
        if dev > 0:
            return {"label": "REQUIERE ACCIÓN", "color": theme.AMBER,
                    "reason": f"{dev} documento(s) devueltos con comentarios pendientes de resolver."}
        if aprob == 0 and kpis.get("enviados", 0) == 0:
            return {"label": "SIN INICIAR", "color": theme.TEXT_MUTED,
                    "reason": "Documentación creada pero aún sin enviar al cliente."}
        return {"label": "EN CURSO", "color": theme.ACCENT,
                "reason": f"{kpis.get('pct_completado', 0)}% aprobado · "
                          f"{kpis.get('enviados', 0)} pendiente(s) de revisión del cliente."}

    # ── 1) Cabecera: identidad + veredicto + % ───────────────────────────────

    def _build_header_card(self, parent, pedido, dash, consulta, docs, kpis, verdict) -> None:
        cli = dash.get("cliente", "") or consulta.get("Cliente", "")
        first = docs[0] if docs else {}
        po = str(first.get("Nº PO", "") or "").strip()
        material = str(first.get("Material", "") or consulta.get("Tipo Equipo", "") or "").strip()
        proyecto = str(consulta.get("Proyecto", "") or "").strip()
        comercial = str(consulta.get("Responsable", "") or "").strip()
        oferta = str(consulta.get("Nº Oferta", "") or "").strip()
        nequipos = str(consulta.get("Nº Equipos", "") or "").strip()
        f_ped = _fmt(consulta.get("Fecha Pedido"))
        f_prev = _fmt(consulta.get("Fecha Prevista"))

        card = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=12,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, theme.SPACE_2))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_2)

        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")

        # Izquierda: identidad
        left = ctk.CTkFrame(top, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        title = ctk.CTkFrame(left, fg_color="transparent")
        title.pack(anchor="w")
        ctk.CTkLabel(title, text=pedido, font=theme.font(22, "bold"),
                     text_color=theme.TEXT_MAIN).pack(side="left")
        if cli:
            ctk.CTkLabel(title, text=cli, font=theme.FONT_BODY_BOLD,
                         text_color=theme.TEXT_SUB).pack(side="left", padx=(theme.SPACE_3, 0))
        if proyecto:
            ctk.CTkLabel(left, text=proyecto, font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                         anchor="w", justify="left", wraplength=560).pack(anchor="w", pady=(2, 0))

        # Derecha: veredicto
        right = ctk.CTkFrame(top, fg_color="transparent")
        right.pack(side="right", padx=(theme.SPACE_3, 0))
        col = verdict["color"]
        ctk.CTkLabel(right, text=f"  {verdict['label']}  ", font=theme.font(13, "bold"),
                     text_color=theme.TEXT_ON_ACCENT if col != theme.TEXT_MUTED else theme.TEXT_MAIN,
                     fg_color=col, corner_radius=8, height=30).pack(anchor="e")
        ctk.CTkLabel(right, text=verdict["reason"], font=theme.FONT_TINY,
                     text_color=theme.TEXT_SUB, anchor="e", justify="right",
                     wraplength=300).pack(anchor="e", pady=(theme.SPACE_1, 0))

        # Datos del pedido — grid claro y bien distribuido (etiqueta + valor)
        fields = []
        if po: fields.append(("PO", po))
        if material: fields.append(("Material", material))
        if nequipos: fields.append(("Nº equipos", nequipos))
        if comercial: fields.append(("Comercial", comercial))
        if oferta: fields.append(("Nº oferta", oferta))
        if f_ped != "—": fields.append(("Fecha pedido", f_ped))
        if f_prev != "—": fields.append(("Fecha prevista", f_prev))
        # Seguimiento del ERP (taller, entrega, material, aval) — solo lo informado
        hdr = (getattr(self, "_bundle", {}) or {}).get("header") or {}
        for lab in ("Prev. taller", "Recep. taller", "Aviso entrega",
                    "Material disponible", "Aval", "Cerrado"):
            val = str(hdr.get(lab, "") or "").strip()
            if val:
                fields.append((lab, val))
        if fields:
            ctk.CTkFrame(inner, fg_color=theme.BORDER, height=1).pack(fill="x", pady=theme.SPACE_2)
            ginfo = ctk.CTkFrame(inner, fg_color="transparent")
            ginfo.pack(fill="x")
            ncols = 4
            for c in range(ncols):
                ginfo.grid_columnconfigure(c, weight=1, uniform="idf")
            for i, (lab, val) in enumerate(fields):
                self._info_item(ginfo, lab, val, i // ncols, i % ncols)

        # Progreso (% aprobado)
        ctk.CTkFrame(inner, fg_color=theme.BORDER, height=1).pack(fill="x", pady=theme.SPACE_2)
        prow = ctk.CTkFrame(inner, fg_color="transparent")
        prow.pack(fill="x")
        ctk.CTkLabel(prow, text="Progreso documental", font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN).pack(side="left")
        pct = kpis.get("pct_completado", 0)
        ctk.CTkLabel(prow, text=f"{pct}% aprobado", font=theme.FONT_SMALL_BOLD,
                     text_color=theme.GREEN).pack(side="right")
        pbar = ctk.CTkProgressBar(inner, height=10, corner_radius=5,
                                  progress_color=theme.GREEN, fg_color=theme.BORDER)
        pbar.pack(fill="x", pady=(theme.SPACE_2, 0))
        pbar.set(min(pct, 100) / 100)

        # Acción: generar el informe web completo de este pedido
        ctk.CTkFrame(inner, fg_color=theme.BORDER, height=1).pack(fill="x", pady=theme.SPACE_2)
        actions = ctk.CTkFrame(inner, fg_color="transparent")
        actions.pack(fill="x", pady=(0, theme.SPACE_1))
        ctk.CTkLabel(actions, text="Informe web completo: ficha, KPIs, predicción y tabla de toda la documentación.",
                     font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w").pack(
            side="left", fill="x", expand=True)
        btn = ui.button(actions, "Informe del pedido  →", "primary", size="xs",
                        corner_radius=theme.RADIUS_MD)
        btn.configure(command=lambda p=pedido, b=btn: self._generate_pedido_report(p, b))
        btn.pack(side="right")

    # ── Informe del pedido (HTML interactivo) ────────────────────────────────

    def _generate_pedido_report(self, pedido: str, btn=None) -> None:
        if btn is not None:
            btn.configure(state="disabled", text="Generando…")

        def worker():
            try:
                from core.services import interactive_report as ir
                path, _ = ir.generate_pedido(pedido)
                self.after(0, lambda: self._pedido_report_done(path, btn))
            except Exception as exc:
                logger.exception("Error generando informe del pedido")
                msg = str(exc)
                self.after(0, lambda: self._pedido_report_fail(msg, btn))

        threading.Thread(target=worker, daemon=True).start()

    def _restore_report_btn(self, btn) -> None:
        if btn is not None and btn.winfo_exists():
            btn.configure(state="normal", text="Informe del pedido  →")

    def _pedido_report_done(self, path, btn) -> None:
        import webbrowser
        try:
            webbrowser.open(path.as_uri())
        except Exception:
            logger.debug("No se pudo abrir el navegador", exc_info=True)
        ui.toast(self, "Informe listo", path.name, kind="success")
        self._restore_report_btn(btn)

    def _pedido_report_fail(self, msg, btn) -> None:
        ui.toast(self, "No se pudo generar el informe", msg, kind="info")
        self._restore_report_btn(btn)

    # ── 2) Estado de la documentación: barra segmentada ──────────────────────

    def _build_estado_documental(self, parent, kpis: dict, avg_dias) -> None:
        _section_header(parent, "Estado de la documentación").pack(fill="x", pady=(0, theme.SPACE_2))
        total = max(kpis.get("total", 0), 1)
        segs = [
            ("Aprobados", kpis.get("aprobados", 0), theme.GREEN),
            ("Enviados (pend. cliente)", kpis.get("enviados", 0), theme.BLUE),
            ("Devoluciones", kpis.get("devoluciones", 0), theme.AMBER),
            ("Sin enviar", kpis.get("sin_enviar", 0), theme.TEXT_MUTED),
        ]
        card = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, theme.SPACE_3))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_3)

        # Barra segmentada
        track = ctk.CTkFrame(inner, fg_color=theme.BORDER, height=14, corner_radius=7)
        track.pack(fill="x", pady=(0, theme.SPACE_2))
        x = 0.0
        for _, count, color in segs:
            if count <= 0:
                continue
            w = count / total
            seg = ctk.CTkFrame(track, fg_color=color, corner_radius=0)
            seg.place(relx=min(x, 0.999), rely=0, relheight=1, relwidth=min(w, 1 - x))
            x += w

        # Leyenda con conteos
        leg = ctk.CTkFrame(inner, fg_color="transparent")
        leg.pack(fill="x")
        for label, count, color in segs:
            chip = ctk.CTkFrame(leg, fg_color="transparent")
            chip.pack(side="left", padx=(0, theme.SPACE_4))
            ctk.CTkFrame(chip, fg_color=color, width=10, height=10, corner_radius=2).pack(side="left")
            ctk.CTkLabel(chip, text=f" {label}: ", font=theme.FONT_TINY,
                         text_color=theme.TEXT_SUB).pack(side="left")
            ctk.CTkLabel(chip, text=str(count), font=theme.FONT_SMALL_BOLD,
                         text_color=theme.TEXT_MAIN).pack(side="left")
        ctk.CTkLabel(leg, text=f"{kpis.get('total', 0)} docs · {avg_dias} días resp. media",
                     font=theme.FONT_TINY, text_color=theme.TEXT_MUTED).pack(side="right")

    # ── 3) Requiere atención: lo accionable (sin la tabla completa) ──────────

    def _build_atencion(self, parent, docs: list[dict]) -> None:
        _section_header(parent, "Requiere atención").pack(fill="x", pady=(0, theme.SPACE_2))

        items = []
        for d in docs:
            est = str(d.get("Estado", "") or "").lower().strip()
            if "aprobado" in est:
                continue
            crit = str(d.get("Crítico", "") or "").lower().strip() in ("sí", "si")
            dd = _to_int(d.get("Días Devolución"))
            is_dev = any(s in est for s in ("com.", "comentado", "menores", "mayores", "rechaz"))
            atrasado = (est == "enviado" and dd >= 15)
            if not (crit or is_dev or atrasado):
                continue
            score = (2 if (crit and dd >= 15) else 0) + (1 if crit else 0) + (1 if is_dev else 0)
            items.append((score, dd, crit, d))

        card = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, theme.SPACE_3))

        if not items:
            ctk.CTkLabel(card, text="✓  Sin acciones pendientes — nada crítico, devuelto ni atrasado.",
                         font=theme.FONT_SMALL, text_color=theme.GREEN, anchor="w").pack(
                fill="x", padx=theme.SPACE_4, pady=theme.SPACE_3)
        else:
            items.sort(key=lambda x: (x[0], x[1]), reverse=True)
            body = ctk.CTkFrame(card, fg_color="transparent")
            body.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_2, 0))
            for score, dd, crit, d in items[:6]:
                estado = str(d.get("Estado", "") or "Sin enviar")
                ecol = _status_color(estado)
                r = ctk.CTkFrame(body, fg_color="transparent")
                r.pack(fill="x", pady=2)
                ctk.CTkLabel(r, text="⚠" if crit else "•", font=theme.FONT_SMALL,
                             text_color=theme.RED if crit else theme.TEXT_MUTED, width=16).pack(side="left")
                ctk.CTkLabel(r, text=_fmt(d.get("Nº Doc. EIPSA")), font=theme.FONT_SMALL_BOLD,
                             text_color=theme.ACCENT, width=150, anchor="w").pack(side="left")
                ctk.CTkLabel(r, text=_trunc(d.get("Título"), 46), font=theme.FONT_SMALL,
                             text_color=theme.TEXT_MAIN, anchor="w").pack(side="left", fill="x", expand=True)
                dcol = theme.RED if dd >= 15 else theme.TEXT_MUTED
                ctk.CTkLabel(r, text=(f"{dd} d" if dd > 0 else "—"), font=theme.FONT_SMALL_BOLD,
                             text_color=dcol, width=44).pack(side="right")
                ctk.CTkLabel(r, text=f" {estado} ", font=theme.FONT_TINY, text_color=ecol,
                             fg_color=ui.blend(ecol, theme.BG_CARD, 0.20), corner_radius=7,
                             height=20).pack(side="right", padx=(0, theme.SPACE_2))

        # Pie: aviso + botón que salta a Documentos filtrando este pedido
        rest = len(items) - 6
        hint = (f"+ {rest} más · " if rest > 0 else "") + "Documentación completa en la sección Documentos."
        foot = ctk.CTkFrame(card, fg_color="transparent")
        foot.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_2, theme.SPACE_3))
        ctk.CTkLabel(foot, text=hint, font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                     anchor="w").pack(side="left", fill="x", expand=True)
        if self._on_open_documentos and self._pedido_current:
            ui.button(foot, "Ver en Documentos  →", "primary", size="xs", corner_radius=theme.RADIUS_MD,
                      command=lambda p=self._pedido_current: self._on_open_documentos(p)).pack(side="right")

    # ── 4) Plazo · Curva-S (conciso) ─────────────────────────────────────────

    def _build_seguimiento_block(self, parent, seg: dict) -> None:
        if not seg or not seg.get("total"):
            return
        _section_header(parent, "Plazo · Curva-S").pack(fill="x", pady=(0, theme.SPACE_2))
        card = ctk.CTkFrame(parent, fg_color=theme.BG_PAGE, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, theme.SPACE_3))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_3)

        pct = seg.get("pct", 0)
        pct_esp = seg.get("pct_esperado")

        ctk.CTkLabel(inner, text="Avance real vs. esperado", font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN).pack(anchor="w")
        track = ctk.CTkFrame(inner, fg_color=theme.BORDER, height=12, corner_radius=6)
        track.pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_1))
        if pct_esp is not None:
            exp = ctk.CTkFrame(track, fg_color=theme.TEXT_MUTED, corner_radius=6)
            exp.place(relx=0, rely=0, relheight=1, relwidth=max(0.01, min(1.0, pct_esp / 100)))
        real = ctk.CTkFrame(track, fg_color=theme.ACCENT, corner_radius=6)
        real.place(relx=0, rely=0, relheight=1, relwidth=max(0.01, min(1.0, pct / 100)))

        leg = ctk.CTkFrame(inner, fg_color="transparent")
        leg.pack(fill="x", pady=(0, theme.SPACE_2))
        for txt, col in (("Real", theme.ACCENT), ("Esperado", theme.TEXT_MUTED)):
            chip = ctk.CTkFrame(leg, fg_color="transparent")
            chip.pack(side="left", padx=(0, theme.SPACE_3))
            ctk.CTkFrame(chip, fg_color=col, width=10, height=10, corner_radius=2).pack(side="left")
            ctk.CTkLabel(chip, text=txt, font=theme.FONT_TINY, text_color=theme.TEXT_MUTED).pack(
                side="left", padx=(4, 0))

        desv = (pct - pct_esp) if pct_esp is not None else None
        en_plazo = seg.get("en_plazo")
        chips = [
            ("% Real", f"{pct}%", theme.ACCENT),
            ("% Esperado", f"{pct_esp}%" if pct_esp is not None else "—", theme.TEXT_SUB),
            ("Desviación", (f"+{desv}pp" if (desv is not None and desv >= 0)
                            else (f"{desv}pp" if desv is not None else "—")),
             (theme.GREEN if (desv is not None and desv >= 0) else theme.RED)
             if desv is not None else theme.TEXT_MUTED),
            ("Fecha prevista", seg.get("fecha_prevista") or "—", theme.TEXT_SUB),
            ("Cierre estimado", seg.get("prediccion_fecha") or "—",
             theme.GREEN if en_plazo is True else (theme.RED if en_plazo is False else theme.TEXT_SUB)),
        ]
        grid = ctk.CTkFrame(inner, fg_color="transparent")
        grid.pack(fill="x")
        ncols = 3
        for c in range(ncols):
            grid.grid_columnconfigure(c, weight=1, uniform="seg")
        for i, (label, val, col) in enumerate(chips):
            cell = ctk.CTkFrame(grid, fg_color=theme.BG_CARD, corner_radius=8,
                                border_width=1, border_color=theme.BORDER)
            cell.grid(row=i // ncols, column=i % ncols, sticky="ew",
                      padx=(0 if i % ncols == 0 else theme.SPACE_2, 0), pady=(0, theme.SPACE_2))
            ctk.CTkLabel(cell, text=label.upper(), font=theme.FONT_TINY,
                         text_color=theme.TEXT_MUTED).pack(anchor="w", padx=theme.SPACE_2,
                                                           pady=(theme.SPACE_1, 0))
            ctk.CTkLabel(cell, text=str(val), font=theme.FONT_SMALL_BOLD,
                         text_color=col).pack(anchor="w", padx=theme.SPACE_2, pady=(0, theme.SPACE_1))

    # ── 5) Fabricación (fases del ERP) ───────────────────────────────────────

    def _build_fase_erp(self, parent, consulta: dict) -> None:
        _section_header(parent, "Fabricación").pack(fill="x", pady=(0, theme.SPACE_2))
        if not consulta:
            ctk.CTkLabel(parent, text="Este pedido no figura en consulta_erp.xlsx.",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                         anchor="w").pack(fill="x", pady=(0, theme.SPACE_3))
            return
        card = ctk.CTkFrame(parent, fg_color=theme.BG_PAGE, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, theme.SPACE_3))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_3)

        phases = erp_service.consulta_phases(consulta)
        prow = ctk.CTkFrame(inner, fg_color="transparent")
        prow.pack(fill="x")
        prow.grid_rowconfigure(0, weight=1)
        for c in range(3):
            prow.grid_columnconfigure(c, weight=1, uniform="phase")
        for i, ph in enumerate(phases):
            self._phase_card(prow, ph, 0, i)

        notas = str(consulta.get("Notas Pedido", "") or "")
        if notas:
            nbox = ctk.CTkFrame(inner, fg_color=theme.BG_CARD, corner_radius=8)
            nbox.pack(fill="x", pady=(theme.SPACE_3, 0))
            ctk.CTkLabel(nbox, text="NOTAS", font=theme.FONT_LABEL, text_color=theme.TEXT_MUTED,
                         anchor="w").pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_2, 0))
            ctk.CTkLabel(nbox, text=notas, font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                         anchor="w", justify="left", wraplength=820).pack(
                fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_2))

    # ── 5b) Fabricación por equipo: órdenes de trabajo del ERP ───────────────

    def _build_ots_block(self, parent, bundle: dict) -> None:
        if not bundle:
            return
        if not bundle.get("available"):
            ctk.CTkLabel(parent, text="ERP no disponible: sin equipos ni órdenes de fabricación "
                                      "(se leen del PostgreSQL local del ERP).",
                         font=theme.FONT_SMALL, text_color=theme.AMBER, anchor="w").pack(
                fill="x", pady=(0, theme.SPACE_3))
            return
        fab = bundle.get("fab_orders") or []
        tags = [t for t in (bundle.get("tags") or [])
                if t.get("_vigente", True) and not t.get("_eliminado")]
        if not fab and not tags:
            return
        _section_header(parent, "Fabricación por equipo · órdenes de trabajo").pack(
            fill="x", pady=(0, theme.SPACE_2))
        card = ctk.CTkFrame(parent, fg_color=theme.BG_PAGE, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, theme.SPACE_3))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_3)

        fabricados = sum(1 for t in tags if t.get("Estado Fab.", "").upper() == "FABRICADO")
        con_plano = sum(1 for t in tags if t.get("Plano Dim."))
        abiertas = [o for o in fab if not o["terminada"]]
        cerradas = len(fab) - len(abiertas)
        n = len(tags)
        chips = [
            ("Equipos", str(n), theme.TEXT_MAIN),
            ("Fabricados", f"{fabricados}/{n}" if n else "—",
             theme.GREEN if n and fabricados == n else (theme.AMBER if fabricados else theme.TEXT_SUB)),
            ("Con plano dim.", f"{con_plano}/{n}" if n else "—", theme.TEXT_SUB),
            ("OTs en curso", str(len(abiertas)), theme.AMBER if abiertas else theme.TEXT_SUB),
            ("OTs terminadas", f"{cerradas}/{len(fab)}" if fab else "—",
             theme.GREEN if fab and cerradas == len(fab) else theme.TEXT_SUB),
        ]
        grid = ctk.CTkFrame(inner, fg_color="transparent")
        grid.pack(fill="x")
        for c in range(len(chips)):
            grid.grid_columnconfigure(c, weight=1, uniform="ot")
        for i, (label, val, col) in enumerate(chips):
            cell = ctk.CTkFrame(grid, fg_color=theme.BG_CARD, corner_radius=8,
                                border_width=1, border_color=theme.BORDER)
            cell.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else theme.SPACE_2, 0))
            ctk.CTkLabel(cell, text=label.upper(), font=theme.FONT_TINY,
                         text_color=theme.TEXT_MUTED).pack(anchor="w", padx=theme.SPACE_2,
                                                           pady=(theme.SPACE_1, 0))
            ctk.CTkLabel(cell, text=val, font=theme.FONT_SMALL_BOLD,
                         text_color=col).pack(anchor="w", padx=theme.SPACE_2, pady=(0, theme.SPACE_1))

        # Qué está en taller ahora mismo (OTs abiertas, las más antiguas primero)
        if abiertas:
            body = ctk.CTkFrame(inner, fg_color="transparent")
            body.pack(fill="x", pady=(theme.SPACE_2, 0))
            for o in abiertas[:8]:
                r = ctk.CTkFrame(body, fg_color="transparent")
                r.pack(fill="x", pady=1)
                ctk.CTkLabel(r, text="•", font=theme.FONT_SMALL, text_color=theme.AMBER,
                             width=14).pack(side="left")
                ctk.CTkLabel(r, text=f"OT {o['ot']}", font=theme.FONT_SMALL_BOLD,
                             text_color=theme.ACCENT, width=90, anchor="w").pack(side="left")
                key = o["tag_key"]
                equipo = key.split("-", 4)[-1] if key.count("-") >= 4 else "Pedido"
                what = " · ".join(x for x in (equipo, o["plano"], o["elemento"]) if x)
                ctk.CTkLabel(r, text=_trunc(what, 70), font=theme.FONT_SMALL,
                             text_color=theme.TEXT_MAIN, anchor="w").pack(side="left", fill="x", expand=True)
                ctk.CTkLabel(r, text=f"desde {o['inicio']}" if o["inicio"] else "sin fecha",
                             font=theme.FONT_TINY, text_color=theme.TEXT_MUTED).pack(side="right")
            if len(abiertas) > 8:
                ctk.CTkLabel(inner, text=f"+ {len(abiertas) - 8} OTs más en curso · "
                                         "detalle por equipo en «Equipos & Tags»",
                             font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w").pack(
                    fill="x", pady=(theme.SPACE_1, 0))

    def _info_item(self, parent, label, value, r, c) -> None:
        cell = ctk.CTkFrame(parent, fg_color="transparent")
        cell.grid(row=r, column=c, sticky="ew", padx=(0, theme.SPACE_3), pady=theme.SPACE_1)
        ctk.CTkLabel(cell, text=str(label).upper(), font=theme.FONT_LABEL,
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        ctk.CTkLabel(cell, text=str(value) if value not in ("", None) else "—",
                     font=theme.FONT_BODY_BOLD, text_color=theme.TEXT_MAIN,
                     anchor="w").pack(anchor="w")

    def _phase_card(self, parent, ph: dict, r, c) -> None:
        color = _phase_color(ph["pct"])
        box = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=8,
                           border_width=1, border_color=theme.BORDER)
        box.grid(row=r, column=c, sticky="nsew", padx=(0 if c == 0 else theme.SPACE_2, 0))
        top = ctk.CTkFrame(box, fg_color="transparent")
        top.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_2, theme.SPACE_2))
        ctk.CTkLabel(top, text=ph["title"], font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN).pack(side="left")
        date = (ph["date"] or "")[:10]
        if date:
            ctk.CTkLabel(top, text=date, font=theme.FONT_TINY,
                         text_color=theme.TEXT_MUTED).pack(side="right")
        barrow = ctk.CTkFrame(box, fg_color="transparent")
        barrow.pack(fill="x", padx=theme.SPACE_3)
        prog = ctk.CTkProgressBar(barrow, height=8, corner_radius=4,
                                  progress_color=color, fg_color=theme.BORDER)
        prog.pack(side="left", fill="x", expand=True, pady=2)
        prog.set(min(ph["pct"], 100) / 100)
        ctk.CTkLabel(barrow, text=f"{ph['pct']}%", font=theme.FONT_SMALL_BOLD,
                     text_color=color, width=44).pack(side="right", padx=(theme.SPACE_2, 0))
        obs = str(ph["obs"] or "").strip()
        if len(obs) > 130:
            obs = obs[:130].rstrip() + "…"
        ctk.CTkLabel(box, text=obs or " ", font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                     anchor="nw", justify="left", wraplength=210).pack(
            fill="both", expand=True, padx=theme.SPACE_3, pady=(theme.SPACE_2, theme.SPACE_2))

    # ── 6) Equipos & Tags (resumen + tabla compacta) ─────────────────────────

    def _render_tags_block(self, parent, tags: list[dict]) -> None:
        _section_header(parent, "Equipos & Tags").pack(fill="x", pady=(0, theme.SPACE_2))
        bundle = getattr(self, "_bundle", {}) or {}
        if not bundle.get("available", True) and not tags:
            ui.empty_state(parent, "ERP no disponible",
                           hint="Los equipos se leen del ERP (PostgreSQL local). Ábrelo y vuelve a intentarlo.",
                           icon="▦", pady=30)
            return
        if not tags:
            ui.empty_state(parent, "Este pedido no tiene equipos registrados en el ERP.",
                           icon="▦", pady=30)
            return
        self._tags_current = tags

        # KPIs del bloque (solo revisiones vigentes, sin eliminados)
        activos = [t for t in tags if t.get("_vigente", True) and not t.get("_eliminado")]
        n = len(activos)
        fabricados = sum(1 for t in activos if t.get("Estado Fab.", "").upper() == "FABRICADO")
        con_plano = sum(1 for t in activos if t.get("Plano Dim."))
        ots_abiertas = sum(t.get("_ot_abiertas", 0) for t in activos)
        docs_ok, docs_tot = self._docs_progress(activos)
        familias = Counter(t.get("Familia", "") for t in activos)
        summ = ctk.CTkFrame(parent, fg_color="transparent")
        summ.pack(fill="x", pady=(0, theme.SPACE_1))
        ctk.CTkLabel(summ, text=f"{n} equipos", font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN).pack(side="left", padx=(0, theme.SPACE_3))
        for txt, col in (
            (f"Fabricados {fabricados}/{n}", theme.GREEN if n and fabricados == n else theme.AMBER),
            (f"Con plano {con_plano}/{n}", theme.TEXT_SUB),
            (f"OTs en curso {ots_abiertas}", theme.AMBER if ots_abiertas else theme.TEXT_SUB),
            (f"Docs aprobados {docs_ok}/{docs_tot}" if docs_tot else "Sin docs enlazados",
             theme.GREEN if docs_tot and docs_ok == docs_tot else theme.TEXT_SUB),
        ):
            ui.badge(summ, txt, col).pack(side="left", padx=(0, theme.SPACE_1))
        if len(familias) > 1:
            ctk.CTkLabel(summ, text="  ·  " + " · ".join(f"{f} {c}" for f, c in familias.most_common()),
                         font=theme.FONT_TINY, text_color=theme.TEXT_MUTED).pack(side="left")

        # Toolbar: búsqueda + familia + estado de fabricación
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", pady=(theme.SPACE_1, theme.SPACE_1))
        self._tags_search = ctk.CTkEntry(
            toolbar, placeholder_text="Buscar TAG, tipo, tamaño, plano, documento…",
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD, fg_color=theme.BG_INPUT,
            border_color=theme.BORDER, text_color=theme.TEXT_MAIN, font=theme.FONT_SMALL)
        self._tags_search.pack(side="left", fill="x", expand=True, padx=(0, theme.SPACE_2))
        self._tags_search.bind("<KeyRelease>", lambda e: self._populate_tags_table())
        opt_kw = dict(height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL,
                      fg_color=theme.BG_INPUT, button_color=theme.BORDER_STRONG,
                      button_hover_color=theme.TEXT_MUTED, text_color=theme.TEXT_MAIN,
                      command=lambda _v: self._populate_tags_table())
        self._tags_familia = ctk.CTkOptionMenu(
            toolbar, values=["Todas"] + [f for f, _ in familias.most_common()], width=140, **opt_kw)
        self._tags_familia.set("Todas")
        self._tags_familia.pack(side="left", padx=(0, theme.SPACE_2))
        self._tags_estado = ctk.CTkOptionMenu(
            toolbar, values=["Todos", "Fabricado", "Pendiente", "Eliminado"], width=140, **opt_kw)
        self._tags_estado.set("Todos")
        self._tags_estado.pack(side="left", padx=(0, theme.SPACE_2))
        # Revisiones superadas (tag_state SUPERADO): ocultas por defecto
        self._tags_superados = ctk.BooleanVar(value=False)
        n_sup = sum(1 for t in tags if not t.get("_vigente", True))
        if n_sup:
            ctk.CTkCheckBox(toolbar, text=f"Incluir superados ({n_sup})",
                            variable=self._tags_superados, font=theme.FONT_TINY,
                            text_color=theme.TEXT_SUB, checkbox_width=18, checkbox_height=18,
                            command=self._populate_tags_table).pack(side="left", padx=(0, theme.SPACE_2))
        self._tags_count = ctk.CTkLabel(toolbar, text="", font=theme.FONT_TINY,
                                        text_color=theme.TEXT_MUTED)
        self._tags_count.pack(side="left")

        ctk.CTkLabel(parent, text="doble-click en un equipo: ficha completa, documentación "
                                  "enlazada y órdenes de fabricación",
                     font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w").pack(
            fill="x", pady=(0, theme.SPACE_1))

        h = min(max(len(tags), 4), 16) * 32 + 60
        host = ctk.CTkFrame(parent, fg_color="transparent", height=h)
        host.pack(fill="x", pady=(0, theme.SPACE_3))
        host.pack_propagate(False)
        self._tags_table = DataTable(
            host, columns=erp_service.TAGS_SUMMARY_COLUMNS,
            on_double_click=lambda _i: self._open_tag_detail(self._tags_table))
        self._tags_table.pack(fill="both", expand=True)
        self._tags_table.set_columns_anchor({
            "Familia": "w", "TAG": "w", "Tipo": "w", "Tamaño": "center", "Rating": "center",
            "Facing": "center", "Estado": "center", "Fab.": "center", "Insp.": "center",
            "Plano Dim.": "w", "OTs": "center", "Docs": "w"})
        self._populate_tags_table()

    # Símbolo por estado documental (docs enlazados a un equipo)
    _DOC_SYM = (("aprobado", "✓"), ("rechaz", "✕"), ("com", "⚠"), ("enviado", "⏳"))

    def _doc_state(self, num: str) -> tuple[str, str, str]:
        """(símbolo, estado, Nº Doc. EIPSA) del documento `num` —nº EIPSA o del
        cliente— según Documentos; ('?', '', '') si no figura."""
        d = (self._doc_index or {}).get(_norm_doc(num))
        if not d:
            return "?", "", ""
        eipsa = str(d.get("Nº Doc. EIPSA", "") or "").strip()
        est = str(d.get("Estado", "") or "").strip()
        low = est.lower()
        for key, sym in self._DOC_SYM:
            if key in low:
                return sym, est, eipsa
        return "○", est or "Sin enviar", eipsa

    def _docs_cell(self, t: dict) -> str:
        parts = []
        for lab, num in (("CAL", t.get("Doc EIPSA Calc.", "")), ("PLG", t.get("Doc EIPSA Plano", ""))):
            if num:
                parts.append(f"{lab} {self._doc_state(num)[0]}")
        return "  ".join(parts)

    def _docs_progress(self, tags: list[dict]) -> tuple[int, int]:
        """(aprobados, total) de los documentos enlazados a los equipos (sin repetir)."""
        ok = tot = 0
        seen: set[str] = set()
        for t in tags:
            for num in (t.get("Doc EIPSA Calc.", ""), t.get("Doc EIPSA Plano", "")):
                if not num or num in seen:
                    continue
                seen.add(num)
                sym = self._doc_state(num)[0]
                if sym == "?":
                    continue
                tot += 1
                ok += sym == "✓"
        return ok, tot

    @staticmethod
    def _fab_cell(t: dict) -> str:
        if t.get("_eliminado"):
            return "✕ Eliminado"
        return "✓ Fabricado" if t.get("Estado Fab.", "").upper() == "FABRICADO" else "—"

    def _populate_tags_table(self) -> None:
        """Rellena la tabla aplicando búsqueda + familia + estado de fabricación.

        El iid de cada fila conserva el índice en self._tags_current para que el
        doble-click abra el equipo correcto aunque la lista esté filtrada.
        """
        table = getattr(self, "_tags_table", None)
        if table is None:
            return
        q = self._tags_search.get().strip().lower()
        familia = self._tags_familia.get()
        estado = self._tags_estado.get()
        superados = bool(self._tags_superados.get())
        table.clear()
        shown = total = 0
        for idx, t in enumerate(self._tags_current):
            if not t.get("_vigente", True) and not superados:
                continue
            total += 1
            if familia != "Todas" and t.get("Familia") != familia:
                continue
            fab = "Eliminado" if t.get("_eliminado") else (
                "Fabricado" if t.get("Estado Fab.", "").upper() == "FABRICADO" else "Pendiente")
            if estado != "Todos" and fab != estado:
                continue
            if q and not any(q in str(v).lower() for k, v in t.items() if not k.startswith("_")):
                continue
            plano = t.get("Plano Dim.", "")
            if plano and t.get("Rev. Plano Dim."):
                plano = f"{plano}  r{t['Rev. Plano Dim.']}"
            table.add_row(values=[
                t.get("Familia", ""), t.get("TAG", ""), t.get("Tipo", ""), t.get("Tamaño", ""),
                t.get("Rating", ""), t.get("Facing", ""), t.get("Estado", ""), self._fab_cell(t),
                t.get("Inspección", ""), plano, t.get("OTs", ""), self._docs_cell(t),
            ], iid=f"tag_{idx}")
            shown += 1
        self._tags_table.autofit_columns(max_per={"Tipo": 170, "TAG": 150, "Plano Dim.": 160, "Docs": 120})
        self._tags_count.configure(text=f"{shown} / {total} equipos")

    # ── Detalle de un TAG ───────────────────────────────────────────────────

    def _open_tag_detail(self, table) -> None:
        iid = table.selected_iid()
        if not iid or not iid.startswith("tag_"):
            return
        try:
            tag = self._tags_current[int(iid.split("_", 1)[1])]
        except (ValueError, IndexError):
            return
        TagDetailWindow(self, tag, doc_state=self._doc_state,
                        on_open_documento=self._on_open_documento)


# ════════════════════════════════════════════════════════════════════════════
#  Ficha de un equipo (modal): documentación enlazada · OTs · campos del ERP
# ════════════════════════════════════════════════════════════════════════════

class TagDetailWindow(ctk.CTkToplevel):
    # Claves de resumen que no se repiten en las secciones
    _SKIP = {"TAG", "Nº Pedido", "Familia", "Tamaño", "OTs", "Docs"}

    def __init__(self, master, tag: dict, doc_state=None, on_open_documento=None):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self._doc_state = doc_state or (lambda _n: ("?", "", ""))
        self._on_open_documento = on_open_documento
        self.title(f"Equipo  ·  {tag.get('TAG', '—')}")
        self.geometry("860x740")
        self.minsize(560, 480)
        self.transient(master)
        self.grab_set()
        self._build(tag)

    def _build(self, tag: dict) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(18, 6))
        ctk.CTkLabel(header, text=str(tag.get("TAG", "—")), font=theme.font(18, "bold"),
                     text_color=theme.ACCENT, anchor="w").pack(anchor="w")
        sub = " · ".join(str(tag.get(k, "")) for k in ("Familia", "Tipo", "Nº Pedido", "Estado")
                         if str(tag.get(k, "") or ""))
        ctk.CTkLabel(header, text=sub, font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB, anchor="w").pack(anchor="w", pady=(2, 0))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=22, pady=(0, 14))
        ui.button(footer, "Cerrar", "secondary", size="lg", command=self.destroy).pack(side="right")

        scroll = ScrollFrame(self, fg_color=theme.BG_CARD)
        scroll.pack(side="top", fill="both", expand=True, padx=22, pady=(8, 12))

        self._docs_block(scroll, tag)
        self._ots_block(scroll, tag)

        shown: set[str] = set(self._SKIP)
        for title, keys in erp_service.TAGS_DETAIL_SECTIONS:
            visibles = [(k, tag.get(k, "")) for k in keys
                        if str(tag.get(k, "") or "").strip() not in ("", "0", "0.0", "—")]
            shown.update(keys)
            if visibles:
                self._section(scroll, title, visibles)
        # Resto de campos con etiqueta (temperatura / nivel / otros)
        rest = [(k, v) for k, v in tag.items()
                if not k.startswith("_") and k not in shown
                and str(v or "").strip() not in ("", "0", "0.0", "—")]
        if rest:
            self._section(scroll, "Otros datos del equipo", rest)

    def _section(self, scroll, title: str, items: list) -> None:
        _section_header(scroll, title).pack(fill="x", padx=14, pady=(theme.SPACE_3, theme.SPACE_1))
        grid = ctk.CTkFrame(scroll, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, theme.SPACE_1))
        for c in range(3):
            grid.grid_columnconfigure(c, weight=1, uniform="d")
        for i, (k, v) in enumerate(items):
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=i // 3, column=i % 3, sticky="ew", padx=(0, theme.SPACE_3), pady=2)
            ctk.CTkLabel(cell, text=k, font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(cell, text=str(v), font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                         anchor="w", justify="left", wraplength=230).pack(anchor="w")

    def _docs_block(self, scroll, tag: dict) -> None:
        docs = [(lab, tag.get(key, "")) for lab, key in
                (("Cálculo", "Doc EIPSA Calc."), ("Plano", "Doc EIPSA Plano"))]
        docs = [(lab, num) for lab, num in docs if num]
        _section_header(scroll, "Documentación EIPSA enlazada").pack(
            fill="x", padx=14, pady=(theme.SPACE_3, theme.SPACE_1))
        if not docs:
            ctk.CTkLabel(scroll, text="Este equipo no tiene cálculo ni plano EIPSA asignados en el ERP.",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w").pack(
                fill="x", padx=14, pady=(0, theme.SPACE_1))
            return
        for lab, num in docs:
            sym, est, eipsa = self._doc_state(num)
            # Si el ERP guardó el nº del cliente, mostrar también el nº EIPSA resuelto
            shown = num if (not eipsa or _norm_doc(eipsa) == _norm_doc(num)) else f"{num}  →  {eipsa}"
            r = ctk.CTkFrame(scroll, fg_color="transparent")
            r.pack(fill="x", padx=14, pady=1)
            ctk.CTkLabel(r, text=lab, font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                         width=60, anchor="w").pack(side="left")
            ctk.CTkLabel(r, text=shown, font=theme.FONT_SMALL_BOLD, text_color=theme.ACCENT,
                         width=260, anchor="w").pack(side="left")
            if sym == "?":
                ctk.CTkLabel(r, text="no figura en Documentos", font=theme.FONT_SMALL,
                             text_color=theme.TEXT_MUTED, anchor="w").pack(side="left", fill="x", expand=True)
            else:
                ecol = _status_color(est)
                ctk.CTkLabel(r, text=f" {sym} {est or 'Sin enviar'} ", font=theme.FONT_TINY,
                             text_color=ecol, fg_color=ui.blend(ecol, theme.BG_CARD, 0.20),
                             corner_radius=7, height=20).pack(side="left")
            if self._on_open_documento:
                ui.button(r, "Ver en Documentos  →", "outline", size="xs", font=theme.FONT_TINY,
                          command=lambda n=(eipsa or num): (self.destroy(), self._on_open_documento(n))
                          ).pack(side="right")

    def _ots_block(self, scroll, tag: dict) -> None:
        ots = tag.get("_ots") or []
        _section_header(scroll, "Órdenes de fabricación").pack(
            fill="x", padx=14, pady=(theme.SPACE_3, theme.SPACE_1))
        if not ots:
            ctk.CTkLabel(scroll, text="Sin órdenes de trabajo registradas para este equipo.",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w").pack(
                fill="x", padx=14, pady=(0, theme.SPACE_1))
            return
        for o in ots:
            r = ctk.CTkFrame(scroll, fg_color="transparent")
            r.pack(fill="x", padx=14, pady=1)
            done = o["terminada"]
            ctk.CTkLabel(r, text="✓" if done else "•", font=theme.FONT_SMALL,
                         text_color=theme.GREEN if done else theme.AMBER, width=16).pack(side="left")
            ctk.CTkLabel(r, text=f"OT {o['ot']}", font=theme.FONT_SMALL_BOLD, text_color=theme.ACCENT,
                         width=90, anchor="w").pack(side="left")
            what = " · ".join(x for x in (o["plano"], o["elemento"],
                                          f"x{o['cantidad']}" if o["cantidad"] else "") if x)
            ctk.CTkLabel(r, text=what, font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                         anchor="w").pack(side="left", fill="x", expand=True)
            when = (f"{o['inicio']} → {o['fin']}" if done
                    else (f"desde {o['inicio']}" if o["inicio"] else "sin fecha"))
            ctk.CTkLabel(r, text=when, font=theme.FONT_TINY, text_color=theme.TEXT_MUTED).pack(side="right")
