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
    "theme": "dark",  # "light" | "dark"
}

_VALID_THEMES = {"light", "dark"}


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
    """Devuelve 'light' o 'dark'. Cualquier valor inválido se trata como 'dark'."""
    t = get("theme", "dark")
    return t if t in _VALID_THEMES else "dark"


def set_theme(value: str) -> None:
    if value not in _VALID_THEMES:
        raise ValueError(f"Theme inválido: {value}")
    set_value("theme", value)
