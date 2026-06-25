"""Conversión HTML→PDF para que el informe salga como el email.

Dos motores, por orden de fidelidad:
  1. wkhtmltopdf (binario WebKit): PDF idéntico al email (bordes redondeados,
     sombras, todo). Windows MSI: https://wkhtmltopdf.org/downloads.html
  2. xhtml2pdf (librería pip, sin binario): fallback puro Python; reproduce
     estructura, colores y tablas, pero pierde detalles CSS (radios, sombras).

`html_to_pdf` usa wkhtmltopdf si está disponible y, si no, xhtml2pdf.
La ruta de wkhtmltopdf se resuelve por: pref `wkhtmltopdf_path` →
env WKHTMLTOPDF_PATH → PATH → ubicaciones de instalación por defecto.
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


def _xhtml2pdf_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("xhtml2pdf") is not None


def available() -> bool:
    return binary() is not None or _xhtml2pdf_available()


def _wkhtmltopdf(html: str, exe: str) -> bytes | None:
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


def _xhtml2pdf(html: str) -> bytes | None:
    try:
        from io import BytesIO

        from xhtml2pdf import pisa
        out = BytesIO()
        status = pisa.CreatePDF(src=html, dest=out, encoding="utf-8")
        if status.err:
            logger.warning("xhtml2pdf devolvió %s error(es)", status.err)
            return None
        return out.getvalue()
    except Exception as exc:
        logger.warning("xhtml2pdf falló: %s", exc)
        return None


def html_to_pdf(html: str) -> bytes | None:
    """Convierte un HTML completo a PDF (wkhtmltopdf si está; si no, xhtml2pdf).
    Devuelve los bytes o None si no hay ningún motor disponible."""
    exe = binary()
    if exe:
        pdf = _wkhtmltopdf(html, exe)
        if pdf:
            return pdf
    pdf = _xhtml2pdf(html)
    if pdf:
        return pdf
    logger.warning("No hay motor HTML→PDF (instala wkhtmltopdf o `pip install "
                   "xhtml2pdf`): no se genera PDF.")
    return None
