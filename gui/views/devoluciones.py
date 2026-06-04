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

# Preview de devolución: columnas a nivel de DOCUMENTO (varían por fila) que se
# muestran en la tabla. El resto (pedido, cliente, material, PO, transmittal…)
# son iguales en todas las filas y se muestran en la cabecera resumen.
DOC_TABLE_COLUMNS = [
    "Doc. Cliente", "Doc. EIPSA", "Título",
    "Tipo de documento", "Rev.", "Estado", "Crítico",
]
# Cabecera abreviada para algunas columnas (id = clave de datos, text = visible)
DOC_HEADER_SHORT = {
    "Tipo de documento": "Tipo",
    "Rev.": "Rev",
    "Crítico": "Crít.",
}
# Campos a nivel de PEDIDO que van a la cabecera resumen: (clave, etiqueta)
META_FIELDS = [
    ("Nº Pedido", "Pedido"),
    ("Cliente", "Cliente"),
    ("Material", "Material"),
    ("PO", "PO"),
    ("Responsable", "Resp."),
    ("Nº Transmittal", "Transmittal"),
    ("Fecha", "Recibido"),
]

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
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(
            header, text="Devoluciones", font=theme.FONT_TITLE,
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Correos parseables del buzón IMAP · doble click para previsualizar y enviar",
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(theme.SPACE_1, 0))

        # Toolbar
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_4, theme.SPACE_2))

        self.btn_reload = ctk.CTkButton(
            toolbar, text="↻  Recargar", font=theme.FONT_SMALL_BOLD,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self._reload,
        )
        self.btn_reload.pack(side="left", padx=(0, theme.SPACE_2))

        # Botón devolución manual (acción primary)
        ctk.CTkButton(
            toolbar, text="+  Devolución manual", font=theme.FONT_SMALL_BOLD,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            text_color="#FFFFFF",
            command=lambda: ManualDevolucionWindow(self),
        ).pack(side="left", padx=(0, theme.SPACE_2))

        self.var_unread = ctk.BooleanVar(value=False)
        self.chk_unread = ctk.CTkCheckBox(
            toolbar, text="Solo no leídos", variable=self.var_unread,
            font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._on_toggle_unread,
        )
        self.chk_unread.pack(side="left", padx=theme.SPACE_2)

        self.count_label = ctk.CTkLabel(
            toolbar, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self.count_label.pack(side="right")

        # Loading state
        self.status_label = ctk.CTkLabel(
            self, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
        )
        self.status_label.pack(fill="x", padx=theme.SPACE_6)

        # Table
        self.table = DataTable(self, columns=COLUMNS, on_double_click=self._on_row_double)
        self.table.pack(fill="both", expand=True, padx=theme.SPACE_6, pady=(theme.SPACE_2, theme.SPACE_6))
        self.table.set_columns_width({
            "Plataforma": 130, "Asunto": 520, "Remitente": 260, "Fecha": 150,
        })
        self.table.set_columns_anchor({
            "Plataforma": "center", "Asunto": "w",
            "Remitente": "w", "Fecha": "center",
        })
        self.table.set_context_menu(self._ctx_menu)

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

    # ── Menú contextual ────────────────────────────────────────────────────

    def _ctx_menu(self, iid: str, col_idx: int):
        email = next((e for e in self._emails if e.get("uid") == iid), None)
        if not email:
            return None
        return [
            ("✉  Procesar / Preview",
             lambda: PreviewWindow(self, uid=iid, on_sent=self._reload)),
            ("-", None),
            ("Copiar asunto",
             lambda: self.table.copy_to_clipboard(email.get("subject", ""))),
            ("Copiar remitente",
             lambda: self.table.copy_to_clipboard(email.get("from", ""))),
        ]


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
        self._fit_after_id = None

        self._build_skeleton()
        self._load()

    def _debounce_fit(self) -> None:
        """Reajusta las columnas al redimensionar la ventana (con debounce)."""
        if self.docs_table is None:
            return
        if self._fit_after_id is not None:
            try:
                self.after_cancel(self._fit_after_id)
            except Exception:
                pass
        self._fit_after_id = self.after(150, self._fit_docs_table)

    def _build_skeleton(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(18, 6))
        self.lbl_platform = ctk.CTkLabel(
            header, text="Cargando…", font=theme.font(18, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
        )
        self.lbl_platform.pack(anchor="w")
        self.lbl_subject = ctk.CTkLabel(
            header, text="", font=theme.FONT_BODY, text_color=theme.TEXT_SUB,
            anchor="w", justify="left", wraplength=820,
        )
        self.lbl_subject.pack(anchor="w", pady=(2, 0))

        # Cabecera resumen del pedido (chips con datos que se repiten en todas
        # las filas). Se rellena en _render_preview.
        self.meta_host = ctk.CTkFrame(
            self, fg_color=theme.BG_CARD, corner_radius=10,
            border_width=1, border_color=theme.BORDER,
        )
        self.meta_host.pack(fill="x", padx=22, pady=(10, 2))

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
        all_cols = [c for c in (pv.get("columns") or (docs[0].keys() if docs else []))
                    if not str(c).startswith("_")]

        # Cabecera resumen del pedido (datos que se repiten en cada fila)
        self._render_meta(docs[0] if docs else {})

        # Columnas de la tabla: solo las de DOCUMENTO presentes en los datos
        cols = [c for c in DOC_TABLE_COLUMNS if c in all_cols]
        if not cols:  # fallback defensivo
            cols = all_cols

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
            # Alineación: texto a la izquierda, Rev/Estado/Crítico centrados
            self.docs_table.set_columns_anchor({
                "Rev.": "center", "Estado": "center", "Crítico": "center",
                "Tipo de documento": "center",
            })
            for idx, doc in enumerate(docs):
                values = [str(doc.get(c, "")) for c in cols]
                tag = _status_tag(doc.get("Estado", ""))
                self.docs_table.add_row(values=values, iid=str(idx), tags=(tag,) if tag else ())

            # Cabeceras abreviadas
            for col in cols:
                short = DOC_HEADER_SHORT.get(col)
                if short:
                    self.docs_table.tree.heading(col, text=short)

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

            # Ajustar columnas para que la tabla entre completa (sin scroll
            # lateral). Se llama tras el layout para medir el ancho real.
            self.after(80, self._fit_docs_table)
            # Reajustar si se redimensiona la ventana
            self.bind("<Configure>", lambda _e: self._debounce_fit())

        self.lbl_status.configure(
            text=f"✓  {len(docs)} documento(s) listos. Click en la columna Estado ✎ para editar manualmente.",
        )
        self.btn_send.configure(state="normal")
        self.btn_preview.configure(state="normal")

    def _fit_docs_table(self) -> None:
        if self.docs_table is not None:
            self.docs_table.autofit_columns(max_per={
                "Título": 360,
                "Doc. Cliente": 200, "Doc. EIPSA": 180,
            })

    def _render_meta(self, doc: dict) -> None:
        """Rellena la cabecera resumen con los datos del pedido (chips)."""
        for child in self.meta_host.winfo_children():
            child.destroy()
        if not doc:
            self.meta_host.pack_forget()
            return
        self.meta_host.pack(fill="x", padx=22, pady=(10, 2))

        grid = ctk.CTkFrame(self.meta_host, fg_color="transparent")
        grid.pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_3)

        # Reparte los campos no vacíos en filas de 4 columnas
        items = [(lbl, str(doc.get(key, "") or "—").strip() or "—")
                 for key, lbl in META_FIELDS]
        ncols = 4
        for c in range(ncols):
            grid.grid_columnconfigure(c, weight=1, uniform="meta")

        for i, (lbl, val) in enumerate(items):
            r, c = divmod(i, ncols)
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=r, column=c, sticky="w", padx=(0, theme.SPACE_4),
                      pady=(0, theme.SPACE_1))
            ctk.CTkLabel(
                cell, text=lbl.upper(), font=theme.FONT_LABEL,
                text_color=theme.TEXT_MUTED, anchor="w",
            ).pack(anchor="w")
            ctk.CTkLabel(
                cell, text=val, font=theme.FONT_BODY_BOLD,
                text_color=theme.TEXT_MAIN, anchor="w",
            ).pack(anchor="w")

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
            font=theme.font(11),
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


