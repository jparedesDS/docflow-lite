"""Escritura de ficheros en las carpetas de los pedidos, sin pisar nunca nada.

La regla es la del departamento: **un documento archivado no se toca**. Cuando
un portal devuelve otra vez un documento que ya está guardado (mismo nombre de
fichero, contenido distinto), lo que hay que hacer es dejarlo al lado —o en la
carpeta de revisión siguiente, que de eso se encarga `dev_folders`—, nunca
escribir encima: el PDF comentado de la devolución anterior es la prueba de lo
que el cliente dijo entonces y no se puede recuperar de ningún sitio.

· `mismo_fichero()` — ¿está ya ahí, con el mismo contenido?
· `libre()`        — el mismo destino, o «nombre (2).pdf» si está ocupado.
· `escribir()`     — vuelca unos bytes sin pisar (devuelve dónde acabaron).
· `mover()`        — renombra a su nombre final sin pisar.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_COPIAS = 99


def mismo_fichero(ruta: Path | str, tamaño: int) -> bool:
    """¿Existe ese fichero y trae el mismo contenido (mismo tamaño)?"""
    try:
        p = Path(ruta)
        return p.is_file() and p.stat().st_size == tamaño
    except OSError:
        return False


def libre(destino: Path | str) -> Path:
    """El mismo destino si está libre; si no, «nombre (2).ext», «(3)»…"""
    destino = Path(destino)
    if not destino.exists():
        return destino
    for n in range(2, MAX_COPIAS + 1):
        alternativo = destino.with_name(f"{destino.stem} ({n}){destino.suffix}")
        if not alternativo.exists():
            logger.warning("Ya había un «%s»: se guarda como «%s» para no pisarlo",
                           destino.name, alternativo.name)
            return alternativo
    raise FileExistsError(f"Hay demasiadas copias de {destino.name} en {destino.parent}")


def _ya_esta(destino: Path, datos: bytes) -> bool:
    """¿Está ya ahí exactamente eso? (comparación byte a byte, sin atajos)"""
    try:
        if not (destino.is_file() and destino.stat().st_size == len(datos)):
            return False
        return destino.read_bytes() == datos
    except OSError:
        return False


def escribir(destino: Path | str, datos: bytes) -> Path:
    """Guarda `datos` en `destino` sin pisar nada; devuelve dónde acabaron.

    Si el fichero ya está y es el mismo, no se escribe nada: se devuelve el que
    había (así volver a descargar una devolución no duplica ni toca nada).
    """
    destino = Path(destino)
    if _ya_esta(destino, datos):
        return destino
    final = libre(destino)
    final.parent.mkdir(parents=True, exist_ok=True)
    with open(final, "xb") as fh:          # creación exclusiva: nunca sobrescribe
        fh.write(datos)
    return final


def mover(origen: Path | str, destino: Path | str) -> Path:
    """Renombra `origen` a `destino` sin pisar; devuelve el nombre que quedó.

    Si en el destino ya está exactamente lo mismo, se tira lo recién bajado y se
    devuelve lo que había.
    """
    origen, destino = Path(origen), Path(destino)
    if origen == destino:
        return destino
    try:
        if mismo_fichero(destino, origen.stat().st_size):
            origen.unlink(missing_ok=True)
            return destino
    except OSError:
        pass
    final = libre(destino)
    origen.replace(final)
    return final
