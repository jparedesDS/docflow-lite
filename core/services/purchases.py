"""Compras: material pedido a proveedor que todavía no ha llegado.

Responde a la pregunta más repetida de un pedido: «¿por qué va tarde?». El ERP
guarda los pedidos a proveedor en `purch_fact`:

  · `supplier_ord_header` — cabecera: proveedor, fecha del pedido y **fecha
    prometida de entrega** (`delivery_date`). El campo `notes` dice para qué
    pedido nuestro es («P-26/059 Y ALMACEN», «P-26/27-S1»…): de ahí se extrae
    el Nº de pedido, tolerando las mil formas en que se escribe.
  · `supplier_ord_detail` — líneas con `quantity` y **`pending`** (lo que falta
    por recibir), y hasta tres entregas parciales con su albarán.
  · `supplies` — descripción del material; `suppliers` — el proveedor.

De 3.168 pedidos a proveedor, el 68 % referencia un pedido nuestro (prácticamente
todos los recientes). Solo lectura, caché corta.
"""

from __future__ import annotations

import logging
from datetime import date

from core.services.erp_common import (
    Cache, as_date, available, clean, norm_order, orders_in, safe_query,
)

logger = logging.getLogger(__name__)

SINCE_YEAR = 2024        # compras anteriores ya no interesan
SOON_DAYS = 30           # «llega pronto»

_cache = Cache()

_SQL = """
    SELECT h.id, h.notes, h.order_date, h.delivery_date, h.supplier_order_num,
           h.delivery_term, h.delivery_way,
           s.name AS supplier, s.phone_number, s.city,
           d.quantity, d.pending, d.position_supply,
           su.description AS material, su.reference,
           d.deliv_date_1, d.deliv_date_2, d.deliv_date_3
    FROM purch_fact.supplier_ord_detail d
    JOIN purch_fact.supplier_ord_header h ON h.id = d.supplier_ord_header_id
    LEFT JOIN purch_fact.suppliers s ON s.id = h.supplier_id
    LEFT JOIN purch_fact.supplies su ON su.id = d.supply_id
    WHERE coalesce(d.pending, 0) > 0
      AND h.order_date >= %s
    ORDER BY h.delivery_date NULLS LAST, h.id
"""


def invalidate_cache() -> None:
    _cache.clear()


def is_available() -> bool:
    return available()


def _row(r: dict) -> dict:
    prometido = as_date(r.get("delivery_date"))
    hoy = date.today()
    retraso = (hoy - prometido).days if prometido and prometido < hoy else 0
    pedidos = orders_in(r.get("notes"))
    return {
        "pedidos": pedidos,
        "pedido": pedidos[0] if pedidos else "",
        "para": clean(r.get("notes")),
        "proveedor": clean(r.get("supplier")),
        "telefono": clean(r.get("phone_number")),
        "material": clean(r.get("material")) or clean(r.get("reference")),
        "cantidad": _num(r.get("quantity")),
        "pendiente": _num(r.get("pending")),
        "pedido_prov": clean(r.get("supplier_order_num")),
        "fecha": as_date(r.get("order_date")),
        "prometido": prometido,
        "retraso": retraso,
        "plazo": clean(r.get("delivery_term")),
        "transporte": clean(r.get("delivery_way")),
    }


def _num(value) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def pending(since_year: int = SINCE_YEAR) -> list[dict]:
    """Líneas de compra pendientes de recibir, las más retrasadas primero."""
    def build():
        rows = safe_query(_SQL, (date(since_year, 1, 1),), label="compras pendientes")
        out = [_row(r) for r in rows]
        out.sort(key=lambda r: (-r["retraso"], r["prometido"] or date.max))
        return out
    return _cache.get(f"pending:{since_year}", build)


def for_pedido(num_order: str) -> list[dict]:
    """Compras pendientes que afectan a un pedido nuestro."""
    key = norm_order(num_order)
    if not key:
        return []
    return [r for r in pending() if key in r["pedidos"]]


def stats() -> dict:
    rows = pending()
    hoy = date.today()
    retrasadas = [r for r in rows if r["retraso"] > 0]
    pronto = [r for r in rows if r["prometido"] and hoy <= r["prometido"]
              and (r["prometido"] - hoy).days <= SOON_DAYS]
    return {
        "lineas": len(rows),
        "retrasadas": len(retrasadas),
        "retraso_max": max((r["retraso"] for r in rows), default=0),
        "proveedores": len({r["proveedor"] for r in rows if r["proveedor"]}),
        "pedidos": len({p for r in rows for p in r["pedidos"]}),
        "pronto": len(pronto),
    }


def export_rows(rows: list[dict]) -> list[dict]:
    return [{
        "Nº Pedido": r["pedido"] or r["para"],
        "Proveedor": r["proveedor"],
        "Material": r["material"],
        "Pendiente": r["pendiente"],
        "De": r["cantidad"],
        "Pedido a proveedor": r["pedido_prov"],
        "Fecha pedido": r["fecha"].strftime("%d-%m-%Y") if r["fecha"] else "",
        "Prometido": r["prometido"].strftime("%d-%m-%Y") if r["prometido"] else "",
        "Días de retraso": r["retraso"] or "",
        "Plazo": r["plazo"],
    } for r in rows]


def export_excel(rows: list[dict], path: str) -> str:
    import pandas as pd

    pd.DataFrame(export_rows(rows)).to_excel(path, index=False, engine="openpyxl")
    return path
