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
import threading
from collections import Counter

import customtkinter as ctk

from core.services import erp as erp_service
from gui import cell_format, theme
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


# ════════════════════════════════════════════════════════════════════════════
#  Vista principal
# ════════════════════════════════════════════════════════════════════════════

class PedidosView(ctk.CTkFrame):
    def __init__(self, master, on_open_documentos=None, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._on_open_documentos = on_open_documentos
        self._projects: list[dict] = []
        self._label_to_pedido: dict[str, str] = {}
        self._pedido_current: str | None = None
        self._tags_current: list[dict] = []
        self._build_layout()
        self.after(60, self._load_projects)

    # ── Layout raíz ─────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(header, text="Seguimiento", font=theme.FONT_TITLE,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            header, text="El estado del pedido de un vistazo: avance, plazo, fabricación y qué requiere acción",
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(theme.SPACE_1, 0))

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
                tags = []
                try:
                    if erp_service.tags_available():
                        tags = erp_service.get_tags(pedido=pedido)
                except Exception:
                    tags = []
                self.after(0, lambda: self._render_detail(pedido, dash, tags))
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

    def _render_detail(self, pedido: str, dash: dict | None, tags: list[dict]) -> None:
        if pedido != self._pedido_current:
            return
        for w in self.detail.winfo_children():
            w.destroy()
        if not dash:
            ctk.CTkLabel(self.detail, text="Sin datos para este pedido.",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(pady=40)
            return
        scroll = self.detail
        kpis = dash["kpis"]
        seg = dash.get("seguimiento") or {}
        consulta = dash.get("consulta") or {}
        docs = dash.get("documents") or []

        verdict = self._status_verdict(kpis, seg)
        self._dash = dash
        self._tags = tags
        self._subview = "estado"

        self._build_header_card(scroll, pedido, dash, consulta, docs, kpis, verdict)

        # Conmutador (arriba): Estado del pedido  |  Equipos & Tags (subsección)
        self._seg_sub = ctk.CTkSegmentedButton(
            scroll, values=["Estado del pedido", "Equipos & Tags"],
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
        # Estado del pedido: Fabricación → Documentación → Atención → Plazo
        self._build_fase_erp(body, dash.get("consulta") or {})
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
                     text_color="#FFFFFF" if col != theme.TEXT_MUTED else theme.TEXT_MAIN,
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
            ctk.CTkButton(
                foot, text="Ver en Documentos  →", font=theme.FONT_SMALL_BOLD,
                height=theme.HEIGHT_BUTTON_SM, corner_radius=theme.RADIUS_MD,
                fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, text_color="#FFFFFF",
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
        if not erp_service.tags_available():
            ctk.CTkLabel(parent, text="data_tags.xlsx no disponible "
                                      "(impórtalo en Ajustes → Fuentes de datos).",
                         font=theme.FONT_SMALL, text_color=theme.AMBER, anchor="w").pack(
                fill="x", pady=(0, theme.SPACE_3))
            return
        if not tags:
            ctk.CTkLabel(parent, text="Este pedido no tiene tags registrados.",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w").pack(
                fill="x", pady=(0, theme.SPACE_3))
            return
        self._tags_current = tags

        # Resumen por Estado Fab. (estado de fabricación de los equipos)
        counts = Counter(str(t.get("Estado Fab.", "") or "—").strip() or "—" for t in tags)
        summ = ctk.CTkFrame(parent, fg_color="transparent")
        summ.pack(fill="x", pady=(0, theme.SPACE_1))
        ctk.CTkLabel(summ, text=f"{len(tags)} equipos", font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN).pack(side="left", padx=(0, theme.SPACE_3))
        for estado, n in counts.most_common():
            ctk.CTkLabel(summ, text=f" {estado}: {n} ", font=theme.FONT_TINY,
                         text_color=theme.TEXT_SUB, fg_color=theme.BG_INPUT,
                         corner_radius=7, height=20).pack(side="left", padx=(0, theme.SPACE_1))

        # Toolbar: búsqueda + filtro por Estado Fab.
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", pady=(theme.SPACE_1, theme.SPACE_1))
        self._tags_search = ctk.CTkEntry(
            toolbar, placeholder_text="Buscar TAG, tipo, tamaño, rating…",
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD, fg_color=theme.BG_INPUT,
            border_color=theme.BORDER, text_color=theme.TEXT_MAIN, font=theme.FONT_SMALL)
        self._tags_search.pack(side="left", fill="x", expand=True, padx=(0, theme.SPACE_2))
        self._tags_search.bind("<KeyRelease>", lambda e: self._populate_tags_table())
        estados = ["Todos"] + sorted({str(t.get("Estado Fab.", "") or "").strip()
                                      for t in tags if str(t.get("Estado Fab.", "") or "").strip()})
        self._tags_estado = ctk.CTkOptionMenu(
            toolbar, values=estados, command=lambda _v: self._populate_tags_table(),
            width=180, height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            font=theme.FONT_SMALL, fg_color=theme.BG_INPUT, button_color=theme.BORDER_STRONG,
            button_hover_color=theme.TEXT_MUTED, text_color=theme.TEXT_MAIN)
        self._tags_estado.set("Todos")
        self._tags_estado.pack(side="left", padx=(0, theme.SPACE_2))
        self._tags_count = ctk.CTkLabel(toolbar, text="", font=theme.FONT_TINY,
                                        text_color=theme.TEXT_MUTED)
        self._tags_count.pack(side="left")

        ctk.CTkLabel(parent, text="doble-click en un equipo para el detalle completo",
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
            "TAG": "w", "Nº Pedido": "w", "Tipo": "w", "Tamaño Línea": "center",
            "Rating": "center", "Facing": "center", "Schedule": "center", "Estado Fab.": "center"})
        self._populate_tags_table()

    def _populate_tags_table(self) -> None:
        """Rellena la tabla de tags aplicando búsqueda + filtro Estado Fab.

        El iid de cada fila conserva el índice en self._tags_current para que el
        doble-click abra el TAG correcto aunque la lista esté filtrada.
        """
        table = getattr(self, "_tags_table", None)
        if table is None:
            return
        q = self._tags_search.get().strip().lower()
        estado = self._tags_estado.get()
        table.clear()
        shown = 0
        for idx, t in enumerate(self._tags_current):
            if estado and estado != "Todos" and str(t.get("Estado Fab.", "") or "").strip() != estado:
                continue
            if q and not any(q in str(v).lower() for v in t.values()):
                continue
            table.add_row(values=[
                t.get("TAG", ""), t.get("Nº Pedido", ""), t.get("Tipo", ""),
                t.get("Tamaño Línea", ""), t.get("Rating", ""), t.get("Facing", ""),
                t.get("Schedule", ""), cell_format.estado_with_icon(t.get("Estado Fab.", "")),
            ], iid=f"tag_{idx}")
            shown += 1
        self._tags_table.autofit_columns(max_per={"Tipo": 190, "TAG": 150, "Nº Pedido": 140})
        self._tags_count.configure(text=f"{shown} / {len(self._tags_current)} equipos")

    # ── Detalle de un TAG ───────────────────────────────────────────────────

    def _open_tag_detail(self, table) -> None:
        iid = table.selected_iid()
        if not iid or not iid.startswith("tag_"):
            return
        try:
            tag = self._tags_current[int(iid.split("_", 1)[1])]
        except (ValueError, IndexError):
            return
        TagDetailWindow(self, tag)


# ════════════════════════════════════════════════════════════════════════════
#  Ventana de detalle de un TAG (modal — 100+ campos)
# ════════════════════════════════════════════════════════════════════════════

class TagDetailWindow(ctk.CTkToplevel):
    def __init__(self, master, tag: dict):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title(f"TAG  ·  {tag.get('TAG', '—')}")
        self.geometry("820x720")
        self.minsize(560, 480)
        self.transient(master)
        self.grab_set()
        self._build(tag)

    def _build(self, tag: dict) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(18, 6))
        ctk.CTkLabel(header, text=str(tag.get("TAG", "—")), font=theme.font(18, "bold"),
                     text_color=theme.ACCENT, anchor="w").pack(anchor="w")
        sub = " · ".join(str(tag.get(k, "")) for k in ("Nº Pedido", "Tipo", "Estado Fab.")
                         if str(tag.get(k, "") or ""))
        ctk.CTkLabel(header, text=sub, font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB, anchor="w").pack(anchor="w", pady=(2, 0))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=22, pady=(0, 14))
        ctk.CTkButton(footer, text="Cerrar", font=theme.FONT_BUTTON, height=36,
                      corner_radius=8, fg_color=theme.BG_CARD, hover_color=theme.BG_INPUT,
                      text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
                      command=self.destroy).pack(side="right")

        scroll = ScrollFrame(self, fg_color=theme.BG_CARD)
        scroll.pack(side="top", fill="both", expand=True, padx=22, pady=(8, 12))

        for title, keys in erp_service.TAGS_DETAIL_SECTIONS:
            visibles = [(k, tag.get(k, "")) for k in keys
                        if str(tag.get(k, "") or "").strip() not in ("", "0", "0.0", "—")]
            if not visibles:
                continue
            _section_header(scroll, title).pack(fill="x", padx=14,
                                                pady=(theme.SPACE_3, theme.SPACE_1))
            grid = ctk.CTkFrame(scroll, fg_color="transparent")
            grid.pack(fill="x", padx=14, pady=(0, theme.SPACE_1))
            for c in range(3):
                grid.grid_columnconfigure(c, weight=1, uniform="d")
            for i, (k, v) in enumerate(visibles):
                cell = ctk.CTkFrame(grid, fg_color="transparent")
                cell.grid(row=i // 3, column=i % 3, sticky="ew", padx=(0, theme.SPACE_3), pady=2)
                ctk.CTkLabel(cell, text=k, font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                             anchor="w").pack(anchor="w")
                ctk.CTkLabel(cell, text=str(v), font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                             anchor="w", justify="left", wraplength=230).pack(anchor="w")
