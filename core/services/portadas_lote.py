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
    ("Tag",             "El TAG del documento (vacío si no es de un tag concreto)"),
    ("Tipo Doc.",       "Tipo de documento: Cálculos, Planos, ITP…"),
    ("Nº Revisión",     "La revisión: 0, 1, 2… (o la letra, si el cliente usa letras)"),
    ("Rev. 2 cifras",   "La revisión con dos cifras: 00, 01, 02"),
    ("Fichero",         "Nombre del PDF que se envía: «<nº cliente>-R00.PDF»"),
    ("Nº Pedido",       "Pedido de EIPSA (P-26/048)"),
    ("Nº PO",           "Pedido del cliente"),
    ("Cliente",         "Nombre del cliente"),
    ("Material",        "Material del pedido"),
    ("Fecha",           "La fecha de hoy, dd/mm/aaaa"),
]

# `{Campo}` o `{Campo|lo que va si ese campo está vacío}`. La alternativa hace
# falta a poco que se mire una portada real: en el hueco del TAG va el tag del
# documento si es de uno —cálculos y planos— y «ALL TAGS» en los demás.
_CAMPO = re.compile(r"\{\s*([^{}]{1,80}?)\s*\}")


def _fold(s) -> str:
    return re.sub(r"\s+", " ", _texto(s)).strip().lower()


def _texto(valor) -> str:
    """El valor como texto, contando el 0 como valor y no como hueco.

    El ERP devuelve la revisión como número: la 0 llega como `0.0`, que es
    falso para Python, y un `str(v or "")` la convertía en una casilla vacía.
    De paso, «0.0» se queda en «0», que es lo que se escribe en una portada.
    """
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


def _tag(doc: dict) -> str:
    """El TAG al que pertenece el documento, o '' si no es de uno concreto.

    Los cálculos y los planos son de un tag; el ITP, el dossier o el manual son
    del pedido entero. No hace falta decidirlo por el tipo de documento: se
    mira si el documento **nombra** alguno de los tags del pedido, en su número
    o en su título, que es lo que hacen todos los clientes:

        V-2401HG04A-2206-300-OHFE-0014-CAL-001   →  OHFE 0014
        EQUIPMENT CALCULATION / DATA SHEET OHFE-0014

    Se compara sin espacios ni guiones, porque el ERP escribe «OHFE 0014», el
    cliente «OHFE-0014» y a veces «OHFE0014». El texto que se devuelve es el
    del ERP, que es como está escrito en las portadas de verdad.
    """
    tags = _tags_del_pedido(_texto(doc.get("Nº Pedido")))
    if not tags:
        # Sin ERP a mano queda el apaño de siempre: lo que va detrás del guion.
        partes = _texto(doc.get("Título")).split(" - ")
        return partes[-1].strip() if len(partes) > 1 else ""
    donde = _sin_separadores(_texto(doc.get("Nº Doc. Cliente")) + " " +
                             _texto(doc.get("Nº Doc. EIPSA")) + " " +
                             _texto(doc.get("Título")))
    casan = [tag for tag, plano in tags if plano in donde]
    return ", ".join(dict.fromkeys(casan))


