"""Leer y rellenar las plantillas de portada que manda el cliente en Word.

Las portadas de los clientes son una tabla de «ETIQUETA : valor»:

    | WOOD DWG. N°   | : | V-2401HG04A-2206-300-DL-001 |
    | VENDOR DOC. Nº | : | 26-062-DL-0001              |

Así que aquí se hacen dos cosas: leer esas etiquetas (para poder emparejarlas
una vez con los campos del ERP) y escribir el valor de cada una conservando el
documento tal y como vino —logos, tipografías, cajas de firma y notas legales—.

**Por qué a mano y no con python-docx**: es el mismo motivo por el que la
plantilla de Planning se edita como ZIP. Un .docx es un zip de XML, y al
reescribirlo hay dos detalles que Word no perdona y que rompen el fichero con un
«el archivo parece estar corrompido»:

· La declaración XML tiene que llevar `standalone="yes"`.
· Los espacios de nombres del elemento raíz. Word declara ahí una docena (w14,
  wp14, mc, o, v…) y `mc:Ignorable` nombra algunos que no aparecen en ningún
  elemento, así que ElementTree —que solo reescribe los que ve usados— los
  pierde; y al revés, los de los dibujos (`a:`, `pic:`) vienen declarados
  dentro del documento y ElementTree los sube a la raíz. Hacen falta los dos
  juegos: con uno solo, Word no abre el fichero.
"""

from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _w(tag: str) -> str:
    return "{%s}%s" % (_W, tag)


# El texto de una portada vive en el cuerpo, en las cabeceras (Técnicas Reunidas
# pone ahí los números de documento) y de vez en cuando en el pie.
_PARTES = re.compile(r"^word/(document|header\d*|footer\d*)\.xml$")

_DECL = re.compile(r'xmlns:([\w.-]+)\s*=\s*"([^"]+)"')
_TAG_RAIZ = re.compile(r"<(?:[\w.-]+:)?[\w.-]+\b[^>]*>")
_CABECERA = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'

# Una etiqueta más larga que esto no es una etiqueta: es la nota legal de turno.
MAX_ETIQUETA = 60


def _texto(elemento) -> str:
    return "".join(t.text or "" for t in elemento.iter(_w("t"))).strip()


# Celdas que solo separan la etiqueta de su valor: no son el valor.
_SEPARADORES = {":", "-", "=", "·", "|"}


def _celda_valor(celdas):
    """La celda donde va el valor de la fila.

    No vale quedarse con la última: WOOD escribe «ETIQUETA | : | valor» (tres
    celdas, la del medio solo trae los dos puntos) pero la cabecera de Técnicas
    Reunidas escribe «ETIQUETA | valor | (vacía)». Así que se va de izquierda a
    derecha desde la etiqueta y se coge la primera que no sea un separador.
    """
    for celda in celdas[1:]:
        if _texto(celda) not in _SEPARADORES:
            return celda
    return celdas[-1]


def _filas(raiz):
    """(fila, celdas) de todas las tablas, incluidas las anidadas."""
    for tabla in raiz.iter(_w("tbl")):
        for fila in tabla.findall(_w("tr")):
            celdas = fila.findall(_w("tc"))
            if len(celdas) >= 2:
                yield fila, celdas


def _registrar_prefijos(crudo: bytes) -> None:
    """Deja los prefijos como estaban (w:, w14:, a:, pic:…) en vez de ns0:, ns1:…

    Se busca en TODO el XML, no solo en el elemento raíz: los espacios de
    nombres de los dibujos (`a:`, `pic:`) se declaran dentro, en el elemento que
    los usa, y si no se registran salen como `ns5:` y Word ya no abre el fichero.
    """
    for prefijo, uri in _DECL.findall(crudo.decode("utf-8", "replace")):
        try:
            ET.register_namespace(prefijo, uri)
        except ValueError:      # prefijos reservados como 'xml'
            pass


_ATRIBUTO = re.compile(r'([\w.:-]+)\s*=\s*"([^"]*)"')


def _fundir_raiz(abre_original: str, abre_nuevo: str) -> str:
    """Tag de apertura con los atributos de los dos.

    Del original hacen falta las declaraciones que Word deja ahí sin usarlas en
    ningún elemento (y que `mc:Ignorable` nombra); del nuevo, las de los
    espacios de nombres que venían declarados dentro del documento —los de los
    dibujos, `a:` y `pic:`—, que ElementTree sube a la raíz al reescribir. Si se
    pone solo uno de los dos tags, faltan unas u otras y Word no abre el fichero.
    """
    nombre = re.match(r"<([\w.:-]+)", abre_nuevo).group(1)
    atributos = dict(_ATRIBUTO.findall(abre_original))
    for clave, valor in _ATRIBUTO.findall(abre_nuevo):
        atributos.setdefault(clave, valor)
    pares = " ".join(f'{k}="{v}"' for k, v in atributos.items())
    return f"<{nombre} {pares}>"


