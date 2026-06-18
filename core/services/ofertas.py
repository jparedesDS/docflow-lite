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
from core.services import email_trust, imap as imap_service, inbox as inbox_service

logger = logging.getLogger(__name__)

CACHE_TTL = 120  # segundos

_TRUSTED_PREF = "ofertas_trusted_domains"


def get_trusted_domains() -> list[str]:
    from core import preferences
    v = preferences.get(_TRUSTED_PREF) or []
    return [str(d).lower().strip() for d in v if d] if isinstance(v, list) else []


def add_trusted_domain(domain: str) -> None:
    domain = (domain or "").lower().strip()
    if not domain:
        return
    from core import preferences
    cur = get_trusted_domains()
    if domain not in cur:
        cur.append(domain)
        preferences.set_value(_TRUSTED_PREF, cur)
        invalidate_cache()


def remove_trusted_domain(domain: str) -> None:
    domain = (domain or "").lower().strip()
    from core import preferences
    cur = [d for d in get_trusted_domains() if d != domain]
    preferences.set_value(_TRUSTED_PREF, cur)
    invalidate_cache()


# ── Buzones de seguimiento (comerciales) — opt-in, SOLO LECTURA ───────────────
# Permite saber si una oferta se respondió desde el correo de un comercial.
# Lee únicamente la carpeta Enviados, en modo solo-lectura (EXAMINE) y con
# BODY.PEEK (no marca nada como leído). Nunca escribe/mueve/borra. Requiere
# informar y contar con el consentimiento de los comerciales.
_TRACKED_PREF = "ofertas_tracked_mailboxes"   # lista de {label, user} (sin contraseña)


def _track_cred_key(user: str) -> str:
    return f"ofertas_track::{(user or '').lower().strip()}"


def list_tracked_mailboxes() -> list[dict]:
    """Buzones de seguimiento configurados (label + user, sin contraseña)."""
    from core import preferences
    v = preferences.get(_TRACKED_PREF) or []
    return [m for m in v if isinstance(m, dict) and m.get("user")] if isinstance(v, list) else []


def _tracked_with_creds() -> list[dict]:
    from core import credentials
    out = []
    for m in list_tracked_mailboxes():
        pw = credentials.get(_track_cred_key(m["user"]))
        if pw:
            out.append({"label": m.get("label") or m["user"], "user": m["user"], "password": pw})
    return out


def add_tracked_mailbox(label: str, user: str, password: str) -> None:
    from core import preferences, credentials
    user = (user or "").strip()
    if not user or not password:
        return
    cur = [m for m in list_tracked_mailboxes() if m.get("user", "").lower() != user.lower()]
    cur.append({"label": (label or user).strip(), "user": user})
    preferences.set_value(_TRACKED_PREF, cur)
    preferences.flush()
    credentials.set(_track_cred_key(user), password)
    invalidate_cache()


def remove_tracked_mailbox(user: str) -> None:
    from core import preferences, credentials
    user = (user or "").strip()
    cur = [m for m in list_tracked_mailboxes() if m.get("user", "").lower() != user.lower()]
    preferences.set_value(_TRACKED_PREF, cur)
    preferences.flush()
    credentials.delete(_track_cred_key(user))
    invalidate_cache()

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


_SUBJ_PREFIX_RE = re.compile(r"^\s*(re|fwd|fw|rv|aw)\s*:\s*", re.IGNORECASE)


def _norm_subj(s: str) -> str:
    s = (s or "").lower().strip()
    while True:
        m = _SUBJ_PREFIX_RE.match(s)
        if not m:
            break
        s = s[m.end():]
    return s.strip()


def _build_reply_index(sent_idx: list[dict]) -> tuple[dict, dict]:
    """Índices de respuestas: por Message-ID respondido y (destinatario, asunto)."""
    by_msgid, by_recip_subj = {}, {}
    for s in sent_idx:
        for mid in s.get("refs", ()):
            by_msgid.setdefault(mid, s)
        nsubj = _norm_subj(s.get("subject", ""))
        for rcpt in s.get("to", ()):
            by_recip_subj.setdefault((rcpt, nsubj), s)
    return by_msgid, by_recip_subj


# ── API pública ───────────────────────────────────────────────────────────────

_inbox_cache: dict[int, tuple[float, list]] = {}


