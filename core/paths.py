"""Resolución de rutas — funciona en modo desarrollo y empaquetado con PyInstaller."""

import os
import sys
from pathlib import Path


def app_root() -> Path:
    """Carpeta base de la aplicación.

    - En desarrollo: carpeta padre de `core/` (docflow-lite/)
    - Empaquetado (PyInstaller --onefile): la carpeta donde está el .exe
    - Empaquetado (--onedir): la carpeta del .exe también
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def resource_path(rel: str) -> Path:
    """Recursos empaquetados de solo lectura (HTML, CSS, JS) — usa _MEIPASS si está congelado."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / rel
    return Path(__file__).resolve().parent.parent / rel


def data_dir() -> Path:
    """Carpeta de datos del usuario (Excels). Configurable vía DATA_DIR env."""
    override = os.getenv("DATA_DIR", "").strip()
    if override:
        return Path(override)
    return app_root() / "data"


def state_dir() -> Path:
    """Carpeta de estado runtime (processed_emails.json, logs)."""
    override = os.getenv("STATE_DIR", "").strip()
    p = Path(override) if override else app_root() / "state"
    p.mkdir(parents=True, exist_ok=True)
    return p


def ui_dir() -> Path:
    """Carpeta de assets UI (servida por FastAPI)."""
    return resource_path("ui")
