"""Producción: qué hay en el taller y cuántas horas se han imputado.

  · **En taller**: pedidos abiertos con su avance (`porc_workshop`,
    `porc_assembly`, `porc_deliveries` de `public.orders`), la fecha prevista y
    las observaciones del taller. Es la foto de la carga de trabajo.
  · **Horas**: `fabrication.imp_ot` guarda cada imputación (fecha, operario,
    operación y tiempo). Para llevarlas a un pedido hay que pasar por
    `fabrication.fab_order`, PERO ojo: una OT cubre varios tags, así que unir
    directamente multiplica las horas. Aquí se agrupa primero por OT y luego se
    asigna cada OT a su pedido (el 99 % de los tags trae uno; las 43 OTs que
    tocan dos pedidos se descartan por no repartir a ciegas).

Lo que NO se hace, a propósito: comparar con las horas de `orders.*_hours`. Esos
campos son estimaciones por equipo, no el total del pedido — al contrastarlos
salen desviaciones de +12.000 %, así que compararlos engañaría.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from core.services.erp_common import Cache, as_date, available, clean, norm_order, orders_in, safe_query

logger = logging.getLogger(__name__)

HOURS_DAYS = 730         # ventana por defecto de las horas (2 años)
STALE_DAYS = 540         # más de año y medio de retraso = pedido zombi del ERP

_cache = Cache()

_SQL_TALLER = """
    SELECT o.num_order, o.porc_workshop, o.porc_assembly, o.porc_deliveries,
           o.expected_date, o.recep_date_workshop, o.recep_date_assembly,
           o.expected_date_workshop, o.obs_workshop, o.obs_assembly,
           o.material_available, o.items_number, o.closed,
           f.client, f.final_client, f.material
    FROM public.orders o
    LEFT JOIN public.offers f ON f.num_offer = o.num_offer
    WHERE coalesce(o.closed, '') <> 'OK'
    ORDER BY o.expected_date NULLS LAST
"""

_SQL_HORAS_OT = """
    SELECT i.number_ot::text AS ot, sum(coalesce(i.total_time, 0)) AS horas,
           max(i.date_ot) AS ultima, count(*) AS apuntes
    FROM fabrication.imp_ot i
    WHERE i.date_ot >= %s
    GROUP BY 1
"""

_SQL_OT_TAGS = "SELECT ot_num::text AS ot, tag FROM fabrication.fab_order WHERE ot_num IS NOT NULL"

_SQL_HORAS_OP = """
    SELECT coalesce(o.name_eipsa, 'Sin operación') AS operacion,
           sum(coalesce(i.total_time, 0)) AS horas,
           count(DISTINCT i.personal_id) AS personas,
           count(*) AS apuntes
    FROM fabrication.imp_ot i
    LEFT JOIN fabrication.operations o ON o.id = i.operations_id
    WHERE i.date_ot >= %s
    GROUP BY 1
    ORDER BY horas DESC