def _scan_inboxes(days: int) -> tuple[list, list]:
    """FASE 1 (rápida): solo las bandejas de entrada → ofertas + flag \\Answered."""
    from concurrent.futures import ThreadPoolExecutor
    trusted = get_trusted_domains()
    accounts = [a for a in OFERTAS_ACCOUNTS if a.get("password")]
    errors: list[str] = []

    def scan(acc):
        try:
            return (acc, imap_service.list_since(days, "INBOX", acc["user"], acc["password"]))
        except Exception as exc:
            return (acc, exc)

    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, len(accounts))) as ex:
        for acc, payload in ex.map(scan, accounts):
            if isinstance(payload, Exception):
                errors.append(f"{acc['label']}: {payload}")
                continue
            for m in payload:
                portal, tipo = detect_portal(m.get("from", ""), m.get("subject", ""))
                trust = email_trust.analyze(m, trusted_domains=trusted)
                from_email = _email_of(m.get("from", ""))
                mid = (m.get("message_id") or "").strip()
                out.append({
                    **m, "account": acc["label"], "account_user": acc["user"],
                    "from_email": from_email, "portal": portal, "tipo": tipo,
                    "trust": trust, "trust_level": trust["level"],
                    "is_answered": bool(m.get("is_answered")),
                    "answered_at": "", "answered_from": "", "answered_via": "",
                    "answered_user": "", "answered_folder": "", "answered_msgid": "",
                    "meta_key": mid or f"{acc['user']}::{m.get('uid')}",
                })
    out.sort(key=lambda x: _parse_dt(x.get("date", "")), reverse=True)
    return out, errors


def _global_reply_index(days: int) -> tuple[dict, dict]:
    """Índice global de respuestas (buzones compartidos + comerciales). Es lo caro."""
    from concurrent.futures import ThreadPoolExecutor
    accounts = [a for a in OFERTAS_ACCOUNTS if a.get("password")]
    shared_labels = {a["label"] for a in accounts}
    targets = [(a["label"], a["user"], a["password"]) for a in accounts]
    targets += [(t["label"], t["user"], t["password"]) for t in _tracked_with_creds()]

    def scan(t):
        label, user, pw = t
        try:
            return (label, user, _get_sent_index(user, pw, days))
        except Exception:
            return (label, user, [])

    g_msgid, g_recip = {}, {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        for label, user, payload in ex.map(scan, targets):
            via = "compartido" if label in shared_labels else "comercial"
            bm, brs = _build_reply_index(payload)
            for k, v in bm.items():
                g_msgid.setdefault(k, {**v, "_owner": label, "_user": user, "_via": via})
            for k, v in brs.items():
                g_recip.setdefault(k, {**v, "_owner": label, "_user": user, "_via": via})
    return g_msgid, g_recip


def _apply_replies(offers: list[dict], g_msgid: dict, g_recip: dict) -> list[dict]:
    for o in offers:
        mid = (o.get("message_id") or "").strip()
        nsubj = _norm_subj(o.get("subject", ""))
        reply = (g_msgid.get(mid) if mid else None) or g_recip.get((o.get("from_email", ""), nsubj))
        if reply:
            o["is_answered"] = True
            o["answered_at"] = reply.get("date", "")
            o["answered_from"] = reply.get("_owner") or reply.get("from", "")
            o["answered_via"] = reply.get("_via", "")
            o["answered_user"] = reply.get("_user", "")
            o["answered_folder"] = reply.get("folder", "")
            o["answered_msgid"] = reply.get("own_msgid", "")
    return offers


def fetch_inbox_offers(days: int = 30, force: bool = False) -> list[dict]:
    """FASE 1: ofertas de las bandejas (rápido). El estado de respuesta inicial
    es solo el de la flag \\Answered; enrich_replies() completa el resto."""
    global last_errors
    now = time.time()
    hit = _inbox_cache.get(days)
    if hit and not force and (now - hit[0]) < CACHE_TTL:
        last_errors = []
        return [dict(o) for o in hit[1]]
    out, errors = _scan_inboxes(days)
    last_errors = errors
    _inbox_cache[days] = (now, [dict(o) for o in out])
    return out


def enrich_replies(offers: list[dict], days: int = 30) -> list[dict]:
    """FASE 2: marca quién/cuándo respondió (escaneo de Enviados, lento)."""
    g_msgid, g_recip = _global_reply_index(days)
    return _apply_replies(offers, g_msgid, g_recip)


def fetch_ofertas(days: int = 30, force: bool = False) -> list[dict]:
    """Carga completa (ofertas + respuestas) en una sola llamada. Cacheada.
    Para export y uso programático; la UI usa las dos fases por separado."""
    now = time.time()
    hit = _cache.get(days)
    if hit and not force and (now - hit[0]) < CACHE_TTL:
        return hit[1]
    out = fetch_inbox_offers(days, force=force)
    out = enrich_replies(out, days)
    _cache[days] = (now, out)
    return out


_SENT_TTL = 600  # s — el índice de Enviados (escaneo caro de carpetas) se cachea 10 min
_sent_cache: dict[str, tuple[float, list]] = {}


def _get_sent_index(user: str, pw: str, days: int) -> list:
    """Índice de Enviados con caché propia (el escaneo de carpetas es lo caro)."""
    now = time.time()
    hit = _sent_cache.get(user)
    if hit and (now - hit[0]) < _SENT_TTL:
        return hit[1]
    sidx = imap_service.list_sent_index(days, user, pw)
    _sent_cache[user] = (now, sidx)
    return sidx


def invalidate_cache() -> None:
    _cache.clear()
    _sent_cache.clear()
    _inbox_cache.clear()


def kpis(ofertas: list[dict]) -> dict:
    total = len(ofertas)
    sin_leer = sum(1 for o in ofertas if not o.get("is_read"))
    sin_responder = sum(1 for o in ofertas if not o.get("is_answered"))
    respondidas = total - sin_responder
    # "Leídas pero sin responder": fuerte indicio de que se contestó desde otro
    # correo (personal) o de que está pendiente.
    leidas_sin_responder = sum(1 for o in ofertas
                               if o.get("is_read") and not o.get("is_answered"))
    por_buzon = Counter(o["account"] for o in ofertas)
    por_portal = Counter(o["portal"] for o in ofertas)
    por_tipo = Counter(o["tipo"] for o in ofertas)
    por_trust = Counter(o.get("trust_level", "precaucion") for o in ofertas)
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
        "verificados": por_trust.get("verificado", 0),
        "precaucion": por_trust.get("precaucion", 0),
        "sospechosos": por_trust.get("sospechoso", 0),
        "sin_responder": sin_responder,
        "respondidas": respondidas,
        "leidas_sin_responder": leidas_sin_responder,
    }


