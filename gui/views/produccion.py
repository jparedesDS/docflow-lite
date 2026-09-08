"""Vista Producción — qué hay en el taller y en qué se van las horas.

  · «En taller»: pedidos abiertos con su avance y su fecha prevista, los más
    retrasados arriba. Los pedidos que arrastran más de año y medio (quedaron
    sin cerrar en el ERP) se ocultan salvo que se pidan.
  · «Horas»: horas imputadas por pedido y por operación. Ojo, la imputación se
    hace por OT y una OT cubre varios equipos: el reparto lo resuelve el
    servicio, aquí solo se pinta.
"""

import logging
import threading
from datetime import datetime

import customtkinter as ctk
from tkinter import filedialog, messagebox

from core.services import production
from gui import theme
from gui.widgets import ui
from gui.widgets.table import DataTable

logger = logging.getLogger(__name__)

TALLER_COLUMNS = ["Pedido", "Cliente", "Equipo", "Taller", "Montaje", "Prevista", "Retraso", "Observaciones"]
HORAS_COLUMNS = ["Pedido", "Horas", "OTs", "Apuntes", "Última imputación"]

TAB_TALLER, TAB_HORAS = "En taller", "Horas de taller"


def _fmt(d) -> str:
    return d.strftime("%d-%m-%Y") if d else "—"


