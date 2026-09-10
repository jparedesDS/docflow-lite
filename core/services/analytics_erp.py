"""Analítica de negocio: lo que se puede medir desde que existe la BBDD del ERP.

`analytics.py` mira la documentación (los Excel del monitoring). Este módulo mira
el resto de la empresa, que hasta ahora no entraba en la Analítica: el dinero
—`orders.order_amount` y `offers.offer_amount` están rellenos al 100 %—, el
embudo comercial de ofertas y el estado de taller, compras, calidad y almacén.

Todo pasa por `erp_common.safe_query`, así que si el ERP no está disponible se
devuelven estructuras vacías y la vista lo dice, en vez de reventar.
"""

from __future__ import annotations

from datetime import date

from core.services import erp_common as ec

_cache = ec.Cache(ttl=300)

# La empresa lleva pedidos desde 2008, pero el detalle solo es fiable de un
# tiempo a esta parte; con 8 años se ven ciclos completos sin ruido antiguo.
DESDE_ANIO = date.today().year - 7

MESES_ES = ("ene", "feb", "mar", "abr", "may", "jun",
            "jul", "ago", "sep", "oct", "nov", "dic")

# Estados de oferta del ERP agrupados por lo que significan de verdad. La
# distinción importa: «Declinada» o «Retirada» las decidimos nosotros, no son
# ofertas perdidas contra un competidor, y «Budgetary» ni siquiera es una oferta
# en firme. Por eso la tasa de adjudicación se calcula solo sobre las resueltas
# de verdad —ganadas frente a perdidas— y las que siguen vivas se cuentan aparte.
_GRUPO_ESTADO = {
    "adjudicada": "ganada",
    "perdida": "perdida",
    "presentada": "viva",
    "registrada": "viva",
    "declinada": "descartada",
    "retirada": "descartada",
    "no ofertada": "descartada",
    "budgetary": "presupuestaria",
}


def grupo_estado(estado: str) -> str:
    return _GRUPO_ESTADO.get(str(estado or "").strip().lower(), "descartada")


def disponible() -> bool:
    return ec.available()


def invalidate_cache() -> None:
    _cache.clear()


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ── Comercial: ofertas y pedidos ─────────────────────────────────────────────

