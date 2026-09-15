"""Orquestador de devoluciones (versión LITE: sin DB, sin notificaciones).

Detecta la plataforma del email, parsea con el parser correspondiente, construye
el HTML de notificación y lo envía por SMTP. Idempotencia local con un fichero
JSON en `state/processed_emails.json`, indexado por Message-ID (ver `email_key`).
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
    ayesa_parser,
    docspace_parser,
    gaia_parser,
    prodoc_parser,
    sacyr_parser,
    sendoc_parser,
    tr_parser,
)
from core.parsers.base_parser import (
    FINAL_COLUMNS,
    build_notification_html,
    compute_recipients,
    enrich_missing_from_erp,
)
from core.services import imap as imap_service
from core.services import smtp as smtp_service
from core.utils import files
from core.utils.json_store import read_json, write_json

logger = logging.getLogger(__name__)

PARSERS = [tr_parser, aconex_parser, sendoc_parser, gaia_parser, prodoc_parser,
           docspace_parser, ayesa_parser, sacyr_parser]
PLATFORM_NAMES = {
    "tr_parser": "TÉCNICAS REUNIDAS",
    "aconex_parser": "ACONEX",
    "sendoc_parser": "SENDOC",
    "gaia_parser": "GAIA",
    "prodoc_parser": "PRODOC",
    "docspace_parser": "DOCUMENT SPACE",
    "ayesa_parser": "AYESA",
    "sacyr_parser": "SACYR",
}


# ── Idempotencia local ────────────────────────────────────────────────────────

def _load_processed() -> set:
    return set(read_json(PROCESSED_EMAILS_FILE, default=[]))


def _save_processed(key: str) -> None:
    processed = _load_processed()
    processed.add(key)
    write_json(PROCESSED_EMAILS_FILE, sorted(processed))


def email_key(e: dict) -> str:
    """Identificador con el que se recuerda un correo ya notificado.

    El Message-ID, que no cambia nunca. NO vale el `uid`: es el nº de secuencia
    del mensaje dentro de la carpeta (IMAP SEARCH devuelve secuencia, no UID), y
    se renumera al borrar cualquier correo anterior — el mismo «uid 41» era un
    correo distinto la semana pasada. Los números sueltos que quedan en
    `processed_emails.json` son de esa época y ya no casan con nada, que es
    justo lo que se busca.
    """
    return str(e.get("message_id") or "").strip() or str(e.get("uid", ""))


def _message_id_from_raw(raw: bytes) -> str:
    """Message-ID de los bytes MIME del correo ('' si no trae)."""
    try:
        from email import message_from_bytes
        return (message_from_bytes(raw).get("Message-ID") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def is_processed(key: str) -> bool:
    """`key` es el de `email_key()`, no el uid."""
    return key in _load_processed()


# ── Detección de plataforma ───────────────────────────────────────────────────

def _detect_platform(sender: str):
    for parser in PARSERS:
        if parser.can_parse(sender):
            module_name = parser.__name__.rsplit(".", 1)[-1]
            return parser, PLATFORM_NAMES.get(module_name, "UNKNOWN")
    return None, "UNKNOWN"


# ── Listado de correos ────────────────────────────────────────────────────────

# Correos que llegan desde el dominio de un portal pero NO son devoluciones:
#   · respuestas / reenvíos de personas («RE: Request for Revised Drawing ///P-24/070»,
#     «RE: 2206-300 - Documentación pendiente // P-26/048», «RE: Wrong Tag numbers»)
#   · acuses de lectura («Not read: …», «Leído: …»), autorespuestas y rebotes.
_NOISE_SUBJECT_RE = re.compile(
    r"^\s*(?:(?:re|fw|fwd|rv|aw|tr|sv|vs|ref)\s*(?:\[\d+\])?\s*:"
    r"|(?:not read|read|le[ií]do|no le[ií]do|automatic reply|respuesta autom|out of office|"
    r"undeliverable|delivery status|no se puede entregar|mail delivery)\b)", re.I)


def is_noise_email(e: dict) -> bool:
    """True para respuestas/reenvíos, acuses de lectura, informes de entrega y autorespuestas."""
    return bool(e.get("is_report")) or bool(_NOISE_SUBJECT_RE.match(e.get("subject") or ""))


def _detect_platform_for(e: dict):
    """Como _detect_platform pero descarta ruido y, si el parser sabe reconocer
    el asunto (`matches_subject`), exige que sea una devolución de verdad."""
    if is_noise_email(e):
        return None, "UNKNOWN"
    parser, platform = _detect_platform(e.get("from", ""))
    if parser is not None and hasattr(parser, "matches_subject") \
            and not parser.matches_subject(e.get("subject") or ""):
        return None, "UNKNOWN"
    return parser, platform


def _download_status(e: dict) -> dict:
    """Estado de descarga de la devolución (zip + archivo en dev.) para la lista."""
    try:
        from core.services import portal_downloads   # import perezoso: evita ciclo
        return portal_downloads.download_status(e.get("from", ""), e.get("subject") or "")
    except Exception:  # noqa: BLE001
        return {"code": "", "downloadable": False, "downloaded": False, "folder": ""}


def fetch_unread_emails(folder: str = "INBOX") -> list[dict]:
    raw = imap_service.list_unread(folder)
    processed = _load_processed()
    results = []
    for e in raw:
        parser, platform = _detect_platform_for(e)
        results.append({**e, "platform": platform, "parseable": parser is not None,
                        "processed": email_key(e) in processed,
                        **({"download": _download_status(e)} if parser else {})})
    return results


def fetch_all_emails(folder: str = "INBOX") -> list[dict]:
    """Sólo correos parseables (cualquier plataforma reconocida)."""
    raw = imap_service.list_all(folder)
    processed = _load_processed()
    out = []
    for e in raw:
        parser, platform = _detect_platform_for(e)
        if parser is None:
            continue
        out.append({
            **e,
            "platform": platform,
            "parseable": True,
            "processed": email_key(e) in processed,
            "download": _download_status(e),
        })
    return out


def saved_folder_for(preview: dict) -> str:
    """Carpeta donde quedó guardada la devolución de este correo ('' si no se ha descargado)."""
    return _download_status(preview).get("folder", "")


def saved_dev_folders_for(preview: dict) -> list[str]:
    """Carpetas dev. de 2-Tecnico donde se archivaron los PDF de esta devolución."""
    return list(_download_status(preview).get("dev_folders") or [])


# Caracteres que hay que escapar en un enlace `file:` para que no se rompa la
# URL. Los acentos NO están: ver `uri_carpeta`.
_ESCAPAR_URI = {"%": "%25", " ": "%20", "#": "%23", "?": "%3F"}


def uri_carpeta(ruta: Path | str) -> str:
    """`file:` de una carpeta de Windows, sin escapar los acentos.

    Aquí está el motivo, que costó verlo: el correo sale en UTF-8 y bien, pero
    **Windows descodifica los `%XX` de un enlace `file:` con la página de
    códigos ANSI**, no con UTF-8. Así, un «Año 2026» escapado en condiciones
    (`A%C3%B1o`) llega al explorador como «AÃ±o 2026», que no existe, y el
    enlace no abre nada. Con la eñe escrita tal cual —el correo va en UTF-8 y
    Outlook lo lee bien— llega entera.

    Se escapa solo lo que rompería la URL: el espacio, la almohadilla y el
    interrogante, que esos sí los entiende bien.
    """
    texto = str(ruta)
    for malo, bueno in _ESCAPAR_URI.items():
        texto = texto.replace(malo, bueno)
    texto = texto.replace("\\", "/")
    # \\SERVIDOR\recurso → file://SERVIDOR/recurso  ·  M:\… → file:///M:/…
    return "file:" + texto if texto.startswith("//") else "file:///" + texto


def folder_link_html(folder: str, depth: int = 1) -> str:
    """Enlace corto para el correo: «📂 dev NDE\\rev2 COM» apuntando a la carpeta.

    Se enlaza la ruta tal y como la ve el departamento —la unidad M:, que es la
    que todos tienen mapeada—, y la completa va en el tooltip para copiarla.
    `depth` = cuántos tramos finales se muestran.
    """
    from html import escape

    p = Path(folder)
    label = "\\".join(p.parts[-depth:]) if len(p.parts) >= depth else p.name
    if not p.is_absolute():      # ruta relativa o rara: mejor sin enlace que uno roto
        return escape(str(folder))
    return (f'<a href="{escape(uri_carpeta(p))}" title="{escape(str(p))}" '
            f'style="color:inherit;text-decoration:underline;">📂 {escape(label)}</a>')


# ── Preview ───────────────────────────────────────────────────────────────────

def rellenar_estado(df, parser, subject: str, msg=None):
    """Pone el Estado de los documentos cuando se puede deducir.

    Hay portales que no escriben la resolución en la tabla del correo pero la
    dejan en otro sitio:

    · **Document Space** la trae en el transmittal que va adjunto, con su
      leyenda impresa; se lee del propio correo, sin descargar nada.
    · **SACYR** la pone en el nombre de los ficheros del paquete (`…_R0_A`),
      así que hace falta tener la carpeta sincronizada a mano.

    Solo se rellena lo que está vacío: lo que se edite en la preview manda."""
    if df is None or getattr(df, "empty", True) or "Estado" not in df.columns:
        return df
    docs = df.to_dict("records")
    try:
        if parser is docspace_parser and msg is not None:
            from core.services import docspace
            adjunto = docspace.cover_adjunto(msg.as_bytes())
            if adjunto is None:
                return df
            docs = docspace.docs_con_estado(docs, adjunto[1])
        elif parser is sacyr_parser:
            from core.services import sacyr
            if not sacyr.is_configured():
                return df
            docs = sacyr.docs_con_estado(sacyr.parse_subject(subject)["code"], docs)
        else:
            return df
    except Exception as exc:  # noqa: BLE001 — sin estado se pone a mano, como antes
        logger.info("No se pudo deducir el Estado de «%s»: %s", subject[:60], exc)
        return df
    df = df.copy()
    df["Estado"] = [d.get("Estado", "") for d in docs]
    return df


def preview_email(uid: str, folder: str = "INBOX") -> dict:
    msg = imap_service.fetch_email(uid, folder)
    sender = imap_service._decode_header_value(msg.get("From", ""))
    subject = imap_service._decode_header_value(msg.get("Subject", ""))
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

    # Red de seguridad común: si el parser no resolvió pedido/cliente/material/PO
    # /Doc. EIPSA, se intenta por Nº Doc. Cliente contra el ERP (rellena huecos).
    df = enrich_missing_from_erp(df)

    # El Estado que el correo no trae escrito pero se puede averiguar, para no
    # tener que ponerlo a mano antes de mandar el aviso.
    df = rellenar_estado(df, parser, subject, msg)

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
    """Localiza (o crea) la carpeta `02 DEVOLUCIONES` del pedido.

    Estructura objetivo, según el tipo de pedido:
      · Normal  `P-XX-XXX`  →  …\\YYYY Pedidos\\<P-...>\\2-Tecnico\\00 DOCUMENTACIÓN\\02 DEVOLUCIONES
      · Almacén `PA-XX-XXX` →  …\\YYYY Pedidos Almacen\\<PA-...>\\00 DOCUMENTACIÓN\\02 DEVOLUCIONES
        (estructura plana: el PA no tiene subcarpeta '2-Tecnico')

    Reusa `apertura.find_documentacion_dir`, que detecta P vs PA, localiza la
    carpeta por prefijo tolerando `-S00` y crea el `00 DOCUMENTACIÓN` cuando hace
    falta (en PA). Si no encuentra la carpeta del pedido devuelve None.
    """
    from core.services import apertura

    base = Path(PEDIDOS_BASE_PATH) if PEDIDOS_BASE_PATH else apertura.DEFAULT_BASE_DIR
    if not base.exists():
        logger.info("Base de pedidos no accesible (%s)", base)
        return None

    doc_dir = apertura.find_documentacion_dir(pedido, base_dir=base, create=True)
    if doc_dir is None:
        logger.info("No se localizó 00 DOCUMENTACIÓN para %r bajo %s", pedido, base)
        return None

    target = doc_dir / "02 DEVOLUCIONES"
    try:
        target.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as exc:
        logger.warning("No se pudo crear %s: %s", target, exc)
        return None
    return target


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

    # Archivado .eml en la carpeta 02 DEVOLUCIONES del pedido. Reusamos las
    # bytes EXACTAS enviadas vía SMTP — así Date, Message-ID y MIME structure
    # son idénticos al correo entregado.
    saved_path = None
    save_error = None
    try:
        pedido = str(info_dict.get("Nº Pedido", "") or "").strip()
        if pedido:
            target = _find_devoluciones_folder(pedido)
            if target:
                pedido_norm = pedido.replace("/", "-").replace("\\", "-")
                ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                filename = f"{ts}_{pedido_norm}_DEV_MANUAL.eml"
                dest = target / filename
                raw = send_result.get("raw")
                dest = files.escribir(dest, raw if raw else
                                      _build_eml(subject, to, cc, html).encode("utf-8"))
                saved_path = str(dest)
                logger.info("Devolución manual archivada en %s", saved_path)
    except Exception as exc:
        save_error = str(exc)
        logger.warning("Fallo guardando EML manual: %s", exc)

    send_result_clean = {k: v for k, v in send_result.items() if k != "raw"}
    return {
        "success": True,
        "email_sent": send_result_clean,
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
    # Si la devolución ya está descargada y archivada, el correo dice dónde.
    devs = saved_dev_folders_for(preview)
    if devs:
        info_dict["Guardado en"] = "<br>".join(folder_link_html(d, depth=2) for d in devs)

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
    # Si la devolución ya está descargada y archivada, el correo dice dónde.
    devs = saved_dev_folders_for(preview)
    if devs:
        info_dict["Guardado en"] = "<br>".join(folder_link_html(d, depth=2) for d in devs)

    html_body = build_notification_html(info_dict, df, deadline)
    subject = f"DEV: {first.get('Nº Pedido', '')} [{preview['subject']}]"

    raw_eml = imap_service.fetch_raw(uid, folder)
    safe_name = re.sub(r'[\\/*?:"<>|]', "_", preview["subject"]) + ".eml"

    send_result = smtp_service.send_html_email(
        to, cc, subject, html_body,
        attachment_eml=raw_eml, attachment_name=safe_name,
    )

    imap_service.mark_as_read(uid, folder)
    _save_processed(_message_id_from_raw(raw_eml) or uid)

    # Archivado .eml en la carpeta 02 DEVOLUCIONES del pedido (bytes reales
    # del MIME enviado, no un .eml reconstruido — preserva Date/Message-ID).
    saved_path = None
    save_error = None
    try:
        pedido = str(first.get("Nº Pedido", "") or "")
        if pedido:
            target = _find_devoluciones_folder(pedido)
            if target:
                pedido_norm = pedido.replace("/", "-").replace("\\", "-")
                ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                filename = f"{ts}_{pedido_norm}_DEV.eml"
                dest = target / filename
                raw = send_result.get("raw")
                dest = files.escribir(dest, raw if raw else
                                      _build_eml(subject, to, cc, html_body).encode("utf-8"))
                saved_path = str(dest)
                logger.info("Devolución archivada en %s", saved_path)
    except Exception as exc:
        save_error = str(exc)
        logger.warning("Fallo guardando EML en carpeta de pedido: %s", exc)

    # No exponer las bytes raw (grandes) en el dict de retorno
    send_result_clean = {k: v for k, v in send_result.items() if k != "raw"}

    return {
        "success": True,
        "email_sent": send_result_clean,
        "documents_count": len(df),
        "subject": subject,
        "saved_path": saved_path,
        "save_error": save_error,
    }
