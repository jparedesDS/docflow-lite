"""Orquestador de devoluciones (versión LITE: sin DB, sin notificaciones).

Detecta la plataforma del email, parsea con el parser correspondiente, construye
el HTML de notificación y lo envía por SMTP. Idempotencia local con un fichero
JSON en `state/processed_emails.json`.
"""

import logging
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd

from core.config import PEDIDOS_BASE_PATH, PROCESSED_EMAILS_FILE
from core.parsers import (
    aconex_parser,
    docspace_parser,
    gaia_parser,
    prodoc_parser,
    sendoc_parser,
    tr_parser,
)
from core.parsers.base_parser import (
    FINAL_COLUMNS,
    build_notification_html,
    compute_recipients,
)
from core.services import imap as imap_service
from core.services import smtp as smtp_service
from core.utils.json_store import read_json, write_json

logger = logging.getLogger(__name__)

PARSERS = [tr_parser, aconex_parser, sendoc_parser, gaia_parser, prodoc_parser, docspace_parser]
PLATFORM_NAMES = {
    "tr_parser": "TÉCNICAS REUNIDAS",
    "aconex_parser": "ACONEX",
    "sendoc_parser": "SENDOC",
    "gaia_parser": "GAIA",
    "prodoc_parser": "PRODOC",
    "docspace_parser": "DOCUMENT SPACE",
}


# ── Idempotencia local ────────────────────────────────────────────────────────

def _load_processed() -> set:
    return set(read_json(PROCESSED_EMAILS_FILE, default=[]))


def _save_processed(uid: str) -> None:
    processed = _load_processed()
    processed.add(uid)
    write_json(PROCESSED_EMAILS_FILE, sorted(processed))


def is_processed(uid: str) -> bool:
    return uid in _load_processed()


# ── Detección de plataforma ───────────────────────────────────────────────────

def _detect_platform(sender: str):
    for parser in PARSERS:
        if parser.can_parse(sender):
            module_name = parser.__name__.rsplit(".", 1)[-1]
            return parser, PLATFORM_NAMES.get(module_name, "UNKNOWN")
    return None, "UNKNOWN"


# ── Listado de correos ────────────────────────────────────────────────────────

def fetch_unread_emails(folder: str = "INBOX") -> list[dict]:
    raw = imap_service.list_unread(folder)
    results = []
    for e in raw:
        parser, platform = _detect_platform(e["from"])
        results.append({**e, "platform": platform, "parseable": parser is not None})
    return results


def fetch_all_emails(folder: str = "INBOX") -> list[dict]:
    """Sólo correos parseables (cualquier plataforma reconocida)."""
    raw = imap_service.list_all(folder)
    processed = _load_processed()
    out = []
    for e in raw:
        parser, platform = _detect_platform(e["from"])
        if parser is None:
            continue
        out.append({
            **e,
            "platform": platform,
            "parseable": True,
            "processed": e["uid"] in processed,
        })
    return out


# ── Preview ───────────────────────────────────────────────────────────────────

def preview_email(uid: str, folder: str = "INBOX") -> dict:
    msg = imap_service.fetch_email(uid, folder)
    sender = msg.get("From", "")
    subject = msg.get("Subject", "")
    date_str = msg.get("Date", "")

    try:
        received_time = parsedate_to_datetime(date_str).strftime("%d-%m-%Y %H:%M:%S")
    except Exception:
        received_time = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

    html_body = imap_service.get_html_body(msg)
    if not html_body:
        raise ValueError("El email no tiene cuerpo HTML legible")

    parser, platform = _detect_platform(sender)
    if not parser:
        raise ValueError(f"Plataforma no reconocida (sender: {sender})")

    kwargs = {}
    if parser is prodoc_parser:
        kwargs["plain_body"] = imap_service.get_plain_body(msg)

    df = parser.parse(html_body, subject, received_time, **kwargs)

    suggested_to, suggested_cc = compute_recipients(df)

    # Limpiar para serialización JSON
    df = df.fillna("")
    for col in df.columns:
        first = df[col].iloc[0] if len(df) > 0 else ""
        if df[col].dtype == "datetime64[ns]" or hasattr(first, "strftime"):
            df[col] = df[col].apply(lambda x: x.strftime("%d-%m-%Y") if hasattr(x, "strftime") else str(x))

    return {
        "platform": platform,
        "subject": subject,
        "from": sender,
        "date": received_time,
        "transmittal_code": parser.extract_transmittal_code(subject),
        "documents": df.to_dict(orient="records"),
        "columns": FINAL_COLUMNS,
        "suggested_to": suggested_to,
        "suggested_cc": suggested_cc,
    }


