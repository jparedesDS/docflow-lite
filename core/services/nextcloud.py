"""Subida de informes a Nextcloud/ownCloud vía enlace público con permiso de
subida, para obtener una URL http clicable (Teams, email…).

Configurar en Ajustes ▸ Fuentes de datos el «Enlace público de Nextcloud»
(p.ej. https://data.eipsa.es/index.php/s/TOKEN). El recurso compartido debe
tener activado «Permitir subir y editar».

Si el enlace tiene contraseña, ponla en la variable de entorno
NEXTCLOUD_SHARE_PASS (en .env, nunca en preferencias en claro).

Sin dependencias externas: usa urllib (stdlib) + WebDAV público.
"""

from __future__ import annotations

import base64
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from core import preferences as pref

logger = logging.getLogger(__name__)


def _share_url() -> str:
    return (pref.get("nextcloud_share_url") or os.getenv("NEXTCLOUD_SHARE_URL", "") or "").strip()


def is_configured() -> bool:
    return bool(_share_url())


def _parse_share(share_url: str) -> tuple[str, str] | None:
    """De 'https://host/index.php/s/TOKEN' → ('https://host', 'TOKEN')."""
    try:
        p = urllib.parse.urlparse(share_url)
        if not p.scheme or not p.netloc:
            return None
        base = f"{p.scheme}://{p.netloc}"
        segs = [s for s in p.path.split("/") if s]
        token = segs[segs.index("s") + 1] if "s" in segs else segs[-1]
        return base, token
    except Exception:
        return None


def upload_report(filename: str, content: str) -> str | None:
    """Sube el HTML al recurso compartido y devuelve una URL http de descarga,
    o None si no hay configuración o falla."""
    share_url = _share_url()
    if not share_url:
        return None
    parsed = _parse_share(share_url)
    if not parsed:
        logger.warning("Enlace de Nextcloud no válido: %s", share_url)
        return None
    base, token = parsed
    pwd = os.getenv("NEXTCLOUD_SHARE_PASS", "")
    safe = filename.replace("/", "_").replace("\\", "_")
    put_url = f"{base}/public.php/webdav/{urllib.parse.quote(safe)}"
    auth = base64.b64encode(f"{token}:{pwd}".encode()).decode()
    req = urllib.request.Request(
        put_url, data=content.encode("utf-8"), method="PUT",
        headers={"Authorization": f"Basic {auth}",
                 "Content-Type": "text/html; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.getcode()
        if not (200 <= code < 300):
            logger.warning("Nextcloud PUT HTTP %s", code)
            return None
    except urllib.error.HTTPError as exc:
        logger.warning("Nextcloud PUT HTTP %s: %s (¿permite subir el recurso "
                       "compartido?)", exc.code, exc.reason)
        return None
    except Exception as exc:
        logger.warning("Error subiendo a Nextcloud: %s", exc)
        return None
    return (f"{base}/index.php/s/{token}/download?path=%2F&files="
            + urllib.parse.quote(safe))
