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
