"""Almacén de secretos híbrido — keyring (Windows Credential Manager) o cifrado local.

Prioridad de lectura:
  1. keyring (Administrador de credenciales del SO) si está instalado.
  2. Fichero local cifrado state/secrets.enc (cryptography/Fernet).
  3. Variable de entorno / .env (compatibilidad y migración).

`set()`/`delete()` escriben en el backend preferente (keyring si está, si no
cifrado local). Así las contraseñas dejan de vivir en texto plano en .env.
"""

from __future__ import annotations

import json
import logging
import os

from core.paths import state_dir

logger = logging.getLogger(__name__)

SERVICE = "DocFlowLite"
_ENC_FILE = state_dir() / "secrets.enc"
_KEY_FILE = state_dir() / ".secretkey"


# ── Backend keyring (opcional) ────────────────────────────────────────────────

def _keyring():
    try:
        import keyring
        # Verifica que haya un backend usable
        keyring.get_keyring()
        return keyring
    except Exception:
        return None


def backend_name() -> str:
    return "Administrador de credenciales (keyring)" if _keyring() else "Cifrado local"


# ── Backend cifrado local (cryptography/Fernet) ───────────────────────────────

def _fernet():
    from cryptography.fernet import Fernet
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_bytes()
    else:
        key = Fernet.generate_key()
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_bytes(key)
        try:
            os.chmod(_KEY_FILE, 0o600)
        except Exception:
            pass
    return Fernet(key)


def _enc_load() -> dict:
    if not _ENC_FILE.exists():
        return {}
    try:
        data = _fernet().decrypt(_ENC_FILE.read_bytes())
        return json.loads(data.decode("utf-8"))
    except Exception as exc:
        logger.warning("No se pudo leer secrets.enc: %s", exc)
        return {}

def _enc_save(d: dict) -> None:
    blob = _fernet().encrypt(json.dumps(d).encode("utf-8"))
    _ENC_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ENC_FILE.write_bytes(blob)
    try:
        os.chmod(_ENC_FILE, 0o600)
    except Exception:
        pass


# ── API pública ───────────────────────────────────────────────────────────────

def get(key: str, env_fallback: str | None = None) -> str:
    """Devuelve el secreto (keyring → cifrado local → env). '' si no existe."""
    kr = _keyring()
    if kr:
        try:
            v = kr.get_password(SERVICE, key)
            if v:
                return v
        except Exception as exc:
            logger.debug("keyring get falló (%s): %s", key, exc)
    v = _enc_load().get(key)
    if v:
        return v
    if env_fallback:
        return os.getenv(env_fallback, "") or ""
    return ""


def set(key: str, value: str) -> None:
    """Guarda el secreto en el backend preferente. value='' lo elimina."""
    if value == "":
        delete(key)
        return
    kr = _keyring()
    if kr:
        try:
            kr.set_password(SERVICE, key, value)
            return
        except Exception as exc:
            logger.warning("keyring set falló (%s): %s — uso cifrado local", key, exc)
    d = _enc_load()
    d[key] = value
    _enc_save(d)


def delete(key: str) -> None:
    kr = _keyring()
    if kr:
        try:
            kr.delete_password(SERVICE, key)
        except Exception:
            pass
    d = _enc_load()
    if key in d:
        d.pop(key, None)
        _enc_save(d)


def is_set(key: str, env_fallback: str | None = None) -> bool:
    return bool(get(key, env_fallback))