# ════════════════════════════════════════════════════════════════════════════
#  Devolución manual (sin email IMAP de origen)
# ════════════════════════════════════════════════════════════════════════════

class ManualDevolucionWindow(ctk.CTkToplevel):
    """Ventana para crear una devolución 100% manual.

    Replica la plantilla del email automático pero con todos los campos editables
    a mano. Útil cuando recibes la información por canales no parseables (Teams,
    WhatsApp, llamada, etc.) y aún quieres enviar la notificación con el mismo
    diseño corporativo.
    """

    def __init__(self, master, on_sent=None):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title("Devolución manual")
        self.geometry("1000x820")
        self.minsize(820, 680)
        self.transient(master)
        self.grab_set()

        self._on_sent = on_sent
        self._doc_rows: list[dict] = []  # cada item = {frame, ent_doc, ent_titulo, ent_rev, cmb_estado}

        self._build_layout()
        # Una fila vacía inicial para que el usuario empiece a escribir
        self._add_doc_row()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_5, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(
            header, text="Devolución manual",
            font=theme.FONT_TITLE, text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Rellena los campos a mano · usa la misma plantilla que las automáticas",
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(theme.SPACE_1, 0))

        # Footer (packeado primero con side=bottom)
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=theme.SPACE_5, pady=theme.SPACE_4)
        ctk.CTkButton(
            footer, text="Cancelar", font=theme.FONT_BUTTON,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self.destroy,
        ).pack(side="right", padx=(theme.SPACE_2, 0))

        self.btn_send = ctk.CTkButton(
            footer, text="Enviar  →", font=theme.FONT_BUTTON,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self._send,
        )
        self.btn_send.pack(side="right")

        self.btn_preview = ctk.CTkButton(
            footer, text="👁  Preview email", font=theme.FONT_BUTTON,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self._preview,
        )
        self.btn_preview.pack(side="left")

        # Status line encima del footer
        self.lbl_status = ctk.CTkLabel(
            self, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
        )
        self.lbl_status.pack(side="bottom", fill="x", padx=theme.SPACE_5,
                              pady=(0, theme.SPACE_1))

        # Scroll wrapper para que el contenido crezca sin romper el footer
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(side="top", fill="both", expand=True,
                     padx=theme.SPACE_5, pady=(theme.SPACE_3, theme.SPACE_2))

        # ── Sección: Información del pedido ──────────────────────────────
        self._section_label(scroll, "INFORMACIÓN DEL PEDIDO")

        info_grid = ctk.CTkFrame(scroll, fg_color="transparent")
        info_grid.pack(fill="x", pady=(0, theme.SPACE_3))
        for col in range(3):
            info_grid.grid_columnconfigure(col, weight=1, uniform="info")

        self.ent_pedido   = self._field(info_grid, 0, 0, "Nº Pedido *", "P-26/029")
        self.ent_po       = self._field(info_grid, 0, 1, "PO",          "1057111030")
        self.ent_supp     = self._field(info_grid, 0, 2, "Supp.",       "S00")
        self.ent_cliente  = self._field(info_grid, 1, 0, "Cliente *",   "")
        self.ent_material = self._field(info_grid, 1, 1, "Material",    "")
        self.ent_fecha    = self._field(info_grid, 1, 2, "Fecha (DD-MM-YYYY)", _today_dmy())

        # ── Sección: Documentos ──────────────────────────────────────────
        docs_head = ctk.CTkFrame(scroll, fg_color="transparent")
        docs_head.pack(fill="x", pady=(theme.SPACE_3, theme.SPACE_1))
        ctk.CTkLabel(
            docs_head, text="DOCUMENTOS DEVUELTOS",
            font=theme.FONT_LABEL, text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(side="left")
        ctk.CTkButton(
            docs_head, text="+ Añadir fila", font=theme.FONT_SMALL_BOLD,
            height=theme.HEIGHT_BUTTON_SM, corner_radius=theme.RADIUS_SM, width=110,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.ACCENT, border_width=1, border_color=theme.BORDER,
            command=self._add_doc_row,
        ).pack(side="right")

        # Cabecera de la tabla (para alinear con los campos)
        head_row = ctk.CTkFrame(scroll, fg_color="transparent")
        head_row.pack(fill="x", pady=(theme.SPACE_1, 0))
        self._docs_header(head_row)

        # Container donde se acumulan las filas
        self.docs_container = ctk.CTkFrame(scroll, fg_color="transparent")
        self.docs_container.pack(fill="x", pady=(theme.SPACE_1, theme.SPACE_4))

        # ── Sección: Destinatarios ────────────────────────────────────────
        self._section_label(scroll, "DESTINATARIOS")

        addr = ctk.CTkFrame(scroll, fg_color="transparent")
        addr.pack(fill="x", pady=(0, theme.SPACE_4))

        ctk.CTkLabel(addr, text="Para (To) *", font=theme.FONT_TINY_BOLD,
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        self.ent_to = ctk.CTkEntry(
            addr, placeholder_text="email1@cliente.com, email2@cliente.com",
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_to.pack(fill="x", pady=(theme.SPACE_1, theme.SPACE_2))

        ctk.CTkLabel(addr, text="Copia (Cc)", font=theme.FONT_TINY_BOLD,
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        self.ent_cc = ctk.CTkEntry(
            addr, placeholder_text="opcional",
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_cc.pack(fill="x", pady=(theme.SPACE_1, 0))

    def _section_label(self, parent, text: str) -> None:
        ctk.CTkLabel(
            parent, text=text, font=theme.FONT_LABEL,
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", pady=(0, theme.SPACE_2))

    def _field(self, grid, row: int, col: int, label: str, placeholder: str) -> ctk.CTkEntry:
        box = ctk.CTkFrame(grid, fg_color="transparent")
        box.grid(row=row, column=col, sticky="ew",
                  padx=(0 if col == 0 else theme.SPACE_2, 0),
                  pady=(0, theme.SPACE_2))
        ctk.CTkLabel(
            box, text=label, font=theme.FONT_TINY_BOLD,
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w")
        ent = ctk.CTkEntry(
            box, placeholder_text=placeholder,
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        ent.pack(fill="x", pady=(theme.SPACE_1, 0))
        return ent

    def _docs_header(self, parent) -> None:
        """Cabecera con los nombres de columna de la tabla de docs."""
        cols = [
            ("Doc. Cliente", 240),
            ("Título",       380),
            ("Rev.",         60),
            ("Estado",       150),
        ]
        for i, (name, w) in enumerate(cols):
            ctk.CTkLabel(
                parent, text=name.upper(), font=theme.FONT_LABEL,
                text_color=theme.TEXT_MUTED, anchor="w", width=w,
            ).pack(side="left", padx=(0 if i == 0 else theme.SPACE_1, 0))
        # Espacio para el botón delete
        ctk.CTkLabel(parent, text="", width=32).pack(side="left")

    # ── Filas de documento ───────────────────────────────────────────────────

    def _add_doc_row(self, prefill: dict | None = None) -> None:
        prefill = prefill or {}
        row = ctk.CTkFrame(self.docs_container, fg_color="transparent")
        row.pack(fill="x", pady=(0, theme.SPACE_1))

        ent_doc = self._row_entry(row, prefill.get("Doc. Cliente", ""), width=240)
        ent_titulo = self._row_entry(row, prefill.get("Título", ""), width=380)
        ent_rev = self._row_entry(row, prefill.get("Rev.", ""), width=60)

        cmb_estado = ctk.CTkOptionMenu(
            row, values=VALID_STATUSES, width=150,
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, button_color=theme.BG_INPUT,
            button_hover_color=theme.BG_CARD, text_color=theme.TEXT_MAIN,
            font=theme.FONT_BODY, dropdown_font=theme.FONT_BODY,
        )
        cmb_estado.set(prefill.get("Estado") or "Com. Menores")
        cmb_estado.pack(side="left", padx=(theme.SPACE_1, 0))

        # Botón delete (se construye con el item ya en la lista)
        item: dict = {
            "frame": row,
            "ent_doc": ent_doc,
            "ent_titulo": ent_titulo,
            "ent_rev": ent_rev,
            "cmb_estado": cmb_estado,
        }
        btn_del = ctk.CTkButton(
            row, text="🗑", width=32,
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_SM,
            fg_color="transparent", hover_color=theme.DELETE_HOVER,
            text_color=theme.TEXT_MUTED, font=theme.FONT_BUTTON,
            command=lambda it=item: self._remove_doc_row(it),
        )
        btn_del.pack(side="left", padx=(theme.SPACE_1, 0))

        self._doc_rows.append(item)

    def _row_entry(self, parent, value: str, width: int) -> ctk.CTkEntry:
        ent = ctk.CTkEntry(
            parent, width=width,
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        if value:
            ent.insert(0, value)
        ent.pack(side="left", padx=(0, 0))
        return ent

    def _remove_doc_row(self, item: dict) -> None:
        if len(self._doc_rows) <= 1:
            # No permitir quedarse sin filas — al menos limpiar
            item["ent_doc"].delete(0, "end")
            item["ent_titulo"].delete(0, "end")
            item["ent_rev"].delete(0, "end")
            return
        try:
            self._doc_rows.remove(item)
            item["frame"].destroy()
        except (ValueError, Exception):
            pass

    # ── Recogida de datos ────────────────────────────────────────────────────

    def _collect_info_dict(self) -> dict:
        return {
            "Nº Pedido": self.ent_pedido.get().strip(),
            "Cliente":   self.ent_cliente.get().strip(),
            "Material":  self.ent_material.get().strip(),
            "Supp.":     self.ent_supp.get().strip() or "S00",
            "PO":        self.ent_po.get().strip(),
            "Fecha":     self.ent_fecha.get().strip(),
        }

    def _collect_docs(self) -> list[dict]:
        docs = []
        fecha = self.ent_fecha.get().strip()
        for item in self._doc_rows:
            titulo = item["ent_titulo"].get().strip()
            doc_cli = item["ent_doc"].get().strip()
            rev = item["ent_rev"].get().strip()
            estado = item["cmb_estado"].get()
            # Saltar filas completamente vacías
            if not titulo and not doc_cli:
                continue
            docs.append({
                "Doc. Cliente": doc_cli,
                "Título":       titulo,
                "Rev.":         rev,
                "Estado":       estado,
                "Fecha":        fecha,
            })
        return docs

    def _validate(self) -> tuple[bool, str]:
        info = self._collect_info_dict()
        if not info["Nº Pedido"]:
            return False, "El Nº Pedido es obligatorio."
        if not info["Cliente"]:
            return False, "El Cliente es obligatorio."
        docs = self._collect_docs()
        if not docs:
            return False, "Añade al menos un documento (con Título o Doc. Cliente)."
        for i, d in enumerate(docs, 1):
            if not d["Título"] and not d["Doc. Cliente"]:
                return False, f"Fila {i}: indica Título o Doc. Cliente."
        return True, ""

    # ── Acciones ─────────────────────────────────────────────────────────────

    def _preview(self) -> None:
        ok, err = self._validate()
        if not ok:
            messagebox.showwarning("Faltan datos", err, parent=self)
            return
        info = self._collect_info_dict()
        docs = self._collect_docs()
        self.lbl_status.configure(text="⏳  Generando preview…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                res = transmittal.generate_manual_notification_html(info, docs)
                self.after(0, lambda: _open_html_preview(res["html"], "devolucion_manual"))
                self.after(0, lambda: self.lbl_status.configure(
                    text=f"✓  Preview abierto en navegador ({res['documents_count']} docs)",
                    text_color=theme.GREEN,
                ))
            except Exception as exc:
                logger.exception("Error generando preview manual")
                err = str(exc)
                self.after(0, lambda: self.lbl_status.configure(
                    text=f"✗  {err}", text_color=theme.RED,
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _send(self) -> None:
        ok, err = self._validate()
        if not ok:
            messagebox.showwarning("Faltan datos", err, parent=self)
            return

        to = [s.strip() for s in self.ent_to.get().split(",") if s.strip()]
        cc = [s.strip() for s in self.ent_cc.get().split(",") if s.strip()]
        if not to:
            messagebox.showwarning("Destinatarios", "Indica al menos un destinatario en 'To'.",
                                    parent=self)
            return

        info = self._collect_info_dict()
        docs = self._collect_docs()

        confirm = messagebox.askyesno(
            "Confirmar envío",
            f"¿Enviar devolución manual?\n\n"
            f"Pedido: {info['Nº Pedido']}\n"
            f"Cliente: {info['Cliente']}\n"
            f"Documentos: {len(docs)}\n"
            f"To: {', '.join(to)}\n"
            f"Cc: {', '.join(cc) or '—'}",
            parent=self,
        )
        if not confirm:
            return

        self.btn_send.configure(state="disabled", text="Enviando…")
        self.btn_preview.configure(state="disabled")
        self.lbl_status.configure(text="📤  Enviando email…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                res = transmittal.send_manual_notification(info, docs, to, cc)
                self.after(0, lambda: self._send_done(res))
            except Exception as exc:
                logger.exception("Error enviando devolución manual")
                err = str(exc)
                self.after(0, lambda: self._send_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _send_done(self, res: dict) -> None:
        n = res.get("documents_count", 0)
        path = res.get("saved_path") or "—"
        messagebox.showinfo(
            "Devolución enviada",
            f"✓ Email enviado con éxito\n\n"
            f"Documentos: {n}\n"
            f"Asunto: {res.get('subject', '')}\n"
            f"EML guardado en: {path}",
            parent=self,
        )
        if self._on_sent:
            self._on_sent()
        self.destroy()

    def _send_error(self, msg: str) -> None:
        self.btn_send.configure(state="normal", text="Enviar  →")
        self.btn_preview.configure(state="normal")
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)
        messagebox.showerror("Error de envío", msg, parent=self)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _today_dmy() -> str:
    """Hoy en formato DD-MM-YYYY como placeholder práctico."""
    from datetime import datetime as _dt
    return _dt.now().strftime("%d-%m-%Y")


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