class ProduccionView(ctk.CTkFrame):
    def __init__(self, master, on_open_pedido=None, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._on_open_pedido = on_open_pedido
        self._rows: list[dict] = []
        self._horas: dict = {}
        self._stats: dict = {}
        self._include_old = False
        self._build_layout()
        self._reload()

    def _build_layout(self) -> None:
        header = ui.page_header(
            self, "Producción",
            "Pedidos en fabricación con su avance, y las horas que lleva cada uno.",
            icon="⚙", help_key="produccion")
        self.btn_export = ui.button(header.actions, "⤓  Excel", "outline", size="sm", width=90,
                                    text_color=theme.TEXT_SUB, command=self._export)
        self.btn_export.pack(side="right", padx=(theme.SPACE_2, 0))
        self.btn_reload = ui.button(header.actions, "↻", "outline", size="sm", width=36,
                                    text_color=theme.TEXT_SUB, command=self._hard_refresh)
        self.btn_reload.pack(side="right")

        self.lbl_status = ctk.CTkLabel(self, text="", font=theme.FONT_SMALL,
                                       text_color=theme.TEXT_MUTED, anchor="w")
        self.lbl_status.pack(fill="x", padx=theme.SPACE_6)

        self.kpi_row = ctk.CTkFrame(self, fg_color="transparent")
        self.kpi_row.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_3, theme.SPACE_2))
        for c in range(4):
            self.kpi_row.grid_columnconfigure(c, weight=1, uniform="kpi")

        self.tabs = ui.tabview(self, command=self._on_tab)
        self.tabs.pack(fill="both", expand=True, padx=theme.SPACE_6, pady=(0, theme.SPACE_5))
        tab_t = self.tabs.add(TAB_TALLER)
        tab_h = self.tabs.add(TAB_HORAS)

        bar = ctk.CTkFrame(tab_t, fg_color="transparent")
        bar.pack(fill="x", pady=(theme.SPACE_2, 0))
        self.var_old = ctk.BooleanVar(value=False)
        self.chk_old = ctk.CTkCheckBox(bar, text="Incluir pedidos antiguos sin cerrar",
                                       variable=self.var_old, font=theme.FONT_SMALL,
                                       text_color=theme.TEXT_SUB, fg_color=theme.ACCENT,
                                       hover_color=theme.ACCENT_HOVER, command=self._toggle_old)
        self.chk_old.pack(side="left")

        self.table = DataTable(tab_t, columns=TALLER_COLUMNS,
                               on_double_click=lambda _e=None: self._open_selected())
        self.table.pack(fill="both", expand=True, pady=(theme.SPACE_2, 0))
        self.table.set_columns_width({"Pedido": 130, "Cliente": 200, "Equipo": 150, "Taller": 70,
                                      "Montaje": 80, "Prevista": 110, "Retraso": 90,
                                      "Observaciones": 260})
        self.table.set_columns_anchor({"Pedido": "w", "Cliente": "w", "Equipo": "w",
                                       "Taller": "center", "Montaje": "center",
                                       "Prevista": "center", "Retraso": "center",
                                       "Observaciones": "w"})
        self.table.tree.tag_configure("tarde", foreground=theme.RED)
        self.table.tree.tag_configure("curso", foreground=theme.GREEN)
        self.table.tree.tag_configure("viejo", foreground=theme.TEXT_MUTED)
        self.table.set_context_menu(self._ctx_menu)

        self.ops_box = ctk.CTkFrame(tab_h, fg_color=theme.BG_CARD, corner_radius=12,
                                    border_width=1, border_color=theme.BORDER)
        self.ops_box.pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_2))
        self.table_h = DataTable(tab_h, columns=HORAS_COLUMNS,
                                 on_double_click=lambda _e=None: self._open_selected_h())
        self.table_h.pack(fill="both", expand=True)
        self.table_h.set_columns_width({"Pedido": 150, "Horas": 100, "OTs": 80,
                                        "Apuntes": 90, "Última imputación": 150})
        self.table_h.set_columns_anchor({"Pedido": "w", "Horas": "center", "OTs": "center",
                                         "Apuntes": "center", "Última imputación": "center"})

    # ── Datos ─────────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        self.lbl_status.configure(text="⏳  Consultando el ERP…", text_color=theme.TEXT_MUTED)
        self.btn_reload.configure(state="disabled")

        def worker():
            try:
                data = (production.workshop(), production.workshop_stats(), production.hours())
                self.after(0, lambda: self._render(*data))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Producción: error consultando el ERP")
                msg = str(exc)
                self.after(0, lambda: self._error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _hard_refresh(self) -> None:
        production.invalidate_cache()
        self._reload()

    def _error(self, msg: str) -> None:
        self.btn_reload.configure(state="normal")
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)

    def _render(self, rows, st, horas) -> None:
        self._rows, self._stats, self._horas = rows, st, horas
        self.btn_reload.configure(state="normal")
        if not production.is_available():
            self.lbl_status.configure(text="✗  El ERP no responde: ábrelo y pulsa ↻.",
                                      text_color=theme.AMBER)
            self.table.clear(); self.table_h.clear()
            return
        ultima = horas.get("ultima")
        self.lbl_status.configure(
            text=f"{st['abiertos']} pedidos en curso · última imputación de horas "
                 f"{_fmt(ultima)} · datos del ERP a {datetime.now():%d-%m-%Y %H:%M}",
            text_color=theme.TEXT_MUTED)
        if st.get("antiguos"):
            self.chk_old.configure(text=f"Incluir {st['antiguos']} pedidos antiguos sin cerrar")
        self._fill()
        self._fill_horas()
        self._kpis()

    def _kpis(self) -> None:
        for w in self.kpi_row.winfo_children():
            w.destroy()
        if self.tabs.get() == TAB_HORAS:
            h = self._horas
            n_ped = len(h.get("por_pedido", []))
            cards = [
                ("Horas imputadas", f"{h.get('total', 0):,.0f}".replace(",", "."), theme.ACCENT,
                 "en los últimos 2 años"),
                ("Repartidas a pedido", f"{h.get('imputadas', 0):,.0f}".replace(",", "."), theme.GREEN,
                 f"{n_ped} pedidos"),
                ("Última imputación", _fmt(h.get("ultima")), theme.AMBER, "en el parte de taller"),
                ("Operaciones", len(h.get("por_operacion", [])), theme.BLUE, "con horas cargadas"),
            ]
        else:
            st = self._stats
            cards = [
                ("En curso", st["en_curso"], theme.GREEN, f"de {st['abiertos']} pedidos abiertos"),
                ("Sin empezar", st["sin_empezar"], theme.TEXT_SUB, "todavía al 0 %"),
                ("Con retraso", st["retrasados"], theme.RED if st["retrasados"] else theme.GREEN,
                 f"hasta {st['retraso_max']} días"),
                ("Antiguos", st.get("antiguos", 0), theme.AMBER,
                 "sin cerrar en el ERP, ocultos"),
            ]
        for col, (label, value, color, sub) in enumerate(cards):
            ui.kpi_card(self.kpi_row, label, value, color, sub).grid(
                row=0, column=col, sticky="ew", padx=(0 if col == 0 else theme.SPACE_2, 0))

    def _on_tab(self) -> None:
        if self._stats:
            self._kpis()

    def _toggle_old(self) -> None:
        self._include_old = bool(self.var_old.get())
        self._fill()

    def _visible(self) -> list[dict]:
        return [r for r in self._rows if self._include_old or not r["antiguo"]]

    def _fill(self) -> None:
        self.table.clear()
        for i, r in enumerate(self._visible()):
            if r["antiguo"]:
                tag = "viejo"
            elif r["retraso"] > 0:
                tag = "tarde"
            elif r["en_curso"]:
                tag = "curso"
            else:
                tag = ""
            self.table.add_row(
                values=[r["pedido_raw"], r["cliente"] or "—", r["equipo"] or "—",
                        f"{r['taller']} %", f"{r['montaje']} %", _fmt(r["prevista"]),
                        f"{r['retraso']} d" if r["retraso"] else "—", r["obs"] or ""],
                iid=str(i), tags=(tag,) if tag else ())
        self.after(60, self.table.autofit_columns)

    def _fill_horas(self) -> None:
        for w in self.ops_box.winfo_children():
            w.destroy()
        ops = self._horas.get("por_operacion", [])
        inner = ctk.CTkFrame(self.ops_box, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_3)
        ui.section_header(inner, "En qué se van las horas").pack(fill="x", pady=(0, theme.SPACE_2))
        total = sum(o["horas"] for o in ops) or 1
        for o in ops[:8]:
            ui.bar_row(inner, o["operacion"][:34], o["horas"], o["horas"] / total, theme.ACCENT,
                       value_text=f"{o['horas']:,.0f} h".replace(",", "."))
        self.table_h.clear()
        for i, a in enumerate(self._horas.get("por_pedido", [])):
            self.table_h.add_row(
                values=[a["pedido"], f"{a['horas']:,.1f}".replace(",", "."), a["ots"],
                        a["apuntes"], _fmt(a["ultima"])],
                iid=str(i))
        self.after(60, self.table_h.autofit_columns)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _selected(self) -> dict | None:
        iid = self.table.selected_iid()
        rows = self._visible()
        return rows[int(iid)] if iid and iid.isdigit() and int(iid) < len(rows) else None

    def _open_selected(self) -> None:
        r = self._selected()
        if r and self._on_open_pedido:
            self._on_open_pedido(r["pedido"])

    def _open_selected_h(self) -> None:
        iid = self.table_h.selected_iid()
        rows = self._horas.get("por_pedido", [])
        if iid and iid.isdigit() and int(iid) < len(rows) and self._on_open_pedido:
            self._on_open_pedido(rows[int(iid)]["pedido"])

    def _ctx_menu(self, iid: str, _col: int):
        r = self._selected()
        if not r:
            return None
        items = []
        if self._on_open_pedido:
            items.append((f"▦  Abrir {r['pedido']} en Pedidos",
                          lambda: self._on_open_pedido(r["pedido"])))
        items.append(("Copiar Nº de pedido", lambda: self.table.copy_to_clipboard(r["pedido_raw"])))
        if r["obs"]:
            items.append(("Copiar observaciones", lambda: self.table.copy_to_clipboard(r["obs"])))
        return items

    def _export(self) -> None:
        horas_tab = self.tabs.get() == TAB_HORAS
        rows = self._horas.get("por_pedido", []) if horas_tab else self._visible()
        if not rows:
            ui.toast(self, "Producción", "No hay filas que exportar.", kind="info")
            return
        nombre = "horas_taller" if horas_tab else "taller"
        path = filedialog.asksaveasfilename(
            parent=self, title="Exportar a Excel", defaultextension=".xlsx",
            initialfile=f"{nombre}_{datetime.now():%Y%m%d}.xlsx", filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            production.export_excel(rows, path, kind="horas" if horas_tab else "taller")
            ui.toast(self, "Exportado", f"{len(rows)} fila(s) a Excel.", kind="success")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Exportar", f"No se pudo exportar:\n{exc}", parent=self)
