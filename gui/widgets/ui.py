"""Design system compartido — helpers visuales y de feedback reutilizables.

Fuente única para cabeceras de sección, badges, tarjetas KPI, barras, colores
por tier y mezcla de color, además de toast/confirm. Antes estaban duplicados
en pedidos/informes/ofertas/docusign; ahora un cambio de estilo se propaga a
todas las vistas desde aquí.
"""

import customtkinter as ctk

from gui import theme


# ── Colores por tier ──────────────────────────────────────────────────────────

def pct_color(pct: float) -> str:
    if pct >= 75:
        return theme.GREEN
    if pct >= 50:
        return theme.AMBER
    return theme.RED


def days_color(d: float) -> str:
    if d > 20:
        return theme.RED
    if d > 10:
        return theme.AMBER
    return theme.GREEN


def score_color(s: float) -> str:
    if s >= 80:
        return theme.GREEN
    if s >= 50:
        return theme.AMBER
    return theme.RED


_AVATAR_COLORS = ["#3B82F6", "#16A34A", "#D97706", "#DB2777",
                  "#DC2626", "#A855F7", "#14B8A6", "#CA8A04"]


def avatar_color(iniciales: str) -> str:
    h = 0
    for ch in str(iniciales or ""):
        h = ord(ch) + ((h << 5) - h)
    return _AVATAR_COLORS[abs(h) % len(_AVATAR_COLORS)]


def hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def blend(base: str, bg: str, t: float) -> str:
    """Mezcla `base` sobre `bg` con intensidad t∈[0,1] → hex. t=0 → bg, t=1 → base."""
    t = max(0.0, min(1.0, t))
    b = hex_to_rgb(base)
    g = hex_to_rgb(bg)
    r = tuple(round(g[i] + (b[i] - g[i]) * t) for i in range(3))
    return f"#{r[0]:02X}{r[1]:02X}{r[2]:02X}"


# ── Componentes ────────────────────────────────────────────────────────────────

def section_header(parent, text: str, color: str | None = None):
    """Cabecera de sección: barra de acento vertical + etiqueta en mayúsculas."""
    color = color or theme.ACCENT
    row = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkFrame(row, fg_color=color, width=3, height=14, corner_radius=2).pack(
        side="left", padx=(0, theme.SPACE_2))
    ctk.CTkLabel(row, text=text.upper(), font=theme.FONT_LABEL,
                 text_color=theme.TEXT_SUB, anchor="w").pack(side="left")
    return row


def badge(parent, text: str, color: str, fg: str | None = None):
    """Pill coloreada (texto en `color`, fondo `fg` o BG_INPUT)."""
    return ctk.CTkLabel(parent, text=f"  {text}  ", font=theme.FONT_TINY, text_color=color,
                        fg_color=fg or theme.BG_INPUT, corner_radius=8, height=22)


_KPI_H = 92  # alto fijo común para tarjetas KPI


def kpi_card(parent, label, value, color, sub: str = "", height: int = _KPI_H):
    """Tarjeta KPI de altura fija (reserva línea de subtítulo aunque vaya vacía)."""
    box = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=10,
                       border_width=1, border_color=theme.BORDER, height=height)
    box.pack_propagate(False)
    ctk.CTkLabel(box, text=str(label).upper(), font=theme.FONT_LABEL,
                 text_color=theme.TEXT_MUTED, anchor="w").pack(
        anchor="w", padx=theme.SPACE_3, pady=(theme.SPACE_3, 0))
    ctk.CTkLabel(box, text=str(value), font=theme.font(22, "bold"),
                 text_color=color, anchor="w").pack(anchor="w", padx=theme.SPACE_3, pady=(2, 0))
    ctk.CTkLabel(box, text=sub or " ", font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                 anchor="w").pack(anchor="w", padx=theme.SPACE_3, pady=(0, theme.SPACE_2))
    return box


