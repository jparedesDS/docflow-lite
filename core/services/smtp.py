import imaplib
import logging
import re
import smtplib
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, getaddresses, make_msgid

from core.config import (
    IMAP_HOST, IMAP_PASS, IMAP_PORT, IMAP_USER,
    SMTP_HOST, SMTP_PASS, SMTP_PORT, SMTP_USER,
)

logger = logging.getLogger(__name__)


# Candidatos comunes de carpeta "Sent" (variantes por proveedor/idioma).
# Probamos en orden hasta encontrar una que exista en el buzón.
# Sin comillas — imaplib se encarga del quoting si el nombre tiene espacios.
_SENT_FOLDER_CANDIDATES = (
    "Sent Items",
    "Sent",
    "INBOX.Sent",
    "INBOX.Sent Items",
    "INBOX/Sent",
    "INBOX/Sent Items",
    "Enviados",
    "INBOX.Enviados",
    "Elementos enviados",
    "[Gmail]/Sent Mail",
    "[Gmail]/Enviados",
)


# Match del nombre del mailbox al final de una línea LIST.
# Formato típico: '(\\Marked \\HasNoChildren \\Sent) "/" "Sent Items"'
# Capturamos el string final entre comillas dobles.
_MAILBOX_NAME_RE = re.compile(r'"([^"]+)"\s*$')


def _quote_mailbox(name: str) -> str:
    """Envuelve el nombre en comillas si tiene espacios/caracteres especiales.

    imaplib mayormente acepta sin quote, pero algunos servers exigen comillas
    para nombres con espacios. Esta función las añade de forma segura.
    """
    if not name:
        return name
    if name.startswith('"') and name.endswith('"'):
        return name
    if " " in name or "/" in name:
        return f'"{name}"'
    return name


def _detect_sent_folder(imap: imaplib.IMAP4_SSL) -> str | None:
    """Detecta el nombre real de la carpeta Sent en el buzón.

    Estrategia:
      1. Si la carpeta tiene el flag SPECIAL-USE \\Sent (RFC 6154), úsala.
      2. Si no, probar candidatos comunes con SELECT.

    Devuelve el nombre del mailbox (sin comillas).
    """
    # 1) SPECIAL-USE \Sent
    try:
        status, folders = imap.list()
        if status == "OK" and folders:
            for f in folders:
                line = f.decode("utf-8", errors="replace") if isinstance(f, bytes) else str(f)
                if "\\Sent" not in line:
                    continue
                m = _MAILBOX_NAME_RE.search(line)
                if m:
                    name = m.group(1)
                    logger.info("Sent folder via SPECIAL-USE \\Sent: %r", name)
                    return name
    except Exception as exc:
        logger.warning("LIST falló al detectar SPECIAL-USE \\Sent: %s", exc)

    # 2) Probar candidatos por SELECT
    for cand in _SENT_FOLDER_CANDIDATES:
        try:
            status, _ = imap.select(_quote_mailbox(cand), readonly=True)
            if status == "OK":
                logger.info("Sent folder probado OK: %r", cand)
                return cand
        except Exception:
            continue
    return None


def _append_to_sent(raw_message: bytes) -> dict:
    """Guarda una copia del mensaje en la carpeta Sent del buzón vía IMAP APPEND.

    Es best-effort: si falla, devuelve {ok: False, error: ...} sin romper el
    envío SMTP que ya tuvo éxito.
    """
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
            imap.login(IMAP_USER, IMAP_PASS)
            sent = _detect_sent_folder(imap)
            if not sent:
                return {"ok": False, "error": "Sent folder no detectada"}

            # APPEND requiere el mensaje crudo + flag \Seen para que aparezca leído
            now = imaplib.Time2Internaldate(time.time())
            status, resp = imap.append(
                _quote_mailbox(sent), "(\\Seen)", now, raw_message,
            )
            if status != "OK":
                return {"ok": False, "error": f"APPEND retornó {status}: {resp}"}
            logger.info("Copia guardada en %r (%d bytes)", sent, len(raw_message))
            return {"ok": True, "folder": sent, "bytes": len(raw_message)}
    except Exception as exc:
        logger.exception("Error guardando en Sent: %s", exc)
        return {"ok": False, "error": str(exc)}


