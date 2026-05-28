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

# Iniciales autorizadas a iniciar sesión. Subconjunto de config.USERS.
# El resto sigue siendo válido para mappings de emails / responsables pero
# no puede entrar en la app. Para habilitar a otro DC, añade su inicial aquí
# y reempaqueta — los hashes se generan en el primer arranque.
ALLOWED_LOGIN_INITIALS: set[str] = {"JP"}


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
    """Crea un usuario por cada inicial autorizada con password por defecto.

    Sólo procesa iniciales en ALLOWED_LOGIN_INITIALS (que también deben existir
    en config.USERS). El resto de USERS no obtiene cuenta de login.
    """
    data = _load()
    allowed = {i.upper() for i in ALLOWED_LOGIN_INITIALS}

    if data["users"]:
        # Añadir los que falten y limpiar los que ya no estén autorizados
        existing = {u.get("initials", "").upper() for u in data["users"]}
        new_users = []
        for initials, info in USERS.items():
            ini = initials.upper()
            if ini in existing or ini not in allowed:
                continue
            new_users.append(_build_seed_user(initials, info))
        if new_users:
            data["users"].extend(new_users)
            logger.info("Auth: %d usuarios nuevos añadidos al seed", len(new_users))

        # Filtrar a los autorizados (revoca cuentas que ya no están en la lista)
        before = len(data["users"])
        data["users"] = [u for u in data["users"] if u.get("initials", "").upper() in allowed]
        if len(data["users"]) != before:
            logger.info(
                "Auth: revocadas %d cuentas no autorizadas",
                before - len(data["users"]),
            )

        _save(data)
        return

    # Primer arranque — crear sólo los autorizados que existan en config.USERS
    data["users"] = [
        _build_seed_user(k, v)
        for k, v in USERS.items()
        if k.upper() in allowed
    ]
    _save(data)
    logger.info(
        "Auth: seed inicial de %d usuario(s) autorizado(s) (password por defecto)",
        len(data["users"]),
    )


def _build_seed_user(initials: str, info: dict) -> dict:
    emails = info.get("emails") or []
    return {
        "initials": initials,
        "nombre": info.get("nombre", initials),
        "email": emails[0] if emails else "",
        "password_hash": hash_password(DEFAULT_PASSWORD),
        "must_change_password": True,
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
    # Defensa en profundidad: rechazar si las iniciales no están autorizadas,
    # incluso si por alguna razón hubiera un hash en users.json (ej. archivo
    # editado manualmente).
    if initials.upper().strip() not in {i.upper() for i in ALLOWED_LOGIN_INITIALS}:
        return None, "Usuario no autorizado."

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
