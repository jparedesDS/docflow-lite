"""Vista Informes — analítica de documentación (sin Centro de Reportes).

Tres pestañas, organizadas:
  • Resumen                → KPIs globales, distribución por estado, top clientes
                             por días de respuesta, por tipo de documento, heatmap.
  • Equipo                 → ranking de rendimiento por responsable + carga de
                             trabajo (stacked bars + detección de sobrecarga).
  • Predicción & Scorecard → curva-S / predicción por pedido + scorecard de
                             clientes (score 0-100).

Carga pesada (monitoring) en hilos. Gráficos resueltos con barras nativas
(CTkFrame + place) y tablas, sin dependencias de charting.
"""

import logging
import os
import threading
import webbrowser

import customtkinter as ctk

from core.services import analytics as an
from gui import theme
from gui.widgets import ui
from gui.widgets.scrollframe import ScrollFrame
from gui.widgets.table import DataTable

logger = logging.getLogger(__name__)


# ── Helpers (design system compartido en gui.widgets.ui) ──────────────────────
_section_header = ui.section_header
_pct_color = ui.pct_color
_days_color = ui.days_color
_score_color = ui.score_color
_avatar_color = ui.avatar_color
_blend = ui.blend
_kpi_card = ui.kpi_card
_bar_row = ui.bar_row


_ROW_H = 34          # alto de fila de tabla (coincide con DataTable.ROW_HEIGHT)
_TBL_MAX = 500       # alto máximo común para todas las tablas de la vista


def _tbl_height(n: int, max_h: int = _TBL_MAX) -> int:
    """Alto consistente para una tabla de `n` filas (cabecera + filas, con tope)."""
    return min(n * _ROW_H + 48, max_h)


def _table_host(parent, height: int) -> ctk.CTkFrame:
    host = ctk.CTkFrame(parent, fg_color="transparent", height=height)
    host.pack(fill="both", expand=True, pady=(0, theme.SPACE_3))
    host.pack_propagate(False)
    return host


# ════════════════════════════════════════════════════════════════════════════
#  Vista principal
# ════════════════════════════════════════════════════════════════════════════

