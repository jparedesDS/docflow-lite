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
        {"key": "agenda",        "label": "Agenda",            "icon": "▣"},
        {"key": "inbox",         "label": "Bandeja AI",        "icon": "✦"},
        {"key": "documentos",    "label": "Documentos",        "icon": "◫"},
        {"key": "devoluciones",  "label": "Devoluciones",      "icon": "✉"},
        {"key": "reclamaciones", "label": "Reclamaciones",     "icon": "⚠"},
        {"key": "reportes",      "label": "Centro de Reportes","icon": "📊"},
    ]

    def __init__(self):
        # Aplicar tema según preferencia persistida
        from core.preferences import get_theme
        mode = get_theme()
        ctk.set_appearance_mode(mode)
        ctk.set_default_color_theme("dark-blue" if mode == "dark" else "blue")

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

        startup_warnings()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self.sidebar = Sidebar(
            self,
            items=self.NAV_ITEMS,
            on_select=self.navigate,
            on_toggle_theme=self._toggle_theme,
            footer="© 2026 Jose Paredes",
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

    # ── Toggle Light / Dark ──────────────────────────────────────────────────

    def _toggle_theme(self) -> None:
        """Cambia el tema persistido y reinicia la app para aplicar."""
        from tkinter import messagebox

        from core.preferences import get_theme, set_theme

        current = get_theme()
        new_mode = "light" if current == "dark" else "dark"
        new_label = "claro" if new_mode == "light" else "oscuro"

        ok = messagebox.askyesno(
            "Cambiar tema",
            f"DocFlow Lite se reiniciará para aplicar el modo {new_label}.\n\n"
            "Las ventanas abiertas se cerrarán. ¿Continuar?",
            parent=self,
        )
        if not ok:
            return

        try:
            set_theme(new_mode)
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo guardar la preferencia:\n{exc}", parent=self)
            return

        self._restart_app()

    @staticmethod
    def _restart_app() -> None:
        import os
        import subprocess
        import sys

        python = sys.executable
        try:
            subprocess.Popen([python, *sys.argv])
        except Exception:
            pass
        os._exit(0)
