"""DocFlowLiteApp — ventana principal con sidebar y router de vistas."""

import logging

import customtkinter as ctk

from core.config import startup_warnings
from gui import theme
from gui.widgets.sidebar import Sidebar

logger = logging.getLogger(__name__)


class DocFlowLiteApp(ctk.CTk):
    TITLE = "DocFlow Lite"
    WIDTH = 1280
    HEIGHT = 820

    NAV_ITEMS = [
        {"key": "home",          "label": "Inicio",            "icon": "⌂"},
        {"key": "apertura",      "label": "Apertura pedidos",  "icon": "✚"},
        {"key": "agenda",        "label": "Agenda",            "icon": "▣"},
        {"key": "inbox",         "label": "Bandeja AI",        "icon": "✦"},
        {"key": "ofertas",       "label": "Ofertas",           "icon": "✉"},
        {"key": "documentos",    "label": "Documentos",        "icon": "◫"},
        {"key": "pedidos",       "label": "Pedidos",           "icon": "▦"},
        {"key": "devoluciones",  "label": "Devoluciones",      "icon": "✉"},
        {"key": "reclamaciones", "label": "Reclamaciones",     "icon": "⚠"},
        {"key": "docusign",      "label": "Contratos & Firmas","icon": "✒"},
        {"key": "informes",      "label": "Informes",          "icon": "▤"},
        {"key": "reportes",      "label": "Centro de Reportes","icon": "📊"},
    ]

    def __init__(self, current_user: dict | None = None):
        # Aplicar tema según preferencia persistida
        from core.preferences import base_mode, get_theme
        mode = get_theme()
        base = base_mode(mode)  # 'light' | 'dark' — para CustomTkinter
        ctk.set_appearance_mode(base)
        ctk.set_default_color_theme("dark-blue" if base == "dark" else "blue")

        self.current_user = current_user or {}

        # Establecer la sesión (permisos por sección)
        from core import session
        session.set_user(self.current_user)

        super().__init__(fg_color=theme.BG_PAGE)
        self.title(self.TITLE)

        # Restaurar geometría previa (tamaño/posición) garantizando que la
        # ventana cae dentro de la pantalla visible (si la posición guardada
        # apuntaba a otro monitor que ahora no existe, la recentra).
        from core import preferences as _pref
        self._restore_geometry(_pref.get("window_geometry"))
        self.minsize(1000, 640)

        self._views: dict[str, ctk.CTkFrame] = {}
        self._current: str | None = None
        self.notifier = None  # se crea tras el layout

        self._build_layout()

        # Notificaciones in-app
        from gui.widgets.notifier import NotificationManager
        self.notifier = NotificationManager(self)

        # Restaurar última sección abierta (si es válida y accesible)
        last = _pref.get("last_section", "home")
        self.navigate(last if last in self._nav_keys else "home")

        # Atajos teclado globales (solo si el foco no está en un Entry)
        self.bind_all("<KeyPress-h>", self._kb_home)
        self.bind_all("<KeyPress-H>", self._kb_home)
        self.bind_all("<KeyPress-d>", self._kb_devoluciones)
        self.bind_all("<KeyPress-D>", self._kb_devoluciones)
        self.bind_all("<KeyPress-o>", self._kb_documentos)
        self.bind_all("<KeyPress-O>", self._kb_documentos)
        self.bind_all("<KeyPress-a>", self._kb_agenda)
        self.bind_all("<KeyPress-A>", self._kb_agenda)
        self.bind_all("<KeyPress-r>", self._kb_reclamaciones)
        self.bind_all("<KeyPress-R>", self._kb_reclamaciones)
        self.bind_all("<KeyPress-i>", self._kb_inbox)
        self.bind_all("<KeyPress-I>", self._kb_inbox)
        self.bind_all("<KeyPress-p>", self._kb_reportes)
        self.bind_all("<KeyPress-P>", self._kb_reportes)
        self.bind_all("<KeyPress-n>", self._kb_apertura)
        self.bind_all("<KeyPress-N>", self._kb_apertura)

        startup_warnings()

        # Pre-calentar el dataset de monitoring en segundo plano para que
        # Documentos / Informes / Pedidos abran al instante (la primera lectura
        # de los Excel es lo más lento; al cachearla aquí ya está lista).
        self.after(400, self._prewarm_data)
        # Pre-construir las vistas en idle (escalonado) → primer clic instantáneo
        self.after(2500, self._prewarm_views)
        # Auto-refresco + notificaciones (primer chequeo a los 30s)
        self._start_autorefresh()

    def _prewarm_data(self) -> None:
        import threading

        def warm():
            try:
                from core.services import monitoring
                monitoring.get_monitoring_data()
            except Exception as exc:  # noqa: BLE001 — best-effort
                logger.debug("Prewarm monitoring falló: %s", exc)
            # consulta_erp + data_tags (Pedidos: detalle instantáneo)
            try:
                from core.services import erp
                erp.consulta()
                if erp.tags_available():
                    erp.get_tags()
            except Exception as exc:  # noqa: BLE001 — best-effort
                logger.debug("Prewarm erp/tags falló: %s", exc)

        threading.Thread(target=warm, daemon=True).start()

    # Orden de pre-construcción: solo vistas pesadas de UI/disco. Se excluyen a
    # propósito las que disparan red al construirse (devoluciones, reclamaciones,
    # ofertas, inbox, docusign): su UI es barata y no queremos conexiones IMAP/API
    # sorpresa al arrancar.
    _PREWARM_ORDER = ["documentos", "pedidos", "informes", "agenda", "home",
                      "reportes", "apertura", "ajustes"]

    def _prewarm_views(self) -> None:
        """Construye las vistas restantes en idle, una cada 600ms.

        Tk obliga a crear widgets en el hilo principal, así que no se puede usar
        un thread: se escalona con after() para que cada construcción (~20-550ms)
        caiga en huecos de inactividad y el primer clic en cualquier sección sea
        instantáneo (la vista ya está cacheada en self._views).
        """
        self._prewarm_queue = [k for k in self._PREWARM_ORDER
                               if k in self._nav_keys and k not in self._views]
        self._prewarm_next()

    def _prewarm_next(self) -> None:
        if not getattr(self, "_prewarm_queue", None):
            return
        key = self._prewarm_queue.pop(0)
        try:
            if key not in self._views:
                import time as _t
                t0 = _t.perf_counter()
                view = self._make_view(key)
                # Mapearla ya (debajo de la actual) → el coste de layout se paga
                # aquí en idle y el primer navigate() es un tkraise casi gratis.
                if view is not None:
                    view.grid(row=0, column=0, sticky="nsew")
                    view.lower()
                    cur = self._views.get(self._current)
                    if cur is not None:
                        cur.tkraise()
                logger.debug("Prewarm vista %s: %.0f ms", key, (_t.perf_counter() - t0) * 1000)
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.debug("Prewarm vista %s falló: %s", key, exc)
        if self._prewarm_queue:
            self.after(600, self._prewarm_next)

    # ── Persistencia de estado (geometría + última sección) ──────────────────

    def _restore_geometry(self, geo) -> None:
        """Aplica una geometría segura: tamaño razonable y SIEMPRE dentro de la
        pantalla visible (recentra si la posición guardada queda fuera, p.ej.
        un segundo monitor que ahora no existe en sesión remota)."""
        import re
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = self.WIDTH, self.HEIGHT
        x = y = None
        m = re.match(r"^(\d+)x(\d+)([+\-]\d+)([+\-]\d+)$", geo or "") if isinstance(geo, str) else None
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            x, y = int(m.group(3)), int(m.group(4))
        # Tamaño dentro de límites de la pantalla
        w = min(max(w, 900), sw)
        h = min(max(h, 600), sh)
        # Posición: si falta o queda fuera de la pantalla → centrar
        margin = 80
        if x is None or x < 0 or y < 0 or x > sw - margin or y > sh - margin:
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def save_state(self) -> None:
        """Guarda geometría y sección actual en preferences (llamado al cerrar)."""
        from core import preferences as _pref
        try:
            if self.state() == "normal":  # no guardar geometría si está maximizada/iconificada
                _pref.set_value("window_geometry", self.winfo_geometry())
        except Exception:
            pass
        if self._current:
            _pref.set_value("last_section", self._current)

    # ── Manejo global de errores ──────────────────────────────────────────────

    def report_callback_exception(self, exc, val, tb) -> None:  # noqa: N802 (API Tk)
        """Captura excepciones de callbacks Tk: las registra y avisa sin cerrar la app."""
        import traceback
        logger.error("Excepción en callback Tk:\n%s",
                     "".join(traceback.format_exception(exc, val, tb)))
        try:
            if self.notifier:
                self.notifier.notify(
                    "Se produjo un error", "Operación interrumpida. Detalles en el registro.",
                    kind="error", native=False)
        except Exception:
            pass

    # ── Auto-refresco + notificaciones ────────────────────────────────────────

    def _start_autorefresh(self) -> None:
        from core import preferences as _pref
        self._refresh_min = int(_pref.get("autorefresh_min", 5) or 0)
        self._notif_on = bool(_pref.get("notifications", True))
        self._notif_baseline = None
        self._notif_startup_done = False
        if self._refresh_min > 0:
            # Primer chequeo a los 30s; luego cada _refresh_min minutos
            self.after(30_000, self._autorefresh_tick)

    def _autorefresh_tick(self) -> None:
        import threading

        def work():
            kpis = None
            try:
                from core.services import monitoring
                monitoring.invalidate_cache()
                kpis = monitoring.compute_kpis(monitoring.get_monitoring_data())
            except Exception as exc:  # noqa: BLE001
                logger.debug("autorefresh: %s", exc)
            self.after(0, lambda: self._autorefresh_done(kpis))

        threading.Thread(target=work, daemon=True).start()

    def _autorefresh_done(self, kpis) -> None:
        # 1) Refresca la vista actual SOLO si declara que es seguro (dashboards)
        view = self._views.get(self._current)
        if view is not None and getattr(view, "auto_refresh_safe", False):
            fn = getattr(view, "refresh", None)
            if callable(fn):
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("refresh vista %s: %s", self._current, exc)

        # 2) Notificaciones por documentos críticos +15 días
        if kpis and self._notif_on and self.notifier:
            c = int(kpis.get("criticos_15d", 0) or 0)
            if not self._notif_startup_done:
                self._notif_startup_done = True
                self._notif_baseline = c
                if c > 0:
                    self.notifier.notify(
                        "Documentos críticos",
                        f"{c} documento(s) crítico(s) llevan +15 días sin respuesta.",
                        kind="warn")
            elif self._notif_baseline is not None and c > self._notif_baseline:
                self.notifier.notify(
                    "Nuevos críticos",
                    f"{c - self._notif_baseline} documento(s) más superan los 15 días.",
                    kind="warn")
                self._notif_baseline = c
            elif self._notif_baseline is not None and c < self._notif_baseline:
                self._notif_baseline = c

        # 3) Reprograma
        if getattr(self, "_refresh_min", 0) > 0:
            self.after(self._refresh_min * 60_000, self._autorefresh_tick)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar — filtrado por permisos del usuario
        from core import auth
        items = [it for it in self.NAV_ITEMS if auth.can_view(self.current_user, it["key"])]
        if auth.is_admin(self.current_user):
            items.append({"key": "ajustes", "label": "Ajustes", "icon": "⚙"})
        self._nav_keys = {it["key"] for it in items}

        nombre = self.current_user.get("nombre") or "Usuario"
        initials = self.current_user.get("initials") or "—"
        self.sidebar = Sidebar(
            self,
            items=items,
            on_select=self.navigate,
            on_toggle_theme=self._toggle_theme,
            current_user_label=f"{nombre} ({initials})",
            on_logout=self._logout,
        )
        self.sidebar.grid(row=0, column=0, sticky="ns")

        # Content
        self.content = ctk.CTkFrame(self, fg_color=theme.BG_PAGE, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

    # ── Routing ───────────────────────────────────────────────────────────────

    def navigate(self, key: str) -> None:
        if key == self._current:
            return
        view = self._views.get(key) or self._make_view(key)
        if view is None:
            return

        # Todas las vistas comparten la celda (0,0); el cambio de sección es un
        # tkraise (z-order) en vez de grid_remove/grid — evita re-mapear cientos
        # de widgets en cada cambio (~100-250ms → ~0ms).
        if not view.grid_info():
            view.grid(row=0, column=0, sticky="nsew")
        view.tkraise()
        self._current = key
        self.sidebar.set_active(key)
        try:
            from core import preferences as _pref
            _pref.set_value("last_section", key)
        except Exception:
            pass

    def _make_view(self, key: str) -> ctk.CTkFrame | None:
        # Lazy import para que un fallo en una vista no impida cargar las otras
        if key == "home":
            from gui.views.home import HomeView
            view = HomeView(self.content, on_navigate=self.navigate)
        elif key == "devoluciones":
            from gui.views.devoluciones import DevolucionesView
            view = DevolucionesView(self.content)
        elif key == "documentos":
            from gui.views.documentos import DocumentosView
            view = DocumentosView(self.content, on_navigate=self.navigate)
        elif key == "pedidos":
            from gui.views.pedidos import PedidosView
            view = PedidosView(self.content)
        elif key == "agenda":
            from gui.views.agenda import AgendaView
            view = AgendaView(self.content)
        elif key == "reclamaciones":
            from gui.views.reclamaciones import ReclamacionesView
            view = ReclamacionesView(self.content)
        elif key == "inbox":
            from gui.views.inbox import InboxView
            view = InboxView(self.content)
        elif key == "ofertas":
            from gui.views.ofertas import OfertasView
            view = OfertasView(self.content)
        elif key == "docusign":
            from gui.views.docusign import DocusignView
            view = DocusignView(self.content)
        elif key == "informes":
            from gui.views.informes import InformesView
            view = InformesView(self.content)
        elif key == "ajustes":
            from gui.views.ajustes import AjustesView
            view = AjustesView(self.content, on_restart=self._restart_app)
        elif key == "reportes":
            from gui.views.reportes import ReportesView
            view = ReportesView(self.content)
        elif key == "apertura":
            from gui.views.apertura import AperturaView
            view = AperturaView(self.content)
        else:
            return None
        self._views[key] = view
        return view

    # ── Atajos teclado (con guarda de foco en Entry) ─────────────────────────

    def _focus_is_entry(self) -> bool:
        try:
            w = self.focus_get()
        except KeyError:
            return False
        if w is None:
            return False
        cls = w.winfo_class()
        return cls in ("Entry", "TEntry", "CTkEntry") or "Entry" in cls

    def _kb_home(self, _evt):
        if not self._focus_is_entry():
            self.navigate("home")

    def _kb_devoluciones(self, _evt):
        if not self._focus_is_entry():
            self.navigate("devoluciones")

    def _kb_documentos(self, _evt):
        if not self._focus_is_entry():
            self.navigate("documentos")

    def _kb_agenda(self, _evt):
        if not self._focus_is_entry():
            self.navigate("agenda")

    def _kb_reclamaciones(self, _evt):
        if not self._focus_is_entry():
            self.navigate("reclamaciones")

    def _kb_inbox(self, _evt):
        if not self._focus_is_entry():
            self.navigate("inbox")

    def _kb_reportes(self, _evt):
        if not self._focus_is_entry():
            self.navigate("reportes")

    def _kb_apertura(self, _evt):
        if not self._focus_is_entry():
            self.navigate("apertura")

    # ── Theme picker ─────────────────────────────────────────────────────────

    def _toggle_theme(self) -> None:
        """Abre un picker con 4 opciones de tema. Reinicia al elegir."""
        from gui.widgets.theme_picker import ThemePickerDialog
        ThemePickerDialog(self, on_apply=self._apply_theme)

    def _apply_theme(self, new_mode: str) -> None:
        from tkinter import messagebox

        from core.preferences import get_theme, set_theme

        current = get_theme()
        logger.info("Apply theme requested: current=%s new=%s", current, new_mode)
        if new_mode == current:
            logger.info("Theme unchanged, skipping restart")
            return

        try:
            set_theme(new_mode)
            # Re-leer para confirmar persistencia
            saved = get_theme()
            logger.info("Theme saved: requested=%s on_disk=%s", new_mode, saved)
            if saved != new_mode:
                messagebox.showerror(
                    "Error",
                    f"El tema se intentó guardar como {new_mode!r} "
                    f"pero en disco quedó como {saved!r}.",
                    parent=self,
                )
                return
        except Exception as exc:
            logger.exception("set_theme failed")
            messagebox.showerror(
                "Error", f"No se pudo guardar la preferencia:\n{exc}", parent=self,
            )
            return

        self._restart_app()

    @staticmethod
    def _restart_app() -> None:
        """Relanza el proceso Python y termina el actual.

        Estrategia:
          1. Intenta `os.execv` (reemplaza el proceso actual — más confiable
             en Windows GUI porque hereda el handle del Tk y no hay race).
          2. Si falla, fallback a subprocess.Popen + sys.exit (no os._exit,
             que abortaría sin destruir Tk correctamente).
        """
        import os
        import subprocess
        import sys
        from tkinter import messagebox

        python = sys.executable
        script = os.path.abspath(sys.argv[0]) if sys.argv else ""
        args = [python, script, *sys.argv[1:]] if script else [python]
        logger.info("Restarting via execv: args=%s", args)

        # Antes de exec — flush logs, preferencias pendientes y avisos
        try:
            for handler in logging.getLogger().handlers:
                handler.flush()
        except Exception:
            pass
        try:
            from core import preferences
            preferences.flush()  # write-behind: no perder cambios al reiniciar
        except Exception:
            pass

        # En Windows pythonw.exe evita el flash de consola al reiniciar
        if sys.platform == "win32":
            pythonw = python.replace("python.exe", "pythonw.exe")
            if os.path.exists(pythonw):
                args[0] = pythonw

        try:
            # Intento 1: execv — reemplaza el proceso actual
            os.execv(args[0], args)
        except OSError as exc:
            logger.warning("execv failed (%s), fallback a subprocess.Popen", exc)
        except Exception as exc:
            logger.exception("execv raised: %s", exc)

        # Intento 2: subprocess.Popen + sys.exit
        try:
            creationflags = 0
            if sys.platform == "win32":
                # CREATE_NEW_CONSOLE (no DETACHED — DETACHED hace que el GUI
                # tarde en mostrarse o no aparezca en algunos setups)
                creationflags = 0x00000010  # CREATE_NEW_CONSOLE
                if args[0].endswith("pythonw.exe"):
                    creationflags = 0  # GUI sin consola
            subprocess.Popen(args, cwd=os.getcwd(), creationflags=creationflags)
        except Exception as exc:
            logger.exception("Failed to spawn restarted process")
            messagebox.showerror(
                "Error de reinicio",
                f"No se pudo relanzar DocFlow Lite:\n{exc}\n\n"
                "Ciérralo manualmente y vuelve a abrirlo.",
            )
            return

        # sys.exit en lugar de os._exit para que Tk se destruya limpiamente
        sys.exit(0)

    # ── Logout ────────────────────────────────────────────────────────────────

    def _logout(self) -> None:
        """Cierra sesión: reinicia la app para volver a la pantalla de login."""
        from tkinter import messagebox
        if not messagebox.askyesno(
            "Cerrar sesión",
            "¿Cerrar sesión y volver al login?",
            parent=self,
        ):
            return
        self._restart_app()
