"""Preferencias de usuario persistidas en state/preferences.json.

Centralizado: tema, futuras opciones (idioma, usuario activo, etc.).
"""

from __future__ import annotations

import logging

from core.paths import state_dir
from core.utils.json_store import read_json, write_json

logger = logging.getLogger(__name__)

PREFS_FILE = str(state_dir() / "preferences.json")

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
    data = read_json(PREFS_FILE, default=dict(_DEFAULTS))
    if not isinstance(data, dict):
        data = dict(_DEFAULTS)
    for k, v in _DEFAULTS.items():
        data.setdefault(k, v)
    return data


def get_all() -> dict:
    return _load()


def get(key: str, default=None):
    return _load().get(key, default)


def set_value(key: str, value) -> None:
    data = _load()
    data[key] = value
    write_json(PREFS_FILE, data)


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
