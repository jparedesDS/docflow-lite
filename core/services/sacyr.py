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
    claves = [_clave(d.get("Doc. Cliente", "")) for d in docs]
    claves = [c for c in claves if len(c) >= 8]
    if not claves:
        return None
    for candidato in _candidatos(root):
        ficheros = [_clave(Path(f).stem) for f in _contenido(candidato)]
        if any(clave in fichero for clave in claves for fichero in ficheros):
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

def file_map(code: str, docs: list[dict]) -> dict[str, dict]:
    """{fichero → {vendor_number, tr_number}} para que el archivado sepa qué es
    cada PDF.

    SACYR nombra los ficheros con el código del documento, pero el código lleva
    una barra («…181752/01-00002») que no cabe en un nombre de fichero y aparece
    cambiada por un guion bajo, con la revisión y algún comentario detrás. Se
    comparan quitando todo lo que no sea letra o número, así que
    «REC627-627-J-C.181752/01-00002» casa con
    «REC627-627-J-C.181752_01-00002 rev0 COMENTADO.pdf» sin depender del formato.
    """
    paquete = find_package(code, docs)
    if paquete is None or paquete.is_file():
        return {}

    # De más largo a más corto: si un código es prefijo de otro (…-0002 y
    # …-00021), gana el más específico.
    candidatos = []
    for d in docs:
        clave = _clave(d.get("Doc. Cliente", ""))
        if len(clave) >= 8:
            candidatos.append((clave, d))
    candidatos.sort(key=lambda x: -len(x[0]))

    out: dict[str, dict] = {}
    for f in package_files(paquete):
        nombre = _clave(f.stem)
        doc = next((d for clave, d in candidatos if clave in nombre), None)
        if doc is not None:
            out[f.relative_to(paquete).as_posix()] = {
                "vendor_number": str(doc.get("Doc. Cliente", "")),
                "tr_number": str(doc.get("Doc. EIPSA", "")),
            }
    return out
