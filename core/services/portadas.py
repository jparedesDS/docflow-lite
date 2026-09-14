"""Generar las portadas de los documentos a partir de las plantillas del cliente.

Una portada puede necesitar **varias plantillas encadenadas**. La de Técnicas
Reunidas, por ejemplo, son dos ficheros que acaban en un solo PDF de tres
páginas: la hoja de estado (`AD-3000-G-00138-Tmp01.docx`, con las casillas de
REJECTED / REVIEWED / VOID) y la cover sheet (`VENDOR WORD DOCUMENT
TEMPLATE.docx`, con la hoja de control de revisiones detrás). La de WOOD, en
cambio, es una sola página.

El paso a PDF lo hace Word por COM, que es el único que respeta del todo el
formato del cliente —logos, tipografías y cajas— y está en todos los equipos
del departamento. Unir los PDF es cosa de `pypdf`: el Excel de portadas viejo
llamaba a Adobe Acrobat para esto, que es justo la parte que fallaba cuando
Acrobat no estaba abierto o se quedaba colgado.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from core.utils import files

logger = logging.getLogger(__name__)

# Word tarda ~5 s en arrancar; si hay que generar cincuenta portadas conviene
# abrirlo una vez y no una por documento (ver `Word` más abajo).
PDF_FORMAT = 17            # wdExportFormatPDF


class Word:
    """Word abierto una sola vez para convertir varios documentos a PDF.

    Se usa como gestor de contexto para que la instancia se cierre pase lo que
    pase: un Word invisible que se queda vivo es un proceso zombi que bloquea
    ficheros y se nota en el siguiente arranque.
    """

    def __init__(self) -> None:
        self._word = None
        self._com = None

    def __enter__(self) -> "Word":
        import pythoncom
        import win32com.client as win32

        self._com = pythoncom
        pythoncom.CoInitialize()
        self._word = win32.DispatchEx("Word.Application")
        self._word.Visible = False
        self._word.DisplayAlerts = 0
        return self

    def __exit__(self, *_exc) -> None:
        try:
            if self._word is not None:
                self._word.Quit()
        except Exception:  # noqa: BLE001 — cerrar Word nunca debe tapar el error real
            logger.debug("Word no cerró limpiamente", exc_info=True)
        finally:
            self._word = None
            if self._com is not None:
                self._com.CoUninitialize()
                self._com = None

    def a_pdf(self, docx: Path | str, pdf: Path | str | None = None) -> Path:
        """Exporta un .docx (o .xlsx abierto por Word) a PDF."""
        origen = Path(docx).resolve()
        destino = Path(pdf).resolve() if pdf else origen.with_suffix(".pdf")
        destino.parent.mkdir(parents=True, exist_ok=True)
        doc = self._word.Documents.Open(str(origen), ReadOnly=True, AddToRecentFiles=False)
        try:
            doc.ExportAsFixedFormat(str(destino), PDF_FORMAT)
        finally:
            doc.Close(False)
        return destino


def a_pdf(docx: Path | str, pdf: Path | str | None = None) -> Path:
    """Un solo documento a PDF (abre y cierra Word)."""
    with Word() as w:
        return w.a_pdf(docx, pdf)


def unir(pdfs: list[Path | str], destino: Path | str) -> Path:
    """Junta varios PDF en uno, en el orden dado."""
    from pypdf import PdfWriter

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    escritor = PdfWriter()
    try:
        for p in pdfs:
            escritor.append(str(p))
        tmp = files.libre(destino.with_suffix(destino.suffix + ".part"))
        with open(tmp, "xb") as fh:
            escritor.write(fh)
        destino = files.mover(tmp, destino)
    finally:
        escritor.close()
    return destino


def generar(plantillas: list[Path | str], destino: Path | str,
            valores: dict | None = None, marcas: dict | None = None,
            word: Word | None = None) -> Path:
    """La portada de un documento: rellena las plantillas y deja un solo PDF.

    `valores` son las etiquetas de las tablas «ETIQUETA : valor» y `marcas` los
    marcadores `{{…}}`; se pasan tal cual a cada plantilla, que coge lo suyo.
    Si se va a generar más de una portada conviene pasar un `Word` ya abierto.
    """
    from core.services import plantilla_docx

    destino = Path(destino)
    tmp = Path(tempfile.mkdtemp(prefix="portada_"))
    try:
        pdfs = []
        for i, plantilla in enumerate(plantillas):
            plantilla = Path(plantilla)
            relleno = plantilla_docx.rellenar(
                plantilla, tmp / f"{i:02d}_{plantilla.stem}.docx", valores, marcas)
            pdfs.append((word.a_pdf(relleno) if word is not None else a_pdf(relleno)))
        if not pdfs:
            raise ValueError("No hay ninguna plantilla con la que hacer la portada")
        destino = files.libre(destino)      # una portada ya hecha no se pisa
        if len(pdfs) == 1:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdfs[0], destino)
        else:
            unir(pdfs, destino)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    logger.info("Portada generada: %s (%d plantilla(s))", destino, len(plantillas))
    return destino
