"""Sesión activa — usuario autenticado + helpers de permisos.

La app llama a set_user() tras el login; cualquier vista puede consultar
can_view/can_manage sin acoplarse a la ventana principal.
"""

from __future__ import annotations

from typing import Optional

from core import auth

_user: Optional[dict] = None


def set_user(user: Optional[dict]) -> None:
    global _user
    _user = user


def current() -> Optional[dict]:
    return _user


def is_admin() -> bool:
    return auth.is_admin(_user)


def can_view(section: str) -> bool:
    return auth.can_view(_user, section)


def can_manage(section: str) -> bool:
    # Si no hay sesión establecida (p.ej. tests), no bloqueamos.
    if _user is None:
        return True
    return auth.can_manage(_user, section)
