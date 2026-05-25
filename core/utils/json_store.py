"""Thread/process-safe JSON file read/write (cross-platform: Windows + Linux)."""

import json
import os
import sys
from contextlib import contextmanager

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import msvcrt
else:
    import fcntl


@contextmanager
def _file_lock(path: str):
    """Acquire an exclusive lock via a .lock companion file."""
    lock_path = path + ".lock"
    lf = open(lock_path, "a+b")
    try:
        if _IS_WINDOWS:
            lf.seek(0)
            if lf.read(1) == b"":
                lf.write(b"\x00")
                lf.flush()
            lf.seek(0)
            msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lf.seek(0)
                msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
    finally:
        lf.close()


def read_json(path, default=None):
    """Read a JSON file. Returns *default* (or ``[]``) if missing or corrupt."""
    if default is None:
        default = []
    path = str(path)
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        return default


def write_json(path, data):
    """Write *data* as JSON atomically, holding an exclusive lock."""
    path = str(path)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with _file_lock(path):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
