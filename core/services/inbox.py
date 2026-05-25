"""Servicio Inbox — lectura de correos IMAP con flag is_read y detalle completo.

Port simplificado de inbox_service del DocFlow grande. Sin IA — la clasificación
se añadirá cuando ANTHROPIC_API_KEY esté configurada.
"""

import email as email_lib
import imaplib
import logging
from email.header import decode_header
from email.utils import parsedate_to_datetime

from core.config import IMAP_HOST, IMAP_PASS, IMAP_PORT, IMAP_USER
from core.services import imap as imap_service

logger = logging.getLogger(__name__)


def _decode_header_value(value) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for data, charset in parts:
        if isinstance(data, bytes):
            result.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(data)
    return "".join(result)


def _connect(folder: str = "INBOX") -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    conn.login(IMAP_USER, IMAP_PASS)
    conn.select(folder)
    return conn


def list_emails(folder: str = "INBOX", filter: str = "all", limit: int = 200) -> list[dict]:
    """Lista correos con flag is_read.

    filter: 'all' | 'unread' | 'read'
    """
    conn = _connect(folder)
    try:
        criterion = {
            "unread": "UNSEEN",
            "read":   "SEEN",
        }.get(filter, "ALL")
        _, data = conn.search(None, criterion)
        uids = data[0].split() if data and data[0] else []
        # Más recientes primero, recortado al límite
        uids = list(reversed(uids))[:limit]

        results = []
        for uid in uids:
            _, msg_data = conn.fetch(uid, "(BODY.PEEK[HEADER] FLAGS)")
            if not msg_data or not msg_data[0]:
                continue
            raw_header = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw_header)

            # Flags
            flags_str = ""
            for item in msg_data:
                if isinstance(item, bytes):
                    flags_str += " " + item.decode(errors="replace")
                elif isinstance(item, tuple) and len(item) > 0:
                    s = item[0].decode(errors="replace") if isinstance(item[0], bytes) else str(item[0])
                    flags_str += " " + s
            is_read = "\\Seen" in flags_str

            subject = _decode_header_value(msg.get("Subject", ""))
            sender = _decode_header_value(msg.get("From", ""))
            date_str = msg.get("Date", "")
            try:
                date_iso = parsedate_to_datetime(date_str).isoformat()
            except Exception:
                date_iso = date_str

            results.append({
                "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                "subject": subject,
                "from": sender,
                "date": date_iso,
                "is_read": is_read,
            })
        return results
    finally:
        try:
            conn.close()
        except Exception:
            pass
        conn.logout()


def get_email_detail(uid: str, folder: str = "INBOX") -> dict:
    """Detalle completo del email: cabeceras + cuerpos HTML/plain."""
    msg = imap_service.fetch_email(uid, folder)

    subject = _decode_header_value(msg.get("Subject", ""))
    sender = _decode_header_value(msg.get("From", ""))
    to = _decode_header_value(msg.get("To", ""))
    cc = _decode_header_value(msg.get("Cc", ""))
    date_str = msg.get("Date", "")
    try:
        date_iso = parsedate_to_datetime(date_str).isoformat()
    except Exception:
        date_iso = date_str

    html_body = imap_service.get_html_body(msg) or ""
    plain_body = imap_service.get_plain_body(msg) or ""

    return {
        "uid": uid,
        "subject": subject,
        "from": sender,
        "to": to,
        "cc": cc,
        "date": date_iso,
        "html_body": html_body,
        "plain_body": plain_body,
    }


def mark_read(uid: str, folder: str = "INBOX") -> None:
    imap_service.mark_as_read(uid, folder)


def mark_unread(uid: str, folder: str = "INBOX") -> None:
    """Quita el flag \\Seen del email."""
    conn = _connect(folder)
    try:
        target = uid.encode() if isinstance(uid, str) else uid
        conn.store(target, "-FLAGS", "\\Seen")
    finally:
        try:
            conn.close()
        except Exception:
            pass
        conn.logout()


# ── Extracción de texto plano legible ─────────────────────────────────────────

def html_to_text(html: str) -> str:
    """Convierte HTML a texto plano legible (mantiene saltos de párrafo)."""
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        # Eliminar style/script
        for tag in soup(["style", "script"]):
            tag.decompose()
        # Mejor representación de saltos
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for block in soup.find_all(["p", "div", "tr", "h1", "h2", "h3", "h4", "li"]):
            block.append("\n")
        text = soup.get_text(separator=" ")
        # Limpiar espacios y saltos múltiples
        lines = [ln.strip() for ln in text.splitlines()]
        out = []
        prev_blank = False
        for ln in lines:
            if not ln:
                if not prev_blank and out:
                    out.append("")
                prev_blank = True
            else:
                out.append(ln)
                prev_blank = False
        return "\n".join(out).strip()
    except Exception as exc:
        logger.warning("html_to_text fallback: %s", exc)
        # Fallback simple
        import re
        t = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", t).strip()
