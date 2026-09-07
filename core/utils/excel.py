"""Lectura rápida de Excel: motor calamine (≈7× más rápido que openpyxl) con
fallback automático a openpyxl si no está instalado o falla en un fichero.

Medido sobre data_erp.xlsx + consulta_erp.xlsx: 940 ms → 126 ms. Paridad
verificada (misma forma, columnas y valores).
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import python_calamine  # noqa: F401
    _ENGINE = "calamine"
except Exception:  # noqa: BLE001 — sin calamine la app funciona igual, más lenta
    _ENGINE = "openpyxl"


def engine() -> str:
    """Motor activo: 'calamine' u 'openpyxl'."""
    return _ENGINE


def read_excel_fast(path, **kwargs) -> pd.DataFrame:
    """pd.read_excel con el motor más rápido disponible."""
    if _ENGINE == "calamine":
        try:
            return pd.read_excel(path, engine="calamine", **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("calamine no pudo leer %s (%s); usando openpyxl", path, exc)
    return pd.read_excel(path, engine="openpyxl", **kwargs)
