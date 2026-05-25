"""Tabla scrollable construida sobre ttk.Treeview con look unificado al tema."""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from gui import theme


class DataTable(ctk.CTkFrame):
    """Wrapper de ttk.Treeview con scrollbar y estilo coherente."""

    def __init__(self, master, columns: list[str], on_double_click=None, selectmode: str = "browse", **kwargs):
        super().__init__(master, fg_color=theme.BG_CARD, corner_radius=12, **kwargs)

        self._columns = columns
        self._on_double_click = on_double_click
        self._selectmode = selectmode

        # Configurar estilo ttk para que case con el tema
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "DocFlow.Treeview",
            background=theme.BG_CARD,
            foreground=theme.TEXT_MAIN,
            fieldbackground=theme.BG_CARD,
            bordercolor=theme.BORDER,
            borderwidth=0,
            rowheight=30,
            font=theme.FONT_BODY,
        )
        style.map(
            "DocFlow.Treeview",
            background=[("selected", theme.ACCENT_SOFT)],
            foreground=[("selected", theme.TEXT_MAIN)],
        )
        style.configure(
            "DocFlow.Treeview.Heading",
            background=theme.BG_SIDEBAR,
            foreground=theme.TEXT_MUTED,
            borderwidth=0,
            relief="flat",
            font=(theme.FONT_FAMILY, 10, "bold"),
        )
        style.map(
            "DocFlow.Treeview.Heading",
            background=[("active", theme.BG_INPUT)],
        )

        container = tk.Frame(self, bg=theme.BG_CARD)
        container.pack(fill="both", expand=True, padx=8, pady=8)

        self.tree = ttk.Treeview(
            container,
            columns=columns,
            show="headings",
            style="DocFlow.Treeview",
            selectmode=self._selectmode,
        )

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=130, anchor="w", stretch=True)

        # Scrollbar vertical
        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        # Scrollbar horizontal (importante con muchas columnas)
        hsb = ttk.Scrollbar(container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        # Grid layout para que el scrollbar horizontal aparezca debajo de la tabla
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        if on_double_click:
            self.tree.bind("<Double-1>", self._on_dbl)
            self.tree.bind("<Return>", self._on_dbl)

        # Tags para estados (colorea texto)
        self.tree.tag_configure("status_aprobado", foreground=theme.GREEN)
        self.tree.tag_configure("status_rechazado", foreground=theme.RED)
        self.tree.tag_configure("status_comentado", foreground=theme.AMBER)
        self.tree.tag_configure("status_enviado", foreground=theme.BLUE)
        self.tree.tag_configure("status_sin_enviar", foreground=theme.TEXT_MUTED)
        self.tree.tag_configure("processed", foreground=theme.TEXT_MUTED)

    def _on_dbl(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        if self._on_double_click:
            self._on_double_click(item)

    def clear(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)

    def add_row(self, values: list, iid: str | None = None, tags: tuple = ()) -> str:
        return self.tree.insert("", "end", iid=iid, values=values, tags=tags)

    def set_columns_width(self, widths: dict[str, int]) -> None:
        for col, w in widths.items():
            if col in self._columns:
                self.tree.column(col, width=w)

    def set_columns_anchor(self, anchors: dict[str, str]) -> None:
        """Establece alineación por columna ('w', 'center', 'e')."""
        for col, a in anchors.items():
            if col in self._columns:
                self.tree.column(col, anchor=a)

    def freeze_widths(self) -> None:
        """Desactiva el auto-stretch de columnas para que aparezca scroll horizontal."""
        for col in self._columns:
            self.tree.column(col, stretch=False)

    def selected_iid(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def selected_iids(self) -> list[str]:
        return list(self.tree.selection())
