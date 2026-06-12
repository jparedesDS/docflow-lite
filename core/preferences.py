"""Preferencias de usuario persistidas en state/preferences.json.

Centralizado: tema, futuras opciones (idioma, usuario activo, etc.).

Rendimiento: el fichero vive en state/ (que puede estar en una unidad de red,
p.ej. U:\\), donde cada lectura/escritura cuesta decenas/cientos de ms. Por eso
este módulo mantiene una CACHÉ en memoria (se lee del disco una sola vez) y las
escrituras son WRITE-BEHIND: set_value() actualiza la caché al instante y
programa un volcado a disco en un hilo de fondo (agrupando ráfagas). flush()
fuerza el volcado pendiente — llamarlo al cerrar la app.
"""

from __future__ import annotations

import logging
import threading

from core.paths import state_dir
from core.utils.json_store import read_json, write_json

logger = logging.getLogger(__name__)

PREFS_FILE = str(state_dir() / "preferences.json")

_WRITE_DELAY = 0.8  # s — agrupa ráfagas de set_value en una sola escritura

_lock = threading.RLock()
_cache: dict | None = None
_dirty = False
_flush_timer: threading.Timer | None = None

_DEFAULTS: dict = {
    "theme": "dark",  # "light" | "dark" | "light-coral" | "dark-coral"
}

# 4 modos disponibles:
#   light        — Linear/Vercel claro (indigo)
#   dark         — Linear/Vercel oscuro (indigo)
#   light-coral  — Cream + coral, estilo terminal (monospace)
#   dark-coral   — Warm dark + coral, estilo terminal (monospace)
_VALID_THEMES = {"light", "dark", "light-coral", "dark-coral"}

# Migración de nombres antiguos → nuevos
_THEME_ALIASES = {
    "light-claude": "light-coral",
    "dark-claude":  "dark-coral",
}


def is_coral_theme(value: str) -> bool:
    return value in ("light-coral", "dark-coral")


def base_mode(value: str) -> str:
    """Devuelve 'light' o 'dark' para mapear a CustomTkinter.appearance_mode."""
    return "light" if value.startswith("light") else "dark"


def _load() -> dict:
    """Devuelve la caché (leyendo del disco solo la primera vez)."""
    global _cache
    with _lock:
        if _cache is None:
            data = read_json(PREFS_FILE, default=dict(_DEFAULTS))
            if not isinstance(data, dict):
                data = dict(_DEFAULTS)
            for k, v in _DEFAULTS.items():
                data.setdefault(k, v)
            _cache = data
        return _cache


def _schedule_flush() -> None:
    """Programa el volcado a disco (agrupando ráfagas) en un hilo de fondo."""
    global _flush_timer
    if _flush_timer is not None:
        _flush_timer.cancel()
    _flush_timer = threading.Timer(_WRITE_DELAY, flush)
    _flush_timer.daemon = True
    _flush_timer.start()


def flush() -> None:
    """Vuelca a disco los cambios pendientes (no-op si no hay nada que escribir)."""
    global _dirty, _flush_timer
    with _lock:
        if _flush_timer is not None:
            _flush_timer.cancel()
            _flush_timer = None
        if not _dirty or _cache is None:
            return
        snapshot = dict(_cache)
        _dirty = False
    try:
        write_json(PREFS_FILE, snapshot)
    except Exception as exc:
        logger.warning("No se pudieron guardar las preferencias: %s", exc)


def get_all() -> dict:
    with _lock:
        return dict(_load())


def get(key: str, default=None):
    with _lock:
        return _load().get(key, default)


def set_value(key: str, value) -> None:
    """Actualiza la caché al instante; el disco se escribe en segundo plano."""
    global _dirty
    with _lock:
        data = _load()
        if data.get(key) == value:
            return  # sin cambios → sin escritura
        data[key] = value
        _dirty = True
        _schedule_flush()


def get_theme() -> str:
    """Devuelve uno de los 4 modos válidos. Migra alias antiguos transparentemente."""
    t = get("theme", "dark")
    # Migración suave: si encontramos un nombre antiguo, lo remapeamos y guardamos
    if t in _THEME_ALIASES:
        t = _THEME_ALIASES[t]
        try:
            set_value("theme", t)
        except Exception:
            pass
    return t if t in _VALID_THEMES else "dark"


def set_theme(value: str) -> None:
    # Acepta alias antiguos para llamadas externas
    value = _THEME_ALIASES.get(value, value)
    if value not in _VALID_THEMES:
        raise ValueError(f"Theme inválido: {value}")
    set_value("theme", value)