def bar_row(parent, label: str, value, ratio: float, color: str, value_text=None):
    """Fila: etiqueta + barra horizontal proporcional + valor a la derecha."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=2)
    ctk.CTkLabel(row, text=label, font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                 anchor="w", width=150).pack(side="left")
    track = ctk.CTkFrame(row, height=10, fg_color=theme.BORDER, corner_radius=5)
    track.pack(side="left", fill="x", expand=True, padx=theme.SPACE_2)
    fill = ctk.CTkFrame(track, fg_color=color, corner_radius=5)
    fill.place(relx=0, rely=0, relheight=1, relwidth=max(0.02, min(1.0, ratio)))
    ctk.CTkLabel(row, text=value_text if value_text is not None else str(value),
                 font=theme.FONT_SMALL_BOLD, text_color=color, width=60, anchor="e").pack(side="right")
    return row


# ── Feedback (toast / confirmación) ────────────────────────────────────────────

def toast(widget, title: str, message: str = "", kind: str = "info") -> None:
    """Muestra un toast in-app usando el NotificationManager de la ventana raíz."""
    try:
        nm = getattr(widget.winfo_toplevel(), "notifier", None)
        if nm is not None:
            nm.notify(title, message, kind=kind, native=False)
    except Exception:
        pass


def confirm(parent, title: str, message: str) -> bool:
    """Diálogo de confirmación Sí/No (para acciones sensibles)."""
    from tkinter import messagebox
    return bool(messagebox.askyesno(title, message, parent=parent))


# ── Estructura de página ───────────────────────────────────────────────────────

class PageHeader:
    """Referencias de una cabecera de página: `frame`, `title`, `subtitle`
    (puede ser None) y `actions` (frame a la derecha para botones/estado)."""

    __slots__ = ("frame", "title", "subtitle", "actions")

    def __init__(self, frame, title, subtitle, actions):
        self.frame = frame
        self.title = title
        self.subtitle = subtitle
        self.actions = actions


def page_header(parent, title: str, subtitle: str = "", icon: str | None = None,
                icon_color: str | None = None, pad_bottom: int = theme.SPACE_1,
                help_key: str | None = None) -> PageHeader:
    """Cabecera estándar de sección: título (+icono opcional), subtítulo y una
    zona de acciones a la derecha. Misma respiración en todas las vistas:
    padx SPACE_6 · pady (SPACE_5, pad_bottom).

    help_key → añade el botón «?» (ayuda contextual de gui/help.py; también F1)."""
    header = ctk.CTkFrame(parent, fg_color="transparent")
    header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, pad_bottom))

    left = ctk.CTkFrame(header, fg_color="transparent")
    left.pack(side="left", fill="x", expand=True)
    title_row = ctk.CTkFrame(left, fg_color="transparent")
    title_row.pack(anchor="w")
    if icon:
        ctk.CTkLabel(title_row, text=icon, font=theme.font(20, "bold"),
                     text_color=icon_color or theme.ACCENT).pack(side="left", padx=(0, theme.SPACE_2))
    lbl_title = ctk.CTkLabel(title_row, text=title, font=theme.FONT_TITLE,
                             text_color=theme.TEXT_MAIN, anchor="w")
    lbl_title.pack(side="left")

    lbl_sub = None
    if subtitle:
        lbl_sub = ctk.CTkLabel(left, text=subtitle, font=theme.FONT_SUBTITLE,
                               text_color=theme.TEXT_SUB, anchor="w")
        lbl_sub.pack(anchor="w", pady=(theme.SPACE_1, 0))

    actions = ctk.CTkFrame(header, fg_color="transparent")
    actions.pack(side="right", anchor="n")
    if help_key:
        def _help(_e=None, k=help_key, p=parent):
            from gui.help import open_help
            open_help(p.winfo_toplevel(), k)
        btn = button(actions, "?", "outline", size="xs", width=30, font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_SUB, command=_help)
        btn.pack(side="right", padx=(theme.SPACE_2, 0))
        tooltip(btn, "Ayuda de esta sección (F1)")
    return PageHeader(header, lbl_title, lbl_sub, actions)


# ── Tooltip ────────────────────────────────────────────────────────────────────

class _Tooltip:
    """Globo de ayuda: aparece tras `delay` ms con el ratón encima, desaparece
    al salir o pulsar. `show()`/`hide()` permiten controlarlo por código."""

    def __init__(self, widget, text: str, delay: int):
        self.widget, self.text, self.delay = widget, text, delay
        self.win = None
        self._job = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def show(self) -> None:
        self._job = None
        if self.win is not None or not self.text:
            return
        try:
            w = self.widget
            x = w.winfo_rootx() + 12
            y = w.winfo_rooty() + w.winfo_height() + 6
            win = ctk.CTkToplevel(w)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(fg_color=theme.BG_CARD)
            ctk.CTkLabel(win, text=self.text, font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                         fg_color=theme.BG_CARD, corner_radius=6, justify="left",
                         wraplength=320).pack(padx=theme.SPACE_2, pady=theme.SPACE_1)
            win.geometry(f"+{x}+{y}")
            self.win = win
        except Exception:  # noqa: BLE001 — un tooltip nunca debe romper nada
            self.win = None

    def hide(self, _e=None) -> None:
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except Exception:  # noqa: BLE001
                pass
            self._job = None
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:  # noqa: BLE001
                pass
            self.win = None

    def _enter(self, _e=None) -> None:
        self.hide()
        self._job = self.widget.after(self.delay, self.show)


def tooltip(widget, text: str, delay: int = 450) -> _Tooltip:
    """Añade un globo de ayuda al widget. Devuelve el controlador (show/hide)."""
    return _Tooltip(widget, text, delay)


def tabview(parent, command=None, **kwargs) -> ctk.CTkTabview:
    """CTkTabview con el estilo de la app (antes copiado a mano en 4 vistas)."""
    opts = dict(
        fg_color=theme.BG_PAGE,
        segmented_button_fg_color=theme.BG_CARD,
        segmented_button_selected_color=theme.ACCENT,
        segmented_button_selected_hover_color=theme.ACCENT_HOVER,
        segmented_button_unselected_color=theme.BG_CARD,
        segmented_button_unselected_hover_color=theme.BG_INPUT,
        text_color=theme.TEXT_MAIN,
    )
    if command is not None:
        opts["command"] = command
    opts.update(kwargs)
    return ctk.CTkTabview(parent, **opts)


# Tamaños reales que usa la app (alto · radio · fuente).
_BUTTON_SIZES = {
    "md": {"height": theme.HEIGHT_BUTTON,    "corner_radius": theme.RADIUS_MD, "font": theme.FONT_BUTTON},
    "sm": {"height": theme.HEIGHT_BUTTON,    "corner_radius": theme.RADIUS_MD, "font": theme.FONT_SMALL_BOLD},
    "lg": {"height": 36,                     "corner_radius": theme.RADIUS_MD, "font": theme.FONT_BUTTON},
    "xs": {"height": theme.HEIGHT_BUTTON_SM, "corner_radius": theme.RADIUS_SM, "font": theme.FONT_SMALL_BOLD},
}


def lazy_tabs(tabview: ctk.CTkTabview, builders: dict, on_change=None) -> dict:
    """Pestañas perezosas: añade todas las pestañas (barato) pero construye el
    contenido de cada una la PRIMERA vez que se abre. La primera se construye
    ya. Ahorra cientos de ms al abrir vistas con muchas pestañas (Ajustes,
    Reportes, Agenda).

    builders: {nombre: fn(frame)} en el orden de las pestañas.
    on_change: callback opcional fn(nombre) tras cada cambio de pestaña.
    Devuelve {nombre: frame}; `tabview.lazy_built` es el set de construidas.
    """
    frames = {name: tabview.add(name) for name in builders}
    built: set = set()
    tabview.lazy_built = built

    def ensure(name: str) -> None:
        if name in built or name not in builders:
            return
        built.add(name)
        builders[name](frames[name])

    def _on_change() -> None:
        name = tabview.get()
        ensure(name)
        if on_change:
            on_change(name)

    tabview.configure(command=_on_change)
    tabview.lazy_ensure = ensure
    ensure(tabview.get())
    return frames


def button(parent, text: str, variant: str = "primary", command=None,
           size: str = "md", **overrides) -> ctk.CTkButton:
    """CTkButton del sistema de diseño.

    variant → color: primary · secondary (relleno card + borde, para Cancelar/
              Cerrar) · outline (transparente + borde, toolbars) · chip
              (relleno suave) · ghost · danger.
    size    → md (34px, 12 bold) · sm (34px, 11 bold: toolbars) · lg (36px:
              pies de diálogo) · xs (28px, radio pequeño).
    `overrides` ajusta lo puntual (width, text_color, state, border_color…).
    """
    kw = theme.button_kwargs(variant)
    kw.update(_BUTTON_SIZES.get(size, _BUTTON_SIZES["md"]))
    kw.update(overrides)
    if kw.get("font", 0) is None:      # font=None → fuente por defecto de CTk
        kw.pop("font")
    return ctk.CTkButton(parent, text=text, command=command, **kw)


def icon_button(parent, glyph: str, command=None, danger: bool = False, **overrides) -> ctk.CTkButton:
    """Botón-icono discreto (✏ 🗑 ✕) de 24×22: transparente, hover suave —o
    DELETE_HOVER si `danger`— y texto atenuado."""
    kw = dict(
        width=24, height=22, corner_radius=4, border_width=0,
        fg_color="transparent",
        hover_color=theme.DELETE_HOVER if danger else theme.BG_INPUT,
        text_color=theme.TEXT_MUTED, font=theme.font(11),
    )
    kw.update(overrides)
    return ctk.CTkButton(parent, text=glyph, command=command, **kw)


# ── Estados vacíos ─────────────────────────────────────────────────────────────

def empty_state(parent, title: str, hint: str = "", icon: str = "○",
                compact: bool = False, pady=40, anchor: str = "center"):
    """Estado vacío consistente.

    compact=True → una sola línea discreta (para huecos dentro de una tarjeta).
    compact=False → icono grande + título en negrita + pista opcional, centrado
    (para listas/paneles enteros sin resultados). Devuelve el widget raíz.
    """
    if compact:
        lbl = ctk.CTkLabel(parent, text=title, font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED)
        lbl.pack(anchor=anchor, pady=pady)
        return lbl
    box = ctk.CTkFrame(parent, fg_color="transparent")
    box.pack(fill="x", pady=pady)
    ctk.CTkLabel(box, text=icon, font=theme.font(26, "bold"),
                 text_color=theme.BORDER_STRONG).pack()
    ctk.CTkLabel(box, text=title, font=theme.FONT_SMALL_BOLD,
                 text_color=theme.TEXT_SUB).pack(pady=(theme.SPACE_2, 0))
    if hint:
        ctk.CTkLabel(box, text=hint, font=theme.FONT_SMALL,
                     text_color=theme.TEXT_MUTED).pack(pady=(theme.SPACE_1, 0))
    return box


# ── KPI ────────────────────────────────────────────────────────────────────────

def kpi_tile(parent, label: str, color: str, variant: str = "dashboard",
             icon: str | None = None, height: int | None = None) -> dict:
    """Tarjeta KPI con valor actualizable (devuelve sus widgets, no la coloca).

    variant="dashboard" → tarjeta amplia (Inicio): radio LG, valor 24.
    variant="tile"      → tile compacto clicable (Documentos): franja de color
                          arriba, icono a la derecha, alto fijo, valor 21.
    Devuelve {card, value, label, icon, accent, widgets}; `widgets` sirve para
    enlazar el click a toda la tarjeta.
    """
    tile = variant == "tile"
    card = ctk.CTkFrame(
        parent, fg_color=theme.BG_CARD,
        corner_radius=theme.RADIUS_MD if tile else theme.RADIUS_LG,
        border_width=1, border_color=theme.BORDER,
        **({"height": height, "cursor": "hand2"} if tile else {}),
    )
    accent = None
    if tile:
        if height:
            card.grid_propagate(False)
        accent = ctk.CTkFrame(card, fg_color=color, height=4, corner_radius=theme.RADIUS_MD)
        accent.pack(fill="x", padx=2, pady=(2, 0))

    inner = ctk.CTkFrame(card, fg_color="transparent")
    if tile:
        inner.pack(fill="both", expand=True, padx=theme.SPACE_3, pady=(theme.SPACE_2, theme.SPACE_2))
    else:
        inner.pack(fill="both", expand=True, padx=theme.SPACE_4, pady=theme.SPACE_4)

    head = ctk.CTkFrame(inner, fg_color="transparent")
    head.pack(fill="x")
    lbl_label = ctk.CTkLabel(head, text=str(label).upper(), font=theme.FONT_LABEL,
                             text_color=theme.TEXT_MUTED, anchor="w")
    lbl_label.pack(side="left")
    lbl_icon = None
    if icon:
        lbl_icon = ctk.CTkLabel(head, text=icon, font=theme.font(13, "bold"), text_color=color)
        lbl_icon.pack(side="right")

    lbl_value = ctk.CTkLabel(inner, text="—", font=theme.font(21 if tile else 24, "bold"),
                             text_color=color, anchor="w")
    lbl_value.pack(anchor="w", pady=(theme.SPACE_1 if tile else theme.SPACE_2, 0))

    widgets = [w for w in (card, inner, head, lbl_label, lbl_icon, lbl_value) if w is not None]
    return {"card": card, "value": lbl_value, "label": lbl_label, "icon": lbl_icon,
            "accent": accent, "widgets": widgets}
