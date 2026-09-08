"""Trazabilidad: quién cambió qué y cuándo, del registro de auditoría del ERP.

El ERP guarda en el esquema `logging` un histórico de cambios por tabla, con
marca de tiempo y usuario. Para documentación son 26.238 apuntes desde
septiembre de 2023 (`logging.documentation_changes`), donde `pkey` es el Nº de
documento EIPSA y el cambio viene como texto:

    INSERT → new_val = la fila entera en JSON
    UPDATE → new_val = {"data": "state - New Value: Enviado"}
             old_val = {"data": "state - Old Value: Sin enviar"}

Aquí se traduce a algo legible («Estado: Sin enviar → Enviado, por JP»). Solo
lectura, caché corta.
"""

from __future__ import annotations

import logging
import re

from core.services.erp_common import Cache, clean, safe_query, who

logger = logging.getLogger(__name__)

_cache = Cache(ttl=120)

# Columnas del ERP → nombre que ve el usuario (el mismo de la app)
FIELDS = {
    "state": "Estado",
    "revision": "Nº Revisión",
    "state_date": "Fecha",
    "tracking": "Seguimiento",
    "doc_title": "Título",
    "num_doc_client": "Nº Doc. Cliente",
    "num_doc_eipsa": "Nº Doc. EIPSA",
    "num_order": "Nº Pedido",
    "critical": "Crítico",
    "review_info": "Info/Review",
    "sending_days": "Días Envío",
    "doc_responsible": "Responsable",
    "doc_type_id": "Tipo Doc.",
    "date_first_rev": "1ª revisión",
}

_CHANGE_RE = re.compile(r"^\s*(\w+)\s*-\s*(?:New|Old)\s+Value:\s*(.*)$", re.S)

_SQL_DOC = """
    SELECT tstamp, operation, who, pkey, new_val::text AS new_val, old_val::text AS old_val
    FROM logging.documentation_changes
    WHERE pkey = %s
    ORDER BY tstamp DESC
    LIMIT %s
"""

_SQL_RECENT = """
    SELECT tstamp, operation, who, pkey, new_val::text AS new_val, old_val::text AS old_val
    FROM logging.documentation_changes
    ORDER BY tstamp DESC
    LIMIT %s
"""


def invalidate_cache() -> None:
    _cache.clear()


def _value(raw: str) -> tuple[str, str]:
    """'state - New Value: Enviado' → ('state', 'Enviado')."""
    try:
        import json
        data = json.loads(raw or "{}")
    except Exception:  # noqa: BLE001
        return "", ""
    texto = data.get("data") if isinstance(data, dict) else None
    if not texto:
        return "", ""
    m = _CHANGE_RE.match(str(texto))
    return (m.group(1), m.group(2).strip()) if m else ("", "")


def _entry(r: dict) -> dict:
    op = clean(r.get("operation")).upper()
    quien = who(r.get("who"))
    if op == "INSERT":
        return {"cuando": r["tstamp"], "quien": quien, "campo": "", "de": "", "a": "",
                "texto": "Documento dado de alta", "tipo": "alta"}
    if op == "DELETE":
        return {"cuando": r["tstamp"], "quien": quien, "campo": "", "de": "", "a": "",
                "texto": "Documento eliminado", "tipo": "baja"}
    campo, nuevo = _value(r.get("new_val"))
    _, viejo = _value(r.get("old_val"))
    etiqueta = FIELDS.get(campo, campo or "Cambio")
    nuevo_txt = nuevo or "(vacío)"
    texto = f"{etiqueta}: {viejo or '(vacío)'} → {nuevo_txt}" if viejo or nuevo else etiqueta
    return {"cuando": r["tstamp"], "quien": quien, "campo": etiqueta,
            "de": viejo, "a": nuevo, "texto": texto, "tipo": "cambio"}


def document_history(num_doc_eipsa: str, limit: int = 60) -> list[dict]:
    """Historial de un documento: [{cuando, quien, campo, de, a, texto, tipo}]."""
    key = clean(num_doc_eipsa)
    if not key:
        return []

    def build():
        rows = safe_query(_SQL_DOC, (key, limit), label="historial documento")
        return [_entry(r) for r in rows]

    return _cache.get(f"doc:{key}:{limit}", build)


def recent(limit: int = 60) -> list[dict]:
    """Últimos cambios de documentación de toda la empresa (actividad reciente)."""
    def build():
        rows = safe_query(_SQL_RECENT, (limit,), label="actividad reciente")
        out = []
        for r in rows:
            e = _entry(r)
            e["documento"] = clean(r.get("pkey"))
            out.append(e)
        return out

    return _cache.get(f"recent:{limit}", build)


def is_available() -> bool:
    from core.services.erp_common import available
    return available()
