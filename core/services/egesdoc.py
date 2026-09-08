"""Portal eGesDoc (Técnicas Reunidas) — cliente HTTP de solo lectura/descarga.

El portal es ASP.NET MVC clásico con jQuery/DataTables. Este módulo reproduce,
sin navegador, exactamente las peticiones que hace Chrome cuando el usuario
entra, elige el PO, abre «Transmittals» y pulsa «Download»:

  1. POST /Login/Login                  (con el token anti-falsificación de /Login/Index)
  2. POST /Main/SelectProject           {projectCode}   → proyecto activo en sesión
  3. GET  /Main/SelectPurchaseOrder     ?project=&purchaseOrder=  → entra en el PO
  4. POST /Supplier/Transmittal/GetTransmittals          → JSON con los transmittals del PO
  5. POST /Supplier/Transmittal/ExportTransmittal {id}   → el portal prepara el zip
     GET  /Supplier/Transmittal/DownloadTransmittal      → lo descarga

Nunca se sube ni se modifica nada en el portal.

Credenciales: preferencia ``egesdoc_user`` + secreto ``egesdoc_pass`` (keyring /
cifrado local, igual que el correo). Nunca se escriben en disco en claro.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from html import unescape
from pathlib import Path

import requests

from core import credentials, preferences
from core.utils import http

logger = logging.getLogger(__name__)

BASE = "https://egesdoc.tecnicasreunidas.es"
TIMEOUT = 25
DOWNLOAD_TIMEOUT = 180
EXPORT_RETRIES = 3
_AJAX = {"X-Requested-With": "XMLHttpRequest"}

# Asunto típico: "eGesdoc - New transmittal registered (10571-TRSEI-V-13174) - PO(1057410920)"
# También: "… registered (1078010910-VT-0022) - PO(1078010910)" (otro formato de código).
_REGISTERED_RE = re.compile(r"transmittal\s+registered\s*\(\s*([^()\s]+)\s*\)", re.I)
_CODE_RE = re.compile(r"\b(\d{5}-[A-Z0-9]{2,}-[A-Z]-\d+)\b")
_PROJECT_PREFIX_RE = re.compile(r"^(\d{5})-(?!\d)")
_PO_RE = re.compile(r"PO\s*\(\s*(\d{10})\s*\)", re.I)
_PO_ANY_RE = re.compile(r"\b(\d{10})\b")


# ── Credenciales ──────────────────────────────────────────────────────────────

def _creds() -> tuple[str, str]:
    user = (preferences.get("egesdoc_user") or "").strip()
    pwd = credentials.get("egesdoc_pass", env_fallback="EGESDOC_PASS") or ""
    return user, pwd


def is_configured() -> bool:
    user, pwd = _creds()
    return bool(user and pwd)


# ── Asunto del correo ─────────────────────────────────────────────────────────

def parse_subject(subject: str) -> dict:
    """Extrae del asunto el código de transmittal, el PO y el proyecto (los 5
    primeros dígitos del transmittal; OJO: no coinciden con los del PO)."""
    subject = subject or ""
    m = _REGISTERED_RE.search(subject) or _CODE_RE.search(subject)
    code = m.group(1).strip() if m else ""
    m = _PO_RE.search(subject) or _PO_ANY_RE.search(subject)
    po = m.group(1) if m else ""
    # El proyecto solo se deduce si el código empieza por sus 5 dígitos
    # («10571-TRSEI-…»); con códigos tipo «1078010910-VT-0022» se buscará.
    pm = _PROJECT_PREFIX_RE.match(code)
    return {"code": code, "po": po, "project": pm.group(1) if pm else ""}


# ── Sesión / login ────────────────────────────────────────────────────────────

def _new_session() -> requests.Session:
    return http.session()


def _hidden(html: str, name: str) -> str:
    m = re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), html) or \
        re.search(r'value="([^"]*)"[^>]*name="%s"' % re.escape(name), html)
    return unescape(m.group(1)) if m else ""


def login(session: requests.Session | None = None) -> requests.Session:
    """Abre sesión en el portal. Lanza RuntimeError si no se puede."""
    user, pwd = _creds()
    if not user or not pwd:
        raise RuntimeError("Faltan usuario o contraseña de eGesDoc (Ajustes ▸ Portales).")
    s = session or _new_session()
    r = s.get(f"{BASE}/Login/Index", timeout=TIMEOUT)
    r.raise_for_status()
    token = _hidden(r.text, "__RequestVerificationToken")
    version = _hidden(r.text, "Version")
    data = {"__RequestVerificationToken": token, "Username": user, "Password": pwd,
            "RememberMe": "false"}
    if version:
        data["Version"] = version
    r = s.post(f"{BASE}/Login/Login", data=data, timeout=TIMEOUT, allow_redirects=True,
               headers={"Referer": f"{BASE}/Login/Index"})
    # Verificación robusta: la raíz ya no redirige al login
    chk = s.get(f"{BASE}/", timeout=TIMEOUT, allow_redirects=True)
    if "/Login" in chk.url or 'id="loginForm"' in chk.text:
        hint = ""
        try:
            j = r.json()
            hint = f" ({j.get('message') or j.get('Message') or j})"
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError("eGesDoc rechazó el acceso: revisa usuario/contraseña" + hint)
    logger.info("eGesDoc: sesión abierta como %s", user)
    return s


def test_login() -> tuple[bool, str]:
    """(ok, mensaje). No modifica nada en el portal."""
    try:
        s = login()
        s.close()
        return True, "Acceso correcto a eGesDoc"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc).splitlines()[0] if str(exc) else repr(exc)


# ── Proyecto y PO ─────────────────────────────────────────────────────────────

def projects(s: requests.Session) -> list[tuple[str, str]]:
    """[(código, nombre)] de los proyectos visibles para el usuario (selector de la Home)."""
    r = s.get(f"{BASE}/", timeout=TIMEOUT)
    r.raise_for_status()
    m = re.search(r'<select[^>]*id="project-select"[^>]*>(.*?)</select>', r.text, re.S | re.I)
    if not m:
        return []
    out = []
    for value, inner in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', m.group(1), re.S | re.I):
        if value and value != "-1":
            name = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", inner))).strip()
            out.append((value, name))
    return out


def select_project(s: requests.Session, project: str) -> bool:
    r = s.post(f"{BASE}/Main/SelectProject", data={"projectCode": project}, headers=_AJAX, timeout=TIMEOUT)
    r.raise_for_status()
    try:
        return bool(r.json().get("setProject", True))
    except ValueError:
        return r.ok


def purchase_orders(s: requests.Session) -> list[str]:
    """POs del proyecto activo en sesión."""
    r = s.post(f"{BASE}/Main/GetPurchaseOrders", data="", headers=_AJAX, timeout=TIMEOUT)
    r.raise_for_status()
    try:
        return [str(x.get("id") or x.get("text") or "") for x in r.json()]
    except ValueError:
        return []


def find_project_for_po(s: requests.Session, po: str, hint: str | None = None) -> str:
    """Proyecto al que pertenece el PO. Prueba primero `hint` (los 5 dígitos del
    transmittal) y, si no cuadra, recorre el resto de proyectos del usuario."""
    codes = [c for c, _ in projects(s)]
    order = ([hint] if hint in codes else []) + [c for c in codes if c != hint]
    for code in order:
        if select_project(s, code) and po in purchase_orders(s):
            return code
    raise LookupError(f"El PO {po} no aparece en ningún proyecto de eGesDoc para este usuario")


def enter_po(s: requests.Session, project: str, po: str) -> None:
    """Equivale a pulsar «Open» en la tarjeta del PO: deja el PO activo en sesión."""
    select_project(s, project)
    r = s.get(f"{BASE}/Main/SelectPurchaseOrder", params={"project": project, "purchaseOrder": po},
              timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    if "/Supplier/" not in r.url:
        raise RuntimeError(f"eGesDoc no abrió el PO {po} (respuesta: {r.url})")


# ── Transmittals ──────────────────────────────────────────────────────────────

def _json_date(value) -> datetime | None:
    m = re.search(r"/Date\((-?\d+)", str(value or ""))
    return datetime.fromtimestamp(int(m.group(1)) / 1000) if m else None


def list_transmittals(s: requests.Session) -> list[dict]:
    """Transmittals del PO activo: [{id, code, date, documents, remarks}]."""
    data = {"draw": 1, "start": 0, "length": 2000, "search[value]": "", "search[regex]": "false",
            "order[0][column]": 1, "order[0][dir]": "desc"}
    r = s.post(f"{BASE}/Supplier/Transmittal/GetTransmittals", data=data,
               headers={**_AJAX, "Referer": f"{BASE}/Supplier/Transmittal"}, timeout=TIMEOUT)
    r.raise_for_status()
    rows = r.json().get("data") or []
    return [{
        "id": row.get("Id"),
        "code": (row.get("Transmittal") or "").strip(),
        "date": _json_date(row.get("RegisterDate")),
        "documents": row.get("DocumentCount"),
        "remarks": row.get("Remarks") or "",
    } for row in rows]


def transmittal_documents(s: requests.Session, transmittal_id: int) -> list[dict]:
    """Documentos de un transmittal: [{id, vendor_number, tr_number, vendor_rev, tr_rev, title, status}]."""
    r = s.post(f"{BASE}/Supplier/Transmittal/GetReturnedDocumentsByTransmittal",
               data={"returnId": transmittal_id},
               headers={**_AJAX, "Referer": f"{BASE}/Supplier/Transmittal"}, timeout=TIMEOUT)
    r.raise_for_status()
    return [{
        "id": d.get("Id"),
        "vendor_number": (d.get("VendorNumber") or "").strip(),
        "tr_number": (d.get("TrNumber") or "").strip(),
        "vendor_rev": d.get("VendorRev"), "tr_rev": d.get("TrRev"),
        "title": d.get("VendorTitle") or "", "status": d.get("ReturnStatus") or "",
    } for d in (r.json().get("data") or [])]


def document_filename(s: requests.Session, document_id: int) -> str:
    """Nombre del fichero de un documento devuelto, SIN descargarlo: se pide la
    exportación y se leen solo las cabeceras de la descarga."""
    r = s.post(f"{BASE}/Supplier/Documents/DownloadDocumentAjax", data={"id": document_id},
               headers={**_AJAX, "Referer": f"{BASE}/Supplier/Transmittal"}, timeout=DOWNLOAD_TIMEOUT)
    r.raise_for_status()
    try:
        if not r.json().get("result"):
            return ""
    except ValueError:
        return ""
    r = s.get(f"{BASE}/Supplier/Documents/DownloadExportedDocument", timeout=DOWNLOAD_TIMEOUT, stream=True)
    try:
        return http.filename_from_headers(r.headers) if r.ok else ""
    finally:
        r.close()


def transmittal_file_map(po: str, code: str, *, project_hint: str | None = None,
                         session: requests.Session | None = None) -> dict[str, dict]:
    """{nombre de fichero en el zip → {vendor_number, tr_number}}.

    Los ficheros del zip de eGesDoc llevan el id interno de TR (AD-3000-Q-96517.pdf),
    que no figura ni en el correo ni en el detalle: se consulta el nombre de cada
    documento para poder archivarlo en su carpeta dev. correcta.
    """
    own = session is None
    s = session or login()
    out: dict[str, dict] = {}
    try:
        project = find_project_for_po(s, po, hint=project_hint)
        enter_po(s, project, po)
        match = next((t for t in list_transmittals(s) if t["code"].upper() == code.upper()), None)
        if match is None:
            return out
        for d in transmittal_documents(s, match["id"]):
            try:
                name = document_filename(s, d["id"])
            except Exception as exc:  # noqa: BLE001 — un doc sin nombre no debe tumbar el resto
                logger.info("eGesDoc: sin nombre de fichero para %s: %s", d["vendor_number"], exc)
                name = ""
            if name:
                out[name] = {"vendor_number": d["vendor_number"], "tr_number": d["tr_number"]}
    finally:
        if own:
            s.close()
    return out


def download_transmittal(po: str, code: str, dest_dir: Path | str, *,
                         project_hint: str | None = None,
                         session: requests.Session | None = None) -> Path:
    """Descarga el zip del transmittal `code` del PO `po` en `dest_dir`.

    Devuelve la ruta del zip. Si se pasa `session` (ya logada) se reutiliza y no
    se cierra; si no, se abre y cierra una sesión propia.
    """
    own = session is None
    s = session or login()
    try:
        project = find_project_for_po(s, po, hint=project_hint)
        enter_po(s, project, po)
        rows = list_transmittals(s)
        match = next((t for t in rows if t["code"].upper() == code.upper()), None)
        if match is None:
            raise LookupError(f"El transmittal {code} no está en el PO {po} (el portal lista {len(rows)})")

        # El portal a veces contesta 500 de forma transitoria al preparar el zip
        # (p. ej. si aún está sirviendo una exportación anterior): se reintenta.
        ok = False
        for attempt in range(1, EXPORT_RETRIES + 1):
            r = s.post(f"{BASE}/Supplier/Transmittal/ExportTransmittal", data={"id": match["id"]},
                       headers={**_AJAX, "Referer": f"{BASE}/Supplier/Transmittal"}, timeout=DOWNLOAD_TIMEOUT)
            if r.status_code < 500:
                r.raise_for_status()
                try:
                    ok = bool(r.json().get("result"))
                except ValueError:
                    ok = False
                break
            logger.info("eGesDoc: ExportTransmittal %s devolvió %s (intento %d/%d)",
                        code, r.status_code, attempt, EXPORT_RETRIES)
            time.sleep(3 * attempt)
        if not ok:
            raise RuntimeError(f"eGesDoc no pudo preparar el zip de {code} (HTTP {r.status_code})")

        r = s.get(f"{BASE}/Supplier/Transmittal/DownloadTransmittal", timeout=DOWNLOAD_TIMEOUT, stream=True)
        r.raise_for_status()
        target = http.save_response(r, dest_dir, f"{code}.zip")
        if not http.is_zip(target):
            target.unlink(missing_ok=True)
            raise RuntimeError("eGesDoc no devolvió un zip (¿sesión caducada o transmittal sin fichero?)")
        logger.info("eGesDoc: %s descargado en %s", code, target)
        return target
    finally:
        if own:
            s.close()
