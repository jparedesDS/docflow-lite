"""Portal Document Space (Hyundai Engineering) — descarga de la devolución.

El correo de «Vendor Data Review Result» trae tres cosas:

· La tabla de documentos devueltos (Type / File Name / Title / Rev.), que
  parsea `docspace_parser`.
· El **transmittal en PDF adjunto** (`<TR>_Cover.pdf`), que es quien dice cómo
  ha quedado cada documento.
· Un botón **Download** con su **contraseña temporal**, los dos escritos en el
  propio correo, que llevan al zip con los PDF comentados.

**La descarga** no es un enlace directo: el botón abre una página que pide la
contraseña, y esa contraseña viaja cifrada con una clave RSA que el servidor da
por sesión. El flujo es el que hace el navegador::

    GET  la página del enlace          → cookie de sesión
    POST /psmail/getEncKey.do          → módulo y exponente RSA de esa sesión
         RSA PKCS#1 v1.5 de la contraseña del correo → hex
    POST /psmail/getDownloadInfo.do    → {bReturn: true} si la contraseña vale
    POST /psmail/downloadFile.do       → el zip

La contraseña es de un solo correo y va en el propio correo (el aviso dice
«Downloadable Period» y «Total Downloadable Count»), así que no es una
credencial de nadie y no se guarda en ningún sitio: se lee del correo cada vez.

**El estado** sale del Cover, y con él la carpeta `dev` en la que acaba cada
PDF. Dos decisiones que explican el código de `estados()`:

· El **significado de cada código se lee del propio PDF**, que trae la leyenda
  impresa («1 : Rejected · 2 : Comments as noted · 3 : Minor comments ·
  4 : No comments · 5 : For information only»). Si Hyundai cambia la
  numeración, se cambia sola; el mapa de respaldo solo entra si no se puede
  leer la leyenda.
· El código de cada documento se busca **anclado al título** que viene en el
  correo. El texto que se saca del PDF pega el estado al final del título y lo
  sigue con el número de la fila siguiente («…ORIFICES2 2 CI VD-…»), así que
  buscar «el último número de la fila» se equivoca de columna.
"""

from __future__ import annotations

import email
import logging
import re
import secrets
from html import unescape
from pathlib import Path

from core.utils import http

logger = logging.getLogger(__name__)

BASE = "https://psmail.hec.co.kr/psmail"
TIMEOUT = 60
DOWNLOAD_TIMEOUT = 600

# Asunto: «[JUS&ICS2-CI0021-HS-EI-T-0039] Vendor Data Review Result for Orifice»
_CODE_RE = re.compile(r"\[([A-Z0-9&]+(?:-[A-Z0-9]+)+)\]", re.I)

# El correo escribe el HTML con comillas simples.
_LINK_RE = re.compile(r"""href=['"]([^'"]*downloadMailFile\.do\?[^'"]+)['"]""", re.I)
_PASS_RE = re.compile(
    r"Download\s*Password.*?<td[^>]*>\s*([A-Za-z0-9]{3,20})\s*</td>", re.S | re.I)
_SEQ_RE = re.compile(r"sEncodedMailSeq=([A-Za-z0-9]+)", re.I)


def parse_subject(subject: str) -> dict:
    """{code} del asunto: el transmittal que va entre corchetes."""
    m = _CODE_RE.search(subject or "")
    return {"code": m.group(1) if m else "", "po": ""}


def download_link(html: str) -> str:
    """URL del botón «Download» del correo ('' si no lo trae)."""
    m = _LINK_RE.search(html or "")
    return unescape(m.group(1)).strip() if m else ""


def download_password(html: str) -> str:
    """Contraseña temporal que el propio correo escribe al lado del botón."""
    m = _PASS_RE.search(html or "")
    return m.group(1).strip() if m else ""


# ── Descarga ──────────────────────────────────────────────────────────────────

def _pkcs1_v15(mensaje: bytes, k: int) -> int:
    """Relleno tipo 2, el mismo que hace la librería jsbn del navegador."""
    hueco = k - len(mensaje) - 3
    if hueco < 8:
        raise ValueError("la contraseña no cabe en el módulo RSA")
    relleno = bytearray()
    while len(relleno) < hueco:
        b = secrets.token_bytes(1)
        if b != b"\x00":
            relleno += b
    return int.from_bytes(b"\x00\x02" + bytes(relleno) + b"\x00" + mensaje, "big")


