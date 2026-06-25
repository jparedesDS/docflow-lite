"""Servicio de Reportes Programados — CRUD JSON + APScheduler.

Versión LITE: solo dos tipos de schedule (executive, personal).
APScheduler corre en BackgroundScheduler dentro de la app; los jobs solo se
ejecutan mientras la app esté abierta.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from core.config import USERS
from core.paths import state_dir
from core.utils.json_store import read_json, write_json

logger = logging.getLogger(__name__)

SCHEDULES_FILE = str(state_dir() / "scheduled_reports.json")

_scheduler_ref = None  # Set por sync_scheduler_jobs


# ── Schedules por defecto ─────────────────────────────────────────────────────

DEFAULT_SCHEDULES: list[dict] = [
    {
        "id": "weekly-executive",
        "type": "executive",
        "title": "Resumen Monitoring Report",
        "description": "Email ejecutivo semanal con KPIs (con IA si hay API key)",
        "enabled": False,
        "frequency": "weekly",
        "schedule": {"day_of_week": "mon", "hour": 8, "minute": 0},
        "recipients": {"to": [], "cc": []},
        "options": {"user_filter": "all"},
        "last_run": None,
    },
    {
        "id": "weekly-personal",
        "type": "personal",
        "title": "Monitoring Report Personal",
        "description": "Email individual por doc controller con sus devoluciones",
        "enabled": False,
        "frequency": "weekly",
        "schedule": {"day_of_week": "mon", "hour": 8, "minute": 0},
        "recipients": {"to": [], "cc": []},
        "options": {"user_filter": "all"},
        "last_run": None,
    },
    {
        "id": "weekly-interactive",
        "type": "interactive",
        "title": "Informe Interactivo Semanal (web)",
        "description": "Informe HTML interactivo (KPIs, gráficos, riesgo) adjunto por email cada lunes",
        "enabled": False,
        "frequency": "weekly",
        "schedule": {"day_of_week": "mon", "hour": 8, "minute": 0},
        "recipients": {"to": [], "cc": []},
        "options": {"period": "weekly"},
        "last_run": None,
    },
    {
        "id": "monthly-interactive",
        "type": "interactive",
        "title": "Informe Interactivo Mensual (web)",
        "description": "Informe HTML interactivo del mes adjunto por email el día 1 de cada mes",
        "enabled": False,
        "frequency": "monthly",
        "schedule": {"day_of_month": 1, "hour": 8, "minute": 0},
        "recipients": {"to": [], "cc": []},
        "options": {"period": "monthly"},
        "last_run": None,
    },
    {
        "id": "monthly-executive-html",
        "type": "interactive_executive",
        "title": "Reporte Ejecutivo Mensual (web)",
        "description": "Reporte ejecutivo HTML interactivo (KPIs, ranking, riesgo, scorecard) adjunto por email el día 1 de cada mes",
        "enabled": False,
        "frequency": "monthly",
        "schedule": {"day_of_month": 1, "hour": 8, "minute": 0},
        "recipients": {"to": [], "cc": []},
        "options": {},
        "last_run": None,
    },
]


DAY_LABELS = {
    "mon": "Lunes", "tue": "Martes", "wed": "Miércoles", "thu": "Jueves",
    "fri": "Viernes", "sat": "Sábado", "sun": "Domingo",
}
LABEL_TO_DAY = {v: k for k, v in DAY_LABELS.items()}


# ── Persistencia ──────────────────────────────────────────────────────────────

# Schedules retirados: se purgan del JSON aunque ya estuvieran persistidos
# (el PDF ejecutivo se sustituyó por el informe interactivo web).
_DEPRECATED_IDS = {"monthly-executive-pdf"}


def _load() -> list[dict]:
    data = read_json(SCHEDULES_FILE, default=None)
    changed = data is None or not isinstance(data, list)
    if changed:
        data = [dict(s) for s in DEFAULT_SCHEDULES]
    # Purga schedules obsoletos
    if any(s.get("id") in _DEPRECATED_IDS for s in data):
        data = [s for s in data if s.get("id") not in _DEPRECATED_IDS]
        changed = True
    # Asegurar que existen los schedules por defecto (idempotente al añadir nuevos en código)
    ids = {s.get("id") for s in data}
    for default in DEFAULT_SCHEDULES:
        if default["id"] not in ids:
            data.append(dict(default))
            ids.add(default["id"])
            changed = True
    if changed:
        _save(data)
    return data


def _save(data: list[dict]) -> None:
    write_json(SCHEDULES_FILE, data)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def list_schedules() -> list[dict]:
    return _load()


def get_schedule(schedule_id: str) -> Optional[dict]:
    for s in _load():
        if s["id"] == schedule_id:
            return s
    return None


def update_schedule(schedule_id: str, changes: dict) -> Optional[dict]:
    schedules = _load()
    for i, s in enumerate(schedules):
        if s["id"] == schedule_id:
            # Merge nested dicts
            for key in ("schedule", "recipients", "options"):
                if key in changes and isinstance(changes[key], dict):
                    existing = s.get(key, {}) or {}
                    existing.update(changes[key])
                    changes[key] = existing
            s.update(changes)
            schedules[i] = s
            _save(schedules)
            _refresh_job(schedule_id)
            return s
    return None


def record_run(schedule_id: str, status: str, recipients_count: int = 0, error: Optional[str] = None) -> None:
    schedules = _load()
    for i, s in enumerate(schedules):
        if s["id"] == schedule_id:
            s["last_run"] = {
                "timestamp": datetime.now().isoformat(),
                "status": status,
                "recipients_count": recipients_count,
                "error": error,
            }
            schedules[i] = s
            _save(schedules)
            return


def get_team_users() -> list[dict]:
    return [
        {"initials": k, "nombre": v["nombre"], "email": v["emails"][0]}
        for k, v in USERS.items()
    ]


# ── Ejecución ─────────────────────────────────────────────────────────────────

def execute_schedule(schedule_id: str) -> dict:
    sched = get_schedule(schedule_id)
    if sched is None:
        return {"status": "error", "error": "Schedule not found"}

    recipients = sched.get("recipients") or {}
    to = recipients.get("to") or None
    cc = recipients.get("cc") or None
    options = sched.get("options") or {}
    user_filter = options.get("user_filter", "all")

    try:
        if sched["type"] == "executive":
            from core.services.weekly_summary import send_executive_email
            result = send_executive_email(to=to, cc=cc)
            count = len(result.get("recipients", []))
        elif sched["type"] == "personal":
            from core.services.weekly_summary import send_personal_emails
            uf = user_filter
            if isinstance(uf, str) and uf != "all" and uf:
                uf = [s.strip() for s in uf.split(",") if s.strip()]
            result = send_personal_emails(to_cc=cc, user_filter=uf)
            count = result.get("count", 0)
        elif sched["type"] == "executive_pdf":
            from core.services.pdf_report import send_executive_pdf_email
            if not to:
                record_run(schedule_id, "error", error="Sin destinatarios (To)")
                return {"status": "error", "error": "Indica al menos un destinatario en To"}
            variant = options.get("variant", "completo")
            result = send_executive_pdf_email(to=to, cc=cc, variant=variant)
            count = len(result.get("recipients", []))
        elif sched["type"] == "interactive":
            from core.services.interactive_report import send_email
            if not to:
                record_run(schedule_id, "error", error="Sin destinatarios (To)")
                return {"status": "error", "error": "Indica al menos un destinatario en To"}
            period = options.get("period", "weekly")
            result = send_email(period=period, to=to, cc=cc)
            count = len(result.get("recipients", []))
        elif sched["type"] == "interactive_executive":
            from core.services.interactive_report import send_executive_html_email
            if not to:
                record_run(schedule_id, "error", error="Sin destinatarios (To)")
                return {"status": "error", "error": "Indica al menos un destinatario en To"}
            result = send_executive_html_email(to=to, cc=cc)
            count = len(result.get("recipients", []))
        else:
            record_run(schedule_id, "error", error=f"Tipo desconocido: {sched['type']}")
            return {"status": "error", "error": f"Tipo desconocido: {sched['type']}"}

        record_run(schedule_id, "success", recipients_count=count)
        return {"status": "success", "schedule_id": schedule_id, "result": result}
    except Exception as exc:
        logger.exception("Error ejecutando schedule %s", schedule_id)
        record_run(schedule_id, "error", error=str(exc))
        return {"status": "error", "schedule_id": schedule_id, "error": str(exc)}


def get_preview_html(schedule_id: str, personal_initials: str = "JP") -> Optional[str]:
    sched = get_schedule(schedule_id)
    if sched is None:
        return None
    if sched["type"] == "executive":
        from core.services.weekly_summary import get_executive_preview
        return get_executive_preview()
    if sched["type"] == "personal":
        from core.services.weekly_summary import get_personal_preview
        return get_personal_preview(personal_initials)
    return None


# ── APScheduler integration ───────────────────────────────────────────────────

def start_background_scheduler():
    """Crea e inicia un BackgroundScheduler con los jobs habilitados.

    Devuelve la instancia (para que el caller pueda llamar shutdown() al cerrar).
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    sync_scheduler_jobs(scheduler)
    scheduler.start()
    logger.info("BackgroundScheduler arrancado (%d jobs)", len(scheduler.get_jobs()))
    return scheduler


