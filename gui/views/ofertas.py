"""Vista Ofertas — unifica los 3 buzones comerciales y clasifica por portal.

Distribución master-detail (como Contratos & Firmas):
  • Cabecera: estado, última sync, rango de días, actualizar.
  • KPIs: Total · Sin leer · Portales · Vía portal/Directo.
  • Desglose "Entrada por portal" (barras).
  • Filtros: buzón · portal · búsqueda (en cliente, instantáneos).
  • Lista de ofertas (izq.) + detalle del correo (der.), sin pop-ups.

Lecturas IMAP en hilo. Si no hay contraseñas en .env → estado "no configurado".
"""

import logging
import threading
from datetime import datetime

import customtkinter as ctk

from core.config import OFERTAS_ACCOUNTS
from core.services import ofertas as of
from gui import theme
from gui.widgets import ui

logger = logging.getLogger(__name__)

ACCENT_OF = theme.ACCENT

DAYS_OPTIONS = [("Últimos 7 días", 7), ("Últimos 15 días", 15), ("Últimos 30 días", 30),
                ("Últimos 60 días", 60), ("Últimos 90 días", 90)]

# Colores estables por buzón
_BUZON_COLORS = {"Comercial": "#2563EB", "Dpto. Comercial": "#0D9488", "Info": "#D97706"}


def _fmt_date(s) -> str:
    return str(s)[:10] if s else "—"


def _buzon_color(label: str) -> str:
    return _BUZON_COLORS.get(label, theme.TEXT_MUTED)


def _bind_click(widget, cmd) -> None:
    widget.bind("<Button-1>", lambda e: cmd())
    for ch in widget.winfo_children():
        _bind_click(ch, cmd)


def _section(parent, text: str, color: str | None = None):
    return ui.section_header(parent, text, color)