def _cifrar(password: str, modulo_hex: str, exponente_hex: str) -> str:
    n = int(modulo_hex, 16)
    e = int(exponente_hex, 16)
    c = pow(_pkcs1_v15(password.encode("utf-8"), (n.bit_length() + 7) // 8), e, n)
    h = format(c, "x")
    return h if len(h) % 2 == 0 else "0" + h      # como BigInteger.toString(16)


def download(url: str, password: str, dest_dir: Path | str, code: str) -> Path:
    """Baja el zip de la devolución y lo deja como `<código>.zip`."""
    if not url:
        raise LookupError("El correo de Document Space no trae el botón «Download»")
    if not password:
        raise LookupError("El correo de Document Space no trae la contraseña de descarga")
    m = _SEQ_RE.search(url)
    if not m:
        raise ValueError(f"El enlace de Document Space no tiene el formato esperado: {url[:80]}")
    seq = m.group(1)

    s = http.session()
    try:
        s.get(url, timeout=TIMEOUT).raise_for_status()          # cookie de sesión
        cabeceras = {"X-Requested-With": "XMLHttpRequest", "Referer": url}

        r = s.post(f"{BASE}/getEncKey.do", timeout=TIMEOUT, headers=cabeceras)
        r.raise_for_status()
        clave = r.json()
        if not clave.get("bReturn"):
            raise RuntimeError(f"Document Space no da la clave de cifrado: {clave.get('sErrorMsg') or '?'}")

        cifrada = _cifrar(password, clave["RSAModulus"], clave["RSAExponent"])
        datos = {"sUserPw": cifrada, "sEncodedMailSeq": seq}

        r = s.post(f"{BASE}/getDownloadInfo.do", timeout=TIMEOUT, data=datos, headers=cabeceras)
        r.raise_for_status()
        info = r.json()
        if not info.get("bReturn"):
            raise RuntimeError(
                "Document Space no acepta la contraseña del correo"
                + (f": {info['sErrorMsg']}" if info.get("sErrorMsg") else "")
                + ". Puede que se haya pasado el plazo de descarga.")

        r = s.post(f"{BASE}/downloadFile.do", timeout=DOWNLOAD_TIMEOUT, stream=True,
                   data=datos, headers={"Referer": url})
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "html" in ctype:
            raise RuntimeError("Document Space devolvió una página en vez del fichero")
        destino = http.save_response(r, dest_dir, f"{code}.zip")
    finally:
        s.close()

    if not (http.is_zip(destino) or http.is_pdf(destino)):
        destino.unlink(missing_ok=True)
        raise RuntimeError("Document Space no devolvió un zip ni un PDF")
    final = destino.with_name(f"{code}.zip")
    if http.is_zip(destino) and destino != final:
        destino.replace(final)
        destino = final
    logger.info("Document Space: %s descargado en %s", code, destino)
    return destino


# ── El transmittal adjunto (Cover) ────────────────────────────────────────────

def cover_adjunto(raw_email: bytes) -> tuple[str, bytes] | None:
    """(nombre, contenido) del PDF del transmittal que viene adjunto."""
    msg = email.message_from_bytes(raw_email or b"")
    for parte in msg.walk():
        nombre = parte.get_filename() or ""
        if nombre.lower().endswith(".pdf") and "cover" in nombre.lower():
            carga = parte.get_payload(decode=True)
            if carga:
                return nombre, carga
    return None


# Qué significa cada código, por si no se puede leer la leyenda del PDF. El
# orden importa: «minor comments» y «no comments» llevan dentro la palabra
# «comments», así que se miran antes que ella.
_SIGNIFICADO = (
    ("reject", "Rechazado"),
    ("minor", "Com. Menores"),
    ("no comment", "Aprobado"),
    ("information", "Informativo"),
    ("comment", "Com. Mayores"),
)
ESTADO_POR_CODIGO = {
    "1": "Rechazado", "2": "Com. Mayores", "3": "Com. Menores",
    "4": "Aprobado", "5": "Informativo",
}

_LEYENDA_RE = re.compile(r"\b([1-9])\s*:\s*([A-Za-z][A-Za-z ,./-]{0,40})")


def leyenda(texto_cover: str) -> dict:
    """{código → estado} leído de la leyenda impresa en el propio transmittal."""
    out: dict[str, str] = {}
    for numero, descripcion in _LEYENDA_RE.findall(texto_cover or ""):
        d = descripcion.strip().lower()
        for pista, estado in _SIGNIFICADO:
            if pista in d:
                out.setdefault(numero, estado)
                break
    return out


def _texto_pdf(contenido: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    paginas = PdfReader(BytesIO(contenido)).pages
    return " ".join(" ".join((p.extract_text() or "").split()) for p in paginas)


def estados(cover: bytes, docs: list[dict]) -> dict:
    """{Doc. Cliente → estado} según el transmittal adjunto.

    Cada documento se localiza por su título, que es el que trae el correo: en
    el texto que se saca del PDF el código de estado queda pegado al final del
    título, y justo detrás empieza la fila siguiente.
    """
    texto = _texto_pdf(cover)
    tabla = {**ESTADO_POR_CODIGO, **leyenda(texto)}
    out: dict[str, str] = {}
    for d in docs:
        codigo = str(d.get("Doc. Cliente", "")).strip()
        titulo = " ".join(str(d.get("Título", "")).split())
        if not codigo or not titulo:
            continue
        i = texto.find(titulo)
        if i < 0:
            logger.info("Document Space: el transmittal no menciona «%s»", titulo[:50])
            continue
        m = re.match(r"\s*([1-9])\b", texto[i + len(titulo):])
        if not m:
            continue
        estado = tabla.get(m.group(1), "")
        if estado:
            out[codigo] = estado
        else:
            logger.warning("Document Space: código de estado «%s» desconocido en %s",
                           m.group(1), codigo)
    return out


def docs_con_estado(docs: list[dict], cover: bytes | None) -> list[dict]:
    """Copia de los documentos con el Estado que dice el transmittal.

    Solo rellena lo que está vacío: lo que se haya puesto a mano en la preview
    manda sobre esto.
    """
    if not cover:
        return list(docs)
    try:
        por_codigo = estados(cover, docs)
    except Exception as exc:  # noqa: BLE001 — sin estado se pone a mano, no se cae la descarga
        logger.warning("Document Space: no se pudo leer el transmittal adjunto: %s", exc)
        return list(docs)
    fuera = []
    for d in docs:
        copia = dict(d)
        if not str(copia.get("Estado", "") or "").strip():
            estado = por_codigo.get(str(copia.get("Doc. Cliente", "")).strip(), "")
            if estado:
                copia["Estado"] = estado
        fuera.append(copia)
    return fuera
