"""Vista Reportes — 3 tabs internos: Excels · Resúmenes por email · Programados."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

from core.config import USERS
from core.services import monitoring as monitoring_service
from core.services import reports as reports_service
from core.services import scheduled_reports as sched_service
from core.services import weekly_summary as weekly_service
from gui import theme

logger = logging.getLogger(__name__)


EXCEL_REPORTS = [
    {
        "id": "monitoring",
        "icon": "📊",
        "color": theme.BLUE,
        "title": "Monitoring Report",
        "desc": ("Excel multi-hoja con secciones ALL DOC. / ENVIADOS / DEVOLUCIONES / "
                 "CRÍTICOS / CRÍTICOS +15d / SIN ENVIAR + STATUS GLOBAL con gráfico."),
        "filename": "Monitoring_Report_{date}.xlsx",
    },
    {
        "id": "export",
        "icon": "📥",
        "color": theme.GREEN,
        "title": "Export Excel (simple)",
        "desc": "Excel plano con todos los documentos + hoja de resumen por estado.",
        "filename": "Export_DocFlow_{date}.xlsx",
    },
]


# ════════════════════════════════════════════════════════════════════════════
#  Vista principal
# ════════════════════════════════════════════════════════════════════════════

class ReportesView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._busy_id: str | None = None
        self._excel_cards: dict[str, dict] = {}
        self._schedule_rows: dict[str, dict] = {}
        self._build_layout()

    def _build_layout(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(
            header, text="Centro de Reportes", font=theme.FONT_TITLE,
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text="Excels · resúmenes por email · programación automática",
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(theme.SPACE_1, 0))

        # Status line global
        self.lbl_status = ctk.CTkLabel(
            self, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
        )
        self.lbl_status.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_2, 0))

        # Tabs
        self.tabs = ctk.CTkTabview(
            self, fg_color=theme.BG_PAGE,
            segmented_button_fg_color=theme.BG_CARD,
            segmented_button_selected_color=theme.ACCENT,
            segmented_button_selected_hover_color=theme.ACCENT_HOVER,
            segmented_button_unselected_color=theme.BG_CARD,
            segmented_button_unselected_hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN,
        )
        self.tabs.pack(fill="both", expand=True,
                        padx=theme.SPACE_5, pady=(theme.SPACE_3, theme.SPACE_4))

        self.tab_excels = self.tabs.add("Excels")
        self.tab_summaries = self.tabs.add("Resúmenes por email")
        self.tab_scheduled = self.tabs.add("Programados")
        self.tab_data = self.tabs.add("Fuente de datos")

        self._build_tab_excels(self.tab_excels)
        self._build_tab_summaries(self.tab_summaries)
        self._build_tab_scheduled(self.tab_scheduled)
        self._build_tab_data(self.tab_data)

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 1: EXCELS
    # ════════════════════════════════════════════════════════════════════════

    def _build_tab_excels(self, parent) -> None:
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="both", expand=True, pady=8)
        grid.grid_columnconfigure((0, 1), weight=1, uniform="cols")
        for i, report in enumerate(EXCEL_REPORTS):
            row, col = divmod(i, 2)
            self._excel_cards[report["id"]] = self._build_excel_card(grid, row, col, report)

    def _build_excel_card(self, parent, row: int, col: int, report: dict) -> dict:
        card = ctk.CTkFrame(
            parent, fg_color=theme.BG_CARD, corner_radius=12,
            border_width=1, border_color=theme.BORDER,
        )
        card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=18)

        title_row = ctk.CTkFrame(inner, fg_color="transparent")
        title_row.pack(fill="x")
        ctk.CTkLabel(title_row, text=report["icon"],
                     font=theme.font(22), text_color=report["color"]).pack(side="left")
        ctk.CTkLabel(title_row, text=report["title"],
                     font=theme.font(15, "bold"),
                     text_color=theme.TEXT_MAIN, anchor="w").pack(side="left", padx=(8, 0))

        ctk.CTkLabel(inner, text=report["desc"], wraplength=380,
                     font=theme.FONT_BODY, text_color=theme.TEXT_SUB,
                     justify="left", anchor="w").pack(anchor="w", pady=(8, 12), fill="x")

        lbl_card = ctk.CTkLabel(inner, text="", font=theme.font(10),
                                text_color=theme.TEXT_MUTED, anchor="w")
        lbl_card.pack(anchor="w", pady=(0, 8))

        actions = ctk.CTkFrame(inner, fg_color="transparent")
        actions.pack(fill="x", side="bottom")
        btn_download = ctk.CTkButton(
            actions, text="⬇  Descargar", font=theme.FONT_BUTTON,
            height=36, corner_radius=8,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=lambda r=report: self._on_download_excel(r),
        )
        btn_download.pack(side="left", fill="x", expand=True)

        return {"card": card, "lbl": lbl_card, "btn": btn_download, "last_path": None}

    def _on_download_excel(self, report: dict) -> None:
        if self._busy_id is not None:
            return
        default_name = report["filename"].format(date=datetime.now().strftime("%Y-%m-%d"))
        path = filedialog.asksaveasfilename(
            parent=self, title=f"Guardar {report['title']}",
            defaultextension=".xlsx", initialfile=default_name,
            filetypes=[("Excel", "*.xlsx"), ("Todos", "*.*")],
        )
        if not path:
            return

        self._busy_id = report["id"]
        card = self._excel_cards[report["id"]]
        card["btn"].configure(state="disabled", text="Generando…")
        card["lbl"].configure(text="⏳  Generando Excel…", text_color=theme.TEXT_MUTED)
        self.lbl_status.configure(text=f"Generando {report['title']}…", text_color=theme.TEXT_MUTED)

        rid = report["id"]
        title = report["title"]

        def worker():
            try:
                if rid == "monitoring":
                    sections = monitoring_service.get_monitoring_report_sections()
                    if not sections.get("all_docs"):
                        raise RuntimeError("No hay documentos en data_erp.xlsx")
                    data = reports_service.generate_monitoring_excel(sections)
                elif rid == "export":
                    docs = monitoring_service.get_monitoring_data()
                    if not docs:
                        raise RuntimeError("No hay documentos en data_erp.xlsx")
                    data = reports_service.generate_export_excel(docs)
                else:
                    raise ValueError(f"Reporte desconocido: {rid}")
                with open(path, "wb") as f:
                    f.write(data)
                self.after(0, lambda: self._on_excel_done(rid, path, title))
            except Exception as exc:
                logger.exception("Error generando %s", rid)
                err = str(exc)
                self.after(0, lambda: self._on_excel_error(rid, err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_excel_done(self, rid: str, path: str, title: str) -> None:
        self._busy_id = None
        card = self._excel_cards[rid]
        card["last_path"] = path
        card["btn"].configure(state="normal", text="⬇  Descargar")
        card["lbl"].configure(text=f"✓  {os.path.basename(path)}  ·  {_fmt_size(path)}",
                              text_color=theme.GREEN)
        self.lbl_status.configure(text=f"✓  {title} guardado en {path}", text_color=theme.GREEN)
        ans = messagebox.askyesnocancel(
            "Archivo generado",
            f"{title} guardado correctamente.\n\n📂 {path}\n\n"
            "¿Abrir el archivo ahora? (No: abrir carpeta · Cancelar: nada)",
        )
        if ans is True:
            _open_path(path)
        elif ans is False:
            _open_path(str(Path(path).parent))

    def _on_excel_error(self, rid: str, msg: str) -> None:
        self._busy_id = None
        card = self._excel_cards[rid]
        card["btn"].configure(state="normal", text="⬇  Descargar")
        card["lbl"].configure(text=f"✗  {msg}", text_color=theme.RED)
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)
        messagebox.showerror("Error generando reporte", msg)

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 2: RESÚMENES POR EMAIL
    # ════════════════════════════════════════════════════════════════════════

    def _build_tab_summaries(self, parent) -> None:
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="both", expand=True, pady=8)
        grid.grid_columnconfigure((0, 1), weight=1, uniform="cols")

        self._build_summary_card(
            grid, 0, 0,
            title="Resumen Monitoring Report",
            icon="📈", color=theme.ACCENT,
            desc="Email ejecutivo semanal con KPIs y párrafo narrativo. Sin la API key de Claude se usa un fallback textual.",
            kind="executive",
        )
        self._build_summary_card(
            grid, 0, 1,
            title="Monitoring Report (Personal)",
            icon="✉", color=theme.GREEN,
            desc="Email individual por doc controller con sus pendientes (Com. Menores/Mayores · Comentado · Rechazado · Sin Enviar), KPIs y comparativa vs equipo.",
            kind="personal",
        )

    def _build_summary_card(self, parent, row: int, col: int, *,
                            title: str, icon: str, color: str, desc: str, kind: str) -> None:
        card = ctk.CTkFrame(
            parent, fg_color=theme.BG_CARD, corner_radius=12,
            border_width=1, border_color=theme.BORDER,
        )
        card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=18)

        title_row = ctk.CTkFrame(inner, fg_color="transparent")
        title_row.pack(fill="x")
        ctk.CTkLabel(title_row, text=icon,
                     font=theme.font(22), text_color=color).pack(side="left")
        ctk.CTkLabel(title_row, text=title,
                     font=theme.font(15, "bold"),
                     text_color=theme.TEXT_MAIN, anchor="w").pack(side="left", padx=(8, 0))

        ctk.CTkLabel(inner, text=desc, wraplength=380,
                     font=theme.FONT_BODY, text_color=theme.TEXT_SUB,
                     justify="left", anchor="w").pack(anchor="w", pady=(8, 14), fill="x")

        # Selector de usuario sólo para el reporte personal
        preview_user_var: ctk.StringVar | None = None
        if kind == "personal":
            picker_row = ctk.CTkFrame(inner, fg_color="transparent")
            picker_row.pack(fill="x", pady=(0, 10))
            ctk.CTkLabel(
                picker_row, text="Previsualizar para:",
                font=theme.font(10, "bold"),
                text_color=theme.TEXT_MUTED,
            ).pack(side="left")
            preview_user_var = ctk.StringVar(value="JP")
            options = [f"{k} — {v['nombre']}" for k, v in sorted(USERS.items())]
            picker = ctk.CTkOptionMenu(
                picker_row, values=options, variable=None,
                width=200, height=28, corner_radius=6,
                fg_color=theme.BG_INPUT, button_color=theme.BG_INPUT,
                button_hover_color=theme.BG_CARD, text_color=theme.TEXT_MAIN,
                font=theme.font(11), dropdown_font=theme.font(11),
                command=lambda selected, var=preview_user_var: var.set(selected.split(" — ")[0]),
            )
            picker.set("JP — Jose Paredes")
            picker.pack(side="left", padx=(8, 0))

        actions = ctk.CTkFrame(inner, fg_color="transparent")
        actions.pack(fill="x", side="bottom")
        ctk.CTkButton(
            actions, text="👁  Preview", font=theme.FONT_BUTTON,
            height=36, corner_radius=8,
            fg_color=theme.BG_INPUT, hover_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=lambda v=preview_user_var: self._open_preview(kind, v.get() if v else "JP"),
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            actions, text="📤  Enviar", font=theme.FONT_BUTTON,
            height=36, corner_radius=8,
            fg_color=color, hover_color=theme.ACCENT_HOVER,
            command=lambda: self._open_send_dialog(kind),
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

    def _open_preview(self, kind: str, initials: str = "JP") -> None:
        label = "Resumen Ejecutivo" if kind == "executive" else f"Personal de {initials}"
        self.lbl_status.configure(text=f"⏳  Generando preview ({label})…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                if kind == "executive":
                    html = weekly_service.get_executive_preview()
                else:
                    html = weekly_service.get_personal_preview(initials)
                self.after(0, lambda: self._show_preview_html(html, kind, initials))
            except Exception as exc:
                logger.exception("Error preview")
                err = str(exc)
                self.after(0, lambda: self._show_preview_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _show_preview_html(self, html: str, kind: str, initials: str = "") -> None:
        suffix = f"_{kind}_{initials}_preview.html" if initials else f"_{kind}_preview.html"
        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=suffix, delete=False,
        )
        tmp.write(html)
        tmp.close()
        webbrowser.open(f"file://{tmp.name}")
        label = f"({initials})" if initials and kind == "personal" else ""
        self.lbl_status.configure(
            text=f"✓  Preview {label} abierto en navegador",
            text_color=theme.GREEN,
        )

    def _show_preview_error(self, msg: str) -> None:
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)
        messagebox.showerror("Error preview", msg)

    def _open_send_dialog(self, kind: str) -> None:
        if kind == "executive":
            SendExecutiveDialog(self, on_sent=lambda: self._on_sent(kind))
        else:
            SendPersonalDialog(self, on_sent=lambda: self._on_sent(kind))

    def _on_sent(self, kind: str) -> None:
        label = "Resumen ejecutivo" if kind == "executive" else "Resúmenes personales"
        self.lbl_status.configure(text=f"✓  {label} enviados", text_color=theme.GREEN)

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 3: PROGRAMADOS
    # ════════════════════════════════════════════════════════════════════════

    def _build_tab_scheduled(self, parent) -> None:
        # Aviso
        info = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        info.pack(fill="x", pady=(8, 12))
        ctk.CTkLabel(
            info,
            text=("ℹ  Los reportes programados se ejecutan en segundo plano mientras "
                  "DocFlow Lite está abierto. Si cierras la app, los envíos se pausan."),
            font=theme.FONT_BODY, text_color=theme.TEXT_SUB,
            anchor="w", justify="left", wraplength=700,
        ).pack(fill="x", padx=14, pady=10)

        # Toolbar
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(
            toolbar, text="↻ Recargar", font=theme.FONT_BUTTON,
            height=32, corner_radius=8,
            fg_color=theme.BG_CARD, hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self._reload_schedules,
        ).pack(side="left")

        # Lista
        self.schedules_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.schedules_scroll.pack(fill="both", expand=True)

        self._reload_schedules()

    def _reload_schedules(self) -> None:
        for w in self.schedules_scroll.winfo_children():
            w.destroy()
        self._schedule_rows.clear()
        for sched in sched_service.list_schedules():
            self._render_schedule_card(sched)

    def _render_schedule_card(self, sched: dict) -> None:
        enabled = bool(sched.get("enabled"))
        card = ctk.CTkFrame(
            self.schedules_scroll,
            fg_color=theme.BG_CARD, corner_radius=10,
            border_width=1, border_color=theme.ACCENT if enabled else theme.BORDER,
        )
        card.pack(fill="x", pady=4)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(10, 4))

        # Toggle enabled
        var = ctk.BooleanVar(value=enabled)
        sw = ctk.CTkSwitch(
            top, text="", variable=var, width=44,
            progress_color=theme.ACCENT,
            command=lambda sid=sched["id"], v=var, c=card: self._toggle_enabled(sid, v.get(), c),
        )
        sw.pack(side="left", padx=(0, 12))

        # Titulo + descripción
        title_box = ctk.CTkFrame(top, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            title_box, text=sched["title"],
            font=theme.font(13, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box, text=sched.get("description") or "",
            font=theme.font(11), text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w")

        # Acciones
        ctk.CTkButton(
            top, text="✏ Editar", font=theme.FONT_BUTTON,
            width=80, height=30, corner_radius=6,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_SUB, border_width=1, border_color=theme.BORDER,
            command=lambda s=sched: self._open_edit_dialog(s),
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            top, text="▶ Ejecutar ahora", font=theme.FONT_BUTTON,
            width=130, height=30, corner_radius=6,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=lambda sid=sched["id"]: self._run_now(sid),
        ).pack(side="right", padx=4)

        # Footer: horario + last_run
        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(
            footer, text=f"⏰  {sched_service.format_next_run(sched)}",
            font=theme.font(11),
            text_color=theme.TEXT_MAIN if enabled else theme.TEXT_MUTED,
            anchor="w",
        ).pack(side="left", padx=(56, 0))

        last_run = sched.get("last_run")
        if last_run:
            ts = last_run.get("timestamp", "")
            status = last_run.get("status", "")
            try:
                dt = datetime.fromisoformat(ts)
                ts_label = dt.strftime("%d %b %H:%M")
            except Exception:
                ts_label = ts[:16]
            icon = "✓" if status == "success" else "✗"
            color = theme.GREEN if status == "success" else theme.RED
            ctk.CTkLabel(
                footer, text=f"  ·  Último: {icon} {ts_label}",
                font=theme.font(11), text_color=color, anchor="w",
            ).pack(side="left")

        # Recipients
        recipients = sched.get("recipients") or {}
        to = recipients.get("to") or []
        cc = recipients.get("cc") or []
        if sched["type"] == "executive" and (to or cc):
            recip_text = f"To: {', '.join(to)}" + (f" · Cc: {', '.join(cc)}" if cc else "")
            ctk.CTkLabel(
                footer, text=f"  ·  {recip_text}",
                font=theme.font(10), text_color=theme.TEXT_MUTED, anchor="w",
            ).pack(side="left")
        elif sched["type"] == "personal":
            uf = (sched.get("options") or {}).get("user_filter", "all")
            filter_text = "Todo el equipo" if uf == "all" else f"Filtro: {uf}"
            ctk.CTkLabel(
                footer, text=f"  ·  {filter_text}",
                font=theme.font(10), text_color=theme.TEXT_MUTED, anchor="w",
            ).pack(side="left")

        self._schedule_rows[sched["id"]] = {"card": card, "switch": sw, "var": var}

    def _toggle_enabled(self, schedule_id: str, enabled: bool, card_widget) -> None:
        sched_service.update_schedule(schedule_id, {"enabled": enabled})
        card_widget.configure(border_color=theme.ACCENT if enabled else theme.BORDER)
        self.lbl_status.configure(
            text=f"{'Activado' if enabled else 'Desactivado'} schedule '{schedule_id}'",
            text_color=theme.GREEN if enabled else theme.TEXT_MUTED,
        )

    def _run_now(self, schedule_id: str) -> None:
        if not messagebox.askyesno("Ejecutar ahora", f"¿Ejecutar el reporte '{schedule_id}' ahora?"):
            return

        self.lbl_status.configure(text=f"⏳  Ejecutando {schedule_id}…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                res = sched_service.execute_schedule(schedule_id)
                self.after(0, lambda: self._on_run_done(schedule_id, res))
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda: self._on_run_error(schedule_id, err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_run_done(self, schedule_id: str, res: dict) -> None:
        if res.get("status") == "success":
            self.lbl_status.configure(text=f"✓  {schedule_id} ejecutado", text_color=theme.GREEN)
            messagebox.showinfo("Ejecutado", f"✓ {schedule_id} ejecutado correctamente.\n\n{res.get('result', '')}")
        else:
            self.lbl_status.configure(text=f"✗  {res.get('error')}", text_color=theme.RED)
            messagebox.showerror("Error", res.get("error", "Error desconocido"))
        self._reload_schedules()

    def _on_run_error(self, schedule_id: str, msg: str) -> None:
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)
        messagebox.showerror("Error", msg)

    def _open_edit_dialog(self, sched: dict) -> None:
        EditScheduleDialog(self, sched=sched, on_save=self._reload_schedules)

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 4: FUENTE DE DATOS
    # ════════════════════════════════════════════════════════════════════════

    def _build_tab_data(self, parent) -> None:
        # Aviso
        info = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=theme.RADIUS_MD,
                            border_width=1, border_color=theme.BORDER)
        info.pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_3))
        ctk.CTkLabel(
            info,
            text=("ℹ  Estos archivos alimentan Documentos, Reclamaciones y todos los reportes. "
                  "Importa una copia local o vincula una ruta de red para que se actualice automáticamente."),
            font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
            anchor="w", justify="left", wraplength=820,
        ).pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_2)

        # Container con scroll
        self.data_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.data_scroll.pack(fill="both", expand=True)

        self._data_cards: dict[str, dict] = {}
        self._reload_data_cards()

    def _reload_data_cards(self) -> None:
        for w in self.data_scroll.winfo_children():
            w.destroy()
        self._data_cards.clear()
        try:
            from core import data_source
            statuses = data_source.get_all_status()
        except Exception as exc:
            logger.exception("Error data_source.get_all_status")
            ctk.CTkLabel(
                self.data_scroll, text=f"Error cargando estado: {exc}",
                font=theme.FONT_SMALL, text_color=theme.RED,
            ).pack(pady=theme.SPACE_3)
            return
        for st in statuses:
            self._data_cards[st["kind"]] = self._render_data_card(st)

    def _render_data_card(self, st: dict) -> dict:
        kind = st["kind"]
        card = ctk.CTkFrame(
            self.data_scroll, fg_color=theme.BG_CARD,
            corner_radius=theme.RADIUS_LG,
            border_width=1, border_color=theme.BORDER,
        )
        card.pack(fill="x", pady=(0, theme.SPACE_3))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=theme.SPACE_5, pady=theme.SPACE_4)

        # Header: icono + título + badge de modo
        title_row = ctk.CTkFrame(inner, fg_color="transparent")
        title_row.pack(fill="x")

        ctk.CTkLabel(
            title_row, text="◫", font=theme.font(18, "bold"),
            text_color=theme.BLUE, width=28,
        ).pack(side="left")

        ctk.CTkLabel(
            title_row, text=st["label"],
            font=theme.font(14, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=(theme.SPACE_1, theme.SPACE_2))

        # Badge de estado
        mode = st["mode"]
        if not st["exists"]:
            badge_text, badge_color = "● No encontrado", theme.RED
        elif mode == "linked":
            badge_text, badge_color = "● Vinculado", theme.BLUE
        elif mode == "linked_broken":
            badge_text, badge_color = "● Vínculo roto", theme.RED
        else:
            badge_text, badge_color = "● Local", theme.GREEN

        ctk.CTkLabel(
            title_row, text=badge_text,
            font=theme.FONT_SMALL_BOLD, text_color=badge_color,
        ).pack(side="left")

        # Path actual
        path_lbl = ctk.CTkLabel(
            inner, text=st["path"] or "(sin configurar)",
            font=theme.FONT_MONO, text_color=theme.TEXT_SUB,
            anchor="w", justify="left", wraplength=820,
        )
        path_lbl.pack(anchor="w", fill="x", pady=(theme.SPACE_2, theme.SPACE_1))

        # Tamaño + fecha modificación
        if st["exists"]:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(st["modified"])
                mod_label = dt.strftime("%d %b %Y · %H:%M")
            except Exception:
                mod_label = st.get("modified", "—")
            meta = f"{_fmt_size_bytes(st['size'])}  ·  modificado {mod_label}"
        else:
            meta = "Archivo no disponible"

        ctk.CTkLabel(
            inner, text=meta,
            font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", pady=(0, theme.SPACE_3))

        # Acciones
        actions = ctk.CTkFrame(inner, fg_color="transparent")
        actions.pack(fill="x")

        ctk.CTkButton(
            actions, text="📥  Importar archivo…", font=theme.FONT_SMALL_BOLD,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            text_color="#FFFFFF",
            command=lambda k=kind: self._import_file(k),
        ).pack(side="left")

        ctk.CTkButton(
            actions, text="🔗  Vincular ruta…", font=theme.FONT_SMALL_BOLD,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=lambda k=kind: self._link_path(k),
        ).pack(side="left", padx=(theme.SPACE_2, 0))

        if st["mode"] in ("linked", "linked_broken"):
            ctk.CTkButton(
                actions, text="Quitar vínculo", font=theme.FONT_SMALL_BOLD,
                height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
                fg_color="transparent", hover_color=theme.BG_INPUT,
                text_color=theme.TEXT_SUB, border_width=1, border_color=theme.BORDER,
                command=lambda k=kind: self._clear_link(k),
            ).pack(side="left", padx=(theme.SPACE_2, 0))

        if st["exists"]:
            ctk.CTkButton(
                actions, text="Abrir carpeta", font=theme.FONT_SMALL_BOLD,
                height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
                fg_color="transparent", hover_color=theme.BG_INPUT,
                text_color=theme.TEXT_SUB, border_width=1, border_color=theme.BORDER,
                command=lambda p=st["path"]: _open_path(str(Path(p).parent)),
            ).pack(side="left", padx=(theme.SPACE_2, 0))

        return {"card": card}

    # ── Acciones del tab Datos ───────────────────────────────────────────────

    def _import_file(self, kind: str) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title=f"Importar {kind}.xlsx",
            filetypes=[("Excel", "*.xlsx *.xlsm *.xls"), ("Todos", "*.*")],
        )
        if not path:
            return
        from core import data_source
        from core.services import monitoring as monitoring_service
        try:
            target = data_source.import_file(kind, path)
            monitoring_service.invalidate_cache()
            self.lbl_status.configure(
                text=f"✓  {data_source.label(kind)} importado · {target}",
                text_color=theme.GREEN,
            )
            messagebox.showinfo(
                "Importado",
                f"✓ Archivo importado correctamente.\n\n"
                f"Origen:  {path}\n"
                f"Destino: {target}",
                parent=self,
            )
        except Exception as exc:
            logger.exception("Error importando %s", kind)
            messagebox.showerror("Error", str(exc), parent=self)
        self._reload_data_cards()

    def _link_path(self, kind: str) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title=f"Vincular {kind}.xlsx (ruta externa)",
            filetypes=[("Excel", "*.xlsx *.xlsm *.xls"), ("Todos", "*.*")],
        )
        if not path:
            return
        from core import data_source
        from core.services import monitoring as monitoring_service
        try:
            data_source.set_linked_path(kind, path)
            monitoring_service.invalidate_cache()
            self.lbl_status.configure(
                text=f"✓  {data_source.label(kind)} vinculado · {path}",
                text_color=theme.GREEN,
            )
        except Exception as exc:
            logger.exception("Error vinculando %s", kind)
            messagebox.showerror("Error", str(exc), parent=self)
        self._reload_data_cards()

    def _clear_link(self, kind: str) -> None:
        from core import data_source
        from core.services import monitoring as monitoring_service
        if not messagebox.askyesno(
            "Quitar vínculo",
            f"¿Quitar el vínculo de {data_source.label(kind)}?\n\n"
            "La app volverá a usar la copia local (si existe).",
            parent=self,
        ):
            return
        data_source.clear_link(kind)
        monitoring_service.invalidate_cache()
        self.lbl_status.configure(
            text=f"✓  Vínculo de {data_source.label(kind)} eliminado",
            text_color=theme.TEXT_MUTED,
        )
        self._reload_data_cards()


# ════════════════════════════════════════════════════════════════════════════
#  Diálogos
# ════════════════════════════════════════════════════════════════════════════

class SendExecutiveDialog(ctk.CTkToplevel):
    def __init__(self, master, on_sent=None):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title("Enviar Resumen Monitoring Report")
        self.geometry("560x340")
        self.minsize(440, 280)
        self.transient(master); self.grab_set()
        self._on_sent = on_sent

        ctk.CTkLabel(
            self, text="Enviar a", font=theme.font(10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", padx=22, pady=(18, 4))
        self.ent_to = ctk.CTkEntry(
            self, placeholder_text="email1@eipsa.es, email2@eipsa.es",
            height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_to.pack(fill="x", padx=22, pady=(0, 8))

        ctk.CTkLabel(
            self, text="Copia (Cc)", font=theme.font(10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", padx=22, pady=(8, 4))
        self.ent_cc = ctk.CTkEntry(
            self, placeholder_text="opcional",
            height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_cc.pack(fill="x", padx=22, pady=(0, 8))

        ctk.CTkLabel(
            self, text="Sin To se usa la variable WEEKLY_EXECUTIVE_RECIPIENTS del .env.",
            font=theme.font(10), text_color=theme.TEXT_MUTED,
        ).pack(anchor="w", padx=22, pady=(4, 12))

        self.lbl_status = ctk.CTkLabel(self, text="", font=theme.FONT_BODY,
                                       text_color=theme.TEXT_MUTED, anchor="w")
        self.lbl_status.pack(fill="x", padx=22)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=22, pady=14, side="bottom")
        ctk.CTkButton(
            footer, text="Cancelar", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.BG_CARD, hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))
        self.btn_send = ctk.CTkButton(
            footer, text="Enviar  →", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._send,
        )
        self.btn_send.pack(side="right")

    def _send(self) -> None:
        to = [s.strip() for s in self.ent_to.get().split(",") if s.strip()]
        cc = [s.strip() for s in self.ent_cc.get().split(",") if s.strip()]
        self.btn_send.configure(state="disabled", text="Enviando…")
        self.lbl_status.configure(text="⏳  Enviando…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                res = weekly_service.send_executive_email(to=to or None, cc=cc or None)
                self.after(0, lambda: self._done(res))
            except Exception as exc:
                logger.exception("Error envío ejecutivo")
                err = str(exc)
                self.after(0, lambda: self._error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, res: dict) -> None:
        if res.get("status") == "skipped":
            messagebox.showwarning("No enviado", f"No hay destinatarios configurados.\nIndica al menos un email en 'To'.")
            self.btn_send.configure(state="normal", text="Enviar  →")
            self.lbl_status.configure(text="", text_color=theme.TEXT_MUTED)
            return
        recipients = res.get("recipients", [])
        messagebox.showinfo(
            "Enviado",
            f"✓ Resumen ejecutivo enviado a {len(recipients)} destinatario(s).\n\n"
            f"{', '.join(recipients)}",
        )
        if self._on_sent:
            self._on_sent()
        self.destroy()

    def _error(self, msg: str) -> None:
        self.btn_send.configure(state="normal", text="Enviar  →")
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)
        messagebox.showerror("Error", msg)


class SendPersonalDialog(ctk.CTkToplevel):
    def __init__(self, master, on_sent=None):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title("Enviar Monitoring Report Personal")
        self.geometry("560x420")
        self.minsize(440, 320)
        self.transient(master); self.grab_set()
        self._on_sent = on_sent

        ctk.CTkLabel(
            self, text="A quién enviar", font=theme.font(10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", padx=22, pady=(18, 4))

        self.mode = ctk.StringVar(value="all")
        ctk.CTkRadioButton(
            self, text="Todo el equipo (los que tengan docs asignados)",
            variable=self.mode, value="all",
            font=theme.FONT_BODY, text_color=theme.TEXT_MAIN,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._on_mode_change,
        ).pack(anchor="w", padx=22, pady=2)
        ctk.CTkRadioButton(
            self, text="Solo a usuarios específicos (por iniciales)",
            variable=self.mode, value="filter",
            font=theme.FONT_BODY, text_color=theme.TEXT_MAIN,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._on_mode_change,
        ).pack(anchor="w", padx=22, pady=2)

        self.ent_filter = ctk.CTkEntry(
            self, placeholder_text="JP, AC, JM",
            height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
            state="disabled",
        )
        self.ent_filter.pack(fill="x", padx=46, pady=(0, 8))

        ctk.CTkLabel(
            self, text="Copia adicional (Cc)", font=theme.font(10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", padx=22, pady=(8, 4))
        self.ent_cc = ctk.CTkEntry(
            self, placeholder_text="opcional, se añade a cada email enviado",
            height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_cc.pack(fill="x", padx=22, pady=(0, 8))

        # Lista de iniciales disponibles
        users_label = ", ".join(sorted(USERS.keys()))
        ctk.CTkLabel(
            self, text=f"Iniciales disponibles: {users_label}",
            font=theme.font(10), text_color=theme.TEXT_MUTED,
            anchor="w", justify="left", wraplength=500,
        ).pack(anchor="w", padx=22, pady=(4, 12))

        self.lbl_status = ctk.CTkLabel(self, text="", font=theme.FONT_BODY,
                                       text_color=theme.TEXT_MUTED, anchor="w")
        self.lbl_status.pack(fill="x", padx=22)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=22, pady=14, side="bottom")
        ctk.CTkButton(
            footer, text="Cancelar", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.BG_CARD, hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))
        self.btn_send = ctk.CTkButton(
            footer, text="Enviar  →", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._send,
        )
        self.btn_send.pack(side="right")

    def _on_mode_change(self) -> None:
        if self.mode.get() == "filter":
            self.ent_filter.configure(state="normal")
        else:
            self.ent_filter.configure(state="disabled")

    def _send(self) -> None:
        cc = [s.strip() for s in self.ent_cc.get().split(",") if s.strip()]
        if self.mode.get() == "all":
            user_filter = "all"
        else:
            raw = self.ent_filter.get().strip()
            if not raw:
                messagebox.showwarning("Sin filtro", "Indica iniciales separadas por coma (ej: JP, AC).")
                return
            user_filter = [s.strip().upper() for s in raw.split(",") if s.strip()]

        confirm = messagebox.askyesno(
            "Confirmar envío",
            f"¿Enviar Monitoring Report Personal?\n\n"
            f"Filtro: {user_filter if user_filter != 'all' else 'Todo el equipo'}\n"
            f"Cc: {', '.join(cc) or '—'}\n\n"
            "Solo se enviará a usuarios que tengan documentos asignados.",
        )
        if not confirm:
            return

        self.btn_send.configure(state="disabled", text="Enviando…")
        self.lbl_status.configure(text="⏳  Enviando…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                res = weekly_service.send_personal_emails(to_cc=cc or None, user_filter=user_filter)
                self.after(0, lambda: self._done(res))
            except Exception as exc:
                logger.exception("Error envío personal")
                err = str(exc)
                self.after(0, lambda: self._error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, res: dict) -> None:
        sent_to = res.get("sent_to", [])
        skipped = res.get("skipped", [])
        skipped_line = f"\n\nOmitidos (sin docs): {', '.join(skipped)}" if skipped else ""
        messagebox.showinfo(
            "Enviado",
            f"✓ {len(sent_to)} resumen(es) personal(es) enviado(s).\n\n"
            f"{chr(10).join('  · ' + e for e in sent_to)}"
            f"{skipped_line}",
        )
        if self._on_sent:
            self._on_sent()
        self.destroy()

    def _error(self, msg: str) -> None:
        self.btn_send.configure(state="normal", text="Enviar  →")
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)
        messagebox.showerror("Error", msg)


class EditScheduleDialog(ctk.CTkToplevel):
    def __init__(self, master, sched: dict, on_save=None):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title(f"Editar — {sched['title']}")
        self.geometry("560x560")
        self.minsize(440, 460)
        self.transient(master); self.grab_set()

        self._sched = sched
        self._on_save = on_save

        ctk.CTkLabel(
            self, text=sched["title"],
            font=theme.font(16, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w", padx=22, pady=(18, 2))
        ctk.CTkLabel(
            self, text=sched.get("description") or "",
            font=theme.FONT_BODY, text_color=theme.TEXT_SUB,
            anchor="w", wraplength=500,
        ).pack(anchor="w", padx=22, pady=(0, 14))

        # Frecuencia (read-only de momento)
        schedule = sched.get("schedule") or {}

        # Día de la semana
        ctk.CTkLabel(self, text="Día de la semana",
                     font=theme.font(10, "bold"),
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w", padx=22, pady=(0, 4))
        day_options = list(sched_service.DAY_LABELS.values())
        current_day = sched_service.DAY_LABELS.get(schedule.get("day_of_week", "mon"), "Lunes")
        self.cmb_day = ctk.CTkOptionMenu(
            self, values=day_options, width=180, height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, button_color=theme.BG_INPUT,
            button_hover_color=theme.BG_CARD, text_color=theme.TEXT_MAIN,
            font=theme.FONT_BODY, dropdown_font=theme.FONT_BODY,
        )
        self.cmb_day.set(current_day)
        self.cmb_day.pack(anchor="w", padx=22, pady=(0, 10))

        # Hora
        time_row = ctk.CTkFrame(self, fg_color="transparent")
        time_row.pack(anchor="w", padx=22, fill="x")
        ctk.CTkLabel(time_row, text="Hora",
                     font=theme.font(10, "bold"),
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        sub = ctk.CTkFrame(time_row, fg_color="transparent")
        sub.pack(anchor="w", fill="x", pady=(2, 12))
        self.ent_hour = ctk.CTkEntry(
            sub, height=34, corner_radius=8, width=80,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_hour.insert(0, f"{schedule.get('hour', 8):02d}")
        self.ent_hour.pack(side="left")
        ctk.CTkLabel(sub, text=":", font=theme.FONT_TITLE,
                     text_color=theme.TEXT_MAIN).pack(side="left", padx=4)
        self.ent_min = ctk.CTkEntry(
            sub, height=34, corner_radius=8, width=80,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_min.insert(0, f"{schedule.get('minute', 0):02d}")
        self.ent_min.pack(side="left")

        # Recipients (solo si es executive)
        recipients = sched.get("recipients") or {}
        if sched["type"] == "executive":
            ctk.CTkLabel(self, text="Destinatarios To",
                         font=theme.font(10, "bold"),
                         text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w", padx=22, pady=(0, 4))
            self.ent_to = ctk.CTkEntry(
                self, height=34, corner_radius=8,
                fg_color=theme.BG_INPUT, border_color=theme.BORDER,
                text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
            )
            self.ent_to.insert(0, ", ".join(recipients.get("to") or []))
            self.ent_to.pack(fill="x", padx=22, pady=(0, 8))

            ctk.CTkLabel(self, text="Cc",
                         font=theme.font(10, "bold"),
                         text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w", padx=22, pady=(0, 4))
            self.ent_cc = ctk.CTkEntry(
                self, height=34, corner_radius=8,
                fg_color=theme.BG_INPUT, border_color=theme.BORDER,
                text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
            )
            self.ent_cc.insert(0, ", ".join(recipients.get("cc") or []))
            self.ent_cc.pack(fill="x", padx=22, pady=(0, 12))
            self.ent_filter = None
        else:
            # Personal: filtro de usuarios
            options = sched.get("options") or {}
            uf = options.get("user_filter", "all")
            ctk.CTkLabel(self, text="Filtro de usuarios",
                         font=theme.font(10, "bold"),
                         text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w", padx=22, pady=(0, 4))
            self.ent_filter = ctk.CTkEntry(
                self, placeholder_text="all (todo el equipo) o JP, AC, JM",
                height=34, corner_radius=8,
                fg_color=theme.BG_INPUT, border_color=theme.BORDER,
                text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
            )
            if isinstance(uf, list):
                self.ent_filter.insert(0, ", ".join(uf))
            else:
                self.ent_filter.insert(0, str(uf))
            self.ent_filter.pack(fill="x", padx=22, pady=(0, 8))

            ctk.CTkLabel(self, text="Cc (añadido a cada email)",
                         font=theme.font(10, "bold"),
                         text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w", padx=22, pady=(0, 4))
            self.ent_cc = ctk.CTkEntry(
                self, height=34, corner_radius=8,
                fg_color=theme.BG_INPUT, border_color=theme.BORDER,
                text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
            )
            self.ent_cc.insert(0, ", ".join(recipients.get("cc") or []))
            self.ent_cc.pack(fill="x", padx=22, pady=(0, 12))
            self.ent_to = None

        # Footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=22, pady=14, side="bottom")
        ctk.CTkButton(
            footer, text="Cancelar", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.BG_CARD, hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            footer, text="Guardar", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._save,
        ).pack(side="right")

    def _save(self) -> None:
        try:
            hour = int(self.ent_hour.get())
            minute = int(self.ent_min.get())
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Hora/minuto fuera de rango")
        except ValueError:
            messagebox.showwarning("Hora inválida", "Indica hora (0-23) y minutos (0-59) numéricos.")
            return

        day_label = self.cmb_day.get()
        day_key = sched_service.LABEL_TO_DAY.get(day_label, "mon")

        changes: dict = {
            "schedule": {"day_of_week": day_key, "hour": hour, "minute": minute},
        }
        cc = [s.strip() for s in self.ent_cc.get().split(",") if s.strip()]

        if self.ent_to is not None:  # executive
            to = [s.strip() for s in self.ent_to.get().split(",") if s.strip()]
            changes["recipients"] = {"to": to, "cc": cc}
        else:  # personal
            raw = self.ent_filter.get().strip()
            if not raw or raw.lower() == "all":
                user_filter = "all"
            else:
                user_filter = [s.strip().upper() for s in raw.split(",") if s.strip()]
            changes["recipients"] = {"to": [], "cc": cc}
            changes["options"] = {"user_filter": user_filter}

        sched_service.update_schedule(self._sched["id"], changes)
        if self._on_save:
            self._on_save()
        self.destroy()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_size(path: str) -> str:
    try:
        return _fmt_size_bytes(os.path.getsize(path))
    except Exception:
        return ""


def _fmt_size_bytes(size: int | float) -> str:
    try:
        size = int(size)
        if size < 1024:
            return f"{size} B"
        if size < 1024 ** 2:
            return f"{size / 1024:.1f} KB"
        if size < 1024 ** 3:
            return f"{size / 1024 ** 2:.1f} MB"
        return f"{size / 1024 ** 3:.1f} GB"
    except Exception:
        return ""


def _open_path(path: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception as exc:
        logger.warning("No se pudo abrir %s: %s", path, exc)
