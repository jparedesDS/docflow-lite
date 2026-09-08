"""Vista Almacén — cuánto espera el material desde que está listo hasta que sale.

Dos pestañas:
  · «En almacén ahora»: lo avisado y todavía sin enviar, lo más viejo arriba.
    Es la lista accionable: a quién hay que reclamar la salida.
  · «Histórico»: los envíos ya hechos, con el reparto de tiempos de espera.

Los datos salen del ERP (`core.services.warehouse`). Doble clic en un pedido lo
abre en Pedidos.
"""

import logging
import threading
from datetime import datetime

import customtkinter as ctk
from tkinter import filedialog, messagebox

from core.services import warehouse
from gui import theme
from gui.widgets import ui
from gui.widgets.table import DataTable

logger = logging.getLogger(__name__)

STOCK_COLUMNS = ["Pedido", "Cliente", "Equipo", "Aviso de entrega", "Días esperando", "Cerrado"]
SHIPPED_COLUMNS = ["Pedido", "Cliente", "Equipo", "Aviso", "Envío", "Días", "Transporte"]

_SEV_COLOR = {"ok": theme.GREEN, "warn": theme.AMBER, "bad": theme.RED}


def _fmt(d) -> str:
    return d.strftime("%d-%m-%Y") if d else "—"