def _serializar(raiz, crudo: bytes) -> bytes:
    """XML de vuelta como lo quiere Word (ver el porqué en la cabecera)."""
    texto = ET.tostring(raiz, encoding="unicode")
    abre_original = _TAG_RAIZ.search(crudo.decode("utf-8", "replace"))
    abre_nuevo = _TAG_RAIZ.search(texto)
    if abre_original and abre_nuevo:
        fundido = _fundir_raiz(abre_original.group(0), abre_nuevo.group(0))
        texto = texto[:abre_nuevo.start()] + fundido + texto[abre_nuevo.end():]
    return _CABECERA + texto.encode("utf-8")


# ── Leer ──────────────────────────────────────────────────────────────────────

def etiquetas(plantilla: Path | str) -> list[dict]:
    """Etiquetas de la plantilla: [{etiqueta, valor, parte}].

    El `valor` es lo que la plantilla trae escrito, que sirve de dos maneras:
    como ejemplo de lo que va ahí y como valor por defecto de los campos que no
    cambian de un documento a otro (el proyecto, la planta, el nº de contrato…).
    """
    out: list[dict] = []
    vistas: set[str] = set()
    with zipfile.ZipFile(plantilla) as z:
        for parte in [n for n in z.namelist() if _PARTES.match(n)]:
            raiz = ET.fromstring(z.read(parte))
            for _, celdas in _filas(raiz):
                etiqueta = _texto(celdas[0])
                if not etiqueta or len(etiqueta) > MAX_ETIQUETA:
                    continue
                clave = etiqueta.strip().lower()
                if clave in vistas:
                    continue
                vistas.add(clave)
                out.append({"etiqueta": etiqueta, "valor": _texto(_celda_valor(celdas)),
                            "parte": parte})
    return out


# ── Escribir ──────────────────────────────────────────────────────────────────

def _escribir(celda, texto: str) -> None:
    """Pone `texto` en la celda con el formato que ya tenía.

    Word parte el texto en trozos (`<w:r>`) por sus propias razones —control de
    cambios, corrector—, así que «V-2401HG04A-2206-300» puede venir en cuatro.
    Se escribe todo en el primero, que es el que trae la fuente y el tamaño, y
    se quitan los demás.
    """
    parrafos = celda.findall(_w("p"))
    if not parrafos:
        return
    p = parrafos[0]
    runs = p.findall(_w("r"))
    if runs:
        primero = runs[0]
        for t in list(primero.findall(_w("t"))):
            primero.remove(t)
        for extra in runs[1:]:
            p.remove(extra)
    else:
        primero = ET.SubElement(p, _w("r"))
    t = ET.SubElement(primero, _w("t"))
    t.text = texto
    t.set(_XML_SPACE, "preserve")
    # Una celda puede traer varios párrafos; los de más se vacían para no dejar
    # medio valor viejo debajo del nuevo.
    for extra in parrafos[1:]:
        for r in list(extra.findall(_w("r"))):
            extra.remove(r)


def rellenar(plantilla: Path | str, destino: Path | str, valores: dict) -> Path:
    """Copia la plantilla a `destino` poniendo `valores` = {etiqueta: texto}.

    Las etiquetas se comparan sin mayúsculas ni espacios de sobra. Lo que no
    esté en `valores` se queda como estaba.
    """
    quiere = {str(k).strip().lower(): str(v) for k, v in (valores or {}).items()}
    destino = Path(destino)
    with zipfile.ZipFile(plantilla) as z:
        orden = z.namelist()
        partes = {n: z.read(n) for n in orden}

    puestas: set[str] = set()
    for nombre in [n for n in orden if _PARTES.match(n)]:
        crudo = partes[nombre]
        _registrar_prefijos(crudo)
        raiz = ET.fromstring(crudo)
        tocado = False
        for _, celdas in _filas(raiz):
            clave = _texto(celdas[0]).strip().lower()
            if clave in quiere:
                _escribir(_celda_valor(celdas), quiere[clave])
                puestas.add(clave)
                tocado = True
        if tocado:
            partes[nombre] = _serializar(raiz, crudo)

    faltan = set(quiere) - puestas
    if faltan:
        logger.info("Portada: la plantilla no tiene estas etiquetas: %s",
                    ", ".join(sorted(faltan)))

    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre in orden:                      # mismo orden: Word es tiquismiquis
            z.writestr(nombre, partes[nombre])
    tmp.replace(destino)
    return destino