def sync_scheduler_jobs(scheduler) -> None:
    """Lee JSON y crea cron jobs para los schedules habilitados."""
    global _scheduler_ref
    _scheduler_ref = scheduler
    for sched in list_schedules():
        _add_job_for(scheduler, sched)


def _add_job_for(scheduler, sched: dict) -> None:
    if not sched.get("enabled"):
        return

    job_id = f"sched_{sched['id']}"
    schedule_id = sched["id"]

    def _run(sid=schedule_id):
        execute_schedule(sid)

    s = sched.get("schedule") or {}
    if sched.get("frequency") == "weekly":
        scheduler.add_job(
            _run, "cron",
            day_of_week=s.get("day_of_week", "mon"),
            hour=s.get("hour", 8),
            minute=s.get("minute", 0),
            id=job_id, replace_existing=True,
        )
    elif sched.get("frequency") == "monthly":
        scheduler.add_job(
            _run, "cron",
            day=s.get("day_of_month", 1),
            hour=s.get("hour", 8),
            minute=s.get("minute", 0),
            id=job_id, replace_existing=True,
        )


def _refresh_job(schedule_id: str) -> None:
    if _scheduler_ref is None:
        return
    job_id = f"sched_{schedule_id}"
    existing = _scheduler_ref.get_job(job_id)
    if existing:
        _scheduler_ref.remove_job(job_id)
    sched = get_schedule(schedule_id)
    if sched and sched.get("enabled"):
        _add_job_for(_scheduler_ref, sched)


def format_next_run(sched: dict) -> str:
    """Devuelve descripción humana de cuándo correrá el schedule."""
    if not sched.get("enabled"):
        return "Desactivado"
    s = sched.get("schedule") or {}
    if sched.get("frequency") == "weekly":
        day = DAY_LABELS.get(s.get("day_of_week", "mon"), s.get("day_of_week", "mon"))
        return f"Cada {day} a las {s.get('hour', 8):02d}:{s.get('minute', 0):02d}"
    if sched.get("frequency") == "monthly":
        return f"Día {s.get('day_of_month', 1)} de cada mes a las {s.get('hour', 8):02d}:{s.get('minute', 0):02d}"
    return "—"
