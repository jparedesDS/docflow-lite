r"""Devoluciones de SACYR: localizar el paquete y dejarlo en la carpeta del pedido.

**Por qué esto no es como Técnicas Reunidas.** eGesDoc tiene un formulario de
login clásico: se le manda usuario y contraseña y se baja el zip. SACYR no. Sus
dos caminos —el portal Proarc (`sacyr.proarconline.com`) y la carpeta de
SharePoint del apartado «Comments» del correo— acaban los dos en el inicio de
sesión de Microsoft del tenant de SACYR (`login.microsoftonline.com`, tenant
672bafce-…). Proarc ni siquiera tiene formulario propio: `/sts/Account/Login`
redirige siempre al proveedor externo. Sin un usuario de Microsoft con acceso al
tenant —y con MFA por medio— no hay nada que scrapear.

Lo que sí se puede automatizar es todo lo demás. SACYR publica cada devolución
en una carpeta de SharePoint que se llama **exactamente igual que el nº de flujo
del asunto**, cambiando la barra por un guion bajo:

    WF#: 4000079-REC627-627-J-C.181752/01-SP-OBTS-000005
    →    4000079-REC627-627-J-C.181752_01-SP-OBTS-000005

Así que basta con que esa carpeta esté accesible en el disco —sincronizada con
OneDrive («Sincronizar» o «Añadir acceso directo a OneDrive») o descargada a
mano— y la app hace el resto: la empaqueta en `00 TRANS Y RES\NNN (fecha)`,
guarda el correo al lado y archiva cada PDF en su `dev <Tipo>\rev<N>`, igual que
con Técnicas Reunidas.

La carpeta donde buscar se configura en Ajustes ▸ Portales.
"""

from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path

from core import preferences

logger = logging.getLogger(__name__)

# Nº de flujo y PO del asunto:
#   «… WF#:4000079-REC627-…-SP-OBTS-000005 - DISC:270 - PO:REC627-… OBTS-000005»
_WF_RE = re.compile(r"WF#\s*:\s*(\S+)", re.I)
_PO_RE = re.compile(r"\bPO\s*:\s*(\S+)", re.I)

# Enlace a la carpeta de SharePoint del apartado «Comments» del correo.
_SHARE_RE = re.compile(r"https://[a-z0-9.-]*sharepoint\.com/[^\s\"'<>]+", re.I)

# Hasta dónde bajar buscando la carpeta del transmittal. Una biblioteca
# sincronizada de SharePoint tiene el paquete a dos o tres niveles del raíz.
_MAX_DEPTH = 5

# Lo que OneDrive y Windows dejan por ahí y no es un documento devuelto.
_IGNORAR = {"thumbs.db", "desktop.ini", ".ds_store"}


def parse_subject(subject: str) -> dict:
    """{code, po} del asunto ('' si no es un aviso de documentos de SACYR)."""
    wf = _WF_RE.search(subject or "")
    po = _PO_RE.search(subject or "")
    return {"code": wf.group(1) if wf else "", "po": po.group(1) if po else ""}


def sharepoint_link(html: str) -> str:
    """Enlace a la carpeta de SharePoint que trae el correo ('' si no lo trae)."""
    m = _SHARE_RE.search(html or "")
    return m.group(0).replace("&amp;", "&") if m else ""


def folder_name(code: str) -> str:
    """Nombre con el que SACYR publica la carpeta: la barra pasa a guion bajo."""
    return str(code or "").replace("/", "_").strip()


def _clave(texto: str) -> str:
    """Solo letras y números, en mayúsculas: así el código del documento es el
    mismo lo escriban con barra, con guion bajo o con espacios."""
    return re.sub(r"[^A-Za-z0-9]", "", str(texto or "")).upper()


def _partes(codigo: str) -> tuple[str, int | None]:
    """Código de documento partido en (tramo común normalizado, nº de orden)."""
    texto = str(codigo or "").strip()
    if "-" not in texto:
        return "", None
    base, cola = texto.rsplit("-", 1)
    m = re.fullmatch(r"0*(\d+)", cola.strip())
    return (_clave(base), int(m.group(1))) if m else ("", None)


