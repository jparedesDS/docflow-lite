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

from tkinter import filedialog, messagebox

from core.config import OFERTAS_ACCOUNTS, USERS
from core.services import email_trust as et
from core.services import ofertas as of
from core.services import ofertas_meta as om
from gui import theme
from gui.widgets import ui
from gui.widgets.scrollframe import ScrollFrame

_TRUST_FILTERS = {"Verificado": "verificado", "Precaución": "precaucion", "Sospechoso": "sospechoso"}
_ASIGNADOS = ["Sin asignar"] + sorted({i.get("nombre", "") for i in USERS.values() if i.get("nombre")})

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


def _deadline_days(s: str):
    """Días hasta la fecha límite (negativo = vencida). None si no parsea."""
    from datetime import date, datetime
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            d = datetime.strptime(s, fmt).date()
            return (d - date.today()).days
        except ValueError:
            continue
    return None


def _engagement(o: dict) -> tuple[str, str, str]:
    """(etiqueta, color, icono) del estado de respuesta del correo.

    Solo refleja lo que se ve EN EL BUZÓN COMPARTIDO (flag \\Answered). Si un
    comercial respondió desde su correo personal, aquí saldrá "sin responder".
    """
    if o.get("is_answered"):
        return "Respondida", theme.GREEN, "↩"
    if o.get("is_read"):
        return "Leída sin responder", theme.AMBER, "•"
    return "Sin abrir", theme.TEXT_MUTED, "○"


