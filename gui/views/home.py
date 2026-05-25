"""Vista Home — dashboard profesional con saludo, KPIs en vivo y accesos rápidos."""

import logging
import threading
import webbrowser
from datetime import datetime

import customtkinter as ctk

from gui import theme

logger = logging.getLogger(__name__)

PORTFOLIO_URL = "https://jparedesds.github.io/"


# ── Cards de navegación (sección, icono, título, descripción base) ────────────

NAV_CARDS = [
    {"key": "documentos",    "icon": "◫",  "color": theme.BLUE,
     "title": "Documentos",      "base_desc": "Vista global con KPIs y filtros"},
    {"key": "agenda",        "icon": "▣",  "color": theme.AMBER,
     "title": "Agenda",          "base_desc": "Tareas, notas y reuniones"},
    {"key": "inbox",         "icon": "✦",  "color": theme.ACCENT,
     "title": "Bandeja AI",      "base_desc": "Correos del buzón IMAP"},
    {"key": "devoluciones",  "icon": "✉",  "color": theme.GREEN,
     "title": "Devoluciones",    "base_desc": "Procesar emails TR/GAIA/ACONEX/SENDOC"},
    {"key": "reclamaciones", "icon": "⚠",  "color": theme.RED,
     "title": "Reclamaciones",   "base_desc": "Pedidos con docs >15 días"},
    {"key": "reportes",      "icon": "📊", "color": theme.ROSE,
     "title": "Centro de Reportes", "base_desc": "Excels y resúmenes por email"},
]


