"""Formateadores de celda compartidos para las tablas (iconos + sparklines).

Glyphs elegidos para renderizar bien en Segoe UI y Cascadia Code.
La información va codificada en el SÍMBOLO (forma) además del color, de modo
que sigue siendo legible en escala de grises o para personas daltónicas.
"""

from __future__ import annotations

# ── Estados → icono ──────────────────────────────────────────────────────────
# La clave se normaliza (lower, sin puntos) antes de buscar.

_ESTADO_ICONS = [
    ("aprobado",   "✓"),   # check
    ("rechazado",  "✗"),   # ballot x
    ("mayores",    "◑"),   # comentado con cambios mayores
    ("menores",    "◐"),   # comentado con cambios menores
    ("comentado",  "◐"),
    ("hold",       "⏸"),
    ("informac",   "ℹ"),   # informativo / información
    ("enviado",    "↑"),   # enviado, a la espera de devolución
    ("sin",        "○"),   # sin enviar
]


def estado_icon(estado: str) -> str:
    """Devuelve el glyph del estado, o '' si no se reconoce."""
    key = str(estado or "").lower().strip().replace(".", "")
    for needle, icon in _ESTADO_ICONS:
        if needle in key:
            return icon
    return ""


def estado_with_icon(estado: str) -> str:
    """'Aprobado' → '✓  Aprobado'. Vacío → '○  Sin Enviar'."""
    txt = str(estado or "").strip()
    if not txt or txt.lower() == "nan":
        return "○  Sin Enviar"
    icon = estado_icon(txt)
    return f"{icon}  {txt}" if icon else txt


# ── Urgencia (reclamaciones) → icono ─────────────────────────────────────────

_URGENCY_ICONS = {"high": "⚠", "medium": "◑", "low": "○"}


def urgency_with_icon(label: str, urgency_key: str) -> str:
    """'ALTA' + 'high' → '⚠  ALTA'."""
    icon = _URGENCY_ICONS.get(urgency_key, "")
    return f"{icon}  {label}" if icon else label


# ── Sparkline de urgencia para columnas de "Días" ────────────────────────────
# Barra horizontal de 5 segmentos: llenos (█) + vacíos (░). La LONGITUD del
# tramo lleno codifica la urgencia, así se escanea sin depender del color.
#
# Umbrales pensados para "días sin devolver" (crítico > 15):
#   0          → sin barra (solo guión)
#   1–3        → 1 bloque
#   4–7        → 2 bloques
#   8–11       → 3 bloques
#   12–15      → 4 bloques
#   16+        → 5 bloques (lleno)

_BAR_SEGMENTS = 5
_BAR_FULL = "█"
_BAR_EMPTY = "░"


def _bar_level(days: int) -> int:
    if days <= 0:
        return 0
    if days <= 3:
        return 1
    if days <= 7:
        return 2
    if days <= 11:
        return 3
    if days <= 15:
        return 4
    return 5


def urgency_bar(value) -> str:
    """Devuelve '███░░  12' a partir del número de días.

    Si el valor es vacío o no numérico devuelve '—'.
    """
    try:
        days = int(float(value))
    except (ValueError, TypeError):
        return "—"
    if days <= 0:
        return f"{_BAR_EMPTY * _BAR_SEGMENTS}  0"
    level = _bar_level(days)
    bar = _BAR_FULL * level + _BAR_EMPTY * (_BAR_SEGMENTS - level)
    return f"{bar}  {days}"
