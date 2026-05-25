"""DocFlow Lite — entry point.

Arranca la GUI nativa de CustomTkinter y el BackgroundScheduler que ejecuta
los reportes programados mientras la app está abierta.
"""

import logging
import sys

from gui.app import DocFlowLiteApp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("docflow-lite")


def _try_start_scheduler():
    """Arranca el BackgroundScheduler. Devuelve la instancia o None si falla."""
    try:
        from core.services.scheduled_reports import start_background_scheduler
        return start_background_scheduler()
    except ImportError as exc:
        logger.warning("APScheduler no disponible (pip install apscheduler): %s", exc)
    except Exception as exc:
        logger.warning("No se pudo arrancar el scheduler: %s", exc)
    return None


def main() -> int:
    scheduler = _try_start_scheduler()

    app = DocFlowLiteApp()

    def _on_close():
        if scheduler is not None:
            try:
                scheduler.shutdown(wait=False)
                logger.info("Scheduler detenido")
            except Exception as exc:
                logger.warning("Error al detener scheduler: %s", exc)
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", _on_close)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