# ── Guardado opcional en carpeta de pedido ────────────────────────────────────

def _find_devoluciones_folder(pedido: str) -> Path | None:
    """Busca `<PEDIDOS_BASE_PATH>/**/<pedido>/02 DEVOLUCIONES`. Devuelve None si no hay base path o no se encuentra."""
    if not PEDIDOS_BASE_PATH:
        return None
    base = Path(PEDIDOS_BASE_PATH)
    if not base.exists():
        return None

    pedido_norm = pedido.replace("/", "-").replace("\\", "-").upper()
    try:
        for entry in base.rglob(f"*{pedido_norm}*"):
            if entry.is_dir():
                target = entry / "02 DEVOLUCIONES"
                if target.is_dir():
                    return target
    except (OSError, PermissionError) as exc:
        logger.warning("No se pudo recorrer %s: %s", base, exc)
    return None


def _build_eml(subject: str, to: list[str], cc: list[str], html_body: str) -> str:
    headers = [
        f"Subject: {subject}",
        f"To: {'; '.join(to)}",
        f"Cc: {'; '.join(cc)}",
        "Content-Type: text/html; charset=utf-8",
        "MIME-Version: 1.0",
        "",
    ]
    return "\n".join(headers) + html_body


# ── Devolución manual (sin email IMAP de origen) ──────────────────────────────

def _parse_fecha_to_deadline(fecha_str: str | None) -> datetime:
    """Parsea cualquier formato de fecha común y devuelve fecha+15 días."""
    if not fecha_str:
        return datetime.now() + timedelta(days=15)
    s = str(fecha_str).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt) + timedelta(days=15)
        except ValueError:
            continue
    return datetime.now() + timedelta(days=15)


def generate_manual_notification_html(info_dict: dict, docs: list[dict]) -> dict:
    """Genera el HTML de una devolución manual (sin email IMAP de origen).

    Args:
        info_dict: claves Nº Pedido / Cliente / Material / Supp. / PO / Fecha
        docs: lista de dicts con Doc. Cliente, Título, Rev., Estado, Fecha

    Returns:
        {html, subject, documents_count}
    """
    df = pd.DataFrame(docs)
    if df.empty:
        raise ValueError("Debes añadir al menos un documento")

    fecha = info_dict.get("Fecha", "")
    deadline = _parse_fecha_to_deadline(fecha)

    # Asegurar que info_dict tiene los campos canónicos (rellenar vacíos por defecto)
    info = {
        "Nº Pedido": info_dict.get("Nº Pedido", ""),
        "Cliente":   info_dict.get("Cliente", ""),
        "Material":  info_dict.get("Material", ""),
        "Supp.":     info_dict.get("Supp.") or "S00",
        "PO":        info_dict.get("PO", ""),
        "Fecha":     str(fecha)[:10] if fecha else "",
    }

    html = build_notification_html(info, df, deadline)
    subject = f"DEV: {info['Nº Pedido']}" if info["Nº Pedido"] else "DEV: (sin pedido)"
    return {"html": html, "subject": subject, "documents_count": len(df)}


def send_manual_notification(
    info_dict: dict, docs: list[dict],
    to: list[str], cc: list[str] | None = None,
) -> dict:
    """Envía una devolución manual usando la misma plantilla que las automáticas."""
    cc = cc or []
    if not to:
        raise ValueError("Indica al menos un destinatario en 'To'")

    res = generate_manual_notification_html(info_dict, docs)
    html = res["html"]
    subject = res["subject"]

    send_result = smtp_service.send_html_email(to, cc, subject, html)

    # Guardado opcional en carpeta del pedido
    saved_path = None
    save_error = None
    try:
        pedido = str(info_dict.get("Nº Pedido", "") or "").strip()
        if pedido:
            target = _find_devoluciones_folder(pedido)
            if target:
                pedido_norm = pedido.replace("/", "-").replace("\\", "-")
                date_str = datetime.now().strftime("%Y-%m-%d")
                filename = f"{date_str}_{pedido_norm}_DEV_MANUAL.eml"
                (target / filename).write_text(
                    _build_eml(subject, to, cc, html),
                    encoding="utf-8",
                )
                saved_path = str(target / filename)
    except Exception as exc:
        save_error = str(exc)
        logger.warning("Fallo guardando EML manual: %s", exc)

    return {
        "success": True,
        "email_sent": send_result,
        "documents_count": res["documents_count"],
        "subject": subject,
        "saved_path": saved_path,
        "save_error": save_error,
        "manual": True,
    }


