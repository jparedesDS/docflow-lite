"""Portal PRODOC (Wood) — descarga de la devolución desde el enlace del correo.

Los transmittals de Wood («Wood Transmittal TL-…-VDC-nnnn - … - PO: …») traen al
pie de la tabla de documentos dos enlaces que no piden usuario ni contraseña,
solo un token:

    Download All 1st Files       → …/VndrDocs/DistributionVndr/vndDownloadZIPMail.cfm?<token>
    Download All 1st+2nd Files   → …/VndrDocs/DistributionVndr/vndDownloadZIPMail.cfm?<otro token>

Se usa el primero: el «1st file» es el PDF devuelto, que es justo lo que se
archiva en las carpetas `dev.`; el «2nd file» es el fichero nativo que mandó
EIPSA (dwg, xls…) y no pinta nada en la devolución. Si el correo solo trae el
segundo enlace, se tira de ese.

Dentro del zip los ficheros van con el código del documento tal cual
(`V-23BLFE01A-2206-400-10TE1501-DWG-001.PDF`), que es el mismo «Doc. Cliente»
de la tabla del correo, así que el archivado los empareja sin ayuda de ningún
mapa —al revés que en eGesDoc, donde hay que preguntarle al portal.

**Los enlaces caducan** (el propio correo lo dice: «The links to electronic
files will expire on …», al mes). Pasada esa fecha el portal no da un error HTTP:
contesta 200 con una página que pone «Error Executing Database Query». Por eso
aquí se mira lo que llega y se avisa en cristiano en vez de guardar un HTML con
la extensión cambiada.
"""

from __future__ import annotations

import logging
import re
import time
import zipfile
from html import unescape
from pathlib import Path

from core.utils import http

logger = logging.getLogger(__name__)

TIMEOUT = 60
DOWNLOAD_TIMEOUT = 600

# El portal no tiene el zip hecho: al pedirlo lanza la generación y contesta una
# página con «alert('Transmittal file process running, please try it again in a
# few minutes.')». Hay que volver a pedirlo hasta que lo sirva, igual que en
# eGesDoc con su exportación. Ojo: con un enlace ya caducado el portal contesta
# ESE MISMO mensaje y no para nunca (comprobado con transmittals de 2024 y 2025,
# cuyo enlace por documento sí dice «This link has expired!»), así que al agotar
# los intentos hay que nombrar las dos posibilidades.
ZIP_RETRIES = 8
ZIP_WAIT = 30

# Asunto: «Wood Transmittal TL-2401HG04A-VDC-6294 - … - PO: 7011419725 - Vendor: …»
_CODE_RE = re.compile(r"\b(TL-[A-Z0-9]+-VDC-\d{3,6})\b", re.I)
_PO_RE = re.compile(r"\bPO\s*:?\s*(\d{6,12})\b", re.I)

