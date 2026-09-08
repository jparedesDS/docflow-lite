"""Vista Compras — material pedido a proveedor que todavía no ha llegado.

Es la respuesta a «¿por qué va tarde este pedido?»: qué falta, de qué proveedor,
para cuándo lo prometió y cuántos días lleva de retraso. Doble clic en una línea
abre el pedido afectado en Seguimiento.
"""

import logging
import threading
from datetime import datetime

import customtkinter as ctk
from tkinter import filedialog, messagebox

from core.services import purchases
from gui import theme
from gui.widgets import ui
from gui.widgets.table import DataTable

logger = logging.getLogger(__name__)

COLUMNS = ["Pedido", "Proveedor", "Material", "Pendiente", "Prometido", "Retraso"]


def _fmt(d) -> str:
    return d.strftime("%d-%m-%Y") if d else "—"


def _qty(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


class ComprasView(ctk.CTkFrame):
    def __init__(self, master, on_open_pedido=None, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._on_open_pedido = on_open_pedido
        self._rows: list[dict] = []
        self._only_late = False
        self._build_layout()
        self._reload()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        header = ui.page_header(
            self, "Compras",
            "Material pedido a proveedor y todavía no recibido: para qué pedido es, "
            "quién lo sirve y cuánto lleva de retraso.",
            icon="🛒", help_key="compras")

        self.btn_export = ui.button(header.actions, "⤓  Excel", "outline", size="sm", width=90,
                                    text_color=theme.TEXT_SUB, command=self._export)
        self.btn_export.pack(side="right", padx=(theme.SPACE_2, 0))
        self.btn_reload = ui.button(header.actions, "↻", "outline", size="sm", width=36,
                                    text_color=theme.TEXT_SUB, command=self._hard_refresh)
        self.btn_reload.pack(side="right")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_2, 0))
        self.var_late = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(bar, text="Solo lo que va con retraso", variable=self.var_late,
                        font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                        fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                        command=self._toggle_late).pack(side="left")
        self.lbl_status = ctk.CTkLabel(bar, text="", font=theme.FONT_SMALL,
                                       text_color=theme.TEXT_MUTED, anchor="e")
        self.lbl_status.pack(side="right")

        self.kpi_row = ctk.CTkFrame(self, fg_color="transparent")
        self.kpi_row.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_3, theme.SPACE_2))
        for c in range(4):
            self.kpi_row.grid_columnconfigure(c, weight=1, uniform="kpi")

        self.table = DataTable(self, columns=COLUMNS, on_double_click=lambda _e=None: self._open_selected())
        self.table.pack(fill="both", expand=True, padx=theme.SPACE_6, pady=(0, theme.SPACE_5))
        self.table.set_columns_width({"Pedido": 120, "Proveedor": 220, "Material": 320,
                                      "Pendiente": 90, "Prometido": 110, "Retraso": 90})
        self.table.set_columns_anchor({"Pedido": "w", "Proveedor": "w", "Material": "w",
                                       "Pendiente": "center", "Prometido": "center", "Retraso": "center"})
        self.table.tree.tag_configure("late", foreground=theme.RED)
        self.table.tree.tag_configure("soon", foreground=theme.AMBER)
        self.table.set_context_menu(self._ctx_menu)

    # ── Datos ─────────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        self.lbl_status.configure(text="⏳  Consultando el ERP…", text_color=theme.TEXT_MUTED)
        self.btn_reload.configure(state="disabled")

        def worker():
            try:
                rows, st = purchases.pending(), purchases.stats()
                self.after(0, lambda: self._render(rows, st))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Compras: error consultando el ERP")
                msg = str(exc)
                self.after(0, lambda: self._error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _hard_refresh(self) -> None:
        purchases.invalidate_cache()
        self._reload()

    def _error(self, msg: str) -> None:
        self.btn_reload.configure(state="normal")
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)

    def _toggle_late(self) -> None:
        self._only_late = bool(self.var_late.get())
        self._fill()

    def _render(self, rows: list[dict], st: dict) -> None:
        self._rows = rows
        self.btn_reload.configure(state="normal")
        for w in self.kpi_row.winfo_children():
            w.destroy()

        if not purchases.is_available():
            self.lbl_status.configure(text="✗  El ERP no responde: ábrelo y pulsa ↻.",
                                      text_color=theme.AMBER)
            self.table.clear()
            return

        self.lbl_status.configure(
            text=f"datos del ERP a {datetime.now():%d-%m-%Y %H:%M}", text_color=theme.TEXT_MUTED)
        cards = [
            ("Líneas pendientes", st["lineas"], theme.ACCENT, f"de {st['proveedores']} proveedor(es)"),
            ("Con retraso", st["retrasadas"], theme.RED if st["retrasadas"] else theme.GREEN,
             f"hasta {st['retraso_max']} días" if st["retraso_max"] else "ninguna"),
            ("Llegan en 30 días", st["pronto"], theme.AMBER, "según lo prometido"),
            ("Pedidos afectados", st["pedidos"], theme.BLUE, "con material pendiente"),
        ]
        for col, (label, value, color, sub) in enumerate(cards):
            ui.kpi_card(self.kpi_row, label, value, color, sub).grid(
                row=0, column=col, sticky="ew", padx=(0 if col == 0 else theme.SPACE_2, 0))
        self._fill()

    def _visible(self) -> list[dict]:
        return [r for r in self._rows if r["retraso"] > 0] if self._only_late else self._rows

    def _fill(self) -> None:
        self.table.clear()
        rows = self._visible()
        for i, r in enumerate(rows):
            tag = ()
            if r["retraso"] > 0:
                tag = ("late",)
            elif r["prometido"] and (r["prometido"] - datetime.now().date()).days <= purchases.SOON_DAYS:
                tag = ("soon",)
            self.table.add_row(
                values=[r["pedido"] or (r["para"][:18] or "—"), r["proveedor"] or "—",
                        r["material"] or "—", _qty(r["pendiente"]), _fmt(r["prometido"]),
                        f"{r['retraso']} d" if r["retraso"] else "—"],
                iid=str(i), tags=tag)
        self.after(60, self.table.autofit_columns)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _selected(self) -> dict | None:
        iid = self.table.selected_iid()
        rows = self._visible()
        return rows[int(iid)] if iid and iid.isdigit() and int(iid) < len(rows) else None

    def _open_selected(self) -> None:
        r = self._selected()
        if r and r["pedido"] and self._on_open_pedido:
            self._on_open_pedido(r["pedido"])

    def _ctx_menu(self, iid: str, _col: int):
        r = self._selected()
        if not r:
            return None
        items = []
        if r["pedido"] and self._on_open_pedido:
            items.append((f"▦  Abrir {r['pedido']} en Seguimiento",
                          lambda: self._on_open_pedido(r["pedido"])))
        items += [
            ("Copiar material", lambda: self.table.copy_to_clipboard(r["material"])),
            ("Copiar proveedor", lambda: self.table.copy_to_clipboard(r["proveedor"])),
        ]
        if r["pedido_prov"]:
            items.append((f"Copiar nº de compra ({r['pedido_prov']})",
                          lambda: self.table.copy_to_clipboard(r["pedido_prov"])))
        return items

    def _export(self) -> None:
        rows = self._visible()
        if not rows:
            ui.toast(self, "Compras", "No hay filas que exportar.", kind="info")
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Exportar compras pendientes", defaultextension=".xlsx",
            initialfile=f"compras_pendientes_{datetime.now():%Y%m%d}.xlsx",
            filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            purchases.export_excel(rows, path)
            ui.toast(self, "Exportado", f"{len(rows)} línea(s) a Excel.", kind="success")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Exportar", f"No se pudo exportar:\n{exc}", parent=self)
