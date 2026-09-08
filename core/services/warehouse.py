"""Almacén: cuánto tiempo espera el material desde que está listo hasta que sale.

El ERP no guarda una «fecha de entrada en almacén» como tal. El tramo lo marcan
dos campos de `public.orders`:

  · `delivery_notification` — **Aviso de entrega**: el material está terminado y
    se avisa al cliente. Es cuando queda esperando en el almacén.
  · `last_date_deliveries`  — **Fecha de envío**: sale de fábrica o lo recogen.

Comprobado sobre los 335 pedidos que tienen las dos fechas: ninguno sale antes
del aviso (mediana 6 días). El campo se empezó a usar en 2025 — cubre el 62 % de
los envíos de ese año y el 92 % de 2026 —, así que no hay histórico anterior.
Se descartaron otras fuentes por poco fiables: el % de montaje del log de
cambios (43 % de resultados negativos), `recep_date_assembly` (es la entrada EN
montaje, incluye la fabricación) y `partial_date_deliveries` (trae nombres de
transportista donde debería ir la fecha).

Solo lectura sobre el Postgres del ERP, con caché corta como `erp_tags`.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime

logger = logging.getLogger(__name__)

CACHE_TTL = 120          # s
HISTORY_DAYS = 540       # ventana del histórico (~18 meses)

# Tramos de espera: hasta una semana es lo normal (mediana 6 días).
OK_DAYS, WARN_DAYS = 7, 30

BUCKETS = [
    ("Mismo día", lambda d: d == 0),
    ("1-7 días", lambda d: 1 <= d <= 7),
    ("8-15 días", lambda d: 8 <= d <= 15),
    ("16-30 días", lambda d: 16 <= d <= 30),
    ("31-60 días", lambda d: 31 <= d <= 60),
    ("Más de 60", lambda d: d > 60),
]

_SQL = """
    SELECT o.num_order, o.delivery_notification, o.last_date_deliveries,
           o.closed, o.obs_deliveries, o.expected_date,
           f.client, f.final_client, f.material, f.project
    FROM public.orders o
    LEFT JOIN public.offers f ON f.num_offer = o.num_offer
    WHERE coalesce(o.delivery_notification, '') <> ''
    ORDER BY o.num_order
