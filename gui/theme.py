"""Paleta y constantes de tema.

4 modos disponibles:
- light         — Anthropic claro · papel cálido + azul · Segoe UI
- dark          — Anthropic oscuro · warm dark + azul · Segoe UI
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
    "BG_PAGE":         "#1C1B19",  # warm dark (estética Anthropic)
    "BG_CARD":         "#242321",
    "BG_SIDEBAR":      "#191816",
    "BG_INPUT":        "#2A2825",
    "BORDER":          "#393734",
    "BORDER_STRONG":   "#52504B",

    "ACCENT":          "#5B9BE0",  # azul "info" (claro sobre fondo cálido oscuro)
    "ACCENT_HOVER":    "#85B7EB",
    "ACCENT_PRESSED":  "#B5D4F4",
    "ACCENT_SOFT":     "#22303F",

    "TEXT_MAIN":       "#F0EEE6",  # crema cálida
    "TEXT_SUB":        "#B4B2A9",
    "TEXT_MUTED":      "#8A8880",

    "ROW_BG_CRITICAL": "#3B201C",
    "ROW_BG_WARN":     "#332515",
    "ROW_BG_EDITED":   "#22303F",
    "DELETE_HOVER":    "#3B201C",

    "ROW_STRIPE":      "#211F1D",  # banda alterna (zebra) — sutil sobre BG_CARD
    "ROW_HOVER":       "#2B2926",  # fila bajo el cursor
    "TABLE_HEADER_BG": "#191816",  # cabecera de tabla
    "TABLE_HEADER_FG": "#A8A29A",

    "NOTE_BLUE":       "#22303F",
    "NOTE_GREEN":      "#26331C",
    "NOTE_AMBER":      "#3A2A14",
    "NOTE_ROSE":       "#3A2026",

    "FONT_FAMILY":      "Segoe UI",
    "FONT_FAMILY_MONO": "Consolas",
}

_LIGHT = {
    "BG_PAGE":         "#F5F4EF",  # papel cálido (estética Anthropic/widget)
    "BG_CARD":         "#FFFFFF",
    "BG_SIDEBAR":      "#FAF9F5",
    "BG_INPUT":        "#F0EEE6",
    "BORDER":          "#E7E5DD",  # borde fino cálido
    "BORDER_STRONG":   "#D3D1C7",

    "ACCENT":          "#185FA5",  # azul "info" del sistema (c-blue 600)
    "ACCENT_HOVER":    "#0C447C",
    "ACCENT_PRESSED":  "#042C53",
    "ACCENT_SOFT":     "#E6F1FB",

    "TEXT_MAIN":       "#2C2C2A",  # casi-negro cálido (c-gray 900)
    "TEXT_SUB":        "#5F5E5A",
    "TEXT_MUTED":      "#888780",

    "ROW_BG_CRITICAL": "#FCEBEB",
    "ROW_BG_WARN":     "#FAEEDA",
    "ROW_BG_EDITED":   "#E6F1FB",
    "DELETE_HOVER":    "#F7C1C1",

    "ROW_STRIPE":      "#FAF9F5",  # banda alterna (zebra) cálida
    "ROW_HOVER":       "#F0EEE6",  # fila bajo el cursor
    "TABLE_HEADER_BG": "#F1EFE8",  # cabecera de tabla (c-gray 50)
    "TABLE_HEADER_FG": "#5F5E5A",

    "NOTE_BLUE":       "#E6F1FB",
    "NOTE_GREEN":      "#EAF3DE",
    "NOTE_AMBER":      "#FAEEDA",
    "NOTE_ROSE":       "#FBEAF0",

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

    "ROW_STRIPE":      "#2C2A28",  # banda alterna (zebra)
    "ROW_HOVER":       "#33302D",  # fila bajo el cursor
    "TABLE_HEADER_BG": "#1A1918",  # cabecera de tabla
    "TABLE_HEADER_FG": "#A8A29E",

    "NOTE_BLUE":       "#1F3140",
    "NOTE_GREEN":      "#1F3520",
    "NOTE_AMBER":      "#3D2A1A",
    "NOTE_ROSE":       "#3D1F2A",

    "FONT_FAMILY":      "Cascadia Mono",   # sin ligaduras → mejor para UI/códigos
    "FONT_FAMILY_MONO": "Cascadia Mono",
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

    "ROW_STRIPE":      "#F6F4ED",  # banda alterna (zebra) cálida
    "ROW_HOVER":       "#F0EDE3",  # fila bajo el cursor
    "TABLE_HEADER_BG": "#EFECE2",  # cabecera de tabla
    "TABLE_HEADER_FG": "#6B6760",

    "NOTE_BLUE":       "#E0EAF5",
    "NOTE_GREEN":      "#E1F0D8",
    "NOTE_AMBER":      "#FBF1D9",
    "NOTE_ROSE":       "#F8E2EA",

    "FONT_FAMILY":      "Cascadia Mono",   # sin ligaduras → mejor para UI/códigos
    "FONT_FAMILY_MONO": "Cascadia Mono",
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
ROW_STRIPE      = _PALETTE["ROW_STRIPE"]
ROW_HOVER       = _PALETTE["ROW_HOVER"]
TABLE_HEADER_BG = _PALETTE["TABLE_HEADER_BG"]
TABLE_HEADER_FG = _PALETTE["TABLE_HEADER_FG"]
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
# Los temas Coral usan una family monoespaciada (Cascadia Mono) en toda la UI.
# Como las monoespaciadas son más ANCHAS por carácter que una sans (Segoe UI)
# al mismo tamaño, aplicamos una escala de puntos reducida en esos temas para
# que el texto encaje sin tocar la estructura.

FONT_FAMILY      = _PALETTE["FONT_FAMILY"]
FONT_FAMILY_MONO = _PALETTE["FONT_FAMILY_MONO"]

# ¿La family de UI es monoespaciada? → usar la escala reducida
_MONO_UI = FONT_FAMILY in ("Cascadia Mono", "Cascadia Code", "Consolas", "Courier New")


def scale_size(size: int) -> int:
    """Reduce el tamaño de punto en temas monoespaciados (más anchos por glyph).

    Sans (Segoe UI): sin cambios.
    Mono (Cascadia Mono): ≤10 sin tocar · 11-14 −1 · 15-18 −2 · ≥19 ×0.82.
    """
    if not _MONO_UI:
        return size
    if size <= 10:
        return size
    if size <= 14:
        return size - 1
    if size <= 18:
        return size - 2
    return max(11, round(size * 0.82))


def font(size: int, weight: str | None = None):
    """Tupla de fuente UI auto-escalada. `font(12, "bold")` → (family, sz, 'bold')."""
    s = scale_size(size)
    return (FONT_FAMILY, s) if weight is None else (FONT_FAMILY, s, weight)


def mfont(size: int, weight: str | None = None):
    """Igual que `font` pero con la family monoespaciada (FONT_FAMILY_MONO)."""
    s = scale_size(size)
    return (FONT_FAMILY_MONO, s) if weight is None else (FONT_FAMILY_MONO, s, weight)


FONT_DISPLAY    = font(28, "bold")
FONT_TITLE      = font(22, "bold")
FONT_HEADING    = font(18, "bold")
FONT_SUBTITLE   = font(14)
FONT_SECTION    = font(13, "bold")
FONT_BODY       = font(12)
FONT_BODY_BOLD  = font(12, "bold")
FONT_SMALL      = font(11)
FONT_SMALL_BOLD = font(11, "bold")
FONT_TINY       = font(10)
FONT_TINY_BOLD  = font(10, "bold")
FONT_LABEL      = font(9, "bold")
FONT_BUTTON     = font(12, "bold")
FONT_MONO       = mfont(11)


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
