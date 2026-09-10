"""Calidad: no conformidades y equipos de medida, del esquema `verification`.

  · **No conformidades** (`nc_report`, 581 registros): cada una lleva el pedido
    afectado, el tipo, quién la detectó (a veces el propio cliente), el
    responsable de la zona, el análisis de causa, la acción correctiva y su
    coste. 182 siguen sin acción correctiva cerrada.
  · **Equipos de medida**: calibres (`calibers_workshop`, con `next_check_date`),
    máquinas (`machines_workshop`, con `next_revision`), manómetros y
    caudalímetros. Sirve para no llegar a una auditoría con la calibración
    caducada: hoy hay 48 calibres en uso y 26 máquinas vencidos.

Los equipos dados de baja (ubicación «BAJA») se marcan aparte para no inflar el
recuento. Solo lectura, caché corta.
"""

from __future__ import annotations

import logging
from datetime import date

from core.services.erp_common import Cache, as_date, available, clean, norm_order, safe_query

logger = logging.getLogger(__name__)

SOON_DAYS = 90           # «toca pronto» para una calibración

_cache = Cache()

_SQL_NC = """
    SELECT id, nc_date, num_order, report_type, audit, drawing_number, zone,
           detected, responsible, zone_responsible, description, cause_analysis,
           nc_type, corrective_action, date_action, corrective_action_completed,
           cost::text AS cost
    FROM verification.nc_report
    ORDER BY nc_date DESC NULLS LAST, id DESC
"""

_SQL_CALIBERS = """
    SELECT equipment_number AS codigo, type_caliber AS tipo,
           location_caliber AS ubicacion, brand AS marca, reference AS referencia,
           range_caliber AS rango, precision_caliber AS precision_,
           last_check_date AS ultima, next_check_date AS proxima
    FROM verification.calibers_workshop
"""

_SQL_MACHINES = """
    SELECT machine_type AS tipo, brand AS marca, characteristics AS caracteristicas,
           warehouse AS ubicacion, frequency_revisions AS frecuencia,
           year AS anio, next_revision AS proxima
    FROM verification.machines_workshop
"""

# Esta tabla no sigue el nombrado de las otras dos: no tiene `equipment_number`
# ni `location`, sino `number`, `instrument` y las fechas como `*_revision`. La
# consulta anterior fallaba entera y los 17 manómetros no aparecían por ningún
# lado —ni en Calidad ni en los avisos de equipos vencidos—.
_SQL_MANOMETERS = """
    SELECT number AS codigo, instrument AS tipo, master AS ubicacion,
           model AS marca, last_revision AS ultima, next_revision AS proxima
    FROM verification.manometers_thermoelements_workshop
"""


def invalidate_cache() -> None:
    _cache.clear()


def is_available() -> bool:
    return available()


# ── No conformidades ──────────────────────────────────────────────────────────

def _nc_row(r: dict) -> dict:
    cerrada = bool(clean(r.get("corrective_action_completed")))
    return {
        "id": clean(r.get("id")),
        "fecha": as_date(r.get("nc_date")),
        "pedido": norm_order(r.get("num_order")) or clean(r.get("num_order")),
        "pedido_raw": clean(r.get("num_order")),
        "tipo": clean(r.get("nc_type")),
        "zona": clean(r.get("zone")),
        "detectada_por": clean(r.get("detected")),
        "responsable": clean(r.get("zone_responsible")) or clean(r.get("responsible")),
        "descripcion": clean(r.get("description")),
        "causa": clean(r.get("cause_analysis")),
        "accion": clean(r.get("corrective_action")),
        "fecha_accion": as_date(r.get("date_action")),
        "cerrada": cerrada,
        "coste": clean(r.get("cost")),
        "plano": clean(r.get("drawing_number")),
        "cliente_detecta": "client" in clean(r.get("detected")).lower()
                           or "cliente" in clean(r.get("detected")).lower(),
    }


def nonconformities() -> list[dict]:
    """Todas las no conformidades, de la más reciente a la más antigua."""
    def build():
        return [_nc_row(r) for r in safe_query(_SQL_NC, label="no conformidades")]
    return _cache.get("nc", build)


def nc_for_pedido(num_order: str) -> list[dict]:
    """No conformidades de un pedido (tolera el sufijo -Sxx)."""
    key = norm_order(num_order)
    if not key:
        return []
    return [n for n in nonconformities() if n["pedido"] == key]


