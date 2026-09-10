"""Descarga de devoluciones de los portales de cliente a la carpeta del pedido.

Portales soportados:
  · Técnicas Reunidas (eGesDoc): el correo avisa del transmittal y el zip se
    baja del portal con las credenciales de Ajustes ▸ Portales (`egesdoc.py`).
  · AYESA: el propio correo trae el enlace de descarga; no hace falta usuario
    (`ayesa.py`).
  · SACYR: sus dos caminos (Proarc y SharePoint) van contra el inicio de sesión
    de Microsoft del tenant de SACYR, así que no hay nada que scrapear. La app
    recoge el paquete de la carpeta local donde aparece —la biblioteca de
    SharePoint sincronizada o una descarga a mano— y de ahí en adelante hace lo
    mismo que con los otros (`sacyr.py`).

Convención de carpetas (la misma que se seguía a mano):

    <pedido>\\2-Tecnico\\00 DOCUMENTACIÓN\\00 TRANS Y RES\\NNN (DD-MM-YYYY)\\
        <código>.zip   ← paquete descargado
        <asunto>.eml   ← el correo original tal cual llegó (se abre con Outlook)

`NNN` es el siguiente número libre dentro de `00 TRANS Y RES`, con el mismo
ancho que ya use el pedido (001… o 0001…).

Tras la descarga, `dev_folders.archive_return` copia cada PDF devuelto a su
carpeta `2-Tecnico\\dev. <Tipo>\\rev<N> AP|COM` (el zip queda intacto).

Dos formas de lanzarlo:
  · Botón «⤓ Descargar devolución» en la preview de Devoluciones.
  · Automático: job cada 10 min mientras la app está abierta (Ajustes ▸ Portales)
    que mira el buzón y descarga las devoluciones nuevas que aún no estén.

Lo descargado queda apuntado en `state/portal_downloads.json` para no repetir;
además, si el zip ya existe en alguna subcarpeta, no se vuelve a bajar.
"""

from __future__ import annotations

import email
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

from core import preferences
from core.config import PEDIDOS_BASE_PATH, PORTAL_DOWNLOADS_FILE
from core.parsers import ayesa_parser, sacyr_parser, tr_parser
from core.services import ayesa, egesdoc, sacyr
from core.services import imap as imap_service
from core.utils.json_store import read_json, write_json

logger = logging.getLogger(__name__)

TRANS_FOLDER = "00 TRANS Y RES"
MAX_AUTO_ATTEMPTS = 6          # tras 6 fallos seguidos el job deja de insistir (el botón sigue funcionando)
PORTAL_NAMES = {"egesdoc": "eGesDoc (Técnicas Reunidas)", "ayesa": "AYESA",
                "sacyr": "SACYR (Proarc)"}

_listeners: list = []          # callbacks(result) para que la GUI avise de descargas automáticas


def enabled() -> bool:
    return bool(preferences.get("portal_auto_download", True))


def on_downloaded(callback) -> None:
    _listeners.append(callback)


def _notify(result: dict) -> None:
    for cb in list(_listeners):
        try:
            cb(result)
        except Exception as exc:  # noqa: BLE001
            logger.debug("listener de descargas falló: %s", exc)


# ── Qué correos son descargables ──────────────────────────────────────────────

def describe_email(sender: str, subject: str) -> dict | None:
    """{portal, code, po} si el correo es una devolución descargable; None si no."""
    if tr_parser.can_parse(sender or ""):
        info = egesdoc.parse_subject(subject)
        if info["code"] and info["po"]:
            return {"portal": "egesdoc", "code": info["code"], "po": info["po"]}
    elif ayesa_parser.can_parse(sender or ""):
        code = ayesa.parse_subject(subject)
        if code:
            return {"portal": "ayesa", "code": code, "po": ""}
    elif sacyr_parser.can_parse(sender or ""):
        info = sacyr.parse_subject(subject)
        if info["code"]:
            return {"portal": "sacyr", "code": info["code"], "po": info["po"]}
    return None


