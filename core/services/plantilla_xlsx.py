"""Rellenar las plantillas de portada que el cliente manda en Excel.

Es el hermano de `plantilla_docx`, para los clientes cuya portada es una hoja de
cálculo. La de MOEVE lo es: las que hay archivadas a mano llevan escrito
«Acrobat PDFMaker for Excel» en sus propiedades.

Aquí solo se trabaja con **marcadores** `{{…}}`, no con etiquetas. En un Word la
tabla «ETIQUETA : valor» se lee sola porque las celdas están una al lado de la
otra; en Excel la portada es un dibujo de celdas combinadas donde el valor tan
pronto está a la derecha como dos filas más abajo, y adivinarlo sería
adivinarlo. Se escribe una vez en la plantilla dónde va cada dato:

    N° DOCUMENTO:  {{DOC CLIENTE}}        ITEM-TAG:  {{TAG}}

**Se edita como ZIP**, igual que la plantilla de Planning y por el mismo motivo:
`openpyxl` reescribe el libro entero y por el camino se deja logos, formatos
condicionales y cajas de dibujo — justo lo que hace que la portada sea la del
cliente. Aquí solo se toca el texto y todo lo demás se copia byte a byte.

El texto de una hoja vive en dos sitios: la tabla común `xl/sharedStrings.xml`
(lo normal) y, cuando el libro viene de otra herramienta, dentro de la propia
celda (`<is>`). Se miran los dos.
"""

from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from core.services.plantilla_docx import _clave_marca, _registrar_prefijos, _serializar

logger = logging.getLogger(__name__)

_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_PARTES = re.compile(r"^xl/(sharedStrings\.xml|worksheets/sheet\d+\.xml)$")
_MARCA = re.compile(r"\{\{\s*([^{}]{1,60}?)\s*\}\}")


def _s(tag: str) -> str:
    return "{%s}%s" % (_S, tag)


def _cadenas(raiz):
    """Los bloques de texto de la parte: cada `<si>` (tabla común) o `<is>`
    (texto metido en la celda). Un bloque puede venir partido en varios `<r>`
    si el cliente puso una palabra en negrita."""
    for etiqueta in ("si", "is"):
        yield from raiz.iter(_s(etiqueta))


def _texto(bloque) -> str:
    return "".join(t.text or "" for t in bloque.iter(_s("t")))


def marcadores(plantilla: Path | str) -> list[str]:
    """Marcadores `{{…}}` escritos en la plantilla, sin repetir."""
    out: list[str] = []
    vistos: set[str] = set()
    with zipfile.ZipFile(plantilla) as z:
        for parte in [n for n in z.namelist() if _PARTES.match(n)]:
            raiz = ET.fromstring(z.read(parte))
            for bloque in _cadenas(raiz):
                for nombre in _MARCA.findall(_texto(bloque)):
                    clave = _clave_marca(nombre)
                    if clave not in vistos:
                        vistos.add(clave)
                        out.append(nombre.strip())
    return out


def _sustituir(raiz, valores: dict) -> bool:
    """Cambia los `{{…}}` de la parte. Devuelve si tocó algo."""
    tocado = False
    for bloque in _cadenas(raiz):
        entero = _texto(bloque)
        if "{{" not in entero:
            continue
        nuevo = _MARCA.sub(
            lambda m: valores.get(_clave_marca(m.group(1)), m.group(0)), entero)
        if nuevo == entero:
            continue
        # El marcador puede estar repartido en varios trozos: se junta todo en
        # el primer `<t>` —que es el que lleva el formato— y los demás se vacían
        # (quitarlos rompería la numeración de `<r>` que Excel espera).
        textos = list(bloque.iter(_s("t")))
        if not textos:
            continue
        textos[0].text = nuevo
        textos[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        for extra in textos[1:]:
            extra.text = ""
        tocado = True
    return tocado


def rellenar(plantilla: Path | str, destino: Path | str, marcas: dict | None = None) -> Path:
    """Copia la plantilla a `destino` con los marcadores sustituidos."""
    quiere = {_clave_marca(k): str(v) for k, v in (marcas or {}).items()}
    destino = Path(destino)
    with zipfile.ZipFile(plantilla) as z:
        orden = z.namelist()
        partes = {n: z.read(n) for n in orden}

    for nombre in [n for n in orden if _PARTES.match(n)]:
        crudo = partes[nombre]
        if b"{{" not in crudo:
            continue
        _registrar_prefijos(crudo)
        raiz = ET.fromstring(crudo)
        if _sustituir(raiz, quiere):
            partes[nombre] = _serializar(raiz, crudo)

    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre in orden:
            z.writestr(nombre, partes[nombre])
    logger.debug("Plantilla Excel rellenada: %s", destino.name)
    return destino