# Los dos enlaces del pie, con el texto que los rotula.
_ZIP_LINK_RE = re.compile(
    r'<a\s[^>]*href="([^"]*vndDownloadZIPMail\.cfm\?[^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_SOLO_1RA = re.compile(r"1st\s*files", re.I)

_ALERT_RE = re.compile(r"alert\s*\(\s*'([^']*)'", re.I)
_PREPARANDO_RE = re.compile(r"process\s+running|try\s+it\s+again", re.I)
_CADUCADO_RE = re.compile(r"link\s+has\s+expired|error\s+executing\s+database\s+query", re.I)


def parse_subject(subject: str) -> dict:
    """{code, po} del asunto de un transmittal de Wood."""
    code = _CODE_RE.search(subject or "")
    po = _PO_RE.search(subject or "")
    return {"code": code.group(1).upper() if code else "",
            "po": po.group(1) if po else ""}


def download_link(html: str) -> str:
    """URL del «Download All 1st Files» del correo ('' si el correo no trae zip).

    Si solo está el «1st+2nd», se devuelve ese: mejor de más que nada.
    """
    enlaces = [(unescape(url).strip(), re.sub(r"<[^>]+>", "", texto))
               for url, texto in _ZIP_LINK_RE.findall(html or "")]
    if not enlaces:
        return ""
    for url, texto in enlaces:
        if _SOLO_1RA.search(texto) and "2nd" not in texto.lower():
            return url
    return enlaces[0][0]


def has_download(html: str) -> bool:
    """¿Este correo trae algo que descargar?

    Los avisos de documentos subidos «para información» (`2I - FOR INFORMATION
    ONLY`) llegan sin ningún enlace: no hay nada que bajar y no es un fallo.
    """
    return bool(download_link(html))


def download(url: str, dest_dir: Path | str, code: str) -> Path:
    """Baja el zip del transmittal a `dest_dir` y lo deja como `<código>.zip`.

    El zip no está hecho de antemano: la primera petición dispara la generación
    y contesta una página pidiendo que se reintente, así que se insiste hasta
    `ZIP_RETRIES` veces esperando `ZIP_WAIT` segundos.
    """
    s = http.session()
    espera = ""
    try:
        for intento in range(1, ZIP_RETRIES + 1):
            r = s.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True, allow_redirects=True)
            r.raise_for_status()
            ctype = (r.headers.get("Content-Type") or "").lower()
            if not ("html" in ctype or "text/" in ctype):
                target = http.save_response(r, dest_dir, f"{code}.zip")
                break
            pagina = r.text
            r.close()
            if not _PREPARANDO_RE.search(pagina):
                raise RuntimeError(_por_que(pagina))
            espera = _mensaje(pagina)
            logger.info("PRODOC: %s aún se está preparando (%d/%d)", code, intento, ZIP_RETRIES)
            if intento < ZIP_RETRIES:
                time.sleep(ZIP_WAIT)
        else:
            raise RuntimeError(
                f"PRODOC no ha soltado el paquete en {ZIP_RETRIES * ZIP_WAIT // 60} "
                f"minutos: sigue diciendo «{espera or 'sin mensaje'}». O el portal "
                "está ocupado y hay que reintentar dentro de un rato, o el enlace "
                "del correo ya ha caducado (caducan al mes) y habrá que bajarlo a "
                "mano desde el portal de Wood.")
    finally:
        s.close()

    if not (http.is_zip(target) or http.is_pdf(target)):
        target.unlink(missing_ok=True)
        raise RuntimeError("PRODOC no devolvió un zip ni un PDF; el enlace del correo "
                           "puede haber caducado (caducan al mes)")
    target = _as_code_zip(target, code)
    logger.info("PRODOC: %s descargado en %s", code, target)
    return target


def _mensaje(pagina: str) -> str:
    """El texto del `alert(...)` de la página, o la página sin etiquetas."""
    m = _ALERT_RE.search(pagina or "")
    if m:
        return m.group(1).strip()
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", pagina or "")).strip()


def _por_que(pagina: str) -> str:
    """Motivo en cristiano cuando el portal contesta una página en vez del zip."""
    texto = _mensaje(pagina)
    if _CADUCADO_RE.search(texto):
        return ("El enlace de descarga del correo ya no vale: los de PRODOC caducan "
                "al mes. Hay que bajarlo a mano desde el portal de Wood.")
    return f"PRODOC devolvió una página en vez del zip: {texto[:160] or 'sin mensaje'}"


def _as_code_zip(path: Path, code: str) -> Path:
    """Deja el resultado como `<código>.zip`: si vino un PDF suelto se empaqueta,
    y si el zip trae otro nombre (el portal le pone `_1`/`_2`) se renombra."""
    final = path.with_name(f"{code}.zip")
    if http.is_zip(path):
        if path != final:
            path.replace(final)
        return final
    with zipfile.ZipFile(final, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(path, arcname=path.name)
    path.unlink(missing_ok=True)
    return final