class InformesView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._loaded: dict[str, bool] = {}
        self._build_layout()
        self.after(60, self._load_resumen)
        self._loaded["Resumen"] = True

    def _build_layout(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(header, text="Analítica", font=theme.FONT_TITLE,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(anchor="w")
        ctk.CTkLabel(header, text="Analítica de documentación · rendimiento · predicción",
                     font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w").pack(
            anchor="w", pady=(theme.SPACE_1, 0))

        self.tabs = ctk.CTkTabview(
            self, fg_color=theme.BG_PAGE,
            segmented_button_fg_color=theme.BG_CARD,
            segmented_button_selected_color=theme.ACCENT,
            segmented_button_selected_hover_color=theme.ACCENT_HOVER,
            segmented_button_unselected_color=theme.BG_CARD,
            segmented_button_unselected_hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, command=self._on_tab)
        self.tabs.pack(fill="both", expand=True, padx=theme.SPACE_5,
                       pady=(theme.SPACE_3, theme.SPACE_4))

        self.tab_resumen = self.tabs.add("Resumen")
        self.tab_equipo = self.tabs.add("Equipo")
        self.tab_pred = self.tabs.add("Predicción & Scorecard")
        self.tab_informe = self.tabs.add("Informe interactivo")

        for tab, attr in ((self.tab_resumen, "scroll_resumen"),
                          (self.tab_equipo, "scroll_equipo"),
                          (self.tab_pred, "scroll_pred")):
            status = ctk.CTkLabel(tab, text="", font=theme.FONT_SMALL,
                                  text_color=theme.TEXT_MUTED, anchor="w")
            status.pack(fill="x", padx=theme.SPACE_2, pady=(theme.SPACE_2, theme.SPACE_1))
            scroll = ScrollFrame(tab)
            scroll.pack(fill="both", expand=True, padx=theme.SPACE_2, pady=(0, theme.SPACE_2))
            setattr(self, attr, scroll)
            setattr(self, attr + "_status", status)

        self._build_informe_tab(self.tab_informe)

    def _on_tab(self) -> None:
        sel = self.tabs.get()
        loaders = {"Resumen": self._load_resumen, "Equipo": self._load_equipo,
                   "Predicción & Scorecard": self._load_pred}
        loader = loaders.get(sel)
        if loader and not self._loaded.get(sel):
            self._loaded[sel] = True
            loader()

    # ── carga genérica en hilo ───────────────────────────────────────────────

    def _run(self, status, fetch, render) -> None:
        status.configure(text="⏳  Calculando…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                data = fetch()
                self.after(0, lambda: render(data))
            except Exception as exc:
                logger.exception("Error informes")
                msg = str(exc)
                self.after(0, lambda: status.configure(text=f"✗  {msg}", text_color=theme.RED))

        threading.Thread(target=worker, daemon=True).start()

    # ════════════════════════════════════════════════════════════════════════
    #  RESUMEN
    # ════════════════════════════════════════════════════════════════════════

    def _load_resumen(self) -> None:
        self._run(self.scroll_resumen_status, an.get_summary, self._render_resumen)

    def _render_resumen(self, s: dict) -> None:
        p = self.scroll_resumen
        for w in p.winfo_children():
            w.destroy()
        self.scroll_resumen_status.configure(
            text=f"✓  {s['total_clientes']} clientes · velocidad media {s['velocidad_media_dias']}d",
            text_color=theme.TEXT_MUTED)

        # KPIs
        kdefs = [
            ("Velocidad media", f"{s['velocidad_media_dias']}d", theme.ACCENT, "días medios de respuesta"),
            ("Clientes OK", f"{s['clientes_ok']}/{s['total_clientes']}", theme.GREEN, "≥75% aprobados"),
            ("Docs en riesgo", s["docs_riesgo"], theme.RED if s["docs_riesgo"] else theme.GREEN, "críticos +15d sin respuesta"),
            ("Vencen ≤3d", s["a_vencer_3d"], theme.AMBER if s["a_vencer_3d"] else theme.GREEN, "casi fuera de plazo"),
        ]
        kgrid = ctk.CTkFrame(p, fg_color="transparent")
        kgrid.pack(fill="x", pady=(0, theme.SPACE_3))
        for c in range(len(kdefs)):
            kgrid.grid_columnconfigure(c, weight=1, uniform="k")
        for i, (lb, val, col, sub) in enumerate(kdefs):
            card = _kpi_card(kgrid, lb, val, col, sub)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else theme.SPACE_2, 0))

        # Distribución por estado
        _section_header(p, "Distribución por estado").pack(fill="x", pady=(0, theme.SPACE_2))
        dist = [("Aprobado", s["total_aprobados"], theme.GREEN),
                ("Enviado", s["total_enviados"], theme.BLUE),
                ("Devoluciones", s["total_devoluciones"], theme.AMBER),
                ("Sin enviar", s["total_sin_enviar"], theme.TEXT_MUTED)]
        dmax = max((v for _, v, _ in dist), default=1) or 1
        dbox = ctk.CTkFrame(p, fg_color=theme.BG_CARD, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        dbox.pack(fill="x", pady=(0, theme.SPACE_3))
        inner = ctk.CTkFrame(dbox, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_3)
        for label, val, col in dist:
            _bar_row(inner, label, val, val / dmax, col)

        # Top clientes por días medios
        _section_header(p, "Top clientes · días medios de respuesta").pack(
            fill="x", pady=(0, theme.SPACE_2))
        top = s["por_cliente"][:10]
        cmax = max((c["media_dias"] for c in top), default=1) or 1
        cbox = ctk.CTkFrame(p, fg_color=theme.BG_CARD, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        cbox.pack(fill="x", pady=(0, theme.SPACE_3))
        cinner = ctk.CTkFrame(cbox, fg_color="transparent")
        cinner.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_3)
        if top:
            for c in top:
                _bar_row(cinner, c["cliente"][:22], c["media_dias"],
                         c["media_dias"] / cmax, _days_color(c["media_dias"]),
                         value_text=f"{c['media_dias']}d")
        else:
            ctk.CTkLabel(cinner, text="Sin datos", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTED).pack()

        # Por tipo de documento
        _section_header(p, "Por tipo de documento").pack(fill="x", pady=(0, theme.SPACE_2))
        cols = ["Tipo", "Aprob.", "Enviado", "Coment.", "Sin env.", "Total"]
        host = _table_host(p, _tbl_height(len(s["por_tipo_doc"][:12])))
        t = DataTable(host, columns=cols)
        t.pack(fill="both", expand=True)
        t.set_columns_anchor({c: ("w" if c == "Tipo" else "center") for c in cols})
        for i, r in enumerate(s["por_tipo_doc"][:12]):
            t.add_row(values=[r["tipo"], r["aprobado"], r["enviado"], r["com_menores"],
                              r["sin_enviar"], r["total"]], iid=f"tp_{i}")
        t.autofit_columns(max_per={"Tipo": 260})

        # Heatmap (mapa de calor real, color por intensidad)
        _section_header(p, "Heatmap cliente × estado").pack(fill="x", pady=(0, theme.SPACE_2))
        self._heatmap_grid(p, s["heatmap_cliente"][:15])

    def _heatmap_grid(self, parent, rows: list[dict]) -> None:
        if not rows:
            ctk.CTkLabel(parent, text="Sin datos.", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTED).pack(anchor="w", pady=(0, theme.SPACE_3))
            return
        cols = [("aprobado", "Aprob.", theme.GREEN), ("enviado", "Enviado", theme.BLUE),
                ("com_menores", "Coment.", theme.AMBER), ("rechazado", "Rechaz.", theme.RED),
                ("sin_enviar", "Sin env.", theme.TEXT_MUTED)]
        maxc = {k: max((r.get(k, 0) for r in rows), default=1) or 1 for k, _, _ in cols}

        box = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=10,
                           border_width=1, border_color=theme.BORDER)
        box.pack(fill="x", pady=(0, theme.SPACE_3))
        grid = ctk.CTkFrame(box, fg_color="transparent")
        grid.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_3)
        grid.grid_columnconfigure(0, weight=1, minsize=180)
        for j in range(len(cols)):
            grid.grid_columnconfigure(j + 1, minsize=78)
        grid.grid_columnconfigure(len(cols) + 1, minsize=60)

        # Cabecera
        ctk.CTkLabel(grid, text="CLIENTE", font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                     anchor="w").grid(row=0, column=0, sticky="w", padx=2, pady=(0, 4))
        for j, (_, lbl, ccol) in enumerate(cols):
            ctk.CTkLabel(grid, text=lbl, font=theme.font(10, "bold"), text_color=ccol).grid(
                row=0, column=j + 1, padx=2, pady=(0, 4))
        ctk.CTkLabel(grid, text="Total", font=theme.FONT_TINY, text_color=theme.TEXT_MUTED).grid(
            row=0, column=len(cols) + 1, padx=2, pady=(0, 4))

        for i, r in enumerate(rows):
            ctk.CTkLabel(grid, text=str(r["cliente"])[:26], font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MAIN, anchor="w").grid(
                row=i + 1, column=0, sticky="w", padx=2, pady=1)
            for j, (key, _, ccol) in enumerate(cols):
                val = r.get(key, 0)
                intensity = val / maxc[key]
                bg = _blend(ccol, theme.BG_CARD, 0.12 + intensity * 0.78) if val > 0 else theme.BG_PAGE
                txt_col = "#FFFFFF" if (val > 0 and intensity > 0.45) else (
                    theme.TEXT_MAIN if val > 0 else theme.TEXT_MUTED)
                ctk.CTkLabel(grid, text=str(val), font=theme.font(11, "bold" if val > 0 else "normal"),
                             text_color=txt_col, fg_color=bg, corner_radius=6,
                             width=70, height=26).grid(row=i + 1, column=j + 1, padx=2, pady=1)
            ctk.CTkLabel(grid, text=str(r["total"]), font=theme.FONT_SMALL_BOLD,
                         text_color=theme.TEXT_SUB).grid(row=i + 1, column=len(cols) + 1, padx=2, pady=1)

    # ════════════════════════════════════════════════════════════════════════
    #  EQUIPO — rendimiento + carga
    # ════════════════════════════════════════════════════════════════════════

    def _load_equipo(self) -> None:
        # get_team_workload ya calcula el ranking internamente (members) → no
        # lo pedimos por separado para no recorrer el dataset dos veces.
        self._run(self.scroll_equipo_status,
                  lambda: {"workload": an.get_team_workload(),
                           "overview": an.get_team_overview(), "matriz": an.get_matriz_comercial()},
                  self._render_equipo)

    def _render_equipo(self, d: dict) -> None:
        p = self.scroll_equipo
        for w in p.winfo_children():
            w.destroy()
        wl = d["workload"]
        ranking = sorted(wl["members"], key=lambda x: x["pct"], reverse=True)
        overview = d["overview"]
        matriz = d["matriz"]
        self.scroll_equipo_status.configure(
            text=f"✓  {len(overview)} persona(s) · carga media {wl['avg_load']} docs",
            text_color=theme.TEXT_MUTED)

        # ── Estado del equipo (una caja por persona) ─────────────────────
        _section_header(p, "Estado del equipo").pack(fill="x", pady=(0, theme.SPACE_2))
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x", pady=(0, theme.SPACE_3))
        ncols = 3
        for c in range(ncols):
            grid.grid_columnconfigure(c, weight=1, uniform="team")
        for i, w in enumerate(overview):
            self._worker_card(grid, w, i // ncols, i % ncols)

        # Ranking de rendimiento
        _section_header(p, "Ranking de rendimiento").pack(fill="x", pady=(0, theme.SPACE_2))
        cols = ["#", "Responsable", "Total", "Aprob.", "% Compl.", "Devol.", "Tasa Dev.", "Críticos"]
        host = _table_host(p, _tbl_height(len(ranking)))
        t = DataTable(host, columns=cols)
        t.pack(fill="both", expand=True)
        t.set_columns_anchor({"#": "center", "Responsable": "w", "Total": "center",
                              "Aprob.": "center", "% Compl.": "center", "Devol.": "center",
                              "Tasa Dev.": "center", "Críticos": "center"})
        t.tree.tag_configure("ok", foreground=theme.GREEN)
        t.tree.tag_configure("warn", foreground=theme.AMBER)
        t.tree.tag_configure("bad", foreground=theme.RED)
        for i, r in enumerate(ranking):
            tier = "ok" if r["pct"] >= 75 else ("warn" if r["pct"] >= 50 else "bad")
            t.add_row(values=[f"#{i+1}", r["responsable"], r["total"], r["aprobados"],
                              f"{r['pct']}%", r["devoluciones"], f"{r['tasa_devolucion']}%",
                              r["criticos"]], iid=f"rk_{i}", tags=(tier,))
        t.autofit_columns(max_per={"Responsable": 200})

        # Carga de trabajo
        _section_header(p, "Carga de trabajo").pack(fill="x", pady=(0, theme.SPACE_2))
        summ = ctk.CTkLabel(
            p, text=f"Media {wl['avg_load']} · Máx {wl['max_load']} · Desv. {wl['std_dev']}"
                    + (f"  ·  ⚠ {len(wl['alerts'])} sobrecargado(s): "
                       + ", ".join(a["responsable"] for a in wl["alerts"]) if wl["alerts"] else ""),
            font=theme.FONT_SMALL, text_color=theme.TEXT_SUB, anchor="w", justify="left")
        summ.pack(fill="x", pady=(0, theme.SPACE_2))

        wbox = ctk.CTkFrame(p, fg_color=theme.BG_CARD, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        wbox.pack(fill="x", pady=(0, theme.SPACE_3))
        inner = ctk.CTkFrame(wbox, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_3)
        for m in wl["members"]:
            self._workload_row(inner, m)

        # Leyenda
        legend = ctk.CTkFrame(inner, fg_color="transparent")
        legend.pack(fill="x", pady=(theme.SPACE_2, 0))
        for txt, col in (("Aprobados", theme.GREEN), ("Devoluciones", theme.AMBER),
                         ("Sin enviar", theme.TEXT_MUTED)):
            chip = ctk.CTkFrame(legend, fg_color="transparent")
            chip.pack(side="left", padx=(0, theme.SPACE_3))
            ctk.CTkFrame(chip, fg_color=col, width=10, height=10, corner_radius=2).pack(side="left")
            ctk.CTkLabel(chip, text=txt, font=theme.FONT_TINY, text_color=theme.TEXT_MUTED).pack(
                side="left", padx=(4, 0))

        # ── Matriz Comercial × Responsable Doc ───────────────────────────
        _section_header(p, "Matriz Comercial × Responsable Doc · % aprobación").pack(
            fill="x", pady=(0, theme.SPACE_2))
        self._matriz_grid(p, matriz)

    # ── Caja por persona ─────────────────────────────────────────────────────

    def _worker_card(self, parent, w: dict, r, c) -> None:
        col = _avatar_color(w["iniciales"])
        card = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        card.grid(row=r, column=c, sticky="nsew",
                  padx=(0 if c == 0 else theme.SPACE_2, 0), pady=(0, theme.SPACE_2))

        # Cabecera: avatar + nombre + chips
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_3, theme.SPACE_2))
        av = ctk.CTkFrame(head, width=34, height=34, corner_radius=17, fg_color=col)
        av.pack(side="left", padx=(0, theme.SPACE_2))
        av.pack_propagate(False)
        ctk.CTkLabel(av, text=w["iniciales"], font=theme.font(11, "bold"),
                     text_color="#FFFFFF").pack(expand=True)
        nm = ctk.CTkFrame(head, fg_color="transparent")
        nm.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(nm, text=w["nombre"], font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(anchor="w")
        sub = f"{w['n_pendientes']} pendiente(s)" if w["n_pendientes"] else "Sin pendientes"
        ctk.CTkLabel(nm, text=sub, font=theme.FONT_TINY,
                     text_color=theme.AMBER if w["n_pendientes"] else theme.GREEN,
                     anchor="w").pack(anchor="w")

        # KPI pills
        pills = ctk.CTkFrame(card, fg_color="transparent")
        pills.pack(fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_2))
        self._pill(pills, "Total", w["total"], theme.TEXT_MAIN)
        self._pill(pills, "% Aprob", f"{w['pct']}%", _pct_color(w["pct"]))
        if w["criticos"]:
            self._pill(pills, "Crít.", w["criticos"], theme.RED)
        if w["devoluciones"]:
            self._pill(pills, "Devol.", w["devoluciones"], theme.AMBER)
        if w["sin_enviar"]:
            self._pill(pills, "Sin env.", w["sin_enviar"], theme.TEXT_MUTED)

        # Barra de progreso
        bar = ctk.CTkProgressBar(card, height=5, corner_radius=3,
                                 progress_color=_pct_color(w["pct"]), fg_color=theme.BORDER)
        bar.pack(fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_2))
        bar.set(min(w["pct"], 100) / 100)

        # Documentos pendientes (top 5)
        ctk.CTkLabel(card, text="PENDIENTES DE TRABAJAR", font=theme.FONT_TINY,
                     text_color=theme.TEXT_MUTED, anchor="w").pack(
            fill="x", padx=theme.SPACE_3, pady=(0, 2))
        if not w["pendientes"]:
            ctk.CTkLabel(card, text="✓  Todo al día", font=theme.FONT_TINY,
                         text_color=theme.GREEN, anchor="w").pack(
                fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_3))
        else:
            for pd in w["pendientes"][:5]:
                self._pending_row(card, pd)
            if w["n_pendientes"] > 5:
                ctk.CTkLabel(card, text=f"+{w['n_pendientes'] - 5} más", font=theme.FONT_TINY,
                             text_color=theme.TEXT_MUTED, anchor="w").pack(
                    fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_2))
            else:
                ctk.CTkFrame(card, fg_color="transparent", height=theme.SPACE_1).pack()

    def _pill(self, parent, label, value, color):
        box = ctk.CTkFrame(parent, fg_color=theme.BG_PAGE, corner_radius=7,
                           border_width=1, border_color=theme.BORDER)
        box.pack(side="left", padx=(0, theme.SPACE_1))
        ctk.CTkLabel(box, text=str(value), font=theme.font(13, "bold"),
                     text_color=color).pack(padx=theme.SPACE_2, pady=(3, 0))
        ctk.CTkLabel(box, text=label, font=theme.FONT_TINY,
                     text_color=theme.TEXT_MUTED).pack(padx=theme.SPACE_2, pady=(0, 3))

    def _pending_row(self, parent, pd: dict) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=theme.SPACE_3, pady=1)
        dcol = _days_color(pd["dias"]) if pd["dias"] else theme.TEXT_MUTED
        ctk.CTkLabel(row, text=f"{pd['dias']}d" if pd["dias"] else "—", font=theme.font(9, "bold"),
                     text_color=dcol, width=34, anchor="w").pack(side="left")
        doc = pd["doc_eipsa"] or pd["titulo"][:18]
        ctk.CTkLabel(row, text=(doc[:30] + ("  ⚠" if pd["critico"] else "")),
                     font=theme.FONT_TINY, text_color=theme.TEXT_SUB, anchor="w").pack(
            side="left", fill="x", expand=True)
        ctk.CTkLabel(row, text=pd["estado"], font=theme.font(9),
                     text_color=theme.TEXT_MUTED, anchor="e").pack(side="right")

    # ── Matriz comercial ─────────────────────────────────────────────────────

    def _matriz_grid(self, parent, matriz: list[dict]) -> None:
        if not matriz:
            ctk.CTkLabel(parent, text="Sin datos.", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTED).pack(anchor="w", pady=(0, theme.SPACE_3))
            return
        comerciales = sorted({r["comercial"] for r in matriz})
        resp_docs = sorted({r["resp_doc"] for r in matriz})
        cell_map = {(r["comercial"], r["resp_doc"]): r for r in matriz}

        box = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=10,
                           border_width=1, border_color=theme.BORDER)
        box.pack(fill="x", pady=(0, theme.SPACE_3))
        grid = ctk.CTkFrame(box, fg_color="transparent")
        grid.pack(anchor="w", padx=theme.SPACE_3, pady=theme.SPACE_3)

        # Cabecera de columnas (resp_doc)
        ctk.CTkLabel(grid, text="COMERCIAL ╲ DOC", font=theme.FONT_TINY,
                     text_color=theme.TEXT_MUTED, anchor="w", width=110).grid(
            row=0, column=0, sticky="w", padx=2, pady=(0, 4))
        for j, rd in enumerate(resp_docs):
            ctk.CTkLabel(grid, text=rd, font=theme.font(10, "bold"), text_color=theme.TEXT_SUB,
                         width=54).grid(row=0, column=j + 1, padx=2, pady=(0, 4))
        # Filas
        for i, com in enumerate(comerciales):
            ctk.CTkLabel(grid, text=com, font=theme.FONT_SMALL_BOLD, text_color=theme.TEXT_MAIN,
                         anchor="w", width=110).grid(row=i + 1, column=0, sticky="w", padx=2, pady=2)
            for j, rd in enumerate(resp_docs):
                cell = cell_map.get((com, rd))
                if cell:
                    pct = cell["pct"]
                    col = _pct_color(pct)
                    lbl = ctk.CTkLabel(grid, text=f"{pct}%", font=theme.font(10, "bold"),
                                       text_color=col, fg_color=_blend(col, theme.BG_CARD, 0.16),
                                       corner_radius=6, width=54, height=26)
                else:
                    lbl = ctk.CTkLabel(grid, text="·", font=theme.FONT_SMALL,
                                       text_color=theme.BORDER_STRONG, width=54, height=26)
                lbl.grid(row=i + 1, column=j + 1, padx=2, pady=2)

    def _workload_row(self, parent, m: dict) -> None:
        total = m["total"] or 1
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        name = m["responsable"] + ("  ⚠" if m.get("overload") else "")
        ctk.CTkLabel(row, text=name, font=theme.FONT_SMALL_BOLD,
                     text_color=theme.RED if m.get("overload") else theme.TEXT_SUB,
                     anchor="w", width=110).pack(side="left")
        track = ctk.CTkFrame(row, height=16, fg_color=theme.BG_INPUT, corner_radius=4)
        track.pack(side="left", fill="x", expand=True, padx=theme.SPACE_2)
        segs = [(m["aprobados"], theme.GREEN), (m["devoluciones"], theme.AMBER),
                (m.get("sin_enviar", 0), theme.TEXT_MUTED)]
        x = 0.0
        for val, col in segs:
            if val <= 0:
                continue
            w = val / total
            seg = ctk.CTkFrame(track, fg_color=col, corner_radius=0)
            seg.place(relx=x, rely=0, relheight=1, relwidth=w)
            x += w
        ctk.CTkLabel(row, text=str(m["total"]), font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN, width=44, anchor="e").pack(side="right")

    # ════════════════════════════════════════════════════════════════════════
    #  PREDICCIÓN & SCORECARD
    # ════════════════════════════════════════════════════════════════════════

    def _load_pred(self) -> None:
        self._run(self.scroll_pred_status,
                  lambda: {"pred": an.get_predicciones(), "score": an.get_scorecard()},
                  self._render_pred)

    def _render_pred(self, d: dict) -> None:
        p = self.scroll_pred
        for w in p.winfo_children():
            w.destroy()
        pred = [x for x in d["pred"] if x.get("pct_esperado") is not None]
        score = d["score"]
        self.scroll_pred_status.configure(
            text=f"✓  {len(pred)} pedido(s) con predicción · {len(score)} clientes en scorecard",
            text_color=theme.TEXT_MUTED)

        # Predicción de pedidos
        _section_header(p, "Predicción de pedidos · curva-S").pack(fill="x", pady=(0, theme.SPACE_2))
        cols = ["Pedido", "% Real", "% Esper.", "Desv.", "Aprob/Total", "Fecha Prev.", "Pred. Fin", "Estado"]
        host = _table_host(p, _tbl_height(len(pred)))
        t = DataTable(host, columns=cols)
        t.pack(fill="both", expand=True)
        t.set_columns_anchor({c: ("w" if c == "Pedido" else "center") for c in cols})
        t.tree.tag_configure("adelantado", foreground=theme.GREEN)
        t.tree.tag_configure("retrasado", foreground=theme.RED)
        for i, x in enumerate(pred):
            desv = x["pct"] - x["pct_esperado"]
            estado = "✓ En plazo" if x.get("en_plazo") is True else ("✗ Riesgo" if x.get("en_plazo") is False else "—")
            t.add_row(values=[x["pedido"], f"{x['pct']}%", f"{x['pct_esperado']}%",
                              (f"+{desv}" if desv >= 0 else str(desv)) + "pp",
                              f"{x['aprobados']}/{x['total']}", x.get("fecha_prevista") or "—",
                              x.get("prediccion_fecha") or "—", estado],
                      iid=f"pr_{i}", tags=("adelantado",) if desv >= 0 else ("retrasado",))
        t.autofit_columns(max_per={"Pedido": 140})

        # Scorecard KPIs
        _section_header(p, "Scorecard de clientes").pack(fill="x", pady=(0, theme.SPACE_2))
        if score:
            avg = round(sum(r["score"] for r in score) / len(score), 1)
            best = max(score, key=lambda r: r["score"])
            worst = min(score, key=lambda r: r["score"])
            kdefs = [("Score medio", avg, _score_color(avg), "sobre 100"),
                     ("Mejor cliente", best["client"][:18], theme.GREEN, f"{best['score']} pts"),
                     ("Peor cliente", worst["client"][:18], theme.RED, f"{worst['score']} pts")]
            kgrid = ctk.CTkFrame(p, fg_color="transparent")
            kgrid.pack(fill="x", pady=(0, theme.SPACE_3))
            for c in range(3):
                kgrid.grid_columnconfigure(c, weight=1, uniform="sk")
            for i, (lb, val, col, sub) in enumerate(kdefs):
                _kpi_card(kgrid, lb, val, col, sub).grid(
                    row=0, column=i, sticky="ew", padx=(0 if i == 0 else theme.SPACE_2, 0))

        # Scorecard tabla
        scols = ["Cliente", "Score", "% Aprob 1ªRev", "Días Resp.", "Crít. +30d", "Total"]
        shost = _table_host(p, _tbl_height(len(score[:25])))
        st = DataTable(shost, columns=scols)
        st.pack(fill="both", expand=True)
        st.set_columns_anchor({c: ("w" if c == "Cliente" else "center") for c in scols})
        st.tree.tag_configure("s_ok", foreground=theme.GREEN)
        st.tree.tag_configure("s_warn", foreground=theme.AMBER)
        st.tree.tag_configure("s_bad", foreground=theme.RED)
        for i, r in enumerate(score[:25]):
            tier = "s_ok" if r["score"] >= 80 else ("s_warn" if r["score"] >= 50 else "s_bad")
            st.add_row(values=[r["client"], r["score"], f"{r['approval_rate_first_rev']}%",
                               r["avg_response_days"], r["critical_docs_count"], r["total_docs"]],
                       iid=f"sc_{i}", tags=(tier,))
        st.autofit_columns(max_per={"Cliente": 240})

    # ════════════════════════════════════════════════════════════════════════
    #  INFORME INTERACTIVO (HTML semanal / mensual)
    # ════════════════════════════════════════════════════════════════════════

    def _build_informe_tab(self, tab) -> None:
        from core.services import interactive_report as ir
        self._ir = ir
        self._ir_mode = "period"          # "period" | "pedido"
        self._ir_period = "weekly"
        self._ir_periods: dict[str, str] = {}
        self._ir_pedidos: dict[str, str] = {}
        self._ir_last_path = None

        wrap = ScrollFrame(tab)
        wrap.pack(fill="both", expand=True, padx=theme.SPACE_2, pady=theme.SPACE_2)

        ctk.CTkLabel(
            wrap, text="Genera un informe web interactivo (un único archivo .html con "
            "gráficos y resumen IA), listo para abrir, archivar o enviar por email.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
            anchor="w", justify="left", wraplength=720).pack(
            anchor="w", pady=(theme.SPACE_2, theme.SPACE_3))

        card = ctk.CTkFrame(wrap, fg_color=theme.BG_CARD, corner_radius=12,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, theme.SPACE_3))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_4, pady=theme.SPACE_4)

        ctk.CTkLabel(inner, text="PERIODO", font=theme.FONT_TINY,
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        self._ir_seg = ctk.CTkSegmentedButton(
            inner, values=["Semanal", "Mensual", "Por pedido"], command=self._on_ir_period,
            height=theme.HEIGHT_BUTTON_SM, font=theme.FONT_SMALL_BOLD,
            corner_radius=theme.RADIUS_MD, fg_color=theme.BG_PAGE,
            selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.BG_PAGE, unselected_hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN)
        self._ir_seg.set("Semanal")
        self._ir_seg.pack(anchor="w", pady=(theme.SPACE_1, theme.SPACE_3))

        self._ir_sel_label = ctk.CTkLabel(inner, text="SEMANA / MES", font=theme.FONT_TINY,
                                          text_color=theme.TEXT_MUTED, anchor="w")
        self._ir_sel_label.pack(anchor="w")
        self._ir_menu = ctk.CTkOptionMenu(
            inner, values=["—"], width=380, height=theme.HEIGHT_INPUT,
            font=theme.FONT_SMALL, fg_color=theme.BG_INPUT, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT_MAIN)
        self._ir_menu.pack(anchor="w", pady=(theme.SPACE_1, theme.SPACE_3))

        ctk.CTkLabel(inner, text="DESTINATARIOS · para enviar por email (separa con coma)",
                     font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        self._ir_to = ctk.CTkEntry(inner, width=440, height=theme.HEIGHT_INPUT,
                                    placeholder_text="nombre@empresa.com, otro@empresa.com",
                                    font=theme.FONT_SMALL)
        self._ir_to.pack(anchor="w", pady=(theme.SPACE_1, theme.SPACE_4))

        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(anchor="w")
        ctk.CTkButton(btns, text="Generar y abrir", command=self._ir_generate,
                      **theme.button_kwargs("primary")).pack(side="left")
        ctk.CTkButton(btns, text="Abrir carpeta", command=self._ir_open_folder,
                      **theme.button_kwargs("secondary")).pack(side="left", padx=(theme.SPACE_2, 0))
        ctk.CTkButton(btns, text="Enviar por email", command=self._ir_send,
                      **theme.button_kwargs("secondary")).pack(side="left", padx=(theme.SPACE_2, 0))

        self._ir_status = ctk.CTkLabel(wrap, text="", font=theme.FONT_SMALL,
                                       text_color=theme.TEXT_MUTED, anchor="w", justify="left")
        self._ir_status.pack(anchor="w", pady=(theme.SPACE_2, 0))

        self._ir_refresh_periods()

    def _on_ir_period(self, value: str) -> None:
        if value == "Por pedido":
            self._ir_mode = "pedido"
            self._ir_sel_label.configure(text="PEDIDO")
            self._ir_refresh_pedidos()
        else:
            self._ir_mode = "period"
            self._ir_period = "monthly" if value == "Mensual" else "weekly"
            self._ir_sel_label.configure(text="SEMANA / MES")
            self._ir_refresh_periods()

    def _ir_refresh_pedidos(self) -> None:
        self._ir_menu.configure(values=["Cargando…"])
        self._ir_menu.set("Cargando…")

        def worker():
            try:
                rows = self._ir.list_pedidos()
            except Exception:
                logger.exception("No se pudieron listar pedidos")
                rows = []
            self.after(0, lambda: self._ir_set_pedidos(rows))

        threading.Thread(target=worker, daemon=True).start()

    def _ir_set_pedidos(self, rows) -> None:
        self._ir_pedidos = {}
        labels = []
        for r in rows:
            cli = (r.get("cliente") or "").strip()
            label = f"{r['pedido']} · {cli}" if cli else r["pedido"]
            self._ir_pedidos[label] = r["pedido"]
            labels.append(label)
        labels = labels or ["—"]
        self._ir_menu.configure(values=labels)
        self._ir_menu.set(labels[0])

    def _ir_refresh_periods(self) -> None:
        try:
            periods = self._ir.get_available_periods(self._ir_period, n=8)
        except Exception:
            logger.exception("No se pudieron calcular los periodos")
            periods = []
        self._ir_periods = {label: iso for label, iso in periods}
        labels = list(self._ir_periods.keys()) or ["—"]
        self._ir_menu.configure(values=labels)
        self._ir_menu.set(labels[0])

    def _ir_refdate(self):
        from datetime import datetime
        iso = self._ir_periods.get(self._ir_menu.get())
        return datetime.fromisoformat(iso) if iso else None

    def _ir_target(self):
        """Devuelve ('pedido', pedido) o ('period', (period, ref)) según el modo,
        o None si la selección no es válida."""
        if self._ir_mode == "pedido":
            pedido = self._ir_pedidos.get(self._ir_menu.get())
            return ("pedido", pedido) if pedido else None
        return ("period", (self._ir_period, self._ir_refdate()))

    def _ir_generate(self) -> None:
        target = self._ir_target()
        if target is None:
            self._ir_status.configure(text="✗  Selecciona un pedido", text_color=theme.RED)
            return
        self._ir_status.configure(text="⏳  Generando informe…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                if target[0] == "pedido":
                    path, _ = self._ir.generate_pedido(target[1])
                else:
                    period, ref = target[1]
                    path, _ = self._ir.generate(period, ref)
                self.after(0, lambda: self._ir_generated(path))
            except Exception as exc:
                logger.exception("Error generando informe interactivo")
                msg = str(exc)
                self.after(0, lambda: self._ir_status.configure(text=f"✗  {msg}", text_color=theme.RED))

        threading.Thread(target=worker, daemon=True).start()

    def _ir_generated(self, path) -> None:
        self._ir_last_path = path
        self._ir_status.configure(text=f"✓  Informe generado: {path.name}", text_color=theme.GREEN)
        try:
            webbrowser.open(path.as_uri())
        except Exception:
            logger.debug("No se pudo abrir el navegador", exc_info=True)
        ui.toast(self, "Informe listo", path.name, kind="success")

    def _ir_open_folder(self) -> None:
        try:
            os.startfile(str(self._ir.reports_dir()))  # noqa: S606 (Windows)
        except Exception as exc:
            ui.toast(self, "No se pudo abrir la carpeta", str(exc), kind="info")

    def _ir_send(self) -> None:
        raw = self._ir_to.get().strip()
        to = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
        if not to:
            ui.toast(self, "Sin destinatarios", "Indica al menos un email.", kind="info")
            return
        target = self._ir_target()
        if target is None:
            self._ir_status.configure(text="✗  Selecciona un pedido", text_color=theme.RED)
            return
        self._ir_status.configure(text="⏳  Enviando informe…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                if target[0] == "pedido":
                    self._ir.send_pedido_email(pedido=target[1], to=to)
                else:
                    period, ref = target[1]
                    self._ir.send_email(period=period, to=to, ref_date=ref)
                self.after(0, lambda: self._ir_sent(to))
            except Exception as exc:
                logger.exception("Error enviando informe interactivo")
                msg = str(exc)
                self.after(0, lambda: self._ir_status.configure(text=f"✗  {msg}", text_color=theme.RED))

        threading.Thread(target=worker, daemon=True).start()

    def _ir_sent(self, to) -> None:
        self._ir_status.configure(
            text=f"✓  Informe enviado a {len(to)} destinatario(s).", text_color=theme.GREEN)
        ui.toast(self, "Enviado", ", ".join(to), kind="success")
