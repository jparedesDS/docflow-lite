"""Vista Pedidos — buscador de pedidos + ficha completa.

Sin lista/bandeja: una barra de filtros (Nº pedido / cliente) para encontrar el
pedido, y debajo TODA su información bien organizada y en una sola vista:
Resumen (KPIs) · Progreso · Seguimiento (curva-S) · Fase ERP · Documentos ·
Tags & Inspecciones.

Carga pesada (monitoring / Excel) en hilos para no bloquear la UI.
"""

import logging
import threading

import customtkinter as ctk

from core.services import erp as erp_service
from gui import cell_format, theme
from gui.views.documentos import _fmt, _fmt_int, _status_color, _trunc
from gui.widgets import ui
from gui.widgets.pilltable import PillTable
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


# ════════════════════════════════════════════════════════════════════════════
#  Vista principal
# ════════════════════════════════════════════════════════════════════════════

class PedidosView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
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
            header, text="Busca un pedido y consulta toda su información en una vista",
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

        # ── Ficha del pedido (todo el ancho, scrollable) ─────────────────
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
        ctk.CTkLabel(box, text="Escribe arriba y elige un pedido para ver su ficha completa:\n"
                              "resumen, progreso, seguimiento, fase ERP, documentos y tags.",
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
        # Si el filtro deja exactamente uno, cárgalo directamente
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
    #  FICHA COMPLETA DEL PEDIDO
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
        cli = dash.get("cliente", "")

        # ── Cabecera del pedido ──────────────────────────────────────────
        head = ctk.CTkFrame(scroll, fg_color=theme.BG_CARD, corner_radius=12,
                            border_width=1, border_color=theme.BORDER)
        head.pack(fill="x", pady=(0, theme.SPACE_3))
        hin = ctk.CTkFrame(head, fg_color="transparent")
        hin.pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_3)
        ctk.CTkLabel(hin, text=pedido, font=theme.font(20, "bold"),
                     text_color=theme.TEXT_MAIN).pack(side="left")
        if cli:
            ctk.CTkLabel(hin, text=cli, font=theme.FONT_BODY, text_color=theme.TEXT_SUB).pack(
                side="left", padx=(theme.SPACE_3, 0))
        ctk.CTkLabel(hin, text=f"{dash['total']} documento(s)", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_MUTED).pack(side="right")
        if kpis["criticos"] > 0:
            ctk.CTkLabel(hin, text=f"  ⚠ {kpis['criticos']} críticos  ", font=theme.FONT_TINY,
                         text_color=theme.RED, fg_color=ui.blend(theme.RED, theme.BG_CARD, 0.18),
                         corner_radius=8, height=22).pack(side="right", padx=(0, theme.SPACE_2))

        # ── 1) Fase ERP ──────────────────────────────────────────────────
        self._build_fase_erp(scroll, dash.get("consulta") or {})

        # ── 2) Seguimiento (curva-S) ─────────────────────────────────────
        self._build_seguimiento_block(scroll, dash.get("seguimiento") or {})

        # ── 3) Resumen (KPIs + progreso) ─────────────────────────────────
        _section_header(scroll, "Resumen").pack(fill="x", pady=(0, theme.SPACE_2))
        kpi_defs = [
            ("Total", kpis["total"], theme.ACCENT),
            ("Aprobados", f"{kpis['aprobados']} · {kpis['pct_completado']}%", theme.GREEN),
            ("Enviados", kpis["enviados"], theme.BLUE),
            ("Devoluciones", kpis["devoluciones"], theme.AMBER),
            ("Sin enviar", kpis["sin_enviar"], theme.TEXT_MUTED),
            ("Críticos", kpis["criticos"], theme.RED),
            ("Media días", dash["avg_dias_respuesta"], theme.TEXT_MAIN),
        ]
        kgrid = ctk.CTkFrame(scroll, fg_color="transparent")
        kgrid.pack(fill="x", pady=(0, theme.SPACE_3))
        ncols = 4
        for c in range(ncols):
            kgrid.grid_columnconfigure(c, weight=1, uniform="kpi")
        for i, (label, value, color) in enumerate(kpi_defs):
            box = ctk.CTkFrame(kgrid, fg_color=theme.BG_CARD, corner_radius=10,
                               border_width=1, border_color=theme.BORDER)
            box.grid(row=i // ncols, column=i % ncols, sticky="ew",
                     padx=(0 if i % ncols == 0 else theme.SPACE_2, 0), pady=(0, theme.SPACE_2))
            ctk.CTkLabel(box, text=str(label).upper(), font=theme.FONT_LABEL,
                         text_color=theme.TEXT_MUTED).pack(anchor="w", padx=theme.SPACE_3,
                                                           pady=(theme.SPACE_2, 0))
            ctk.CTkLabel(box, text=str(value), font=theme.font(17, "bold"),
                         text_color=color).pack(anchor="w", padx=theme.SPACE_3,
                                                pady=(0, theme.SPACE_2))

        # Progreso
        pcard = ctk.CTkFrame(scroll, fg_color=theme.BG_CARD, corner_radius=10,
                             border_width=1, border_color=theme.BORDER)
        pcard.pack(fill="x", pady=(0, theme.SPACE_3))
        prow = ctk.CTkFrame(pcard, fg_color="transparent")
        prow.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_3, theme.SPACE_1))
        ctk.CTkLabel(prow, text="Progreso del pedido", font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN).pack(side="left")
        ctk.CTkLabel(prow, text=f"{kpis['pct_completado']}%", font=theme.FONT_SMALL_BOLD,
                     text_color=theme.GREEN).pack(side="right")
        bar = ctk.CTkProgressBar(pcard, height=10, corner_radius=5,
                                 progress_color=theme.GREEN, fg_color=theme.BORDER)
        bar.pack(fill="x", padx=theme.SPACE_4, pady=(0, theme.SPACE_3))
        bar.set(min(kpis["pct_completado"], 100) / 100)

        # ── 4) Documentos (misma estética que la sección Documentos) ─────
        self._build_docs_table(scroll, dash["documents"], dash["total"])

        # ── Tags & Inspecciones ──────────────────────────────────────────
        self._render_tags_block(scroll, tags)

    # ── Documentos — PillTable con pills de color (estética sección Documentos)

    _DOC_COLS = [
        {"key": "Nº Doc. EIPSA",   "label": "Nº Doc. EIPSA", "min": 172, "anchor": "w"},
        {"key": "Título",          "label": "Título",        "min": 200, "anchor": "w", "stretch": True},
        {"key": "Tipo Doc.",       "label": "Tipo",          "min": 130, "anchor": "w"},
        {"key": "Crítico",         "label": "Crít.",         "min": 64,  "anchor": "center"},
        {"key": "Info/Review",     "label": "I/R",           "min": 52,  "anchor": "center"},
        {"key": "Estado",          "label": "Estado",        "min": 124, "anchor": "center"},
        {"key": "Nº Revisión",     "label": "Rev.",          "min": 56,  "anchor": "center"},
        {"key": "Fecha Env. Doc.", "label": "Fecha Env.",    "min": 100, "anchor": "center"},
        {"key": "Días Devolución", "label": "Días Dev.",     "min": 78,  "anchor": "center"},
    ]

    def _build_docs_table(self, parent, documents: list[dict], total: int) -> None:
        _section_header(parent, f"Documentos ({total})").pack(fill="x", pady=(0, theme.SPACE_2))
        if not documents:
            ctk.CTkLabel(parent, text="Este pedido no tiene documentos.",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w").pack(
                fill="x", pady=(0, theme.SPACE_3))
            return
        # Altura ajustada al nº de filas (cap a ~12 visibles → resto con scroll interno)
        h = min(max(len(documents), 1), 12) * 42 + 54
        host = ctk.CTkFrame(parent, fg_color="transparent", height=h)
        host.pack(fill="x", pady=(0, theme.SPACE_3))
        host.pack_propagate(False)
        table = PillTable(host, self._DOC_COLS)
        table.pack(fill="both", expand=True)
        rows = []
        for i, d in enumerate(documents):
            rows.append((f"d_{i}", self._doc_cells(d)))
        table.set_rows(rows)

    @staticmethod
    def _doc_cells(doc: dict) -> dict:
        estado = str(doc.get("Estado", "") or "")
        ecolor = _status_color(estado)
        crit = str(doc.get("Crítico", "") or "").strip().lower()
        if crit in ("sí", "si"):
            critico_cell = {"text": "Sí", "pill": True, "fg": theme.ROSE,
                            "pill_bg": ui.blend(theme.ROSE, theme.BG_CARD, 0.20)}
        else:
            critico_cell = {"text": "No" if crit else "—", "fg": theme.TEXT_MUTED}
        return {
            "Nº Doc. EIPSA":   {"text": _fmt(doc.get("Nº Doc. EIPSA")), "fg": theme.ACCENT},
            "Título":          {"text": _trunc(doc.get("Título"), 64)},
            "Tipo Doc.":       {"text": _trunc(doc.get("Tipo Doc."), 22)},
            "Crítico":         critico_cell,
            "Info/Review":     {"text": _fmt(doc.get("Info/Review"))},
            "Estado":          {"text": (estado or "Sin enviar"), "pill": True, "fg": ecolor,
                                "pill_bg": ui.blend(ecolor, theme.BG_CARD, 0.20)},
            "Nº Revisión":     {"text": _fmt_int(doc.get("Nº Revisión"))},
            "Fecha Env. Doc.": {"text": _fmt(doc.get("Fecha Env. Doc."))},
            "Días Devolución": {"text": _fmt_int(doc.get("Días Devolución"), dash=True),
                                "bold": True},
        }

    # ── Tags & Inspecciones (bloque dentro de la ficha) ──────────────────────

    def _render_tags_block(self, parent, tags: list[dict]) -> None:
        _section_header(parent, "Tags & Inspecciones").pack(fill="x", pady=(0, theme.SPACE_2))
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
        ctk.CTkLabel(parent, text=f"{len(tags)} tag(s) · doble-click para el detalle completo",
                     font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w").pack(
            fill="x", pady=(0, theme.SPACE_1))
        host = ctk.CTkFrame(parent, fg_color="transparent", height=320)
        host.pack(fill="x", pady=(0, theme.SPACE_3))
        host.pack_propagate(False)
        table = DataTable(host, columns=erp_service.TAGS_SUMMARY_COLUMNS,
                          on_double_click=lambda _i: self._open_tag_detail(table))
        table.pack(fill="both", expand=True)
        table.set_columns_anchor({
            "TAG": "w", "Nº Pedido": "w", "Tipo": "w", "Tamaño Línea": "center",
            "Rating": "center", "Facing": "center", "Schedule": "center", "Estado Fab.": "center"})
        for idx, t in enumerate(tags):
            table.add_row(values=[
                t.get("TAG", ""), t.get("Nº Pedido", ""), t.get("Tipo", ""),
                t.get("Tamaño Línea", ""), t.get("Rating", ""), t.get("Facing", ""),
                t.get("Schedule", ""), cell_format.estado_with_icon(t.get("Estado Fab.", "")),
            ], iid=f"tag_{idx}")
        table.autofit_columns(max_per={"Tipo": 190, "TAG": 150, "Nº Pedido": 140})

    # ── Seguimiento (curva-S) embebido en la ficha ──────────────────────────

    def _build_seguimiento_block(self, parent, seg: dict) -> None:
        _section_header(parent, "Seguimiento · Curva-S").pack(fill="x", pady=(0, theme.SPACE_2))
        card = ctk.CTkFrame(parent, fg_color=theme.BG_PAGE, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, theme.SPACE_3))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_3)

        pct = seg.get("pct", 0)
        pct_esp = seg.get("pct_esperado")
        en_plazo = seg.get("en_plazo")

        # Línea superior: avance + estado
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text="Avance real vs. esperado", font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN).pack(side="left")
        if en_plazo is True:
            estado_txt, estado_col = "✓ En plazo", theme.GREEN
        elif en_plazo is False:
            estado_txt, estado_col = "✗ Riesgo de retraso", theme.RED
        else:
            estado_txt, estado_col = "Sin fecha prevista", theme.TEXT_MUTED
        ctk.CTkLabel(top, text=f"  {estado_txt}  ", font=theme.FONT_TINY,
                     text_color=estado_col, fg_color=theme.BG_CARD, corner_radius=8,
                     height=22).pack(side="right")

        # Barra dual (esperado de fondo + real encima)
        track = ctk.CTkFrame(inner, fg_color=theme.BORDER, height=12, corner_radius=6)
        track.pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_1))
        if pct_esp is not None:
            exp = ctk.CTkFrame(track, fg_color=theme.TEXT_MUTED, corner_radius=6)
            exp.place(relx=0, rely=0, relheight=1, relwidth=max(0.01, min(1.0, pct_esp / 100)))
        real = ctk.CTkFrame(track, fg_color=theme.ACCENT, corner_radius=6)
        real.place(relx=0, rely=0, relheight=1, relwidth=max(0.01, min(1.0, pct / 100)))

        # Leyenda real/esperado
        leg = ctk.CTkFrame(inner, fg_color="transparent")
        leg.pack(fill="x", pady=(0, theme.SPACE_2))
        for txt, col in (("Real", theme.ACCENT), ("Esperado", theme.TEXT_MUTED)):
            chip = ctk.CTkFrame(leg, fg_color="transparent")
            chip.pack(side="left", padx=(0, theme.SPACE_3))
            ctk.CTkFrame(chip, fg_color=col, width=10, height=10, corner_radius=2).pack(side="left")
            ctk.CTkLabel(chip, text=txt, font=theme.FONT_TINY, text_color=theme.TEXT_MUTED).pack(
                side="left", padx=(4, 0))

        # Chips de métricas
        desv = (pct - pct_esp) if pct_esp is not None else None
        chips = [
            ("% Real", f"{pct}%", theme.ACCENT),
            ("% Esperado", f"{pct_esp}%" if pct_esp is not None else "—", theme.TEXT_SUB),
            ("Desviación", (f"+{desv}pp" if (desv is not None and desv >= 0)
                            else (f"{desv}pp" if desv is not None else "—")),
             (theme.GREEN if (desv is not None and desv >= 0) else theme.RED) if desv is not None else theme.TEXT_MUTED),
            ("Aprob/Total", f"{seg.get('aprobados', 0)}/{seg.get('total', 0)}", theme.TEXT_MAIN),
            ("Fecha prevista", seg.get("fecha_prevista") or "—", theme.TEXT_SUB),
            ("Pred. fin", seg.get("prediccion_fecha") or "—",
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

    # ── Fase ERP (ficha de consulta_erp, embebida en el Dashboard) ──────────

    def _build_fase_erp(self, parent, consulta: dict) -> None:
        _section_header(parent, "Fase ERP").pack(fill="x", pady=(0, theme.SPACE_2))
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

        # Info grid
        grid = ctk.CTkFrame(inner, fg_color="transparent")
        grid.pack(fill="x", pady=(0, theme.SPACE_3))
        cols = 4
        for c in range(cols):
            grid.grid_columnconfigure(c, weight=1, uniform="info")
        fields = erp_service.CONSULTA_INFO_FIELDS + [
            ("Cliente", "Cliente"), ("Nº Referencia", "Nº Referencia"),
            ("Importante Oferta", "Importante Oferta")]
        for i, (label, key) in enumerate(fields):
            self._info_item(grid, label, consulta.get(key, ""), i // cols, i % cols)

        # Fases
        phases = erp_service.consulta_phases(consulta)
        prow = ctk.CTkFrame(inner, fg_color="transparent")
        prow.pack(fill="x")
        prow.grid_rowconfigure(0, weight=1)
        for c in range(3):
            prow.grid_columnconfigure(c, weight=1, uniform="phase")
        for i, ph in enumerate(phases):
            self._phase_card(prow, ph, 0, i)

        # Notas
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
                     font=theme.FONT_SMALL_BOLD, text_color=theme.TEXT_MAIN,
                     anchor="w").pack(anchor="w")

    def _phase_card(self, parent, ph: dict, r, c) -> None:
        color = _phase_color(ph["pct"])
        box = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=8,
                           border_width=1, border_color=theme.BORDER)
        # nsew → todas las cajas de fase quedan a la misma altura
        box.grid(row=r, column=c, sticky="nsew", padx=(0 if c == 0 else theme.SPACE_2, 0))

        # Cabecera: título + fecha
        top = ctk.CTkFrame(box, fg_color="transparent")
        top.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_2, theme.SPACE_2))
        ctk.CTkLabel(top, text=ph["title"], font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN).pack(side="left")
        date = (ph["date"] or "")[:10]
        if date:
            ctk.CTkLabel(top, text=date, font=theme.FONT_TINY,
                         text_color=theme.TEXT_MUTED).pack(side="right")

        # Barra + % en línea
        barrow = ctk.CTkFrame(box, fg_color="transparent")
        barrow.pack(fill="x", padx=theme.SPACE_3)
        prog = ctk.CTkProgressBar(barrow, height=8, corner_radius=4,
                                  progress_color=color, fg_color=theme.BORDER)
        prog.pack(side="left", fill="x", expand=True, pady=2)
        prog.set(min(ph["pct"], 100) / 100)
        ctk.CTkLabel(barrow, text=f"{ph['pct']}%", font=theme.FONT_SMALL_BOLD,
                     text_color=color, width=44).pack(side="right", padx=(theme.SPACE_2, 0))

        # Observaciones (acotadas a 2-3 líneas)
        obs = str(ph["obs"] or "").strip()
        if len(obs) > 130:
            obs = obs[:130].rstrip() + "…"
        ctk.CTkLabel(box, text=obs or " ", font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                     anchor="nw", justify="left", wraplength=210).pack(
            fill="both", expand=True, padx=theme.SPACE_3, pady=(theme.SPACE_2, theme.SPACE_2))

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

        scroll = ctk.CTkScrollableFrame(self, fg_color=theme.BG_CARD, corner_radius=10)
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
