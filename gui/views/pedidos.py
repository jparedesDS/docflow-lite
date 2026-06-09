"""Vista Pedidos — Proyectos como eje, con Consulta ERP y Tags contextuales.

Arquitectura (mínimos clics, todo centrado en el pedido):

  Pestañas de primer nivel:
    • Proyectos    → master-detail. Tabla de pedidos a la izquierda; al
                     seleccionar uno, su tarjeta a la derecha con sub-pestañas:
                         Dashboard · Consulta ERP · Tags & Inspecciones
                     (toda la información del pedido en un mismo sitio).
      (la curva-S / predicción de cada pedido va embebida en su Dashboard).

Carga pesada (monitoring / Excel) en hilos para no bloquear la UI.
"""

import logging
import threading

import customtkinter as ctk

from core.services import erp as erp_service
from gui import cell_format, theme
from gui.widgets import ui
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
    DETAIL_SUBS = ("Dashboard", "Tags & Inspecciones")

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)

        self._loaded: dict[str, bool] = {}
        self._proj_data: list[dict] = []
        self._proj_iid_pedido: dict[str, str] = {}
        self._proj_current: str | None = None
        self._dash: dict | None = None
        self._tags_current: list[dict] = []

        self._build_layout()
        # Proyectos es la pestaña por defecto → cargar al arrancar
        self.after(60, self._ensure_proj_loaded)

    # ── Layout raíz ─────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(header, text="Pedidos", font=theme.FONT_TITLE,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Dashboard, fase ERP, seguimiento y tags de cada pedido en una vista",
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(theme.SPACE_1, 0))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=theme.SPACE_5, pady=(theme.SPACE_3, theme.SPACE_4))
        self._build_proyectos_tab(content)

    def _ensure_proj_loaded(self) -> None:
        if not self._loaded.get("Proyectos"):
            self._loaded["Proyectos"] = True
            self._load_proj_general()

    # ════════════════════════════════════════════════════════════════════════
    #  PROYECTOS — master-detail
    # ════════════════════════════════════════════════════════════════════════

    PROJ_COLUMNS = ["Pedido", "Cliente", "Total", "%", "Crít."]

    def _build_proyectos_tab(self, parent) -> None:
        split = ctk.CTkFrame(parent, fg_color="transparent")
        split.pack(fill="both", expand=True, padx=theme.SPACE_2, pady=theme.SPACE_2)

        # ── Izquierda: lista de proyectos ────────────────────────────────
        left = ctk.CTkFrame(split, fg_color="transparent", width=420)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        self.ent_proj = ctk.CTkEntry(
            left, placeholder_text="Filtrar pedido / cliente…",
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_SMALL)
        self.ent_proj.pack(fill="x", pady=(0, theme.SPACE_2))
        self.ent_proj.bind("<KeyRelease>", lambda e: self._filter_proj())

        self.proj_status = ctk.CTkLabel(
            left, text="", font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w")
        self.proj_status.pack(fill="x", pady=(0, theme.SPACE_1))

        self.proj_table = DataTable(left, columns=self.PROJ_COLUMNS)
        self.proj_table.pack(fill="both", expand=True)
        self.proj_table.set_columns_anchor({
            "Pedido": "w", "Cliente": "w", "Total": "center", "%": "center", "Crít.": "center"})
        self.proj_table.tree.bind("<<TreeviewSelect>>", lambda e: self._on_proj_select())

        # ── Derecha: tarjeta del pedido (cabecera + sub-pestañas + host) ──
        right = ctk.CTkFrame(split, fg_color=theme.BG_CARD, corner_radius=12,
                             border_width=1, border_color=theme.BORDER)
        right.pack(side="left", fill="both", expand=True, padx=(theme.SPACE_4, 0))

        self.detail_head = ctk.CTkFrame(right, fg_color="transparent")
        self.detail_head.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_3, theme.SPACE_2))
        self.detail_title = ctk.CTkLabel(
            self.detail_head, text="Selecciona un pedido", font=theme.font(16, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w")
        self.detail_title.pack(anchor="w")
        self.detail_sub = ctk.CTkLabel(
            self.detail_head, text="Haz clic en una fila para ver toda su información.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w")
        self.detail_sub.pack(anchor="w", pady=(2, 0))
        ctk.CTkFrame(self.detail_head, fg_color=theme.BORDER, height=1).pack(
            fill="x", pady=(theme.SPACE_3, 0))

        self.detail_seg = ctk.CTkSegmentedButton(
            right, values=list(self.DETAIL_SUBS), command=self._on_detail_sub,
            fg_color=theme.BG_INPUT, selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.BG_INPUT, unselected_hover_color=theme.BG_CARD,
            text_color=theme.TEXT_MAIN, font=theme.FONT_SMALL_BOLD)
        # se muestra al seleccionar un pedido

        self.detail_host = ctk.CTkFrame(right, fg_color="transparent")
        self.detail_host.pack(fill="both", expand=True, padx=theme.SPACE_3,
                              pady=(0, theme.SPACE_3))
        self._detail_placeholder()

    def _detail_placeholder(self) -> None:
        for w in self.detail_host.winfo_children():
            w.destroy()
        box = ctk.CTkFrame(self.detail_host, fg_color="transparent")
        box.pack(expand=True, pady=70)
        ctk.CTkLabel(box, text="▦", font=theme.font(34, "bold"),
                     text_color=theme.BORDER_STRONG).pack()
        ctk.CTkLabel(box, text="Sin pedido seleccionado", font=theme.FONT_BODY_BOLD,
                     text_color=theme.TEXT_SUB).pack(pady=(theme.SPACE_2, 0))
        ctk.CTkLabel(box, text="Elige un pedido de la lista para ver su dashboard,\n"
                              "su ficha ERP y sus tags.",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                     justify="center").pack(pady=(2, 0))

    def _load_proj_general(self) -> None:
        self.proj_status.configure(text="⏳  Cargando…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                data = erp_service.project_list()
                self.after(0, lambda: self._render_proj_general(data))
            except Exception as exc:
                logger.exception("Error proyectos")
                msg = str(exc)
                self.after(0, lambda: self.proj_status.configure(
                    text=f"✗  {msg}", text_color=theme.RED))

        threading.Thread(target=worker, daemon=True).start()

    def _render_proj_general(self, data: list[dict]) -> None:
        self._proj_data = data
        self._fill_proj_table(data)

    def _fill_proj_table(self, data: list[dict]) -> None:
        self.proj_table.clear()
        self.proj_table.tree.tag_configure("row_crit", foreground=theme.RED)
        self._proj_iid_pedido = {}
        for vis, p in enumerate(data):
            iid = f"proj_{vis}"
            self._proj_iid_pedido[iid] = p["pedido"]
            vals = [p["pedido"], p["cliente"], p["total"],
                    f"{p['pct_completado']}%", p["criticos"]]
            tags = ("row_crit",) if p["criticos"] > 0 and p["pct_completado"] < 100 else ()
            self.proj_table.add_row(values=vals, iid=iid, tags=tags)
        self.proj_table.autofit_columns(max_per={"Cliente": 200, "Pedido": 120})
        self.proj_status.configure(text=f"{len(data)} pedido(s)", text_color=theme.TEXT_MUTED)

    def _filter_proj(self) -> None:
        q = self.ent_proj.get().strip().lower()
        shown = self._proj_data if not q else [
            p for p in self._proj_data
            if q in str(p["pedido"]).lower() or q in str(p["cliente"]).lower()]
        self._fill_proj_table(shown)

    def _on_proj_select(self) -> None:
        iid = self.proj_table.selected_iid()
        if not iid:
            return
        pedido = self._proj_iid_pedido.get(iid)
        if not pedido or pedido == self._proj_current:
            return
        self._proj_current = pedido
        self._dash = None
        self._tags_current = []
        # Cabecera + sub-nav
        self.detail_title.configure(text=pedido)
        self.detail_sub.configure(text="Cargando…")
        if not self.detail_seg.winfo_ismapped():
            self.detail_seg.pack(fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_2),
                                 before=self.detail_host)
        self.detail_seg.set("Dashboard")
        self._show_detail_loading()

        def worker():
            try:
                dash = erp_service.project_dashboard(pedido)
                self.after(0, lambda: self._on_dash_loaded(pedido, dash))
            except Exception as exc:
                logger.exception("Error dashboard")
                msg = str(exc)
                self.after(0, lambda: self._show_detail_error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _show_detail_loading(self) -> None:
        for w in self.detail_host.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.detail_host, text="⏳  Cargando…", font=theme.FONT_BODY,
                     text_color=theme.TEXT_MUTED).pack(pady=50)

    def _show_detail_error(self, msg: str) -> None:
        for w in self.detail_host.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.detail_host, text=f"✗  {msg}", font=theme.FONT_SMALL,
                     text_color=theme.RED).pack(pady=50)

    def _on_dash_loaded(self, pedido: str, dash: dict | None) -> None:
        if pedido != self._proj_current:
            return
        self._dash = dash
        cli = (dash or {}).get("cliente", "")
        ndocs = (dash or {}).get("total", 0)
        self.detail_sub.configure(text=f"{cli}  ·  {ndocs} documento(s)" if cli else f"{ndocs} documento(s)")
        self._render_detail_sub("Dashboard")

    def _on_detail_sub(self, name: str) -> None:
        self._render_detail_sub(name)

    def _render_detail_sub(self, name: str) -> None:
        for w in self.detail_host.winfo_children():
            w.destroy()
        if name == "Dashboard":
            self._render_dashboard_sub()
        elif name == "Tags & Inspecciones":
            self._render_tags_sub()

    # ── Sub-pestaña: Dashboard ───────────────────────────────────────────────

    def _render_dashboard_sub(self) -> None:
        dash = self._dash
        if not dash:
            ctk.CTkLabel(self.detail_host, text="Sin datos.", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTED).pack(pady=40)
            return
        scroll = ctk.CTkScrollableFrame(self.detail_host, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        kpis = dash["kpis"]

        _section_header(scroll, "Resumen").pack(fill="x", pady=(theme.SPACE_1, theme.SPACE_2))

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
            box = ctk.CTkFrame(kgrid, fg_color=theme.BG_PAGE, corner_radius=10,
                               border_width=1, border_color=theme.BORDER)
            box.grid(row=i // ncols, column=i % ncols, sticky="ew",
                     padx=(0 if i % ncols == 0 else theme.SPACE_2, 0), pady=(0, theme.SPACE_2))
            ctk.CTkLabel(box, text=label.upper(), font=theme.FONT_LABEL,
                         text_color=theme.TEXT_MUTED).pack(anchor="w", padx=theme.SPACE_3,
                                                           pady=(theme.SPACE_2, 0))
            ctk.CTkLabel(box, text=str(value), font=theme.font(17, "bold"),
                         text_color=color).pack(anchor="w", padx=theme.SPACE_3,
                                                pady=(0, theme.SPACE_2))

        # Progreso
        pcard = ctk.CTkFrame(scroll, fg_color=theme.BG_PAGE, corner_radius=10,
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

        # Seguimiento (curva-S / predicción del pedido)
        self._build_seguimiento_block(scroll, dash.get("seguimiento") or {})

        # Fase ERP (ficha de consulta_erp embebida)
        self._build_fase_erp(scroll, dash.get("consulta") or {})

        # Documentos
        _section_header(scroll, f"Documentos ({dash['total']})").pack(
            fill="x", pady=(0, theme.SPACE_2))
        host = ctk.CTkFrame(scroll, fg_color="transparent", height=400)
        host.pack(fill="both", expand=True)
        host.pack_propagate(False)
        table = DataTable(host, columns=["Doc. EIPSA", "Título", "Tipo", "Rev", "Estado", "Crít.", "Días"])
        table.pack(fill="both", expand=True)
        table.set_columns_anchor({
            "Doc. EIPSA": "w", "Título": "w", "Tipo": "w", "Rev": "center",
            "Estado": "center", "Crít.": "center", "Días": "center"})
        for i, d in enumerate(dash["documents"]):
            crit = str(d.get("Crítico", "") or "").strip().lower()
            table.add_row(values=[
                d.get("Nº Doc. EIPSA", ""), d.get("Título", ""), d.get("Tipo Doc.", ""),
                d.get("Nº Revisión", ""), cell_format.estado_with_icon(d.get("Estado", "")),
                "Sí" if crit in ("sí", "si") else "No",
                cell_format.urgency_bar(d.get("Días Devolución", "")),
            ], iid=f"d_{i}")
        table.autofit_columns(max_per={"Título": 380, "Doc. EIPSA": 185, "Tipo": 150})

    # ── Seguimiento (curva-S) embebido en el Dashboard ──────────────────────

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

    # ── Sub-pestaña: Tags & Inspecciones (del pedido) ───────────────────────

    def _render_tags_sub(self) -> None:
        pedido = self._proj_current
        info = ctk.CTkLabel(self.detail_host, text="⏳  Cargando tags…",
                            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w")
        info.pack(fill="x", pady=(0, theme.SPACE_1))

        table = DataTable(self.detail_host, columns=erp_service.TAGS_SUMMARY_COLUMNS,
                          on_double_click=lambda _i: self._open_tag_detail(table))
        table.pack(fill="both", expand=True)
        table.set_columns_anchor({
            "TAG": "w", "Nº Pedido": "w", "Tipo": "w", "Tamaño Línea": "center",
            "Rating": "center", "Facing": "center", "Schedule": "center", "Estado Fab.": "center"})

        def worker():
            try:
                available = erp_service.tags_available()
                data = erp_service.get_tags(pedido=pedido) if available else []
                self.after(0, lambda: self._fill_tags_sub(info, table, available, data))
            except Exception as exc:
                logger.exception("Error tags pedido")
                msg = str(exc)
                self.after(0, lambda: info.configure(text=f"✗  {msg}", text_color=theme.RED))

        threading.Thread(target=worker, daemon=True).start()

    def _fill_tags_sub(self, info, table, available, data) -> None:
        if not available:
            info.configure(
                text="data_tags.xlsx no disponible (impórtalo en Centro de Reportes → Fuente de datos).",
                text_color=theme.AMBER)
            return
        self._tags_current = data
        table.clear()
        for idx, t in enumerate(data):
            table.add_row(values=[
                t.get("TAG", ""), t.get("Nº Pedido", ""), t.get("Tipo", ""),
                t.get("Tamaño Línea", ""), t.get("Rating", ""), t.get("Facing", ""),
                t.get("Schedule", ""), cell_format.estado_with_icon(t.get("Estado Fab.", "")),
            ], iid=f"tag_{idx}")
        table.autofit_columns(max_per={"Tipo": 190, "TAG": 150, "Nº Pedido": 140})
        if data:
            info.configure(text=f"✓  {len(data)} tag(s) · doble-click para el detalle completo",
                           text_color=theme.TEXT_MUTED)
        else:
            info.configure(text="Este pedido no tiene tags registrados.", text_color=theme.TEXT_MUTED)

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
