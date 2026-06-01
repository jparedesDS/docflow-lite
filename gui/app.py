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
        {"key": "documentos",    "label": "Documentos",        "icon": "◫"},
        {"key": "devoluciones",  "label": "Devoluciones",      "icon": "✉"},
        {"key": "reclamaciones", "label": "Reclamaciones",     "icon": "⚠"},
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

        super().__init__(fg_color=theme.BG_PAGE)
        self.title(self.TITLE)
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        self.minsize(1000, 640)

        self._views: dict[str, ctk.CTkFrame] = {}
        self._current: str | None = None

        self._build_layout()
        self.navigate("home")

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

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        nombre = self.current_user.get("nombre") or "Usuario"
        initials = self.current_user.get("initials") or "—"
        self.sidebar = Sidebar(
            self,
            items=self.NAV_ITEMS,
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

        # Hide current
        if self._current and self._current in self._views:
            self._views[self._current].grid_remove()

        view.grid(row=0, column=0, sticky="nsew")
        self._current = key
        self.sidebar.set_active(key)

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
            view = DocumentosView(self.content)
        elif key == "agenda":
            from gui.views.agenda import AgendaView
            view = AgendaView(self.content)
        elif key == "reclamaciones":
            from gui.views.reclamaciones import ReclamacionesView
            view = ReclamacionesView(self.content)
        elif key == "inbox":
            from gui.views.inbox import InboxView
            view = InboxView(self.content)
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

        # Antes de exec — flush logs y avisos
        try:
            for handler in logging.getLogger().handlers:
                handler.flush()
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