"""

_cache: dict[str, tuple[float, object]] = {}


def invalidate_cache() -> None:
    _cache.clear()


def _cached(key: str, builder, ttl: float = CACHE_TTL):
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    value = builder()
    _cache[key] = (now, value)
    return value


def is_available() -> bool:
    """¿Responde el ERP? (delegado en erp_tags, que ya cachea el ping)."""
    from core.services import erp_tags
    return erp_tags.is_available()


# ── Utilidades ────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})")


def parse_date(value) -> date | None:
    """Fechas del ERP (texto DD/MM/YYYY, a veces con ruido) → date o None."""
    if hasattr(value, "year") and not isinstance(value, str):
        return value if isinstance(value, date) else None
    m = _DATE_RE.search(str(value or "").strip())
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y = y + 2000 if y < 100 else y
    try:
        return datetime(y, mo, d).date()
    except ValueError:
        return None


def severity(dias: int) -> str:
    """'ok' (≤7 días) · 'warn' (≤30) · 'bad' (más)."""
    if dias <= OK_DAYS:
        return "ok"
    return "warn" if dias <= WARN_DAYS else "bad"


def _client(row: dict) -> str:
    """Cliente final / planta; si el ERP no lo tiene, la ingeniería contratante."""
    for key in ("final_client", "client"):
        val = str(row.get(key) or "").strip()
        if val and val.lower() != "no hay datos":
            return val
    return ""


# ── Datos ─────────────────────────────────────────────────────────────────────

def _fetch_rows() -> list[dict]:
    from core.services import erp_db

    conn = erp_db._connect()
    try:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = 20000;")
        cur.execute(_SQL)
        names = [c.name for c in cur.description]
        raw = [dict(zip(names, r)) for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()

    hoy = date.today()
    out = []
    for r in raw:
        aviso = parse_date(r["delivery_notification"])
        if aviso is None:
            continue
        envio = parse_date(r["last_date_deliveries"])
        fin = envio or hoy
        dias = (fin - aviso).days
        if dias < 0:
            continue                      # fecha incoherente en el ERP: fuera
        out.append({
            "pedido": r["num_order"] or "",
            "cliente": _client(r),
            "equipo": str(r.get("material") or "").strip(),
            "proyecto": str(r.get("project") or "").strip(),
            "aviso": aviso,
            "envio": envio,
            "dias": dias,
            "transporte": str(r.get("obs_deliveries") or "").strip(),
            "cerrado": str(r.get("closed") or "").strip(),
            "en_almacen": envio is None,
        })
    return out


def snapshot(history_days: int = HISTORY_DAYS) -> dict:
    """Foto del almacén: lo que está esperando, lo enviado y las cifras.

    Devuelve {available, stock, shipped, stats, buckets}. Si el ERP no responde,
    `available` es False y las listas van vacías (la vista muestra el aviso).
    """
    def build() -> dict:
        if not is_available():
            return {"available": False, "stock": [], "shipped": [], "stats": {}, "buckets": []}
        try:
            rows = _fetch_rows()
        except Exception as exc:  # noqa: BLE001 — el ERP puede cerrarse a media consulta
            logger.warning("Almacén: no se pudo consultar el ERP: %s", exc)
            return {"available": False, "stock": [], "shipped": [], "stats": {}, "buckets": []}

        hoy = date.today()
        stock = sorted([r for r in rows if r["en_almacen"]], key=lambda r: r["dias"], reverse=True)
        shipped = [r for r in rows if not r["en_almacen"]
                   and (hoy - r["envio"]).days <= history_days]
        shipped.sort(key=lambda r: r["envio"], reverse=True)

        dias_env = sorted(r["dias"] for r in shipped)
        n = len(dias_env)
        mediana = dias_env[n // 2] if n else 0
        en_semana = sum(1 for d in dias_env if d <= OK_DAYS)
        recientes = [r for r in shipped if (hoy - r["envio"]).days <= 30]
        stats = {
            "en_almacen": len(stock),
            "dias_max": stock[0]["dias"] if stock else 0,
            "pedido_max": stock[0]["pedido"] if stock else "",
            "atascados": sum(1 for r in stock if r["dias"] > WARN_DAYS),
            "mediana": mediana,
            "enviados": n,
            "pct_semana": round(100 * en_semana / n) if n else 0,
            "enviados_30d": len(recientes),
            "mediana_30d": (sorted(r["dias"] for r in recientes)[len(recientes) // 2]
                            if recientes else 0),
        }
        buckets = [(label, sum(1 for d in dias_env if test(d))) for label, test in BUCKETS]
        return {"available": True, "stock": stock, "shipped": shipped,
                "stats": stats, "buckets": buckets}

    return _cached(f"snapshot:{history_days}", build)


def for_pedido(num_order: str) -> dict | None:
    """Datos de almacén de un pedido (para la ficha de Seguimiento).

    Tolera el sufijo de suministro: 'P-26/048' encuentra 'P-26/048-S00'.
    """
    base = str(num_order or "").strip().upper()
    if not base:
        return None
    snap = snapshot()
    if not snap["available"]:
        return None
    for r in snap["stock"] + snap["shipped"]:
        ped = r["pedido"].strip().upper()
        if ped == base or ped.startswith(base + "-S") or base.startswith(ped + "-S"):
            return r
    return None


def export_rows(rows: list[dict]) -> "list[dict]":
    """Filas listas para Excel (cabeceras en español)."""
    return [{
        "Nº Pedido": r["pedido"],
        "Cliente": r["cliente"],
        "Equipo": r["equipo"],
        "Proyecto": r["proyecto"],
        "Aviso de entrega": r["aviso"].strftime("%d-%m-%Y") if r["aviso"] else "",
        "Fecha de envío": r["envio"].strftime("%d-%m-%Y") if r["envio"] else "",
        "Días en almacén": r["dias"],
        "Transporte": r["transporte"],
        "Cerrado": r["cerrado"],
    } for r in rows]


def export_excel(rows: list[dict], path: str) -> str:
    import pandas as pd

    pd.DataFrame(export_rows(rows)).to_excel(path, index=False, engine="openpyxl")
    return path
