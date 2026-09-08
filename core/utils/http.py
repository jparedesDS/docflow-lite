"""Utilidades HTTP compartidas por los portales de cliente (eGesDoc, AYESA…).

· `session()` — sesión `requests` con User-Agent propio. Con `windows_trust=True`
  valida los certificados con el motor de Windows (vía `truststore`), igual que
  Chrome: hace falta con servidores que no envían el certificado intermedio
  (p. ej. bd.ayesa.com), que el almacén de certifi no puede resolver. Si
  `truststore` no está instalado se usa la validación estándar (nunca se
  desactiva la verificación).
· `filename_from_headers()` — nombre de fichero del Content-Disposition.
· `save_response()` — vuelca una respuesta a disco de forma atómica (tmp+replace).
"""

from __future__ import annotations

import os
import re
import ssl
from html import unescape
from pathlib import Path
from urllib.parse import unquote

import requests
from requests.adapters import HTTPAdapter

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DocFlowLite/1.0"
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def ssl_context(windows_trust: bool = True) -> ssl.SSLContext:
    if windows_trust:
        try:
            import truststore
            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except ImportError:
            pass
    return ssl.create_default_context()


class _TrustAdapter(HTTPAdapter):
    def __init__(self, context: ssl.SSLContext, **kwargs):
        self._context = context
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._context
        return super().init_poolmanager(*args, **kwargs)


def session(windows_trust: bool = False) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"})
    if windows_trust:
        s.mount("https://", _TrustAdapter(ssl_context(True)))
    return s


def filename_from_headers(headers) -> str:
    cd = headers.get("Content-Disposition", "") or ""
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
    name = unescape(m.group(1)).strip().strip('"') if m else ""
    if "%" in name:
        name = unquote(name)           # algunos servidores lo mandan URL-codificado
    name = os.path.basename(name.replace("\\", "/"))
    return _BAD_CHARS.sub("_", name)


def save_response(response: requests.Response, dest_dir: Path | str, default_name: str) -> Path:
    """Guarda el cuerpo de `response` (en streaming) en `dest_dir`, con el nombre
    del Content-Disposition o `default_name`. Escritura atómica."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / (filename_from_headers(response.headers) or default_name)
    tmp = target.with_suffix(target.suffix + ".part")
    with open(tmp, "wb") as fh:
        for chunk in response.iter_content(1 << 16):
            if chunk:
                fh.write(chunk)
    os.replace(tmp, target)
    return target


def _magic(path: Path | str, n: int) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(n)
    except OSError:
        return b""


def is_zip(path: Path | str) -> bool:
    return _magic(path, 2) == b"PK"


def is_pdf(path: Path | str) -> bool:
    return _magic(path, 4) == b"%PDF"