class AlmacenView(ctk.CTkFrame):
    def __init__(self, master, on_open_pedido=None, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._on_open_pedido = on_open_pedido
        self._snap: dict = {}
        self._build_layout()
        self._reload()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        header = ui.page_header(
            self, "Almacén",
            "Material terminado y avisado al cliente: cuánto lleva esperando la salida "
            "y cuánto tardó en salir lo ya enviado.",
            icon="📦", help_key="almacen")

        self.btn_export = ui.button(header.actions, "⤓  Excel", "outline", size="sm", width=90,
                                    text_color=theme.TEXT_SUB, command=self._export)
        self.btn_export.pack(side="right", padx=(theme.SPACE_2, 0))
        self.btn_reload = ui.button(header.actions, "↻", "outline", size="sm", width=36,
                                    text_color=theme.TEXT_SUB, command=self._hard_refresh)
        self.btn_reload.pack(side="right")

        self.lbl_status = ctk.CTkLabel(self, text="", font=theme.FONT_SMALL,
                                       text_color=theme.TEXT_MUTED, anchor="w")
        self.lbl_status.pack(fill="x", padx=theme.SPACE_6)

        # KPIs
        self.kpi_row = ctk.CTkFrame(self, fg_color="transparent")
        self.kpi_row.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_3, theme.SPACE_2))
        for c in range(4):
            self.kpi_row.grid_columnconfigure(c, weight=1, uniform="kpi")

        # Pestañas
        self.tabs = ui.tabview(self)
        self.tabs.pack(fill="both", expand=True, padx=theme.SPACE_6, pady=(0, theme.SPACE_5))
        self.tab_stock = self.tabs.add("En almacén ahora")
        self.tab_hist = self.tabs.add("Histórico de envíos")

        self.table_stock = DataTable(self.tab_stock, columns=STOCK_COLUMNS,
                                     on_double_click=lambda _e=None: self._open_selected(self.table_stock))
        self.table_stock.pack(fill="both", expand=True, pady=(theme.SPACE_2, 0))
        self.table_stock.set_columns_width({"Pedido": 150, "Cliente": 260, "Equipo": 170,
                                            "Aviso de entrega": 130, "Días esperando": 120, "Cerrado": 90})
        self.table_stock.set_columns_anchor({"Pedido": "w", "Cliente": "w", "Equipo": "w",
                                             "Aviso de entrega": "center", "Días esperando": "center",
                                             "Cerrado": "center"})
        self.table_stock.set_context_menu(lambda iid, col: self._ctx_menu(self.table_stock, iid))

        # Histórico: reparto arriba, tabla debajo
        self.hist_box = ctk.CTkFrame(self.tab_hist, fg_color=theme.BG_CARD, corner_radius=12,
                                     border_width=1, border_color=theme.BORDER)
        self.hist_box.pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_2))
        self.table_hist = DataTable(self.tab_hist, columns=SHIPPED_COLUMNS,
                                    on_double_click=lambda _e=None: self._open_selected(self.table_hist))
        self.table_hist.pack(fill="both", expand=True)
        self.table_hist.set_columns_width({"Pedido": 150, "Cliente": 240, "Equipo": 160,
                                           "Aviso": 110, "Envío": 110, "Días": 70, "Transporte": 130})
        self.table_hist.set_columns_anchor({"Pedido": "w", "Cliente": "w", "Equipo": "w",
                                            "Aviso": "center", "Envío": "center", "Días": "center",
                                            "Transporte": "center"})
        self.table_hist.set_context_menu(lambda iid, col: self._ctx_menu(self.table_hist, iid))

        for table in (self.table_stock, self.table_hist):
            for sev, color in _SEV_COLOR.items():
                table.tree.tag_configure(f"sev_{sev}", foreground=color)

    # ── Datos ─────────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        self.lbl_status.configure(text="⏳  Consultando el ERP…", text_color=theme.TEXT_MUTED)
        self.btn_reload.configure(state="disabled")

        def worker():
            try:
                snap = warehouse.snapshot()
                self.after(0, lambda: self._render(snap))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Almacén: error consultando el ERP")
                msg = str(exc)
                self.after(0, lambda: self._render_error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _hard_refresh(self) -> None:
        warehouse.invalidate_cache()
        self._reload()

    def _render_error(self, msg: str) -> None:
        self.btn_reload.configure(state="normal")
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)

    def _render(self, snap: dict) -> None:
        self._snap = snap
        self.btn_reload.configure(state="normal")

        if not snap.get("available"):
            self.lbl_status.configure(
                text="✗  El ERP no responde: abre el programa del ERP y pulsa ↻.",
                text_color=theme.AMBER)
            self._render_kpis({})
            self.table_stock.clear()
            self.table_hist.clear()
            return

        st = snap["stats"]
        self.lbl_status.configure(
            text=f"✓  {st['en_almacen']} pedido(s) esperando salida  ·  "
                 f"{st['enviados']} envíos analizados  ·  "
                 f"datos del ERP a {datetime.now():%d-%m-%Y %H:%M}",
            text_color=theme.TEXT_MUTED)
        self._render_kpis(st)
        self._render_stock(snap["stock"])
        self._render_hist(snap["shipped"], snap["buckets"], st)

    def _render_kpis(self, st: dict) -> None:
        for w in self.kpi_row.winfo_children():
            w.destroy()
        if not st:
            return
        atascados = st.get("atascados", 0)
        cards = [
            ("En almacén", st["en_almacen"], theme.ACCENT, "pedidos esperando salida"),
            ("Espera más larga", f"{st['dias_max']} d",
             _SEV_COLOR[warehouse.severity(st["dias_max"])] if st["dias_max"] else theme.TEXT_SUB,
             st["pedido_max"] or "—"),
            ("Más de 30 días", atascados, theme.RED if atascados else theme.GREEN,
             "conviene reclamar la salida" if atascados else "nada atascado"),
            ("Mediana de espera", f"{st['mediana']} d", theme.GREEN,
             f"{st['pct_semana']}% sale en menos de una semana"),
        ]
        for col, (label, value, color, sub) in enumerate(cards):
            card = ui.kpi_card(self.kpi_row, label, value, color, sub)
            card.grid(row=0, column=col, sticky="ew",
                      padx=(0 if col == 0 else theme.SPACE_2, 0))

    def _render_stock(self, stock: list[dict]) -> None:
        self.table_stock.clear()
        for child in list(self.tab_stock.winfo_children()):
            if getattr(child, "_empty_state", False):
                child.destroy()
        if not stock:
            box = ui.empty_state(self.tab_stock, "No hay material esperando salida",
                                 "Todo lo avisado al cliente ya se ha enviado.", icon="📦")
            box._empty_state = True
            return
        for r in stock:
            self.table_stock.add_row(
                values=[r["pedido"], r["cliente"] or "—", r["equipo"] or "—",
                        _fmt(r["aviso"]), f"{r['dias']} d", r["cerrado"] or ""],
                iid=r["pedido"],
                tags=(f"sev_{warehouse.severity(r['dias'])}",))
        self.after(60, self.table_stock.autofit_columns)

    def _render_hist(self, shipped: list[dict], buckets: list, st: dict) -> None:
        for w in self.hist_box.winfo_children():
            w.destroy()
        inner = ctk.CTkFrame(self.hist_box, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_3)
        ui.section_header(inner, "Cuánto tarda en salir el material").pack(
            fill="x", pady=(0, theme.SPACE_2))
        total = sum(n for _, n in buckets) or 1
        for label, n in buckets:
            color = theme.GREEN if label in ("Mismo día", "1-7 días") else (
                theme.AMBER if label in ("8-15 días", "16-30 días") else theme.RED)
            ui.bar_row(inner, label, n, n / total, color, value_text=f"{n}  ({100*n/total:.0f}%)")
        if st.get("enviados_30d"):
            ctk.CTkLabel(inner,
                         text=f"Últimos 30 días: {st['enviados_30d']} envíos, "
                              f"mediana de {st['mediana_30d']} días en almacén.",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_SUB, anchor="w").pack(
                anchor="w", pady=(theme.SPACE_2, 0))

        self.table_hist.clear()
        for r in shipped:
            self.table_hist.add_row(
                values=[r["pedido"], r["cliente"] or "—", r["equipo"] or "—",
                        _fmt(r["aviso"]), _fmt(r["envio"]), f"{r['dias']} d",
                        r["transporte"] or "—"],
                iid=r["pedido"],
                tags=(f"sev_{warehouse.severity(r['dias'])}",))
        self.after(60, self.table_hist.autofit_columns)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _rows(self) -> list[dict]:
        """Filas de la pestaña activa (para exportar)."""
        if self.tabs.get() == "En almacén ahora":
            return self._snap.get("stock", [])
        return self._snap.get("shipped", [])

    def _open_selected(self, table: DataTable) -> None:
        iid = table.selected_iid()
        if iid and self._on_open_pedido:
            self._on_open_pedido(iid)

    def _ctx_menu(self, table: DataTable, iid: str):
        if not iid:
            return None
        items = [("Copiar Nº de pedido", lambda: table.copy_to_clipboard(iid))]
        if self._on_open_pedido:
            items.insert(0, ("▦  Abrir en Pedidos", lambda: self._on_open_pedido(iid)))
        return items

    def _export(self) -> None:
        rows = self._rows()
        if not rows:
            ui.toast(self, "Almacén", "No hay filas que exportar.", kind="info")
            return
        nombre = "almacen_espera" if self.tabs.get() == "En almacén ahora" else "almacen_historico"
        path = filedialog.asksaveasfilename(
            parent=self, title="Exportar a Excel", defaultextension=".xlsx",
            initialfile=f"{nombre}_{datetime.now():%Y%m%d}.xlsx",
            filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            warehouse.export_excel(rows, path)
            ui.toast(self, "Exportado", f"{len(rows)} fila(s) a Excel.", kind="success")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Exportar", f"No se pudo exportar:\n{exc}", parent=self)