def casa_documento(codigo: str, nombre: str) -> bool:
    """¿Este fichero es ese documento?

    Los PDF que publica SACYR llevan el código **del ERP**, no el del correo:

        correo   REC627-627-J-C.181752/01-00002
        fichero  V-REC627-627-J-C.181752_01-002_R0_A.pdf

    Sobra el prefijo del proveedor, el nº de orden va con menos ceros y detrás
    van la revisión y el código de revisión del cliente. Es el mismo desfase que
    ya hay entre el correo y el ERP, así que se compara igual: el tramo común
    tiene que aparecer en el nombre y el número que va justo después tiene que
    ser el mismo. Comparar el código entero no vale: «…0100002» nunca casaría
    con «…01002».
    """
    base, orden = _partes(codigo)
    if not base or orden is None or len(base) < 8:
        return False
    fichero = _clave(nombre)
    desde = fichero.find(base)
    if desde < 0:
        return False
    m = re.match(r"0*(\d+)", fichero[desde + len(base):])
    return bool(m) and int(m.group(1)) == orden


# ── Dónde buscar ──────────────────────────────────────────────────────────────

def local_root() -> Path | None:
    """Carpeta local donde aparecen las devoluciones de SACYR (Ajustes ▸ Portales)."""
    raw = str(preferences.get("sacyr_folder", "") or "").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_dir() else None


def is_configured() -> bool:
    return local_root() is not None


def _candidatos(root: Path) -> list[Path]:
    """Carpetas y zips que hay dentro de la carpeta configurada, del más nuevo
    al más viejo (lo recién descargado primero)."""
    fuera: list[Path] = []
    pendientes = [(root, 0)]
    while pendientes and len(fuera) < 200:
        carpeta, nivel = pendientes.pop(0)
        try:
            hijos = list(carpeta.iterdir())
        except OSError:
            continue
        for hijo in hijos:
            if hijo.is_dir():
                fuera.append(hijo)
                if nivel < _MAX_DEPTH:
                    pendientes.append((hijo, nivel + 1))
            elif hijo.suffix.lower() == ".zip":
                fuera.append(hijo)
    fuera.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return fuera


def _contenido(paquete: Path) -> list[str]:
    """Nombres de los ficheros que hay dentro (carpeta o zip)."""
    try:
        if paquete.is_file():
            with zipfile.ZipFile(paquete) as zf:
                return [zi.filename for zi in zf.infolist() if not zi.is_dir()]
        return [p.name for p in paquete.iterdir() if p.is_file()]
    except (OSError, zipfile.BadZipFile):
        return []


def find_package(code: str, docs: list[dict] | None = None,
                 root: Path | None = None) -> Path | None:
    """Carpeta o zip de esa devolución dentro de la carpeta configurada.

    Se busca en dos pasadas:

    1. **Por nombre**: la carpeta que publica SACYR se llama como el WF#, y el
       zip que genera SharePoint al descargarla, igual. Si están las dos gana la
       carpeta: solo con los ficheros sueltos se puede emparejar cada PDF con su
       documento.
    2. **Por contenido**, si se pasan los documentos del correo: al descargar
       desde un enlace compartido, SharePoint a veces nombra el zip
       «OneDrive_1_10-09-2026.zip» en vez de con el nombre de la carpeta. Se mira
       dentro de lo que haya (lo más reciente primero) y se acepta lo que
       contenga alguno de los códigos de documento del correo, así no hay que
       andar renombrando nada.
    """
    root = root or local_root()
    if root is None or not code:
        return None

    objetivo = folder_name(code).lower()
    comprimidos = {objetivo + ext for ext in (".zip", ".7z")}
    zip_encontrado = None
    for candidato in _candidatos(root):
        nombre = candidato.name.lower()
        if candidato.is_dir() and nombre == objetivo:
            return candidato
        if candidato.is_file() and nombre in comprimidos and zip_encontrado is None:
            zip_encontrado = candidato
    if zip_encontrado is not None:
        return zip_encontrado

    if not docs:
        return None
    codigos = [str(d.get("Doc. Cliente", "")) for d in docs]
    codigos = [c for c in codigos if _partes(c)[1] is not None]
    if not codigos:
        return None
    for candidato in _candidatos(root):
        ficheros = [Path(f).stem for f in _contenido(candidato)]
        if any(casa_documento(c, f) for c in codigos for f in ficheros):
            logger.info("SACYR: %s reconocido por su contenido como %s",
                        candidato.name, code)
            return candidato
    return None


def package_files(paquete: Path) -> list[Path]:
    """Ficheros de la devolución (si el paquete es carpeta; el zip va aparte)."""
    if paquete.is_file():
        return [paquete]
    return sorted(p for p in paquete.rglob("*")
                  if p.is_file() and p.name.lower() not in _IGNORAR)