def funnel(ofertas: list[dict]) -> dict:
    """Métricas de embudo + respuesta. Lee el estado de gestión de cada oferta."""
    from core.services import ofertas_meta as meta
    from datetime import datetime

    por_estado = Counter()
    por_comercial = Counter()
    importe_pipeline = 0.0
    tiempos = []  # horas hasta la 1ª respuesta
    ganadas = perdidas = vencen = 0
    for o in ofertas:
        m = meta.get(o.get("meta_key", ""))
        estado = m.get("estado") or "Nueva"
        por_estado[estado] += 1
        if estado not in meta.CERRADOS:
            dd = _deadline_days(m.get("deadline"))
            if dd is not None and dd <= 7:
                vencen += 1
        asign = m.get("asignado") or "Sin asignar"
        por_comercial[asign] += 1
        if estado == "Ganada":
            ganadas += 1
        elif estado == "Perdida":
            perdidas += 1
        if estado not in meta.CERRADOS:
            importe_pipeline += _money(m.get("importe"))
        # Tiempo de respuesta (entrada → respuesta desde Enviados)
        if o.get("answered_at") and o.get("date"):
            try:
                h = (datetime.fromisoformat(o["answered_at"])
                     - datetime.fromisoformat(o["date"])).total_seconds() / 3600
                if h >= 0:
                    tiempos.append(h)
            except Exception:
                pass
    total = len(ofertas)
    respondidas = sum(1 for o in ofertas if o.get("is_answered"))
    avg_h = round(sum(tiempos) / len(tiempos), 1) if tiempos else None
    decididas = ganadas + perdidas
    return {
        "total": total,
        "por_estado": dict(por_estado),
        "por_comercial": por_comercial.most_common(),
        "importe_pipeline": importe_pipeline,
        "tasa_respuesta": round(100 * respondidas / total) if total else 0,
        "tiempo_medio_h": avg_h,
        "ganadas": ganadas,
        "perdidas": perdidas,
        "tasa_exito": round(100 * ganadas / decididas) if decididas else None,
        "vencen": vencen,
    }


def _deadline_days(s):
    from datetime import date, datetime
    s = (str(s) or "").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return (datetime.strptime(s, fmt).date() - date.today()).days
        except ValueError:
            continue
    return None


