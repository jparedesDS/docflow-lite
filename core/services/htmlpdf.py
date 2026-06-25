"""Conversión HTML→PDF de alta fidelidad con wkhtmltopdf (motor WebKit).

Renderiza el HTML tal cual (colores, tablas, bordes redondeados…), de modo que
el PDF salga idéntico al email. Requiere el binario wkhtmltopdf instalado:
  Windows: https://wkhtmltopdf.org/downloads.html  (instalador MSI)

La ruta se resuelve por: pref `wkhtmltopdf_path` → env WKHTMLTOPDF_PATH → PATH →
ubicaciones de instalación por defecto.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile

from core import preferences as pref

logger = logging.getLogger(__name__)

_DEFAULT_PATHS = (
    r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe",
    r"C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe",
)


def binary() -> str | None:
    cand = (pref.get("wkhtmltopdf_path") or os.getenv("WKHTMLTOPDF_PATH") or "").strip()
    if cand and os.path.isfile(cand):
        return cand
    found = shutil.which("wkhtmltopdf")
    if found:
        return found
    for p in _DEFAULT_PATHS:
        if os.path.isfile(p):
            return p
    return None


def available() -> bool:
    return binary() is not None


def html_to_pdf(html: str) -> bytes | None:
    """Convierte un HTML completo a PDF. Devuelve los bytes o None si no está
    wkhtmltopdf o falla la conversión."""
    exe = binary()
    if not exe:
        logger.warning("wkhtmltopdf no encontrado: no se genera PDF "
                       "(instálalo o configura la ruta en Ajustes).")
        return None
    in_path = out_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(html)
            in_path = fh.name
        out_path = in_path[:-5] + ".pdf"
        cmd = [exe, "--quiet", "--encoding", "utf-8", "--enable-local-file-access",
               "--page-size", "A4",
               "--margin-top", "8mm", "--margin-bottom", "8mm",
               "--margin-left", "6mm", "--margin-right", "6mm",
               in_path, out_path]
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        with open(out_path, "rb") as fh:
            return fh.read()
    except Exception as exc:
        logger.warning("wkhtmltopdf falló: %s", exc)
        return None
    finally:
        for p in (in_path, out_path):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
