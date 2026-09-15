"""Archivo de los documentos devueltos en `2-Tecnico\\dev. <Tipo>\\rev<N> AP|COM|com`.

Patrón de carpetas de los pedidos (se conserva el que ya tenga cada pedido):

    2-Tecnico\\env. Cálculos\\rev 2\\V-…-CAL-001-R02.PDF            ← lo enviado
    2-Tecnico\\dev. Cálculos\\rev2 AP\\V-…-CAL-001-R02 (AF).PDF     ← lo devuelto
                                     \\dev 15-07-2026.eml           ← el correo

  · Pedidos antiguos usan «dev X» / «env X» sin punto: si existe se respeta; si
    hay que crear, se imita el estilo de la carpeta «env» hermana (y «dev. X»
    si no hay referencia).
  · Sufijo: AP (aprobado / informativo), COM (comentarios MAYORES o rechazado)
    y com en minúsculas (comentarios menores) — como «rev0 COM» / «rev1 com».
  · Letra de revisión del cliente («rev0-A COM»): solo si el pedido ya la usa
    en sus carpetas «dev» o el cliente la manda en el correo (TR: «TR Rev»).

Cada PDF del zip se empareja con un documento del correo por su código (Doc.
Cliente / Doc. EIPSA dentro del nombre del fichero). La carpeta se decide así:
  1. Buscando el fichero ENVIADO con ese código en las carpetas «env» (da la
     carpeta y la revisión exactas).
  2. Si no aparece, por tipo de documento + palabras del título contra las
     carpetas «env»/«dev» existentes.
  3. Si el pedido no tiene carpeta de ese tipo, por el catálogo de la apertura
     (`apertura.SUBFOLDER_CATALOG`) → se crea «dev. <Tipo>».
Lo que no se sabe colocar se deja en el zip y se informa; nunca se inventa.
El zip original queda intacto (se COPIA, no se mueve).

**Un documento archivado no se sobrescribe jamás.** Cuando el cliente devuelve
otra vez el mismo documento, el fichero se llama igual que el de la devolución
anterior; si la carpeta elegida ya lo tiene, esta se va a la siguiente del
correlativo. Solo se da por archivado lo que ya está ahí con el mismo contenido
(tamaño y CRC32 del zip), que es lo que hace idempotente volver a descargar.
El PDF comentado de una devolución es la prueba de lo que el cliente dijo
entonces y no se puede recuperar de ningún sitio.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import zipfile
import zlib
from pathlib import Path

from core.parsers.base_parser import es_anulado, norm_doc_code

logger = logging.getLogger(__name__)

_KIND_RE = re.compile(r"^(env|dev)\.?\s+(.+?)\s*$", re.I)
# `rev<N>[-<revisión>][ <sufijo>]`. El sufijo se captura libre (AP, com, COM,
# REJ, «AB - la rechazan»…): si solo se admitieran AP/COM, las carpetas con
# cualquier otra anotación se ignorarían y no contarían para el correlativo.
_REV_DIR_RE = re.compile(r"^z?rev\s*(\d+)(?:\s*-\s*([A-Z0-9]+))?(?:\s+(.*?))?\s*$", re.I)
_LETTER_STYLE_RE = re.compile(r"^rev\s*\d+\s*-\s*[A-Z]\b", re.I)

# Tipo de documento (parsers) → palabras que debe contener la carpeta env./dev.
TYPE_KEYWORDS = {
    "Planos": ["plano"],
    "Cálculos": ["calcul", "cal y pla", "cál"],
    "Cálculos y Planos": ["cal y pla", "calculos y planos", "cál y pla", "cálculos y planos"],
    "Certificado": ["certific"],
    "Dossier": ["dossier"],
    "Listado": ["vddl", "listado", "list"],
    "PPI": ["itp", "ppi"],
    "Programa": ["program"],
    "Procedimientos": ["proc", "procedure"],
    "Manual": ["manual"],
    "Nameplate": ["nameplate", "placa"],
    "Repuestos": ["spare", "repuesto"],
    "Soldadura": ["soldadura", "weld"],
    "Indice": ["index", "indice"],
    "Catalogo": ["catalog"],
}
_APPROVED = ("aprob", "certific", "informativ")
_MAJOR = ("mayor", "rechaz")
_STOP_WORDS = {"THE", "AND", "FOR", "WITH", "DE", "DEL", "LOS", "LAS", "PARA", "CON"}


def _fold(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).lower().strip()


def _rev_number(value) -> int | None:
    m = re.search(r"\d+", str(value or ""))
    return int(m.group(0)) if m else None


def _rev_letter(value) -> str:
    v = str(value or "").strip().upper()
    return v if re.fullmatch(r"[A-Z]", v) else ""


def _suffix(estado: str) -> str:
    """AP = aprobado · COM = comentarios mayores / rechazado · com = comentarios menores."""
    e = _fold(estado)
    if any(k in e for k in _APPROVED):
        return "AP"
    return "COM" if any(k in e for k in _MAJOR) else "com"


def _title_words(title: str) -> set[str]:
    return {w for w in re.findall(r"[A-ZÁÉÍÓÚÑ]{3,}", _fold(title).upper()) if w not in _STOP_WORDS}


# ── Carpetas del pedido ───────────────────────────────────────────────────────

def tecnico_dir(pedido: str) -> Path | None:
    from core.config import PEDIDOS_BASE_PATH
    from core.services import apertura

    base = Path(PEDIDOS_BASE_PATH) if PEDIDOS_BASE_PATH else apertura.DEFAULT_BASE_DIR
    doc_dir = apertura.find_documentacion_dir(pedido, base_dir=base, create=False) if base.exists() else None
    return doc_dir.parent if doc_dir else None


def scan_folders(tecnico: Path) -> list[dict]:
    """[{kind: 'env'|'dev', name: 'Cálculos', dotted: bool, path}] de 2-Tecnico."""
    out = []
    try:
        for d in tecnico.iterdir():
            m = _KIND_RE.match(d.name)
            if d.is_dir() and m:
                out.append({"kind": m.group(1).lower(), "name": m.group(2), "dotted": "." in d.name[:4], "path": d})
    except OSError:
        pass
    return out


def _uses_letter(folders: list[dict]) -> bool:
    for f in folders:
        if f["kind"] != "dev":
            continue
        try:
            if any(_LETTER_STYLE_RE.match(sub.name) for sub in f["path"].iterdir() if sub.is_dir()):
                return True
        except OSError:
            pass
    return False


def _find_sent_file(folders: list[dict], codes: list[str],
                    names: list[str] | None = None) -> list[tuple[dict, Path | None]]:
    """Carpetas env (y subcarpeta rev) donde está el fichero que se envió.

    Se reconoce de dos maneras: porque el nombre lleva el código del documento,
    o porque es exactamente el fichero que el portal da como suyo (`names`). Lo
    segundo hace falta con Técnicas Reunidas, donde el fichero se llama con el
    id interno del cliente (AD-3000-G-00968.pdf) y el código no aparece por
    ningún lado.
    """
    quiere = {_fold(n) for n in (names or []) if n}

    def casa(fichero: Path) -> bool:
        if _fold(fichero.name) in quiere:
            return True
        norm = norm_doc_code(fichero.name)
        return any(c in norm for c in codes)

    hits = []
    for f in folders:
        if f["kind"] != "env":
            continue
        try:
            for entry in f["path"].iterdir():
                if entry.is_file():
                    if casa(entry):
                        hits.append((f, None))
                elif entry.is_dir():
                    for sub in entry.iterdir():
                        if sub.is_file() and casa(sub):
                            hits.append((f, entry))
                            break
        except OSError:
            continue
    return hits


def _env_rev_casa(sub_name: str, n: int, letter: str) -> bool:
    """¿La subcarpeta de envío «rev0-1» corresponde a esta revisión?

    Con el estilo correlativo el número de delante es el orden de envío, no la
    revisión: la que manda es la de detrás del guion.
    """
    m = _REV_DIR_RE.match(sub_name)
    if not m:
        return False
    num, rev = int(m.group(1)), (m.group(2) or "").upper()
    return rev == (letter or str(n)).upper() if rev else num == n


# Palabras que aparecen en casi cualquier título y no distinguen carpetas
_GENERIC_WORDS = {"PROCEDURE", "PROCEDURES", "PROCEDIMIENTO", "PROCEDIMIENTOS", "PROC", "DOCUMENT",
                  "DOCUMENTS", "DOCUMENTO", "DOCUMENTOS", "REPORT", "LIST", "LISTA", "PLAN", "PACKAGE",
                  "PROJECT", "PROYECTO", "GENERAL", "FINAL", "INDEX", "INDICE", "DATA", "BOOK"}


_TIPOS_NORM: dict[str, list] | None = None


def _palabras_del_tipo(tipo: str) -> list:
    """Palabras que debe llevar la carpeta de ese tipo de documento.

    El tipo del ERP no siempre está escrito igual que la clave del catálogo
    («Certificados» frente a «Certificado»), así que se busca sin acentos, sin
    mayúsculas y probando el singular y el plural antes de darse por vencido.
    """
    global _TIPOS_NORM
    if _TIPOS_NORM is None:
        _TIPOS_NORM = {_fold(k): v for k, v in TYPE_KEYWORDS.items()}
    t = _fold(tipo)
    if not t:
        return []
    return _TIPOS_NORM.get(t) or _TIPOS_NORM.get(t.rstrip("s")) or _TIPOS_NORM.get(t + "s") or []


def _folder_score(folder_name: str, title_words: set[str], tipo: str) -> float:
    """Cuánto se parece una carpeta env./dev. al documento: palabras del título
    que aparecen en el nombre de la carpeta (las genéricas valen poco) + un
    pequeño bonus si el nombre encaja con el tipo de documento."""
    fwords = _title_words(folder_name)
    score = sum(0.3 if w in _GENERIC_WORDS else 1.0 for w in title_words & fwords)
    carpeta = _fold(folder_name)
    # El tipo pesa más que una palabra suelta del título, que puede coincidir
    # por casualidad: el «QUALITY CONTROL PLAN» (tipo PPI) comparte QUALITY con
    # «env. FINAL QUALITY DOSSIER» y su sitio es «env. ITP».
    if any(k in carpeta for k in _palabras_del_tipo(tipo)):
        score += 1.5
    # El tipo del ERP a veces ES el nombre de la carpeta («VDDL», «ITP») y no
    # está en TYPE_KEYWORDS ni se parece al título («Lista de documentos»).
    elif tipo and _fold(tipo) == carpeta:
        score += 1.5
    return score


def _by_type_and_title(folders: list[dict], tipo: str, title: str) -> dict | None:
    """Carpeta existente que mejor casa con el documento; None si no hay una
    ganadora clara (empate o ninguna palabra en común)."""
    if not folders:
        return None
    words = _title_words(title)
    scored = [(_folder_score(f["name"], words, tipo), f) for f in folders]
    best = max(s for s, _ in scored)
    if best < 1.0:
        # Sin palabras del título en común: vale el tipo de documento solo si
        # hay UNA única carpeta de ese tipo (p. ej. «Planos» → «env planos»).
        keys = TYPE_KEYWORDS.get(tipo or "", [])
        by_type = [f for f in folders if any(k in _fold(f["name"]) for k in keys)]
        names = {_fold(f["name"]) for f in by_type}
        return by_type[0] if len(names) == 1 else None
    top = [f for s, f in scored if s == best]
    names = {_fold(f["name"]) for f in top}
    return top[0] if len(names) == 1 else None


def _from_catalog(eipsa_doc: str, title: str) -> str | None:
    from core.services import apertura

    m = re.search(r"-([A-Z]{2,5})-\d+", str(eipsa_doc or "").upper())
    if not m:
        return None
    prefix = m.group(1)
    entries = [e for e in apertura.SUBFOLDER_CATALOG if str(e.get("eipsa_code", "")).upper().startswith(prefix + "-")]
    if not entries:
        return None
    if len(entries) == 1:
        return entries[0]["folder"][len("env. "):]
    words = _title_words(title)
    scored = [(len(words & (_title_words(e["es"]) | _title_words(e["en"]))), e) for e in entries]
    best = max(s for s, _ in scored)
    top = [e for s, e in scored if s == best]
    return top[0]["folder"][len("env. "):] if len(top) == 1 and best > 0 else None


def _dev_folder_for(folders: list[dict], name: str, style_dotted: bool) -> tuple[Path, bool]:
    """(ruta de la carpeta dev, existe_ya) para el tipo `name`."""
    for f in folders:
        if f["kind"] == "dev" and _fold(f["name"]) == _fold(name):
            return f["path"], True
    tecnico = folders[0]["path"].parent if folders else None
    return tecnico / (("dev. " if style_dotted else "dev ") + name), False


def _ya_archivado(dev_dir: Path, fichero: str, tamaño: int, crc: int | None = None) -> Path | None:
    """Subcarpeta de revisión donde ya está ESE MISMO fichero, si se archivó antes.

    Es lo que hace que volver a darle a descargar no duplique nada: ahora que el
    número de la carpeta es un correlativo, calcularlo otra vez daría el
    siguiente («rev2 COM» al lado del «rev1 COM» que ya tiene el PDF). También
    aguanta que la carpeta se haya renombrado a mano después.

    El tamaño es imprescindible: dos devoluciones distintas del mismo documento
    traen el mismo nombre de fichero. Si solo se mirara el nombre, la nueva se
    daría por archivada en la carpeta de la anterior y acabaría escribiendo
    encima del PDF comentado de aquella devolución.
    """
    try:
        for sub in dev_dir.iterdir():
            if sub.is_dir() and _mismo_fichero(sub / fichero, tamaño, crc):
                return sub
    except OSError:
        pass
    return None


def _mismo_fichero(ruta: Path, tamaño: int, crc: int | None = None) -> bool:
    """¿Está ya ahí ese fichero, con el mismo contenido?

    El tamaño descarta en seco; cuando coincide se compara el CRC32, que el zip
    ya trae calculado. Dos revisiones de un mismo PDF pueden ocupar lo mismo por
    casualidad, y confundirlas sería justo el error que no se puede cometer.
    """
    try:
        if not (ruta.is_file() and ruta.stat().st_size == tamaño):
            return False
    except OSError:
        return False
    return True if crc is None else _crc32(ruta) == crc


def _crc32(ruta: Path) -> int | None:
    try:
        acc = 0
        with open(ruta, "rb") as fh:
            for trozo in iter(lambda: fh.read(1 << 20), b""):
                acc = zlib.crc32(trozo, acc)
        return acc
    except OSError:
        return None


def _sin_pisar(dev_dir: Path, rev_dir: Path, existe: bool, fichero: str,
               tamaño: int, crc: int | None = None) -> tuple[Path, bool]:
    """La misma carpeta, o la siguiente si en esa ya vive OTRO fichero así.

    Un documento archivado no se toca nunca. Cuando el cliente devuelve otra vez
    el mismo documento —mismo nombre de fichero, contenido distinto— y la
    carpeta elegida ya tiene el PDF de la devolución anterior, esta se va a la
    siguiente del correlativo en vez de escribir encima.
    """
    destino = rev_dir / fichero
    while destino.exists() and not _mismo_fichero(destino, tamaño, crc):
        m = _REV_DIR_RE.match(rev_dir.name)
        if m:
            siguiente = int(m.group(1)) + 1
            rev, sufijo = (m.group(2) or ""), (m.group(3) or "")
        else:                       # carpeta renombrada a mano: detrás de todas
            subs = _rev_subfolders(dev_dir)
            siguiente = (max(num for _, num, _, _ in subs) + 1) if subs else 0
            rev, sufijo = "", ""
        nombre = f"rev{siguiente}" + (f"-{rev}" if rev else "") + (f" {sufijo}" if sufijo else "")
        if nombre == rev_dir.name:              # no avanzamos: mejor no tocar nada
            break
        rev_dir = dev_dir / nombre
        existe = rev_dir.is_dir()
        destino = rev_dir / fichero
    return rev_dir, existe


def _subcarpeta(padre: Path, nombre: str) -> tuple[Path, bool]:
    """(ruta, existe_ya) de una subcarpeta, respetando cómo esté ya escrita.

    Si la carpeta existe como «RO» no se crea otra «ro» al lado.
    """
    try:
        for d in padre.iterdir():
            if d.is_dir() and _fold(d.name) == _fold(nombre):
                return d, True
    except OSError:
        pass
    return padre / nombre, False


def _rev_subfolders(dev_dir: Path) -> list[tuple[Path, int, str, str]]:
    """Subcarpetas de revisión de una carpeta dev: (ruta, nº, revisión, sufijo)."""
    out = []
    if dev_dir.is_dir():
        try:
            for sub in dev_dir.iterdir():
                m = _REV_DIR_RE.match(sub.name)
                if sub.is_dir() and m:
                    out.append((sub, int(m.group(1)), (m.group(2) or "").upper(), m.group(3) or ""))
        except OSError:
            pass
    return out


def _rev_folder_for(dev_dir: Path, n: int, letter: str, suffix: str,
                    envio: Path | None = None) -> tuple[Path, bool]:
    """Subcarpeta de revisión existente, o la que habría que crear.

    Cada carpeta dev se nombra de una de estas dos formas, y se respeta la suya:

    · Correlativo — `rev0`, `rev1`, `rev2-D`, `rev3-0`, `rev4-1`…  El número NO
      es la revisión sino el orden de devolución de ESA carpeta, y tras el guion
      va la revisión real del documento (letra del cliente o número). Es lo que
      usan los pedidos donde la numeración del cliente se reinicia o salta
      (rev D → rev 0 → … → rev 50): si se usara la revisión como número, las
      carpetas dejarían de ir en orden. La siguiente es `rev<último+1>-<rev>`.

    · Directo — `rev50`, `rev51`…  El número ES la revisión. Se usa cuando la
      carpeta no tiene ninguna subcarpeta con guion.

    El sufijo de comentarios distingue mayúsculas (COM = mayores, com = menores);
    AP se acepta en cualquier caja.

    `envio` es la subcarpeta de la carpeta env de la que salió el documento. Si
    la carpeta dev todavía está vacía, es ella la que dice el nombre: lo que se
    mandó desde «env. Manual\\rev0-1» vuelve a «dev. Manual\\rev0-1 COM». Sin esa
    pista habría que inventarse el correlativo, y saldría «rev1 COM».
    """
    subs = _rev_subfolders(dev_dir)

    def mismo_sufijo(found: str) -> bool:
        return found.upper() == "AP" if suffix == "AP" else found == suffix

    con_guion = [(sub, num, rev, found) for sub, num, rev, found in subs if rev]
    if con_guion:                                # la carpeta ya va por correlativo
        rev_text = letter or str(n)
        for sub, _, rev, found in con_guion:
            if rev == rev_text.upper() and mismo_sufijo(found):
                return sub, True
        # El correlativo sale SOLO de las que llevan guion: una carpeta suelta
        # con la revisión por número (un «rev50» colado) dispararía la cuenta.
        # Pero si ese número ya lo ocupa otra subcarpeta, se va detrás de todas:
        # hay carpetas que mezclan los dos estilos (rev 1, rev 2-C, rev 3).
        siguiente = max(num for _, num, _, _ in con_guion) + 1
        if any(num == siguiente for _, num, _, _ in subs):
            siguiente = max(num for _, num, _, _ in subs) + 1
        return dev_dir / f"rev{siguiente}-{rev_text} {suffix}", False

    for sub, num, rev, found in subs:
        if num == n and mismo_sufijo(found) and (not letter or rev == letter):
            return sub, True

    # Aunque no lleven guion, el número de estas carpetas también cuenta las
    # devoluciones de ESA carpeta, no la revisión: en P-24/070 la primera
    # devolución (que el cliente numeró «rev A») está en «rev0 com» y la
    # segunda («rev 0» para él) va a «rev1 COM». Si se usara su revisión, la
    # segunda se llamaría «rev0» otra vez y quedarían dos carpetas rev0.
    if subs:
        siguiente = max(num for _, num, _, _ in subs) + 1
        return dev_dir / f"rev{siguiente} {suffix}", False

    if envio is not None:
        m = _REV_DIR_RE.match(envio.name)
        if m and m.group(2):
            return dev_dir / f"rev{int(m.group(1))}-{m.group(2).upper()} {suffix}", False
    return dev_dir / f"rev{n}{'-' + letter if letter else ''} {suffix}", False


# ── Archivado ─────────────────────────────────────────────────────────────────

def _match_docs(names: list[str], docs: list[dict], file_docs: dict[str, dict] | None = None) -> dict[str, dict | None]:
    """Fichero del zip → documento del correo.

    1. Si el portal nos dio el mapa fichero → códigos (`file_docs`, caso TR con
       ids internos), se usa ese.
    2. Si no, por el código más largo (Doc. Cliente / Doc. EIPSA) contenido en el nombre.
    3. Por descarte, cuando queda un solo fichero suelto y un solo documento sin
       fichero: entonces no puede ser otro. Hace falta porque el nombre que da el
       portal no siempre es el que acaba dentro del zip — el documento que se
       descarga suelto como «AD-3000-I-50160.pdf» viene en el zip del transmittal
       como «AD-3000-I-500239-SHT-001.pdf»—, y sin esto el PDF se quedaba fuera.
    """
    by_code: dict[str, dict] = {}
    for d in docs:
        for key in ("Doc. Cliente", "Doc. EIPSA"):
            code = norm_doc_code(d.get(key, ""))
            if len(code) >= 6:
                by_code.setdefault(code, d)
    known = {norm_doc_code(k): v for k, v in (file_docs or {}).items()}
    out = {}
    for name in names:
        base = Path(name).name
        norm = norm_doc_code(base)
        best, best_len = None, 0
        info = known.get(norm)
        if info:
            for val in (info.get("vendor_number"), info.get("tr_number")):
                d = by_code.get(norm_doc_code(val))
                if d is not None:
                    best = d
                    break
        if best is None:
            for code, d in by_code.items():
                if code in norm and len(code) > best_len:
                    best, best_len = d, len(code)
        out[name] = best

    huerfanos = [n for n, d in out.items() if d is None]
    colocados = {id(d) for d in out.values() if d is not None}
    sin_fichero = [d for d in docs if id(d) not in colocados]
    if len(huerfanos) == 1 and len(sin_fichero) == 1:
        out[huerfanos[0]] = sin_fichero[0]
        logger.info("Archivo dev.: %s se asigna por descarte a %s (es el único "
                    "fichero y el único documento que quedaban sin pareja)",
                    Path(huerfanos[0]).name,
                    sin_fichero[0].get("Doc. EIPSA") or sin_fichero[0].get("Doc. Cliente"))
    return out


def _portal_names(docs: list[dict], file_docs: dict[str, dict] | None) -> dict[int, list[str]]:
    """{documento → nombres de fichero que el portal le atribuye}.

    Sirve para reconocer el fichero que se envió dentro de las carpetas `env.`:
    en Técnicas Reunidas el fichero se guarda con el nombre del cliente
    (AD-3000-G-00968.pdf) y ese nombre solo lo sabe el portal.
    """
    out: dict[int, list[str]] = {}
    for fichero, info in (file_docs or {}).items():
        claves = {norm_doc_code(info.get("vendor_number")), norm_doc_code(info.get("tr_number"))}
        claves.discard("")
        for d in docs:
            suyas = {norm_doc_code(d.get("Doc. Cliente", "")), norm_doc_code(d.get("Doc. EIPSA", ""))}
            if claves & suyas:
                out.setdefault(id(d), []).append(Path(fichero).name)
    return out


def archive_return(zip_path: Path, docs: list[dict], pedido: str, *, email_raw: bytes | None = None,
                   email_date: str = "", dry_run: bool = False,
                   file_docs: dict[str, dict] | None = None) -> dict:
    """Copia los ficheros devueltos del zip a sus carpetas `dev.` del pedido.

    `file_docs`: mapa opcional {fichero → {vendor_number, tr_number}} dado por el
    portal, para zips cuyos ficheros no llevan el código del documento.
    Devuelve {archived: [(fichero, destino)], skipped: [(fichero, motivo)],
    created: [carpetas nuevas], plan: [...]} — con `dry_run` solo calcula.
    """
    res = {"archived": [], "skipped": [], "created": [], "plan": []}
    tecnico = tecnico_dir(pedido)
    if tecnico is None or not tecnico.is_dir():
        res["skipped"].append((zip_path.name, f"no se localiza 2-Tecnico del pedido {pedido}"))
        return res
    folders = scan_folders(tecnico)
    uses_letter = _uses_letter(folders)
    default_dotted = any(f["dotted"] for f in folders) or not folders
    eml_name = f"dev {email_date[:10]}.eml" if email_date else "dev.eml"

    with zipfile.ZipFile(zip_path) as zf:
        entries = [zi for zi in zf.infolist() if not zi.is_dir()]
        matched = _match_docs([zi.filename for zi in entries], docs, file_docs)
        portal_names = _portal_names(docs, file_docs)
        touched: set[Path] = set()
        for zi in entries:
            fname = Path(zi.filename).name
            doc = matched.get(zi.filename)
            if doc is None:
                res["skipped"].append((fname, "no coincide con ningún documento del correo"))
                continue
            estado = str(doc.get("Estado", ""))
            if es_anulado(estado):
                res["skipped"].append((fname, "documento anulado (VOID)"))
                continue
            n = _rev_number(doc.get("Rev."))
            if n is None:
                res["skipped"].append((fname, f"revisión desconocida ({doc.get('Rev.')!r})"))
                continue
            codes = [c for c in (norm_doc_code(doc.get("Doc. Cliente", "")), norm_doc_code(doc.get("Doc. EIPSA", ""))) if len(c) >= 6]
            letter = _rev_letter(doc.get("_rev_cliente")) if (uses_letter or _rev_letter(doc.get("_rev_cliente"))) else ""

            # 1) carpeta env por el fichero enviado
            hits = _find_sent_file(folders, codes, portal_names.get(id(doc)))
            same_rev = [(f, sub) for f, sub in hits if sub is not None and _env_rev_casa(sub.name, n, letter)]
            env, envio = (same_rev or hits or [(None, None)])[0]
            name, dotted, how = (env["name"], env["dotted"], "fichero enviado") if env else (None, default_dotted, "")
            # 2) por tipo + título
            if name is None:
                f = _by_type_and_title(folders, str(doc.get("Tipo de documento", "")), str(doc.get("Título", "")))
                if f:
                    name, dotted, how = f["name"], f["dotted"], "tipo y título"
            # 3) catálogo de apertura
            if name is None:
                cat = _from_catalog(str(doc.get("Doc. EIPSA", "")), str(doc.get("Título", "")))
                if cat:
                    name, dotted, how = cat, True, "catálogo"
            if name is None:
                res["skipped"].append((fname, f"no sé en qué carpeta va ({doc.get('Tipo de documento') or 'sin tipo'})"))
                continue

            dev_dir, dev_exists = _dev_folder_for(folders, name, dotted)
            # Algunos pedidos agrupan dentro de la carpeta: en P-24/070 los
            # documentos cuelgan de «env Specification Technical Data\FL» y
            # «…\RO» según sean de placas de caudal o de restricción. Ese nivel
            # se replica en dev, que es como están archivados a mano.
            grupo = envio.name if (envio is not None and not _REV_DIR_RE.match(envio.name)) else ""
            if grupo:
                dev_dir, dev_exists = _subcarpeta(dev_dir, grupo)
                envio = None            # ya no dice nada de la revisión
            rev_dir = _ya_archivado(dev_dir, fname, zi.file_size, zi.CRC)
            rev_exists = rev_dir is not None
            if rev_dir is None:
                rev_dir, rev_exists = _rev_folder_for(dev_dir, n, letter, _suffix(estado), envio=envio)
                rev_dir, rev_exists = _sin_pisar(dev_dir, rev_dir, rev_exists, fname,
                                                 zi.file_size, zi.CRC)
            target = rev_dir / fname
            res["plan"].append({"file": fname, "dest": target, "how": how, "doc": doc.get("Doc. EIPSA") or doc.get("Doc. Cliente")})
            if dry_run:
                continue
            for d, exists in ((dev_dir, dev_exists), (rev_dir, rev_exists)):
                if not d.is_dir():
                    d.mkdir(parents=True)
                    res["created"].append(d)
                    if d.parent == tecnico:
                        folders.append({"kind": "dev", "name": name, "dotted": dotted, "path": d})
            if _mismo_fichero(target, zi.file_size, zi.CRC):
                res["archived"].append((fname, target))   # ya estaba, y es el mismo
            else:
                # «xb» (creación exclusiva) es la última red: si algo se colara,
                # esto revienta en vez de destruir un documento ya archivado.
                try:
                    with zf.open(zi) as src, open(target, "xb") as dst:
                        for chunk in iter(lambda: src.read(1 << 16), b""):
                            dst.write(chunk)
                except FileExistsError:
                    logger.error("Archivo dev: %s ya existe en %s y NO se pisa", fname, rev_dir)
                    res["skipped"].append((fname, f"ya hay otro documento con ese nombre en {rev_dir.name}"))
                    continue
                res["archived"].append((fname, target))
            if email_raw and rev_dir not in touched:
                touched.add(rev_dir)
                eml = rev_dir / eml_name
                if not eml.exists():
                    eml.write_bytes(email_raw)
    if not dry_run:
        logger.info("Archivo dev. %s: %d copiado(s), %d sin colocar, %d carpeta(s) nueva(s)",
                    pedido, len(res["archived"]), len(res["skipped"]), len(res["created"]))
    return res


def summary_line(res: dict) -> str:
    """Frase corta para la GUI: «2 PDF en dev. Cálculos\\rev2 AP · 1 sin colocar»."""
    parts = []
    dests = {}
    for _, dest in res.get("archived", []):
        key = f"{dest.parent.parent.name}\\{dest.parent.name}"
        dests[key] = dests.get(key, 0) + 1
    for key, n in dests.items():
        parts.append(f"{n} en {key}")
    if res.get("skipped"):
        parts.append(f"{len(res['skipped'])} sin colocar")
    return " · ".join(parts) if parts else "nada que archivar"
