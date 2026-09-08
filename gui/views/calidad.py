"""Vista Calidad — no conformidades y equipos de medida.

  · «No conformidades»: las del ERP, con el pedido afectado, quién la detectó y
    si la acción correctiva está cerrada. Doble clic abre el detalle completo
    (descripción, causa y acción); el menú contextual lleva al pedido.
  · «Equipos de medida»: calibres, máquinas y manómetros con su próxima
    calibración, los vencidos arriba. Los dados de baja se muestran aparte.
"""

import logging
import threading
from datetime import datetime

import customtkinter as ctk
from tkinter import filedialog, messagebox

from core.services import quality
from gui import theme
from gui.widgets import ui
from gui.widgets.scrollframe import ScrollFrame
from gui.widgets.table import DataTable

logger = logging.getLogger(__name__)

NC_COLUMNS = ["Nº", "Fecha", "Pedido", "Tipo", "Detectada por", "Responsable", "Acción"]
EQ_COLUMNS = ["Familia", "Código", "Tipo", "Ubicación", "Última", "Próxima", "Estado"]

TAB_NC, TAB_EQ = "No conformidades", "Equipos de medida"


def _fmt(d) -> str:
    return d.strftime("%d-%m-%Y") if d else "—"


class CalidadView(ctk.CTkFrame):
    def __init__(self, master, on_open_pedido=None, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._on_open_pedido = on_open_pedido
        self._nc: list[dict] = []
        self._eq: list[dict] = []
        self._only_open = False
        self._build_layout()
        self._reload()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        header = ui.page_header(
            self, "Calidad",
            "No conformidades abiertas y equipos de medida con la calibración al día.",
            icon="✔", help_key="calidad")
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
        tab_nc = self.tabs.add(TAB_NC)
        tab_eq = self.tabs.add(TAB_EQ)

        bar = ctk.CTkFrame(tab_nc, fg_color="transparent")
        bar.pack(fill="x", pady=(theme.SPACE_2, 0))
        self.var_open = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(bar, text="Solo las que siguen sin acción correctiva cerrada",
                        variable=self.var_open, font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                        fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                        command=self._toggle_open).pack(side="left")

        self.table_nc = DataTable(tab_nc, columns=NC_COLUMNS,
                                  on_double_click=lambda _e=None: self._open_nc())
        self.table_nc.pack(fill="both", expand=True, pady=(theme.SPACE_2, 0))
        self.table_nc.set_columns_width({"Nº": 60, "Fecha": 100, "Pedido": 130, "Tipo": 260,
                                         "Detectada por": 150, "Responsable": 150, "Acción": 90})
        self.table_nc.set_columns_anchor({"Nº": "center", "Fecha": "center", "Pedido": "w",
                                          "Tipo": "w", "Detectada por": "w", "Responsable": "w",
                                          "Acción": "center"})
        self.table_nc.tree.tag_configure("abierta", foreground=theme.AMBER)
        self.table_nc.tree.tag_configure("cliente", foreground=theme.RED)
        self.table_nc.set_context_menu(self._ctx_nc)

        self.table_eq = DataTable(tab_eq, columns=EQ_COLUMNS)
        self.table_eq.pack(fill="both", expand=True, pady=(theme.SPACE_2, 0))
        self.table_eq.set_columns_width({"Familia": 100, "Código": 190, "Tipo": 200,
                                         "Ubicación": 170, "Última": 100, "Próxima": 100,
                                         "Estado": 100})
        self.table_eq.set_columns_anchor({"Familia": "center", "Código": "w", "Tipo": "w",
                                          "Ubicación": "w", "Última": "center",
                                          "Próxima": "center", "Estado": "center"})
        self.table_eq.tree.tag_configure("vencido", foreground=theme.RED)
        self.table_eq.tree.tag_configure("pronto", foreground=theme.AMBER)
        self.table_eq.tree.tag_configure("baja", foreground=theme.TEXT_MUTED)

    # ── Datos ─────────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        self.lbl_status.configure(text="⏳  Consultando el ERP…", text_color=theme.TEXT_MUTED)
        self.btn_reload.configure(state="disabled")

        def worker():
            try:
                data = (quality.nonconformities(), quality.nc_stats(),
                        quality.equipment(), quality.equipment_stats())
                self.after(0, lambda: self._render(*data))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Calidad: error consultando el ERP")
                msg = str(exc)
                self.after(0, lambda: self._error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _hard_refresh(self) -> None:
        quality.invalidate_cache()
        self._reload()

    def _error(self, msg: str) -> None:
        self.btn_reload.configure(state="normal")
        self.lbl_status.configure(text=f"✗  {msg}", text_color=theme.RED)

    def _render(self, nc, nc_st, eq, eq_st) -> None:
        self._nc, self._eq = nc, eq
        self._nc_stats, self._eq_stats = nc_st, eq_st
        self.btn_reload.configure(state="normal")
        if not quality.is_available():
            self.lbl_status.configure(text="✗  El ERP no responde: ábrelo y pulsa ↻.",
                                      text_color=theme.AMBER)
            self.table_nc.clear(); self.table_eq.clear()
            return
        self.lbl_status.configure(
            text=f"{nc_st['total']} no conformidades · {eq_st['total']} equipos en uso · "
                 f"datos del ERP a {datetime.now():%d-%m-%Y %H:%M}", text_color=theme.TEXT_MUTED)
        self._fill_nc()
        self._fill_eq()
        self._kpis()

    def _kpis(self) -> None:
        for w in self.kpi_row.winfo_children():
            w.destroy()
        if self.tabs.get() == TAB_EQ:
            st = self._eq_stats
            cards = [
                ("Vencidos", st["vencidos"], theme.RED if st["vencidos"] else theme.GREEN,
                 "calibración pasada de fecha"),
                ("Vencen en 90 días", st["pronto"], theme.AMBER, "conviene programarlos"),
                ("Sin fecha", st["sin_fecha"], theme.TEXT_SUB, "no tienen próxima revisión"),
                ("Equipos en uso", st["total"], theme.ACCENT, f"{st['baja']} dados de baja"),
            ]
        else:
            st = self._nc_stats
            cards = [
                ("Sin cerrar", st["abiertas"], theme.AMBER if st["abiertas"] else theme.GREEN,
                 "sin acción correctiva completada"),
                ("Del último año", st["ultimo_anio"], theme.ACCENT,
                 f"{st['abiertas_anio']} siguen abiertas"),
                ("Detectadas por el cliente", st["cliente"], theme.RED,
                 "en los últimos 12 meses"),
                ("Pedidos afectados", st["pedidos"], theme.BLUE, f"de {st['total']} NC en total"),
            ]
        for col, (label, value, color, sub) in enumerate(cards):
            ui.kpi_card(self.kpi_row, label, value, color, sub).grid(
                row=0, column=col, sticky="ew", padx=(0 if col == 0 else theme.SPACE_2, 0))

    def _on_tab(self) -> None:
        if getattr(self, "_nc_stats", None):
            self._kpis()

    def _toggle_open(self) -> None:
        self._only_open = bool(self.var_open.get())
        self._fill_nc()

    def _visible_nc(self) -> list[dict]:
        return [n for n in self._nc if not n["cerrada"]] if self._only_open else self._nc

    def _fill_nc(self) -> None:
        self.table_nc.clear()
        for i, n in enumerate(self._visible_nc()):
            tags = ("cliente",) if (n["cliente_detecta"] and not n["cerrada"]) else (
                ("abierta",) if not n["cerrada"] else ())
            self.table_nc.add_row(
                values=[n["id"], _fmt(n["fecha"]), n["pedido_raw"] or "—", n["tipo"] or "—",
                        n["detectada_por"] or "—", n["responsable"] or "—",
                        "cerrada" if n["cerrada"] else "abierta"],
                iid=str(i), tags=tags)
        self.after(60, self.table_nc.autofit_columns)

    def _fill_eq(self) -> None:
        self.table_eq.clear()
        for i, e in enumerate(self._eq):
            if e["baja"]:
                tag, estado = "baja", "Baja"
            elif e["vencido"]:
                tag, estado = "vencido", "Vencido"
            elif e["dias"] is not None and e["dias"] <= quality.SOON_DAYS:
                tag, estado = "pronto", f"{e['dias']} d"
            else:
                tag, estado = "", "Al día" if e["proxima"] else "Sin fecha"
            self.table_eq.add_row(
                values=[e["familia"], e["codigo"] or "—", e["tipo"] or "—", e["ubicacion"] or "—",
                        _fmt(e["ultima"]), _fmt(e["proxima"]), estado],
                iid=str(i), tags=(tag,) if tag else ())
        self.after(60, self.table_eq.autofit_columns)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _selected_nc(self) -> dict | None:
        iid = self.table_nc.selected_iid()
        rows = self._visible_nc()
        return rows[int(iid)] if iid and iid.isdigit() and int(iid) < len(rows) else None

    def _open_nc(self) -> None:
        n = self._selected_nc()
        if n:
            NCDetailWindow(self, n, on_open_pedido=self._on_open_pedido)

    def _ctx_nc(self, iid: str, _col: int):
        n = self._selected_nc()
        if not n:
            return None
        items = [("🔍  Ver la no conformidad", self._open_nc)]
        if n["pedido"] and self._on_open_pedido:
            items.append((f"▦  Abrir {n['pedido']} en Pedidos",
                          lambda: self._on_open_pedido(n["pedido"])))
        items.append(("Copiar descripción", lambda: self.table_nc.copy_to_clipboard(n["descripcion"])))
        return items

    def _export(self) -> None:
        eq_tab = self.tabs.get() == TAB_EQ
        rows = self._eq if eq_tab else self._visible_nc()
        if not rows:
            ui.toast(self, "Calidad", "No hay filas que exportar.", kind="info")
            return
        nombre = "equipos_medida" if eq_tab else "no_conformidades"
        path = filedialog.asksaveasfilename(
            parent=self, title="Exportar a Excel", defaultextension=".xlsx",
            initialfile=f"{nombre}_{datetime.now():%Y%m%d}.xlsx", filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            quality.export_excel(rows, path, kind="eq" if eq_tab else "nc")
            ui.toast(self, "Exportado", f"{len(rows)} fila(s) a Excel.", kind="success")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Exportar", f"No se pudo exportar:\n{exc}", parent=self)


class NCDetailWindow(ctk.CTkToplevel):
    """Ficha completa de una no conformidad (los textos largos del ERP)."""

    def __init__(self, master, nc: dict, on_open_pedido=None):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title(f"No conformidad {nc['id']}")
        self.geometry("760x620")
        self.minsize(620, 480)
        self.transient(master)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=theme.SPACE_5, pady=(theme.SPACE_5, theme.SPACE_2))
        ctk.CTkLabel(head, text=f"NC {nc['id']}  ·  {_fmt(nc['fecha'])}",
                     font=theme.font(18, "bold"), text_color=theme.TEXT_MAIN, anchor="w").pack(anchor="w")
        estado = "Acción correctiva cerrada" if nc["cerrada"] else "Sin acción correctiva cerrada"
        ctk.CTkLabel(head, text=f"{nc['tipo'] or 'Sin tipificar'}  ·  {estado}",
                     font=theme.FONT_BODY,
                     text_color=theme.GREEN if nc["cerrada"] else theme.AMBER,
                     anchor="w").pack(anchor="w", pady=(2, 0))

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(side="bottom", fill="x", padx=theme.SPACE_5, pady=theme.SPACE_4)
        ui.button(foot, "Cerrar", "secondary", size="lg", command=self.destroy).pack(side="right")
        if nc["pedido"] and on_open_pedido:
            ui.button(foot, f"▦  Abrir {nc['pedido']}", "primary", size="lg",
                      command=lambda: (self.destroy(), on_open_pedido(nc["pedido"]))).pack(side="left")

        body = ScrollFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=theme.SPACE_5, pady=(0, theme.SPACE_2))

        for label, value in (("Pedido", nc["pedido_raw"]), ("Plano", nc["plano"]),
                             ("Zona", nc["zona"]), ("Detectada por", nc["detectada_por"]),
                             ("Responsable", nc["responsable"]),
                             ("Fecha de la acción", _fmt(nc["fecha_accion"])),
                             ("Coste", nc["coste"])):
            if value and value != "—":
                row = ctk.CTkFrame(body, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text=label.upper(), font=theme.FONT_LABEL,
                             text_color=theme.TEXT_MUTED, anchor="w", width=140).pack(side="left")
                ctk.CTkLabel(row, text=value, font=theme.FONT_BODY_BOLD,
                             text_color=theme.TEXT_MAIN, anchor="w",
                             wraplength=520, justify="left").pack(side="left", fill="x", expand=True)

        for titulo, texto in (("Descripción", nc["descripcion"]),
                              ("Análisis de la causa", nc["causa"]),
                              ("Acción correctiva", nc["accion"])):
            if not texto:
                continue
            ui.section_header(body, titulo).pack(fill="x", pady=(theme.SPACE_3, theme.SPACE_1))
            card = ctk.CTkFrame(body, fg_color=theme.BG_CARD, corner_radius=10,
                                border_width=1, border_color=theme.BORDER)
            card.pack(fill="x")
            ctk.CTkLabel(card, text=texto, font=theme.FONT_BODY, text_color=theme.TEXT_MAIN,
                         anchor="w", justify="left", wraplength=660).pack(
                anchor="w", padx=theme.SPACE_3, pady=theme.SPACE_3)