"""


def invalidate_cache() -> None:
    _cache.clear()


def is_available() -> bool:
    return available()


def _pct(v) -> int:
    try:
        return max(0, min(100, int(float(v))))
    except (TypeError, ValueError):
        return 0


def _client(r: dict) -> str:
    for k in ("final_client", "client"):
        v = clean(r.get(k))
        if v:
            return v
    return ""


# ── En taller ─────────────────────────────────────────────────────────────────

def workshop() -> list[dict]:
    """Pedidos abiertos con su avance de fabricación, los más urgentes primero.

    Marca como `antiguo` lo que arrastra más de año y medio de retraso: son
    pedidos que quedaron sin cerrar en el ERP (hay alguno con fecha de 1901) y
    taparían lo que de verdad está en marcha.
    """
    def build():
        hoy = date.today()
        out = []
        for r in safe_query(_SQL_TALLER, label="taller"):
            prev = as_date(r.get("expected_date"))
            retraso = (hoy - prev).days if prev and prev < hoy else 0
            taller, montaje = _pct(r.get("porc_workshop")), _pct(r.get("porc_assembly"))
            out.append({
                "antiguo": retraso > STALE_DAYS,
                "pedido": norm_order(r.get("num_order")) or clean(r.get("num_order")),
                "pedido_raw": clean(r.get("num_order")),
                "cliente": _client(r),
                "equipo": clean(r.get("material")),
                "unidades": clean(r.get("items_number")),
                "taller": taller,
                "montaje": montaje,
                "envio": _pct(r.get("porc_deliveries")),
                "prevista": prev,
                "retraso": retraso,
                "recep_taller": clean(r.get("recep_date_workshop")),
                "material": clean(r.get("material_available")),
                "obs": clean(r.get("obs_workshop")) or clean(r.get("obs_assembly")),
                "en_curso": 0 < max(taller, montaje) < 100,
                "sin_empezar": max(taller, montaje) == 0,
            })
        out.sort(key=lambda r: (-r["retraso"], r["prevista"] or date.max))
        return out
    return _cache.get("taller", build)


def active(include_old: bool = False) -> list[dict]:
    """Pedidos en taller; sin los zombis salvo que se pidan expresamente."""
    rows = workshop()
    return rows if include_old else [r for r in rows if not r["antiguo"]]


def workshop_stats() -> dict:
    """Cifras sobre los pedidos vivos (los zombis se cuentan aparte)."""
    rows = active()
    return {
        "abiertos": len(rows),
        "en_curso": sum(1 for r in rows if r["en_curso"]),
        "sin_empezar": sum(1 for r in rows if r["sin_empezar"]),
        "retrasados": sum(1 for r in rows if r["retraso"] > 0),
        "retraso_max": max((r["retraso"] for r in rows), default=0),
        "antiguos": sum(1 for r in workshop() if r["antiguo"]),
    }


def for_pedido(num_order: str) -> dict | None:
    """Avance de fabricación de un pedido concreto."""
    key = norm_order(num_order)
    if not key:
        return None
    return next((r for r in workshop() if r["pedido"] == key), None)


# ── Horas ─────────────────────────────────────────────────────────────────────

def _ot_to_order() -> dict:
    """{OT → pedido}. Solo las OTs que apuntan a UN pedido."""
    por_ot = defaultdict(set)
    for r in safe_query(_SQL_OT_TAGS, label="OTs"):
        for p in orders_in(r.get("tag")):
            por_ot[clean(r.get("ot"))].add(p)
    return {ot: next(iter(peds)) for ot, peds in por_ot.items() if len(peds) == 1}


def hours(days: int = HOURS_DAYS) -> dict:
    """{por_pedido: [...], por_operacion: [...], ultima: date, total: float}."""
    def build():
        desde = date.fromordinal(date.today().toordinal() - days)
        ots = safe_query(_SQL_HORAS_OT, (desde,), label="horas por OT")
        mapa = _ot_to_order()
        por_pedido: dict[str, dict] = {}
        total = 0.0
        ultima = None
        for r in ots:
            h = float(r.get("horas") or 0)
            total += h
            fin = as_date(r.get("ultima"))
            if fin and (ultima is None or fin > ultima):
                ultima = fin
            ped = mapa.get(clean(r.get("ot")))
            if not ped:
                continue
            acc = por_pedido.setdefault(ped, {"pedido": ped, "horas": 0.0, "apuntes": 0,
                                              "ots": 0, "ultima": None})
            acc["horas"] += h
            acc["apuntes"] += int(r.get("apuntes") or 0)
            acc["ots"] += 1
            if fin and (acc["ultima"] is None or fin > acc["ultima"]):
                acc["ultima"] = fin
        lista = sorted(por_pedido.values(), key=lambda a: -a["horas"])
        ops = [{"operacion": clean(r.get("operacion")), "horas": float(r.get("horas") or 0),
                "personas": int(r.get("personas") or 0), "apuntes": int(r.get("apuntes") or 0)}
               for r in safe_query(_SQL_HORAS_OP, (desde,), label="horas por operación")]
        return {"por_pedido": lista, "por_operacion": ops, "ultima": ultima,
                "total": total, "imputadas": sum(a["horas"] for a in lista)}
    return _cache.get(f"horas:{days}", build)


def hours_for_pedido(num_order: str) -> dict | None:
    key = norm_order(num_order)
    if not key:
        return None
    return next((a for a in hours()["por_pedido"] if a["pedido"] == key), None)


# ── Exportación ───────────────────────────────────────────────────────────────

def export_workshop_rows(rows: list[dict]) -> list[dict]:
    return [{
        "Nº Pedido": r["pedido_raw"], "Cliente": r["cliente"], "Equipo": r["equipo"],
        "Unidades": r["unidades"], "% Taller": r["taller"], "% Montaje": r["montaje"],
        "% Envío": r["envio"],
        "Fecha prevista": r["prevista"].strftime("%d-%m-%Y") if r["prevista"] else "",
        "Días de retraso": r["retraso"] or "",
        "Material disponible": r["material"], "Observaciones": r["obs"],
    } for r in rows]


def export_hours_rows(rows: list[dict]) -> list[dict]:
    return [{
        "Nº Pedido": r["pedido"], "Horas": round(r["horas"], 1), "OTs": r["ots"],
        "Apuntes": r["apuntes"],
        "Última imputación": r["ultima"].strftime("%d-%m-%Y") if r["ultima"] else "",
    } for r in rows]


def export_excel(rows: list[dict], path: str, kind: str = "taller") -> str:
    import pandas as pd

    data = export_workshop_rows(rows) if kind == "taller" else export_hours_rows(rows)
    pd.DataFrame(data).to_excel(path, index=False, engine="openpyxl")
    return path
