"""Paleta y constantes de tema.

4 modos disponibles:
- light         — Linear/Vercel claro · indigo · Inter/Segoe UI
- dark          — Linear/Vercel oscuro · indigo · Inter/Segoe UI
- light-coral   — Cream + coral · estilo terminal · monospace
- dark-coral    — Warm dark + coral · estilo terminal · monospace

Cambio por reinicio. El módulo carga la preferencia activa al importarse.
"""

from __future__ import annotations

from core.preferences import get_theme

# Estados semánticos (compartidos entre todos los modos)
GREEN = "#16A34A"
AMBER = "#D97706"
RED = "#DC2626"
BLUE = "#2563EB"
ROSE = "#DB2777"

# Acento coral cálido para los temas terminal
_CORAL = "#D97757"
_CORAL_HOVER = "#C26749"
_CORAL_PRESSED = "#A8553A"


# ═══ Paletas por modo ═══════════════════════════════════════════════════════

_DARK = {
    "BG_PAGE":         "#0F1117",
    "BG_CARD":         "#1A1D27",
    "BG_SIDEBAR":      "#0C0E15",
    "BG_INPUT":        "#252837",
    "BORDER":          "#2E3244",
    "BORDER_STRONG":   "#3D4256",

    "ACCENT":          "#4F46E5",  # indigo principal
    "ACCENT_HOVER":    "#4338CA",
    "ACCENT_PRESSED":  "#3730A3",
    "ACCENT_SOFT":     "#1E1C3A",

    "TEXT_MAIN":       "#F1F5F9",
    "TEXT_SUB":        "#B4BCD0",
    "TEXT_MUTED":      "#7B8398",

    "ROW_BG_CRITICAL": "#3B1818",
    "ROW_BG_WARN":     "#2C2412",
    "ROW_BG_EDITED":   "#1E3A5F",
    "DELETE_HOVER":    "#3B1818",

    "NOTE_BLUE":       "#1E3A5F",
    "NOTE_GREEN":      "#14532D",
    "NOTE_AMBER":      "#451A03",
    "NOTE_ROSE":       "#4C0519",

    "FONT_FAMILY":      "Segoe UI",
    "FONT_FAMILY_MONO": "Consolas",
}

_LIGHT = {
    "BG_PAGE":         "#F7F8FA",
    "BG_CARD":         "#FFFFFF",
    "BG_SIDEBAR":      "#FAFBFC",
    "BG_INPUT":        "#F3F4F6",
    "BORDER":          "#E5E7EB",
    "BORDER_STRONG":   "#D1D5DB",

    "ACCENT":          "#4F46E5",
    "ACCENT_HOVER":    "#4338CA",
    "ACCENT_PRESSED":  "#3730A3",
    "ACCENT_SOFT":     "#EEF2FF",

    "TEXT_MAIN":       "#0F172A",
    "TEXT_SUB":        "#475569",
    "TEXT_MUTED":      "#94A3B8",

    "ROW_BG_CRITICAL": "#FEE2E2",
    "ROW_BG_WARN":     "#FEF3C7",
    "ROW_BG_EDITED":   "#DBEAFE",
    "DELETE_HOVER":    "#FECACA",

    "NOTE_BLUE":       "#DBEAFE",
    "NOTE_GREEN":      "#DCFCE7",
    "NOTE_AMBER":      "#FEF3C7",
    "NOTE_ROSE":       "#FCE7F3",

    "FONT_FAMILY":      "Segoe UI",
    "FONT_FAMILY_MONO": "Consolas",
}

# ═══ Coral Dark — warm terminal aesthetic ════════════════════════════════════
_DARK_CORAL = {
    "BG_PAGE":         "#1F1E1D",  # warm dark, terminal-like
    "BG_CARD":         "#262624",
    "BG_SIDEBAR":      "#1A1918",
    "BG_INPUT":        "#2A2826",
    "BORDER":          "#3D3B38",
    "BORDER_STRONG":   "#52504C",

    "ACCENT":          _CORAL,
    "ACCENT_HOVER":    _CORAL_HOVER,
    "ACCENT_PRESSED":  _CORAL_PRESSED,
    "ACCENT_SOFT":     "#3D2B22",  # dark warm coral, para selected/hover

    "TEXT_MAIN":       "#F0EEE6",  # warm cream
    "TEXT_SUB":        "#A8A29E",
    "TEXT_MUTED":      "#7A746E",

    "ROW_BG_CRITICAL": "#3B2018",
    "ROW_BG_WARN":     "#332515",
    "ROW_BG_EDITED":   "#2A3540",
    "DELETE_HOVER":    "#3B2018",

    "NOTE_BLUE":       "#1F3140",
    "NOTE_GREEN":      "#1F3520",
    "NOTE_AMBER":      "#3D2A1A",
    "NOTE_ROSE":       "#3D1F2A",

    "FONT_FAMILY":      "Cascadia Code",   # fallback chain: Cascadia → Consolas
    "FONT_FAMILY_MONO": "Cascadia Code",
}