def parse_recipients(value) -> list[tuple[str, str]]:
    """Normaliza destinatarios a [(nombre, email), …] sin duplicados.

    Acepta string o lista. Tolera el formato de pegado de Outlook/Webmail:
      · Separadores `,`  `;`  y saltos de línea.
      · Formato `'Nombre Apellido' <email>` o `Nombre <email>` o email pelado.
      · Nombres con tildes / no-ASCII (p.ej. «杨振华»).
    Las entradas sin `@` válido se descartan.
    """
    if value is None:
        return []
    items = [value] if isinstance(value, str) else list(value)
    joined = ", ".join(str(i) for i in items if i is not None and str(i).strip())
    # getaddresses parsea listas separadas por coma → normalizamos ; y saltos.
    joined = joined.replace(";", ",").replace("\n", ",").replace("\r", ",")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, addr in getaddresses([joined]):
        # Outlook envuelve nombres y a veces emails pelados en comillas SIMPLES
        # ('...'), que no son comillas RFC → getaddresses las deja pegadas a la
        # dirección. Las quitamos (solo las envolventes; respeta O'Brien).
        name = _strip_squotes(name)
        addr = _strip_squotes(addr)
        if not addr or "@" not in addr or " " in addr:
            continue
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((name, addr))
    return out


def _strip_squotes(s: str) -> str:
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        s = s[1:-1].strip()
    return s


def _format_header(pairs: list[tuple[str, str]]) -> str:
    """Cabecera RFC-5322: `Nombre <email>` con el nombre codificado (RFC 2047)
    si lleva no-ASCII. formataddr usa charset utf-8 por defecto."""
    return ", ".join(formataddr((n, a)) if n else a for n, a in pairs)


def clean_addresses(value) -> list[str]:
    """Lista legible `Nombre <email>` (o email pelado), deduplicada — para que
    la vista muestre/guarde destinatarios limpios."""
    return [f"{n} <{a}>" if n else a for n, a in parse_recipients(value)]


def send_html_email(
    to: list[str],
    cc: list[str],
    subject: str,
    html_body: str,
    attachment_eml: bytes = None,
    attachment_name: str = "original.eml",
    save_to_sent: bool = True,
):
    """Envía un email HTML por SMTP_SSL y guarda copia en Sent (IMAP APPEND).

    save_to_sent=False permite desactivar el APPEND (p.ej. para tests).
    """
    to_pairs = parse_recipients(to)
    cc_pairs = parse_recipients(cc)

    msg = MIMEMultipart("mixed")
    msg["From"] = SMTP_USER
    msg["To"] = _format_header(to_pairs)
    msg["Cc"] = _format_header(cc_pairs)
    msg["Subject"] = subject
    # Headers de fecha + ID: imprescindibles para que Outlook muestre
    # "Enviado: <fecha>" en la copia archivada en Sent Items vía IMAP APPEND.
    # SMTP_SSL no añade Date automáticamente para mensajes ya formados.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=SMTP_USER.split("@")[-1] if "@" in SMTP_USER else "localhost")
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if attachment_eml:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment_eml)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=attachment_name)
        msg.attach(part)

    raw = msg.as_bytes()
    # Envelope: SOLO las direcciones peladas (sin nombre) para el RCPT TO.
    all_recipients = [a for _, a in to_pairs] + [a for _, a in cc_pairs]

    # 1) Envío SMTP
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, all_recipients, raw)

    # raw también se devuelve para que el caller pueda archivarlo en disco
    # (p.ej. claims guarda copia .eml en la carpeta del pedido).
    result = {"success": True, "recipients": all_recipients, "raw": raw}

    # 2) Copia en Sent (best-effort, no rompe el envío si falla)
    if save_to_sent:
        sent_result = _append_to_sent(raw)
        result["sent_folder"] = sent_result
        if sent_result.get("ok"):
            logger.info("Email enviado y archivado en %s", sent_result.get("folder"))
        else:
            logger.warning("Email enviado pero NO archivado: %s", sent_result.get("error"))

    return result
