"""Administración: facturas pendientes de cobro y avales en vigor.

  · **Facturas** (`purch_fact.invoice_header`, 6.359 desde 2012): número,
    importe, fecha y `pay_date`. Las que no tienen fecha de cobro están
    pendientes (`invoice_state` = 'Pagada' cuando sí lo están). El campo
    `our_ref` enlaza con nuestro pedido en el 99 % de los casos, y `id_client`
    con `purch_fact.clients`.
  · **Avales** (`orders.warranty_bond*`): 98 pedidos con aval EN VIGOR, con
    importe, banco, referencia y fecha de vencimiento. Un aval que vence sin
    cancelarse sigue costando comisiones, así que interesa verlos venir.

Aviso sobre los datos: el campo `warranty_bond` dice a veces «No Aplica» en
pedidos que sí tienen aval en vigor, así que manda el estado + la fecha de
vencimiento, no ese campo.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from core.services.erp_common import Cache, as_date, available, clean, norm_order, safe_query

logger = logging.getLogger(__name__)

SOON_DAYS = 90           # un aval que vence en 3 meses ya conviene mirarlo
RECENT_YEARS = 3         # ventana por defecto de facturas pendientes

_cache = Cache()

_SQL_FACTURAS = """
    SELECT i.num_invoice, i.our_ref, i.date_invoice, i.pay_date, i.invoice_state,
           i.tax_base_amount::text AS importe, i.date_send_invoice, i.destination,
           c.name AS cliente
    FROM purch_fact.invoice_header i
    LEFT JOIN purch_fact.clients c ON c.id::text = i.id_client::text
    WHERE i.date_invoice >= %s
    ORDER BY i.date_invoice DESC
"""

_SQL_AVALES = """
    SELECT o.num_order, o.warranty_bond, o.warranty_bond_state,
           o.warranty_bond_expiring_date, o.warranty_bond_amount,
           o.warranty_bond_bank, o.warranty_bond_reference,
           f.client, f.final_client
    FROM public.orders o
    LEFT JOIN public.offers f ON f.num_offer = o.num_offer
    WHERE coalesce(o.warranty_bond_expiring_date, '') <> ''
