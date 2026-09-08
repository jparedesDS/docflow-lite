"""Piezas comunes de los servicios que leen el ERP (compras, calidad, auditoría).

Todos comparten la misma mecánica: consulta de SOLO LECTURA al Postgres local,
caché corta y degradación limpia si el ERP está cerrado. Aquí vive lo repetido
para que cada servicio se ocupe solo de su dominio.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime

logger = logging.getLogger(__name__)

CACHE_TTL = 180          # s


# ── Caché ─────────────────────────────────────────────────────────────────────

class Cache:
    """Caché por clave con TTL, propia de cada servicio."""

    def __init__(self, ttl: float = CACHE_TTL):
        self.ttl = ttl
        self._data: dict[str, tuple[float, object]] = {}

    def clear(self) -> None:
        self._data.clear()

    def get(self, key: str, builder):
        now = time.time()
        hit = self._data.get(key)
        if hit and (now - hit[0]) < self.ttl:
            return hit[1]
        value = builder()
        self._data[key] = (now, value)
        return value


# ── Conexión ──────────────────────────────────────────────────────────────────

def available() -> bool:
    """¿Responde el ERP? Cacheado por erp_tags; nunca lanza."""
    from core.services import erp_tags
    return erp_tags.is_available()


def query(sql: str, params=None, timeout_ms: int = 20000) -> list[dict]:
    """Ejecuta una consulta de lectura y devuelve list[dict]. Lanza si falla."""
    from core.services import erp_db

    conn = erp_db._connect()
    try:
        cur = conn.cursor()
        cur.execute(f"SET statement_timeout = {int(timeout_ms)};")
        cur.execute(sql, params or ())
        names = [c.name for c in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()
    return rows


def safe_query(sql: str, params=None, label: str = "") -> list[dict]:
    """Como `query` pero devuelve [] si el ERP no está o la consulta falla."""
    if not available():
        return []
    try:
        return query(sql, params)
    except Exception as exc:  # noqa: BLE001 — el ERP puede cerrarse a media consulta
        logger.warning("ERP: consulta %s falló: %s", label or "", exc)
        return []


# ── Fechas y textos ───────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})")


def as_date(value) -> date | None:
    """date/datetime o texto DD/MM/YYYY (con ruido) → date. None si no hay fecha."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    m = _DATE_RE.search(str(value or "").strip())
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y = y + 2000 if y < 100 else y
    try:
        return datetime(y, mo, d).date()
    except ValueError:
        return None


def fmt(d) -> str:
    return d.strftime("%d-%m-%Y") if d else "—"


def clean(value) -> str:
    """Texto del ERP saneado: sin None, sin 'No hay datos', sin espacios sobrantes."""
    s = str(value or "").strip()
    return "" if s.lower() in ("none", "nan", "no hay datos", "-") else s


# ── Nº de pedido ──────────────────────────────────────────────────────────────

# El ERP escribe los pedidos de muchas formas: 'P-26/059', 'P-26/21 S00 Y S01',
# 'P-26/27-S1', 'PA-26/067'. Se normalizan a 'P-26/059' (3 dígitos, sin sufijo).
_ORDER_RE = re.compile(r"\b(PA|P)\s*-?\s*(\d{2})\s*[/-]\s*(\d{1,3})", re.I)


def orders_in(text) -> list[str]:
    """Todos los Nº de pedido que aparecen en un texto, normalizados."""
    out, seen = [], set()
    for pre, yy, nnn in _ORDER_RE.findall(str(text or "")):
        code = f"{pre.upper()}-{yy}/{int(nnn):03d}"
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def norm_order(value) -> str:
    """Nº de pedido normalizado (sin sufijo -Sxx) o '' si no lo hay."""
    found = orders_in(value)
    return found[0] if found else ""


def same_order(a, b) -> bool:
    """Compara pedidos ignorando formato y sufijo de suministro."""
    na, nb = norm_order(a), norm_order(b)
    return bool(na) and na == nb


# ── Usuarios del ERP ──────────────────────────────────────────────────────────

_users_cache = Cache(ttl=3600)


def user_initials() -> dict:
    """{username del ERP → iniciales} (j.paredes → JP). {} si el ERP no está."""
    def build():
        rows = safe_query("select username, initials from users_data.initials", label="initials")
        return {clean(r["username"]).lower(): clean(r["initials"])
                for r in rows if clean(r["initials"]).lower() != "no hay datos"}
    return _users_cache.get("initials", build)


def who(username) -> str:
    """Nombre presentable de un usuario del ERP.

    Usa las iniciales de `users_data.initials` cuando están (e.carrillo → ECI).
    Esa tabla no cubre a todo el mundo (falta j.paredes, j.martinez…), así que
    para el resto se compone un nombre legible del propio usuario
    ('j.paredes' → 'J. Paredes') en vez de inventar unas iniciales.
    """
    u = clean(username)
    if not u:
        return ""
    known = user_initials().get(u.lower())
    if known:
        return known
    if u.lower() in ("postgres", "erp", "system"):
        return "sistema"
    m = re.match(r"^([a-záéíóúñ])[._]([a-záéíóúñ' -]+)$", u, re.I)
    if m:
        return f"{m.group(1).upper()}. {m.group(2).replace('_', ' ').title()}"
    return u