def nc_stats() -> dict:
    rows = nonconformities()
    hoy = date.today()
    ultimo_anio = [n for n in rows if n["fecha"] and (hoy - n["fecha"]).days <= 365]
    abiertas = [n for n in rows if not n["cerrada"]]
    return {
        "total": len(rows),
        "abiertas": len(abiertas),
        "ultimo_anio": len(ultimo_anio),
        "abiertas_anio": sum(1 for n in ultimo_anio if not n["cerrada"]),
        "cliente": sum(1 for n in ultimo_anio if n["cliente_detecta"]),
        "pedidos": len({n["pedido"] for n in rows if n["pedido"]}),
    }


def nc_by_type(rows: list[dict] | None = None) -> list[tuple]:
    """[(tipo, nº)] ordenado, para el gráfico de barras."""
    from collections import Counter
    rows = nonconformities() if rows is None else rows
    c = Counter(n["tipo"] or "Sin tipificar" for n in rows)
    return c.most_common()


# ── Equipos de medida ─────────────────────────────────────────────────────────

def _equip_row(r: dict, familia: str) -> dict:
    prox = as_date(r.get("proxima"))
    hoy = date.today()
    ubic = clean(r.get("ubicacion"))
    baja = "BAJA" in ubic.upper()
    dias = (prox - hoy).days if prox else None
    return {
        "familia": familia,
        "codigo": clean(r.get("codigo")) or clean(r.get("tipo")),
        "tipo": clean(r.get("tipo")),
        "marca": clean(r.get("marca")),
        "ubicacion": ubic,
        "ultima": as_date(r.get("ultima")),
        "proxima": prox,
        "dias": dias,
        "vencido": bool(prox and prox < hoy) and not baja,
        "baja": baja,
        "detalle": clean(r.get("rango")) or clean(r.get("caracteristicas")) or clean(r.get("frecuencia")),
    }


def equipment() -> list[dict]:
    """Calibres, máquinas y manómetros con su próxima calibración/revisión."""
    def build():
        out = []
        for sql, familia in ((_SQL_CALIBERS, "Calibre"),
                             (_SQL_MACHINES, "Máquina"),
                             (_SQL_MANOMETERS, "Manómetro")):
            for r in safe_query(sql, label=f"equipos {familia}"):
                out.append(_equip_row(r, familia))
        # Vencidos primero; luego por fecha de próxima revisión
        out.sort(key=lambda e: (not e["vencido"], e["proxima"] or date.max))
        return out
    return _cache.get("equipos", build)


def equipment_stats() -> dict:
    rows = [e for e in equipment() if not e["baja"]]
    hoy = date.today()
    return {
        "total": len(rows),
        "vencidos": sum(1 for e in rows if e["vencido"]),
        "pronto": sum(1 for e in rows if e["proxima"] and not e["vencido"]
                      and (e["proxima"] - hoy).days <= SOON_DAYS),
        "sin_fecha": sum(1 for e in rows if not e["proxima"]),
        "baja": sum(1 for e in equipment() if e["baja"]),
    }


# ── Exportación ───────────────────────────────────────────────────────────────

def export_nc_rows(rows: list[dict]) -> list[dict]:
    return [{
        "Nº NC": n["id"],
        "Fecha": n["fecha"].strftime("%d-%m-%Y") if n["fecha"] else "",
        "Nº Pedido": n["pedido_raw"],
        "Tipo": n["tipo"],
        "Zona": n["zona"],
        "Detectada por": n["detectada_por"],
        "Responsable": n["responsable"],
        "Descripción": n["descripcion"],
        "Causa": n["causa"],
        "Acción correctiva": n["accion"],
        "Cerrada": "Sí" if n["cerrada"] else "No",
        "Coste": n["coste"],
    } for n in rows]


def export_equipment_rows(rows: list[dict]) -> list[dict]:
    return [{
        "Familia": e["familia"],
        "Código": e["codigo"],
        "Tipo": e["tipo"],
        "Marca": e["marca"],
        "Ubicación": e["ubicacion"],
        "Última": e["ultima"].strftime("%d-%m-%Y") if e["ultima"] else "",
        "Próxima": e["proxima"].strftime("%d-%m-%Y") if e["proxima"] else "",
        "Estado": "Vencido" if e["vencido"] else ("Baja" if e["baja"] else "Al día"),
    } for e in rows]


def export_excel(rows: list[dict], path: str, kind: str = "nc") -> str:
    import pandas as pd

    data = export_nc_rows(rows) if kind == "nc" else export_equipment_rows(rows)
    pd.DataFrame(data).to_excel(path, index=False, engine="openpyxl")
    return path
