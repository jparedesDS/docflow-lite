"""Vista Docusign — Contratos & Firmas (DocuSign eSignature).

Distribución profesional master-detail (sin pop-ups):
  • Cabecera con estado de API + última sync + botón actualizar.
  • KPIs: Pendientes · Completados · Rechazados · Expirados · Total.
  • Filtros: estado · rango de días · búsqueda.
  • Master-detail:
      - Izquierda  → lista de sobres (tarjetas: asunto, remitente, firmantes,
                     estado y fecha).
      - Derecha    → detalle EN LÍNEA del sobre seleccionado: Información,
                     Firmantes y Historial de eventos + descarga del PDF.
  • Estado "no configurado" con las variables .env necesarias.

Las llamadas a la API de DocuSign corren en hilos.
"""

import logging
import threading
from datetime import datetime

import customtkinter as ctk
from tkinter import filedialog, messagebox

from core.services import docusign as ds
from gui import theme
from gui.widgets import ui

logger = logging.getLogger(__name__)

ACCENT_DS = "#2563EB"

DAYS_OPTIONS = [
    ("Sin límite (todos)", 0), ("Últimos 7 días", 7), ("Últimos 14 días", 14),
    ("Últimos 30 días", 30), ("Últimos 60 días", 60), ("Últimos 90 días", 90),
    ("Últimos 180 días", 180), ("Últimos 365 días", 365),
]


def _fmt_date(s) -> str:
    return str(s)[:10] if s else "—"


def _initials(name: str) -> str:
    parts = [w[0] for w in str(name or "").split() if w]
    return "".join(parts)[:2].upper() or "?"


def _signer_color(status: str) -> str:
    st = (status or "").lower()
    if st == "completed":
        return theme.GREEN
    if st == "declined":
        return theme.RED
    return ACCENT_DS


def _avatar(parent, r: dict, size: int = 24):
    col = _signer_color(r.get("status"))
    circle = ctk.CTkFrame(parent, width=size, height=size, corner_radius=size // 2,
                          fg_color=theme.BG_INPUT, border_width=2, border_color=col)
    circle.pack_propagate(False)
    ctk.CTkLabel(circle, text=_initials(r.get("name", "")), font=theme.font(9, "bold"),
                 text_color=col).pack(expand=True)
    return circle


def _badge(parent, status: str):
    col = ds.status_color(status)
    return ctk.CTkLabel(parent, text=f"  {ds.status_label(status)}  ",
                        font=theme.FONT_TINY, text_color=col,
                        fg_color=theme.BG_INPUT, corner_radius=8, height=22)


def _bind_click(widget, cmd) -> None:
    widget.bind("<Button-1>", lambda e: cmd())
    for ch in widget.winfo_children():
        _bind_click(ch, cmd)


def _section(parent, text: str):
    return ui.section_header(parent, text, ACCENT_DS)


# ════════════════════════════════════════════════════════════════════════════
#  Vista principal
# ════════════════════════════════════════════════════════════════════════════

