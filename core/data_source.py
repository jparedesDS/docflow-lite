"""Gestión de las fuentes de datos (data_erp.xlsx, consulta_erp.xlsx).

Dos modos:
- **Importar**: copia el archivo origen a `data/<kind>.xlsx` y elimina vínculo.
- **Vincular**: guarda el path externo en preferences. La app lo lee desde ahí
  (útil si el archivo está en una unidad compartida que se actualiza solo).

Resolución de paths (prioridad descendente):
1. Override en preferences (modo "vincular")
2. Path por defecto en `data/<kind>.xlsx`
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from core.config import CONSULTA_ERP_PATH, DATA_ERP_PATH
from core.preferences import get, set_value

logger = logging.getLogger(__name__)

# Kinds soportados (clave en preferences = "<kind>_path")
_KINDS: dict[str, str] = {
    "data_erp":     DATA_ERP_PATH,
    "consulta_erp": CONSULTA_ERP_PATH,
}

_LABELS = {
    "data_erp":     "data_erp.xlsx",
    "consulta_erp": "consulta_erp.xlsx",
}


def label(kind: str) -> str:
    return _LABELS.get(kind, kind)


# ─── Path resolution ─────────────────────────────────────────────────────────

def get_effective_path(kind: str) -> str:
    """Path que la app usa para leer este Excel.

    Si hay vínculo y el archivo existe, lo devuelve. Si no, el default local.
    """
    if kind not in _KINDS:
        raise ValueError(f"kind desconocido: {kind}")
    override = (get(f"{kind}_path") or "").strip()
    if override and os.path.exists(override):
        return override
    return _KINDS[kind]


def get_linked_path(kind: str) -> str | None:
    """Path vinculado configurado en preferences (existe o no), o None."""
    if kind not in _KINDS:
        raise ValueError(f"kind desconocido: {kind}")
    override = (get(f"{kind}_path") or "").strip()
    return override or None


# ─── Mutaciones ──────────────────────────────────────────────────────────────

def import_file(kind: str, source_path: str) -> str:
    """Copia source_path a la ubicación por defecto data/<kind>.xlsx.

    Limpia cualquier vínculo previo (la app usará la copia local).
    Devuelve el path destino.
    """
    if kind not in _KINDS:
        raise ValueError(f"kind desconocido: {kind}")
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"No existe: {source_path}")
    if not src.is_file():
        raise ValueError("La ruta seleccionada no es un archivo.")

    target = Path(_KINDS[kind])
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    logger.info("Importado %s -> %s", src, target)
    clear_link(kind)
    return str(target)


def set_linked_path(kind: str, path: str) -> None:
    """Vincula un path externo. La app leerá desde ahí en cada arranque."""
    if kind not in _KINDS:
        raise ValueError(f"kind desconocido: {kind}")
    if not path:
        raise ValueError("path vacío")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No existe: {path}")
    set_value(f"{kind}_path", path)
    logger.info("Vinculado %s -> %s", kind, path)


def clear_link(kind: str) -> None:
    """Quita el vínculo externo. La app volverá al path local por defecto."""
    if kind not in _KINDS:
        raise ValueError(f"kind desconocido: {kind}")
    set_value(f"{kind}_path", None)


def remove_local_copy(kind: str) -> bool:
    """Elimina la copia local data/<kind>.xlsx (sin tocar el vínculo).

    Devuelve True si había archivo y se borró, False si no existía.
    """
    if kind not in _KINDS:
        raise ValueError(f"kind desconocido: {kind}")
    target = Path(_KINDS[kind])
    if target.exists():
        target.unlink()
        return True
    return False


# ─── Estado / metadatos ──────────────────────────────────────────────────────

def get_status(kind: str) -> dict:
    """Estado del archivo: path activo, modo (local|linked), existe, tamaño, mtime."""
    if kind not in _KINDS:
        raise ValueError(f"kind desconocido: {kind}")

    linked = get_linked_path(kind)
    if linked and os.path.exists(linked):
        path = linked
        mode = "linked"
    elif linked:
        # vínculo configurado pero el archivo no existe
        path = linked
        mode = "linked_broken"
    else:
        path = _KINDS[kind]
        mode = "local"

    exists = os.path.exists(path)
    info: dict = {
        "kind": kind,
        "label": _LABELS[kind],
        "path": path,
        "mode": mode,
        "exists": exists,
        "size": 0,
        "modified": None,
        "linked_path": linked,
    }
    if exists:
        try:
            st = os.stat(path)
            info["size"] = st.st_size
            info["modified"] = datetime.fromtimestamp(st.st_mtime).isoformat()
        except OSError:
            pass
    return info


def get_all_status() -> list[dict]:
    return [get_status(k) for k in _KINDS]
