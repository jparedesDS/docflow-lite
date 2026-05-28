"""Communication Matrix para reclamaciones.

Asocia cada pedido (P-XX/YYY) con su lista oficial de destinatarios TO + CC.
Distinto de `claim_recipients.json` que guarda el ÚLTIMO ENVÍO real (histórico):
la matrix es la fuente "canónica" pre-configurada, que se usa como segunda
prioridad después de los recipients que el usuario meta a mano.

Prioridad de resolución en send_claim:
1. To/Cc explícitos
2. Communication Matrix
3. Último envío (claim_recipients.json)
4. Auto-detect por nivel de escalation

Persistencia: state/comm_matrix.json
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from core.paths import state_dir
from core.utils.json_store import read_json, write_json

logger = logging.getLogger(__name__)

MATRIX_FILE = str(state_dir() / "comm_matrix.json")


# ── Regex de parsing ─────────────────────────────────────────────────────────

# Cualquier secuencia que parezca un email. Tolerante: . _ - + en local part,
# y cualquier subdominio razonable.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Línea que SOLO contiene un pedido tipo P-25/023 (case-insensitive).
_PEDIDO_RE = re.compile(r"^(P-\d{2}/\d{3})\s*$", re.IGNORECASE)

# Inicio de línea TO: o CC: (con o sin espacio, mayúsculas/minúsculas).
_TO_RE = re.compile(r"^TO\s*:", re.IGNORECASE)
_CC_RE = re.compile(r"^CC\s*:", re.IGNORECASE)


# ═══ Persistencia ═══════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    data = read_json(MATRIX_FILE, default={})
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    write_json(MATRIX_FILE, data)


# ═══ Parser del .txt ════════════════════════════════════════════════════════

def parse_txt(content: str) -> list[dict]:
    """Parsea el contenido de un .txt con bloques pedido / TO / CC.

    Devuelve una lista de dicts: [{"pedido", "to": [...], "cc": [...]}, ...].
    Si TO o CC continúan en líneas siguientes (no aparecen prefijos), las
    une al último bloque conocido.
    """
    pedidos: list[dict] = []
    current: dict | None = None
    last_section: str | None = None  # "to" | "cc"

    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            last_section = None
            continue

        m_pedido = _PEDIDO_RE.match(line)
        if m_pedido:
            if current:
                pedidos.append(current)
            current = {"pedido": m_pedido.group(1).upper(), "to": [], "cc": []}
            last_section = None
            continue

        if current is None:
            continue

        if _TO_RE.match(line):
            current["to"].extend(_EMAIL_RE.findall(line))
            last_section = "to"
        elif _CC_RE.match(line):
            current["cc"].extend(_EMAIL_RE.findall(line))
            last_section = "cc"
        elif last_section:
            # Continuación de la línea anterior (TO o CC partidos en varias líneas)
            current[last_section].extend(_EMAIL_RE.findall(line))

    if current:
        pedidos.append(current)

    # Dedup por orden de aparición
    for p in pedidos:
        p["to"] = _dedup(p["to"])
        p["cc"] = _dedup(p["cc"])
    return pedidos


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        key = x.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(x.strip())
    return out


# ═══ API pública ════════════════════════════════════════════════════════════

def get_contacts(pedido: str) -> dict | None:
    """Devuelve {to, cc, updatedAt} para un pedido, o None si no está en la matrix."""
    if not pedido:
        return None
    return _load().get(pedido.upper().strip())


def set_contacts(pedido: str, to: list[str], cc: list[str]) -> None:
    """Crea o sobreescribe los contactos de un pedido."""
    if not pedido:
        raise ValueError("Pedido vacío")
    data = _load()
    data[pedido.upper().strip()] = {
        "to": _dedup(to or []),
        "cc": _dedup(cc or []),
        "updatedAt": _now(),
    }
    _save(data)


def remove(pedido: str) -> bool:
    data = _load()
    key = (pedido or "").upper().strip()
    if key in data:
        del data[key]
        _save(data)
        return True
    return False


def list_pedidos() -> list[dict]:
    """Lista todos los pedidos en la matrix, ordenados desc por updatedAt."""
    data = _load()
    out = []
    for pedido, info in data.items():
        out.append({
            "pedido": pedido,
            "to": info.get("to") or [],
            "cc": info.get("cc") or [],
            "updatedAt": info.get("updatedAt") or "",
        })
    out.sort(key=lambda x: (x["updatedAt"] or "", x["pedido"]), reverse=True)
    return out


def import_from_txt(content: str) -> dict:
    """Importa pedidos desde el texto del .txt.

    Si un pedido ya existe en la matrix, se sobreescribe (el último prevalece).
    Si el mismo pedido aparece varias veces en el .txt, el último también
    prevalece.

    Returns:
        {
          "imported": N,           # número de pedidos guardados
          "updated":  M,           # de los anteriores, cuántos sobrescribieron
          "created":  N - M,
          "duplicates_in_input": list de pedidos duplicados en el .txt,
          "skipped":  list de pedidos saltados (sin emails),
        }
    """
    parsed = parse_txt(content)
    data = _load()

    seen_in_input: dict[str, int] = {}
    duplicates: list[str] = []
    skipped: list[str] = []
    created = updated = 0

    for entry in parsed:
        pedido = entry["pedido"]
        # Contar repeticiones en el input
        seen_in_input[pedido] = seen_in_input.get(pedido, 0) + 1

        if not entry["to"] and not entry["cc"]:
            skipped.append(pedido)
            continue

        existed = pedido in data
        data[pedido] = {
            "to": entry["to"],
            "cc": entry["cc"],
            "updatedAt": _now(),
        }
        if existed:
            updated += 1
        else:
            created += 1

    for p, n in seen_in_input.items():
        if n > 1:
            duplicates.append(p)

    _save(data)
    return {
        "imported": created + updated,
        "created": created,
        "updated": updated,
        "duplicates_in_input": duplicates,
        "skipped": skipped,
    }


def stats() -> dict:
    data = _load()
    return {"total_pedidos": len(data)}