def portal_ready(portal: str) -> tuple[bool, str]:
    """(listo, motivo) — si el portal puede usarse ahora mismo."""
    if portal == "egesdoc" and not egesdoc.is_configured():
        return False, "configura el acceso a eGesDoc en Ajustes ▸ Portales"
    if portal == "sacyr" and not sacyr.is_configured():
        return False, ("indica en Ajustes ▸ Portales dónde aparecen las devoluciones "
                       "de SACYR (la carpeta de SharePoint sincronizada)")
    return True, ""


# ── Registro de descargas ─────────────────────────────────────────────────────

def _registry() -> dict:
    data = read_json(PORTAL_DOWNLOADS_FILE, default={})
    return data if isinstance(data, dict) else {}


def is_downloaded(code: str) -> bool:
    return code in _registry().get("done", {})


def downloaded_info(code: str) -> dict | None:
    """Registro de una descarga hecha: {pedido, po, portal, zip, folder, eml, when} o None."""
    return _registry().get("done", {}).get(code)


def download_status(sender: str, subject: str) -> dict:
    """Para la lista de Devoluciones: {code, downloadable, downloaded, folder}."""
    info = describe_email(sender, subject)
    if info is None:
        return {"code": "", "downloadable": False, "downloaded": False, "folder": ""}
    done = downloaded_info(info["code"])
    return {"code": info["code"], "downloadable": True, "downloaded": done is not None,
            "folder": (done or {}).get("folder", ""),
            "dev_folders": list((done or {}).get("dev_folders") or [])}


def _mark_done(code: str, info: dict) -> None:
    reg = _registry()
    reg.setdefault("done", {})[code] = info
    reg.get("errors", {}).pop(code, None)
    write_json(PORTAL_DOWNLOADS_FILE, reg)


def _update_done(code: str, extra: dict) -> None:
    reg = _registry()
    entry = reg.setdefault("done", {}).get(code)
    if entry is not None:
        entry.update(extra)
        write_json(PORTAL_DOWNLOADS_FILE, reg)


def _mark_error(code: str, msg: str) -> None:
    reg = _registry()
    entry = reg.setdefault("errors", {}).setdefault(code, {"count": 0})
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last"] = datetime.now().isoformat(timespec="seconds")
    entry["msg"] = msg[:300]
    write_json(PORTAL_DOWNLOADS_FILE, reg)


def _attempts(code: str) -> int:
    return int(_registry().get("errors", {}).get(code, {}).get("count", 0))


# ── Carpetas del pedido ───────────────────────────────────────────────────────

_NUM_RE = re.compile(r"^(\d{3,4})\b")
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def trans_root(pedido: str) -> Path | None:
    """Carpeta `00 TRANS Y RES` del pedido (la crea si falta). None si no se
    localiza el pedido o la unidad de red no está accesible."""
    from core.services import apertura

    base = Path(PEDIDOS_BASE_PATH) if PEDIDOS_BASE_PATH else apertura.DEFAULT_BASE_DIR
    if not base.exists():
        logger.info("Base de pedidos no accesible (%s)", base)
        return None
    doc_dir = apertura.find_documentacion_dir(pedido, base_dir=base, create=True)
    if doc_dir is None:
        return None
    root = doc_dir / TRANS_FOLDER
    try:
        root.mkdir(exist_ok=True)
    except OSError as exc:
        logger.warning("No se pudo crear %s: %s", root, exc)
        return None
    return root


def existing_zip(root: Path, code: str) -> Path | None:
    """El zip de la devolución si ya está en `root` o en alguna de sus subcarpetas."""
    name = f"{code}.zip".lower()
    try:
        for entry in root.iterdir():
            if entry.is_file() and entry.name.lower() == name:
                return entry
            if entry.is_dir():
                for f in entry.iterdir():
                    if f.is_file() and f.name.lower() == name:
                        return f
    except OSError:
        pass
    return None


