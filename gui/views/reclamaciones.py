"""Vista Reclamaciones — pedidos con docs >= 15 días sin devolver."""

import logging
import os
import threading

import customtkinter as ctk
from tkinter import messagebox

from core.services import claims as claims_service
from gui import cell_format
from gui import theme
from gui.widgets import ui
from gui.widgets.table import DataTable

logger = logging.getLogger(__name__)

COLUMNS = [
    "Pedido", "Cliente", "Docs", "Días", "Urgencia",
    "Nivel propuesto", "Último envío", "Reclamaciones",
]

URGENCY_LABEL = {"low": "BAJA", "medium": "MEDIA", "high": "ALTA"}
URGENCY_COLOR = {"low": theme.BLUE, "medium": theme.AMBER, "high": theme.RED}
LEVEL_LABEL = {1: "1 · Recordatorio", 2: "2 · Formal", 3: "3 · Urgente"}


class ReclamacionesView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._pedidos: list[dict] = []
        self._build_layout()
        self._reload()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(
            header, text="Reclamaciones", font=theme.FONT_TITLE,
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        self.lbl_header_sub = ctk.CTkLabel(
            header,
            text="Pedidos con documentos enviados hace ≥ 15 días sin respuesta del cliente",
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        )
        self.lbl_header_sub.pack(anchor="w", pady=(theme.SPACE_1, 0))

        # Toolbar
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_3, theme.SPACE_2))

        # Secondary buttons (Recargar / Preview / Enviar todas)
        _SECONDARY = dict(
            font=theme.FONT_SMALL_BOLD,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
        )

        # Filtro: días mínimos desde envío
        ctk.CTkLabel(
            toolbar, text="Días ≥", font=theme.FONT_SMALL,
            text_color=theme.TEXT_SUB,
        ).pack(side="left", padx=(0, theme.SPACE_1))

        self._min_days = claims_service.DEFAULT_MIN_DAYS  # 15 por defecto
        self.var_min_days = ctk.StringVar(value=str(self._min_days))
        self.entry_min_days = ctk.CTkEntry(
            toolbar, textvariable=self.var_min_days, width=56,
            height=theme.HEIGHT_BUTTON, font=theme.FONT_SMALL_BOLD,
            fg_color=theme.BG_INPUT, text_color=theme.TEXT_MAIN,
            border_color=theme.BORDER, border_width=1,
            corner_radius=theme.RADIUS_MD, justify="center",
        )
        self.entry_min_days.pack(side="left", padx=(0, theme.SPACE_1))
        self.entry_min_days.bind("<Return>", lambda _e: self._reload())
        self.entry_min_days.bind("<FocusOut>", lambda _e: self._reload())

        ctk.CTkButton(
            toolbar, text="Todos", width=60, **_SECONDARY,
            command=self._show_all,
        ).pack(side="left", padx=(0, theme.SPACE_2))

        self.btn_reload = ctk.CTkButton(
            toolbar, text="↻  Recargar", **_SECONDARY, command=self._reload,
        )
        self.btn_reload.pack(side="left")

        self.btn_preview = ctk.CTkButton(
            toolbar, text="👁  Preview", **_SECONDARY,
            state="disabled", command=self._open_preview,
        )
        self.btn_preview.pack(side="left", padx=(theme.SPACE_2, 0))

        self.btn_send_selected = ctk.CTkButton(
            toolbar, text="Enviar seleccionadas", font=theme.FONT_SMALL_BOLD,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            text_color="#FFFFFF",
            state="disabled", command=self._send_selected,
        )
        self.btn_send_selected.pack(side="left", padx=(theme.SPACE_2, 0))

        self.btn_send_all = ctk.CTkButton(
            toolbar, text="Enviar todas", **_SECONDARY,
            state="disabled", command=self._send_all,
        )
        self.btn_send_all.pack(side="left", padx=(theme.SPACE_2, 0))

        ctk.CTkButton(
            toolbar, text="📒  Comm. Matrix", **_SECONDARY,
            command=self._open_matrix,
        ).pack(side="left", padx=(theme.SPACE_2, 0))

        self.lbl_count = ctk.CTkLabel(
            toolbar, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self.lbl_count.pack(side="right")

        # Status line
        self.lbl_status = ctk.CTkLabel(
            self, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
        )
        self.lbl_status.pack(fill="x", padx=theme.SPACE_6)

        # Tabla con selección múltiple
        self.table = DataTable(
            self, columns=COLUMNS,
            on_double_click=self._on_row_double,
            selectmode="extended",
        )
        self.table.pack(fill="both", expand=True, padx=theme.SPACE_6, pady=(theme.SPACE_2, theme.SPACE_6))
        self.table.set_columns_width({
            "Pedido": 120, "Cliente": 240, "Docs": 70, "Días": 115,
            "Urgencia": 110, "Nivel propuesto": 150, "Último envío": 140, "Reclamaciones": 120,
        })
        # Texto a la izquierda, números/badges/fechas centrados
        self.table.set_columns_anchor({
            "Pedido": "w", "Cliente": "w",
            "Docs": "center", "Días": "center", "Urgencia": "center",
            "Nivel propuesto": "center", "Último envío": "center",
            "Reclamaciones": "center",
        })

        # Tags color para urgency
        self.table.tree.tag_configure("urg_low", foreground=theme.BLUE)
        self.table.tree.tag_configure("urg_medium", foreground=theme.AMBER)
        self.table.tree.tag_configure("urg_high", foreground=theme.RED)

        self.table.set_context_menu(self._ctx_menu)

        # Bind selection → habilitar botones
        self.table.tree.bind("<<TreeviewSelect>>", self._on_select_change)

    # ── Datos ─────────────────────────────────────────────────────────────────

    def _read_min_days(self) -> int:
        """Lee el entry y normaliza a int >= 0; en error vuelve al default."""
        raw = (self.var_min_days.get() or "").strip()
        try:
            n = int(raw)
            return max(0, n)
        except ValueError:
            self.var_min_days.set(str(claims_service.DEFAULT_MIN_DAYS))
            return claims_service.DEFAULT_MIN_DAYS

    def _show_all(self) -> None:
        """Atajo: pone 0 (todos los enviados pendientes) y recarga."""
        self.var_min_days.set("0")
        self._reload()

    def _reload(self) -> None:
        self._min_days = self._read_min_days()
        # Actualiza el subtítulo según el filtro activo
        if self._min_days <= 0:
            sub = "Todos los documentos enviados pendientes de devolución"
        else:
            sub = (
                f"Pedidos con documentos enviados hace ≥ {self._min_days} días "
                "sin respuesta del cliente"
            )
        self.lbl_header_sub.configure(text=sub)

        self.lbl_status.configure(text="⏳  Calculando pedidos reclamables…", text_color=theme.TEXT_MUTED)
        self.btn_reload.configure(state="disabled")
        self.table.clear()

        min_days = self._min_days

        def worker():
            try:
                rows = claims_service.get_claimable_pedidos(min_days=min_days)
                self.after(0, lambda: self._on_loaded(rows))
            except Exception as exc:
                logger.exception("Error cargando reclamaciones")
                err = str(exc)
                self.after(0, lambda: self._show_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_loaded(self, rows: list[dict]) -> None:
        self.btn_reload.configure(state="normal")
        self._pedidos = rows
        self.table.clear()
        self.btn_send_all.configure(state="normal" if rows else "disabled")
        self._on_select_change()  # actualiza estado de los demás botones

        if not rows:
            self.lbl_status.configure(text="✓  Sin pedidos pendientes de reclamación", text_color=theme.GREEN)
            self.lbl_count.configure(text="0 pedidos")
            return

        for p in rows:
            level = claims_service.get_escalation_level(p)
            urgency = p.get("urgency", "low")
            tag = f"urg_{urgency}"
            self.table.add_row(
                values=[
                    p.get("pedido", ""),
                    p.get("cliente", "")[:60],
                    p.get("docs_count", 0),
                    cell_format.urgency_bar(p.get("max_dias", 0)),
                    cell_format.urgency_with_icon(
                        URGENCY_LABEL.get(urgency, "—"), urgency
                    ),
                    LEVEL_LABEL.get(level, ""),
                    _fmt_dt(p.get("last_claimed")),
                    p.get("claim_count", 0),
                ],
                iid=p["pedido"],
                tags=(tag,),
            )

        self.lbl_count.configure(text=f"{len(rows)} pedidos")
        self.lbl_status.configure(
            text=f"✓  {len(rows)} pedidos. Doble-click en una fila para previsualizar y enviar.",
            text_color=theme.TEXT_MUTED,
        )

    def _show_error(self, msg: str) -> None:
        self.btn_reload.configure(state="normal")
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)

    def _on_row_double(self, item) -> None:
        self._open_preview()

    # ── Menú contextual ────────────────────────────────────────────────────

    def _ctx_menu(self, iid: str, col_idx: int):
        pedido = iid  # el iid de la fila ES el código de pedido
        return [
            ("✉  Previsualizar y enviar", self._open_preview),
            ("-", None),
            ("Copiar pedido", lambda: self.table.copy_to_clipboard(pedido)),
            ("Copiar fila",
             lambda: self.table.copy_to_clipboard(
                 "\t".join(str(v) for v in self.table.row_values(iid)))),
            ("-", None),
            ("📁  Abrir carpeta del pedido",
             lambda: self._open_pedido_folder(pedido)),
        ]

    def _open_pedido_folder(self, pedido: str) -> None:
        from core.services import apertura
        try:
            folder_id, _ = apertura.parse_pedido(pedido)
        except ValueError:
            messagebox.showinfo("Carpeta", f"Pedido no reconocido: {pedido}", parent=self)
            return
        m = apertura._PEDIDO_FOLDER_RE.match(folder_id)
        from datetime import datetime
        año = 2000 + int(m.group(1)) if m else datetime.now().year
        pdir = apertura.find_existing_pedido_dir(folder_id, año)
        if pdir and pdir.exists():
            try:
                os.startfile(str(pdir))  # type: ignore[attr-defined]
            except Exception as exc:
                messagebox.showerror("Carpeta", f"No se pudo abrir:\n{exc}", parent=self)
        else:
            messagebox.showinfo(
                "Carpeta", f"No se encontró la carpeta del pedido {folder_id}.",
                parent=self,
            )

    def _open_matrix(self) -> None:
        CommMatrixWindow(self)

    def _on_select_change(self, _evt=None) -> None:
        n = len(self.table.selected_iids())
        self.btn_preview.configure(state="normal" if n == 1 else "disabled")
        self.btn_send_selected.configure(
            state="normal" if n >= 1 else "disabled",
            text=f"Enviar seleccionada{'s' if n != 1 else ''} ({n})" if n else "Enviar seleccionadas",
        )

    def _open_preview(self) -> None:
        sel = self.table.selected_iids()
        if len(sel) != 1:
            return
        pedido = sel[0]
        data = next((p for p in self._pedidos if p["pedido"] == pedido), None)
        if not data:
            return
        ReclamacionPreview(
            self, pedido_data=data, on_sent=self._reload,
            min_days=self._min_days,
        )

    def _can_send(self) -> bool:
        from core import session
        if not session.can_manage("reclamaciones"):
            ui.toast(self, "Solo lectura", "No tienes permiso para enviar reclamaciones.", kind="warn")
            return False
        return True

    def _send_selected(self) -> None:
        sel = self.table.selected_iids()
        if not sel or not self._can_send():
            return
        self._send_bulk_confirm(sel, "seleccionada(s)")

    def _send_all(self) -> None:
        if not self._pedidos or not self._can_send():
            return
        all_ids = [p["pedido"] for p in self._pedidos]
        self._send_bulk_confirm(all_ids, "TODAS")

    def _send_bulk_confirm(self, pedidos: list[str], label: str) -> None:
        # Muestra preview agregado con niveles auto-detectados
        lookup = {p["pedido"]: p for p in self._pedidos}
        lines = []
        for ped in pedidos:
            data = lookup.get(ped)
            if not data:
                continue
            lvl = claims_service.get_escalation_level(data)
            lines.append(f"  • {ped}  →  L{lvl} ({ESCALATION_LEVEL_NAMES[lvl]})  ·  {data['docs_count']} docs  ·  {data['max_dias']}d")

        body = (
            f"Vas a enviar reclamaciones {label}:\n\n"
            f"{chr(10).join(lines)}\n\n"
            f"Total: {len(pedidos)} pedido(s).\n"
            f"Nivel y destinatarios se calculan automáticamente.\n\n"
            f"¿Confirmar envío?"
        )
        if not messagebox.askyesno(f"Enviar {label}", body):
            return

        self._set_buttons_busy(True)
        self.lbl_status.configure(text=f"📤  Enviando {len(pedidos)} reclamación(es)…", text_color=theme.TEXT_MUTED)

        min_days = self._min_days

        def worker():
            try:
                res = claims_service.send_bulk(pedidos, min_days=min_days)
                self.after(0, lambda: self._bulk_done(res))
            except Exception as exc:
                logger.exception("Error en send_bulk")
                err = str(exc)
                self.after(0, lambda: self._bulk_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _set_buttons_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for b in (self.btn_reload, self.btn_preview, self.btn_send_selected, self.btn_send_all):
            b.configure(state=state)

    def _bulk_done(self, res: dict) -> None:
        sent = res.get("sent", [])
        errors = res.get("errors", [])
        sent_lines = [f"  ✓ {s['pedido']}  ·  L{s['level']}  ·  {s['docs_count']} docs" for s in sent]
        err_lines = [f"  ✗ {e['pedido']}: {e['error']}" for e in errors]

        if errors:
            messagebox.showwarning(
                "Envío parcial",
                f"Enviadas: {len(sent)} / {res['total']}\n\n"
                f"{chr(10).join(sent_lines) or '(ninguna)'}\n\n"
                f"Errores:\n{chr(10).join(err_lines)}",
            )
        else:
            ui.toast(self, "Reclamaciones enviadas",
                     f"{len(sent)} reclamación(es) enviada(s) con éxito.", kind="success")
        self._reload()

    def _bulk_error(self, msg: str) -> None:
        self._set_buttons_busy(False)
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)
        messagebox.showerror("Error", msg)


# ════════════════════════════════════════════════════════════════════════════
#  Preview / envío
# ════════════════════════════════════════════════════════════════════════════

class ReclamacionPreview(ctk.CTkToplevel):
    def __init__(self, master, pedido_data: dict, on_sent=None,
                 min_days: int = claims_service.DEFAULT_MIN_DAYS):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title(f"Reclamación — {pedido_data['pedido']}")
        self.geometry("960x800")
        self.minsize(820, 680)
        self.transient(master)
        self.grab_set()

        self._pedido_data = pedido_data
        self._preview: dict | None = None
        self._on_sent = on_sent
        self._min_days = min_days
        self._level = claims_service.get_escalation_level(pedido_data)
        self._using_saved = False  # True si los inputs vienen de saved
        self.docs_table: DataTable | None = None

        self._build_skeleton()
        self._load()

    def _build_skeleton(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(18, 6))

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x")
        ctk.CTkLabel(
            title_row, text=self._pedido_data["pedido"],
            font=theme.font(20, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(side="left")

        urgency = self._pedido_data.get("urgency", "low")
        ucolor = URGENCY_COLOR.get(urgency, theme.TEXT_MUTED)
        ctk.CTkLabel(
            title_row, text=f"  {URGENCY_LABEL.get(urgency, '—')}  ",
            font=theme.font(10, "bold"),
            text_color="white", fg_color=ucolor, corner_radius=4,
        ).pack(side="left", padx=10)

        info = (
            f"{self._pedido_data.get('cliente', '')}  ·  "
            f"PO: {self._pedido_data.get('po', '') or '—'}  ·  "
            f"{self._pedido_data.get('docs_count', 0)} docs  ·  "
            f"Max {self._pedido_data.get('max_dias', 0)} días"
        )
        ctk.CTkLabel(
            header, text=info, font=theme.FONT_BODY,
            text_color=theme.TEXT_SUB, anchor="w", justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # Nivel selector
        level_row = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=10,
                                  border_width=1, border_color=theme.BORDER)
        level_row.pack(fill="x", padx=22, pady=(12, 6))
        inner = ctk.CTkFrame(level_row, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(
            inner, text="Nivel de escalation", font=theme.font(10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w")

        self.cmb_level = ctk.CTkOptionMenu(
            inner, values=[LEVEL_LABEL[1], LEVEL_LABEL[2], LEVEL_LABEL[3]],
            width=240, height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, button_color=theme.BG_INPUT,
            button_hover_color=theme.BG_CARD, text_color=theme.TEXT_MAIN,
            font=theme.FONT_BODY, dropdown_font=theme.FONT_BODY,
            command=self._on_level_changed,
        )
        self.cmb_level.set(LEVEL_LABEL[self._level])
        self.cmb_level.pack(anchor="w", pady=(2, 0))

        self.lbl_level_note = ctk.CTkLabel(
            inner,
            text=self._level_note(),
            font=theme.font(11), text_color=theme.TEXT_SUB, anchor="w",
        )
        self.lbl_level_note.pack(anchor="w", pady=(4, 0))

        # Destinatarios
        addr = ctk.CTkFrame(self, fg_color="transparent")
        addr.pack(fill="x", padx=22, pady=(4, 6))

        # Header con label + indicador + botón "Sugeridos"
        addr_head = ctk.CTkFrame(addr, fg_color="transparent")
        addr_head.pack(fill="x")
        ctk.CTkLabel(
            addr_head, text="Destinatarios", font=theme.font(10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(side="left")
        self.lbl_recipients_note = ctk.CTkLabel(
            addr_head, text="", font=theme.font(10),
            text_color=theme.TEXT_MUTED, anchor="w",
        )
        self.lbl_recipients_note.pack(side="left", padx=10)
        self.btn_reset_recipients = ctk.CTkButton(
            addr_head, text="↺ Sugeridos por nivel", font=theme.font(10),
            height=22, width=140, corner_radius=6,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_SUB, border_width=1, border_color=theme.BORDER,
            command=self._apply_suggested_recipients,
        )
        self.btn_reset_recipients.pack(side="right")

        ctk.CTkLabel(addr, text="Para (To)", font=theme.font(10),
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w", pady=(6, 0))
        self.ent_to = ctk.CTkEntry(
            addr, height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_to.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(addr, text="Copia (Cc)", font=theme.font(10),
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        self.ent_cc = ctk.CTkEntry(
            addr, height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_cc.pack(fill="x")

        # Tabla docs (con header + botones Todos/Ninguno + contador)
        docs_head = ctk.CTkFrame(self, fg_color="transparent")
        docs_head.pack(fill="x", padx=22, pady=(14, 4))
        ctk.CTkLabel(
            docs_head, text="Documentos a reclamar",
            font=theme.font(10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(side="left")
        self.lbl_doc_counter = ctk.CTkLabel(
            docs_head, text="", font=theme.font(10),
            text_color=theme.TEXT_MUTED,
        )
        self.lbl_doc_counter.pack(side="left", padx=10)
        ctk.CTkButton(
            docs_head, text="Todos", font=theme.font(10), height=22, width=70, corner_radius=6,
            fg_color="transparent", hover_color=theme.BG_INPUT, text_color=theme.TEXT_SUB,
            border_width=1, border_color=theme.BORDER,
            command=lambda: self._set_all_docs(True),
        ).pack(side="right", padx=(4, 0))
        ctk.CTkButton(
            docs_head, text="Ninguno", font=theme.font(10), height=22, width=70, corner_radius=6,
            fg_color="transparent", hover_color=theme.BG_INPUT, text_color=theme.TEXT_SUB,
            border_width=1, border_color=theme.BORDER,
            command=lambda: self._set_all_docs(False),
        ).pack(side="right")

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
            footer, text="Enviar reclamación  →", font=theme.FONT_BUTTON,
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
            self, text="⏳  Cargando preview…", font=theme.FONT_BODY,
            text_color=theme.TEXT_MUTED, anchor="w",
        )
        self.lbl_status.pack(side="bottom", fill="x", padx=22)

        # Tabla expansible (toma el espacio restante en el medio)
        self.table_host = ctk.CTkFrame(self, fg_color="transparent")
        self.table_host.pack(side="top", fill="both", expand=True, padx=22, pady=(0, 8))

    def _level_note(self) -> str:
        notes = {
            1: "Tono cortés — recordatorio cordial al cliente.",
            2: "Tono firme — incluye dirección en copia (CC: Enrique Serrano).",
            3: "Tono urgente — incluye dirección + comercial del pedido en copia.",
        }
        return notes.get(self._level, "")

    def _on_level_changed(self, value: str) -> None:
        for k, v in LEVEL_LABEL.items():
            if v == value:
                self._level = k
                break
        self.lbl_level_note.configure(text=self._level_note())
        # Si no estamos usando saved, recalcular sugeridos según nuevo nivel.
        # Si hay saved, respetar lo que el usuario tiene puesto (es su personalización).
        if self._preview and not self._using_saved:
            self._apply_suggested_recipients()

    def _apply_suggested_recipients(self) -> None:
        auto_to, auto_cc = claims_service.get_escalation_recipients(self._pedido_data, self._level)
        self.ent_to.delete(0, "end"); self.ent_to.insert(0, ", ".join(auto_to))
        self.ent_cc.delete(0, "end"); self.ent_cc.insert(0, ", ".join(auto_cc))
        self._using_saved = False
        self._update_recipients_note()

    def _update_recipients_note(self) -> None:
        if self._using_saved == "matrix" and self._preview:
            ts = self._preview.get("matrix_updated_at") or ""
            try:
                from datetime import datetime
                stamp = datetime.fromisoformat(ts).strftime("%d %b %Y") if ts else ""
            except Exception:
                stamp = ts[:10]
            tail = f" · {stamp}" if stamp else ""
            self.lbl_recipients_note.configure(
                text=f"📒 Communication Matrix{tail}",
                text_color=theme.ACCENT,
            )
        elif self._using_saved and self._preview and self._preview.get("saved_at"):
            saved_at = self._preview["saved_at"]
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(saved_at)
                stamp = dt.strftime("%d %b %Y")
            except Exception:
                stamp = saved_at[:10]
            self.lbl_recipients_note.configure(
                text=f"💾 Guardados del envío anterior · {stamp}",
                text_color=theme.GREEN,
            )
        else:
            self.lbl_recipients_note.configure(
                text="💡 Sugeridos por nivel de escalation",
                text_color=theme.TEXT_MUTED,
            )

    def _load(self) -> None:
        pedido = self._pedido_data["pedido"]

        min_days = self._min_days

        def worker():
            try:
                pv = claims_service.get_pedido_preview(pedido, min_days=min_days)
                self.after(0, lambda: self._render_preview(pv))
            except Exception as exc:
                logger.exception("Error en preview reclamación")
                err = str(exc)
                self.after(0, lambda: self._render_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _render_preview(self, pv: dict) -> None:
        self._preview = pv

        # Destinatarios: prioridad matrix > saved > sugeridos por nivel
        if pv.get("matrix_to") is not None or pv.get("matrix_cc") is not None:
            self.ent_to.delete(0, "end")
            self.ent_to.insert(0, ", ".join(pv.get("matrix_to") or []))
            self.ent_cc.delete(0, "end")
            self.ent_cc.insert(0, ", ".join(pv.get("matrix_cc") or []))
            self._using_saved = "matrix"
            self._update_recipients_note()
        elif pv.get("saved_to") is not None:
            self.ent_to.delete(0, "end")
            self.ent_to.insert(0, ", ".join(pv.get("saved_to") or []))
            self.ent_cc.delete(0, "end")
            self.ent_cc.insert(0, ", ".join(pv.get("saved_cc") or []))
            self._using_saved = True
            self._update_recipients_note()
        else:
            self._apply_suggested_recipients()

        # Tabla docs con columna ✓ toggleable
        for child in self.table_host.winfo_children():
            child.destroy()
        cols = ["✓", "EIPSA Doc.", "Título", "Estado", "Rev.", "Fecha envío", "Días"]
        self.docs_table = DataTable(self.table_host, columns=cols, selectmode="none")
        self.docs_table.pack(fill="both", expand=True)
        self.docs_table.set_columns_width({
            "✓": 36, "EIPSA Doc.": 130, "Título": 320, "Estado": 110,
            "Rev.": 60, "Fecha envío": 110, "Días": 60,
        })
        self.docs_table.tree.column("✓", anchor="center", stretch=False)

        for r in pv["table_rows"]:
            tag = ""
            if isinstance(r["return_days"], int):
                if r["return_days"] >= 60: tag = "urg_high"
                elif r["return_days"] >= 30: tag = "urg_medium"
                elif r["return_days"] >= 15: tag = "urg_low"
            self.docs_table.add_row(
                values=[
                    "☑", r["eipsa_doc_no"], r["title"], r["status"],
                    r["revision"] or "—", r["sent_date"] or "—", r["return_days"],
                ],
                iid=r["eipsa_doc_no"],
                tags=(tag,) if tag else (),
            )
        self.docs_table.tree.tag_configure("urg_low", foreground=theme.BLUE)
        self.docs_table.tree.tag_configure("urg_medium", foreground=theme.AMBER)
        self.docs_table.tree.tag_configure("urg_high", foreground=theme.RED)
        # Click toggle en columna ✓
        self.docs_table.tree.bind("<Button-1>", self._on_doc_click)

        self._update_doc_counter()

        self.lbl_status.configure(
            text=f"✓  {pv['docs_count']} documento(s) cargados. Revisa destinatarios y selección.",
            text_color=theme.GREEN,
        )
        self.btn_send.configure(state="normal")
        self.btn_preview.configure(state="normal")

    # ── Selección de docs ────────────────────────────────────────────────────

    def _on_doc_click(self, event) -> str | None:
        if not self.docs_table:
            return None
        tree = self.docs_table.tree
        region = tree.identify_region(event.x, event.y)
        col = tree.identify_column(event.x)
        row_id = tree.identify_row(event.y)
        if region != "cell" or col != "#1" or not row_id:
            return None
        values = list(tree.item(row_id, "values"))
        values[0] = "☐" if values[0] == "☑" else "☑"
        tree.item(row_id, values=values)
        self._update_doc_counter()
        return "break"

    def _set_all_docs(self, included: bool) -> None:
        if not self.docs_table:
            return
        tree = self.docs_table.tree
        char = "☑" if included else "☐"
        for iid in tree.get_children():
            values = list(tree.item(iid, "values"))
            values[0] = char
            tree.item(iid, values=values)
        self._update_doc_counter()

    def _get_included_codes(self) -> list[str]:
        if not self.docs_table:
            return []
        out = []
        for iid in self.docs_table.tree.get_children():
            values = self.docs_table.tree.item(iid, "values")
            if values and values[0] == "☑":
                out.append(iid)
        return out

    def _update_doc_counter(self) -> None:
        if not self.docs_table:
            return
        total = len(self.docs_table.tree.get_children())
        sel = len(self._get_included_codes())
        color = theme.GREEN if sel == total else (theme.AMBER if sel > 0 else theme.RED)
        self.lbl_doc_counter.configure(
            text=f"{sel}/{total} incluidos",
            text_color=color,
        )
        self.btn_send.configure(state="normal" if sel > 0 else "disabled")

    def _render_error(self, msg: str) -> None:
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)

    def _preview_email(self) -> None:
        """Genera el HTML de la reclamación con docs marcados + nivel actual, sin enviar."""
        if not self._preview:
            return
        included = self._get_included_codes()
        if not included:
            messagebox.showwarning("Documentos", "Marca al menos un documento (columna ✓) para previsualizar.")
            return

        self.lbl_status.configure(text="⏳  Generando preview…", text_color=theme.TEXT_MUTED)
        pedido = self._pedido_data["pedido"]
        level = self._level

        min_days = self._min_days

        def worker():
            try:
                res = claims_service.generate_claim_html(
                    pedido, level=level, include_eipsa_codes=included,
                    min_days=min_days,
                )
                self.after(0, lambda: _open_html_preview(res["html"], "reclamacion"))
                self.after(0, lambda: self.lbl_status.configure(
                    text=f"✓  Preview L{res['level']} abierto en navegador ({res['docs_count']} docs)",
                    text_color=theme.GREEN,
                ))
            except Exception as exc:
                logger.exception("Error generando preview email")
                err = str(exc)
                self.after(0, lambda: self.lbl_status.configure(
                    text=f"✗  {err}", text_color=theme.RED,
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _send(self) -> None:
        if not self._preview:
            return
        from core import session
        if not session.can_manage("reclamaciones"):
            ui.toast(self, "Solo lectura", "No tienes permiso para enviar reclamaciones.", kind="warn")
            return
        to = [s.strip() for s in self.ent_to.get().split(",") if s.strip()]
        cc = [s.strip() for s in self.ent_cc.get().split(",") if s.strip()]
        if not to:
            messagebox.showwarning("Destinatarios", "Indica al menos un destinatario en 'To'.")
            return

        included = self._get_included_codes()
        if not included:
            messagebox.showwarning("Documentos", "Marca al menos un documento (columna ✓) antes de enviar.")
            return

        confirm = messagebox.askyesno(
            "Confirmar reclamación",
            f"¿Enviar reclamación de nivel {self._level} ({ESCALATION_LEVEL_NAMES[self._level]})?\n\n"
            f"Pedido: {self._pedido_data['pedido']}\n"
            f"Documentos a reclamar: {len(included)} de {self._preview['docs_count']}\n"
            f"To: {', '.join(to)}\n"
            f"Cc: {', '.join(cc) or '—'}\n\n"
            f"Los destinatarios se guardarán para futuras reclamaciones de este pedido.",
        )
        if not confirm:
            return

        self.btn_send.configure(state="disabled", text="Enviando…")
        self.lbl_status.configure(text="📤  Enviando reclamación…", text_color=theme.TEXT_MUTED)

        pedido = self._pedido_data["pedido"]
        level = self._level

        min_days = self._min_days

        def worker():
            try:
                res = claims_service.send_claim(
                    pedido, to=to, cc=cc, level=level,
                    include_eipsa_codes=included,
                    min_days=min_days,
                )
                self.after(0, lambda: self._send_done(res))
            except Exception as exc:
                logger.exception("Error enviando reclamación")
                err = str(exc)
                self.after(0, lambda: self._send_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _send_done(self, res: dict) -> None:
        # Toast sobre la ventana padre (este diálogo se cierra a continuación)
        ui.toast(self.master, "Reclamación enviada",
                 f"Nivel {res.get('level')} ({res.get('level_name')}) · "
                 f"{res.get('docs_count')} documento(s).", kind="success")
        if self._on_sent:
            self._on_sent()
        self.destroy()

    def _send_error(self, msg: str) -> None:
        self.btn_send.configure(state="normal", text="Enviar reclamación  →")
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)
        messagebox.showerror("Error", msg)


# ════════════════════════════════════════════════════════════════════════════
#  Communication Matrix — gestión de contactos por pedido
# ════════════════════════════════════════════════════════════════════════════

class CommMatrixWindow(ctk.CTkToplevel):
    """Lista de pedidos en la matrix con sus contactos TO/CC.

    Permite importar masivamente desde un .txt y editar/borrar por pedido.
    """

    def __init__(self, master):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title("Communication Matrix · Reclamaciones")
        self.geometry("920x720")
        self.minsize(760, 560)
        self.transient(master)
        self.grab_set()

        self._build_layout()
        self._reload_list()

    def _build_layout(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_5, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(
            header, text="Communication Matrix",
            font=theme.FONT_TITLE, text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Destinatarios oficiales por pedido · prioridad sobre el último envío y los sugeridos por nivel",
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(theme.SPACE_1, 0))

        # Toolbar
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=theme.SPACE_5, pady=(theme.SPACE_3, theme.SPACE_2))

        ctk.CTkButton(
            toolbar, text="📥  Importar .txt", font=theme.FONT_SMALL_BOLD,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self._import_txt,
        ).pack(side="left")

        ctk.CTkButton(
            toolbar, text="+  Nuevo pedido", font=theme.FONT_SMALL_BOLD,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=lambda: self._open_editor(None),
        ).pack(side="left", padx=(theme.SPACE_2, 0))

        self.lbl_count = ctk.CTkLabel(
            toolbar, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self.lbl_count.pack(side="right")

        # Status
        self.lbl_status = ctk.CTkLabel(
            self, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
        )
        self.lbl_status.pack(fill="x", padx=theme.SPACE_5)

        # Footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=theme.SPACE_5, pady=theme.SPACE_4)
        ctk.CTkButton(
            footer, text="Cerrar", font=theme.FONT_BUTTON,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self.destroy,
        ).pack(side="right")

        # Lista scrollable
        self.list_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_scroll.pack(side="top", fill="both", expand=True,
                               padx=theme.SPACE_5, pady=(theme.SPACE_2, theme.SPACE_2))

    # ── Importar .txt ────────────────────────────────────────────────────────

    def _import_txt(self) -> None:
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            parent=self, title="Importar communication matrix desde .txt",
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            # Fallback latin-1 si el .txt no es UTF-8
            with open(path, "r", encoding="latin-1") as f:
                content = f.read()
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo leer el archivo:\n{exc}", parent=self)
            return

        from core.services import comm_matrix
        try:
            res = comm_matrix.import_from_txt(content)
        except Exception as exc:
            logger.exception("Error parseando .txt")
            messagebox.showerror("Error", str(exc), parent=self)
            return

        lines = [
            f"✓  {res['imported']} pedido(s) en la matrix",
            f"     · {res['created']} nuevo(s)  ·  {res['updated']} actualizado(s)",
        ]
        if res["duplicates_in_input"]:
            lines.append(f"⚠  Duplicados en el .txt (último prevalece): {', '.join(res['duplicates_in_input'])}")
        if res["skipped"]:
            lines.append(f"⚠  Saltados (sin emails): {', '.join(res['skipped'])}")

        messagebox.showinfo("Importación completada", "\n".join(lines), parent=self)
        self._reload_list()

    # ── Lista ────────────────────────────────────────────────────────────────

    def _reload_list(self) -> None:
        for w in self.list_scroll.winfo_children():
            w.destroy()

        from core.services import comm_matrix
        pedidos = comm_matrix.list_pedidos()
        self.lbl_count.configure(text=f"{len(pedidos)} pedido(s)")

        if not pedidos:
            ctk.CTkLabel(
                self.list_scroll,
                text="No hay pedidos en la matrix. Importa un .txt o añade uno manualmente.",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            ).pack(pady=theme.SPACE_8)
            return

        for p in pedidos:
            self._render_row(p)

    def _render_row(self, p: dict) -> None:
        row = ctk.CTkFrame(
            self.list_scroll, fg_color=theme.BG_CARD,
            corner_radius=theme.RADIUS_MD,
            border_width=1, border_color=theme.BORDER,
        )
        row.pack(fill="x", pady=(0, theme.SPACE_2))

        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_3)

        # Pedido (a la izquierda)
        ctk.CTkLabel(
            inner, text=p["pedido"],
            font=theme.font(13, "bold"),
            text_color=theme.ACCENT, width=110, anchor="w",
        ).pack(side="left")

        # Contador TO/CC
        counts = f"{len(p['to'])} TO  ·  {len(p['cc'])} CC"
        ctk.CTkLabel(
            inner, text=counts,
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            width=110, anchor="w",
        ).pack(side="left")

        # IMPORTANTE: packeamos los botones (side="right") ANTES del preview
        # expandible. Si no, el preview con expand=True consume todo el espacio
        # y los botones quedan fuera del viewport.
        ctk.CTkButton(
            inner, text="🗑", width=32,
            height=theme.HEIGHT_BUTTON_SM, corner_radius=theme.RADIUS_SM,
            fg_color="transparent", hover_color=theme.DELETE_HOVER,
            text_color=theme.TEXT_MUTED, font=theme.FONT_BUTTON,
            command=lambda ped=p["pedido"]: self._delete(ped),
        ).pack(side="right", padx=theme.SPACE_1)

        ctk.CTkButton(
            inner, text="Editar", width=70,
            height=theme.HEIGHT_BUTTON_SM, corner_radius=theme.RADIUS_SM,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            font=theme.FONT_SMALL_BOLD,
            command=lambda ped=p["pedido"]: self._open_editor(ped),
        ).pack(side="right", padx=theme.SPACE_1)

        # Vista compacta de TO + CC (primeros 2 + "…") — al final, llena el resto
        preview_emails = (p["to"][:2] + p["cc"][:2])
        if not preview_emails:
            preview_text = "(sin contactos)"
        else:
            preview_text = ", ".join(preview_emails)
            remaining = (len(p["to"]) + len(p["cc"])) - len(preview_emails)
            if remaining > 0:
                preview_text += f"  +{remaining} más"
        ctk.CTkLabel(
            inner, text=preview_text,
            font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
            anchor="w", justify="left",
        ).pack(side="left", fill="x", expand=True, padx=(theme.SPACE_2, theme.SPACE_2))

    def _open_editor(self, pedido: str | None) -> None:
        CommMatrixEditor(self, pedido=pedido, on_save=self._reload_list)

    def _delete(self, pedido: str) -> None:
        if not messagebox.askyesno(
            "Borrar contactos",
            f"¿Borrar la entrada de {pedido} de la matrix?",
            parent=self,
        ):
            return
        from core.services import comm_matrix
        comm_matrix.remove(pedido)
        self.lbl_status.configure(text=f"Eliminado {pedido}", text_color=theme.TEXT_MUTED)
        self._reload_list()


class CommMatrixEditor(ctk.CTkToplevel):
    """Editor de contactos de un pedido (TO + CC). Acepta uno por línea o separados por coma."""

    def __init__(self, master, pedido: str | None, on_save=None):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title("Editar pedido — Communication Matrix")
        self.geometry("640x620")
        self.minsize(520, 480)
        self.transient(master)
        self.grab_set()

        self._on_save = on_save
        self._is_new = pedido is None
        existing = None
        if pedido:
            from core.services import comm_matrix
            existing = comm_matrix.get_contacts(pedido)

        # Header
        ctk.CTkLabel(
            self,
            text=("Nuevo pedido" if self._is_new else f"Editar {pedido}"),
            font=theme.FONT_HEADING, text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w", padx=theme.SPACE_5, pady=(theme.SPACE_5, theme.SPACE_1))

        # Footer (side=bottom primero)
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=theme.SPACE_5, pady=theme.SPACE_4)
        ctk.CTkButton(
            footer, text="Cancelar", font=theme.FONT_BUTTON,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self.destroy,
        ).pack(side="right", padx=(theme.SPACE_2, 0))
        ctk.CTkButton(
            footer, text="Guardar", font=theme.FONT_BUTTON,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self._save,
        ).pack(side="right")

        # Body
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(side="top", fill="both", expand=True,
                   padx=theme.SPACE_5, pady=(theme.SPACE_3, 0))

        # Pedido
        ctk.CTkLabel(body, text="PEDIDO *", font=theme.FONT_LABEL,
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        self.ent_pedido = ctk.CTkEntry(
            body, placeholder_text="P-26/029",
            height=theme.HEIGHT_INPUT, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        if pedido:
            self.ent_pedido.insert(0, pedido)
            self.ent_pedido.configure(state="disabled")
        self.ent_pedido.pack(fill="x", pady=(theme.SPACE_1, theme.SPACE_3))

        # TO
        ctk.CTkLabel(body, text="TO (uno por línea o separados por coma / ;)",
                     font=theme.FONT_LABEL, text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        self.txt_to = ctk.CTkTextbox(
            body, height=140, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER, border_width=1,
            text_color=theme.TEXT_MAIN, font=theme.FONT_MONO,
        )
        if existing:
            self.txt_to.insert("1.0", "\n".join(existing.get("to") or []))
        self.txt_to.pack(fill="x", pady=(theme.SPACE_1, theme.SPACE_3))

        # CC
        ctk.CTkLabel(body, text="CC (uno por línea o separados por coma / ;)",
                     font=theme.FONT_LABEL, text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        self.txt_cc = ctk.CTkTextbox(
            body, height=140, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER, border_width=1,
            text_color=theme.TEXT_MAIN, font=theme.FONT_MONO,
        )
        if existing:
            self.txt_cc.insert("1.0", "\n".join(existing.get("cc") or []))
        self.txt_cc.pack(fill="x", pady=(theme.SPACE_1, 0))

        self.lbl_error = ctk.CTkLabel(
            body, text="", font=theme.FONT_SMALL, text_color=theme.RED,
            anchor="w", justify="left", wraplength=560,
        )
        self.lbl_error.pack(anchor="w", pady=(theme.SPACE_2, 0))

    def _save(self) -> None:
        import re as _re
        pedido = self.ent_pedido.get().strip().upper()
        if not _re.match(r"^P-\d{2}/\d{3}$", pedido):
            self.lbl_error.configure(text="Formato de pedido inválido (esperado P-XX/YYY).")
            return
        to = _split_emails(self.txt_to.get("1.0", "end"))
        cc = _split_emails(self.txt_cc.get("1.0", "end"))
        if not to and not cc:
            self.lbl_error.configure(text="Indica al menos un email en TO o CC.")
            return

        from core.services import comm_matrix
        try:
            comm_matrix.set_contacts(pedido, to, cc)
        except Exception as exc:
            self.lbl_error.configure(text=str(exc))
            return

        if self._on_save:
            self._on_save()
        self.destroy()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_emails(raw: str) -> list[str]:
    """Acepta emails separados por línea, coma o punto y coma. Elimina espacios."""
    import re as _re
    parts = _re.split(r"[,\n;]+", raw or "")
    return [p.strip() for p in parts if p.strip()]


ESCALATION_LEVEL_NAMES = {1: "Recordatorio", 2: "Reclamación formal", 3: "Escalation urgente"}


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


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso).strftime("%d %b %Y")
    except Exception:
        return iso[:10]
