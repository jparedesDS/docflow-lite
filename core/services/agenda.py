"""Servicio Agenda — Notas, Reuniones y Tareas persistidas en JSON local.

Port de agenda_service.py del DocFlow grande, sin dependencia IMAP/IA.
Las tareas pueden sincronizarse con los docs pendientes del Monitoring.
"""

import logging
import uuid
from datetime import datetime, timezone

from core.paths import state_dir
from core.utils.json_store import read_json, write_json

logger = logging.getLogger(__name__)

AGENDA_FILE = str(state_dir() / "agenda_data.json")

TIPOS = ("notas", "reuniones", "tareas")
_DEFAULT = {"notas": [], "reuniones": [], "tareas": []}

ESTADOS_PENDIENTES = {"sin enviar", "", "com. menores", "com. mayores", "comentado", "rechazado"}
DEFAULT_OWNER = "JP"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    data = read_json(AGENDA_FILE, default=dict(_DEFAULT))
    if not isinstance(data, dict):
        return {k: [] for k in TIPOS}
    for k in TIPOS:
        data.setdefault(k, [])
    return data


def _save(data: dict) -> None:
    write_json(AGENDA_FILE, data)


# ── CRUD genérico ─────────────────────────────────────────────────────────────

def get_all(tipo: str) -> list[dict]:
    if tipo not in TIPOS:
        raise ValueError(f"Tipo inválido: {tipo}")
    return _load().get(tipo, [])


def create(tipo: str, item: dict) -> dict:
    if tipo not in TIPOS:
        raise ValueError(f"Tipo inválido: {tipo}")
    data = _load()
    now = _now()
    item = {**item, "id": str(uuid.uuid4()), "createdAt": now, "updatedAt": now}
    data[tipo].append(item)
    _save(data)
    return item


def update(tipo: str, item_id: str, changes: dict) -> dict | None:
    if tipo not in TIPOS:
        raise ValueError(f"Tipo inválido: {tipo}")
    data = _load()
    for i, it in enumerate(data[tipo]):
        if it.get("id") == item_id:
            updated = {**it, **changes, "id": item_id, "updatedAt": _now()}
            data[tipo][i] = updated
            _save(data)
            return updated
    return None


def delete(tipo: str, item_id: str) -> bool:
    if tipo not in TIPOS:
        raise ValueError(f"Tipo inválido: {tipo}")
    data = _load()
    before = len(data[tipo])
    data[tipo] = [it for it in data[tipo] if it.get("id") != item_id]
    if len(data[tipo]) < before:
        _save(data)
        return True
    return False


# ── Tareas (con owner) ────────────────────────────────────────────────────────

def get_tareas(owner: str = DEFAULT_OWNER) -> list[dict]:
    data = _load()
    changed = False
    for tarea in data["tareas"]:
        if "owner" not in tarea:
            asignado = (tarea.get("asignado") or "").strip()
            tarea["owner"] = asignado if asignado else DEFAULT_OWNER
            changed = True
    if changed:
        _save(data)
    return [t for t in data["tareas"] if t.get("owner") == owner]


def create_tarea(owner: str, item: dict) -> dict:
    item = {**item, "owner": owner}
    return create("tareas", item)


def sync_tareas(owner: str, docs: list[dict]) -> dict:
    """Sincroniza tareas auto-generadas con docs pendientes actuales del monitoring.

    - Crea tareas para docs nuevos pendientes
    - Marca completadas las que ya no están pendientes
    - Actualiza descripción de las que cambiaron de estado
    """
    data = _load()

    pending_by_source: dict[str, dict] = {}
    for doc in docs:
        sid = f"{doc.get('Nº Pedido', '')}_{doc.get('Nº Doc. EIPSA', '')}_{doc.get('Nº Revisión', doc.get('Rev.', ''))}"
        pending_by_source[sid] = doc

    existing_ids: set[str] = set()
    completed = updated = created = 0
    now = _now()

    for tarea in data["tareas"]:
        if not tarea.get("auto_generated") or tarea.get("owner") != owner:
            continue
        sid = tarea.get("source_doc_id")
        if not sid:
            continue
        existing_ids.add(sid)

        if sid not in pending_by_source:
            if tarea.get("estado") != "completada":
                tarea["estado"] = "completada"
                tarea["updatedAt"] = now
                completed += 1
        else:
            doc = pending_by_source[sid]
            new_desc = (
                f"Pedido {doc.get('Nº Pedido', '')} · "
                f"Rev. {doc.get('Nº Revisión', '')} · "
                f"Estado: {doc.get('Estado', '') or 'Sin Enviar'}"
            )
            if tarea.get("descripcion") != new_desc:
                tarea["descripcion"] = new_desc
                tarea["updatedAt"] = now
                updated += 1
            if tarea.get("estado") == "completada":
                tarea["estado"] = "pendiente"
                tarea["updatedAt"] = now

    # Crear nuevas
    for sid, doc in pending_by_source.items():
        if sid in existing_ids:
            continue
        estado = (doc.get("Estado") or "").strip().lower()
        prioridad = "alta" if estado in {"rechazado", "com. mayores", "comentado"} else "media"
        if estado in {"sin enviar", ""} and str(doc.get("Crítico", "")).lower().strip() in ("sí", "si"):
            prioridad = "alta"
        titulo_raw = doc.get("Título") or doc.get("Material") or ""
        new_task = {
            "titulo": f"[{doc.get('Nº Doc. EIPSA', '')}] {titulo_raw[:60]}",
            "descripcion": (
                f"Pedido {doc.get('Nº Pedido', '')} · "
                f"Rev. {doc.get('Nº Revisión', '')} · "
                f"Estado: {doc.get('Estado', '') or 'Sin Enviar'}"
            ),
            "prioridad": prioridad,
            "estado": "pendiente",
            "fecha_limite": str(doc.get("Fecha Prevista", "") or ""),
            "asignado": owner,
            "auto_generated": True,
            "source_doc_id": sid,
            "owner": owner,
        }
        create("tareas", new_task)
        created += 1

    if completed > 0 or updated > 0:
        _save(data)

    return {"created": created, "completed": completed, "updated": updated}