# ═══ Coral Light — antique white / cream ═════════════════════════════════════
_LIGHT_CORAL = {
    "BG_PAGE":         "#FAF9F5",  # antique white cálido
    "BG_CARD":         "#FFFFFF",
    "BG_SIDEBAR":      "#F5F4ED",
    "BG_INPUT":        "#F0EFE8",
    "BORDER":          "#E5E4DD",
    "BORDER_STRONG":   "#D1CFC5",

    "ACCENT":          _CORAL,
    "ACCENT_HOVER":    _CORAL_HOVER,
    "ACCENT_PRESSED":  _CORAL_PRESSED,
    "ACCENT_SOFT":     "#FCE9DC",  # very light coral

    "TEXT_MAIN":       "#1F1E1D",
    "TEXT_SUB":        "#6B6760",
    "TEXT_MUTED":      "#A8A29E",

    "ROW_BG_CRITICAL": "#FAE2D6",
    "ROW_BG_WARN":     "#FBF1D9",
    "ROW_BG_EDITED":   "#E0EAF5",
    "DELETE_HOVER":    "#F5D0BD",

    "NOTE_BLUE":       "#E0EAF5",
    "NOTE_GREEN":      "#E1F0D8",
    "NOTE_AMBER":      "#FBF1D9",
    "NOTE_ROSE":       "#F8E2EA",

    "FONT_FAMILY":      "Cascadia Code",
    "FONT_FAMILY_MONO": "Cascadia Code",
}


_PALETTES = {
    "light":        _LIGHT,
    "dark":         _DARK,
    "light-coral":  _LIGHT_CORAL,
    "dark-coral":   _DARK_CORAL,
    # Aliases retrocompat
    "light-claude": _LIGHT_CORAL,
    "dark-claude":  _DARK_CORAL,
}

_MODE = get_theme()
_PALETTE = _PALETTES.get(_MODE, _DARK)


# ═══ Exportar como atributos de módulo ══════════════════════════════════════

BG_PAGE         = _PALETTE["BG_PAGE"]
BG_CARD         = _PALETTE["BG_CARD"]
BG_SIDEBAR      = _PALETTE["BG_SIDEBAR"]
BG_INPUT        = _PALETTE["BG_INPUT"]
BORDER          = _PALETTE["BORDER"]
BORDER_STRONG   = _PALETTE["BORDER_STRONG"]
ACCENT          = _PALETTE["ACCENT"]
ACCENT_HOVER    = _PALETTE["ACCENT_HOVER"]
ACCENT_PRESSED  = _PALETTE["ACCENT_PRESSED"]
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
    """Devuelve el modo activo: 'light' | 'dark' | 'light-coral' | 'dark-coral'."""
    return _MODE


def is_coral() -> bool:
    return _MODE in ("light-coral", "dark-coral", "light-claude", "dark-claude")


def is_dark() -> bool:
    return _MODE in ("dark", "dark-coral", "dark-claude")


# ═══ Estados (colores semánticos) ═══════════════════════════════════════════

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


# ═══ Tipografía (escala consistente) ════════════════════════════════════════
# Los temas Claude usan la misma family para todo (look CLI/terminal mono).
# Los temas Linear/Vercel separan sans (UI) y mono (códigos).

FONT_FAMILY      = _PALETTE["FONT_FAMILY"]
FONT_FAMILY_MONO = _PALETTE["FONT_FAMILY_MONO"]

FONT_DISPLAY   = (FONT_FAMILY, 28, "bold")
FONT_TITLE     = (FONT_FAMILY, 22, "bold")
FONT_HEADING   = (FONT_FAMILY, 18, "bold")
FONT_SUBTITLE  = (FONT_FAMILY, 14)
FONT_SECTION   = (FONT_FAMILY, 13, "bold")
FONT_BODY      = (FONT_FAMILY, 12)
FONT_BODY_BOLD = (FONT_FAMILY, 12, "bold")
FONT_SMALL     = (FONT_FAMILY, 11)
FONT_SMALL_BOLD = (FONT_FAMILY, 11, "bold")
FONT_TINY      = (FONT_FAMILY, 10)
FONT_TINY_BOLD = (FONT_FAMILY, 10, "bold")
FONT_LABEL     = (FONT_FAMILY, 9, "bold")
FONT_BUTTON    = (FONT_FAMILY, 12, "bold")
FONT_MONO      = (FONT_FAMILY_MONO, 11)


# ═══ Espaciados (grid base 4px) ═════════════════════════════════════════════

SPACE_1  = 4
SPACE_2  = 8
SPACE_3  = 12
SPACE_4  = 16
SPACE_5  = 20
SPACE_6  = 24
SPACE_8  = 32
SPACE_10 = 40

RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 12

HEIGHT_BUTTON = 34
HEIGHT_BUTTON_SM = 28
HEIGHT_INPUT = 34
HEIGHT_ROW = 36


# ═══ Botones — variantes consistentes ═══════════════════════════════════════

BUTTON_STYLES = {
    "primary": {
        "fg_color": ACCENT,
        "hover_color": ACCENT_HOVER,
        "text_color": "#FFFFFF",
        "border_width": 0,
    },
    "secondary": {
        "fg_color": BG_CARD,
        "hover_color": BG_INPUT,
        "text_color": TEXT_MAIN,
        "border_width": 1,
        "border_color": BORDER,
    },
    "ghost": {
        "fg_color": "transparent",
        "hover_color": BG_INPUT,
        "text_color": TEXT_SUB,
        "border_width": 0,
    },
    "danger": {
        "fg_color": "transparent",
        "hover_color": DELETE_HOVER,
        "text_color": TEXT_MUTED,
        "border_width": 0,
    },
}


def button_kwargs(variant: str = "primary") -> dict:
    """Devuelve kwargs de estilo para CTkButton según variante."""
    style = BUTTON_STYLES.get(variant, BUTTON_STYLES["primary"]).copy()
    style["corner_radius"] = RADIUS_MD
    style["height"] = HEIGHT_BUTTON
    style["font"] = FONT_BUTTON
    return style