class OfertasView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._ofertas: list[dict] = []
        self._buzon_filter = ""
        self._portal_filter = ""
        self._trust_filter = ""
        self._estado_filter = ""
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
        self.btn_export = ctk.CTkButton(
            actions, text="⤓  Excel", width=90, height=theme.HEIGHT_INPUT,
            corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL_BOLD,
            fg_color="transparent", hover_color=theme.BG_INPUT, text_color=theme.GREEN,
            border_width=1, border_color=theme.BORDER, command=self._export)
        self.btn_export.pack(side="left", padx=(0, theme.SPACE_2))
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
                ("total", "Ofertas", ACCENT_OF),
                ("sin_responder", "Sin responder", theme.AMBER),
                ("respondidas", "Respondidas", theme.BLUE),
                ("ganadas", "Ganadas", theme.GREEN),
                ("perdidas", "Perdidas", theme.RED)]):
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

        # Embudo comercial (chips de estado clicables) + métricas
        self.funnel_box = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=10,
                                       border_width=1, border_color=theme.BORDER)
        self.funnel_box.pack(fill="x", padx=theme.SPACE_6, pady=(0, theme.SPACE_2))

        # Filtros
        filt = ctk.CTkFrame(self, fg_color="transparent")
        filt.pack(fill="x", padx=theme.SPACE_6, pady=(0, theme.SPACE_2))
        self.opt_buzon = ctk.CTkOptionMenu(
            filt, values=["Todos los buzones"] + [a["label"] for a in OFERTAS_ACCOUNTS],
            width=180, height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL,
            fg_color=theme.BG_INPUT, button_color=theme.BORDER_STRONG,
            button_hover_color=theme.TEXT_MUTED, text_color=theme.TEXT_MAIN, command=self._on_buzon)
        self.opt_buzon.pack(side="left", padx=(0, theme.SPACE_2))
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
        self.list_scroll = ScrollFrame(left)
        self.list_scroll.pack(fill="both", expand=True)

        self.detail = ctk.CTkScrollableFrame(split, fg_color=theme.BG_CARD, corner_radius=12,
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

    def _on_trust(self, label: str) -> None:
        self._trust_filter = _TRUST_FILTERS.get(label, "")
        self._render_list()

    # ── Fetch ────────────────────────────────────────────────────────────────

    def _fetch(self, force: bool = False) -> None:
        self.btn_refresh.configure(text="Actualizando…")
        self.list_status.configure(text="⏳  Cargando ofertas…", text_color=theme.TEXT_MUTED)

        def worker():
            # FASE 1 (rápida): bandejas de entrada → mostrar ofertas ya
            try:
                offers = of.fetch_inbox_offers(self._days, force=force)
            except Exception as exc:
                logger.exception("Error Ofertas fetch")
                self.after(0, lambda e=str(exc): self._on_error(e))
                return
            self.after(0, lambda: self._on_offers(offers))
            # FASE 2 (lenta): escanear Enviados → marcar respuestas
            try:
                of.enrich_replies(offers, self._days)
            except Exception as exc:
                logger.debug("Ofertas: enrich respuestas falló: %s", exc)
            self.after(0, lambda: self._on_replies(offers))

        threading.Thread(target=worker, daemon=True).start()

    def _on_error(self, msg: str) -> None:
        if not self.winfo_exists():
            return
        self.btn_refresh.configure(text="↻  Actualizar")
        self.list_status.configure(text=f"✗  {msg}", text_color=theme.RED)

    def _update_kpis(self) -> None:
        k = of.kpis(self._ofertas)
        fn = of.funnel(self._ofertas)
        self._kpi["total"].configure(text=str(k["total"]))
        self._kpi["sin_responder"].configure(text=str(k["sin_responder"]))
        self._kpi["respondidas"].configure(text=str(k["respondidas"]))
        self._kpi["ganadas"].configure(text=str(fn["ganadas"]))
        self._kpi["perdidas"].configure(text=str(fn["perdidas"]))

    def _on_offers(self, offers: list[dict]) -> None:
        if not self.winfo_exists():
            return
        self._ofertas = offers
        self._update_kpis()
        self._refresh_funnel()
        self._render_list()
        self.list_status.configure(text=f"{len(offers)} ofertas · buscando respuestas…",
                                   text_color=theme.TEXT_MUTED)

    def _on_replies(self, offers: list[dict]) -> None:
        if not self.winfo_exists():
            return
        self._ofertas = offers
        self.btn_refresh.configure(text="↻  Actualizar")
        self.lbl_sync.configure(text=f"Sync: {datetime.now().strftime('%H:%M')}")
        self._update_kpis()
        self._refresh_funnel()
        self._render_list()
        if of.last_errors:
            self.list_status.configure(text="⚠  " + " · ".join(of.last_errors)[:120],
                                       text_color=theme.AMBER)
        else:
            self.list_status.configure(text=f"{len(offers)} oferta(s)", text_color=theme.TEXT_MUTED)

    def _refresh_funnel(self) -> None:
        for w in self.funnel_box.winfo_children():
            w.destroy()
        f = of.funnel(self._ofertas)
        inner = ctk.CTkFrame(self.funnel_box, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_2)
        head = ctk.CTkFrame(inner, fg_color="transparent")
        head.pack(fill="x")
        _section(head, "Seguimiento").pack(side="left")
        # Métricas de tracking a la derecha
        bits = [f"Respondidas {f['tasa_respuesta']}%"]
        if f["tiempo_medio_h"] is not None:
            t = f["tiempo_medio_h"]
            bits.append(f"T. medio respuesta {t:.0f}h" if t < 48 else f"T. medio respuesta {t/24:.1f}d")
        if f["tasa_exito"] is not None:
            bits.append(f"Éxito {f['tasa_exito']}%")
        ctk.CTkLabel(head, text="   ·   ".join(bits), font=theme.FONT_TINY,
                     text_color=theme.TEXT_SUB).pack(side="right")
        # Chips de estado (clicables → filtran)
        chips = ctk.CTkFrame(inner, fg_color="transparent")
        chips.pack(fill="x", pady=(theme.SPACE_1, 0))
        for estado in om.ESTADOS:
            n = f["por_estado"].get(estado, 0)
            col = om.ESTADO_COLOR.get(estado, theme.TEXT_MUTED)
            active = self._estado_filter == estado
            chip = ctk.CTkLabel(
                chips, text=f"  {estado}: {n}  ", font=theme.FONT_TINY,
                text_color="#FFFFFF" if active else col,
                fg_color=col if active else ui.blend(col, theme.BG_CARD, 0.16),
                corner_radius=8, height=24, cursor="hand2")
            chip.pack(side="left", padx=(0, theme.SPACE_1))
            chip.bind("<Button-1>", lambda e, s=estado: self._toggle_estado(s))

    def _toggle_estado(self, estado: str) -> None:
        self._estado_filter = "" if self._estado_filter == estado else estado
        self._refresh_funnel()
        self._render_list()

    def _export(self) -> None:
        if not self._ofertas:
            return
        from datetime import datetime
        default = f"ofertas_{datetime.now().strftime('%Y%m%d')}.xlsx"
        path = filedialog.asksaveasfilename(
            parent=self, title="Exportar ofertas", defaultextension=".xlsx",
            initialfile=default, filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            of.export_excel(self._filtered(), path)
            ui.toast(self, "Exportado", "Ofertas exportadas a Excel.", kind="success")
        except Exception as exc:
            messagebox.showerror("Exportar", f"No se pudo exportar:\n{exc}", parent=self)

    # ── Lista (master) ───────────────────────────────────────────────────────

    def _filtered(self) -> list[dict]:
        rows = self._ofertas
        if self._buzon_filter:
            rows = [o for o in rows if o["account"] == self._buzon_filter]
        if self._portal_filter:
            rows = [o for o in rows if o["portal"] == self._portal_filter]
        if self._trust_filter:
            rows = [o for o in rows if o.get("trust_level") == self._trust_filter]
        if self._estado_filter:
            rows = [o for o in rows if om.estado_of(o.get("meta_key", "")) == self._estado_filter]
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

        # Borde rojo si es sospechoso (señal de phishing sutil, sin ruido)
        if o.get("trust_level") == "sospechoso" and not selected:
            card.configure(border_color=theme.RED)

        # Línea 1: punto no-leído + asunto + fecha de entrada
        l1 = ctk.CTkFrame(inner, fg_color="transparent")
        l1.pack(fill="x")
        if not o.get("is_read"):
            ctk.CTkFrame(l1, fg_color=ACCENT_OF, width=8, height=8, corner_radius=4).pack(
                side="left", padx=(0, theme.SPACE_1), pady=4)
        subj = o.get("subject") or "(Sin asunto)"
        ctk.CTkLabel(l1, text=subj if len(subj) <= 46 else subj[:46] + "…",
                     font=theme.FONT_SMALL_BOLD if not o.get("is_read") else theme.FONT_SMALL,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(l1, text=_fmt_date(o.get("date")), font=theme.FONT_TINY,
                     text_color=theme.TEXT_MUTED).pack(side="right")

        # Línea 2: remitente
        ctk.CTkLabel(inner, text=o.get("from_email") or o.get("from") or "—",
                     font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w").pack(
            fill="x", pady=(2, 0))

        # Línea 3: resultado  ·····  estado de respuesta (con fecha)
        l3 = ctk.CTkFrame(inner, fg_color="transparent")
        l3.pack(fill="x", pady=(theme.SPACE_1, 0))
        estado = om.estado_of(o.get("meta_key", ""))
        ecol = om.ESTADO_COLOR.get(estado, theme.TEXT_MUTED)
        ctk.CTkLabel(l3, text=f"  {estado}  ", font=theme.FONT_TINY, text_color=ecol,
                     fg_color=ui.blend(ecol, theme.BG_CARD, 0.18), corner_radius=7,
                     height=20).pack(side="left")

        # Estado de respuesta (derecha): "✓ Luis Bravo · 11/06" o "Sin responder"
        if o.get("is_answered"):
            frm = o.get("answered_from") or ""
            when = _fmt_date(o.get("answered_at"))
            wd = f"{when[8:10]}/{when[5:7]}" if when and when != "—" else ""
            rtxt = f"✓ {frm}" if frm else "Respondida"
            if wd:
                rtxt += f" · {wd}"
            rcol = theme.GREEN
        elif o.get("is_read"):
            rtxt, rcol = "Leída sin responder", theme.AMBER
        else:
            rtxt, rcol = "Sin abrir", theme.TEXT_MUTED
        ctk.CTkLabel(l3, text=f"  {rtxt}  ", font=theme.FONT_TINY, text_color=rcol,
                     fg_color=ui.blend(rcol, theme.BG_CARD, 0.16), corner_radius=7,
                     height=20).pack(side="right")

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

        # Metadatos + fechas de tracking (entrada / contestada)
        meta = ctk.CTkFrame(self.detail, fg_color="transparent")
        meta.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_2, 0))
        rows = [("De", d.get("from") or o.get("from")),
                ("Entrada", _fmt_date(d.get("date") or o.get("date")))]
        if o.get("is_answered") and o.get("answered_at"):
            rows.append(("Contestada", _fmt_date(o.get("answered_at"))))
        for label, val in rows:
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

        # Estado de respuesta (con la salvedad de la bandeja compartida)
        elabel, ecolor, eicon = _engagement(o)
        ban = ctk.CTkFrame(self.detail, fg_color=ui.blend(ecolor, theme.BG_CARD, 0.10),
                           corner_radius=8, border_width=1,
                           border_color=ui.blend(ecolor, theme.BORDER, 0.4))
        ban.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_3, 0))
        bi = ctk.CTkFrame(ban, fg_color="transparent")
        bi.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_2)
        ctk.CTkLabel(bi, text=f"{eicon}  {elabel}", font=theme.FONT_SMALL_BOLD,
                     text_color=ecolor, anchor="w").pack(anchor="w")
        if o.get("is_answered"):
            when = _fmt_date(o.get("answered_at"))
            frm = o.get("answered_from") or ""
            via = o.get("answered_via")
            if via == "comercial":
                sub = f"Respondida por {frm}" if frm else "Respondida por un comercial"
            else:
                sub = "Respondida desde este buzón compartido"
                if frm:
                    sub += f" · {frm}"
            if when and when != "—":
                sub += f" el {when}"
            sub += "."
        elif o.get("is_read"):
            sub = ("Abierta pero sin responder desde el buzón. Puede haberse contestado "
                   "desde un correo personal (no deja rastro aquí) o estar pendiente.")
        else:
            sub = "Todavía nadie la ha abierto en el buzón."
        ctk.CTkLabel(bi, text=sub, font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                     anchor="w", justify="left", wraplength=600).pack(anchor="w", pady=(2, 0))

        # Ver el cuerpo de la respuesta enviada (descarga bajo demanda)
        if o.get("is_answered") and o.get("answered_msgid") and o.get("answered_user"):
            btn = ctk.CTkButton(bi, text="📄  Ver propuesta enviada", height=28,
                                corner_radius=theme.RADIUS_MD, font=theme.FONT_TINY,
                                fg_color="transparent", hover_color=theme.BG_INPUT,
                                text_color=ecolor, border_width=1, border_color=theme.BORDER)
            btn.configure(command=lambda b=btn: self._load_reply(o, b, bi))
            btn.pack(anchor="w", pady=(theme.SPACE_2, 0))

        # Contenido del email (visible nada más seleccionar)
        _section(self.detail, "Contenido del email").pack(fill="x", padx=theme.SPACE_4,
                                                          pady=(theme.SPACE_3, theme.SPACE_1))
        body_host = ctk.CTkFrame(self.detail, fg_color=theme.BG_PAGE, corner_radius=8,
                                 border_width=1, border_color=theme.BORDER, height=240)
        body_host.pack(fill="x", padx=theme.SPACE_4, pady=(0, theme.SPACE_1))
        body_host.pack_propagate(False)
        txt = ctk.CTkTextbox(body_host, fg_color="transparent", text_color=theme.TEXT_SUB,
                             font=theme.FONT_SMALL, wrap="word")
        txt.pack(fill="both", expand=True, padx=theme.SPACE_2, pady=theme.SPACE_2)
        txt.insert("1.0", d.get("body") or "(No se pudo cargar el contenido)")
        txt.configure(state="disabled")

        # Gestión comercial (pipeline + datos + notas)
        self._render_gestion(o)

        # Análisis de seguridad — solo si NO está verificado (evita ruido)
        trust = d.get("trust") or o.get("trust") or {}
        if trust.get("level") and trust["level"] != "verificado":
            self._render_security(trust, d.get("links") or [])

    def _render_gestion(self, o: dict) -> None:
        key = o.get("meta_key", "")
        m = om.get(key)
        _section(self.detail, "Gestión comercial", theme.ACCENT).pack(
            fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_3, theme.SPACE_1))
        box = ctk.CTkFrame(self.detail, fg_color=theme.BG_PAGE, corner_radius=8,
                           border_width=1, border_color=theme.BORDER)
        box.pack(fill="x", padx=theme.SPACE_4, pady=(0, theme.SPACE_1))
        grid = ctk.CTkFrame(box, fg_color="transparent")
        grid.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_3)
        for c in range(2):
            grid.grid_columnconfigure(c, weight=1, uniform="g")

        def cell(row, col, label, make):
            f = ctk.CTkFrame(grid, fg_color="transparent")
            f.grid(row=row, column=col, sticky="ew", padx=4, pady=(0, theme.SPACE_2))
            ctk.CTkLabel(f, text=label.upper(), font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                         anchor="w").pack(anchor="w")
            w = make(f)
            w.pack(fill="x")
            return w

        self._g_estado = ctk.StringVar(value=m.get("estado") or "Nueva")
        cell(0, 0, "Estado", lambda p: ctk.CTkOptionMenu(
            p, values=om.ESTADOS, variable=self._g_estado, height=30,
            corner_radius=theme.RADIUS_SM, font=theme.FONT_SMALL, fg_color=theme.BG_INPUT,
            button_color=theme.BORDER_STRONG, button_hover_color=theme.TEXT_MUTED,
            text_color=theme.TEXT_MAIN))
        self._g_asignado = ctk.StringVar(value=m.get("asignado") or "Sin asignar")
        cell(0, 1, "Asignado a", lambda p: ctk.CTkComboBox(
            p, values=_ASIGNADOS, variable=self._g_asignado, height=30,
            corner_radius=theme.RADIUS_SM, font=theme.FONT_SMALL, fg_color=theme.BG_INPUT,
            border_color=theme.BORDER, button_color=theme.BORDER_STRONG, text_color=theme.TEXT_MAIN))
        self._g_cliente = cell(1, 0, "Cliente", lambda p: self._g_entry(p, m.get("cliente", "")))

        # Notas
        nf = ctk.CTkFrame(box, fg_color="transparent")
        nf.pack(fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_2))
        ctk.CTkLabel(nf, text="NOTAS", font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                     anchor="w").pack(anchor="w")
        self._g_notas = ctk.CTkTextbox(nf, height=56, fg_color=theme.BG_INPUT,
                                       border_color=theme.BORDER, border_width=1,
                                       text_color=theme.TEXT_MAIN, font=theme.FONT_SMALL, wrap="word")
        self._g_notas.pack(fill="x")
        if m.get("notas"):
            self._g_notas.insert("1.0", m["notas"])

        ctk.CTkButton(box, text="💾  Guardar ficha", height=32, corner_radius=theme.RADIUS_MD,
                      font=theme.FONT_SMALL_BOLD, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color="#FFFFFF", command=lambda k=key: self._save_gestion(k)).pack(
            anchor="e", padx=theme.SPACE_3, pady=(0, theme.SPACE_3))

    def _g_entry(self, parent, value="") -> ctk.CTkEntry:
        e = ctk.CTkEntry(parent, height=30, corner_radius=theme.RADIUS_SM, fg_color=theme.BG_INPUT,
                         border_color=theme.BORDER, text_color=theme.TEXT_MAIN, font=theme.FONT_SMALL)
        if value:
            e.insert(0, str(value))
        return e

    def _save_gestion(self, key: str) -> None:
        om.set_fields(
            key, estado=self._g_estado.get(), asignado=self._g_asignado.get(),
            cliente=self._g_cliente.get().strip(),
            notas=self._g_notas.get("1.0", "end").strip())
        ui.toast(self, "Guardado", "Ficha de la oferta actualizada.", kind="success")
        self._render_list()       # refresca chips de estado en la lista
        self._refresh_funnel()    # refresca el embudo

    def _load_reply(self, o: dict, btn, holder) -> None:
        btn.configure(text="Cargando respuesta…", state="disabled")

        def work():
            try:
                body = of.get_reply_body(o.get("answered_user", ""),
                                         o.get("answered_folder", ""),
                                         o.get("answered_msgid", ""))
            except Exception as exc:
                body = f"(No se pudo cargar la respuesta: {exc})"
            self.after(0, lambda: self._show_reply(btn, holder, body))

        threading.Thread(target=work, daemon=True).start()

    def _show_reply(self, btn, holder, body: str) -> None:
        try:
            if not btn.winfo_exists():
                return
            btn.destroy()
            host = ctk.CTkFrame(holder, fg_color=theme.BG_INPUT, corner_radius=8,
                                border_width=1, border_color=theme.BORDER, height=170)
            host.pack(fill="x", pady=(theme.SPACE_2, 0))
            host.pack_propagate(False)
            tb = ctk.CTkTextbox(host, fg_color="transparent", text_color=theme.TEXT_SUB,
                                font=theme.FONT_SMALL, wrap="word")
            tb.pack(fill="both", expand=True, padx=6, pady=6)
            tb.insert("1.0", body or "(La respuesta no tiene texto o no se encontró el correo.)")
            tb.configure(state="disabled")
        except Exception:
            pass

    def _render_security(self, trust: dict, links: list) -> None:
        lvl = trust.get("level", "precaucion")
        meta = et.LEVEL_META.get(lvl, et.LEVEL_META["precaucion"])
        _section(self.detail, "Análisis de seguridad", meta["color"]).pack(
            fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_3, theme.SPACE_1))
        box = ctk.CTkFrame(self.detail, fg_color=theme.BG_PAGE, corner_radius=8,
                           border_width=1, border_color=ui.blend(meta["color"], theme.BORDER, 0.4))
        box.pack(fill="x", padx=theme.SPACE_4, pady=(0, theme.SPACE_1))
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_3)

        # Veredicto + chips de autenticación
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=f"  {meta['icon']}  {meta['label'].upper()}  ",
                     font=theme.font(12, "bold"), text_color=meta["color"],
                     fg_color=ui.blend(meta["color"], theme.BG_PAGE, 0.18),
                     corner_radius=8, height=28).pack(side="left")
        auth = trust.get("auth", {}) or {}
        for mech in ("spf", "dkim", "dmarc"):
            v = auth.get(mech) or "—"
            c = theme.GREEN if v == "pass" else (theme.RED if v == "fail" else theme.TEXT_MUTED)
            ctk.CTkLabel(top, text=f" {mech.upper()}:{v} ", font=theme.FONT_TINY, text_color=c,
                         fg_color=theme.BG_INPUT, corner_radius=6, height=22).pack(
                side="left", padx=(theme.SPACE_1, 0))

        # Motivos
        for r in trust.get("reasons", []):
            ctk.CTkLabel(inner, text=f"•  {r}", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                         anchor="w", justify="left", wraplength=600).pack(anchor="w", pady=(theme.SPACE_1, 0))

        # Enlaces sospechosos
        for lk in links:
            ctk.CTkLabel(inner, text=f"⚠  Enlace engañoso: muestra «{lk['text_domain']}» "
                                     f"pero lleva a «{lk['real_domain']}»",
                         font=theme.FONT_SMALL, text_color=theme.RED, anchor="w",
                         justify="left", wraplength=600).pack(anchor="w", pady=(theme.SPACE_1, 0))

        # Dominio + acción de confianza
        dom = trust.get("from_domain", "")
        foot = ctk.CTkFrame(inner, fg_color="transparent")
        foot.pack(fill="x", pady=(theme.SPACE_2, 0))
        if dom:
            ctk.CTkLabel(foot, text=f"Dominio: {dom}", font=theme.FONT_TINY,
                         text_color=theme.TEXT_MUTED, anchor="w").pack(side="left")
        if dom and not trust.get("trusted"):
            ctk.CTkButton(foot, text="✓ Marcar dominio de confianza", height=28,
                          corner_radius=theme.RADIUS_MD, font=theme.FONT_TINY,
                          fg_color="transparent", hover_color=theme.BG_INPUT,
                          text_color=theme.GREEN, border_width=1, border_color=theme.BORDER,
                          command=lambda d=dom: self._trust_domain(d)).pack(side="right")

    def _trust_domain(self, domain: str) -> None:
        of.add_trusted_domain(domain)
        ui.toast(self, "Dominio de confianza", f"{domain} marcado como de confianza.", kind="success")
        self._fetch(force=True)

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