class DocusignView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._envelopes: list[dict] = []
        self._status_filter = ""
        self._days = 30
        self._selected_id: str | None = None
        self._build_header()
        if not ds.is_configured():
            self._render_not_configured()
        else:
            self._build_body()
            self.after(80, self._fetch)

    # ── Cabecera ─────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_2))

        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        title_row = ctk.CTkFrame(left, fg_color="transparent")
        title_row.pack(anchor="w")
        ctk.CTkLabel(title_row, text="✒", font=theme.font(20, "bold"),
                     text_color=ACCENT_DS).pack(side="left", padx=(0, theme.SPACE_2))
        ctk.CTkLabel(title_row, text="Contratos & Firmas", font=theme.FONT_TITLE,
                     text_color=theme.TEXT_MAIN).pack(side="left")
        ctk.CTkLabel(left, text="DocuSign eSignature", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_SUB, anchor="w").pack(anchor="w", pady=(theme.SPACE_1, 0))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.pack(side="right")
        self.lbl_api = ctk.CTkLabel(actions, text="", font=theme.FONT_SMALL_BOLD)
        self.lbl_api.pack(side="left", padx=(0, theme.SPACE_2))
        self.lbl_sync = ctk.CTkLabel(actions, text="", font=theme.FONT_TINY,
                                     text_color=theme.TEXT_MUTED)
        self.lbl_sync.pack(side="left", padx=(0, theme.SPACE_2))
        self.btn_refresh = ctk.CTkButton(
            actions, text="↻  Actualizar", width=120, height=theme.HEIGHT_INPUT,
            corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL_BOLD,
            fg_color="transparent", hover_color=theme.BG_INPUT, text_color=theme.TEXT_SUB,
            border_width=1, border_color=theme.BORDER, command=self._fetch)
        self.btn_refresh.pack(side="left")

    # ── Estado no configurado ────────────────────────────────────────────────

    def _render_not_configured(self) -> None:
        box = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=14,
                           border_width=1, border_color=theme.BORDER)
        box.pack(fill="x", padx=theme.SPACE_6, pady=theme.SPACE_5)
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(padx=theme.SPACE_6, pady=theme.SPACE_6)
        ctk.CTkLabel(inner, text="✒", font=theme.font(34, "bold"), text_color=ACCENT_DS).pack()
        ctk.CTkLabel(inner, text="DocuSign no configurado", font=theme.font(16, "bold"),
                     text_color=theme.TEXT_MAIN).pack(pady=(theme.SPACE_2, theme.SPACE_1))
        ctk.CTkLabel(inner, text="Para activar la integración añade estas variables al .env del proyecto:",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                     wraplength=520, justify="center").pack(pady=(0, theme.SPACE_3))
        env_block = (
            "DOCUSIGN_INTEGRATION_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx\n"
            "DOCUSIGN_USER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx\n"
            "DOCUSIGN_ACCOUNT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx\n"
            "DOCUSIGN_BASE_URL=https://demo.docusign.net\n"
            "DOCUSIGN_RSA_PRIVATE_KEY_PATH=docusign_private.pem"
        )
        code = ctk.CTkFrame(inner, fg_color=theme.BG_PAGE, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        code.pack(fill="x")
        ctk.CTkLabel(code, text=env_block, font=theme.mfont(11), text_color="#A5F3FC",
                     justify="left", anchor="w").pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_3)

    # ── Cuerpo: KPIs + filtros + master-detail ───────────────────────────────

    def _build_body(self) -> None:
        # KPIs
        kpi_row = ctk.CTkFrame(self, fg_color="transparent")
        kpi_row.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_2, theme.SPACE_2))
        self._kpi_labels: dict[str, ctk.CTkLabel] = {}
        kdefs = [("Pendientes", "sent", theme.AMBER), ("Completados", "completed", theme.GREEN),
                 ("Rechazados", "declined", theme.RED), ("Expirados", "timed_out", theme.AMBER),
                 ("Total", "total", ACCENT_DS)]
        for i, (label, key, col) in enumerate(kdefs):
            kpi_row.grid_columnconfigure(i, weight=1, uniform="k")
            card = ctk.CTkFrame(kpi_row, fg_color=theme.BG_CARD, corner_radius=10,
                                border_width=1, border_color=theme.BORDER)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else theme.SPACE_2, 0))
            ctk.CTkLabel(card, text=label.upper(), font=theme.FONT_LABEL,
                         text_color=theme.TEXT_MUTED, anchor="w").pack(
                anchor="w", padx=theme.SPACE_3, pady=(theme.SPACE_3, 0))
            v = ctk.CTkLabel(card, text="…", font=theme.font(22, "bold"), text_color=col, anchor="w")
            v.pack(anchor="w", padx=theme.SPACE_3, pady=(0, theme.SPACE_3))
            self._kpi_labels[key] = v

        # Filtros
        filters = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=10,
                               border_width=1, border_color=theme.BORDER)
        filters.pack(fill="x", padx=theme.SPACE_6, pady=(0, theme.SPACE_2))
        fin = ctk.CTkFrame(filters, fg_color="transparent")
        fin.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_2)

        estados = ["Todos los estados"] + [m["label"] for m in ds.STATUS_META.values()]
        self._estado_label_to_key = {m["label"]: k for k, m in ds.STATUS_META.items()}
        self.opt_estado = ctk.CTkOptionMenu(
            fin, values=estados, width=180, height=theme.HEIGHT_INPUT,
            corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL,
            fg_color=theme.BG_INPUT, button_color=theme.BORDER_STRONG,
            button_hover_color=theme.TEXT_MUTED, text_color=theme.TEXT_MAIN, command=self._on_estado)
        self.opt_estado.pack(side="left", padx=(0, theme.SPACE_2))

        self.opt_days = ctk.CTkOptionMenu(
            fin, values=[d[0] for d in DAYS_OPTIONS], width=170, height=theme.HEIGHT_INPUT,
            corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL,
            fg_color=theme.BG_INPUT, button_color=theme.BORDER_STRONG,
            button_hover_color=theme.TEXT_MUTED, text_color=theme.TEXT_MAIN, command=self._on_days)
        self.opt_days.set("Últimos 30 días")
        self.opt_days.pack(side="left", padx=(0, theme.SPACE_2))

        self.ent_search = ctk.CTkEntry(
            fin, placeholder_text="Buscar asunto o remitente…",
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_SMALL)
        self.ent_search.pack(side="left", fill="x", expand=True)
        self.ent_search.bind("<KeyRelease>", lambda e: self._render_list())

        # Master-detail
        split = ctk.CTkFrame(self, fg_color="transparent")
        split.pack(fill="both", expand=True, padx=theme.SPACE_6, pady=(0, theme.SPACE_5))

        left = ctk.CTkFrame(split, fg_color="transparent", width=520)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.list_status = ctk.CTkLabel(left, text="", font=theme.FONT_TINY,
                                        text_color=theme.TEXT_MUTED, anchor="w")
        self.list_status.pack(fill="x", pady=(0, theme.SPACE_1))
        self.list_scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.list_scroll.pack(fill="both", expand=True)

        self.detail = ctk.CTkFrame(split, fg_color=theme.BG_CARD, corner_radius=12,
                                   border_width=1, border_color=theme.BORDER)
        self.detail.pack(side="left", fill="both", expand=True, padx=(theme.SPACE_4, 0))
        self._detail_placeholder()

    # ── Filtros ──────────────────────────────────────────────────────────────

    def _on_estado(self, label: str) -> None:
        # Filtro de estado en cliente — no requiere volver a llamar a la API.
        self._status_filter = self._estado_label_to_key.get(label, "")
        self._render_list()

    def _on_days(self, label: str) -> None:
        # Cambiar el periodo sí cambia la consulta al servidor → re-fetch.
        self._days = dict(DAYS_OPTIONS).get(label, 30)
        self._fetch()

    # ── Fetch ────────────────────────────────────────────────────────────────

    def _fetch(self) -> None:
        self.btn_refresh.configure(text="Actualizando…")
        self.list_status.configure(text="⏳  Cargando sobres…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                svc = ds.get_service()
                effective = 3650 if self._days == 0 else self._days
                # Una sola llamada de red: todos los estados del periodo.
                envelopes = svc.list_envelopes(days=effective)
                kpis = ds.kpis_from_envelopes(envelopes)
                self.after(0, lambda: self._on_fetched(envelopes, kpis))
            except Exception as exc:
                logger.exception("Error DocuSign fetch")
                msg = str(exc)
                self.after(0, lambda: self._on_error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_error(self, msg: str) -> None:
        self.lbl_api.configure(text="✗ Error de API", text_color=theme.RED)
        self.btn_refresh.configure(text="↻  Actualizar")
        self.list_status.configure(text=f"✗  {msg}", text_color=theme.RED)

    def _on_fetched(self, envelopes: list[dict], kpis: dict) -> None:
        self._envelopes = envelopes
        self.lbl_api.configure(text="● API conectada", text_color=theme.GREEN)
        self.lbl_sync.configure(text=f"Sync: {datetime.now().strftime('%H:%M')}")
        self.btn_refresh.configure(text="↻  Actualizar")
        by = kpis.get("by_status", {})
        for key, lbl in self._kpi_labels.items():
            lbl.configure(text=str(kpis.get("total", 0) if key == "total" else by.get(key, 0)))
        self._render_list()

    # ── Lista (master) ───────────────────────────────────────────────────────

    def _filtered(self) -> list[dict]:
        rows = self._envelopes
        if self._status_filter:
            rows = [e for e in rows if e.get("status") == self._status_filter]
        q = self.ent_search.get().strip().lower()
        if q:
            rows = [e for e in rows
                    if q in str(e.get("subject", "")).lower()
                    or q in str(e.get("sender_name", "")).lower()
                    or q in str(e.get("sender", "")).lower()]
        return rows

    def _render_list(self) -> None:
        for w in self.list_scroll.winfo_children():
            w.destroy()
        self._card_widgets = {}  # id sobre → frame de la tarjeta
        rows = self._filtered()
        if not rows:
            empty = ctk.CTkFrame(self.list_scroll, fg_color="transparent")
            empty.pack(fill="x", pady=40)
            ctk.CTkLabel(empty, text="✒", font=theme.font(26, "bold"),
                         text_color=theme.BORDER_STRONG).pack()
            ctk.CTkLabel(empty, text="No se encontraron sobres", font=theme.FONT_SMALL_BOLD,
                         text_color=theme.TEXT_SUB).pack(pady=(theme.SPACE_2, 0))
            self.list_status.configure(text="0 sobres", text_color=theme.TEXT_MUTED)
            return
        for env in rows:
            self._list_item(env)
        self.list_status.configure(text=f"{len(rows)} sobre(s)", text_color=theme.TEXT_MUTED)

    def _list_item(self, env: dict) -> None:
        selected = env.get("id") == self._selected_id
        card = ctk.CTkFrame(
            self.list_scroll, corner_radius=10, border_width=1,
            fg_color=theme.ACCENT_SOFT if selected else theme.BG_CARD,
            border_color=ACCENT_DS if selected else theme.BORDER)
        card.pack(fill="x", pady=(0, theme.SPACE_2))
        self._card_widgets[env.get("id")] = card
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_2)

        # Línea 1: asunto + estado
        l1 = ctk.CTkFrame(inner, fg_color="transparent")
        l1.pack(fill="x")
        subj = env.get("subject") or "Sin asunto"
        ctk.CTkLabel(l1, text=subj if len(subj) <= 46 else subj[:46] + "…",
                     font=theme.FONT_SMALL_BOLD, text_color=theme.TEXT_MAIN, anchor="w").pack(
            side="left", fill="x", expand=True)
        _badge(l1, env.get("status", "")).pack(side="right")

        # Línea 2: remitente + fecha
        l2 = ctk.CTkFrame(inner, fg_color="transparent")
        l2.pack(fill="x", pady=(2, 0))
        ctk.CTkLabel(l2, text=env.get("sender_name") or env.get("sender") or "—",
                     font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w").pack(
            side="left", fill="x", expand=True)
        ctk.CTkLabel(l2, text=_fmt_date(env.get("sent_at")), font=theme.FONT_TINY,
                     text_color=theme.TEXT_MUTED).pack(side="right")

        # Línea 3: avatares de firmantes
        recips = env.get("recipients") or []
        if recips:
            l3 = ctk.CTkFrame(inner, fg_color="transparent")
            l3.pack(fill="x", pady=(theme.SPACE_2, 0))
            for r in recips[:6]:
                _avatar(l3, r, size=22).pack(side="left", padx=(0, 3))
            if len(recips) > 6:
                ctk.CTkLabel(l3, text=f"+{len(recips) - 6}", font=theme.FONT_TINY,
                             text_color=theme.TEXT_MUTED).pack(side="left", padx=(2, 0))

        _bind_click(card, lambda e=env: self._select(e))

    # ── Detalle (inline) ─────────────────────────────────────────────────────

    def _detail_placeholder(self) -> None:
        for w in self.detail.winfo_children():
            w.destroy()
        box = ctk.CTkFrame(self.detail, fg_color="transparent")
        box.pack(expand=True, pady=70)
        ctk.CTkLabel(box, text="✒", font=theme.font(34, "bold"),
                     text_color=theme.BORDER_STRONG).pack()
        ctk.CTkLabel(box, text="Selecciona un sobre", font=theme.FONT_BODY_BOLD,
                     text_color=theme.TEXT_SUB).pack(pady=(theme.SPACE_2, 0))
        ctk.CTkLabel(box, text="Haz clic en un sobre para ver su información,\nfirmantes e historial.",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, justify="center").pack(pady=(2, 0))

    def _set_card_selected(self, card, selected: bool) -> None:
        if card is None or not card.winfo_exists():
            return
        card.configure(fg_color=theme.ACCENT_SOFT if selected else theme.BG_CARD,
                       border_color=ACCENT_DS if selected else theme.BORDER)

    def _select(self, env: dict) -> None:
        new_id = env.get("id")
        if new_id == self._selected_id:
            return
        # Solo restila la tarjeta anterior y la nueva — NO reconstruye la lista.
        cards = getattr(self, "_card_widgets", {})
        self._set_card_selected(cards.get(self._selected_id), False)
        self._selected_id = new_id
        self._set_card_selected(cards.get(new_id), True)
        self._show_detail_loading()

        def worker():
            try:
                full = ds.get_service().get_envelope(self._selected_id)
                self.after(0, lambda: self._render_detail(env, full))
            except Exception as exc:
                # Si el detalle falla, mostramos al menos lo que ya tenemos del listado
                logger.warning("Detalle DocuSign no disponible: %s", exc)
                self.after(0, lambda: self._render_detail(env, env))

        threading.Thread(target=worker, daemon=True).start()

    def _show_detail_loading(self) -> None:
        for w in self.detail.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.detail, text="⏳  Cargando detalle…", font=theme.FONT_BODY,
                     text_color=theme.TEXT_MUTED).pack(pady=50)

    def _render_detail(self, env: dict, data: dict) -> None:
        if env.get("id") != self._selected_id:
            return
        for w in self.detail.winfo_children():
            w.destroy()

        # Cabecera del detalle
        head = ctk.CTkFrame(self.detail, fg_color="transparent")
        head.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_3, theme.SPACE_2))
        bar = ctk.CTkFrame(head, fg_color="transparent")
        bar.pack(fill="x")
        title_wrap = ctk.CTkFrame(bar, fg_color="transparent")
        title_wrap.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(title_wrap, text=data.get("subject") or "Detalle del sobre",
                     font=theme.font(15, "bold"), text_color=theme.TEXT_MAIN,
                     anchor="w", justify="left", wraplength=620).pack(anchor="w")
        _badge(title_wrap, data.get("status", "")).pack(anchor="w", pady=(theme.SPACE_2, 0))
        if data.get("status") == "completed":
            ctk.CTkButton(bar, text="⤓  Descargar PDF", width=140, height=32,
                          corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL_BOLD,
                          fg_color=theme.BG_INPUT, hover_color=theme.BORDER,
                          text_color=theme.GREEN, command=lambda: self._download(env)).pack(side="right")
        ctk.CTkFrame(head, fg_color=theme.BORDER, height=1).pack(fill="x", pady=(theme.SPACE_3, 0))

        body = ctk.CTkScrollableFrame(self.detail, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=theme.SPACE_3, pady=(0, theme.SPACE_3))

        # Información
        _section(body, "Información").pack(fill="x", pady=(theme.SPACE_1, theme.SPACE_2))
        grid = ctk.CTkFrame(body, fg_color="transparent")
        grid.pack(fill="x", pady=(0, theme.SPACE_3))
        for c in range(2):
            grid.grid_columnconfigure(c, weight=1, uniform="i")
        info = [("Remitente", data.get("sender_name") or data.get("sender") or "—"),
                ("Enviado", _fmt_date(data.get("sent_at"))),
                ("Completado", _fmt_date(data.get("completed_at"))),
                ("Expira", _fmt_date(data.get("expires_at")))]
        for i, (label, val) in enumerate(info):
            cell = ctk.CTkFrame(grid, fg_color=theme.BG_PAGE, corner_radius=8,
                                border_width=1, border_color=theme.BORDER)
            cell.grid(row=i // 2, column=i % 2, sticky="ew",
                      padx=(0 if i % 2 == 0 else theme.SPACE_2, 0), pady=(0, theme.SPACE_2))
            ctk.CTkLabel(cell, text=label.upper(), font=theme.FONT_TINY,
                         text_color=theme.TEXT_MUTED, anchor="w").pack(
                anchor="w", padx=theme.SPACE_3, pady=(theme.SPACE_2, 0))
            ctk.CTkLabel(cell, text=str(val), font=theme.FONT_SMALL_BOLD,
                         text_color=theme.TEXT_MAIN, anchor="w").pack(
                anchor="w", padx=theme.SPACE_3, pady=(0, theme.SPACE_2))

        # Firmantes
        recips = data.get("recipients") or []
        if recips:
            _section(body, f"Firmantes ({len(recips)})").pack(fill="x", pady=(0, theme.SPACE_2))
            for r in recips:
                rrow = ctk.CTkFrame(body, fg_color=theme.BG_PAGE, corner_radius=8,
                                    border_width=1, border_color=theme.BORDER)
                rrow.pack(fill="x", pady=(0, theme.SPACE_1))
                _avatar(rrow, r, size=26).pack(side="left", padx=theme.SPACE_2, pady=theme.SPACE_2)
                mid = ctk.CTkFrame(rrow, fg_color="transparent")
                mid.pack(side="left", fill="x", expand=True, pady=theme.SPACE_2)
                ctk.CTkLabel(mid, text=r.get("name", "—"), font=theme.FONT_SMALL_BOLD,
                             text_color=theme.TEXT_MAIN, anchor="w").pack(anchor="w")
                ctk.CTkLabel(mid, text=r.get("email", ""), font=theme.FONT_TINY,
                             text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
                _badge(rrow, r.get("status", "")).pack(side="right", padx=theme.SPACE_3)

        # Historial
        history = data.get("history") or []
        if history:
            _section(body, "Historial de eventos").pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_2))
            tl = ctk.CTkFrame(body, fg_color="transparent")
            tl.pack(fill="x")
            for h in history:
                hrow = ctk.CTkFrame(tl, fg_color="transparent")
                hrow.pack(fill="x", pady=2)
                ctk.CTkFrame(hrow, fg_color=ACCENT_DS, width=8, height=8, corner_radius=4).pack(
                    side="left", padx=(theme.SPACE_1, theme.SPACE_3))
                txt = ctk.CTkFrame(hrow, fg_color="transparent")
                txt.pack(side="left", fill="x", expand=True)
                ctk.CTkLabel(txt, text=h.get("event") or "Evento", font=theme.FONT_SMALL,
                             text_color=theme.TEXT_SUB, anchor="w").pack(anchor="w")
                if h.get("user"):
                    ctk.CTkLabel(txt, text=h.get("user"), font=theme.FONT_TINY,
                                 text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
                if h.get("date"):
                    ctk.CTkLabel(hrow, text=_fmt_date(h.get("date")), font=theme.mfont(9),
                                 text_color=theme.TEXT_MUTED).pack(side="right", padx=theme.SPACE_2)

    # ── Descarga ─────────────────────────────────────────────────────────────

    def _download(self, env: dict) -> None:
        env_id = env.get("id")
        path = filedialog.asksaveasfilename(
            parent=self, title="Guardar PDF firmado", defaultextension=".pdf",
            initialfile=f"sobre_{env_id}.pdf", filetypes=[("PDF", "*.pdf")])
        if not path:
            return

        def worker():
            try:
                data = ds.get_service().download_combined_pdf(env_id)
                with open(path, "wb") as f:
                    f.write(data)
                import os as _os
                self.after(0, lambda: ui.toast(
                    self, "PDF descargado", _os.path.basename(path), kind="success"))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda: messagebox.showerror(
                    "Error", f"No se pudo descargar:\n{msg}", parent=self))

        threading.Thread(target=worker, daemon=True).start()
