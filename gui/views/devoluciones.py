"""Vista Devoluciones — lista emails IMAP parseables + ventana preview/envío."""

import logging
import threading
import tkinter as tk
from email.utils import parsedate_to_datetime

import customtkinter as ctk
from tkinter import messagebox

from core.services import transmittal
from gui import theme
from gui.widgets.table import DataTable

logger = logging.getLogger(__name__)

COLUMNS = ["Plataforma", "Asunto", "Remitente", "Fecha"]

# Estados válidos para edición manual desde el preview de devolución.
# Ordenados por frecuencia de uso real del Document Controller.
VALID_STATUSES = [
    "Aprobado", "Com. Menores", "Com. Mayores", "Comentado",
    "Rechazado", "Informativo", "Enviado", "Sin Enviar",
]


class DevolucionesView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._emails: list[dict] = []
        self._only_unread = False
        self._build_layout()
        self._reload()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 6))
        ctk.CTkLabel(
            header, text="Devoluciones", font=theme.FONT_TITLE,
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text="Correos parseables del buzón IMAP. Doble click para previsualizar y enviar.",
            font=theme.FONT_BODY, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # Toolbar
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=24, pady=(14, 8))

        self.btn_reload = ctk.CTkButton(
            toolbar, text="↻ Recargar", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.BG_CARD, hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self._reload,
        )
        self.btn_reload.pack(side="left", padx=(0, 8))

        self.var_unread = ctk.BooleanVar(value=False)
        self.chk_unread = ctk.CTkCheckBox(
            toolbar, text="Solo no leídos", variable=self.var_unread,
            font=theme.FONT_BODY, text_color=theme.TEXT_SUB,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._on_toggle_unread,
        )
        self.chk_unread.pack(side="left", padx=8)

        self.count_label = ctk.CTkLabel(
            toolbar, text="", font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        )
        self.count_label.pack(side="right")

        # Loading state
        self.status_label = ctk.CTkLabel(
            self, text="", font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        )
        self.status_label.pack(fill="x", padx=24)

        # Table
        self.table = DataTable(self, columns=COLUMNS, on_double_click=self._on_row_double)
        self.table.pack(fill="both", expand=True, padx=24, pady=(8, 24))
        self.table.set_columns_width({
            "Plataforma": 130, "Asunto": 520, "Remitente": 260, "Fecha": 140,
        })

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _on_toggle_unread(self) -> None:
        self._only_unread = bool(self.var_unread.get())
        self._reload()

    def _reload(self) -> None:
        self.status_label.configure(text="⏳  Conectando con IMAP…")
        self.btn_reload.configure(state="disabled")
        self.table.clear()

        def worker():
            try:
                if self._only_unread:
                    data = transmittal.fetch_unread_emails()
                else:
                    data = transmittal.fetch_all_emails()
                self.after(0, lambda: self._populate(data))
            except Exception as exc:
                logger.exception("Error cargando emails")
                err = str(exc)
                self.after(0, lambda: self._show_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _populate(self, emails: list[dict]) -> None:
        self._emails = emails
        self.btn_reload.configure(state="normal")
        self.status_label.configure(text="")
        self.table.clear()

        if not emails:
            self.count_label.configure(text="0 emails")
            return

        for e in emails:
            tags = ("processed",) if e.get("processed") else ()
            self.table.add_row(
                values=[
                    e.get("platform", "—"),
                    e.get("subject", "(sin asunto)"),
                    e.get("from", ""),
                    _fmt_date(e.get("date", "")),
                ],
                iid=e.get("uid"),
                tags=tags,
            )
        self.count_label.configure(text=f"{len(emails)} emails")

    def _show_error(self, msg: str) -> None:
        self.btn_reload.configure(state="normal")
        friendly = _friendly_error(msg)
        self.status_label.configure(text=f"✗  {friendly}", text_color=theme.RED)

    def _on_row_double(self, item) -> None:
        iid = item.get("text") or None
        # En treeview con iid custom, el item viene con id real:
        sel = self.table.selected_iid()
        if not sel:
            return
        PreviewWindow(self, uid=sel, on_sent=self._reload)


# ════════════════════════════════════════════════════════════════════════════
#  Preview / envío
# ════════════════════════════════════════════════════════════════════════════

class PreviewWindow(ctk.CTkToplevel):
    def __init__(self, master, uid: str, on_sent=None):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title("Preview de devolución")
        self.geometry("900x760")
        self.minsize(780, 640)
        self.transient(master)
        self.grab_set()

        self._uid = uid
        self._preview: dict | None = None
        self._on_sent = on_sent
        self._status_overrides: dict[str, str] = {}  # iid -> nuevo Estado
        self.docs_table: DataTable | None = None
        self._estado_col_id: str | None = None  # ej "#5"

        self._build_skeleton()
        self._load()

    def _build_skeleton(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(18, 6))
        self.lbl_platform = ctk.CTkLabel(
            header, text="Cargando…", font=(theme.FONT_FAMILY, 18, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
        )
        self.lbl_platform.pack(anchor="w")
        self.lbl_subject = ctk.CTkLabel(
            header, text="", font=theme.FONT_BODY, text_color=theme.TEXT_SUB,
            anchor="w", justify="left", wraplength=820,
        )
        self.lbl_subject.pack(anchor="w", pady=(2, 0))

        # Fields
        fields = ctk.CTkFrame(self, fg_color="transparent")
        fields.pack(fill="x", padx=22, pady=(12, 8))

        ctk.CTkLabel(fields, text="Para (To)", font=theme.FONT_SECTION,
                     text_color=theme.TEXT_MUTED).grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.ent_to = ctk.CTkEntry(
            fields, height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_to.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkLabel(fields, text="Copia (Cc)", font=theme.FONT_SECTION,
                     text_color=theme.TEXT_MUTED).grid(row=2, column=0, sticky="w", pady=(0, 2))
        self.ent_cc = ctk.CTkEntry(
            fields, height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_cc.grid(row=3, column=0, sticky="ew", pady=(0, 0))

        fields.grid_columnconfigure(0, weight=1)

        # Tabla documentos
        ctk.CTkLabel(self, text="Documentos detectados",
                     font=theme.FONT_SECTION, text_color=theme.TEXT_MUTED,
                     anchor="w").pack(fill="x", padx=22, pady=(14, 4))

        # Footer y status se packean PRIMERO con side="bottom" para garantizar
        # que el botón Enviar quede siempre visible aunque la tabla crezca.
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=22, pady=14)
        ctk.CTkButton(
            footer, text="Cancelar", font=theme.FONT_BUTTON,
            height=36, corner_radius=8,
            fg_color=theme.BG_CARD, hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))

        self.btn_send = ctk.CTkButton(
            footer, text="Enviar notificación  →", font=theme.FONT_BUTTON,
            height=36, corner_radius=8,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            state="disabled",
            command=self._send,
        )
        self.btn_send.pack(side="right")

        self.btn_preview = ctk.CTkButton(
            footer, text="👁  Preview email", font=theme.FONT_BUTTON,
            height=36, corner_radius=8,
            fg_color=theme.BG_INPUT, hover_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            state="disabled",
            command=self._preview_email,
        )
        self.btn_preview.pack(side="left")

        self.lbl_status = ctk.CTkLabel(
            self, text="⏳  Parseando email…", font=theme.FONT_BODY,
            text_color=theme.TEXT_MUTED, anchor="w",
        )
        self.lbl_status.pack(side="bottom", fill="x", padx=22)

        # Tabla expansible (toma el espacio restante en el medio)
        self.table_host = ctk.CTkFrame(self, fg_color="transparent")
        self.table_host.pack(side="top", fill="both", expand=True, padx=22, pady=(0, 8))

    def _load(self) -> None:
        uid = self._uid

        def worker():
            try:
                data = transmittal.preview_email(uid)
                self.after(0, lambda: self._render_preview(data))
            except Exception as exc:
                logger.exception("Error en preview")
                err = str(exc)
                self.after(0, lambda: self._render_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _render_preview(self, pv: dict) -> None:
        self._preview = pv
        self.lbl_platform.configure(text=pv.get("platform", "—"))
        self.lbl_subject.configure(text=pv.get("subject", ""))

        self.ent_to.delete(0, "end")
        self.ent_to.insert(0, ", ".join(pv.get("suggested_to") or []))
        self.ent_cc.delete(0, "end")
        self.ent_cc.insert(0, ", ".join(pv.get("suggested_cc") or []))

        docs = pv.get("documents") or []
        cols = [c for c in (pv.get("columns") or (docs[0].keys() if docs else []))
                if not str(c).startswith("_")]

        for child in self.table_host.winfo_children():
            child.destroy()

        self._status_overrides.clear()
        self.docs_table = None
        self._estado_col_id = None

        if not docs:
            ctk.CTkLabel(
                self.table_host, text="No se detectaron documentos",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            ).pack(pady=20)
        else:
            self.docs_table = DataTable(self.table_host, columns=cols)
            self.docs_table.pack(fill="both", expand=True)
            for idx, doc in enumerate(docs):
                values = [str(doc.get(c, "")) for c in cols]
                tag = _status_tag(doc.get("Estado", ""))
                self.docs_table.add_row(values=values, iid=str(idx), tags=(tag,) if tag else ())

            # Configurar tags de coloreo
            for k, color in (
                ("status_aprobado", theme.GREEN),
                ("status_rechazado", theme.RED),
                ("status_comentado", theme.AMBER),
                ("status_enviado", theme.BLUE),
            ):
                self.docs_table.tree.tag_configure(k, foreground=color)
            self.docs_table.tree.tag_configure("status_edited", background=theme.ROW_BG_EDITED)

            # Localizar el id de columna Estado (ej "#5") para el bind
            if "Estado" in cols:
                self._estado_col_id = f"#{cols.index('Estado') + 1}"
                # Subrayar visualmente la columna Estado como editable
                self.docs_table.tree.heading("Estado", text="Estado  ✎")
                self.docs_table.tree.bind("<Button-1>", self._on_doc_click)

        self.lbl_status.configure(
            text=f"✓  {len(docs)} documento(s) listos. Click en la columna Estado ✎ para editar manualmente.",
        )
        self.btn_send.configure(state="normal")
        self.btn_preview.configure(state="normal")

    # ── Editor de Estado por documento ────────────────────────────────────────

    def _on_doc_click(self, event) -> None:
        """Detecta click en la celda Estado y abre el menú de selección."""
        if not self.docs_table or not self._estado_col_id:
            return
        tree = self.docs_table.tree
        region = tree.identify_region(event.x, event.y)
        col = tree.identify_column(event.x)
        row_id = tree.identify_row(event.y)
        if region != "cell" or col != self._estado_col_id or not row_id:
            return
        self._open_estado_menu(row_id, event.x_root, event.y_root)

    def _open_estado_menu(self, row_id: str, x_root: int, y_root: int) -> None:
        """Menú nativo tk.Menu con la lista de estados válidos."""
        menu = tk.Menu(
            self, tearoff=False,
            bg=theme.BG_CARD, fg=theme.TEXT_MAIN,
            activebackground=theme.ACCENT, activeforeground="white",
            font=(theme.FONT_FAMILY, 11),
            borderwidth=1, relief="solid",
        )
        for estado in VALID_STATUSES:
            menu.add_command(
                label=f"  {estado}  ",
                command=lambda e=estado, r=row_id: self._set_estado(r, e),
            )
        menu.add_separator()
        menu.add_command(
            label="  ↺  Restaurar original  ",
            command=lambda r=row_id: self._restore_estado(r),
        )
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _set_estado(self, row_id: str, nuevo_estado: str) -> None:
        if not self.docs_table or not self._estado_col_id:
            return
        tree = self.docs_table.tree
        col_idx = int(self._estado_col_id.lstrip("#")) - 1
        values = list(tree.item(row_id, "values"))
        if col_idx >= len(values):
            return
        values[col_idx] = nuevo_estado
        tree.item(row_id, values=values)

        # Marcar como editado y aplicar tag de color por nuevo estado
        new_tag = _status_tag(nuevo_estado)
        tags = ("status_edited", new_tag) if new_tag else ("status_edited",)
        tree.item(row_id, tags=tags)

        self._status_overrides[row_id] = nuevo_estado
        self._refresh_overrides_status()

    def _restore_estado(self, row_id: str) -> None:
        if row_id not in self._status_overrides or not self._preview:
            return
        try:
            idx = int(row_id)
            docs = self._preview.get("documents") or []
            original_estado = docs[idx].get("Estado", "")
        except (ValueError, IndexError):
            return
        if not self.docs_table or not self._estado_col_id:
            return
        tree = self.docs_table.tree
        col_idx = int(self._estado_col_id.lstrip("#")) - 1
        values = list(tree.item(row_id, "values"))
        if col_idx < len(values):
            values[col_idx] = str(original_estado)
            tree.item(row_id, values=values)
        # Quitar tag de editado, restaurar tag por estado original
        orig_tag = _status_tag(original_estado)
        tree.item(row_id, tags=(orig_tag,) if orig_tag else ())
        del self._status_overrides[row_id]
        self._refresh_overrides_status()

    def _refresh_overrides_status(self) -> None:
        n = len(self._status_overrides)
        if n == 0:
            self.lbl_status.configure(
                text=f"✓  {len(self._preview.get('documents') or [])} documento(s) listos. Click en Estado ✎ para editar.",
                text_color=theme.GREEN,
            )
        else:
            self.lbl_status.configure(
                text=f"✏  {n} estado(s) modificado(s) manualmente. Se aplicarán al enviar.",
                text_color=theme.AMBER,
            )

    def _render_error(self, msg: str) -> None:
        self.lbl_platform.configure(text="Error", text_color=theme.RED)
        self.lbl_subject.configure(text=msg)
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)

    def _preview_email(self) -> None:
        """Genera el HTML que se enviaría y lo abre en el navegador."""
        if not self._preview:
            return
        self.lbl_status.configure(text="⏳  Generando preview…", text_color=theme.TEXT_MUTED)
        uid = self._uid
        overrides = dict(self._status_overrides)

        def worker():
            try:
                res = transmittal.generate_notification_html(uid, status_overrides=overrides)
                self.after(0, lambda: _open_html_preview(res["html"], "devolucion"))
                extra = f" ({len(overrides)} override(s) aplicado(s))" if overrides else ""
                self.after(0, lambda: self.lbl_status.configure(
                    text=f"✓  Preview abierto en navegador{extra}", text_color=theme.GREEN,
                ))
            except Exception as exc:
                logger.exception("Error generando preview email")
                err = str(exc)
                self.after(0, lambda: self.lbl_status.configure(
                    text=f"✗  {err}", text_color=theme.RED,
                ))

        import threading as _th
        _th.Thread(target=worker, daemon=True).start()

    def _send(self) -> None:
        if not self._preview:
            return
        to = [s.strip() for s in self.ent_to.get().split(",") if s.strip()]
        cc = [s.strip() for s in self.ent_cc.get().split(",") if s.strip()]
        if not to:
            messagebox.showwarning("Destinatarios", "Indica al menos un destinatario en 'To'.")
            return

        overrides_line = (
            f"\nEstados modificados: {len(self._status_overrides)} doc(s)"
            if self._status_overrides else ""
        )
        confirm = messagebox.askyesno(
            "Confirmar envío",
            f"¿Enviar notificación de devolución?\n\n"
            f"Para: {', '.join(to)}\n"
            f"Cc: {', '.join(cc) or '—'}\n"
            f"Docs: {len(self._preview.get('documents', []))}"
            f"{overrides_line}",
        )
        if not confirm:
            return

        self.btn_send.configure(state="disabled", text="Enviando…")
        self.lbl_status.configure(text="📤  Enviando email…", text_color=theme.TEXT_MUTED)

        uid = self._uid
        overrides = dict(self._status_overrides)

        def worker():
            try:
                res = transmittal.process_and_notify(
                    uid, to=to, cc=cc, status_overrides=overrides,
                )
                self.after(0, lambda: self._send_done(res))
            except Exception as exc:
                logger.exception("Error enviando notificación")
                err = str(exc)
                self.after(0, lambda: self._send_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _send_done(self, res: dict) -> None:
        n = res.get("documents_count", 0)
        path = res.get("saved_path") or "—"
        messagebox.showinfo(
            "Notificación enviada",
            f"✓ Email enviado con éxito\n\n"
            f"Documentos: {n}\n"
            f"Asunto: {res.get('subject', '')}\n"
            f"EML guardado en: {path}",
        )
        if self._on_sent:
            self._on_sent()
        self.destroy()

    def _send_error(self, msg: str) -> None:
        self.btn_send.configure(state="normal", text="Enviar notificación  →")
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)
        messagebox.showerror("Error de envío", msg)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _open_html_preview(html: str, kind: str) -> None:
    """Guarda el HTML en un tmpfile y lo abre en el navegador del sistema."""
    import tempfile
    import webbrowser
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=f"_{kind}_preview.html", delete=False,
    )
    tmp.write(html)
    tmp.close()
    webbrowser.open(f"file://{tmp.name}")


def _friendly_error(msg: str) -> str:
    low = msg.lower()
    if "bad username or password" in low or "authentication failed" in low:
        return "Credenciales IMAP incorrectas. Edita .env y rellena IMAP_USER / IMAP_PASS."
    if "name or service not known" in low or "getaddrinfo" in low or "timed out" in low:
        return "No se pudo contactar con el servidor IMAP. Revisa IMAP_HOST en .env."
    return msg


def _fmt_date(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = parsedate_to_datetime(iso) if " " in iso or "+" in iso else None
        if dt is None:
            from datetime import datetime
            dt = datetime.fromisoformat(iso)
        return dt.strftime("%d %b · %H:%M")
    except Exception:
        return iso[:16]


def _status_tag(estado: str) -> str:
    s = (estado or "").lower().strip().replace(".", "").replace(" ", "_")
    if "aprobado" in s: return "status_aprobado"
    if "rechazado" in s: return "status_rechazado"
    if "comentado" in s or "menores" in s or "mayores" in s: return "status_comentado"
    if "enviado" in s: return "status_enviado"
    return ""
