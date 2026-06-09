"""Ofertas — unifica los 3 buzones comerciales y clasifica el origen/portal.

Junta las bandejas de entrada de comercial@ / dptocomercial@ / info@ (mismas
credenciales IMAP host:port que el resto, contraseñas en .env) y, por cada
correo entrante, detecta el **portal de origen** (SAP Ariba, Coupa, Aconex…) o,
si llega como email directo, el dominio del remitente. Así se tiene control de
qué ofertas/RFQs van entrando y por dónde.

Lecturas IMAP cacheadas (TTL corto) y pensadas para correr en hilo desde la UI.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from datetime import datetime

from core.config import OFERTAS_ACCOUNTS
from core.services import imap as imap_service, inbox as inbox_service

logger = logging.getLogger(__name__)

CACHE_TTL = 120  # segundos

# ── Detección de portal ───────────────────────────────────────────────────────
# (patrón sobre remitente+asunto, nombre del portal). Ampliable fácilmente.
PORTAL_PATTERNS: list[tuple[str, str]] = [
    (r"ariba\.com|ansmtp\.ariba|ans\.ariba", "SAP Ariba"),
    (r"jaggaer|sciquest|sci\.quest", "Jaggaer"),
    (r"coupahost|coupa\.com", "Coupa"),
    (r"aconex", "Aconex"),
    (r"gep\.com|gepsmart|smart\.gep", "GEP SMART"),
    (r"ivalua", "Ivalua"),
    (r"tradeshift", "Tradeshift"),
    (r"synertrade", "SynerTrade"),
    (r"proactis", "Proactis"),
    (r"achilles", "Achilles"),
    (r"tungsten|ob10", "Tungsten / OB10"),
    (r"tejari", "Tejari"),
    (r"quadrem", "Quadrem"),
    (r"vortal", "Vortal"),
    (r"negometrix", "Negometrix"),
    (r"sap\b|srm", "SAP SRM"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), name) for p, name in PORTAL_PATTERNS]

_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w.\-]+")

# Estado de errores de la última lectura (lo consume la vista)
last_errors: list[str] = []

_cache: dict[int, tuple[float, list[dict]]] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def available() -> bool:
    return any(a.get("password") for a in OFERTAS_ACCOUNTS)


def _email_of(from_header: str) -> str:
    m = _EMAIL_RE.search(from_header or "")
    return m.group(0).lower() if m else ""


def _domain_of(addr: str) -> str:
    return addr.split("@", 1)[1].lower() if "@" in addr else ""


def detect_portal(from_header: str, subject: str) -> tuple[str, str]:
    """Devuelve (nombre_portal_u_origen, tipo) donde tipo ∈ {'Portal','Directo'}."""
    email_addr = _email_of(from_header)
    haystack = f"{email_addr} {subject or ''}"
    for rx, name in _COMPILED:
        if rx.search(haystack):
            return name, "Portal"
    domain = _domain_of(email_addr)
    return (domain or "Desconocido"), "Directo"


def _creds(label: str) -> tuple[str, str] | None:
    for a in OFERTAS_ACCOUNTS:
        if a["label"] == label:
            return a["user"], a["password"]
    return None


def _parse_dt(iso: str):
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        return datetime.min


# ── API pública ───────────────────────────────────────────────────────────────

def fetch_ofertas(days: int = 30, force: bool = False) -> list[dict]:
    """Correos recientes de los 3 buzones, clasificados por portal. Cacheado."""
    now = time.time()
    hit = _cache.get(days)
    if hit and not force and (now - hit[0]) < CACHE_TTL:
        return hit[1]

    global last_errors
    last_errors = []
    out: list[dict] = []
    for acc in OFERTAS_ACCOUNTS:
        if not acc.get("password"):
            continue
        try:
            msgs = imap_service.list_since(days, "INBOX", acc["user"], acc["password"])
        except Exception as exc:
            logger.warning("Ofertas: fallo IMAP %s: %s", acc["user"], exc)
            last_errors.append(f"{acc['label']}: {exc}")
            continue
        for m in msgs:
            portal, tipo = detect_portal(m.get("from", ""), m.get("subject", ""))
            out.append({
                **m,
                "account": acc["label"],
                "account_user": acc["user"],
                "from_email": _email_of(m.get("from", "")),
                "portal": portal,
                "tipo": tipo,
            })

    out.sort(key=lambda x: _parse_dt(x.get("date", "")), reverse=True)
    _cache[days] = (now, out)
    return out


def invalidate_cache() -> None:
    _cache.clear()


def kpis(ofertas: list[dict]) -> dict:
    total = len(ofertas)
    sin_leer = sum(1 for o in ofertas if not o.get("is_read"))
    por_buzon = Counter(o["account"] for o in ofertas)
    por_portal = Counter(o["portal"] for o in ofertas)
    por_tipo = Counter(o["tipo"] for o in ofertas)
    portales = sorted(por_portal.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "total": total,
        "sin_leer": sin_leer,
        "buzones": len([a for a in OFERTAS_ACCOUNTS if a.get("password")]),
        "n_portales": len(por_portal),
        "por_buzon": dict(por_buzon),
        "por_portal": portales,
        "directos": por_tipo.get("Directo", 0),
        "via_portal": por_tipo.get("Portal", 0),
    }


def portal_options() -> list[str]:
    """Lista de portales presentes (para el filtro). Requiere cache poblada."""
    last = max(_cache.values(), key=lambda v: v[0], default=None)
    if not last:
        return []
    return sorted({o["portal"] for o in last[1]})


def get_detail(account_label: str, uid: str) -> dict:
    """Detalle de un correo: cabeceras + cuerpo en texto legible."""
    creds = _creds(account_label)
    if not creds:
        raise RuntimeError(f"Cuenta desconocida: {account_label}")
    user, password = creds
    msg = imap_service.fetch_email(uid, "INBOX", user, password)

    from email.header import decode_header

    def _dec(v):
        if not v:
            return ""
        return "".join(
            (d.decode(c or "utf-8", errors="replace") if isinstance(d, bytes) else d)
            for d, c in decode_header(v))

    html = imap_service.get_html_body(msg) or ""
    plain = imap_service.get_plain_body(msg) or ""
    body = inbox_service.html_to_text(html) if html else plain
    from email.utils import parsedate_to_datetime
    date_str = msg.get("Date", "")
    try:
        date_iso = parsedate_to_datetime(date_str).isoformat()
    except Exception:
        date_iso = date_str
    return {
        "uid": uid,
        "subject": _dec(msg.get("Subject", "")),
        "from": _dec(msg.get("From", "")),
        "to": _dec(msg.get("To", "")),
        "date": date_iso,
        "body": body.strip() or "(Sin cuerpo de texto)",
    }


def mark_read(account_label: str, uid: str) -> None:
    creds = _creds(account_label)
    if not creds:
        return
    user, password = creds
    try:
        imap_service.mark_as_read(uid, "INBOX", user, password)
    except Exception as exc:
        logger.warning("Ofertas: no se pudo marcar leído %s: %s", uid, exc)
