"""Autenticación local — usuarios + hashes en state/users.json.

Diseño:
- Hash con PBKDF2-SHA256 (stdlib, sin dependencias C).
- Seed automático: al primer arranque crea un user por cada entrada de USERS
  (config.py) con password por defecto "Aa123456" y must_change_password=True.
- Sesión NO persistente: el caller mantiene `current_user` en memoria; al
  cerrar la app se pierde y hay que volver a hacer login.
- Todos los usuarios del config son Document Controllers válidos.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from core.config import USERS
from core.paths import state_dir
from core.utils.json_store import read_json, write_json

logger = logging.getLogger(__name__)

USERS_FILE = str(state_dir() / "users.json")

DEFAULT_PASSWORD = "Aa123456"
PBKDF2_ITERATIONS = 200_000

# El rol administrador (gestiona usuarios y permisos) es exclusivo de JP.
ADMIN_INITIALS: set[str] = {"JP"}

# Secciones gobernables por permisos (claves de navegación del sidebar).
# 'home' siempre es visible; 'ajustes' es exclusivo del admin.
SECTION_KEYS: list[str] = [
    "apertura", "agenda", "inbox", "ofertas", "documentos", "pedidos",
    "devoluciones", "reclamaciones", "docusign", "informes", "reportes",
]
PERM_LEVELS = ("none", "ver", "gestionar")


def _all_perms(level: str) -> dict:
    return {k: level for k in SECTION_KEYS}


# ═══ Password hashing (PBKDF2-SHA256, stdlib) ═══════════════════════════════

def hash_password(plain: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Devuelve un hash con formato `pbkdf2_sha256$iters$salt_b64$hash_b64`."""
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iterations)
    return (
        f"pbkdf2_sha256${iterations}"
        f"${base64.b64encode(salt).decode()}"
        f"${base64.b64encode(h).decode()}"
    )


def verify_password(plain: str, stored: str) -> bool:
    """Verifica un password contra el hash almacenado (constant-time compare)."""
    try:
        algo, iters_str, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_str)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        candidate = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iters)
        return secrets.compare_digest(candidate, expected)
    except (ValueError, TypeError):
        return False


# ═══ Persistencia de usuarios ════════════════════════════════════════════════

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    data = read_json(USERS_FILE, default=None)
    if not isinstance(data, dict) or "users" not in data:
        return {"users": []}
    return data


def _save(data: dict) -> None:
    write_json(USERS_FILE, data)


def _seed_if_empty() -> None:
    """Asegura que existe el admin (JP) y migra registros antiguos.

    - Primer arranque: crea la cuenta JP (admin, gestiona todo).
    - Arranques posteriores: NO borra cuentas (las crea el admin desde Ajustes);
      solo garantiza que JP existe y rellena campos nuevos (permisos/is_admin).
    """
    data = _load()

    if not data["users"]:
        info = USERS.get("JP", {"nombre": "Jose Paredes", "emails": ["documentacion@eipsa.es"]})
        data["users"] = [_build_seed_user("JP", info, is_admin=True,
                                          permisos=_all_perms("gestionar"))]
        _save(data)
        logger.info("Auth: seed inicial — cuenta admin JP creada")
        return

    changed = False
    if not any(u.get("initials", "").upper() == "JP" for u in data["users"]):
        info = USERS.get("JP", {"nombre": "Jose Paredes", "emails": ["documentacion@eipsa.es"]})
        data["users"].append(_build_seed_user("JP", info, is_admin=True,
                                              permisos=_all_perms("gestionar")))
        changed = True
    # Migración de esquema: campos nuevos en cuentas existentes
    for u in data["users"]:
        ini = u.get("initials", "").upper()
        if "is_admin" not in u:
            u["is_admin"] = ini in {i.upper() for i in ADMIN_INITIALS}
            changed = True
        if "permisos" not in u or not isinstance(u.get("permisos"), dict):
            u["permisos"] = _all_perms("gestionar" if u.get("is_admin") else "ver")
            changed = True
        else:
            # añadir claves de sección que falten
            for k in SECTION_KEYS:
                if k not in u["permisos"]:
                    u["permisos"][k] = "gestionar" if u.get("is_admin") else "ver"
                    changed = True
    if changed:
        _save(data)


def _build_seed_user(initials: str, info: dict, is_admin: bool = False,
                     permisos: dict | None = None) -> dict:
    emails = info.get("emails") or []
    return {
        "initials": initials,
        "nombre": info.get("nombre", initials),
        "email": emails[0] if emails else "",
        "password_hash": hash_password(DEFAULT_PASSWORD),
        "must_change_password": True,
        "is_admin": is_admin,
        "permisos": permisos or _all_perms("ver"),
        "created_at": _now(),
        "last_login": None,
    }


# ═══ API pública ════════════════════════════════════════════════════════════

def initialize() -> None:
    """Asegura que existe el users.json y todas las iniciales del config."""
    _seed_if_empty()


def get_user(initials: str) -> Optional[dict]:
    """Busca un usuario por iniciales (case-insensitive)."""
    if not initials:
        return None
    target = initials.upper().strip()
    for u in _load()["users"]:
        if u.get("initials", "").upper() == target:
            return u
    return None


