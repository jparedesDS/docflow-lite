"""DocFlow Lite — entry point.

Flujo:
1. Inicializar usuarios locales (seed si es el primer arranque).
2. Pantalla de login. Si el usuario cierra sin autenticar → exit.
3. Arrancar BackgroundScheduler (reportes programados).
4. Lanzar DocFlowLiteApp con el usuario autenticado.
5. Al cerrar la ventana, parar el scheduler limpiamente.
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("docflow-lite")


def _try_start_scheduler():
    try:
        from core.services.scheduled_reports import start_background_scheduler
        return start_background_scheduler()
    except ImportError as exc:
        logger.warning("APScheduler no disponible: %s", exc)
    except Exception as exc:
        logger.warning("No se pudo arrancar el scheduler: %s", exc)
    return None


def _authenticate():
    """Muestra la pantalla de login. Devuelve el user dict o None."""
    from core import auth
    from gui.login import LoginWindow

    auth.initialize()  # seed users.json si no existe
    login = LoginWindow()
    login.mainloop()
    return login.user


def main() -> int:
    user = _authenticate()
    if user is None:
        logger.info("Login cancelado por el usuario")
        return 0

    logger.info("Login OK · %s (%s)", user.get("nombre"), user.get("initials"))

    scheduler = _try_start_scheduler()

    from gui.app import DocFlowLiteApp
    app = DocFlowLiteApp(current_user=user)

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
