"""PillTable — tabla a medida con celdas ricas (pills de color, negrita, texto
de acento, cabecera oscura ordenable). Sustituye a ttk cuando se necesita
formato por celda (que ttk.Treeview no permite).

Rendimiento: usa un POOL de filas reutilizables. Las filas/celdas se crean una
sola vez y al refrescar (filtros, paginación, orden) solo se reconfigura el
texto/color de cada etiqueta — nunca se destruyen ni recrean widgets. Construida
con widgets `tk` nativos dentro de un Canvas scrollable (sin el rastreador de
escala de CustomTkinter).

Uso:
    cols = [{"key","label","min","stretch","anchor"}, ...]
    t = PillTable(parent, cols, on_double_click=fn, on_sort=fn)
    t.set_rows([("row_0", {"Estado": {"text": "Enviado", "pill": True,
                                       "fg": BLUE, "pill_bg": tint}, ...}), ...])
"""

import tkinter as tk

import customtkinter as ctk

from gui import theme

_PADX = 8


class PillTable(ctk.CTkFrame):
    def __init__(self, master, columns, on_double_click=None, on_select=None,
                 on_sort=None, rowheight=40, **kwargs):
        super().__init__(master, fg_color=theme.BG_CARD, corner_radius=12,
                         border_width=1, border_color=theme.BORDER, **kwargs)
        self._columns = columns
        self._on_double_click = on_double_click
        self._on_select = on_select
        self._on_sort = on_sort
        self._rowheight = rowheight
        self._ctx_builder = None
        self._pool: list[dict] = []
        self._rowid_pos: dict[str, int] = {}
        self._selected: str | None = None
        self._header_labels: dict[str, tk.Label] = {}

        wrap = tk.Frame(self, bg=theme.BG_CARD)
        wrap.pack(fill="both", expand=True, padx=8, pady=8)
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(1, weight=1)

        # ── Cabecera ──────────────────────────────────────────────────────────
        self._header = tk.Frame(wrap, bg=theme.TABLE_HEADER_BG, height=34)
        self._header.grid(row=0, column=0, sticky="ew")
        self._header.grid_propagate(False)
        self._apply_cols(self._header)
        for i, col in enumerate(columns):
            lbl = tk.Label(self._header, text=col["label"].upper(),
                           bg=theme.TABLE_HEADER_BG, fg=theme.TABLE_HEADER_FG,
                           font=theme.font(10, "bold"),
                           anchor="center" if col.get("anchor") == "center" else "w")
            lbl.grid(row=0, column=i, sticky="ew", padx=_PADX, pady=6)
            if on_sort:
                lbl.configure(cursor="hand2")
                lbl.bind("<Button-1>", lambda e, k=col["key"]: self._on_sort(k))
            self._header_labels[col["key"]] = lbl

        # ── Cuerpo scrollable ────────────────────────────────────────────────
        self._canvas = tk.Canvas(wrap, bg=theme.BG_CARD, highlightthickness=0, bd=0)
        self._vsb = tk.Scrollbar(wrap, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self._canvas.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self._vsb.grid(row=1, column=1, sticky="ns", pady=(4, 0))
        self._inner = tk.Frame(self._canvas, bg=theme.BG_CARD)
        self._inner.grid_columnconfigure(0, weight=1)
        self._win = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfigure(self._win, width=e.width))
        # Actualiza el scrollregion automáticamente (diferido a idle) cuando el
        # contenido cambia de tamaño — evita forzar update_idletasks por render.
        self._inner.bind("<Configure>",
                         lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        # Rueda del ratón: enlazada DIRECTAMENTE al canvas y al frame interior (no
        # con bind_all, que secuestraría la rueda del resto de la app). Cada fila
        # también la enlaza (ver _bind_row) para que funcione encima de las filas.
        self._canvas.bind("<MouseWheel>", self._on_wheel)
        self._inner.bind("<MouseWheel>", self._on_wheel)

    # ── Helpers de layout ────────────────────────────────────────────────────

    def _apply_cols(self, frame) -> None:
        for i, col in enumerate(self._columns):
            frame.grid_columnconfigure(
                i, weight=1 if col.get("stretch") else 0, minsize=col.get("min", 60))

    def _on_wheel(self, event) -> None:
        try:
            self._canvas.yview_scroll(int(-event.delta / 120), "units")
        except Exception:
            pass

    @staticmethod
    def _tf(size: int = 11, bold: bool = False):
        return theme.font(size, "bold") if bold else theme.font(size)

    # ── API ───────────────────────────────────────────────────────────────────

    def set_context_menu(self, builder) -> None:
        self._ctx_builder = builder

    def set_sort_arrow(self, key: str | None, asc: bool) -> None:
        for k, lbl in self._header_labels.items():
            base = next(c["label"] for c in self._columns if c["key"] == k).upper()
            lbl.configure(text=f"{base}  {'▲' if asc else '▼'}" if k == key else base)

    def set_rows(self, rows: list) -> None:
        """Refresca la tabla reutilizando filas del pool (rows = [(rowid, cells)])."""
        self._ensure_pool(len(rows))
        self._rowid_pos = {}
        for i, (rowid, cells) in enumerate(rows):
            ro = self._pool[i]
            base = theme.BG_CARD if (i % 2 == 0) else theme.ROW_STRIPE
            ro["rowid"] = rowid
            ro["base"] = base
            ro["frame"].configure(bg=base)
            self._inner.grid_rowconfigure(i, minsize=self._rowheight)
            ro["frame"].grid(row=i, column=0, sticky="ew", pady=1)
            for ci, col in enumerate(self._columns):
                self._update_cell(ro["cells"][ci], cells.get(col["key"]) or {}, base)
            self._rowid_pos[rowid] = i
        # Ocultar filas sobrantes del pool
        for i in range(len(rows), len(self._pool)):
            self._pool[i]["frame"].grid_remove()
            self._pool[i]["rowid"] = None
        self._selected = None
        self._canvas.yview_moveto(0)

    def clear(self) -> None:
        for ro in self._pool:
            ro["frame"].grid_remove()
            ro["rowid"] = None
        self._rowid_pos = {}
        self._selected = None

    def selected_id(self) -> str | None:
        return self._selected

    # ── Construcción / actualización de filas ────────────────────────────────

    def _ensure_pool(self, n: int) -> None:
        while len(self._pool) < n:
            self._pool.append(self._new_row())

    def _new_row(self) -> dict:
        frame = tk.Frame(self._inner, bg=theme.BG_CARD, height=self._rowheight)
        frame.grid_propagate(False)
        self._apply_cols(frame)
        frame.grid_rowconfigure(0, weight=1)  # las celdas llenan el alto de la fila
        cells = []
        for i, col in enumerate(self._columns):
            anchor = col.get("anchor", "w")
            cont = tk.Frame(frame, bg=theme.BG_CARD)
            cont.grid(row=0, column=i, sticky="nsew", padx=1)
            lbl = tk.Label(cont, bg=theme.BG_CARD, font=self._tf(11),
                           anchor="center" if anchor == "center" else "w")
            if anchor == "center":
                lbl.place(relx=0.5, rely=0.5, anchor="center")
            else:
                lbl.place(relx=0.0, rely=0.5, anchor="w", x=6, relwidth=1.0)
            cells.append({"cont": cont, "label": lbl, "anchor": anchor, "pill": False})
        ro = {"frame": frame, "cells": cells, "rowid": None, "base": theme.BG_CARD}
        self._bind_row(ro)
        return ro

    def _update_cell(self, cell: dict, spec: dict, base: str) -> None:
        lbl = cell["label"]
        cell["cont"].configure(bg=base)
        text = str(spec.get("text", ""))
        if spec.get("pill") and text:
            lbl.configure(text=f" {text} ", bg=spec.get("pill_bg", theme.BG_INPUT),
                          fg=spec.get("fg", theme.TEXT_MAIN), font=self._tf(10, True), padx=4)
            cell["pill"] = True
        else:
            lbl.configure(text=text, bg=base, fg=spec.get("fg", theme.TEXT_MAIN),
                          font=self._tf(11, bool(spec.get("bold"))), padx=0)
            cell["pill"] = False

    # ── Interacción ─────────────────────────────────────────────────────────

    def _bind_row(self, ro: dict) -> None:
        def on_click(_e):
            if ro["rowid"]:
                self.select(ro["rowid"])
        def on_dbl(_e):
            if ro["rowid"] and self._on_double_click:
                self._on_double_click(ro["rowid"])
        def on_ctx(e):
            if not ro["rowid"]:
                return
            self.select(ro["rowid"])
            if self._ctx_builder:
                self._show_menu(e, ro["rowid"])
        widgets = [ro["frame"]]
        for c in ro["cells"]:
            widgets += [c["cont"], c["label"]]
        for w in widgets:
            w.bind("<Button-1>", on_click)
            w.bind("<Double-Button-1>", on_dbl)
            w.bind("<Button-3>", on_ctx)
            w.bind("<MouseWheel>", self._on_wheel)

    def _paint(self, rowid: str, bg: str) -> None:
        ro = self._pool[self._rowid_pos[rowid]]
        ro["frame"].configure(bg=bg)
        for c in ro["cells"]:
            c["cont"].configure(bg=bg)
            if not c["pill"]:
                c["label"].configure(bg=bg)

    def select(self, rowid: str) -> None:
        if self._selected and self._selected in self._rowid_pos:
            self._paint(self._selected, self._pool[self._rowid_pos[self._selected]]["base"])
        self._selected = rowid
        if rowid in self._rowid_pos:
            self._paint(rowid, theme.ACCENT_SOFT)
        if self._on_select:
            self._on_select(rowid)

    def _show_menu(self, event, rowid: str) -> None:
        try:
            items = self._ctx_builder(rowid)
        except Exception:
            items = None
        if not items:
            return
        menu = tk.Menu(self, tearoff=0, bg=theme.BG_CARD, fg=theme.TEXT_MAIN,
                       activebackground=theme.ACCENT, activeforeground="#FFFFFF",
                       bd=0, relief="flat")
        for label, cmd in items:
            if label == "-" or cmd is None:
                menu.add_separator()
            else:
                menu.add_command(label=label, command=cmd)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