"""

_MONEY_RE = re.compile(r"-?[\d.,]+")


def invalidate_cache() -> None:
    _cache.clear()


def is_available() -> bool:
    return available()


def money(value) -> float:
    """'75.449,00 €' → 75449.0. Devuelve 0.0 si no hay número."""
    m = _MONEY_RE.search(str(value or "").replace("\xa0", " "))
    if not m:
        return 0.0
    s = m.group(0).strip()
    # Formato español: el punto separa miles y la coma los decimales.
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def euros(value: float) -> str:
    return f"{value:,.0f} €".replace(",", ".")


# ── Facturas ──────────────────────────────────────────────────────────────────

def invoices(years: int = RECENT_YEARS) -> list[dict]:
    """Facturas emitidas en los últimos `years` años, las recientes primero."""
    def build():
        hoy = date.today()
        desde = date(hoy.year - years, 1, 1)
        out = []
        for r in safe_query(_SQL_FACTURAS, (desde,), label="facturas"):
            emitida = as_date(r.get("date_invoice"))
            cobro = as_date(r.get("pay_date"))
            pagada = bool(cobro) or clean(r.get("invoice_state")).lower() == "pagada"
            out.append({
                "numero": clean(r.get("num_invoice")),
                "pedido": norm_order(r.get("our_ref")) or clean(r.get("our_ref")),
                "pedido_raw": clean(r.get("our_ref")),
                "cliente": clean(r.get("cliente")),
                "emitida": emitida,
                "cobro": cobro,
                "importe": money(r.get("importe")),
                "pagada": pagada,
                "dias": (hoy - emitida).days if (emitida and not pagada) else 0,
                "destino": clean(r.get("destination")),
            })
        return out
    return _cache.get(f"facturas:{years}", build)


def unpaid(years: int = RECENT_YEARS) -> list[dict]:
    """Facturas sin cobro registrado, de la más antigua a la más reciente."""
    rows = [f for f in invoices(years) if not f["pagada"]]
    rows.sort(key=lambda f: f["emitida"] or date.max)
    return rows


def invoices_for_pedido(num_order: str) -> list[dict]:
    key = norm_order(num_order)
    if not key:
        return []
    return [f for f in invoices() if f["pedido"] == key]


def invoice_stats(years: int = RECENT_YEARS) -> dict:
    todas = invoices(years)
    pend = [f for f in todas if not f["pagada"]]
    return {
        "facturas": len(todas),
        "pendientes": len(pend),
        "importe_pendiente": sum(f["importe"] for f in pend),
        "mas_antigua": max((f["dias"] for f in pend), default=0),
        "clientes": len({f["cliente"] for f in pend if f["cliente"]}),
    }


# ── Avales ────────────────────────────────────────────────────────────────────

def bonds() -> list[dict]:
    """Avales con fecha de vencimiento, los que vencen antes primero."""
    def build():
        hoy = date.today()
        out = []
        for r in safe_query(_SQL_AVALES, label="avales"):
            vence = as_date(r.get("warranty_bond_expiring_date"))
            dias = (vence - hoy).days if vence else None
            cliente = clean(r.get("final_client")) or clean(r.get("client"))
            out.append({
                "pedido": clean(r.get("num_order")),
                "cliente": cliente,
                "estado": clean(r.get("warranty_bond_state")),
                "vence": vence,
                "dias": dias,
                "importe": money(r.get("warranty_bond_amount")),
                "banco": clean(r.get("warranty_bond_bank")),
                "referencia": clean(r.get("warranty_bond_reference")),
                "vencido": bool(vence and vence < hoy),
                "pronto": bool(dias is not None and 0 <= dias <= SOON_DAYS),
            })
        out.sort(key=lambda a: a["vence"] or date.max)
        return out
    return _cache.get("avales", build)


def bonds_for_pedido(num_order: str) -> list[dict]:
    key = norm_order(num_order)
    if not key:
        return []
    return [a for a in bonds() if norm_order(a["pedido"]) == key]


def bond_stats() -> dict:
    rows = bonds()
    return {
        "total": len(rows),
        "vencidos": sum(1 for a in rows if a["vencido"]),
        "pronto": sum(1 for a in rows if a["pronto"]),
        "importe": sum(a["importe"] for a in rows if not a["vencido"]),
        "bancos": len({a["banco"] for a in rows if a["banco"]}),
    }


# ── Exportación ───────────────────────────────────────────────────────────────

def export_invoice_rows(rows: list[dict]) -> list[dict]:
    return [{
        "Factura": f["numero"], "Nº Pedido": f["pedido_raw"], "Cliente": f["cliente"],
        "Emitida": f["emitida"].strftime("%d-%m-%Y") if f["emitida"] else "",
        "Importe": f["importe"],
        "Cobrada": f["cobro"].strftime("%d-%m-%Y") if f["cobro"] else "",
        "Días sin cobrar": f["dias"] or "",
    } for f in rows]


def export_bond_rows(rows: list[dict]) -> list[dict]:
    return [{
        "Nº Pedido": a["pedido"], "Cliente": a["cliente"], "Estado": a["estado"],
        "Vence": a["vence"].strftime("%d-%m-%Y") if a["vence"] else "",
        "Días": a["dias"] if a["dias"] is not None else "",
        "Importe": a["importe"], "Banco": a["banco"], "Referencia": a["referencia"],
    } for a in rows]


def export_excel(rows: list[dict], path: str, kind: str = "facturas") -> str:
    import pandas as pd

    data = export_invoice_rows(rows) if kind == "facturas" else export_bond_rows(rows)
    pd.DataFrame(data).to_excel(path, index=False, engine="openpyxl")
    return path
