"""Portal AYESA — descarga de la devolución desde el enlace del propio correo.

Los correos de devolución de AYESA («P03_3630_EIP-2206-300-008: Documentos de
3000005785-2206-3000: …») traen un enlace «Clic aquí para descargar» a
``https://bd.ayesa.com/dashboard/descarga.aspx?ID=…``. No pide usuario: esa
página es un gestor de ficheros (DevExpress ASPxFileManager) que al abrirse
selecciona todos los ficheros y pulsa «Descargar». Aquí se reproduce ese clic:

  1. GET del enlace → HTML con el formulario ASP.NET (__VIEWSTATE…) y la lista de
     ficheros en ``itemsInfo`` (id ``o:<GUID>`` + nombre).
  2. POST del mismo formulario con ``__EVENTTARGET=laLista`` y
     ``__EVENTARGUMENT=DOWNLOAD|[{"name":…,"id":…,"isFolder":false}, …]``
     → el servidor devuelve el zip (o el fichero suelto si solo hay uno; en ese
     caso se empaqueta aquí como ``<código>.zip`` para archivarlo igual).

El servidor de AYESA no envía el certificado intermedio: se valida con el motor
de certificados de Windows (`core.utils.http.session(windows_trust=True)`).
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from html import unescape
from pathlib import Path

from core.utils import http

logger = logging.getLogger(__name__)

TIMEOUT = 60
DOWNLOAD_TIMEOUT = 300
FILE_MANAGER_ID = "laLista"

# "P03_3630_EIP-2206-300-008: Documentos de …" → P03_3630_EIP-2206-300-008
_CODE_RE = re.compile(r"^\s*(P\d+_\d+_EIP-[\dA-Z-]+)\s*:", re.I)
_LINK_RE = re.compile(r'href="([^"]*descarga\.aspx[^"]*)"', re.I)
_INPUT_RE = re.compile(r"<input[^>]*>", re.I)
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
_ITEMS_RE = re.compile(r"'itemsInfo':\{'items':\[(.*?)\]", re.S)
_ITEM_RE = re.compile(r"\{[^{}]*\}")
_PROP_RE = re.compile(r"'(\w+)':'((?:[^'\\]|\\.)*)'")


def parse_subject(subject: str) -> str:
    """Código de la devolución (primer token del asunto) o ''."""
    m = _CODE_RE.match(subject or "")
    return m.group(1) if m else ""


def download_link(html: str) -> str:
    """URL del enlace de descarga del correo, o ''."""
    m = _LINK_RE.search(html or "")
    return unescape(m.group(1)).strip() if m else ""


# ── Página del gestor de ficheros ─────────────────────────────────────────────

def _form_fields(page: str) -> dict:
    """Campos del formulario ASP.NET (hidden y texto, con su valor actual)."""
    fields: dict = {}
    for tag in _INPUT_RE.findall(page):
        attrs = dict(_ATTR_RE.findall(tag))
        name = attrs.get("name")
        if not name or attrs.get("type", "text").lower() in ("file", "submit", "button", "image", "checkbox", "radio"):
            continue
        fields[name] = unescape(attrs.get("value", ""))
    return fields


def _js_unescape(value: str) -> str:
    try:
        return json.loads('"' + value.replace('"', '\\"') + '"')
    except ValueError:
        return value


def _current_folder(page: str) -> str:
    m = re.search(r"'currentFolderId':'([^']+)'", page)
    return m.group(1) if m else "o:1"


def list_files(page: str) -> list[dict]:
    """Ficheros que ofrece la página: [{id, name}] (solo entradas de tipo File)."""
    m = _ITEMS_RE.search(page)
    if not m:
        return []
    out = []
    for chunk in _ITEM_RE.findall(m.group(1)):
        props = {k: _js_unescape(v) for k, v in _PROP_RE.findall(chunk)}
        if props.get("it", "File") == "File" and props.get("id") and props.get("n"):
            out.append({"id": props["id"], "name": props["n"]})
    return out


def download(url: str, dest_dir: Path | str, code: str) -> Path:
    """Reproduce el «Descargar» del gestor de ficheros y guarda el resultado en
    `dest_dir` (zip con todos los ficheros, o el fichero suelto si es uno)."""
    s = http.session(windows_trust=True)
    try:
        r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        page = r.text
        files = list_files(page)
        if not files:
            raise RuntimeError("AYESA no muestra ficheros para descargar (¿enlace caducado?)")
        fields = _form_fields(page)
        if "__VIEWSTATE" not in fields:
            raise RuntimeError("La página de descarga de AYESA no tiene el formato esperado")
        # Mismo postback que hace el JS: TryDownload → GetArgumentsString("DOWNLOAD",
        # {items: [...]}) + campo oculto de estado (name = id del control).
        fields["__EVENTTARGET"] = FILE_MANAGER_ID
        fields["__EVENTARGUMENT"] = "DOWNLOAD|" + json.dumps(
            {"items": [{"name": f["name"], "id": f["id"], "isFolder": False} for f in files]},
            separators=(",", ":"), ensure_ascii=False)
        fields[FILE_MANAGER_ID] = json.dumps({"currentPath": "", "currentIdPath": [_current_folder(page)]},
                                             separators=(",", ":"))
        r = s.post(r.url, data=fields, headers={"Referer": r.url}, timeout=DOWNLOAD_TIMEOUT, stream=True)
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "text/html" in ctype:
            raise RuntimeError("AYESA devolvió una página en vez del fichero (¿enlace caducado?)")
        default = f"{code}.zip" if len(files) > 1 else files[0]["name"]
        target = http.save_response(r, dest_dir, default)
    finally:
        s.close()
    if not (http.is_zip(target) or http.is_pdf(target)):
        target.unlink(missing_ok=True)
        raise RuntimeError("AYESA no devolvió un zip ni un PDF (¿enlace caducado?)")
    target = _as_code_zip(target, code)
    logger.info("AYESA: %s descargado en %s (%d fichero(s))", code, target, len(files))
    return target


def _as_code_zip(path: Path, code: str) -> Path:
    """Deja el resultado como `<código>.zip`, igual que se archivaba a mano: si
    el portal devolvió un fichero suelto (un solo documento) se empaqueta; si
    devolvió un zip con otro nombre, se renombra."""
    final = path.with_name(f"{code}.zip")
    if http.is_zip(path):
        if path != final:
            path.replace(final)
        return final
    with zipfile.ZipFile(final, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(path, arcname=path.name)
    path.unlink(missing_ok=True)
    return final