def next_folder(root: Path, when: datetime | None = None) -> Path:
    """Crea y devuelve la siguiente subcarpeta `NNN (DD-MM-YYYY)`, respetando el
    ancho de numeración que ya use el pedido (3 dígitos por defecto)."""
    nums, width = [], 3
    for d in root.iterdir():
        m = _NUM_RE.match(d.name)
        if d.is_dir() and m:
            nums.append(int(m.group(1)))
            width = max(width, len(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    when = when or datetime.now()
    folder = root / f"{n:0{width}d} ({when:%d-%m-%Y})"
    folder.mkdir()
    return folder


def safe_filename(name: str, limit: int = 150) -> str:
    cleaned = _BAD_CHARS.sub("_", name or "").strip(" .")
    return (cleaned or "correo")[:limit]


def _remove_if_empty(folder: Path) -> None:
    try:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass


# ── Descarga ──────────────────────────────────────────────────────────────────

def download_for_email(uid: str, folder: str = "INBOX", *, session=None) -> dict:
    """Descarga la devolución del correo `uid` a la carpeta de su pedido y guarda
    también el correo. `session`: sesión de eGesDoc ya abierta (opcional)."""
    from core.services import transmittal

    pv = transmittal.preview_email(uid, folder)
    subject = pv.get("subject", "")
    info = describe_email(pv.get("from", ""), subject)
    if info is None:
        raise ValueError("Este correo no es una devolución descargable "
                         "(solo Técnicas Reunidas, AYESA y SACYR)")
    ok, why = portal_ready(info["portal"])
    if not ok:
        raise RuntimeError(why)
    docs = pv.get("documents") or []
    pedido = str((docs[0].get("Nº Pedido") if docs else "") or "").strip()
    if not pedido:
        raise LookupError("No sé a qué pedido pertenece esta devolución (no está en el ERP)")

    raw = imap_service.fetch_raw(uid, folder)
    code = info["code"]
    file_docs: dict[str, dict] = {}
    if info["portal"] == "egesdoc":
        hint = egesdoc.parse_subject(subject)["project"] or None

        def fetch(dest: Path) -> Path:
            return egesdoc.download_transmittal(info["po"], code, dest, project_hint=hint, session=session)

        # Los ficheros del zip de TR van con id interno: se pide al portal el
        # nombre de cada documento para poder archivarlos en su carpeta dev.
        try:
            file_docs = egesdoc.transmittal_file_map(info["po"], code, project_hint=hint, session=session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("eGesDoc: no se pudo obtener el mapa de ficheros de %s: %s", code, exc)
    elif info["portal"] == "sacyr":
        def fetch(dest: Path) -> Path:
            return sacyr.collect(code, dest)

        # Los ficheros de SACYR llevan el código del documento con la barra
        # cambiada, así que se emparejan por el nº de orden final.
        try:
            file_docs = sacyr.file_map(code, docs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SACYR: no se pudo emparejar los ficheros de %s: %s", code, exc)
    else:
        html = imap_service.get_html_body(email.message_from_bytes(raw)) or ""
        url = ayesa.download_link(html)
        if not url:
            raise LookupError("El correo de AYESA no trae el enlace «Clic aquí para descargar»")

        def fetch(dest: Path) -> Path:
            return ayesa.download(url, dest, code)

    res = download(code, pedido, fetch, subject=subject, raw_email=raw,
                   portal=info["portal"], po=info["po"])
    # Segundo paso: archivar los PDF devueltos en 2-Tecnico\dev. <Tipo>\rev<N> AP|COM
    # (copia; el zip de 00 TRANS Y RES queda intacto). Nunca hace fallar la descarga.
    try:
        from core.services import dev_folders
        res["archive"] = dev_folders.archive_return(res["zip"], docs, pedido, email_raw=raw,
                                                    email_date=pv.get("date", ""), file_docs=file_docs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Archivo en dev. de %s falló: %s", code, exc)
        res["archive"] = {"archived": [], "skipped": [(res["zip"].name, str(exc))], "created": [], "plan": []}
    # Carpetas dev. donde quedaron los PDF: se apuntan para poder abrirlas luego.
    res["dev_folders"] = sorted({str(Path(dest).parent) for _, dest in res["archive"]["archived"]})
    if res["dev_folders"]:
        _update_done(code, {"dev_folders": res["dev_folders"]})
    return res


def download(code: str, pedido: str, fetch: Callable[[Path], Path], *, subject: str = "",
             raw_email: bytes | None = None, portal: str = "", po: str = "") -> dict:
    """Baja el paquete (`fetch(dest_dir)` → ruta del zip) a la siguiente carpeta
    `NNN (fecha)` del pedido y, si hay `raw_email`, guarda el correo como .eml.

    Devuelve {code, po, pedido, portal, zip, folder, eml, already}. `already=True`
    si el zip ya existía (no se descarga de nuevo ni se crea carpeta).
    """
    root = trans_root(pedido)
    if root is None:
        raise FileNotFoundError(f"No se localiza la carpeta del pedido {pedido} (¿unidad M: conectada?)")

    found = existing_zip(root, code)
    if found is not None:
        res = {"code": code, "po": po, "pedido": pedido, "portal": portal, "zip": found,
               "folder": found.parent, "eml": None, "already": True}
        _mark_done(code, _info(res))
        return res

    dest = next_folder(root)
    try:
        zip_path = fetch(dest)
        eml_path = None
        if raw_email:
            try:
                eml_path = dest / (safe_filename(subject or code) + ".eml")
                eml_path.write_bytes(raw_email)
            except Exception as exc:  # noqa: BLE001 — el zip ya está; el correo es un extra
                logger.warning("No se pudo guardar el correo junto a %s: %s", code, exc)
    except Exception:
        _remove_if_empty(dest)     # no dejar un "NNN (fecha)" vacío si falla
        raise

    res = {"code": code, "po": po, "pedido": pedido, "portal": portal, "zip": zip_path,
           "folder": dest, "eml": eml_path, "already": False}
    _mark_done(code, _info(res))
    logger.info("Devolución %s (%s) guardada en %s", code, PORTAL_NAMES.get(portal, portal), dest)
    return res


def _info(res: dict) -> dict:
    return {
        "pedido": res["pedido"], "po": res["po"], "portal": res["portal"],
        "zip": str(res["zip"]), "folder": str(res["folder"]),
        "eml": str(res["eml"]) if res.get("eml") else None,
        "when": datetime.now().isoformat(timespec="seconds"),
    }


# ── Automático (job del scheduler) ────────────────────────────────────────────

def pending_emails(days: int = 7) -> list[dict]:
    """Correos de devolución de los últimos `days` días cuyo paquete aún no
    está descargado: [{uid, subject, from, date, portal, code, po}]."""
    out = []
    from core.services.transmittal import is_noise_email

    for e in imap_service.list_since(days=days):
        if is_noise_email(e):
            continue
        info = describe_email(e.get("from", ""), e.get("subject") or "")
        if info is None or is_downloaded(info["code"]):
            continue
        out.append({**e, **info})
    return out


def auto_download(days: int = 7, *, force: bool = False) -> list[dict]:
    """Descarga todas las devoluciones pendientes. Silencioso si está desactivado
    (salvo `force`, que lo lanza igualmente)."""
    if not force and not enabled():
        return []
    try:
        pending = pending_emails(days)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Descarga automática: no se pudo leer el buzón: %s", exc)
        return []
    pending = [e for e in pending if (force or _attempts(e["code"]) < MAX_AUTO_ATTEMPTS)
               and portal_ready(e["portal"])[0]]
    if not pending:
        return []

    results: list[dict] = []
    session = None                     # sesión eGesDoc, solo si hace falta
    egesdoc_down = False
    try:
        for e in pending:
            if e["portal"] == "egesdoc":
                if egesdoc_down:
                    continue
                if session is None:
                    try:
                        session = egesdoc.login()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Descarga automática: eGesDoc no abre sesión: %s", exc)
                        egesdoc_down = True
                        continue
            try:
                res = download_for_email(e["uid"], session=session)
                results.append(res)
                _notify(res)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Descarga automática: %s → %s", e["code"], exc)
                _mark_error(e["code"], str(exc))
    finally:
        if session is not None:
            session.close()
    return results
