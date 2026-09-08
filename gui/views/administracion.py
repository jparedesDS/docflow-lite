"""Vista Administración — facturas pendientes de cobro y avales en vigor.

  · «Facturas»: las emitidas sin fecha de cobro, de la más antigua a la más
    reciente, con el importe y los días que llevan esperando.
  · «Avales»: los que tienen fecha de vencimiento, los que vencen antes arriba.
    Un aval pasado de fecha sigue generando comisiones: salen en rojo.
"""

import logging
import threading
from datetime import datetime

import customtkinter as ctk
from tkinter import filedialog, messagebox

from core.services import administration as adm
from gui import theme
from gui.widgets import ui
from gui.widgets.table import DataTable

logger = logging.getLogger(__name__)

FACT_COLUMNS = ["Factura", "Pedido", "Cliente", "Emitida", "Importe", "Días"]
AVAL_COLUMNS = ["Pedido", "Cliente", "Vence", "Días", "Importe", "Banco", "Referencia"]

TAB_FACT, TAB_AVAL = "Facturas pendientes", "Avales"


def _fmt(d) -> str:
    return d.strftime("%d-%m-%Y") if d else "—"


class AdministracionView(ctk.CTkFrame):
    def __init__(self, master, on_open_pedido=None, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._on_open_pedido = on_open_pedido
        self._fact: list[dict] = []
        self._avales: list[dict] = []
        self._f_stats: dict = {}
        self._a_stats: dict = {}
        self._build_layout()
        self._reload()

    def _build_layout(self) -> None:
        header = ui.page_header(
            self, "Administración",
            "Facturas emitidas y todavía sin cobrar, y avales bancarios con su vencimiento.",
            icon="€", help_key="administracion")
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
        tab_f = self.tabs.add(TAB_FACT)
        tab_a = self.tabs.add(TAB_AVAL)

        self.table_f = DataTable(tab_f, columns=FACT_COLUMNS,
                                 on_double_click=lambda _e=None: self._open(self.table_f, self._fact))
        self.table_f.pack(fill="both", expand=True, pady=(theme.SPACE_2, 0))
        self.table_f.set_columns_width({"Factura": 110, "Pedido": 140, "Cliente": 280,
                                        "Emitida": 110, "Importe": 120, "Días": 80})
        self.table_f.set_columns_anchor({"Factura": "w", "Pedido": "w", "Cliente": "w",
                                         "Emitida": "center", "Importe": "e", "Días": "center"})
        self.table_f.tree.tag_configure("vieja", foreground=theme.RED)
        self.table_f.tree.tag_configure("media", foreground=theme.AMBER)
        self.table_f.set_context_menu(lambda i, c: self._ctx(self.table_f, self._fact))

        self.table_a = DataTable(tab_a, columns=AVAL_COLUMNS,
                                 on_double_click=lambda _e=None: self._open(self.table_a, self._avales))
        self.table_a.pack(fill="both", expand=True, pady=(theme.SPACE_2, 0))
        self.table_a.set_columns_width({"Pedido": 150, "Cliente": 220, "Vence": 110, "Días": 80,
                                        "Importe": 120, "Banco": 130, "Referencia": 200})
        self.table_a.set_columns_anchor({"Pedido": "w", "Cliente": "w", "Vence": "center",
                                         "Días": "center", "Importe": "e", "Banco": "w",
                                         "Referencia": "w"})
        self.table_a.tree.tag_configure("vencido", foreground=theme.RED)
        self.table_a.tree.tag_configure("pronto", foreground=theme.AMBER)
        self.table_a.set_context_menu(lambda i, c: self._ctx(self.table_a, self._avales))

    # ── Datos ─────────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        self.lbl_status.configure(text="⏳  Consultando el ERP…", text_color=theme.TEXT_MUTED)
        self.btn_reload.configure(state="disabled")

        def worker():
            try:
                data = (adm.unpaid(), adm.invoice_stats(), adm.bonds(), adm.bond_stats())
                self.after(0, lambda: self._render(*data))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Administración: error consultando el ERP")
                msg = str(exc)
                self.after(0, lambda: self._error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _hard_refresh(self) -> None:
        adm.invalidate_cache()
        self._reload()

    def _error(self, msg: str) -> None:
        self.btn_reload.configure(state="normal")
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)

    def _render(self, fact, f_st, avales, a_st) -> None:
        self._fact, self._f_stats = fact, f_st
        self._avales, self._a_stats = avales, a_st
        self.btn_reload.configure(state="normal")
        if not adm.is_available():
            self.lbl_status.configure(text="✗  El ERP no responde: ábrelo y pulsa ↻.",
                                      text_color=theme.AMBER)
            self.table_f.clear(); self.table_a.clear()
            return
        self.lbl_status.configure(
            text=f"{f_st['pendientes']} facturas sin cobrar · {a_st['total']} avales · "
                 f"datos del ERP a {datetime.now():%d-%m-%Y %H:%M}", text_color=theme.TEXT_MUTED)
        self._fill_fact()
        self._fill_avales()
        self._kpis()

    def _kpis(self) -> None:
        for w in self.kpi_row.winfo_children():
            w.destroy()
        if self.tabs.get() == TAB_AVAL:
            st = self._a_stats
            cards = [
                ("Vencidos", st["vencidos"], theme.RED if st["vencidos"] else theme.GREEN,
                 "pasados de fecha, siguen costando"),
                ("Vencen en 90 días", st["pronto"], theme.AMBER, "conviene ir cancelándolos"),
                ("Importe en vigor", adm.euros(st["importe"]), theme.ACCENT,
                 f"en {st['bancos']} banco(s)"),
                ("Avales", st["total"], theme.BLUE, "con fecha de vencimiento"),
            ]
        else:
            st = self._f_stats
            cards = [
                ("Sin cobrar", st["pendientes"], theme.AMBER if st["pendientes"] else theme.GREEN,
                 f"de {st['facturas']} facturas"),
                ("Importe pendiente", adm.euros(st["importe_pendiente"]), theme.RED,
                 "suma de lo no cobrado"),
                ("La más antigua", f"{st['mas_antigua']} d", theme.RED, "desde que se emitió"),
                ("Clientes", st["clientes"], theme.BLUE, "con algo pendiente"),
            ]
        for col, (label, value, color, sub) in enumerate(cards):
            ui.kpi_card(self.kpi_row, label, value, color, sub).grid(
                row=0, column=col, sticky="ew", padx=(0 if col == 0 else theme.SPACE_2, 0))

    def _on_tab(self) -> None:
        if self._f_stats:
            self._kpis()

    def _fill_fact(self) -> None:
        self.table_f.clear()
        for i, f in enumerate(self._fact):
            tag = "vieja" if f["dias"] > 365 else ("media" if f["dias"] > 90 else "")
            self.table_f.add_row(
                values=[f["numero"], f["pedido_raw"] or "—", f["cliente"] or "—",
                        _fmt(f["emitida"]), adm.euros(f["importe"]), f["dias"]],
                iid=str(i), tags=(tag,) if tag else ())
        self.after(60, self.table_f.autofit_columns)

    def _fill_avales(self) -> None:
        self.table_a.clear()
        for i, a in enumerate(self._avales):
            tag = "vencido" if a["vencido"] else ("pronto" if a["pronto"] else "")
            self.table_a.add_row(
                values=[a["pedido"], a["cliente"] or "—", _fmt(a["vence"]),
                        a["dias"] if a["dias"] is not None else "—",
                        adm.euros(a["importe"]), a["banco"] or "—", a["referencia"] or "—"],
                iid=str(i), tags=(tag,) if tag else ())
        self.after(60, self.table_a.autofit_columns)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _row(self, table: DataTable, rows: list[dict]) -> dict | None:
        iid = table.selected_iid()
        return rows[int(iid)] if iid and iid.isdigit() and int(iid) < len(rows) else None

    def _open(self, table: DataTable, rows: list[dict]) -> None:
        r = self._row(table, rows)
        if r and self._on_open_pedido:
            pedido = r.get("pedido") or ""
            if pedido:
                self._on_open_pedido(pedido)

    def _ctx(self, table: DataTable, rows: list[dict]):
        r = self._row(table, rows)
        if not r:
            return None
        items = []
        if r.get("pedido") and self._on_open_pedido:
            items.append((f"▦  Abrir {r['pedido']} en Pedidos",
                          lambda: self._on_open_pedido(r["pedido"])))
        if r.get("numero"):
            items.append((f"Copiar nº de factura ({r['numero']})",
                          lambda: table.copy_to_clipboard(r["numero"])))
        if r.get("referencia"):
            items.append(("Copiar referencia del aval",
                          lambda: table.copy_to_clipboard(r["referencia"])))
        return items or None

    def _export(self) -> None:
        aval_tab = self.tabs.get() == TAB_AVAL
        rows = self._avales if aval_tab else self._fact
        if not rows:
            ui.toast(self, "Administración", "No hay filas que exportar.", kind="info")
            return
        nombre = "avales" if aval_tab else "facturas_pendientes"
        path = filedialog.asksaveasfilename(
            parent=self, title="Exportar a Excel", defaultextension=".xlsx",
            initialfile=f"{nombre}_{datetime.now():%Y%m%d}.xlsx", filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            adm.export_excel(rows, path, kind="avales" if aval_tab else "facturas")
            ui.toast(self, "Exportado", f"{len(rows)} fila(s) a Excel.", kind="success")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Exportar", f"No se pudo exportar:\n{exc}", parent=self)
