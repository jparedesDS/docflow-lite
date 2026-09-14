"""Portadas de un pedido entero: qué se escribe en cada hueco y dónde va el PDF.

`portadas.py` sabe rellenar una plantilla y sacar el PDF. Aquí está lo otro: de
dónde sale cada dato, cómo se recuerda el emparejamiento de cada cliente y en
qué carpeta acaba cada portada.

**El emparejamiento se hace una vez por cliente.** Cada plantilla trae sus
huecos —las etiquetas de su tabla («N° DOCUMENTO», «ITEM-TAG») o los
marcadores `{{…}}` que se escriben a mano— y a cada uno se le asigna un patrón:
texto normal con campos del ERP entre llaves.

    N° DOCUMENTO  →  {Nº Doc. Cliente}
    ITEM-TAG      →  {Tag} ALL ITEMS
    PLANTA        →  3000005785-2206-3000      (fijo, el mismo para el pedido)
    FECHA         →  {Fecha}

Así un hueco puede mezclar datos y texto fijo sin tener que inventar un campo
nuevo por cada manía de cada cliente. El perfil se guarda por cliente, de modo
que el segundo pedido de MOEVE ya sale solo.

**La portada va a la carpeta del documento**, la misma `env.` de la que sale lo
que se envía, y se llama `PORTADA <nº de documento del cliente>.pdf`, que es
como están archivadas a mano. Nunca se pisa una portada anterior: si ya hay
una, la nueva se guarda al lado (lo hace `portadas.generar`).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

PREFIJO = "PORTADA "

# Campos que se pueden meter entre llaves en cualquier hueco, con lo que son en
# lenguaje llano: es la lista que se le enseña a quien empareja la plantilla.
CAMPOS: list[tuple[str, str]] = [
    ("Nº Doc. Cliente", "El número que le da el cliente al documento"),
    ("Nº Doc. EIPSA",   "El número interno de EIPSA"),
    ("Título",          "Título del documento"),
    ("Tag",             "El tag del título (lo que va detrás del guion)"),
    ("Tipo Doc.",       "Tipo de documento: Cálculos, Planos, ITP…"),
    ("Nº Revisión",     "Revisión, tal cual está en el ERP (0, 1, A…)"),
    ("Rev. 2 cifras",   "La revisión con dos cifras: 00, 01, 02"),
    ("Fichero",         "Nombre del PDF que se envía: «<nº cliente>-R00.PDF»"),
    ("Nº Pedido",       "Pedido de EIPSA (P-26/048)"),
    ("Nº PO",           "Pedido del cliente"),
    ("Cliente",         "Nombre del cliente"),
    ("Material",        "Material del pedido"),
    ("Fecha",           "La fecha de hoy, dd/mm/aaaa"),
]

_CAMPO = re.compile(r"\{\s*([^{}]{1,40}?)\s*\}")


def _fold(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _tag(titulo: str) -> str:
    """El tag que va detrás del guion del título: «Cálculos - TKFE 2017N»."""
    partes = str(titulo or "").split(" - ")
    return partes[-1].strip() if len(partes) > 1 else ""


def _dos_cifras(rev) -> str:
    """«1.0» → «01». Si la revisión es una letra se deja como está."""
    texto = str(rev or "").strip()
    m = re.match(r"^\s*(\d+)", texto)
    return f"{int(m.group(1)):02d}" if m else texto.upper()


def valores_documento(doc: dict) -> dict[str, str]:
    """Lo que vale cada campo para ESE documento."""
    cliente_doc = str(doc.get("Nº Doc. Cliente", "") or "").strip()
    rev2 = _dos_cifras(doc.get("Nº Revisión"))
    return {
        "Nº Doc. Cliente": cliente_doc,
        "Nº Doc. EIPSA": str(doc.get("Nº Doc. EIPSA", "") or "").strip(),
        "Título": str(doc.get("Título", "") or "").strip(),
        "Tag": _tag(doc.get("Título", "")),
        "Tipo Doc.": str(doc.get("Tipo Doc.", "") or "").strip(),
        "Nº Revisión": str(doc.get("Nº Revisión", "") or "").strip(),
        "Rev. 2 cifras": rev2,
        "Fichero": f"{cliente_doc}-R{rev2}.PDF" if cliente_doc else "",
        "Nº Pedido": str(doc.get("Nº Pedido", "") or "").strip(),
        "Nº PO": str(doc.get("Nº PO", "") or "").strip(),
        "Cliente": str(doc.get("Cliente", "") or "").strip(),
        "Material": str(doc.get("Material", "") or "").strip(),
        "Fecha": datetime.now().strftime("%d/%m/%Y"),
    }


def aplicar(patron: str, valores: dict) -> str:
    """«{Tag} ALL ITEMS» → «TKFE 2017N ALL ITEMS».

    Un campo que no exista se queda vacío en vez de reventar: la portada sale
    con un hueco, que se ve, y no se pierde el lote entero por una errata.
    """
    def cambia(m):
        clave = _fold(m.group(1))
        for k, v in valores.items():
            if _fold(k) == clave:
                return str(v)
        logger.info("Portadas: el campo «%s» no existe; se deja vacío", m.group(1))
        return ""
    return _CAMPO.sub(cambia, str(patron or ""))


# ── Huecos de las plantillas ──────────────────────────────────────────────────

def huecos(plantillas: list[Path | str]) -> list[dict]:
    """Los huecos que hay que rellenar en esas plantillas.

    [{clave, tipo: 'etiqueta'|'marca', ejemplo, plantilla}] — `ejemplo` es lo
    que la plantilla trae escrito, que ayuda a saber qué va ahí.
    """
    from core.services import plantilla_docx, plantilla_xlsx

    out: list[dict] = []
    vistos: set[tuple[str, str]] = set()
    for p in plantillas:
        p = Path(p)
        try:
            # Una hoja de cálculo solo trae marcadores: ver `plantilla_xlsx`.
            if p.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
                for m in plantilla_xlsx.marcadores(p):
                    clave = (m, "marca")
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    out.append({"clave": m, "tipo": "marca", "ejemplo": "", "plantilla": p.name})
                continue
            for e in plantilla_docx.etiquetas(p):
                clave = (e["etiqueta"], "etiqueta")
                if clave in vistos:
                    continue
                vistos.add(clave)
                out.append({"clave": e["etiqueta"], "tipo": "etiqueta",
                            "ejemplo": e.get("valor", ""), "plantilla": p.name})
            for m in plantilla_docx.marcadores(p):
                clave = (m, "marca")
                if clave in vistos:
                    continue
                vistos.add(clave)
                out.append({"clave": m, "tipo": "marca", "ejemplo": "", "plantilla": p.name})
        except Exception as exc:  # noqa: BLE001 — una plantilla rota no tumba las demás
            logger.warning("No se pudo leer la plantilla %s: %s", p, exc)
    return out


# ── Perfil por cliente ────────────────────────────────────────────────────────

def _perfiles() -> dict:
    from core import preferences
    return dict(preferences.get("portadas_perfiles") or {})


def perfil(cliente: str) -> dict:
    """{plantillas: [rutas], mapa: {hueco: patrón}} de ese cliente."""
    datos = _perfiles().get(_fold(cliente)) or {}
    return {"plantillas": list(datos.get("plantillas") or []),
            "mapa": dict(datos.get("mapa") or {})}


def guardar_perfil(cliente: str, plantillas: list, mapa: dict) -> None:
    from core import preferences

    todos = _perfiles()
    todos[_fold(cliente)] = {"plantillas": [str(p) for p in plantillas],
                             "mapa": {str(k): str(v) for k, v in mapa.items()}}
    preferences.set_value("portadas_perfiles", todos)
    logger.info("Portadas: perfil de %s guardado (%d plantilla(s), %d hueco(s))",
                cliente, len(plantillas), len(mapa))


# ── Dónde va cada portada ─────────────────────────────────────────────────────

def carpeta_destino(doc: dict) -> Path | None:
    """La carpeta `env.` del documento, que es donde se archivan las portadas."""
    from core.services import dev_folders

    pedido = str(doc.get("Nº Pedido", "") or "")
    tecnico = dev_folders.tecnico_dir(pedido)
    if tecnico is None:
        return None
    envs = [f for f in dev_folders.scan_folders(tecnico) if f["kind"] == "env"]
    elegida = dev_folders._by_type_and_title(
        envs, str(doc.get("Tipo Doc.", "")), str(doc.get("Título", "")))
    return elegida["path"] if elegida else None


def destino_portada(doc: dict) -> Path | None:
    """Ruta completa del PDF de la portada, o None si no se sabe dónde va."""
    carpeta = carpeta_destino(doc)
    codigo = str(doc.get("Nº Doc. Cliente", "") or "").strip()
    if carpeta is None or not codigo:
        return None
    return carpeta / f"{PREFIJO}{codigo}.pdf"


# ── Generar ───────────────────────────────────────────────────────────────────

def generar_lote(docs: list[dict], plantillas: list, mapa: dict,
                 progreso=None) -> list[dict]:
    """Una portada por documento. Devuelve [{doc, destino, error}].

    Word (o Excel, según la plantilla) se abre UNA vez para todo el lote:
    arrancarlo por cada documento son cinco segundos por portada, y un lote de
    cincuenta se iría a cuatro minutos de puro arranque.
    """
    from core.services import portadas

    if not plantillas:
        raise ValueError("Este cliente no tiene ninguna plantilla de portada configurada")
    resultados: list[dict] = []
    with portadas.Oficina() as oficina:
        for i, doc in enumerate(docs, 1):
            codigo = str(doc.get("Nº Doc. Cliente", "") or "").strip()
            if progreso:
                progreso(i, len(docs), codigo)
            destino = destino_portada(doc)
            if destino is None:
                resultados.append({"doc": doc, "destino": None,
                                   "error": "no sé en qué carpeta env. va este documento"})
                continue
            valores = valores_documento(doc)
            textos = {h: aplicar(patron, valores) for h, patron in mapa.items() if patron}
            try:
                final = portadas.generar(plantillas, destino, valores=textos,
                                         marcas=textos, oficina=oficina)
                resultados.append({"doc": doc, "destino": final, "error": ""})
            except Exception as exc:  # noqa: BLE001 — un fallo no corta el lote
                logger.exception("Portada de %s", codigo)
                resultados.append({"doc": doc, "destino": None, "error": str(exc)})
    return resultados