def comercial(desde: int = DESDE_ANIO) -> dict:
    """Embudo comercial por año, por comercial y por estado de la oferta.

    OJO con el año de la oferta: la columna `offer_year` está a medio rellenar
    (587 ofertas sin año, y de 2026 solo tiene 18 cuando por fecha de registro
    son 478 — dejó de escribirse en enero). Se usa `register_date`, que está en
    todas. En `orders` no pasa: ahí `order_year` coincide siempre con la fecha.
    """
    def build():
        pedidos = ec.safe_query("""
            SELECT order_year AS anio, count(*) AS n,
                   coalesce(sum(order_amount::numeric), 0) AS importe
            FROM public.orders WHERE order_year >= %s GROUP BY 1 ORDER BY 1
        """, (desde,), label="pedidos por año")

        crudo = ec.safe_query("""
            SELECT extract(year FROM f.register_date)::int AS anio,
                   coalesce(nullif(trim(f.state), ''), 'Sin estado') AS estado,
                   coalesce(nullif(i.initials, 'No hay datos'), '—') AS iniciales,
                   coalesce(nullif(trim(f.nac_ext), ''), 'Sin definir') AS mercado,
                   count(*) AS n, coalesce(sum(f.offer_amount::numeric), 0) AS importe
            FROM public.offers f
            LEFT JOIN users_data.initials i ON lower(i.username) = lower(f.responsible)
            WHERE f.register_date IS NOT NULL
              AND extract(year FROM f.register_date) >= %s
            GROUP BY 1, 2, 3, 4
        """, (desde,), label="ofertas")

        def acumular(clave):
            """Agrupa las ofertas por `clave` y reparte por grupo de estado."""
            acc: dict = {}
            for r in crudo:
                k = r[clave]
                g = acc.setdefault(k, {"ofertas": 0, "importe": 0.0, "imp_ganadas": 0.0,
                                       "ganada": 0, "perdida": 0, "viva": 0,
                                       "descartada": 0, "presupuestaria": 0})
                grupo = grupo_estado(r["estado"])
                n, imp = int(r["n"] or 0), _f(r["importe"])
                g["ofertas"] += n
                g["importe"] += imp
                g[grupo] += n
                if grupo == "ganada":
                    g["imp_ganadas"] += imp
            for g in acc.values():
                resueltas = g["ganada"] + g["perdida"]
                g["resueltas"] = resueltas
                g["tasa"] = round(100 * g["ganada"] / resueltas, 1) if resueltas else 0.0
            return acc

        ped = {int(r["anio"]): r for r in pedidos if r.get("anio")}
        por_anio_of = acumular("anio")
        filas = []
        for a in sorted(set(por_anio_of) | set(ped)):
            o = por_anio_of.get(a, {})
            p = ped.get(a, {})
            filas.append({
                "anio": a,
                "ofertas": o.get("ofertas", 0),
                "of_importe": o.get("importe", 0.0),
                "ganadas": o.get("ganada", 0),
                "perdidas": o.get("perdida", 0),
                "vivas": o.get("viva", 0),
                "resueltas": o.get("resueltas", 0),
                "imp_ganadas": o.get("imp_ganadas", 0.0),
                "tasa": o.get("tasa", 0.0),
                "pedidos": int(p.get("n") or 0),
                "importe": _f(p.get("importe")),
            })

        por_comercial = [{"iniciales": k, **v} for k, v in acumular("iniciales").items()]
        por_comercial.sort(key=lambda r: r["imp_ganadas"], reverse=True)
        mercado = [{"mercado": k, **v} for k, v in acumular("mercado").items()]
        mercado.sort(key=lambda r: r["ofertas"], reverse=True)

        estados: dict = {}
        for r in crudo:
            g = estados.setdefault(r["estado"], {"n": 0, "importe": 0.0})
            g["n"] += int(r["n"] or 0)
            g["importe"] += _f(r["importe"])
        por_estado = [{"estado": k, **v} for k, v in estados.items()]
        por_estado.sort(key=lambda r: r["n"], reverse=True)

        return {"por_anio": filas, "por_comercial": por_comercial,
                "por_estado": por_estado, "mercado": mercado}

    return _cache.get("comercial", build)


def pedidos_mensuales(meses: int = 24) -> dict:
    """Pedidos e importe mes a mes, con el mismo mes del año anterior al lado."""
    def build():
        rows = ec.safe_query("""
            SELECT order_year AS anio, order_month AS mes, count(*) AS n,
                   coalesce(sum(order_amount::numeric), 0) AS importe
            FROM public.orders
            WHERE order_year >= %s AND order_month BETWEEN 1 AND 12
            GROUP BY 1, 2
        """, (date.today().year - 3,), label="pedidos por mes")
        idx = {(int(r["anio"]), int(r["mes"])): r for r in rows if r.get("anio") and r.get("mes")}

        hoy = date.today()
        y, m = hoy.year, hoy.month
        periodo = []
        for _ in range(meses):
            periodo.append((y, m))
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        periodo.reverse()

        labels, importes, num, previo = [], [], [], []
        for y, m in periodo:
            r = idx.get((y, m), {})
            p = idx.get((y - 1, m), {})
            labels.append(f"{MESES_ES[m - 1]} {str(y)[2:]}")
            importes.append(_f(r.get("importe")))
            num.append(int(r.get("n") or 0))
            previo.append(_f(p.get("importe")))
        return {"labels": labels, "importes": importes, "pedidos": num,
                "importes_previo": previo}

    return _cache.get(f"mensual::{meses}", build)