def list_users() -> list[dict]:
    """Lista todos los usuarios (sin hash de password)."""
    return [
        {k: v for k, v in u.items() if k != "password_hash"}
        for u in _load()["users"]
    ]


def login(initials: str, password: str) -> tuple[Optional[dict], Optional[str]]:
    """Verifica credenciales y devuelve (user, error_msg).

    Si OK: (user_dict, None). Si KO: (None, "mensaje de error").
    Actualiza last_login en disco al autenticar correctamente.
    """
    user = get_user(initials)
    if user is None:
        return None, "Usuario no encontrado. Revisa las iniciales."
    if not verify_password(password, user.get("password_hash", "")):
        return None, "Contraseña incorrecta."

    # Marcar last_login
    data = _load()
    for i, u in enumerate(data["users"]):
        if u.get("initials", "").upper() == user["initials"].upper():
            data["users"][i]["last_login"] = _now()
            break
    _save(data)

    return user, None


def change_password(initials: str, new_password: str, current_password: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """Cambia la contraseña de un usuario.

    Si `current_password` se pasa, lo verifica antes de cambiar.
    Si es None, asume que el caller ya autenticó (uso interno tras login).
    """
    user = get_user(initials)
    if user is None:
        return False, "Usuario no encontrado."

    if current_password is not None:
        if not verify_password(current_password, user.get("password_hash", "")):
            return False, "La contraseña actual no es correcta."

    if not new_password or len(new_password) < 6:
        return False, "La nueva contraseña debe tener al menos 6 caracteres."

    data = _load()
    for i, u in enumerate(data["users"]):
        if u.get("initials", "").upper() == user["initials"].upper():
            data["users"][i]["password_hash"] = hash_password(new_password)
            data["users"][i]["must_change_password"] = False
            break
    _save(data)
    return True, None


# ═══ Permisos / roles ════════════════════════════════════════════════════════

def is_admin(user: Optional[dict]) -> bool:
    if not user:
        return False
    return user.get("initials", "").upper() in {i.upper() for i in ADMIN_INITIALS}


def can_view(user: Optional[dict], section: str) -> bool:
    if section in ("home", "ajustes" if is_admin(user) else "__never__"):
        return True
    if is_admin(user):
        return True
    if not user:
        return False
    return (user.get("permisos") or {}).get(section, "none") in ("ver", "gestionar")


def can_manage(user: Optional[dict], section: str) -> bool:
    if is_admin(user):
        return True
    if not user:
        return False
    return (user.get("permisos") or {}).get(section, "none") == "gestionar"


# ═══ Gestión de cuentas (solo admin) ═════════════════════════════════════════

def create_user(initials: str, nombre: str, email: str = "",
                password: str | None = None, permisos: dict | None = None) -> tuple[bool, Optional[str]]:
    initials = (initials or "").strip().upper()
    if not initials:
        return False, "Indica unas iniciales."
    if get_user(initials):
        return False, f"Ya existe un usuario con iniciales {initials}."
    if password and len(password) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres."
    data = _load()
    perms = _all_perms("ver")
    if isinstance(permisos, dict):
        for k in SECTION_KEYS:
            if permisos.get(k) in PERM_LEVELS:
                perms[k] = permisos[k]
    data["users"].append({
        "initials": initials,
        "nombre": nombre or initials,
        "email": email or "",
        "password_hash": hash_password(password or DEFAULT_PASSWORD),
        "must_change_password": not password,
        "is_admin": False,
        "permisos": perms,
        "created_at": _now(),
        "last_login": None,
    })
    _save(data)
    return True, None


def update_user(initials: str, *, nombre: str | None = None, email: str | None = None,
                permisos: dict | None = None) -> tuple[bool, Optional[str]]:
    data = _load()
    target = initials.upper().strip()
    for u in data["users"]:
        if u.get("initials", "").upper() == target:
            if nombre is not None:
                u["nombre"] = nombre
            if email is not None:
                u["email"] = email
            if isinstance(permisos, dict):
                base = u.get("permisos") or _all_perms("ver")
                for k in SECTION_KEYS:
                    if permisos.get(k) in PERM_LEVELS:
                        base[k] = permisos[k]
                u["permisos"] = base
            _save(data)
            return True, None
    return False, "Usuario no encontrado."


def reset_password(initials: str, new_password: str) -> tuple[bool, Optional[str]]:
    if not new_password or len(new_password) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres."
    data = _load()
    target = initials.upper().strip()
    for u in data["users"]:
        if u.get("initials", "").upper() == target:
            u["password_hash"] = hash_password(new_password)
            u["must_change_password"] = True
            _save(data)
            return True, None
    return False, "Usuario no encontrado."


def delete_user(initials: str) -> tuple[bool, Optional[str]]:
    target = initials.upper().strip()
    if target in {i.upper() for i in ADMIN_INITIALS}:
        return False, "No se puede eliminar la cuenta administradora."
    data = _load()
    before = len(data["users"])
    data["users"] = [u for u in data["users"] if u.get("initials", "").upper() != target]
    if len(data["users"]) == before:
        return False, "Usuario no encontrado."
    _save(data)
    return True, None
