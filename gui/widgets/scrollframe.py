"""ScrollFrame — marco scrollable ligero en tk nativo.

Reemplazo directo de `CTkScrollableFrame` para reducir el coste de repintado:
CTkScrollableFrame apila ~3-4 canvas de CustomTkinter (marco exterior, canvas,
scrollbar y marco interior), todos repintándose en cada `<Configure>`. Este
widget usa Canvas + Frame + Scrollbar de tk → cero canvas de CTk en el contenedor
(el maximizar/restaurar va mucho más suelto).

Drop-in: los hijos se parentan a la instancia (van al marco interior); los
métodos de geometría (pack/grid/place y *_forget/remove) se redirigen al
contenedor exterior para que se ubique bien en el layout del padre. El scrollbar
se auto-oculta cuando el contenido cabe.
"""

import tkinter as tk

from gui import theme

# kwargs propios de CustomTkinter que tk.Frame no entiende (se descartan)
_CTK_ONLY = {
    "corner_radius", "border_width", "border_color", "border_spacing",
    "scrollbar_button_color", "scrollbar_button_hover_color",
    "scrollbar_fg_color", "label_text", "label_font", "label_fg_color",
    "label_text_color", "label_anchor", "orientation",
}


class ScrollFrame(tk.Frame):
    def __init__(self, master, fg_color=None, width=None, height=None, **kwargs):
        for k in _CTK_ONLY:
            kwargs.pop(k, None)
        kwargs.pop("width", None)
        kwargs.pop("height", None)
        bg = theme.BG_PAGE if fg_color in (None, "transparent") else fg_color
        self._bg = bg

        self._outer = tk.Frame(master, bg=bg)
        if width:
            self._outer.configure(width=int(width))
        if height:
            self._outer.configure(height=int(height))
        if width or height:
            self._outer.grid_propagate(False)
        self._outer.grid_rowconfigure(0, weight=1)
        self._outer.grid_columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(self._outer, bg=bg, highlightthickness=0, bd=0)
        self._vsb = tk.Scrollbar(self._outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._vsb.grid(row=0, column=1, sticky="ns")

        super().__init__(self._canvas, bg=bg, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self._win = self._canvas.create_window((0, 0), window=self, anchor="nw")

        self._last_w = 0
        self._sr_after = None
        self._canvas.bind("<Configure>", self._on_canvas_cfg)
        self.bind("<Configure>", self._on_inner_cfg)
        # Rueda (patrón estilo CTkScrollableFrame): al entrar en el área se
        # engancha <MouseWheel> globalmente y el handler comprueba que el widget
        # bajo el cursor pertenezca a ESTE canvas. Así funciona también sobre las
        # tarjetas hijas, y cede a scrollers anidados (PillTable/Treeview) sin
        # doble-scroll. No se desengancha en Leave: el siguiente Enter reasigna.
        self._canvas.bind("<Enter>", self._wheel_on)
        self.bind("<Enter>", self._wheel_on)

    # ── Redibujado eficiente ────────────────────────────────────────────────
    def _on_canvas_cfg(self, e) -> None:
        if e.width != self._last_w:
            self._last_w = e.width
            self._canvas.itemconfigure(self._win, width=e.width)

    def _on_inner_cfg(self, _e) -> None:
        if self._sr_after is not None:
            try:
                self.after_cancel(self._sr_after)
            except Exception:
                pass
        self._sr_after = self.after_idle(self._update_sr)

    def _update_sr(self) -> None:
        self._sr_after = None
        try:
            bbox = self._canvas.bbox("all")
            if not bbox:
                return
            self._canvas.configure(scrollregion=bbox)
            # Auto-ocultar el scrollbar si el contenido cabe en la vista
            if (bbox[3] - bbox[1]) > self._canvas.winfo_height():
                if not self._vsb.winfo_ismapped():
                    self._vsb.grid()
            elif self._vsb.winfo_ismapped():
                self._vsb.grid_remove()
        except Exception:
            pass

    # ── Rueda del ratón ──────────────────────────────────────────────────────
    def _wheel_on(self, _e) -> None:
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _on_wheel(self, e) -> None:
        # Sube por la jerarquía del widget bajo el cursor: si llega a NUESTRO
        # canvas, hace scroll; si antes encuentra otro Canvas/Treeview (scroller
        # anidado, p.ej. una PillTable o DataTable dentro), cede y no hace nada.
        node = getattr(e, "widget", None)
        while node is not None:
            if node is self._canvas:
                try:
                    self._canvas.yview_scroll(int(-e.delta / 120), "units")
                except Exception:
                    pass
                return "break"
            try:
                cls = node.winfo_class()
            except Exception:
                cls = ""
            # Ceder SOLO ante scrollers anidados REALES. Ojo: los widgets de
            # CustomTkinter (tarjetas, botones…) usan un Canvas interno de dibujo
            # que también es clase "Canvas" pero NO tiene yscrollcommand — sobre
            # ellos debemos seguir subiendo hasta nuestro canvas, no ceder.
            if cls in ("Treeview", "Text", "Listbox"):
                return
            if cls == "Canvas":
                try:
                    if node.cget("yscrollcommand"):
                        return  # canvas con scroll propio (PillTable / ScrollFrame anidado)
                except Exception:
                    pass
            node = getattr(node, "master", None)

    # ── Redirección de geometría al contenedor exterior ──────────────────────
    def pack(self, **kw):
        self._outer.pack(**kw)
        return self

    def grid(self, **kw):
        self._outer.grid(**kw)
        return self

    def place(self, **kw):
        self._outer.place(**kw)
        return self

    def pack_forget(self):
        self._outer.pack_forget()

    def grid_forget(self):
        self._outer.grid_forget()

    def grid_remove(self):
        self._outer.grid_remove()

    def place_forget(self):
        self._outer.place_forget()