def cartera() -> dict:
    """Pedidos abiertos: cuántos, por cuánto y cuánto llevan andando."""
    def build():
        rows = ec.safe_query("""
            SELECT count(*) AS n,
                   coalesce(sum(order_amount::numeric), 0) AS importe,
                   count(*) FILTER (WHERE expected_date < current_date) AS fuera_plazo,
                   coalesce(avg(porc_workshop), 0) AS avance
            FROM public.orders
            WHERE coalesce(closed, '') = '' AND order_year >= %s
        """, (date.today().year - 3,), label="cartera")
        r = rows[0] if rows else {}
        return {"pedidos": int(r.get("n") or 0), "importe": _f(r.get("importe")),
                "fuera_plazo": int(r.get("fuera_plazo") or 0),
                "avance": round(_f(r.get("avance")))}

    return _cache.get("cartera", build)


def top_clientes(desde: int = DESDE_ANIO, limite: int = 12) -> list[dict]:
    """Clientes por importe de pedido (el cliente sale de la oferta)."""
    def build():
        rows = ec.safe_query("""
            -- «No hay datos» es el relleno del ERP cuando el cliente no se puso;
            -- son 1.323 ofertas y taparía a clientes de verdad en el ranking.
            SELECT coalesce(nullif(nullif(trim(f.final_client), ''), 'No hay datos'),
                            nullif(nullif(trim(f.client), ''), 'No hay datos'),
                            'Sin cliente') AS cliente,
                   count(*) AS pedidos,
                   coalesce(sum(o.order_amount::numeric), 0) AS importe
            FROM public.orders o
            LEFT JOIN public.offers f ON f.num_offer = o.num_offer
            WHERE o.order_year >= %s
            GROUP BY 1 ORDER BY 3 DESC LIMIT %s
        """, (desde, limite), label="top clientes")
        for r in rows:
            r["pedidos"] = int(r.get("pedidos") or 0)
            r["importe"] = _f(r.get("importe"))
        return rows

    return _cache.get(f"top_clientes::{desde}::{limite}", build)


# ── Operaciones: el estado del resto de la casa ──────────────────────────────

def operaciones() -> dict:
    """KPIs de taller, compras, calidad y almacén, cada uno de su servicio.

    Se piden aquí juntos para que la vista haga una sola pasada en un hilo; cada
    servicio ya trae su propia caché.
    """
    def build():
        out: dict = {}
        for clave, fn in (
            ("taller", lambda: _mod("production").workshop_stats()),
            ("horas", lambda: _mod("production").hours()),
            ("compras", lambda: _mod("purchases").stats()),
            ("nc", lambda: _mod("quality").nc_stats()),
            ("equipos", lambda: _mod("quality").equipment_stats()),
            ("facturas", lambda: _mod("administration").invoice_stats()),
            ("avales", lambda: _mod("administration").bond_stats()),
            ("almacen", lambda: _mod("warehouse").snapshot().get("stats", {})),
        ):
            try:
                out[clave] = fn() or {}
            except Exception:  # noqa: BLE001 — un departamento caído no tumba el resto
                out[clave] = {}
        try:
            out["nc_tipos"] = _mod("quality").nc_by_type()[:8]
        except Exception:  # noqa: BLE001
            out["nc_tipos"] = []
        return out

    return _cache.get("operaciones", build)


def _mod(nombre: str):
    from importlib import import_module
    return import_module(f"core.services.{nombre}")


def nc_por_anio(desde: int = DESDE_ANIO) -> list[dict]:
    """No conformidades por año, con las que costaron dinero."""
    def build():
        rows = ec.safe_query("""
            SELECT extract(year FROM nc_date)::int AS anio, count(*) AS n,
                   coalesce(sum(nullif(cost::text, '')::money::numeric), 0) AS coste
            FROM verification.nc_report
            WHERE nc_date IS NOT NULL AND extract(year FROM nc_date) >= %s
            GROUP BY 1 ORDER BY 1
        """, (desde,), label="NC por año")
        for r in rows:
            r["n"] = int(r.get("n") or 0)
            r["coste"] = _f(r.get("coste"))
        return rows

    return _cache.get(f"nc_anio::{desde}", build)
