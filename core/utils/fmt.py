"""Formateo de cifras para pantalla e informes, en castellano.

Vive en `core` y no en `gui` porque lo usan los dos: los gráficos de la app y el
HTML de los informes, que se genera desde los servicios y no puede importar la
interfaz.
"""

from __future__ import annotations


def num(v: float) -> str:
    """Número corto: 1.234.567 → «1,2 M» · 45.600 → «45,6k» · 999 → «999»."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return "0"
    a = abs(v)
    if a >= 1_000_000:
        return f"{v / 1_000_000:.1f}".replace(".", ",").rstrip("0").rstrip(",") + " M"
    if a >= 1_000:
        return f"{v / 1_000:.1f}".replace(".", ",").rstrip("0").rstrip(",") + "k"
    if v != int(v):
        return f"{v:.1f}".replace(".", ",")
    return str(int(v))


def eur(v: float) -> str:
    return num(v) + " €"


def dec(v: float, decimales: int = 1) -> str:
    """Decimal con coma, como se escribe en castellano: 19.9 → «19,9»."""
    try:
        return f"{float(v or 0):.{decimales}f}".replace(".", ",")
    except (TypeError, ValueError):
        return "0"


def pct(v: float, decimales: int = 0) -> str:
    """Porcentaje con coma decimal: 74.8 → «75%» o «74,8%»."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:.{decimales}f}".replace(".", ",") + "%"