def _money(v) -> float:
    if not v:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(v)).replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def export_excel(ofertas: list[dict], path: str) -> str:
    """Exporta las ofertas + gestión a un Excel. Devuelve la ruta."""
    from openpyxl import Workbook
    from core.services import ofertas_meta as meta

    wb = Workbook()
    ws = wb.active
    ws.title = "Ofertas"
    headers = ["Entrada", "Buzón", "Remitente", "Asunto", "Portal/Origen",
               "Respondida", "Respondida por", "Fecha respuesta",
               "Resultado", "Asignado", "Cliente", "Notas"]
    ws.append(headers)
    for o in ofertas:
        m = meta.get(o.get("meta_key", ""))
        ws.append([
            str(o.get("date", ""))[:10], o.get("account", ""), o.get("from_email", ""),
            o.get("subject", ""), o.get("portal", ""),
            "Sí" if o.get("is_answered") else "No", o.get("answered_from", ""),
            str(o.get("answered_at", ""))[:10],
            m.get("estado", "Nueva"), m.get("asignado", ""), m.get("cliente", ""),
            m.get("notas", ""),
        ])
    for col in ws.columns:
        w = max((len(str(c.value)) for c in col if c.value), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max(w + 2, 10), 50)
    wb.save(path)
    return path


def portal_options() -> list[str]:
    """Lista de portales presentes (para el filtro). Requiere cache poblada."""
    last = max(_cache.values(), key=lambda v: v[0], default=None)
    if not last:
        return []
    return sorted({o["portal"] for o in last[1]})


def _password_for(user: str) -> str:
    """Contraseña de un buzón (compartido o comercial de seguimiento)."""
    user = (user or "").lower().strip()
    for a in OFERTAS_ACCOUNTS:
        if a.get("user", "").lower() == user and a.get("password"):
            return a["password"]
    from core import credentials
    return credentials.get(_track_cred_key(user))


def get_reply_body(user: str, folder: str, msgid: str) -> str:
    """Cuerpo (texto) de la respuesta enviada — descarga bajo demanda, solo-lectura."""
    pw = _password_for(user)
    if not (user and pw and msgid):
        return ""
    msg = imap_service.fetch_by_msgid(folder or "INBOX", msgid, user, pw)
    if msg is None:
        return ""
    html = imap_service.get_html_body(msg) or ""
    plain = imap_service.get_plain_body(msg) or ""
    body = inbox_service.html_to_text(html) if html else plain
    return (body or "").strip()


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

    # Análisis de confianza + enlaces sospechosos (texto-visible ≠ destino real)
    trust = email_trust.analyze({
        "from": _dec(msg.get("From", "")),
        "auth_results": "; ".join(msg.get_all("Authentication-Results", []) or []),
        "reply_to": _dec(msg.get("Reply-To", "")),
    }, trusted_domains=get_trusted_domains())
    links = _suspicious_links(html)
    if links:
        trust = dict(trust)
        trust["reasons"] = list(trust["reasons"]) + [
            f"{len(links)} enlace(s) cuyo texto no coincide con el destino real."]

    return {
        "uid": uid,
        "subject": _dec(msg.get("Subject", "")),
        "from": _dec(msg.get("From", "")),
        "to": _dec(msg.get("To", "")),
        "date": date_iso,
        "body": body.strip() or "(Sin cuerpo de texto)",
        "trust": trust,
        "links": links,
    }


_HREF_RE = re.compile(r'<a\s[^>]*href=["\']?(https?://[^"\'>\s]+)["\']?[^>]*>(.*?)</a>',
                      re.IGNORECASE | re.DOTALL)
_URL_IN_TEXT_RE = re.compile(r'https?://([^/\s"\'<>]+)', re.IGNORECASE)


def _suspicious_links(html: str) -> list[dict]:
    """Enlaces cuyo TEXTO visible muestra un dominio distinto al destino real
    del href (truco clásico de phishing). Devuelve hasta 5."""
    if not html:
        return []
    out = []
    for href, text in _HREF_RE.findall(html):
        href_dom = _domain_of(_email_of(href) or "") or _url_domain(href)
        m = _URL_IN_TEXT_RE.search(text or "")
        if not m:
            continue
        text_dom = m.group(1).lower()
        if text_dom and href_dom and text_dom not in href_dom and href_dom not in text_dom:
            out.append({"text_domain": text_dom, "real_domain": href_dom})
            if len(out) >= 5:
                break
    return out


def _url_domain(url: str) -> str:
    m = _URL_IN_TEXT_RE.search(url or "")
    return m.group(1).lower() if m else ""


def mark_read(account_label: str, uid: str) -> None:
    creds = _creds(account_label)
    if not creds:
        return
    user, password = creds
    try:
        imap_service.mark_as_read(uid, "INBOX", user, password)
    except Exception as exc:
        logger.warning("Ofertas: no se pudo marcar leído %s: %s", uid, exc)