class OfertasView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._ofertas: list[dict] = []
        self._buzon_filter = ""
        self._portal_filter = ""
        self._days = 30
        self._selected_uid: str | None = None
        self._card_widgets: dict[str, ctk.CTkFrame] = {}

        self._build_header()
        if not of.available():
            self._render_not_configured()
        else:
            self._build_body()
            self.after(120, self._fetch)

    # ── Cabecera ─────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_2))
        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        tr = ctk.CTkFrame(left, fg_color="transparent")
        tr.pack(anchor="w")
        ctk.CTkLabel(tr, text="✉", font=theme.font(20, "bold"),
                     text_color=ACCENT_OF).pack(side="left", padx=(0, theme.SPACE_2))
        ctk.CTkLabel(tr, text="Ofertas", font=theme.FONT_TITLE,
                     text_color=theme.TEXT_MAIN).pack(side="left")
        ctk.CTkLabel(left, text="Bandejas comercial · dptocomercial · info  ·  control de entrada por portal",
                     font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w").pack(
            anchor="w", pady=(theme.SPACE_1, 0))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.pack(side="right")
        self.lbl_sync = ctk.CTkLabel(actions, text="", font=theme.FONT_TINY,
                                     text_color=theme.TEXT_MUTED)
        self.lbl_sync.pack(side="left", padx=(0, theme.SPACE_2))
        self.opt_days = ctk.CTkOptionMenu(
            actions, values=[d[0] for d in DAYS_OPTIONS], width=150, height=theme.HEIGHT_INPUT,
            corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL,
            fg_color=theme.BG_INPUT, button_color=theme.BORDER_STRONG,
            button_hover_color=theme.TEXT_MUTED, text_color=theme.TEXT_MAIN, command=self._on_days)
        self.opt_days.set("Últimos 30 días")
        self.opt_days.pack(side="left", padx=(0, theme.SPACE_2))
        self.btn_refresh = ctk.CTkButton(
            actions, text="↻  Actualizar", width=120, height=theme.HEIGHT_INPUT,
            corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL_BOLD,
            fg_color="transparent", hover_color=theme.BG_INPUT, text_color=theme.TEXT_SUB,
            border_width=1, border_color=theme.BORDER, command=lambda: self._fetch(force=True))
        self.btn_refresh.pack(side="left")

    # ── No configurado ───────────────────────────────────────────────────────

    def _render_not_configured(self) -> None:
        box = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=14,
                           border_width=1, border_color=theme.BORDER)
        box.pack(fill="x", padx=theme.SPACE_6, pady=theme.SPACE_5)
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(padx=theme.SPACE_6, pady=theme.SPACE_6)
        ctk.CTkLabel(inner, text="✉", font=theme.font(34, "bold"), text_color=ACCENT_OF).pack()
        ctk.CTkLabel(inner, text="Buzones de ofertas no configurados", font=theme.font(16, "bold"),
                     text_color=theme.TEXT_MAIN).pack(pady=(theme.SPACE_2, theme.SPACE_1))
        ctk.CTkLabel(inner, text="Añade las contraseñas de los buzones al .env del proyecto:",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(pady=(0, theme.SPACE_3))
        env_block = ("OFERTAS_COMERCIAL_PASS=********\n"
                     "OFERTAS_DPTO_PASS=********\n"
                     "OFERTAS_INFO_PASS=********")
        code = ctk.CTkFrame(inner, fg_color=theme.BG_PAGE, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        code.pack(fill="x")
        ctk.CTkLabel(code, text=env_block, font=theme.mfont(11), text_color="#A5F3FC",
                     justify="left", anchor="w").pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_3)

    # ── Cuerpo ───────────────────────────────────────────────────────────────

    def _build_body(self) -> None:
        # KPIs
        self.kpi_row = ctk.CTkFrame(self, fg_color="transparent")
        self.kpi_row.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_2, theme.SPACE_2))
        self._kpi = {}
        for i, (key, label, col) in enumerate([
                ("total", "Total", ACCENT_OF), ("sin_leer", "Sin leer", theme.AMBER),
                ("n_portales", "Portales", theme.BLUE), ("via_portal", "Vía portal", theme.GREEN)]):
            self.kpi_row.grid_columnconfigure(i, weight=1, uniform="k")
            card = ctk.CTkFrame(self.kpi_row, fg_color=theme.BG_CARD, corner_radius=10,
                                border_width=1, border_color=theme.BORDER, height=80)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else theme.SPACE_2, 0))
            card.pack_propagate(False)
            ctk.CTkLabel(card, text=label.upper(), font=theme.FONT_LABEL,
                         text_color=theme.TEXT_MUTED, anchor="w").pack(
                anchor="w", padx=theme.SPACE_3, pady=(theme.SPACE_3, 0))
            v = ctk.CTkLabel(card, text="…", font=theme.font(22, "bold"), text_color=col, anchor="w")
            v.pack(anchor="w", padx=theme.SPACE_3, pady=(0, theme.SPACE_3))
            self._kpi[key] = v

        # Desglose por portal
        self.portal_box = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=10,
                                       border_width=1, border_color=theme.BORDER)
        self.portal_box.pack(fill="x", padx=theme.SPACE_6, pady=(0, theme.SPACE_2))

        # Filtros
        filt = ctk.CTkFrame(self, fg_color="transparent")
        filt.pack(fill="x", padx=theme.SPACE_6, pady=(0, theme.SPACE_2))
        self.opt_buzon = ctk.CTkOptionMenu(
            filt, values=["Todos los buzones"] + [a["label"] for a in OFERTAS_ACCOUNTS],
            width=180, height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL,
            fg_color=theme.BG_INPUT, button_color=theme.BORDER_STRONG,
            button_hover_color=theme.TEXT_MUTED, text_color=theme.TEXT_MAIN, command=self._on_buzon)
        self.opt_buzon.pack(side="left", padx=(0, theme.SPACE_2))
        self.opt_portal = ctk.CTkOptionMenu(
            filt, values=["Todos los portales"], width=200, height=theme.HEIGHT_INPUT,
            corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL,
            fg_color=theme.BG_INPUT, button_color=theme.BORDER_STRONG,
            button_hover_color=theme.TEXT_MUTED, text_color=theme.TEXT_MAIN, command=self._on_portal)
        self.opt_portal.pack(side="left", padx=(0, theme.SPACE_2))
        self.ent_search = ctk.CTkEntry(
            filt, placeholder_text="Buscar asunto / remitente…", height=theme.HEIGHT_INPUT,
            corner_radius=theme.RADIUS_MD, fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_SMALL)
        self.ent_search.pack(side="left", fill="x", expand=True)
        self.ent_search.bind("<KeyRelease>", lambda e: self._render_list())

        # Master-detail
        split = ctk.CTkFrame(self, fg_color="transparent")
        split.pack(fill="both", expand=True, padx=theme.SPACE_6, pady=(0, theme.SPACE_5))
        left = ctk.CTkFrame(split, fg_color="transparent", width=540)
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

    # ── Filtros (cliente) ────────────────────────────────────────────────────

    def _on_days(self, label: str) -> None:
        self._days = dict(DAYS_OPTIONS).get(label, 30)
        self._fetch(force=True)

    def _on_buzon(self, label: str) -> None:
        self._buzon_filter = "" if label.startswith("Todos") else label
        self._render_list()

    def _on_portal(self, label: str) -> None:
        self._portal_filter = "" if label.startswith("Todos") else label
        self._render_list()

    # ── Fetch ────────────────────────────────────────────────────────────────

    def _fetch(self, force: bool = False) -> None:
        self.btn_refresh.configure(text="Actualizando…")
        self.list_status.configure(text="⏳  Cargando buzones…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                ofertas = of.fetch_ofertas(self._days, force=force)
                self.after(0, lambda: self._on_fetched(ofertas))
            except Exception as exc:
                logger.exception("Error Ofertas fetch")
                msg = str(exc)
                self.after(0, lambda: self._on_error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_error(self, msg: str) -> None:
        self.btn_refresh.configure(text="↻  Actualizar")
        self.list_status.configure(text=f"✗  {msg}", text_color=theme.RED)

    def _on_fetched(self, ofertas: list[dict]) -> None:
        self._ofertas = ofertas
        self.btn_refresh.configure(text="↻  Actualizar")
        self.lbl_sync.configure(text=f"Sync: {datetime.now().strftime('%H:%M')}")
        k = of.kpis(ofertas)
        self._kpi["total"].configure(text=str(k["total"]))
        self._kpi["sin_leer"].configure(text=str(k["sin_leer"]))
        self._kpi["n_portales"].configure(text=str(k["n_portales"]))
        self._kpi["via_portal"].configure(text=f"{k['via_portal']} / {k['directos']}")
        self.opt_portal.configure(values=["Todos los portales"] + [p for p, _ in k["por_portal"]])
        self._render_portal_breakdown(k["por_portal"])
        self._render_list()
        # avisos de cuentas que fallaron
        if of.last_errors:
            self.list_status.configure(
                text="⚠  " + " · ".join(of.last_errors)[:120], text_color=theme.AMBER)

    def _render_portal_breakdown(self, por_portal: list) -> None:
        for w in self.portal_box.winfo_children():
            w.destroy()
        inner = ctk.CTkFrame(self.portal_box, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_2)
        _section(inner, "Entrada por portal / origen").pack(fill="x", pady=(0, theme.SPACE_1))
        if not por_portal:
            ctk.CTkLabel(inner, text="Sin datos", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTED).pack(anchor="w")
            return
        top = por_portal[:6]
        mx = max((c for _, c in top), default=1) or 1
        for name, count in top:
            row = ctk.CTkFrame(inner, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=name[:26], font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                         anchor="w", width=200).pack(side="left")
            track = ctk.CTkFrame(row, height=10, fg_color=theme.BORDER, corner_radius=5)
            track.pack(side="left", fill="x", expand=True, padx=theme.SPACE_2)
            fill = ctk.CTkFrame(track, fg_color=ACCENT_OF, corner_radius=5)
            fill.place(relx=0, rely=0, relheight=1, relwidth=max(0.03, count / mx))
            ctk.CTkLabel(row, text=str(count), font=theme.FONT_SMALL_BOLD, text_color=ACCENT_OF,
                         width=42, anchor="e").pack(side="right")

    # ── Lista (master) ───────────────────────────────────────────────────────

    def _filtered(self) -> list[dict]:
        rows = self._ofertas
        if self._buzon_filter:
            rows = [o for o in rows if o["account"] == self._buzon_filter]
        if self._portal_filter:
            rows = [o for o in rows if o["portal"] == self._portal_filter]
        q = self.ent_search.get().strip().lower()
        if q:
            rows = [o for o in rows
                    if q in str(o.get("subject", "")).lower()
                    or q in str(o.get("from", "")).lower()
                    or q in str(o.get("portal", "")).lower()]
        return rows

    def _render_list(self) -> None:
        for w in self.list_scroll.winfo_children():
            w.destroy()
        self._card_widgets = {}
        rows = self._filtered()
        if not rows:
            empty = ctk.CTkFrame(self.list_scroll, fg_color="transparent")
            empty.pack(fill="x", pady=40)
            ctk.CTkLabel(empty, text="✉", font=theme.font(26, "bold"),
                         text_color=theme.BORDER_STRONG).pack()
            ctk.CTkLabel(empty, text="Sin ofertas en este filtro", font=theme.FONT_SMALL_BOLD,
                         text_color=theme.TEXT_SUB).pack(pady=(theme.SPACE_2, 0))
            self.list_status.configure(text="0 ofertas", text_color=theme.TEXT_MUTED)
            return
        for o in rows:
            self._list_item(o)
        self.list_status.configure(text=f"{len(rows)} oferta(s)", text_color=theme.TEXT_MUTED)

    def _card_key(self, o: dict) -> str:
        return f"{o['account_user']}::{o['uid']}"

    def _list_item(self, o: dict) -> None:
        key = self._card_key(o)
        selected = key == self._selected_uid
        card = ctk.CTkFrame(self.list_scroll, corner_radius=10, border_width=1,
                            fg_color=theme.ACCENT_SOFT if selected else theme.BG_CARD,
                            border_color=ACCENT_OF if selected else theme.BORDER)
        card.pack(fill="x", pady=(0, theme.SPACE_2))
        self._card_widgets[key] = card
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_2)

        # Línea 1: punto no-leído + asunto + fecha
        l1 = ctk.CTkFrame(inner, fg_color="transparent")
        l1.pack(fill="x")
        if not o.get("is_read"):
            ctk.CTkFrame(l1, fg_color=ACCENT_OF, width=8, height=8, corner_radius=4).pack(
                side="left", padx=(0, theme.SPACE_1), pady=4)
        subj = o.get("subject") or "(Sin asunto)"
        ctk.CTkLabel(l1, text=subj if len(subj) <= 50 else subj[:50] + "…",
                     font=theme.FONT_SMALL_BOLD if not o.get("is_read") else theme.FONT_SMALL,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(l1, text=_fmt_date(o.get("date")), font=theme.FONT_TINY,
                     text_color=theme.TEXT_MUTED).pack(side="right")

        # Línea 2: remitente
        ctk.CTkLabel(inner, text=o.get("from_email") or o.get("from") or "—",
                     font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w").pack(
            fill="x", pady=(2, 0))

        # Línea 3: chips buzón + portal
        l3 = ctk.CTkFrame(inner, fg_color="transparent")
        l3.pack(fill="x", pady=(theme.SPACE_1, 0))
        bcol = _buzon_color(o["account"])
        ctk.CTkLabel(l3, text=f"  {o['account']}  ", font=theme.FONT_TINY, text_color=bcol,
                     fg_color=theme.BG_INPUT, corner_radius=7, height=20).pack(side="left")
        pcol = theme.BLUE if o["tipo"] == "Portal" else theme.TEXT_MUTED
        ctk.CTkLabel(l3, text=f"  {o['portal']}  ", font=theme.FONT_TINY, text_color=pcol,
                     fg_color=theme.BG_INPUT, corner_radius=7, height=20).pack(
            side="left", padx=(theme.SPACE_1, 0))

        _bind_click(card, lambda oo=o: self._select(oo))

    # ── Detalle ──────────────────────────────────────────────────────────────

    def _detail_placeholder(self) -> None:
        for w in self.detail.winfo_children():
            w.destroy()
        box = ctk.CTkFrame(self.detail, fg_color="transparent")
        box.pack(expand=True, pady=70)
        ctk.CTkLabel(box, text="✉", font=theme.font(34, "bold"),
                     text_color=theme.BORDER_STRONG).pack()
        ctk.CTkLabel(box, text="Selecciona una oferta", font=theme.FONT_BODY_BOLD,
                     text_color=theme.TEXT_SUB).pack(pady=(theme.SPACE_2, 0))
        ctk.CTkLabel(box, text="Haz clic en un correo para ver su contenido y origen.",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(pady=(2, 0))

    def _set_card_selected(self, card, selected: bool) -> None:
        if card is None or not card.winfo_exists():
            return
        card.configure(fg_color=theme.ACCENT_SOFT if selected else theme.BG_CARD,
                       border_color=ACCENT_OF if selected else theme.BORDER)

    def _select(self, o: dict) -> None:
        key = self._card_key(o)
        if key == self._selected_uid:
            return
        self._set_card_selected(self._card_widgets.get(self._selected_uid), False)
        self._selected_uid = key
        self._set_card_selected(self._card_widgets.get(key), True)
        self._show_detail_loading()

        def worker():
            try:
                detail = of.get_detail(o["account"], o["uid"])
                self.after(0, lambda: self._render_detail(o, detail))
            except Exception as exc:
                logger.warning("Detalle oferta no disponible: %s", exc)
                self.after(0, lambda: self._render_detail(o, None))

        threading.Thread(target=worker, daemon=True).start()

    def _show_detail_loading(self) -> None:
        for w in self.detail.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.detail, text="⏳  Cargando correo…", font=theme.FONT_BODY,
                     text_color=theme.TEXT_MUTED).pack(pady=50)

    def _render_detail(self, o: dict, detail: dict | None) -> None:
        if self._card_key(o) != self._selected_uid:
            return
        for w in self.detail.winfo_children():
            w.destroy()
        d = detail or {}

        head = ctk.CTkFrame(self.detail, fg_color="transparent")
        head.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_3, theme.SPACE_2))
        ctk.CTkLabel(head, text=d.get("subject") or o.get("subject") or "(Sin asunto)",
                     font=theme.font(15, "bold"), text_color=theme.TEXT_MAIN, anchor="w",
                     justify="left", wraplength=640).pack(anchor="w")
        chips = ctk.CTkFrame(head, fg_color="transparent")
        chips.pack(fill="x", pady=(theme.SPACE_2, 0))
        bcol = _buzon_color(o["account"])
        ctk.CTkLabel(chips, text=f"  {o['account']}  ", font=theme.FONT_TINY, text_color=bcol,
                     fg_color=theme.BG_INPUT, corner_radius=7, height=22).pack(side="left")
        pcol = theme.BLUE if o["tipo"] == "Portal" else theme.TEXT_MUTED
        ctk.CTkLabel(chips, text=f"  {o['tipo']}: {o['portal']}  ", font=theme.FONT_TINY,
                     text_color=pcol, fg_color=theme.BG_INPUT, corner_radius=7, height=22).pack(
            side="left", padx=(theme.SPACE_1, 0))
        ctk.CTkFrame(head, fg_color=theme.BORDER, height=1).pack(fill="x", pady=(theme.SPACE_3, 0))

        # Metadatos
        meta = ctk.CTkFrame(self.detail, fg_color="transparent")
        meta.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_2, 0))
        for label, val in [("De", d.get("from") or o.get("from")),
                           ("Para", d.get("to")),
                           ("Fecha", _fmt_date(d.get("date") or o.get("date")))]:
            if not val:
                continue
            r = ctk.CTkFrame(meta, fg_color="transparent")
            r.pack(fill="x", pady=1)
            ctk.CTkLabel(r, text=label.upper(), font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                         anchor="w", width=54).pack(side="left")
            ctk.CTkLabel(r, text=str(val), font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                         anchor="w", justify="left", wraplength=600).pack(side="left", fill="x", expand=True)

        # Acciones
        if not o.get("is_read"):
            act = ctk.CTkFrame(self.detail, fg_color="transparent")
            act.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_2, 0))
            ctk.CTkButton(act, text="✓ Marcar como leído", height=30, corner_radius=theme.RADIUS_MD,
                          font=theme.FONT_SMALL_BOLD, fg_color="transparent",
                          hover_color=theme.BG_INPUT, text_color=theme.GREEN,
                          border_width=1, border_color=theme.BORDER,
                          command=lambda: self._mark_read(o)).pack(side="left")

        # Cuerpo
        _section(self.detail, "Contenido").pack(fill="x", padx=theme.SPACE_4,
                                                 pady=(theme.SPACE_3, theme.SPACE_1))
        body_host = ctk.CTkFrame(self.detail, fg_color=theme.BG_PAGE, corner_radius=8,
                                 border_width=1, border_color=theme.BORDER)
        body_host.pack(fill="both", expand=True, padx=theme.SPACE_4, pady=(0, theme.SPACE_4))
        txt = ctk.CTkTextbox(body_host, fg_color="transparent", text_color=theme.TEXT_SUB,
                             font=theme.FONT_SMALL, wrap="word")
        txt.pack(fill="both", expand=True, padx=theme.SPACE_2, pady=theme.SPACE_2)
        txt.insert("1.0", d.get("body") or "(No se pudo cargar el contenido)")
        txt.configure(state="disabled")

    def _mark_read(self, o: dict) -> None:
        def worker():
            of.mark_read(o["account"], o["uid"])
            o["is_read"] = True
            self.after(0, self._after_mark_read)

        threading.Thread(target=worker, daemon=True).start()

    def _after_mark_read(self) -> None:
        k = of.kpis(self._ofertas)
        self._kpi["sin_leer"].configure(text=str(k["sin_leer"]))
        self._render_list()
