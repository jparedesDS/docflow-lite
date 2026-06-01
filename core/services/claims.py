"""ClaimService LITE — reclamaciones de documentos pendientes de devolución.

Port del claim_service del DocFlow grande, simplificado:
- Lee del monitoring_service (data_erp + consulta_erp)
- Reusa compute_recipients/RESPONSABLE_PEDIDO_MAP/DEFAULT_TO/DEFAULT_CC del base_parser
- Mantiene el sistema de escalation 3 niveles (recordatorio / formal / urgente)
- Log en state/claims_log.json
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.config import PEDIDOS_BASE_PATH, SMTP_USER, USERS
from core.paths import state_dir
from core.parsers.base_parser import (
    DEFAULT_CC,
    DEFAULT_TO,
    RESPONSABLE_PEDIDO_MAP,
    _load_logo_b64,
    compute_recipients,
)
from core.services import monitoring
from core.services import smtp as smtp_service
from core.utils.json_store import read_json, write_json

logger = logging.getLogger(__name__)

CLAIMS_LOG_PATH = str(state_dir() / "claims_log.json")
CLAIM_RECIPIENTS_PATH = str(state_dir() / "claim_recipients.json")

URGENCY_THRESHOLDS = {"low": 15, "medium": 30, "high": 60}

ESCALATION_LEVELS = {
    1: {"name": "reminder", "label": "Document Review Reminder",  "accent": "#2563EB"},
    2: {"name": "formal",   "label": "Formal Document Claim",     "accent": "#D97706"},
    3: {"name": "urgent",   "label": "Urgent Escalation Notice",  "accent": "#DC2626"},
}

DIRECTION_CC = ["enrique-serrano@eipsa.es"]

NAVY = "#1B3A5C"

STATUS_EN = {
    "Enviado": "Submitted",
    "Aprobado": "Approved",
    "Rechazado": "Rejected",
    "En Revisión": "Under Review",
    "Aprobado con Com.": "Approved w/ Comments",
    "Aprobado con com. menores": "Approved w/ Min. Comments",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean(value) -> str:
    """Convierte un valor de pandas/dict a string limpia (sin 'nan')."""
    if value is None:
        return ""
    s = str(value).strip()
    if s.lower() == "nan":
        return ""
    return s


_REVISION_KEYS = ("Nº Revisión", "Nº Rev.", "Nº Rev", "Revisión", "Rev.", "Rev", "Revision")


def _format_revision(value) -> str:
    """Normaliza un valor de revisión: 3.0 → '3', 'A' → 'A', '' → ''.

    Pandas tiende a leer columnas numéricas como float64 — así un '3' del
    Excel llega como `3.0`. Convertimos a int cuando el float representa
    un entero exacto, y dejamos el resto tal cual (letras, dobles A.1, …).
    """
    if value is None:
        return ""
    # Caso 1: ya es int
    if isinstance(value, bool):  # bool es subclase de int — descartar
        return _clean(value)
    if isinstance(value, int):
        return str(value)
    # Caso 2: float entero (3.0 → 3)
    if isinstance(value, float):
        if value != value:  # NaN
            return ""
        if value.is_integer():
            return str(int(value))
        # Float no entero: '3.5' como string limpio
        return f"{value:g}"
    # Caso 3: string — pero puede ser "3.0" si pandas ya stringified
    s = _clean(value)
    if not s:
        return ""
    # Intenta parsear "3.0", "3,0" como float y normalizar
    try:
        f = float(s.replace(",", "."))
        if f.is_integer():
            return str(int(f))
    except ValueError:
        pass
    return s


def _resolve_revision(doc: dict) -> str:
    """Busca el número de revisión probando varios nombres de columna."""
    for k in _REVISION_KEYS:
        if k in doc:
            raw = doc.get(k)
            if raw is None:
                continue
            formatted = _format_revision(raw)
            if formatted:
                return formatted
    return ""


def _normalize_pedido(pedido_raw: str) -> str:
    """Elimina sufijo -S00/-S01 para agrupar por pedido base."""
    p = (pedido_raw or "").strip()
    return re.sub(r"(?i)-s\d{1,3}$", "", p)


def _load_log() -> dict:
    return read_json(CLAIMS_LOG_PATH, default={})


def _save_log(log: dict) -> None:
    write_json(CLAIMS_LOG_PATH, log)


# ── Recipients persistidos por pedido ─────────────────────────────────────────

def get_saved_recipients(pedido: str) -> dict | None:
    """Devuelve {to, cc, updatedAt} si hay destinatarios guardados, o None."""
    data = read_json(CLAIM_RECIPIENTS_PATH, default={})
    return data.get(pedido)


def save_recipients(pedido: str, to: list[str], cc: list[str]) -> None:
    data = read_json(CLAIM_RECIPIENTS_PATH, default={})
    data[pedido] = {
        "to": list(to or []),
        "cc": list(cc or []),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    write_json(CLAIM_RECIPIENTS_PATH, data)


def forget_recipients(pedido: str) -> None:
    data = read_json(CLAIM_RECIPIENTS_PATH, default={})
    if pedido in data:
        del data[pedido]
        write_json(CLAIM_RECIPIENTS_PATH, data)


# ── API pública ───────────────────────────────────────────────────────────────

DEFAULT_MIN_DAYS = 15


def get_claimable_docs(min_days: int = DEFAULT_MIN_DAYS) -> list[dict]:
    """Docs con Estado='Enviado' y Días Devolución ≥ `min_days`.

    `min_days=0` devuelve todos los enviados pendientes (sin filtro).
    """
    docs = monitoring.get_monitoring_data()
    result = []
    for doc in docs:
        estado = str(doc.get("Estado", "") or "").strip().lower()
        if estado != "enviado":
            continue
        try:
            if int(float(doc.get("Días Devolución", 0) or 0)) >= min_days:
                result.append(doc)
        except (ValueError, TypeError):
            pass
    return result


def get_claimable_pedidos(min_days: int = DEFAULT_MIN_DAYS) -> list[dict]:
    """Pedidos con docs reclamables, ordenados por urgencia (max_dias desc)."""
    docs = get_claimable_docs(min_days=min_days)
    log = _load_log()

    groups: dict[str, list[dict]] = {}
    for doc in docs:
        pedido = _normalize_pedido(str(doc.get("Nº Pedido", "") or ""))
        groups.setdefault(pedido, []).append(doc)

    result = []
    for pedido, pedido_docs in groups.items():
        dias_list = []
        for d in pedido_docs:
            try:
                dias_list.append(int(float(d.get("Días Devolución", 0) or 0)))
            except (ValueError, TypeError):
                dias_list.append(0)

        max_dias = max(dias_list) if dias_list else 0
        first = pedido_docs[0]

        if max_dias >= URGENCY_THRESHOLDS["high"]:
            urgency = "high"
        elif max_dias >= URGENCY_THRESHOLDS["medium"]:
            urgency = "medium"
        else:
            urgency = "low"

        entry = log.get(pedido, {})
        last_claimed = entry.get("last_claimed") or entry.get("sent_at")
        history = entry.get("history", [])

        result.append({
            "pedido": pedido,
            "po": str(first.get("Nº PO", "") or ""),
            "cliente": str(first.get("Cliente", "") or ""),
            "responsable": str(first.get("Responsable", "") or ""),
            "material": str(first.get("Material", "") or ""),
            "docs_count": len(pedido_docs),
            "max_dias": max_dias,
            "urgency": urgency,
            "last_claimed": last_claimed,
            "claim_count": len(history),
        })

    result.sort(key=lambda x: -x["max_dias"])
    return result


def get_pedido_preview(pedido: str, min_days: int = DEFAULT_MIN_DAYS) -> dict:
    """Datos completos para preview del email."""
    docs = get_claimable_docs(min_days=min_days)
    pedido_docs = [
        d for d in docs
        if _normalize_pedido(str(d.get("Nº Pedido", "") or "")) == pedido
    ]
    if not pedido_docs:
        raise ValueError(f"No hay documentos reclamables para el pedido {pedido}")

    first = pedido_docs[0]
    po = str(first.get("Nº PO", "") or "")
    cliente = str(first.get("Cliente", "") or "")

    df = pd.DataFrame(pedido_docs)
    if "Nº Doc. EIPSA" in df.columns:
        df["_doc_code"] = df["Nº Doc. EIPSA"].astype(str).str.extract(
            r"-([A-Z]{2,4})-", expand=False
        ).fillna("")
    suggested_to, suggested_cc = compute_recipients(df)

    table_rows = []
    for doc in pedido_docs:
        try:
            dias = int(float(doc.get("Días Devolución", "") or 0))
        except (ValueError, TypeError):
            dias = ""
        fecha_env = doc.get("Fecha Env. Doc.", "") or doc.get("Fecha", "")
        if hasattr(fecha_env, "strftime"):
            fecha_env = fecha_env.strftime("%d-%m-%Y")
        elif fecha_env:
            fecha_env = str(fecha_env).split(" ")[0].split("T")[0]

        table_rows.append({
            "order_no": _clean(doc.get("Nº Pedido", "")),
            "po_no": po,
            "client_doc_no": _clean(doc.get("Nº Doc. Cliente", "")),
            "eipsa_doc_no": _clean(doc.get("Nº Doc. EIPSA", "")),
            "title": _clean(doc.get("Título", "")),
            "status": _clean(doc.get("Estado", "")),
            "revision": _resolve_revision(doc),
            "sent_date": fecha_env,
            "return_days": dias,
        })
    table_rows.sort(key=lambda x: -(x["return_days"] if isinstance(x["return_days"], int) else 0))

    saved = get_saved_recipients(pedido)
    # Communication matrix (segunda prioridad después de explícitos)
    from core.services import comm_matrix
    matrix = comm_matrix.get_contacts(pedido)
    return {
        "pedido": pedido,
        "po": po,
        "cliente": cliente,
        "docs_count": len(table_rows),
        "table_rows": table_rows,
        "suggested_to": suggested_to,
        "suggested_cc": suggested_cc,
        "saved_to": saved["to"] if saved else None,
        "saved_cc": saved["cc"] if saved else None,
        "saved_at": saved["updatedAt"] if saved else None,
        "matrix_to": matrix["to"] if matrix else None,
        "matrix_cc": matrix["cc"] if matrix else None,
        "matrix_updated_at": matrix["updatedAt"] if matrix else None,
    }


def get_pedido_history(pedido: str) -> dict:
    log = _load_log()
    entry = log.get(pedido, {})
    if "history" not in entry:
        history = []
        if "sent_at" in entry:
            history.append({
                "sent_at": entry["sent_at"],
                "to": entry.get("to", []),
                "cc": entry.get("cc", []),
                "docs_count": entry.get("docs_count", 0),
                "level": 1,
            })
    else:
        history = entry["history"]
    return {"pedido": pedido, "count": len(history), "entries": history}


# ── Escalation ────────────────────────────────────────────────────────────────

def get_escalation_level(pedido_data: dict) -> int:
    max_dias = pedido_data.get("max_dias", 0)
    claim_count = pedido_data.get("claim_count")
    if claim_count is None:
        claim_count = get_pedido_history(pedido_data.get("pedido", "")).get("count", 0)

    if max_dias >= 60 or claim_count >= 2:
        return 3
    if max_dias >= 30 or claim_count >= 1:
        return 2
    return 1


def get_escalation_recipients(pedido_data: dict, level: int) -> tuple[list[str], list[str]]:
    to = list(DEFAULT_TO)
    cc = list(DEFAULT_CC)

    pedido = pedido_data.get("pedido", "")
    pm_email = RESPONSABLE_PEDIDO_MAP.get(pedido)
    if pm_email and pm_email not in to and pm_email not in cc:
        cc.append(pm_email)

    if level >= 2:
        for email in DIRECTION_CC:
            if email not in cc:
                cc.append(email)

    if level >= 3:
        responsable = pedido_data.get("responsable", "")
        if responsable in USERS:
            for email in USERS[responsable].get("emails", []):
                if email not in cc and email not in to:
                    cc.append(email)

    return to, cc


# ── Generación de HTML (preview sin enviar) ──────────────────────────────────

def generate_claim_html(
    pedido: str,
    level: int | None = None,
    include_eipsa_codes: list[str] | None = None,
    min_days: int = DEFAULT_MIN_DAYS,
) -> dict:
    """Genera el HTML que se enviaría como reclamación, sin enviar.

    Devuelve dict con `html`, `subject`, `level`, `docs_count` para preview.
    """
    pedidos = get_claimable_pedidos(min_days=min_days)
    pedido_data = next((p for p in pedidos if p["pedido"] == pedido), None)
    if not pedido_data:
        raise ValueError(f"Pedido {pedido} no encontrado o no reclamable")

    if level is None:
        level = get_escalation_level(pedido_data)

    preview = get_pedido_preview(pedido, min_days=min_days)
    if include_eipsa_codes is not None:
        wanted = {str(c) for c in include_eipsa_codes}
        filtered = [r for r in preview["table_rows"] if r["eipsa_doc_no"] in wanted]
        if not filtered:
            raise ValueError("Ningún documento marcado — selecciona al menos uno.")
        preview = {**preview, "table_rows": filtered, "docs_count": len(filtered)}

    html = _build_html(preview, level)
    subject = _subject_for(pedido, preview.get("po", ""), level)
    return {
        "html": html,
        "subject": subject,
        "level": level,
        "docs_count": preview["docs_count"],
    }


# ── Envío ─────────────────────────────────────────────────────────────────────

def send_claim(
    pedido: str,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    level: int | None = None,
    include_eipsa_codes: list[str] | None = None,
    persist_recipients: bool = True,
    min_days: int = DEFAULT_MIN_DAYS,
) -> dict:
    pedidos = get_claimable_pedidos(min_days=min_days)
    pedido_data = next((p for p in pedidos if p["pedido"] == pedido), None)
    if not pedido_data:
        raise ValueError(f"Pedido {pedido} no encontrado o no reclamable")

    if level is None:
        level = get_escalation_level(pedido_data)

    # Fallback de destinatarios: explícitos > matrix > saved > auto-detectados
    if to is None or cc is None:
        from core.services import comm_matrix
        matrix = comm_matrix.get_contacts(pedido)
        if matrix:
            if to is None and matrix.get("to"):
                to = list(matrix["to"])
            if cc is None and matrix.get("cc"):
                cc = list(matrix["cc"])
    if to is None or cc is None:
        saved = get_saved_recipients(pedido)
        if saved:
            if to is None:
                to = list(saved.get("to") or [])
            if cc is None:
                cc = list(saved.get("cc") or [])
    if to is None or cc is None:
        auto_to, auto_cc = get_escalation_recipients(pedido_data, level)
        if to is None:
            to = auto_to
        if cc is None:
            cc = auto_cc

    if not to:
        raise ValueError("Lista 'to' vacía")

    preview = get_pedido_preview(pedido, min_days=min_days)
    if include_eipsa_codes is not None:
        wanted = {str(c) for c in include_eipsa_codes}
        filtered = [r for r in preview["table_rows"] if r["eipsa_doc_no"] in wanted]
        if not filtered:
            raise ValueError("Ningún documento marcado — selecciona al menos uno.")
        preview = {**preview, "table_rows": filtered, "docs_count": len(filtered)}

    html = _build_html(preview, level)
    subject = _subject_for(pedido, preview.get("po", ""), level)

    result = smtp_service.send_html_email(to, cc, subject, html)

    _log_claim(pedido, level, to, cc, preview["docs_count"])

    if persist_recipients:
        save_recipients(pedido, to, cc)

    # Archivado .eml en la carpeta del pedido (01 RECLAMACIONES dentro de
    # 2-Tecnico/00 DOCUMENTACIÓN). Reusamos las bytes EXACTAS enviadas vía
    # SMTP — así el .eml conserva Date, Message-ID y MIME structure correctos.
    saved_path = None
    save_error = None
    try:
        folder = _find_reclamaciones_folder(pedido)
        if folder:
            pedido_norm = pedido.replace("/", "-").replace("\\", "-")
            ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            filename = f"{ts}_{pedido_norm}_RECLAM_L{level}.eml"
            raw_bytes = result.get("raw")
            target = folder / filename
            if raw_bytes:
                target.write_bytes(raw_bytes)
            else:
                # Fallback defensivo si el SMTP no devolvió raw
                target.write_text(_build_eml(subject, to, cc, html), encoding="utf-8")
            saved_path = str(target)
            logger.info("Reclamación archivada en %s", saved_path)
    except Exception as exc:
        save_error = str(exc)
        logger.warning("Fallo archivando .eml en carpeta del pedido: %s", exc)

    # No exponer las bytes raw en el dict final — son grandes y ya están en disco
    email_sent_clean = {k: v for k, v in result.items() if k != "raw"}

    return {
        "success": True,
        "level": level,
        "level_name": ESCALATION_LEVELS[level]["name"],
        "subject": subject,
        "to": to,
        "cc": cc,
        "docs_count": preview["docs_count"],
        "saved_path": saved_path,
        "save_error": save_error,
        "email_sent": email_sent_clean,
    }


def send_bulk(pedidos: list[str], min_days: int = DEFAULT_MIN_DAYS) -> dict:
    """Envía reclamaciones para varios pedidos con nivel/destinatarios auto-detectados.

    Devuelve un resumen agregado con éxitos y errores por pedido.
    """
    claimable = {p["pedido"]: p for p in get_claimable_pedidos(min_days=min_days)}
    sent: list[dict] = []
    errors: list[dict] = []

    for pedido in pedidos:
        data = claimable.get(pedido)
        if not data:
            errors.append({"pedido": pedido, "error": f"No reclamable (no docs ≥ {min_days} días)"})
            continue
        try:
            res = send_claim(pedido, to=None, cc=None, level=None, min_days=min_days)
            sent.append({
                "pedido": pedido,
                "level": res["level"],
                "level_name": res["level_name"],
                "docs_count": res["docs_count"],
            })
        except Exception as exc:
            logger.exception("Error enviando reclamación %s", pedido)
            errors.append({"pedido": pedido, "error": str(exc)})

    return {"sent": sent, "errors": errors, "total": len(pedidos)}


def _log_claim(pedido: str, level: int, to: list, cc: list, docs_count: int) -> None:
    log = _load_log()
    now_iso = datetime.now(timezone.utc).isoformat()
    existing = log.get(pedido, {})

    history = existing.get("history")
    if history is None:
        history = []
        if "sent_at" in existing:
            history.append({
                "sent_at": existing["sent_at"],
                "to": existing.get("to", []),
                "cc": existing.get("cc", []),
                "docs_count": existing.get("docs_count", 0),
                "level": 1,
            })

    history.append({
        "sent_at": now_iso,
        "to": to,
        "cc": cc,
        "docs_count": docs_count,
        "level": level,
    })

    log[pedido] = {"last_claimed": now_iso, "history": history}
    _save_log(log)


def _find_reclamaciones_folder(pedido: str) -> Path | None:
    """Localiza (o crea) la carpeta `01 RECLAMACIONES` del pedido.

    Estructura objetivo:
        M:\\base de datos de pedidos\\Año YYYY\\YYYY Pedidos\\
            <P-XX-XXX … >\\2-Tecnico\\00 DOCUMENTACIÓN\\01 RECLAMACIONES

    Reusa los helpers de `apertura` que ya saben localizar el pedido por
    prefijo (`P-XX-XXX`) ignorando si la carpeta lleva `-S00` o no.

    Si la carpeta `01 RECLAMACIONES` no existe pero el resto del path sí,
    la crea para que el archivado funcione la primera vez.
    """
    from core.services import apertura

    # Resolver base — la env var manda; si no, default M:\base de datos de pedidos
    base = Path(PEDIDOS_BASE_PATH) if PEDIDOS_BASE_PATH else apertura.DEFAULT_BASE_DIR
    if not base.exists():
        logger.info("Base de pedidos no accesible (%s)", base)
        return None

    # Año del pedido: P-26/050 → 2026
    try:
        folder_id, _ = apertura.parse_pedido(pedido)
    except ValueError:
        logger.warning("Pedido no parseable: %r", pedido)
        return None
    m = apertura._PEDIDO_FOLDER_RE.match(folder_id)
    if not m:
        return None
    año = 2000 + int(m.group(1))

    pedido_dir = apertura.find_existing_pedido_dir(folder_id, año, base_dir=base)
    if pedido_dir is None:
        logger.info("Pedido %s no encontrado bajo %s", folder_id, base)
        return None

    tecnico = apertura.find_tecnico_dir(pedido_dir)
    if tecnico is None:
        logger.info("2-Tecnico no existe en %s", pedido_dir)
        return None

    target = tecnico / "00 DOCUMENTACIÓN" / "01 RECLAMACIONES"
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


def _subject_for(pedido: str, po: str, level: int) -> str:
    """Subject único para todos los niveles — el nivel se refleja en el cuerpo
    del email (banner + tono del HTML), no en el subject."""
    return f"{pedido} / PO: {po} // DOCUMENTS PENDING REVIEW"


# ── HTML profesional (mismas plantillas que DocFlow grande) ───────────────────

def _build_html(preview: dict, level: int) -> str:
    meta = ESCALATION_LEVELS[level]
    accent = meta["accent"]

    # Logo compuesto sobre navy en backend (PIL), sin caja
    logo_b64 = _load_logo_b64(bg_color=NAVY)
    if logo_b64:
        logo_html = (
            f'<img src="data:image/png;base64,{logo_b64}" alt="EIPSA" '
            f'style="display:block;height:34px;width:auto;border:0;outline:0;" />'
        )
    else:
        logo_html = (
            f'<span style="font-size:18px;font-weight:800;color:#FFFFFF;'
            f'letter-spacing:1.2px;">EIPSA</span>'
        )

    rows_html = ""
    for i, row in enumerate(preview["table_rows"]):
        bg_row = "#F4F7FC" if i % 2 == 0 else "#FFFFFF"
        sep = "border-bottom:1px solid #DDE3F5;border-right:1px solid #DDE3F5;"
        sep_last = "border-bottom:1px solid #DDE3F5;"
        cell = f"background:{bg_row};padding:11px 14px;font-size:10pt;line-height:1.4;color:#263238;"

        dias = row["return_days"]
        dias_cell = (
            f'<span style="font-weight:700;color:#C62828;background:#FFEBEE;'
            f'padding:2px 7px;border-radius:4px;">{dias}</span>'
            if isinstance(dias, int) and dias > 0
            else (str(dias) if dias != "" else '<span style="color:#B0BEC5;">—</span>')
        )

        status_val = row["status"]
        status_en = STATUS_EN.get(status_val, status_val)
        status_style = "background:#E3F2FD;color:#1565C0;border:1px solid #BBDEFB;"
        if status_val == "Aprobado":
            status_style = "background:#E8F5E9;color:#2E7D32;border:1px solid #C8E6C9;"
        elif status_val == "Rechazado":
            status_style = "background:#FFEBEE;color:#C62828;border:1px solid #FFCDD2;"
        elif "Com" in status_val:
            status_style = "background:#FFF8E1;color:#E65100;border:1px solid #FFE082;"

        rows_html += f"""
        <tr>
          <td style="{cell}{sep}white-space:nowrap;">{row['order_no']}</td>
          <td style="{cell}{sep}white-space:nowrap;font-family:monospace;">{row['po_no']}</td>
          <td style="{cell}{sep}">{row['client_doc_no'] or '<span style="color:#B0BEC5;">—</span>'}</td>
          <td style="{cell}{sep}white-space:nowrap;font-family:monospace;">{row['eipsa_doc_no']}</td>
          <td style="{cell}{sep}">{row['title']}</td>
          <td style="{cell}{sep}text-align:center;">
            <span style="padding:3px 10px;border-radius:4px;font-size:9pt;font-weight:700;white-space:nowrap;{status_style}">{status_en}</span>
          </td>
          <td style="{cell}{sep}text-align:center;">{row['revision'] or '—'}</td>
          <td style="{cell}{sep}white-space:nowrap;font-family:monospace;">{row['sent_date'] or '—'}</td>
          <td style="{cell}{sep_last}text-align:center;white-space:nowrap;">{dias_cell}</td>
        </tr>"""

    today = datetime.now().strftime("%d/%m/%Y")
    pedido = preview["pedido"]
    po = preview["po"]
    cliente = preview["cliente"]
    docs_count = preview["docs_count"]
    doc_label = "document" if docs_count == 1 else "documents"

    th = (
        f"background:{NAVY};color:#FFFFFF;padding:10px 14px;font-size:9px;"
        f"font-weight:700;letter-spacing:0.06em;text-transform:uppercase;"
        f"text-align:left;border-right:1px solid #234B73;"
    )

    if level == 1:
        body_text = (
            f"Please find below the list of documents submitted for review under "
            f"<strong>Order {pedido}</strong>"
            f"{f' / PO <strong>{po}</strong>' if po else ''}"
            f"{f' — <strong>{cliente}</strong>' if cliente else ''}. "
            f"The following <strong>{docs_count} {doc_label}</strong> have been sent "
            f"pending review and have not yet been returned by the customer."
        )
        closing_text = (
            "We kindly request you to confirm the review status of the above documents "
            "at your earliest convenience, or let us know if any additional information "
            "is required on your end."
        )
    elif level == 2:
        body_text = (
            f"We would like to formally bring to your attention that the following "
            f"<strong>{docs_count} {doc_label}</strong> under "
            f"<strong>Order {pedido}</strong>"
            f"{f' / PO <strong>{po}</strong>' if po else ''}"
            f"{f' — <strong>{cliente}</strong>' if cliente else ''} "
            f"have been pending review for an extended period. "
            f"This delay may affect project scheduling and contractual milestones."
        )
        closing_text = (
            "We respectfully request your immediate attention to this matter. "
            "Please confirm the review status or provide an estimated return date "
            "as soon as possible to avoid further delays in the project timeline."
        )
    else:
        body_text = (
            f"<strong style='color:#DC2626;'>URGENT:</strong> Despite previous communications, "
            f"the following <strong>{docs_count} {doc_label}</strong> under "
            f"<strong>Order {pedido}</strong>"
            f"{f' / PO <strong>{po}</strong>' if po else ''}"
            f"{f' — <strong>{cliente}</strong>' if cliente else ''} "
            f"remain pending review for a critical period exceeding contractual timelines. "
            f"This situation requires immediate action."
        )
        closing_text = (
            "<strong>Immediate action is required.</strong> Please prioritize the review "
            "of the above documents and confirm the status within the next 48 hours. "
            "Failure to respond may result in formal contractual escalation procedures."
        )

    level_badge = (
        f'<span style="display:inline-block;padding:4px 12px;border-radius:4px;'
        f'font-size:10px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;'
        f'background:{accent}18;color:{accent};border:1px solid {accent}40;">'
        f'{meta["label"]}</span>'
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#EEF2F9;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#EEF2F9;padding:32px 0;">
<tr><td align="center">
<table width="800" cellpadding="0" cellspacing="0" style="max-width:800px;background:#FFFFFF;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(30,45,125,0.12);">
  <tr><td style="background:{NAVY};padding:16px 28px;border-top:4px solid {accent};">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="vertical-align:middle;">{logo_html}</td>
      <td style="vertical-align:middle;text-align:right;">
        <p style="margin:0;font-size:14px;font-weight:700;color:#FFFFFF;">{meta['label']}</p>
        <p style="margin:4px 0 0;font-size:11px;color:{accent};letter-spacing:0.04em;text-transform:uppercase;">Ref: {pedido}</p>
      </td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:24px 28px 8px;">
    <div style="margin-bottom:16px;">{level_badge}</div>
    <p style="margin:0 0 4px;font-size:13px;color:{NAVY};font-weight:600;">Dear All,</p>
    <p style="margin:0 0 20px;font-size:12px;color:#37474F;line-height:1.6;">{body_text}</p>
    <p style="margin:0 0 8px;font-size:10px;font-weight:700;color:{accent};text-transform:uppercase;letter-spacing:0.08em;">Pending Documents ({docs_count})</p>
    <table cellpadding="0" cellspacing="0" style="width:100%;border-radius:8px;overflow:hidden;border:1px solid #DDE3F5;margin-bottom:24px;">
      <thead><tr>
        <th style="{th}">Order No.</th><th style="{th}">PO No.</th><th style="{th}">Client Doc.</th>
        <th style="{th}">EIPSA Doc.</th><th style="{th}">Title</th><th style="{th}">Status</th>
        <th style="{th}">Rev.</th><th style="{th}">Sent Date</th>
        <th style="{th}border-right:none;">Return Days</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    <p style="margin:0 0 6px;font-size:12px;color:#37474F;line-height:1.6;">{closing_text}</p>
    <p style="margin:0 0 24px;font-size:12px;color:#37474F;">Best regards,<br><strong>Document Control</strong></p>
  </td></tr>
  <tr><td style="background:#F4F7FC;border-top:3px solid {accent};padding:16px 28px;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td>
        <p style="margin:0;font-size:12px;font-weight:700;color:{NAVY};">Document Control</p>
        <p style="margin:3px 0 0;font-size:11px;color:#90A4AE;">
          <a href="mailto:{SMTP_USER}" style="color:{accent};text-decoration:none;">{SMTP_USER}</a>
        </p>
      </td>
      <td style="text-align:right;vertical-align:middle;">
        <p style="margin:0;font-size:10px;color:#B0BEC5;">DocFlow &nbsp;·&nbsp; © 2026 jparedesDS &nbsp;·&nbsp; {today}</p>
      </td>
    </tr></table>
  </td></tr>
</table></td></tr></table>
</body></html>"""
