"""DocFlow Lite — entry point.

Flujo:
1. Inicializar usuarios locales (seed si es el primer arranque).
2. Pantalla de login. Si el usuario cierra sin autenticar → exit.
3. Arrancar BackgroundScheduler (reportes programados).
4. Lanzar DocFlowLiteApp con el usuario autenticado.
5. Al cerrar la ventana, parar el scheduler limpiamente.
"""

import logging
import logging.handlers
import sys


def _setup_logging() -> None:
    """Logging a consola + fichero rotativo en state/logs/docflow.log."""
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        from core.paths import state_dir
        logs_dir = state_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        fileh = logging.handlers.RotatingFileHandler(
            logs_dir / "docflow.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        fileh.setFormatter(fmt)
        root.addHandler(fileh)
    except Exception as exc:  # noqa: BLE001
        root.warning("No se pudo crear el log de fichero: %s", exc)


_setup_logging()
logger = logging.getLogger("docflow-lite")


def _install_excepthook() -> None:
    """Registra cualquier excepción no capturada del hilo principal en el log."""
    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("Excepción no controlada", exc_info=(exc_type, exc_value, exc_tb))
    sys.excepthook = _hook


_install_excepthook()


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
        try:
            app.save_state()  # geometría + última sección
        except Exception as exc:
            logger.debug("save_state falló: %s", exc)
        try:
            from core import preferences
            preferences.flush()  # volcar escrituras pendientes (write-behind)
        except Exception as exc:
            logger.debug("preferences.flush falló: %s", exc)
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
