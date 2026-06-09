"""Tabla scrollable construida sobre ttk.Treeview con look unificado al tema.

Mejoras de legibilidad:
- Zebra striping automático (filas alternas) — se inyecta como primer tag,
  de modo que cualquier tag de estado de la vista (background) lo sobrescribe.
- Cabecera con contraste, padding y separador.
- Resalte de la fila bajo el cursor (hover).
- Selección destacada con el color de acento.
- Filas más altas para respirar.
"""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from gui import theme

# Estilo único por proceso — un contador para que cada DataTable tenga su
# propio nombre de estilo y no se pisen configuraciones entre instancias.
_STYLE_SEQ = [0]


class DataTable(ctk.CTkFrame):
    """Wrapper de ttk.Treeview con scrollbar y estilo coherente."""

    ROW_HEIGHT = 34

    def __init__(self, master, columns: list[str], on_double_click=None,
                 selectmode: str = "browse", striped: bool = True, **kwargs):
        super().__init__(
            master, fg_color=theme.BG_CARD, corner_radius=12,
            border_width=1, border_color=theme.BORDER, **kwargs,
        )

        self._columns = columns
        self._on_double_click = on_double_click
        self._selectmode = selectmode
        self._striped = striped
        self._row_count = 0           # para alternar zebra
        self._base_tags: dict[str, tuple] = {}  # iid → tags base (sin hover)
        self._hover_iid: str | None = None
        self._ctx_builder = None      # builder(iid, col_idx) -> items | None
        self._sb_visible: dict[str, bool | None] = {"v": None, "h": None}

        _STYLE_SEQ[0] += 1
        self._style_name = f"DocFlow{_STYLE_SEQ[0]}.Treeview"

        # ── Estilo ttk ──────────────────────────────────────────────────
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            self._style_name,
            background=theme.BG_CARD,
            foreground=theme.TEXT_MAIN,
            fieldbackground=theme.BG_CARD,
            bordercolor=theme.BG_CARD,   # sin separadores 3D
            borderwidth=0,
            relief="flat",
            rowheight=self.ROW_HEIGHT,
            font=theme.FONT_BODY,
        )
        # Aplana cualquier borde 3D residual del tema clam (quita el borde
        # del field, dejando solo el área de filas)
        try:
            style.layout(self._style_name, [
                ("Treeview.treearea", {"sticky": "nswe"}),
            ])
        except tk.TclError:
            pass
        style.map(
            self._style_name,
            background=[("selected", theme.ACCENT)],
            foreground=[("selected", "#FFFFFF")],
        )
        heading_style = f"{self._style_name}.Heading"
        style.configure(
            heading_style,
            background=theme.TABLE_HEADER_BG,
            foreground=theme.TABLE_HEADER_FG,
            borderwidth=0,
            relief="flat",
            padding=(10, 9),
            font=theme.font(10, "bold"),
        )
        style.map(
            heading_style,
            background=[("active", theme.BG_INPUT)],
            foreground=[("active", theme.TEXT_MAIN)],
        )

        # ── Contenedor + Treeview ───────────────────────────────────────
        container = tk.Frame(self, bg=theme.BG_CARD)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        self.tree = ttk.Treeview(
            container,
            columns=columns,
            show="headings",
            style=self._style_name,
            selectmode=self._selectmode,
        )

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=130, anchor="w", stretch=True)

        # Scrollbars modernos (CTkScrollbar) — finos, sin flechas, con thumb
        # redondeado que combina con el tema. Se auto-ocultan si no hacen falta.
        self._vsb = ctk.CTkScrollbar(
            container, command=self.tree.yview,
            fg_color=theme.BG_CARD,
            button_color=theme.BORDER_STRONG,
            button_hover_color=theme.TEXT_MUTED,
            corner_radius=8, width=12,
        )
        self._hsb = ctk.CTkScrollbar(
            container, orientation="horizontal", command=self.tree.xview,
            fg_color=theme.BG_CARD,
            button_color=theme.BORDER_STRONG,
            button_hover_color=theme.TEXT_MUTED,
            corner_radius=8, height=12,
        )
        self.tree.configure(
            yscrollcommand=lambda f, l: self._scroll_set("v", self._vsb, f, l),
            xscrollcommand=lambda f, l: self._scroll_set("h", self._hsb, f, l),
        )

        self.tree.grid(row=0, column=0, sticky="nsew")
        self._vsb.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self._hsb.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        if on_double_click:
            self.tree.bind("<Double-1>", self._on_dbl)
            self.tree.bind("<Return>", self._on_dbl)

        # Rueda del ratón: vertical, y Shift+rueda para horizontal.
        self.tree.bind("<MouseWheel>", self._on_wheel)
        self.tree.bind("<Shift-MouseWheel>", self._on_wheel_h)

        # Hover por fila
        self.tree.bind("<Motion>", self._on_motion)
        self.tree.bind("<Leave>", self._on_leave)

        # ── Tags base ───────────────────────────────────────────────────
        # Zebra: dos bandas. 'oddrow' = BG_CARD (igual que el fondo) para que
        # se note solo la banda alterna. 'evenrow' = ROW_STRIPE.
        self.tree.tag_configure("oddrow", background=theme.BG_CARD)
        self.tree.tag_configure("evenrow", background=theme.ROW_STRIPE)
        self.tree.tag_configure("rowhover", background=theme.ROW_HOVER)

        # Tags de estado (foreground) — compatibles con zebra (no tocan bg)
        self.tree.tag_configure("status_aprobado", foreground=theme.GREEN)
        self.tree.tag_configure("status_rechazado", foreground=theme.RED)
        self.tree.tag_configure("status_comentado", foreground=theme.AMBER)
        self.tree.tag_configure("status_enviado", foreground=theme.BLUE)
        self.tree.tag_configure("status_sin_enviar", foreground=theme.TEXT_MUTED)
        self.tree.tag_configure("processed", foreground=theme.TEXT_MUTED)

    # ── Hover ───────────────────────────────────────────────────────────────

    def _on_motion(self, event):
        iid = self.tree.identify_row(event.y)
        if iid == self._hover_iid:
            return
        # Restaurar la fila anterior
        if self._hover_iid and self._hover_iid in self._base_tags:
            self.tree.item(self._hover_iid, tags=self._base_tags[self._hover_iid])
        # Aplicar hover a la nueva (hover como ÚLTIMO tag → su bg gana)
        if iid:
            base = self._base_tags.get(iid, ())
            self.tree.item(iid, tags=base + ("rowhover",))
        self._hover_iid = iid

    def _on_leave(self, _event):
        if self._hover_iid and self._hover_iid in self._base_tags:
            self.tree.item(self._hover_iid, tags=self._base_tags[self._hover_iid])
        self._hover_iid = None

    # ── Rueda del ratón ─────────────────────────────────────────────────────

    def _on_wheel(self, event):
        self.tree.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _on_wheel_h(self, event):
        self.tree.xview_scroll(int(-event.delta / 120), "units")
        return "break"

    # ── Scrollbars (auto-ocultar) ───────────────────────────────────────────

    def _scroll_set(self, key: str, sb, first, last) -> None:
        """Conecta el scroll del Treeview con el CTkScrollbar y lo oculta si
        el contenido cabe entero (first<=0 y last>=1). Solo togglea cuando
        cambia el estado para evitar parpadeos."""
        try:
            visible = not (float(first) <= 0.0 and float(last) >= 1.0)
        except (TypeError, ValueError):
            visible = True
        if visible != self._sb_visible.get(key):
            self._sb_visible[key] = visible
            if visible:
                sb.grid()
            else:
                sb.grid_remove()
        sb.set(first, last)

    # ── Menú contextual ─────────────────────────────────────────────────────

    def set_context_menu(self, builder) -> None:
        """Registra un builder de menú contextual (click derecho).

        `builder(iid, col_idx) -> list[(label, callback)] | None`
        Usa la tupla ('-', None) para insertar un separador.
        """
        self._ctx_builder = builder
        self.tree.bind("<Button-3>", self._on_right_click)

    def _on_right_click(self, event) -> None:
        if self._ctx_builder is None:
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        # Selecciona la fila clicada (salvo que ya esté en una multi-selección)
        if iid not in self.tree.selection():
            self.tree.selection_set(iid)
        col = self.tree.identify_column(event.x)
        col_idx = (int(col[1:]) - 1) if col and col.startswith("#") else -1
        try:
            items = self._ctx_builder(iid, col_idx)
        except Exception:
            items = None
        if not items:
            return
        menu = tk.Menu(
            self, tearoff=0,
            bg=theme.BG_CARD, fg=theme.TEXT_MAIN,
            activebackground=theme.ACCENT, activeforeground="#FFFFFF",
            bd=0, relief="flat", font=theme.FONT_BODY,
        )
        for label, cmd in items:
            if label == "-" or cmd is None:
                menu.add_separator()
            else:
                menu.add_command(label=label, command=cmd)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ── Helpers de datos / portapapeles ─────────────────────────────────────

    def row_values(self, iid: str) -> tuple:
        return self.tree.item(iid, "values")

    def cell_value(self, iid: str, col_idx: int):
        vals = self.tree.item(iid, "values")
        if 0 <= col_idx < len(vals):
            return vals[col_idx]
        return ""

    def copy_to_clipboard(self, text) -> None:
        self.clipboard_clear()
        self.clipboard_append(str(text))
        try:
            from gui.widgets import ui
            preview = str(text)
            ui.toast(self, "Copiado", preview if len(preview) <= 48 else preview[:48] + "…",
                     kind="success")
        except Exception:
            pass

    # ── Eventos ─────────────────────────────────────────────────────────────

    def _on_dbl(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        if self._on_double_click:
            self._on_double_click(item)

    # ── API ─────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_count = 0
        self._base_tags.clear()
        self._hover_iid = None

    def add_row(self, values: list, iid: str | None = None, tags: tuple = ()) -> str:
        # Zebra como PRIMER tag → cualquier tag de estado con background lo pisa.
        if self._striped:
            zebra = ("evenrow",) if (self._row_count % 2) else ("oddrow",)
            final_tags = zebra + tuple(tags)
        else:
            final_tags = tuple(tags)
        self._row_count += 1

        new_iid = self.tree.insert("", "end", iid=iid, values=values, tags=final_tags)
        self._base_tags[new_iid] = final_tags
        return new_iid

    def set_columns_width(self, widths: dict[str, int]) -> None:
        for col, w in widths.items():
            if col in self._columns:
                self.tree.column(col, width=w)

    def set_columns_anchor(self, anchors: dict[str, str]) -> None:
        """Establece alineación por columna ('w', 'center', 'e').

        También centra la cabecera de las columnas centradas para coherencia.
        """
        for col, a in anchors.items():
            if col in self._columns:
                self.tree.column(col, anchor=a)
                # Cabecera alineada igual que el contenido
                self.tree.heading(col, anchor=a)

    def freeze_widths(self) -> None:
        """Desactiva el auto-stretch de columnas para que aparezca scroll horizontal."""
        for col in self._columns:
            self.tree.column(col, stretch=False)

    def set_columns_stretch(self, mapping: dict[str, bool]) -> None:
        """Activa/desactiva stretch por columna (la que estira absorbe el hueco)."""
        for col, val in mapping.items():
            if col in self._columns:
                self.tree.column(col, stretch=bool(val))

    def autofit_columns(self, min_w: int = 46, max_w: int = 360,
                        padding: int = 26, max_per: dict[str, int] | None = None) -> None:
        """Ajusta los anchos al contenido y los comprime para que la tabla
        entre COMPLETA sin scroll horizontal.

        - Mide el texto (cabecera + celdas) con la fuente del cuerpo.
        - Si la suma supera el ancho disponible, escala todo proporcionalmente.
        - Si sobra espacio, `stretch=True` reparte el resto.
        """
        import tkinter.font as tkfont

        try:
            body = tkfont.Font(font=theme.FONT_BODY)
        except Exception:
            return
        max_per = max_per or {}

        widths: dict[str, int] = {}
        for col in self._columns:
            try:
                head = str(self.tree.heading(col).get("text", col))
            except Exception:
                head = col
            w = body.measure(head) + padding + 14  # +14 por el icono de orden/flecha
            for iid in self.tree.get_children():
                val = self.tree.set(iid, col)
                if val:
                    w = max(w, body.measure(str(val)) + padding)
            cap = max_per.get(col, max_w)
            widths[col] = max(min_w, min(cap, w))

        total = sum(widths.values()) or 1

        # Ancho disponible real de la tabla. Si la tabla aún no está mapeada
        # (winfo_width pequeño/no fiable), caemos al ancho del toplevel; y si
        # tampoco es fiable, NO comprimimos (mejor scroll que columnas a 46px).
        self.update_idletasks()
        avail = self.tree.winfo_width()
        if avail < 200:
            try:
                top_w = self.winfo_toplevel().winfo_width()
                if top_w > 200:
                    avail = top_w - 90
            except Exception:
                pass
        if avail < 200:
            avail = total  # ancho desconocido → no comprimir

        if total > avail:
            scale = avail / total
            widths = {c: max(min_w, int(w * scale)) for c, w in widths.items()}

        for col, w in widths.items():
            self.tree.column(col, width=w, stretch=True)

    def selected_iid(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def selected_iids(self) -> list[str]:
        return list(self.tree.selection())