def collect(code: str, dest_dir: Path | str,
            docs: list[dict] | None = None) -> Path:
    """Deja la devolución como un zip en `dest_dir`. Devuelve la ruta del zip.

    Es la función que consume `portal_downloads.download_for_email`, con la misma
    forma que `egesdoc.download_transmittal` y `ayesa.download`.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    paquete = find_package(code, docs)
    if paquete is None:
        raiz = local_root()
        if raiz is None:
            raise RuntimeError(
                "Configura en Ajustes ▸ Portales la carpeta donde aparecen las "
                "devoluciones de SACYR (la biblioteca de SharePoint sincronizada).")
        raise FileNotFoundError(
            f"No encuentro «{folder_name(code)}» dentro de {raiz}. Sincroniza esa "
            f"carpeta de SharePoint o descárgala ahí.")

    destino = dest_dir / (folder_name(code) + ".zip")
    if paquete.is_file():
        destino.write_bytes(paquete.read_bytes())
        logger.info("SACYR: %s copiado de %s", destino.name, paquete)
        return destino

    ficheros = package_files(paquete)
    if not ficheros:
        raise FileNotFoundError(f"La carpeta {paquete} está vacía")
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in ficheros:
            zf.write(f, f.relative_to(paquete).as_posix())
    logger.info("SACYR: %s empaquetado con %d fichero(s) de %s",
                destino.name, len(ficheros), paquete)
    return destino


# ── Emparejar ficheros con documentos ─────────────────────────────────────────

def file_map(code: str, docs: list[dict] | None = None) -> dict[str, dict]:
    """{fichero → {vendor_number, tr_number}} para que el archivado sepa qué es
    cada PDF.

    Funciona igual si el paquete es una carpeta o un zip: lo que hace falta son
    los nombres de dentro. El emparejado lo hace `casa_documento`, porque SACYR
    nombra los ficheros con el código del ERP y el correo trae el suyo.
    """
    docs = docs or []
    paquete = find_package(code, docs)
    if paquete is None:
        return {}
    out: dict[str, dict] = {}
    for entrada in _contenido(paquete):
        nombre = Path(entrada).name
        doc = next((d for d in docs
                    if casa_documento(str(d.get("Doc. Cliente", "")), Path(nombre).stem)), None)
        if doc is not None:
            out[nombre] = {
                "vendor_number": str(doc.get("Doc. Cliente", "")),
                "tr_number": str(doc.get("Doc. EIPSA", "")),
            }
    return out


# ── Código de revisión del cliente ────────────────────────────────────────────
#
# Los PDF de SACYR acaban con la revisión y una letra:
#
#     V-REC627-627-J-C.181752_01-002_R0_A.pdf   → rev 0, código A
#     V-REC627-627-J-C.181752_01-003-R1_B.pdf   → rev 1, código B
#
# Esa letra es la resolución, que el correo NO trae. Coincide con cómo están
# archivadas ya las carpetas del pedido a mano: el cálculo rev 0 con código A
# está en «dev Cálculos\rev0 AP», y el plano rev 1 con código B en
# «dev planos\rev1 com». Solo se traducen las dos letras de las que hay
# constancia; con cualquier otra el estado se queda vacío y se pone a mano, que
# es lo que se hacía hasta ahora.

_REV_RE = re.compile(r"[-_]R\d+[-_]([A-Z])\b", re.I)

ESTADO_POR_CODIGO = {
    "A": "Aprobado",
    "B": "Com. Menores",
}


def codigo_revision(nombre: str) -> str:
    """Letra del código de revisión del nombre del fichero ('' si no la lleva)."""
    m = _REV_RE.search(Path(str(nombre or "")).stem + " ")
    return m.group(1).upper() if m else ""


def docs_con_estado(code: str, docs: list[dict]) -> list[dict]:
    """Copia de los documentos con el Estado que dice el nombre del fichero.

    Solo rellena lo que está vacío: si el estado ya viene puesto —porque se editó
    en la preview— no se toca.
    """
    ficheros = [Path(f).name for f in _contenido(find_package(code, docs) or Path("."))]
    fuera = []
    for d in docs:
        copia = dict(d)
        if not str(copia.get("Estado", "") or "").strip():
            codigo = str(copia.get("Doc. Cliente", ""))
            fichero = next((f for f in ficheros if casa_documento(codigo, Path(f).stem)), "")
            estado = ESTADO_POR_CODIGO.get(codigo_revision(fichero), "")
            if estado:
                copia["Estado"] = estado
        fuera.append(copia)
    return fuera
