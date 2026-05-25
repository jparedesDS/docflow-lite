"""Paleta y constantes de tema. Light + Dark mode con cambio por reinicio.

El módulo carga la preferencia activa al importarse. Los símbolos exportados
(BG_PAGE, TEXT_MAIN, etc.) reflejan la paleta activa. Cambiar el tema requiere
reiniciar la app (los widgets de Tk/CTk no se actualizan en caliente porque
muchos colores se fijan en la creación).
"""

from __future__ import annotations

from core.preferences import get_theme

# ─── Acentos comunes (no cambian entre temas) ────────────────────────────────
ACCENT = "#4F46E5"
ACCENT_HOVER = "#4338CA"

GREEN = "#16A34A"
AMBER = "#D97706"
RED = "#DC2626"
BLUE = "#2563EB"
ROSE = "#DB2777"


# ─── Paletas por modo ────────────────────────────────────────────────────────

_DARK = {
    "BG_PAGE":         "#0F1117",
    "BG_CARD":         "#1A1D27",
    "BG_SIDEBAR":      "#0C0E15",
    "BG_INPUT":        "#252837",
    "BORDER":          "#2E3244",
    "ACCENT_SOFT":     "#312E81",
    "TEXT_MAIN":       "#F1F5F9",
    "TEXT_SUB":        "#B4BCD0",
    "TEXT_MUTED":      "#7B8398",
    # Fondos de fila / hover
    "ROW_BG_CRITICAL": "#3B1818",
    "ROW_BG_WARN":     "#2C2412",
    "ROW_BG_EDITED":   "#1E3A5F",
    "DELETE_HOVER":    "#3B1818",
    # Notas (fondos saturados sobre dark)
    "NOTE_BLUE":       "#1E3A5F",
    "NOTE_GREEN":      "#14532D",
    "NOTE_AMBER":      "#451A03",
    "NOTE_ROSE":       "#4C0519",
}

_LIGHT = {
    "BG_PAGE":         "#F4F6FA",
    "BG_CARD":         "#FFFFFF",
    "BG_SIDEBAR":      "#FFFFFF",
    "BG_INPUT":        "#F1F3F8",
    "BORDER":          "#E2E8F0",
    "ACCENT_SOFT":     "#EEF2FF",
    "TEXT_MAIN":       "#0F172A",
    "TEXT_SUB":        "#475569",
    "TEXT_MUTED":      "#94A3B8",
    # Versiones suaves para fondo blanco
    "ROW_BG_CRITICAL": "#FEE2E2",
    "ROW_BG_WARN":     "#FEF3C7",
    "ROW_BG_EDITED":   "#DBEAFE",
    "DELETE_HOVER":    "#FECACA",
    # Notas (pasteles claros sobre light)
    "NOTE_BLUE":       "#DBEAFE",
    "NOTE_GREEN":      "#DCFCE7",
    "NOTE_AMBER":      "#FEF3C7",
    "NOTE_ROSE":       "#FCE7F3",
}


_MODE = get_theme()
_PALETTE = _LIGHT if _MODE == "light" else _DARK

# Exportar como atributos de módulo (uso directo: theme.BG_PAGE)
BG_PAGE         = _PALETTE["BG_PAGE"]
BG_CARD         = _PALETTE["BG_CARD"]
BG_SIDEBAR      = _PALETTE["BG_SIDEBAR"]
BG_INPUT        = _PALETTE["BG_INPUT"]
BORDER          = _PALETTE["BORDER"]
ACCENT_SOFT     = _PALETTE["ACCENT_SOFT"]
TEXT_MAIN       = _PALETTE["TEXT_MAIN"]
TEXT_SUB        = _PALETTE["TEXT_SUB"]
TEXT_MUTED      = _PALETTE["TEXT_MUTED"]
ROW_BG_CRITICAL = _PALETTE["ROW_BG_CRITICAL"]
ROW_BG_WARN     = _PALETTE["ROW_BG_WARN"]
ROW_BG_EDITED   = _PALETTE["ROW_BG_EDITED"]
DELETE_HOVER    = _PALETTE["DELETE_HOVER"]
NOTE_BLUE       = _PALETTE["NOTE_BLUE"]
NOTE_GREEN      = _PALETTE["NOTE_GREEN"]
NOTE_AMBER      = _PALETTE["NOTE_AMBER"]
NOTE_ROSE       = _PALETTE["NOTE_ROSE"]


def current_mode() -> str:
    """'light' o 'dark'."""
    return _MODE


# ─── Estados (mismos colores en ambos modos para coherencia) ─────────────────

STATUS_COLORS = {
    "aprobado":    GREEN,
    "rechazado":   RED,
    "com_mayores": AMBER,
    "com_menores": AMBER,
    "comentado":   AMBER,
    "informativo": BLUE,
    "enviado":     BLUE,
    "sin_enviar":  TEXT_MUTED,
}


def normalize_status(value: str) -> str:
    if not value:
        return ""
    return str(value).lower().strip().replace(".", "").replace(" ", "_")


def status_color(value: str) -> str:
    key = normalize_status(value)
    for k, color in STATUS_COLORS.items():
        if k in key:
            return color
    return TEXT_MUTED


# ─── Tipografía ──────────────────────────────────────────────────────────────

FONT_FAMILY = "Segoe UI"  # disponible en Windows nativo

FONT_TITLE = (FONT_FAMILY, 22, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 14)
FONT_SECTION = (FONT_FAMILY, 13, "bold")
FONT_BODY = (FONT_FAMILY, 12)
FONT_SMALL = (FONT_FAMILY, 11)
FONT_TINY = (FONT_FAMILY, 10)
FONT_BUTTON = (FONT_FAMILY, 12, "bold")
FONT_MONO = ("Consolas", 11)
