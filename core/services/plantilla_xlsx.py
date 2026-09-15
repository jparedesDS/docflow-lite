"""Rellenar las plantillas de portada que el cliente manda en Excel.

Es el hermano de `plantilla_docx`, para los clientes cuya portada es una hoja de
cálculo. La de MOEVE lo es: las que hay archivadas a mano llevan escrito
«Acrobat PDFMaker for Excel» en sus propiedades.

Se rellena de las dos maneras, como en Word:

· **Etiquetas**, cuando la portada es una tabla de «ETIQUETA : valor» repartida
  en celdas —la de MOEVE lo es: `A2 CLIENT :` y al lado `B2 MOEVE - ONUBA…`—.
  Se leen solas y no hay que tocar la plantilla.
· **Marcadores** `{{…}}` para las que no lo son: portadas que son un dibujo de
  celdas combinadas donde el valor tan pronto está a la derecha como dos filas
  más abajo. Ahí se escribe una vez en la plantilla dónde va cada dato:

      N° DOCUMENTO:  {{DOC CLIENTE}}        ITEM-TAG:  {{TAG}}

El valor se escribe **dentro de la celda** (`inlineStr`) y no en la tabla común
de cadenas, que la comparten todas las hojas: cambiar ahí una entrada usada en
dos sitios cambiaría los dos.

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
_HOJA = re.compile(r"^xl/worksheets/sheet\d+\.xml$")
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


# -- Etiquetas «ETIQUETA : valor» ---------------------------------------------
#
# Muchas portadas de Excel son la misma tabla que las de Word, solo que en
# celdas: la etiqueta en una columna y el valor en la de al lado.
#
#     A2  CLIENT          :     B2  MOEVE - ONUBA SUSTAINABLE FUEL
#     A12 VENDOR DOC. N.  :     B12 26-062-DL-0001
#
# Cuando la plantilla está así se leen solas y no hay que escribir marcadores.

_REF = re.compile(r"^([A-Z]+)(\d+)$")
MAX_ETIQUETA = 60


def _celda_pos(ref: str) -> tuple[int, int]:
    """(fila, columna) de una referencia «B12», para poder ordenar."""
    m = _REF.match(str(ref or "").upper())
    if not m:
        return (0, 0)
    col = 0
    for letra in m.group(1):
        col = col * 26 + (ord(letra) - 64)
    return (int(m.group(2)), col)


def _texto_celda(celda, tabla: list) -> str:
    """Lo que se lee en la celda, venga de la tabla común o de dentro."""
    if celda.get("t") == "s":
        v = celda.find(_s("v"))
        try:
            return tabla[int(v.text)] if v is not None and v.text else ""
        except (ValueError, IndexError):
            return ""
    dentro = celda.find(_s("is"))
    if dentro is not None:
        return "".join(t.text or "" for t in dentro.iter(_s("t")))
    v = celda.find(_s("v"))
    return (v.text or "") if v is not None and celda.get("t") != "e" else ""


def _tabla_comun(partes: dict) -> list:
    crudo = partes.get("xl/sharedStrings.xml")
    if not crudo:
        return []
    raiz = ET.fromstring(crudo)
    return ["".join(t.text or "" for t in si.iter(_s("t"))) for si in raiz.iter(_s("si"))]


def _filas(raiz, tabla: list):
    """Por cada fila, sus celdas ordenadas: [(ref, texto, elemento)]."""
    for fila in raiz.iter(_s("row")):
        celdas = [(c.get("r") or "", _texto_celda(c, tabla), c) for c in fila.iter(_s("c"))]
        if celdas:
            yield sorted(celdas, key=lambda x: _celda_pos(x[0]))


# La otra forma de escribir una portada en Excel: la etiqueta y el valor en la
# MISMA celda, separados por un salto de línea. Así está la de MOEVE:
#
#     A3   «Nº DOCUMENTO:\nV-2201BI01A0BG-2206-740-DL-001»
#     E3   «ITEM-TAG:\nBR10S 0001»
#
# Se reconoce igual que la otra y al escribir se conserva la primera línea.
_ETIQUETA_EN_CELDA = re.compile(r"^([^\n]{1,60}?)\s*:[ \t]*\n(.*)$", re.S)


def _pares(raiz, tabla: list):
    """(etiqueta, celda del valor, valor, lo que va delante) de la hoja.

    Dos formas, las dos de portadas reales:

    · La etiqueta en una celda y el valor en la de al lado («CLIENT : | MOEVE»).
      La etiqueta es la primera celda con texto de la fila y el valor la
      siguiente que haya: los dos puntos van pegados a la etiqueta, no en una
      celda de en medio.
    · Las dos cosas en la misma celda, separadas por un salto de línea. Ahí
      puede haber varias por fila, así que se miran todas.
    """
    for celdas in _filas(raiz, tabla):
        juntas = False
        for _r, txt, el in celdas:
            m = _ETIQUETA_EN_CELDA.match(txt)
            if not m:
                continue
            etiqueta = m.group(1).strip()
            if etiqueta and len(etiqueta) <= MAX_ETIQUETA:
                juntas = True
                yield etiqueta, el, m.group(2).strip(), f"{etiqueta}:\n"
        if juntas:
            continue

        con_texto = [(r, txt, el) for r, txt, el in celdas if txt.strip()]
        if not con_texto:
            continue
        ref, etiqueta, _ = con_texto[0]
        etiqueta = etiqueta.strip().rstrip(":").strip()
        # Un texto de varias líneas es el rótulo de una caja («A RELLENAR / POR
        # EL / VENDEDOR»), no una etiqueta con su valor al lado.
        if not etiqueta or len(etiqueta) > MAX_ETIQUETA or "\n" in etiqueta:
            continue
        posteriores = [(r, txt, el) for r, txt, el in celdas
                       if _celda_pos(r) > _celda_pos(ref)]
        if not posteriores:
            continue
        _r, texto, celda = posteriores[0]
        yield etiqueta, celda, texto, ""


def etiquetas(plantilla: Path | str) -> list:
    """Etiquetas de la plantilla: [{etiqueta, valor}], sin repetir."""
    with zipfile.ZipFile(plantilla) as z:
        partes = {n: z.read(n) for n in z.namelist()}
    tabla = _tabla_comun(partes)
    out = []
    vistas = set()
    for nombre in [n for n in partes if _HOJA.match(n)]:
        raiz = ET.fromstring(partes[nombre])
        for etiqueta, _celda, valor, _delante in _pares(raiz, tabla):
            clave = etiqueta.lower()
            if clave in vistas:
                continue
            vistas.add(clave)
            out.append({"etiqueta": etiqueta, "valor": valor})
    return out


def _escribir(celda, texto: str) -> None:
    """Deja `texto` en la celda sin tocar su formato.

    Se escribe **dentro** de la celda (`inlineStr`) en vez de en la tabla común
    de cadenas: esa tabla la comparten todas las hojas, y cambiar una entrada
    usada en dos sitios cambiaría los dos.
    """
    for hijo in list(celda):
        celda.remove(hijo)
    celda.set("t", "inlineStr")
    dentro = ET.SubElement(celda, _s("is"))
    t = ET.SubElement(dentro, _s("t"))
    t.text = texto
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def rellenar(plantilla: Path | str, destino: Path | str,
             valores: dict | None = None, marcas: dict | None = None) -> Path:
    """Copia la plantilla a `destino` rellenándola de las dos maneras posibles.

    · `valores` = {etiqueta : texto} — para las portadas que son una tabla.
    · `marcas`  = {marcador : texto} — para los `{{…}}` escritos a mano.
    """
    quiere_marcas = {_clave_marca(k): str(v) for k, v in (marcas or {}).items()}
    quiere = {str(k).strip().rstrip(":").strip().lower(): str(v)
              for k, v in (valores or {}).items()}
    destino = Path(destino)
    with zipfile.ZipFile(plantilla) as z:
        orden = z.namelist()
        partes = {n: z.read(n) for n in orden}

    tabla = _tabla_comun(partes)
    for nombre in [n for n in orden if _PARTES.match(n)]:
        crudo = partes[nombre]
        _registrar_prefijos(crudo)
        raiz = ET.fromstring(crudo)
        tocado = False
        if quiere and _HOJA.match(nombre):
            for etiqueta, celda, _valor, delante in _pares(raiz, tabla):
                texto = quiere.get(etiqueta.lower())
                if texto is not None:
                    _escribir(celda, delante + texto)
                    tocado = True
        if quiere_marcas and b"{{" in crudo and _sustituir(raiz, quiere_marcas):
            tocado = True
        if tocado:
            partes[nombre] = _serializar(raiz, crudo)

    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre in orden:
            z.writestr(nombre, partes[nombre])
    logger.debug("Plantilla Excel rellenada: %s", destino.name)
    return destino