# ── Generación de HTML (preview sin enviar) ──────────────────────────────────

def generate_notification_html(
    uid: str,
    folder: str = "INBOX",
    status_overrides: dict | None = None,
) -> dict:
    """Genera el HTML que se enviaría como notificación de devolución, sin enviar.

    Devuelve dict con `html`, `subject`, `documents_count` para mostrar en preview.
    """
    status_overrides = status_overrides or {}
    preview = preview_email(uid, folder)
    df = pd.DataFrame(preview["documents"])

    for idx_str, estado in status_overrides.items():
        try:
            df.at[int(idx_str), "Estado"] = estado
        except (ValueError, KeyError):
            pass

    if df.empty:
        raise ValueError("El parseo no encontró documentos")

    first = df.iloc[0]
    fecha = first.get("Fecha", "")
    if isinstance(fecha, pd.Timestamp):
        deadline = fecha + timedelta(days=15)
    else:
        deadline = datetime.now() + timedelta(days=15)

    info_dict = {
        "Nº Pedido": first.get("Nº Pedido", ""),
        "Cliente": first.get("Cliente", ""),
        "Material": first.get("Material", ""),
        "Supp.": first.get("Supp.", "S00"),
        "PO": first.get("PO", ""),
        "Fecha": str(fecha)[:10] if fecha else "",
    }

    html_body = build_notification_html(info_dict, df, deadline)
    subject = f"DEV: {first.get('Nº Pedido', '')} [{preview['subject']}]"

    return {
        "html": html_body,
        "subject": subject,
        "documents_count": len(df),
    }


# ── Envío ─────────────────────────────────────────────────────────────────────

def process_and_notify(
    uid: str,
    to: list[str],
    cc: list[str],
    folder: str = "INBOX",
    status_overrides: dict | None = None,
) -> dict:
    status_overrides = status_overrides or {}

    preview = preview_email(uid, folder)
    df = pd.DataFrame(preview["documents"])

    for idx_str, estado in status_overrides.items():
        try:
            df.at[int(idx_str), "Estado"] = estado
        except (ValueError, KeyError):
            pass

    if df.empty:
        raise ValueError("El parseo no encontró documentos")

    first = df.iloc[0]
    fecha = first.get("Fecha", "")
    if isinstance(fecha, pd.Timestamp):
        deadline = fecha + timedelta(days=15)
    else:
        deadline = datetime.now() + timedelta(days=15)

    info_dict = {
        "Nº Pedido": first.get("Nº Pedido", ""),
        "Cliente": first.get("Cliente", ""),
        "Material": first.get("Material", ""),
        "Supp.": first.get("Supp.", "S00"),
        "PO": first.get("PO", ""),
        "Fecha": str(fecha)[:10] if fecha else "",
    }

    html_body = build_notification_html(info_dict, df, deadline)
    subject = f"DEV: {first.get('Nº Pedido', '')} [{preview['subject']}]"

    raw_eml = imap_service.fetch_raw(uid, folder)
    safe_name = re.sub(r'[\\/*?:"<>|]', "_", preview["subject"]) + ".eml"

    send_result = smtp_service.send_html_email(
        to, cc, subject, html_body,
        attachment_eml=raw_eml, attachment_name=safe_name,
    )

    imap_service.mark_as_read(uid, folder)
    _save_processed(uid)

    # Guardado opcional en carpeta de red
    saved_path = None
    save_error = None
    try:
        pedido = str(first.get("Nº Pedido", "") or "")
        if pedido:
            target = _find_devoluciones_folder(pedido)
            if target:
                pedido_norm = pedido.replace("/", "-").replace("\\", "-")
                date_str = datetime.now().strftime("%Y-%m-%d")
                filename = f"{date_str}_{pedido_norm}_DEV.eml"
                (target / filename).write_text(
                    _build_eml(subject, to, cc, html_body),
                    encoding="utf-8",
                )
                saved_path = str(target / filename)
    except Exception as exc:
        save_error = str(exc)
        logger.warning("Fallo guardando EML en carpeta de pedido: %s", exc)

    return {
        "success": True,
        "email_sent": send_result,
        "documents_count": len(df),
        "subject": subject,
        "saved_path": saved_path,
        "save_error": save_error,
    }
