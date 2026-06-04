"""Vista Bandeja AI — listado IMAP + panel de detalle (sin clasificación IA aún)."""

import logging
import os
import threading
from email.utils import parsedate_to_datetime

import customtkinter as ctk
from tkinter import messagebox

from core.config import ANTHROPIC_API_KEY
from core.services import inbox as inbox_service
from gui import theme
from gui.widgets.table import DataTable

logger = logging.getLogger(__name__)

COLUMNS = ["", "Asunto", "Remitente", "Fecha"]


class InboxView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._emails: list[dict] = []
        self._current_uid: str | None = None
        self._search_after_id = None
        self._build_layout()
        self._reload()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(
            header, text="Bandeja AI", font=theme.FONT_TITLE,
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Lectura de correos del buzón IMAP · análisis con IA al configurar ANTHROPIC_API_KEY",
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(theme.SPACE_1, 0))

        # Toolbar
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_3, theme.SPACE_1))

        self.btn_reload = ctk.CTkButton(
            toolbar, text="↻  Recargar", font=theme.FONT_SMALL_BOLD,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self._reload,
        )
        self.btn_reload.pack(side="left")

        self.cmb_filter = ctk.CTkOptionMenu(
            toolbar, values=["Todos", "No leídos", "Leídos"],
            width=130, height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, button_color=theme.BG_INPUT,
            button_hover_color=theme.BG_CARD, text_color=theme.TEXT_MAIN,
            font=theme.FONT_SMALL, dropdown_font=theme.FONT_SMALL,
            command=lambda _: self._reload(),
        )
        self.cmb_filter.pack(side="left", padx=(theme.SPACE_2, 0))

        self.ent_search = ctk.CTkEntry(
            toolbar, placeholder_text="Buscar en asunto / remitente",
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_search.pack(side="left", fill="x", expand=True, padx=(theme.SPACE_2, 0))
        self.ent_search.bind("<KeyRelease>", lambda e: self._debounced_filter())

        self.lbl_count = ctk.CTkLabel(
            toolbar, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self.lbl_count.pack(side="right", padx=(theme.SPACE_3, 0))

        # Status line
        self.lbl_status = ctk.CTkLabel(
            self, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
        )
        self.lbl_status.pack(fill="x", padx=theme.SPACE_6)

        # Split: lista (izq) + detalle (der)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=theme.SPACE_6, pady=(theme.SPACE_2, theme.SPACE_6))
        body.grid_columnconfigure(0, weight=3, uniform="cols")
        body.grid_columnconfigure(1, weight=4, uniform="cols")
        body.grid_rowconfigure(0, weight=1)

        # ── Lista izquierda ─────────────────────────────────────────────────
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        self.table = DataTable(
            left, columns=COLUMNS,
            on_double_click=self._open_detail,
            selectmode="browse",
        )
        self.table.pack(fill="both", expand=True)
        self.table.set_columns_width({
            "": 28, "Asunto": 340, "Remitente": 200, "Fecha": 110,
        })
        self.table.tree.column("", anchor="center", stretch=False)
        self.table.tree.tag_configure("unread", foreground=theme.TEXT_MAIN, font=theme.font(11, "bold"))
        self.table.tree.tag_configure("read", foreground=theme.TEXT_SUB)
        self.table.tree.bind("<<TreeviewSelect>>", self._on_select)

        # ── Detalle derecha ─────────────────────────────────────────────────
        self.detail = ctk.CTkFrame(
            body, fg_color=theme.BG_CARD, corner_radius=12,
            border_width=1, border_color=theme.BORDER,
        )
        self.detail.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        self._render_detail_empty()

    def _render_detail_empty(self) -> None:
        for w in self.detail.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.detail, text="✉",
            font=theme.font(48), text_color=theme.TEXT_MUTED,
        ).pack(pady=(80, 8))
        ctk.CTkLabel(
            self.detail, text="Selecciona un email para leerlo",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        ).pack()

    # ── Carga de emails ──────────────────────────────────────────────────────

    def _reload(self) -> None:
        self.lbl_status.configure(text="⏳  Conectando con IMAP…", text_color=theme.TEXT_MUTED)
        self.btn_reload.configure(state="disabled")
        self.table.clear()
        self._current_uid = None
        self._render_detail_empty()

        filt = {"Todos": "all", "No leídos": "unread", "Leídos": "read"}.get(
            self.cmb_filter.get(), "all"
        )

        def worker():
            try:
                emails = inbox_service.list_emails(filter=filt, limit=200)
                self.after(0, lambda: self._on_loaded(emails))
            except Exception as exc:
                logger.exception("Error cargando bandeja")
                err = str(exc)
                self.after(0, lambda: self._show_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_loaded(self, emails: list[dict]) -> None:
        self.btn_reload.configure(state="normal")
        self._emails = emails
        self._render_list()

    def _show_error(self, msg: str) -> None:
        self.btn_reload.configure(state="normal")
        friendly = _friendly_error(msg)
        self.lbl_status.configure(text=f"✗  {friendly}", text_color=theme.RED)

    def _debounced_filter(self) -> None:
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(250, self._render_list)

    def _render_list(self) -> None:
        q = self.ent_search.get().strip().lower()
        rows = self._emails
        if q:
            rows = [
                e for e in rows
                if q in str(e.get("subject", "")).lower()
                or q in str(e.get("from", "")).lower()
            ]

        self.table.clear()
        for e in rows:
            tag = "unread" if not e.get("is_read") else "read"
            self.table.add_row(
                values=[
                    "●" if not e.get("is_read") else "",
                    e.get("subject", "(sin asunto)") or "(sin asunto)",
                    e.get("from", ""),
                    _fmt_date(e.get("date", "")),
                ],
                iid=e["uid"],
                tags=(tag,),
            )

        unread = sum(1 for e in self._emails if not e.get("is_read"))
        self.lbl_count.configure(text=f"{len(rows)} mostrados · {unread} no leídos")
        if rows:
            self.lbl_status.configure(text="", text_color=theme.TEXT_MUTED)
        else:
            self.lbl_status.configure(text="Sin resultados", text_color=theme.TEXT_MUTED)

    # ── Selección + detalle ──────────────────────────────────────────────────

    def _on_select(self, _evt=None) -> None:
        uid = self.table.selected_iid()
        if uid and uid != self._current_uid:
            self._open_detail_uid(uid)

    def _open_detail(self, _item=None) -> None:
        uid = self.table.selected_iid()
        if uid:
            self._open_detail_uid(uid)

    def _open_detail_uid(self, uid: str) -> None:
        self._current_uid = uid
        for w in self.detail.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.detail, text="⏳  Cargando email…",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        ).pack(pady=80)

        def worker():
            try:
                d = inbox_service.get_email_detail(uid)
                self.after(0, lambda: self._render_detail(d))
            except Exception as exc:
                logger.exception("Error cargando detalle email")
                err = str(exc)
                self.after(0, lambda: self._render_detail_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _render_detail_error(self, msg: str) -> None:
        for w in self.detail.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.detail, text=f"✗  {msg}", font=theme.FONT_BODY, text_color=theme.RED,
            wraplength=420, justify="left",
        ).pack(padx=20, pady=80)

    def _render_detail(self, d: dict) -> None:
        for w in self.detail.winfo_children():
            w.destroy()

        # Header
        head = ctk.CTkFrame(self.detail, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(14, 4))

        ctk.CTkLabel(
            head, text=d.get("subject") or "(sin asunto)",
            font=theme.font(14, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
            justify="left", wraplength=520,
        ).pack(anchor="w")

        meta = ctk.CTkFrame(self.detail, fg_color="transparent")
        meta.pack(fill="x", padx=18, pady=(2, 8))
        self._meta_row(meta, "De:", d.get("from", ""))
        if d.get("to"):
            self._meta_row(meta, "Para:", d.get("to", ""))
        if d.get("cc"):
            self._meta_row(meta, "Cc:", d.get("cc", ""))
        self._meta_row(meta, "Fecha:", _fmt_date_long(d.get("date", "")))

        # Toolbar acciones
        actions = ctk.CTkFrame(self.detail, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(4, 8))

        # Toggle leído/no leído
        email_obj = next((e for e in self._emails if e["uid"] == d["uid"]), None)
        is_read = email_obj.get("is_read") if email_obj else True
        toggle_label = "📫 Marcar no leído" if is_read else "📬 Marcar leído"
        ctk.CTkButton(
            actions, text=toggle_label, font=theme.FONT_BUTTON,
            height=30, corner_radius=8,
            fg_color=theme.BG_INPUT, hover_color=theme.BORDER,
            text_color=theme.TEXT_MAIN,
            command=lambda uid=d["uid"], r=is_read: self._toggle_read(uid, r),
        ).pack(side="left")

        # Botón IA (deshabilitado sin key)
        ai_btn = ctk.CTkButton(
            actions, text="🤖 Análisis IA", font=theme.FONT_BUTTON,
            height=30, corner_radius=8,
            fg_color=theme.BG_INPUT, hover_color=theme.BORDER,
            text_color=theme.TEXT_MUTED, state="disabled",
            command=lambda: None,
        )
        ai_btn.pack(side="left", padx=(8, 0))
        if not ANTHROPIC_API_KEY:
            self._add_tooltip(ai_btn, "Configura ANTHROPIC_API_KEY en .env para activar.")

        # Body
        ctk.CTkLabel(
            self.detail, text="MENSAJE",
            font=theme.font(9, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", padx=18, pady=(10, 4))

        body_text = d.get("plain_body") or inbox_service.html_to_text(d.get("html_body", ""))
        if not body_text:
            body_text = "(Email sin cuerpo legible)"

        body = ctk.CTkTextbox(
            self.detail, fg_color=theme.BG_PAGE, corner_radius=8,
            border_width=1, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY, wrap="word",
        )
        body.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        body.insert("1.0", body_text)
        body.configure(state="disabled")

        # Marcar como leído automáticamente (server-side) si estaba unread
        if email_obj and not email_obj.get("is_read"):
            self._mark_locally(d["uid"], True)
            threading.Thread(
                target=lambda u=d["uid"]: _safe_call(inbox_service.mark_read, u),
                daemon=True,
            ).start()

    def _meta_row(self, parent, label: str, value: str) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(
            row, text=label, font=theme.font(10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w", width=50,
        ).pack(side="left")
        ctk.CTkLabel(
            row, text=value, font=theme.FONT_BODY,
            text_color=theme.TEXT_SUB, anchor="w",
            justify="left", wraplength=520,
        ).pack(side="left", fill="x", expand=True)

    def _toggle_read(self, uid: str, was_read: bool) -> None:
        self._mark_locally(uid, not was_read)
        target = inbox_service.mark_unread if was_read else inbox_service.mark_read

        def worker():
            try:
                target(uid)
            except Exception as exc:
                logger.exception("Error toggle read")
                self.after(0, lambda: messagebox.showerror("Error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()
        # Re-render del detalle si es el mismo email
        if self._current_uid == uid:
            d_email = next((e for e in self._emails if e["uid"] == uid), None)
            if d_email:
                # Recargar detalle para refrescar el botón
                self._open_detail_uid(uid)

    def _mark_locally(self, uid: str, is_read: bool) -> None:
        for e in self._emails:
            if e["uid"] == uid:
                e["is_read"] = is_read
                break
        # Refrescar fila en la tabla
        try:
            values = list(self.table.tree.item(uid, "values"))
            values[0] = "" if is_read else "●"
            self.table.tree.item(uid, values=values, tags=("read" if is_read else "unread",))
        except Exception:
            pass
        unread = sum(1 for e in self._emails if not e.get("is_read"))
        total_visible = len(self.table.tree.get_children())
        self.lbl_count.configure(text=f"{total_visible} mostrados · {unread} no leídos")

    # ── Tooltip simple ───────────────────────────────────────────────────────

    def _add_tooltip(self, widget, text: str) -> None:
        tip = {"win": None}

        def show(_evt=None):
            if tip["win"]:
                return
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tw = ctk.CTkToplevel(self)
            tw.wm_overrideredirect(True)
            tw.geometry(f"+{x}+{y}")
            tw.configure(fg_color=theme.BG_SIDEBAR)
            ctk.CTkLabel(
                tw, text=text, font=theme.font(10),
                text_color=theme.TEXT_MAIN, fg_color=theme.BG_SIDEBAR,
                corner_radius=6,
            ).pack(padx=8, pady=4)
            tip["win"] = tw

        def hide(_evt=None):
            if tip["win"]:
                tip["win"].destroy()
                tip["win"] = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_date(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = parsedate_to_datetime(iso) if " " in iso else None
        if dt is None:
            from datetime import datetime
            dt = datetime.fromisoformat(iso)
        return dt.strftime("%d %b · %H:%M")
    except Exception:
        return iso[:16]


def _fmt_date_long(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = parsedate_to_datetime(iso) if " " in iso else None
        if dt is None:
            from datetime import datetime
            dt = datetime.fromisoformat(iso)
        return dt.strftime("%A %d %b %Y · %H:%M")
    except Exception:
        return iso


def _friendly_error(msg: str) -> str:
    low = msg.lower()
    if "bad username or password" in low or "authentication failed" in low:
        return "Credenciales IMAP incorrectas. Edita .env y rellena IMAP_USER / IMAP_PASS."
    if "name or service not known" in low or "getaddrinfo" in low or "timed out" in low:
        return "No se pudo contactar con el servidor IMAP. Revisa IMAP_HOST en .env."
    return msg


def _safe_call(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("Llamada IMAP falló silenciosamente: %s", exc)
