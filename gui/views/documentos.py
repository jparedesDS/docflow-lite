"""Vista Documentos — réplica funcional de Documents.js del DocFlow grande.

KPIs filtrables, filtros libres, tabla con 12 columnas, ordenación, paginación
y drawer de detalle al doble-click.
"""

import logging
import threading

import customtkinter as ctk
from tkinter import ttk

from core.services import monitoring as monitoring_service
from gui import theme
from gui.widgets.table import DataTable

logger = logging.getLogger(__name__)

# Columnas visibles (mismo orden que Documents.js)
VISIBLE_COLUMNS = list(monitoring_service.VISIBLE_COLUMNS)

PAGE_SIZE = 30


# KPI cards: (key, label, color)
KPI_DEFS = [
    ("total",        "Total",         theme.ACCENT),
    ("aprobados",    "Aprobados",     theme.GREEN),
    ("enviados",     "Enviados",      theme.BLUE),
    ("devoluciones", "Devoluciones",  theme.AMBER),
    ("criticos",     "Críticos",      theme.RED),
    ("criticos_15d", "Críticos +15d", theme.ROSE),
    ("sin_enviar",   "Sin enviar",    theme.TEXT_MUTED),
]


class DocumentosView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)

        self._all_docs: list[dict] = []
        self._filtered: list[dict] = []
        self._page = 0
        self._sort_col: str | None = None
        self._sort_asc = True
        self._active_kpi: str | None = None
        self._search_after_id = None

        self._build_layout()
        self._reload()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(
            header, text="Documentos", font=theme.FONT_TITLE,
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text="Vista de monitorización · data_erp + consulta_erp",
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(theme.SPACE_1, 0))

        # KPIs
        self.kpi_row = ctk.CTkFrame(self, fg_color="transparent")
        self.kpi_row.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_4, theme.SPACE_2))
        self._build_kpi_cards()

        # Filtros (caja minimal, sin background card)
        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_2, theme.SPACE_2))

        self.ent_q = self._make_entry(filters, "Buscar (Nº Doc, Título, Cliente…)")
        self.ent_q.pack(side="left", fill="x", expand=True, padx=(0, theme.SPACE_2))
        self.ent_q.bind("<KeyRelease>", lambda e: self._debounced_search())

        self.ent_pedido = self._make_entry(filters, "Nº Pedido", width=130)
        self.ent_pedido.pack(side="left", padx=(0, theme.SPACE_2))
        self.ent_pedido.bind("<KeyRelease>", lambda e: self._debounced_search())

        self.ent_cliente = self._make_entry(filters, "Cliente", width=130)
        self.ent_cliente.pack(side="left", padx=(0, theme.SPACE_2))
        self.ent_cliente.bind("<KeyRelease>", lambda e: self._debounced_search())

        self.ent_resp = self._make_entry(filters, "Responsable (JP)", width=140)
        self.ent_resp.pack(side="left", padx=(0, theme.SPACE_2))
        self.ent_resp.bind("<KeyRelease>", lambda e: self._debounced_search())

        ctk.CTkButton(
            filters, text="Limpiar", width=70,
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_SUB, font=theme.FONT_SMALL_BOLD,
            border_width=1, border_color=theme.BORDER,
            command=self._clear_filters,
        ).pack(side="left", padx=(0, theme.SPACE_2))

        ctk.CTkButton(
            filters, text="↻", width=36,
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_SUB, font=theme.FONT_BUTTON,
            border_width=1, border_color=theme.BORDER,
            command=self._hard_refresh,
        ).pack(side="left")

        # Status + paginación
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_3, theme.SPACE_1))

        self.lbl_status = ctk.CTkLabel(
            bar, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
        )
        self.lbl_status.pack(side="left")

        pager = ctk.CTkFrame(bar, fg_color="transparent")
        pager.pack(side="right")
        self.btn_prev = ctk.CTkButton(
            pager, text="‹", width=30,
            height=theme.HEIGHT_BUTTON_SM, corner_radius=theme.RADIUS_SM,
            fg_color="transparent", hover_color=theme.BG_INPUT, text_color=theme.TEXT_SUB,
            font=theme.FONT_BUTTON, border_width=1, border_color=theme.BORDER,
            command=lambda: self._goto_page(self._page - 1),
        )
        self.btn_prev.pack(side="left", padx=theme.SPACE_1)

        self.lbl_page = ctk.CTkLabel(
            pager, text="—", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB, width=100,
        )
        self.lbl_page.pack(side="left", padx=theme.SPACE_1)

        self.btn_next = ctk.CTkButton(
            pager, text="›", width=30,
            height=theme.HEIGHT_BUTTON_SM, corner_radius=theme.RADIUS_SM,
            fg_color="transparent", hover_color=theme.BG_INPUT, text_color=theme.TEXT_SUB,
            font=theme.FONT_BUTTON, border_width=1, border_color=theme.BORDER,
            command=lambda: self._goto_page(self._page + 1),
        )
        self.btn_next.pack(side="left", padx=theme.SPACE_1)

        # Table
        self.table = DataTable(self, columns=VISIBLE_COLUMNS, on_double_click=self._on_row_double)
        self.table.pack(fill="both", expand=True, padx=theme.SPACE_6, pady=(theme.SPACE_2, theme.SPACE_6))
        self._setup_table_columns()
        self._setup_row_tags()
        for col in VISIBLE_COLUMNS:
            self.table.tree.heading(col, text=col, command=lambda c=col: self._on_sort(c))

    def _make_entry(self, parent, placeholder: str, width: int | None = None) -> ctk.CTkEntry:
        kwargs = dict(
            placeholder_text=placeholder,
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        if width:
            kwargs["width"] = width
        return ctk.CTkEntry(parent, **kwargs)

    def _build_kpi_cards(self) -> None:
        self.kpi_widgets: dict[str, dict] = {}
        for col, (key, label, color) in enumerate(KPI_DEFS):
            card = ctk.CTkFrame(
                self.kpi_row, fg_color=theme.BG_CARD,
                corner_radius=theme.RADIUS_MD,
                border_width=1, border_color=theme.BORDER,
                height=72, cursor="hand2",
            )
            card.grid(row=0, column=col, sticky="nsew",
                      padx=(0 if col == 0 else theme.SPACE_2, 0))
            card.grid_propagate(False)

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=theme.SPACE_3, pady=theme.SPACE_3)

            lbl_label = ctk.CTkLabel(
                inner, text=label.upper(), font=theme.FONT_LABEL,
                text_color=theme.TEXT_MUTED, anchor="w",
            )
            lbl_label.pack(anchor="w")
            lbl_value = ctk.CTkLabel(
                inner, text="—", font=(theme.FONT_FAMILY, 20, "bold"),
                text_color=color, anchor="w",
            )
            lbl_value.pack(anchor="w", pady=(theme.SPACE_1, 0))

            for w in (card, inner, lbl_label, lbl_value):
                w.bind("<Button-1>", lambda e, k=key: self._toggle_kpi(k))

            self.kpi_widgets[key] = {"card": card, "value": lbl_value, "color": color, "label": lbl_label}

        for col in range(len(KPI_DEFS)):
            self.kpi_row.grid_columnconfigure(col, weight=1, uniform="kpi")

    def _setup_table_columns(self) -> None:
        widths = {
            "Nº Pedido": 110, "Nº Doc. EIPSA": 180, "Título": 320, "Cliente": 160,
            "Repsonsable": 100, "Tipo Doc.": 110, "Crítico": 70, "Info/Review": 90,
            "Estado": 130, "Nº Revisión": 80, "Fecha Env. Doc.": 120, "Días Devolución": 90,
        }
        self.table.set_columns_width(widths)
        # Anchor por tipo de dato: texto → izquierda, números/fechas/badges → centro
        anchors = {
            "Nº Pedido": "w", "Nº Doc. EIPSA": "w", "Título": "w", "Cliente": "w",
            "Repsonsable": "center", "Tipo Doc.": "center", "Crítico": "center",
            "Info/Review": "center", "Estado": "center", "Nº Revisión": "center",
            "Fecha Env. Doc.": "center", "Días Devolución": "center",
        }
        self.table.set_columns_anchor(anchors)
        # Desactivar stretch para que aparezca scroll horizontal en lugar de comprimir
        self.table.freeze_widths()

    def _setup_row_tags(self) -> None:
        # Coloreo de filas como en Documents.js
        self.table.tree.tag_configure("row_critico",   background=theme.ROW_BG_CRITICAL)
        self.table.tree.tag_configure("row_warn",      background=theme.ROW_BG_WARN)
        self.table.tree.tag_configure("row_aprobado",  foreground=theme.GREEN)
        self.table.tree.tag_configure("row_rechazado", foreground=theme.RED)
        self.table.tree.tag_configure("row_comentado", foreground=theme.AMBER)
        self.table.tree.tag_configure("row_enviado",   foreground=theme.BLUE)
        self.table.tree.tag_configure("row_sin_enviar", foreground=theme.TEXT_MUTED)

    # ── Datos ─────────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        self.lbl_status.configure(text="⏳  Cargando data_erp.xlsx + consulta_erp.xlsx…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                docs = monitoring_service.get_monitoring_data()
                self.after(0, lambda: self._on_loaded(docs))
            except Exception as exc:
                logger.exception("Error cargando monitoring")
                err = str(exc)
                self.after(0, lambda: self._show_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _hard_refresh(self) -> None:
        monitoring_service.invalidate_cache()
        self._reload()

    def _on_loaded(self, docs: list[dict]) -> None:
        self._all_docs = docs
        self._apply_filters_and_render()
        self._update_kpis(monitoring_service.compute_kpis(docs))

    def _show_error(self, msg: str) -> None:
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)

    # ── KPIs ──────────────────────────────────────────────────────────────────

    def _update_kpis(self, kpis: dict) -> None:
        for key, w in self.kpi_widgets.items():
            w["value"].configure(text=str(kpis.get(key, 0)))
            # Mostrar selección activa
            if key == self._active_kpi:
                w["card"].configure(border_color=w["color"])
            else:
                w["card"].configure(border_color=theme.BORDER)

    def _toggle_kpi(self, key: str) -> None:
        self._active_kpi = None if self._active_kpi == key else key
        self._page = 0
        self._apply_filters_and_render()

    # ── Filtros + render ──────────────────────────────────────────────────────

    def _debounced_search(self) -> None:
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(220, self._on_filter_change)

    def _on_filter_change(self) -> None:
        self._page = 0
        self._apply_filters_and_render()

    def _clear_filters(self) -> None:
        for ent in (self.ent_q, self.ent_pedido, self.ent_cliente, self.ent_resp):
            ent.delete(0, "end")
        self._active_kpi = None
        self._page = 0
        self._apply_filters_and_render()

    def _apply_filters_and_render(self) -> None:
        q = self.ent_q.get().strip()
        pedido = self.ent_pedido.get().strip()
        cliente = self.ent_cliente.get().strip()
        resp = self.ent_resp.get().strip()

        rows = self._all_docs

        if pedido:
            rows = [r for r in rows if pedido.lower() in str(r.get("Nº Pedido", "")).lower()]
        if cliente:
            rows = [r for r in rows if cliente.lower() in str(r.get("Cliente", "")).lower()]
        if resp:
            rl = resp.lower()
            rows = [r for r in rows
                    if rl in str(r.get("Responsable", "")).lower()
                    or rl in str(r.get("Repsonsable", "")).lower()]
        if q:
            ql = q.lower()
            rows = [r for r in rows if any(ql in str(v).lower() for v in r.values())]

        if self._active_kpi:
            rows = monitoring_service.filter_by_kpi(rows, self._active_kpi)

        if self._sort_col:
            try:
                rows = sorted(
                    rows,
                    key=lambda r: _sort_key(r.get(self._sort_col)),
                    reverse=not self._sort_asc,
                )
            except TypeError as exc:
                logger.warning("Sort fallback (incomparable types): %s", exc)
                rows = sorted(
                    rows,
                    key=lambda r: str(r.get(self._sort_col, "")).lower(),
                    reverse=not self._sort_asc,
                )

        self._filtered = rows
        self._render_page()
        self._update_kpis(monitoring_service.compute_kpis(self._all_docs))

    def _render_page(self) -> None:
        total = len(self._filtered)
        if total == 0:
            self.table.clear()
            self.lbl_page.configure(text="—")
            self.lbl_status.configure(text="Sin resultados", text_color=theme.TEXT_MUTED)
            self.btn_prev.configure(state="disabled")
            self.btn_next.configure(state="disabled")
            return

        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        if self._page >= pages:
            self._page = pages - 1
        if self._page < 0:
            self._page = 0

        start = self._page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_rows = self._filtered[start:end]

        self.table.clear()
        for idx, doc in enumerate(page_rows):
            values = [_fmt(doc.get(c, "")) for c in VISIBLE_COLUMNS]
            tags = _row_tags(doc)
            self.table.add_row(values=values, iid=f"row_{start + idx}", tags=tags)

        self.lbl_page.configure(text=f"Pág {self._page + 1} / {pages}")
        self.lbl_status.configure(
            text=f"✓  {total} documentos  ·  mostrando {start + 1}-{end}",
            text_color=theme.TEXT_MUTED,
        )
        self.btn_prev.configure(state="normal" if self._page > 0 else "disabled")
        self.btn_next.configure(state="normal" if self._page < pages - 1 else "disabled")

    def _goto_page(self, page: int) -> None:
        self._page = page
        self._render_page()

    def _on_sort(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        # Marca visual: añade flecha
        for c in VISIBLE_COLUMNS:
            arrow = ""
            if c == self._sort_col:
                arrow = "  ▲" if self._sort_asc else "  ▼"
            self.table.tree.heading(c, text=f"{c}{arrow}")
        self._page = 0
        self._apply_filters_and_render()

    def _on_row_double(self, item) -> None:
        sel = self.table.selected_iid()
        if not sel or not sel.startswith("row_"):
            return
        try:
            idx = int(sel.split("_", 1)[1])
            doc = self._filtered[idx]
        except (ValueError, IndexError):
            return
        DocDetailWindow(self, doc=doc)


# ════════════════════════════════════════════════════════════════════════════
#  Ventana de detalle
# ════════════════════════════════════════════════════════════════════════════

class DocDetailWindow(ctk.CTkToplevel):
    def __init__(self, master, doc: dict):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title(f"{doc.get('Nº Doc. EIPSA', 'Documento')}")
        self.geometry("680x720")
        self.minsize(560, 560)
        self.transient(master)
        self.grab_set()

        self._build(doc)

    def _build(self, doc: dict) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(20, 6))
        ctk.CTkLabel(
            header, text=str(doc.get("Nº Doc. EIPSA", "—")),
            font=(theme.FONT_FAMILY, 18, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text=str(doc.get("Título", "") or "Sin título"),
            font=theme.FONT_BODY, text_color=theme.TEXT_SUB,
            anchor="w", wraplength=620, justify="left",
        ).pack(anchor="w", pady=(2, 0))

        # Badge estado
        estado = str(doc.get("Estado", "") or "Sin Enviar")
        badge_color = _status_color(estado)
        badge = ctk.CTkFrame(self, fg_color=badge_color, corner_radius=6, height=28)
        badge.pack(anchor="w", padx=22, pady=(8, 8))
        ctk.CTkLabel(
            badge, text=f"  {estado.upper()}  ", font=(theme.FONT_FAMILY, 11, "bold"),
            text_color="white",
        ).pack()

        # Footer pegado al fondo (se packea primero para garantizar visibilidad)
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=22, pady=(0, 14))
        ctk.CTkButton(
            footer, text="Cerrar", font=theme.FONT_BUTTON,
            height=36, corner_radius=8,
            fg_color=theme.BG_CARD, hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self.destroy,
        ).pack(side="right")

        # Scrollable list de campos (toma el espacio restante)
        scroll = ctk.CTkScrollableFrame(self, fg_color=theme.BG_CARD, corner_radius=10)
        scroll.pack(side="top", fill="both", expand=True, padx=22, pady=(0, 14))

        field_order = [
            "Nº Pedido", "Nº PO", "Nº Oferta",
            "Cliente", "Material", "Responsable", "Repsonsable",
            "Tipo Doc.", "Info/Review", "Crítico", "Nº Revisión",
            "Fecha Pedido", "Fecha Prevista", "Fecha Env. Doc.",
            "Días Envío", "Días Devolución",
            "Nº Doc. Cliente", "Seguimiento", "Historial Rev.",
        ]
        seen = set()
        for k in field_order + list(doc.keys()):
            if k in seen or k == "Estado" or k == "Título" or k == "Nº Doc. EIPSA":
                continue
            seen.add(k)
            val = doc.get(k, "")
            if val == "" or val is None:
                continue
            self._add_field(scroll, k, str(val))

    def _add_field(self, parent, label: str, value: str) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(
            row, text=label, font=(theme.FONT_FAMILY, 10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w", width=160,
        ).pack(side="left")
        ctk.CTkLabel(
            row, text=value or "—", font=theme.FONT_BODY,
            text_color=theme.TEXT_MAIN, anchor="w", justify="left", wraplength=420,
        ).pack(side="left", fill="x", expand=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(val) -> str:
    if val is None or val == "":
        return "—"
    s = str(val)
    # ISO date sin hora
    if len(s) >= 10 and s[4] == "-" and s[7] == "-" and "T" in s:
        return s.split("T")[0]
    return s[:120]


def _sort_key(v):
    """Devuelve siempre tuplas con shape uniforme (bucket:int, sort_value).

    Buckets: 0 = numérico, 1 = texto, 2 = vacío. Garantiza que sorted() no
    intente comparar str con int en posiciones distintas de la tupla.
    """
    if v is None or v == "":
        return (2, "")
    if isinstance(v, bool):
        return (0, float(v))
    if isinstance(v, (int, float)):
        try:
            return (0, float(v))
        except (TypeError, ValueError):
            return (1, str(v).lower())
    s = str(v).strip()
    if not s:
        return (2, "")
    try:
        return (0, float(s))
    except ValueError:
        return (1, s.lower())


def _row_tags(doc: dict) -> tuple:
    tags = []
    estado = str(doc.get("Estado", "") or "").lower().strip()
    critico = str(doc.get("Crítico", "") or "").lower().strip()
    es_critico = critico in ("sí", "si")

    if es_critico and "aprobado" not in estado:
        tags.append("row_critico")
    else:
        try:
            dias = int(float(doc.get("Días Envío", 0) or 0))
            if dias > 14 and "aprobado" not in estado:
                tags.append("row_warn")
        except (ValueError, TypeError):
            pass

    if "aprobado" in estado:
        tags.append("row_aprobado")
    elif "rechazado" in estado:
        tags.append("row_rechazado")
    elif any(s in estado for s in ("com.", "comentado", "menores", "mayores")):
        tags.append("row_comentado")
    elif "enviado" in estado:
        tags.append("row_enviado")
    elif not estado or "sin" in estado:
        tags.append("row_sin_enviar")

    return tuple(tags)


def _status_color(estado: str) -> str:
    e = estado.lower().strip()
    if "aprobado" in e: return theme.GREEN
    if "rechazado" in e: return theme.RED
    if any(s in e for s in ("comentado", "menores", "mayores")): return theme.AMBER
    if "enviado" in e: return theme.BLUE
    return theme.TEXT_MUTED