def _sin_separadores(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", _texto(s).upper())


# Un tag más corto que esto casaría con cualquier cosa por casualidad.
MIN_TAG = 5


def _tags_del_pedido(pedido: str) -> list:
    """[(tag, tag sin separadores)] de los tags vigentes del pedido."""
    if not pedido:
        return []
    cache = _TAGS_CACHE.get(pedido)
    if cache is None:
        cache = []
        try:
            from core.services import erp_tags
            for t in erp_tags.fetch_tags(pedido):
                if not t.get("_vigente") or t.get("_eliminado"):
                    continue
                tag = _texto(t.get("TAG")).strip()
                plano = _sin_separadores(tag)
                if len(plano) >= MIN_TAG:
                    cache.append((tag, plano))
        except Exception as exc:  # noqa: BLE001 — sin ERP se tira del título
            logger.info("Portadas: no se pudieron leer los tags de %s: %s", pedido, exc)
        # Primero los más largos: «OUFE 00141» antes que «OUFE 0014».
        cache.sort(key=lambda x: len(x[1]), reverse=True)
        _TAGS_CACHE[pedido] = cache
    return cache


_TAGS_CACHE: dict = {}


def _cifras(rev) -> str:
    """«1.0» → «1». Si la revisión es una letra se deja como está."""
    texto = _texto(rev).strip()
    m = re.match(r"^\s*(\d+)", texto)
    return str(int(m.group(1))) if m else texto.upper()


def _dos_cifras(rev) -> str:
    """«1.0» → «01». Si la revisión es una letra se deja como está."""
    texto = _texto(rev).strip()
    m = re.match(r"^\s*(\d+)", texto)
    return f"{int(m.group(1)):02d}" if m else texto.upper()


def valores_documento(doc: dict) -> dict[str, str]:
    """Lo que vale cada campo para ESE documento."""
    cliente_doc = _texto(doc.get("Nº Doc. Cliente")).strip()
    rev2 = _dos_cifras(doc.get("Nº Revisión"))
    return {
        "Nº Doc. Cliente": cliente_doc,
        "Nº Doc. EIPSA": _texto(doc.get("Nº Doc. EIPSA")).strip(),
        "Título": _texto(doc.get("Título")).strip(),
        "Tag": _tag(doc),
        "Tipo Doc.": _texto(doc.get("Tipo Doc.")).strip(),
        "Nº Revisión": _cifras(doc.get("Nº Revisión")),
        "Rev. 2 cifras": rev2,
        "Fichero": f"{cliente_doc}-R{rev2}.PDF" if cliente_doc else "",
        "Nº Pedido": _texto(doc.get("Nº Pedido")).strip(),
        "Nº PO": _texto(doc.get("Nº PO")).strip(),
        "Cliente": _texto(doc.get("Cliente")).strip(),
        "Material": _texto(doc.get("Material")).strip(),
        "Fecha": datetime.now().strftime("%d/%m/%Y"),
    }


def aplicar(patron: str, valores: dict) -> str:
    """«{Tag} ALL ITEMS» → «TKFE 2017N ALL ITEMS».

    Detrás de una barra va lo que se pone cuando ese campo está vacío:
    «{Tag|ALL TAGS}» escribe el tag del documento, y «ALL TAGS» en los que no
    son de un tag concreto.

    Un campo que no exista se queda vacío en vez de reventar: la portada sale
    con un hueco, que se ve, y no se pierde el lote entero por una errata.
    """
    def cambia(m):
        nombre, _, alternativa = m.group(1).partition("|")
        clave = _fold(nombre)
        for k, v in valores.items():
            if _fold(k) == clave:
                texto = str(v)
                return texto if texto.strip() else alternativa.strip()
        logger.info("Portadas: el campo «%s» no existe; se deja vacío", nombre)
        return alternativa.strip()
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
            lector = plantilla_xlsx if p.suffix.lower() in (".xlsx", ".xlsm", ".xls") else plantilla_docx
            for e in lector.etiquetas(p):
                clave = (e["etiqueta"], "etiqueta")
                if clave in vistos:
                    continue
                vistos.add(clave)
                out.append({"clave": e["etiqueta"], "tipo": "etiqueta",
                            "ejemplo": e.get("valor", ""), "plantilla": p.name})
            for m in lector.marcadores(p):
                clave = (m, "marca")
                if clave in vistos:
                    continue
                vistos.add(clave)
                out.append({"clave": m, "tipo": "marca", "ejemplo": "", "plantilla": p.name})
        except Exception as exc:  # noqa: BLE001 — una plantilla rota no tumba las demás
            logger.warning("No se pudo leer la plantilla %s: %s", p, exc)
    return out


def sugerir(huecos: list[dict], docs: list[dict]) -> dict[str, str]:
    """Qué poner de entrada en cada hueco, sin que haya que adivinar nada.

    La plantilla del cliente viene rellena de un documento suyo, y eso dice más
    que cualquier instrucción: si lo que trae escrito es exactamente el número
    de un documento del pedido, ese hueco es de los que cambian y se propone el
    campo del ERP correspondiente; si no, es un dato fijo del pedido —el
    proyecto, la planta, el contrato— y se deja **tal cual estaba**.

    Así no hay que saber qué se completa y qué no: lo que está bien, se queda.
    """
    indice: dict[str, str] = {}
    for doc in docs or []:
        valores = valores_documento(doc)
        for campo, _ in CAMPOS:                   # en orden: gana el más concreto
            valor = _fold(valores.get(campo, ""))
            # Menos de cuatro letras no distingue nada («OG», «0», «R1»).
            if len(valor) >= 4:
                indice.setdefault(valor, campo)
    out: dict[str, str] = {}
    for h in huecos:
        ejemplo = str(h.get("ejemplo", "") or "").strip()
        if not ejemplo:
            out[h["clave"]] = ""
            continue
        campo = indice.get(_fold(ejemplo))
        if campo:
            out[h["clave"]] = f"{{{campo}}}"
        elif _fold(ejemplo) in _TODOS_LOS_TAGS:
            # «ALL TAGS» es lo que se pone cuando el documento no es de un tag
            # concreto: en los cálculos y los planos va el tag, y en el resto
            # se queda tal cual.
            out[h["clave"]] = f"{{Tag|{ejemplo}}}"
        else:
            out[h["clave"]] = _nombre_de_fichero(ejemplo, indice) or ejemplo
    return out


_TODOS_LOS_TAGS = {"all tags", "all items", "todos los tags", "all tag", "all"}


# Casi todos los clientes nombran el PDF igual: el número del documento, la
# revisión detrás de una R y la extensión («…-DL-001-R0.PDF»). Es el hueco que
# más fácil se queda a medias, porque el número casa con un campo pero la
# revisión va pegada y no.
_NOMBRE_FICHERO = re.compile(r"^(?P<doc>.+?)-R(?P<rev>\d+)\.(?P<ext>pdf)$", re.I)


def _nombre_de_fichero(ejemplo: str, indice: dict) -> str:
    """«V-…-DL-001-R0.PDF» → «{Nº Doc. Cliente}-R{Nº Revisión}.PDF» ('' si no lo es)."""
    m = _NOMBRE_FICHERO.match(ejemplo)
    if not m:
        return ""
    campo = indice.get(_fold(m.group("doc")))
    if not campo:
        return ""
    # Una cifra o dos: cada cliente escribe la revisión a su manera y hay que
    # respetar la suya, que es la que espera ver en el fichero.
    rev = "Nº Revisión" if len(m.group("rev")) == 1 else "Rev. 2 cifras"
    return f"{{{campo}}}-R{{{rev}}}.{m.group('ext')}"


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
    """Una portada por documento. Devuelve [{doc, destino, error, vacios}].

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
            # Un hueco que pedía un dato del ERP y se queda en blanco no es un
            # fallo de la plantilla: es que el documento no tiene ese dato. La
            # portada sale igual —con el hueco a la vista— pero hay que decirlo.
            vacios = [h for h, patron in mapa.items()
                      if patron and "{" in patron and not textos.get(h, "").strip()]
            try:
                final = portadas.generar(plantillas, destino, valores=textos,
                                         marcas=textos, oficina=oficina)
                if vacios:
                    logger.warning("Portada de %s: sin datos para %s", codigo, ", ".join(vacios))
                resultados.append({"doc": doc, "destino": final, "error": "", "vacios": vacios})
            except Exception as exc:  # noqa: BLE001 — un fallo no corta el lote
                logger.exception("Portada de %s", codigo)
                resultados.append({"doc": doc, "destino": None, "error": str(exc)})
    return resultados