class HomeView(ctk.CTkFrame):
    def __init__(self, master, on_navigate, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._on_navigate = on_navigate
        self._kpi_widgets: dict[str, ctk.CTkLabel] = {}
        self._card_descs: dict[str, ctk.CTkLabel] = {}
        self._build()
        # Cargar datos en background para no bloquear render
        self.after(50, self._reload_kpis_async)

    def _build(self) -> None:
        # Scrollable para que en pantallas pequeñas no se corte
        wrapper = ctk.CTkScrollableFrame(self, fg_color="transparent")
        wrapper.pack(fill="both", expand=True)

        # ── Saludo + fecha ──────────────────────────────────────────────────
        header = ctk.CTkFrame(wrapper, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 8))

        ctk.CTkLabel(
            header, text=_greeting(),
            font=(theme.FONT_FAMILY, 26, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            header, text=_today_long(),
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # ── KPIs en vivo ────────────────────────────────────────────────────
        kpis_section = ctk.CTkFrame(wrapper, fg_color="transparent")
        kpis_section.pack(fill="x", padx=24, pady=(20, 8))

        ctk.CTkLabel(
            kpis_section, text="RESUMEN DEL DÍA",
            font=(theme.FONT_FAMILY, 10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", pady=(0, 8))

        kpis_grid = ctk.CTkFrame(kpis_section, fg_color="transparent")
        kpis_grid.pack(fill="x")
        for col in range(6):
            kpis_grid.grid_columnconfigure(col, weight=1, uniform="kpi")

        for col, (key, label, color) in enumerate([
            ("total",       "Total Docs",       theme.ACCENT),
            ("pendientes",  "Pendientes",       theme.AMBER),
            ("criticos",    "Críticos",         theme.RED),
            ("reclamables", "Reclamables",      theme.ROSE),
            ("tareas",      "Tareas pdtes.",    theme.BLUE),
            ("inbox",       "Inbox no leídos",  theme.GREEN),
        ]):
            self._kpi_widgets[key] = self._build_kpi_card(kpis_grid, col, label, color)

        # ── Accesos rápidos ─────────────────────────────────────────────────
        nav_section = ctk.CTkFrame(wrapper, fg_color="transparent")
        nav_section.pack(fill="x", padx=24, pady=(24, 8))

        ctk.CTkLabel(
            nav_section, text="ACCESOS RÁPIDOS",
            font=(theme.FONT_FAMILY, 10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", pady=(0, 8))

        nav_grid = ctk.CTkFrame(nav_section, fg_color="transparent")
        nav_grid.pack(fill="x")
        for col in range(3):
            nav_grid.grid_columnconfigure(col, weight=1, uniform="nav")

        for i, c in enumerate(NAV_CARDS):
            row, col = divmod(i, 3)
            self._build_nav_card(nav_grid, row, col, c)

        # Footer con info de versión + copyright + link al portfolio
        footer = ctk.CTkFrame(wrapper, fg_color="transparent")
        footer.pack(fill="x", padx=24, pady=(28, 20))

        row = ctk.CTkFrame(footer, fg_color="transparent")
        row.pack(anchor="center")

        ctk.CTkLabel(
            row, text="DocFlow Lite v0.1  ·  hecho por  ",
            font=(theme.FONT_FAMILY, 10), text_color=theme.TEXT_MUTED,
        ).pack(side="left")

        link = ctk.CTkLabel(
            row, text="jparedesDS",
            font=(theme.FONT_FAMILY, 10, "bold"),
            text_color=theme.ACCENT, cursor="hand2",
        )
        link.pack(side="left")
        link.bind("<Button-1>", lambda _e: webbrowser.open(PORTFOLIO_URL))
        link.bind("<Enter>", lambda _e: link.configure(text_color=theme.ACCENT_HOVER))
        link.bind("<Leave>", lambda _e: link.configure(text_color=theme.ACCENT))

        ctk.CTkLabel(
            row, text="  ·  © 2026  ·  Todos los derechos reservados",
            font=(theme.FONT_FAMILY, 10), text_color=theme.TEXT_MUTED,
        ).pack(side="left")

    def _build_kpi_card(self, parent, col: int, label: str, color: str) -> ctk.CTkLabel:
        card = ctk.CTkFrame(
            parent, fg_color=theme.BG_CARD, corner_radius=10,
            border_width=1, border_color=theme.BORDER,
        )
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=14, pady=12)

        value_lbl = ctk.CTkLabel(
            inner, text="—", font=(theme.FONT_FAMILY, 22, "bold"),
            text_color=color, anchor="w",
        )
        value_lbl.pack(anchor="w")

        ctk.CTkLabel(
            inner, text=label.upper(), font=(theme.FONT_FAMILY, 9, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        return value_lbl

    def _build_nav_card(self, parent, row: int, col: int, c: dict) -> None:
        card = ctk.CTkFrame(
            parent, fg_color=theme.BG_CARD, corner_radius=12,
            border_width=1, border_color=theme.BORDER,
            cursor="hand2",
        )
        card.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0), pady=(0, 8))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=18, pady=16)

        # Icono + título en fila
        title_row = ctk.CTkFrame(inner, fg_color="transparent")
        title_row.pack(fill="x")
        ctk.CTkLabel(
            title_row, text=c["icon"],
            font=(theme.FONT_FAMILY, 20, "bold"),
            text_color=c["color"], anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            title_row, text=c["title"],
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=(8, 0))

        desc_lbl = ctk.CTkLabel(
            inner, text=c["base_desc"],
            font=(theme.FONT_FAMILY, 11),
            text_color=theme.TEXT_SUB, anchor="w", justify="left", wraplength=320,
        )
        desc_lbl.pack(anchor="w", pady=(8, 0))
        self._card_descs[c["key"]] = desc_lbl

        # Hover + click handlers para toda la card
        def _enter(_evt, card=card, color=c["color"]):
            card.configure(border_color=color)

        def _leave(_evt, card=card):
            card.configure(border_color=theme.BORDER)

        def _click(_evt, key=c["key"]):
            self._on_navigate(key)

        for widget in (card, inner, title_row, desc_lbl):
            widget.bind("<Enter>", _enter)
            widget.bind("<Leave>", _leave)
            widget.bind("<Button-1>", _click)

    # ── Carga de datos asíncrona ─────────────────────────────────────────────

    def _reload_kpis_async(self) -> None:
        """Carga todos los KPIs en background."""
        # Set inicial "Cargando…"
        for lbl in self._kpi_widgets.values():
            lbl.configure(text="…")

        def worker():
            results = {}
            try:
                from core.services import monitoring as monitoring_service
                docs = monitoring_service.get_monitoring_data()
                kpis = monitoring_service.compute_kpis(docs)
                results["total"] = kpis.get("total", 0)
                # Pendientes = no aprobados (todo lo que sea ESTADOS_PENDIENTES o sin enviar)
                results["pendientes"] = (
                    kpis.get("enviados", 0) + kpis.get("devoluciones", 0)
                    + kpis.get("sin_enviar", 0)
                )
                results["criticos"] = kpis.get("criticos", 0)
            except Exception as exc:
                logger.warning("KPIs documentos fallaron: %s", exc)

            try:
                from core.services import claims as claims_service
                results["reclamables"] = len(claims_service.get_claimable_pedidos())
            except Exception as exc:
                logger.warning("KPI reclamables falló: %s", exc)

            try:
                from core.services import agenda as agenda_service
                tareas = agenda_service.get_tareas(agenda_service.DEFAULT_OWNER)
                results["tareas"] = sum(1 for t in tareas if t.get("estado") != "completada")
            except Exception as exc:
                logger.warning("KPI tareas falló: %s", exc)

            # Inbox unread es opcional (depende de IMAP). Si falla, no mostramos.
            try:
                from core.services import inbox as inbox_service
                emails = inbox_service.list_emails(filter="unread", limit=200)
                results["inbox"] = len(emails)
            except Exception as exc:
                logger.warning("KPI inbox falló (probablemente IMAP no configurado): %s", exc)

            self.after(0, lambda: self._update_kpis(results))

        threading.Thread(target=worker, daemon=True).start()

    def _update_kpis(self, results: dict) -> None:
        for key, lbl in self._kpi_widgets.items():
            val = results.get(key)
            lbl.configure(text=str(val) if val is not None else "—")

        # Enriquecer descripciones de cards con datos en vivo
        if "tareas" in results:
            n = results["tareas"]
            self._card_descs["agenda"].configure(
                text=f"{n} tarea(s) pendiente(s) · notas y reuniones",
            )
        if "total" in results:
            self._card_descs["documentos"].configure(
                text=f"{results['total']} docs · KPIs, filtros, detalle",
            )
        if "reclamables" in results:
            n = results["reclamables"]
            self._card_descs["reclamaciones"].configure(
                text=f"{n} pedido(s) reclamable(s) · 3 niveles de escalation",
            )
        if "inbox" in results:
            self._card_descs["inbox"].configure(
                text=f"{results['inbox']} correo(s) sin leer",
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _greeting() -> str:
    """Saludo según la hora actual."""
    h = datetime.now().hour
    if 6 <= h < 12:
        prefix = "Buenos días"
    elif 12 <= h < 21:
        prefix = "Buenas tardes"
    else:
        prefix = "Buenas noches"
    return f"{prefix}, Jose"


def _today_long() -> str:
    days = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    months = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    now = datetime.now()
    return f"{days[now.weekday()]}, {now.day} de {months[now.month - 1]} · {now.strftime('%H:%M')}"
