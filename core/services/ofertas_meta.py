"""Metadatos de gestión de ofertas — el control comercial sobre cada RFQ.

Los correos son la fuente (solo lectura); aquí guardamos NUESTROS datos de
gestión, enlazados por una clave estable (Message-ID preferentemente):

  estado · asignado · cliente · importe · fecha límite · probabilidad · notas ·
  pedido vinculado.

Persistido en state/ofertas_meta.json (gitignored). Caché en memoria + escritura
write-through (las ediciones son puntuales, no por tecla).
"""

from __future__ import annotations

import threading
import time

from core.paths import state_dir
from core.utils.json_store import read_json, write_json

_FILE = str(state_dir() / "ofertas_meta.json")
_lock = threading.RLock()
_cache: dict | None = None

# Embudo comercial (orden = avance del pipeline)
ESTADOS = ["Nueva", "En estudio", "Ofertada", "Ganada", "Perdida", "Descartada"]
ESTADO_COLOR = {
    "Nueva":      "#2563EB",
    "En estudio": "#D97706",
    "Ofertada":   "#6366F1",
    "Ganada":     "#16A34A",
    "Perdida":    "#DC2626",
    "Descartada": "#94A3B8",
}
# Estados que cuentan como "cerradas" (ya no requieren seguimiento)
CERRADOS = {"Ganada", "Perdida", "Descartada"}

_FIELDS = ("estado", "asignado", "cliente", "importe", "deadline",
           "probabilidad", "notas", "pedido")


def _load() -> dict:
    global _cache
    with _lock:
        if _cache is None:
            data = read_json(_FILE, default={})
            _cache = data if isinstance(data, dict) else {}
        return _cache


def get(key: str) -> dict:
    """Metadatos de una oferta (dict vacío si no hay)."""
    if not key:
        return {}
    return dict(_load().get(key, {}))


def get_all() -> dict:
    return dict(_load())


def set_fields(key: str, **fields) -> None:
    """Actualiza/crea los metadatos de una oferta y persiste."""
    if not key:
        return
    with _lock:
        data = _load()
        cur = dict(data.get(key, {}))
        for k, v in fields.items():
            if k in _FIELDS:
                cur[k] = v
        cur["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        data[key] = cur
        write_json(_FILE, data)


def estado_of(key: str) -> str:
    return get(key).get("estado") or "Nueva"
