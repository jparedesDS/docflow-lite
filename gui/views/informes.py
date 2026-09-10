"""Vista Analítica — cómo va la empresa, no solo la documentación.

Seis pestañas, de lo general a lo concreto:

  • Pulso          → una pantalla con el estado de toda la casa: cartera, ventas
                     mes a mes, actividad documental y un semáforo por área.
  • Documentación  → el ciclo de vida del documento: actividad mensual, cuánto
                     tarda el cliente en contestar y cuántas vueltas da un
                     documento hasta aprobarse.
  • Clientes       → quién contesta rápido y quién hace repetir el trabajo, en
                     un cuadrante, más el scorecard y el peso de cada uno.
  • Comercial      → el embudo de ofertas y los importes, que es lo que aporta
                     la BBDD del ERP y antes no se veía por ningún lado.
  • Operaciones    → taller, compras, calidad y almacén.
  • Equipo         → carga y rendimiento por responsable.

Los datos salen de `analytics` (documentación, de los Excel del monitoring) y de
`analytics_erp` (negocio y operaciones, del Postgres del ERP). Cada pestaña se
calcula en un hilo la primera vez que se abre. Los gráficos son `gui.widgets.charts`,
dibujados sobre Canvas: sin dependencias y se repintan al cambiar el tamaño.
"""

import logging
import threading

import customtkinter as ctk

from core.services import analytics as an
from core.services import analytics_erp as ae
from gui import theme
from gui.widgets import charts
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


def _fila(parent, n: int = 2, pady=(0, theme.SPACE_3)):
    """Fila de `n` columnas iguales para poner gráficos uno al lado del otro."""
    box = ctk.CTkFrame(parent, fg_color="transparent")
    box.pack(fill="x", pady=pady)
    for c in range(n):
        box.grid_columnconfigure(c, weight=1, uniform="fila")
    return box


def _celda(box, widget, col: int, row: int = 0):
    widget.grid(row=row, column=col, sticky="nsew",
                padx=(0 if col == 0 else theme.SPACE_3, 0))
    return widget


def _delta(actual: float, previo: float):
    """Variación en % respecto al periodo anterior (None si no hay con qué comparar)."""
    if not previo:
        return None
    return round(100 * (actual - previo) / previo)


def _dept_card(parent, titulo: str, cifras: list, color: str, nota: str = ""):
    """Tarjeta de área: un titular y dos o tres cifras con su rótulo."""
    card = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=12,
                        border_width=1, border_color=theme.BORDER)
    cab = ctk.CTkFrame(card, fg_color="transparent")
    cab.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_3, theme.SPACE_1))
    ctk.CTkFrame(cab, fg_color=color, width=4, height=15, corner_radius=2).pack(
        side="left", padx=(0, theme.SPACE_2))
    ctk.CTkLabel(cab, text=titulo.upper(), font=theme.FONT_LABEL,
                 text_color=theme.TEXT_SUB, anchor="w").pack(side="left")

    linea = ctk.CTkFrame(card, fg_color="transparent")
    linea.pack(fill="x", padx=theme.SPACE_3, pady=(0, 2))
    for i, (valor, etiqueta, col) in enumerate(cifras):
        celda = ctk.CTkFrame(linea, fg_color="transparent")
        celda.pack(side="left", padx=(0 if i == 0 else theme.SPACE_4, 0))
        ctk.CTkLabel(celda, text=str(valor), font=theme.font(20, "bold"),
                     text_color=col, anchor="w").pack(anchor="w")
        ctk.CTkLabel(celda, text=etiqueta.upper(), font=theme.font(9),
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
    ctk.CTkLabel(card, text=nota or " ", font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                 anchor="w", justify="left").pack(
        anchor="w", fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_3))
    return card


# ════════════════════════════════════════════════════════════════════════════
#  Vista principal
# ════════════════════════════════════════════════════════════════════════════

TABS = ("Pulso", "Documentación", "Clientes", "Comercial", "Operaciones", "Equipo")


class InformesView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._loaded: dict[str, bool] = {}
        self._build_layout()
        self.after(60, self._load_pulso)
        self._loaded["Pulso"] = True

    def _build_layout(self) -> None:
        ui.page_header(
            self, "Analítica",
            "El estado de la empresa con los datos del ERP: documentación, clientes, "
            "ofertas y operaciones.",
            help_key="informes")

        self.tabs = ui.tabview(self, command=self._on_tab)
        self.tabs.pack(fill="both", expand=True, padx=theme.SPACE_5,
                       pady=(theme.SPACE_3, theme.SPACE_4))

        self._scroll: dict[str, ScrollFrame] = {}
        self._status: dict[str, ctk.CTkLabel] = {}
        for nombre in TABS:
            tab = self.tabs.add(nombre)
            status = ctk.CTkLabel(tab, text="", font=theme.FONT_SMALL,
                                  text_color=theme.TEXT_MUTED, anchor="w")
            status.pack(fill="x", padx=theme.SPACE_2, pady=(theme.SPACE_2, theme.SPACE_1))
            scroll = ScrollFrame(tab)
            scroll.pack(fill="both", expand=True, padx=theme.SPACE_2, pady=(0, theme.SPACE_2))
            self._scroll[nombre] = scroll
            self._status[nombre] = status

    def _on_tab(self) -> None:
        sel = self.tabs.get()
        loaders = {
            "Pulso": self._load_pulso,
            "Documentación": self._load_documentacion,
            "Clientes": self._load_clientes,
            "Comercial": self._load_comercial,
            "Operaciones": self._load_operaciones,
            "Equipo": self._load_equipo,
        }
        loader = loaders.get(sel)
        if loader and not self._loaded.get(sel):
            self._loaded[sel] = True
            loader()

    # ── carga genérica en hilo ───────────────────────────────────────────────

    def _run(self, tab: str, fetch, render) -> None:
        status = self._status[tab]
        status.configure(text="⏳  Calculando…", text_color=theme.TEXT_MUTED)

        def worker():
            try:
                data = fetch()
                self.after(0, lambda: render(data))
            except Exception as exc:
                logger.exception("Error analítica (%s)", tab)
                msg = str(exc)
                self.after(0, lambda: status.configure(text=f"✗  {msg}", text_color=theme.RED))

        threading.Thread(target=worker, daemon=True).start()

    def _limpiar(self, tab: str) -> ScrollFrame:
        p = self._scroll[tab]
        for w in p.winfo_children():
            w.destroy()
        return p

    # ════════════════════════════════════════════════════════════════════════
    #  PULSO — el estado de toda la casa en una pantalla
    # ════════════════════════════════════════════════════════════════════════

    def _load_pulso(self) -> None:
        def fetch():
            eventos = an.doc_events()
            return {
                "resumen": an.get_summary(),
                "actividad": an.get_actividad_mensual(18, eventos),
                "ciclo": an.get_ciclo_respuesta(eventos),
                "mensual": ae.pedidos_mensuales(24),
                "cartera": ae.cartera(),
                "comercial": ae.comercial(),
                "ops": ae.operaciones(),
                "erp": ae.disponible(),
            }
        self._run("Pulso", fetch, self._render_pulso)

    def _render_pulso(self, d: dict) -> None:
        p = self._limpiar("Pulso")
        s, cartera, mensual, ops = d["resumen"], d["cartera"], d["mensual"], d["ops"]
        anios = d["comercial"]["por_anio"]
        año = anios[-1] if anios else {}

        fact = ops.get("facturas", {})
        nc = ops.get("nc", {})
        compras = ops.get("compras", {})
        taller = ops.get("taller", {})

        self._status["Pulso"].configure(
            text=("✓  Datos del ERP al día" if d["erp"] else
                  "⚠  El ERP no responde: solo se ve la parte de documentación"),
            text_color=theme.TEXT_MUTED if d["erp"] else theme.AMBER)

        ui.stat_strip(p, [
            (charts.fmt_eur(cartera["importe"]), "cartera abierta", theme.ACCENT,
             f"{cartera['pedidos']} pedidos · {cartera['fuera_plazo']} fuera de plazo"),
            (charts.fmt_eur(año.get("importe", 0)), f"pedidos {año.get('anio', '')}", theme.GREEN,
             f"{año.get('pedidos', 0)} pedidos"),
            (f"{año.get('tasa', 0):.0f}%".replace(".", ","), "ofertas adjudicadas", theme.BLUE,
             f"{año.get('ganadas', 0)} de {año.get('resueltas', 0)} resueltas"),
            (s["docs_riesgo"], "docs en riesgo", theme.RED if s["docs_riesgo"] else theme.GREEN,
             "críticos +15 días sin respuesta"),
            (charts.fmt_eur(fact.get("importe_pendiente", 0)), "por cobrar", theme.AMBER,
             f"{fact.get('pendientes', 0)} facturas"),
        ], pady=(0, theme.SPACE_4))

        # Ventas mes a mes + reparto de ofertas
        fila = _fila(p)
        _celda(fila, charts.LineChart(
            fila,
            series=[{"label": "Este año", "color": theme.ACCENT, "values": mensual["importes"]},
                    {"label": "Año anterior", "color": theme.BORDER_STRONG,
                     "values": mensual["importes_previo"]}],
            x_labels=mensual["labels"], unit=" €", height=210,
            title="Pedidos entrados por mes",
            subtitle="importe firmado · el mes en curso va incompleto"), 0)
        estados = d["comercial"]["por_estado"]
        colores = {"Adjudicada": theme.GREEN, "Perdida": theme.RED, "Presentada": theme.BLUE,
                   "Registrada": theme.BLUE, "Declinada": theme.TEXT_MUTED,
                   "Retirada": theme.TEXT_MUTED, "Budgetary": theme.AMBER,
                   "No Ofertada": theme.TEXT_MUTED}
        _celda(fila, charts.Donut(
            fila, [{"label": e["estado"], "value": e["n"],
                    "color": colores.get(e["estado"], theme.TEXT_MUTED)} for e in estados],
            center_label="ofertas", height=210,
            title="Ofertas por estado", subtitle=f"desde {ae.DESDE_ANIO}"), 1)

        # Actividad documental
        act = d["actividad"]
        charts.LineChart(
            p,
            series=[{"label": "Enviados", "color": theme.BLUE, "values": act["enviados"]},
                    {"label": "Aprobados", "color": theme.GREEN, "values": act["aprobados"]},
                    {"label": "Devueltos", "color": theme.AMBER, "values": act["devueltos"]}],
            x_labels=act["labels"], height=200, area=False,
            title="Actividad documental",
            subtitle="hechos con fecha del historial de revisiones del ERP",
        ).pack(fill="x", pady=(0, theme.SPACE_3))

        # Semáforo por área
        _section_header(p, "Cómo va cada área").pack(fill="x", pady=(0, theme.SPACE_2))
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x", pady=(0, theme.SPACE_3))
        for c in range(3):
            grid.grid_columnconfigure(c, weight=1, uniform="dept")

        ciclo = d["ciclo"]
        almacen = ops.get("almacen", {})
        equipos = ops.get("equipos", {})
        avales = ops.get("avales", {})
        horas = ops.get("horas", {})
        tarjetas = [
            ("Documentación", [
                (s["total_aprobados"], "aprobados", theme.GREEN),
                (s["total_enviados"], "en el cliente", theme.BLUE),
                (s["total_sin_enviar"], "sin enviar", theme.TEXT_MUTED)],
             theme.ACCENT,
             f"El cliente tarda {ciclo['mediana']} días de mediana en contestar"),
            ("Comercial", [
                (año.get("ofertas", 0), "ofertas", theme.TEXT_MAIN),
                (año.get("vivas", 0), "vivas", theme.BLUE),
                (f"{año.get('tasa', 0):.0f}%", "adjudicación", theme.GREEN)],
             theme.BLUE, f"Adjudicado {charts.fmt_eur(año.get('imp_ganadas', 0))} en {año.get('anio', '')}"),
            ("Taller", [
                (taller.get("abiertos", 0), "abiertos", theme.TEXT_MAIN),
                (taller.get("en_curso", 0), "en curso", theme.BLUE),
                (taller.get("retrasados", 0), "retrasados", theme.RED)],
             theme.AMBER,
             f"{charts.fmt_num(horas.get('total', 0))} h imputadas en el periodo"),
            ("Compras", [
                (compras.get("lineas", 0), "líneas", theme.TEXT_MAIN),
                (compras.get("retrasadas", 0), "retrasadas", theme.RED),
                (compras.get("proveedores", 0), "proveedores", theme.TEXT_SUB)],
             theme.ROSE,
             f"El mayor retraso va por {compras.get('retraso_max', 0)} días"),
            ("Calidad", [
                (nc.get("abiertas", 0), "NC abiertas", theme.RED if nc.get("abiertas") else theme.GREEN),
                (nc.get("ultimo_anio", 0), "este año", theme.TEXT_MAIN),
                (equipos.get("vencidos", 0), "equipos vencidos", theme.AMBER)],
             theme.GREEN, f"{nc.get('total', 0)} no conformidades registradas"),
            ("Administración", [
                (fact.get("pendientes", 0), "facturas", theme.AMBER),
                (avales.get("vencidos", 0), "avales vencidos", theme.RED),
                (almacen.get("en_almacen", 0), "en almacén", theme.TEXT_SUB)],
             theme.TEXT_SUB,
             f"La factura más vieja lleva {fact.get('mas_antigua', 0)} días sin cobrar"),
        ]
        for i, (titulo, cifras, color, nota) in enumerate(tarjetas):
            _dept_card(grid, titulo, cifras, color, nota).grid(
                row=i // 3, column=i % 3, sticky="nsew",
                padx=(0 if i % 3 == 0 else theme.SPACE_3, 0), pady=(0, theme.SPACE_3))

    # ════════════════════════════════════════════════════════════════════════
    #  DOCUMENTACIÓN
    # ════════════════════════════════════════════════════════════════════════

    def _load_documentacion(self) -> None:
        def fetch():
            eventos = an.doc_events()
            return {
                "resumen": an.get_summary(),
                "actividad": an.get_actividad_mensual(18, eventos),
                "ciclo": an.get_ciclo_respuesta(eventos),
                "retrabajo": an.get_retrabajo(eventos),
                "ultima": an.get_fecha_datos(eventos),
                "n_eventos": len(eventos),
            }
        self._run("Documentación", fetch, self._render_documentacion)

    def _render_documentacion(self, d: dict) -> None:
        p = self._limpiar("Documentación")
        s, act, ciclo, retra = d["resumen"], d["actividad"], d["ciclo"], d["retrabajo"]
        self._status["Documentación"].configure(
            text=f"✓  {d['n_eventos']} movimientos de documento · último el {d['ultima']}",
            text_color=theme.TEXT_MUTED)

        # KPIs con tendencia
        fila = _fila(p, 4, pady=(0, theme.SPACE_3))
        mensual = [v for v in ciclo["mediana_mensual"] if v is not None]
        _celda(fila, charts.trend_card(
            fila, "Respuesta del cliente", f"{ciclo['mediana']} d",
            _days_color(ciclo["mediana"]),
            f"mediana · media {ciclo['media']} d · p90 {ciclo['p90']} d · "
            f"la línea son los 12 meses cerrados",
            spark=ciclo["mediana_mensual"], subir_es_bueno=False,
            delta=_delta(mensual[-1], mensual[-2]) if len(mensual) > 1 else None), 0)
        _celda(fila, charts.trend_card(
            fila, "Dentro de 15 días", f"{ciclo['dentro_15']}%",
            _pct_color(ciclo["dentro_15"]), f"de {ciclo['n']} respuestas medidas"), 1)
        _celda(fila, charts.trend_card(
            fila, "Aprobado a la primera", f"{retra['pct_primera']}%",
            _pct_color(retra["pct_primera"]),
            f"{retra['a_la_primera']} de {retra['aprobados']} aprobados"), 2)
        _celda(fila, charts.trend_card(
            fila, "Envíos por documento", str(retra["media_envios"]).replace(".", ","),
            theme.AMBER if retra["media_envios"] > 1.5 else theme.GREEN,
            f"{retra['vueltas_extra']} envíos repetidos hasta aprobar"), 3)

        charts.LineChart(
            p,
            series=[{"label": "Enviados", "color": theme.BLUE, "values": act["enviados"]},
                    {"label": "Aprobados", "color": theme.GREEN, "values": act["aprobados"]},
                    {"label": "Devueltos", "color": theme.AMBER, "values": act["devueltos"]}],
            x_labels=act["labels"], height=210, area=False,
            title="Actividad mes a mes",
            subtitle=f"{act['total_enviados']} enviados · {act['total_aprobados']} aprobados "
                     f"· {act['total_devueltos']} devueltos · el mes en curso va incompleto",
        ).pack(fill="x", pady=(0, theme.SPACE_3))

        fila = _fila(p)
        _celda(fila, charts.BarChart(
            fila, [h["label"] for h in ciclo["histograma"]],
            [{"label": "Respuestas", "color": theme.ACCENT,
              "values": [h["value"] for h in ciclo["histograma"]]}],
            height=200, title="Cuánto tarda en volver un documento",
            subtitle="de cada envío a su respuesta"), 0)
        _celda(fila, charts.Donut(
            fila,
            [{"label": "Aprobado", "value": s["total_aprobados"], "color": theme.GREEN},
             {"label": "En el cliente", "value": s["total_enviados"], "color": theme.BLUE},
             {"label": "Con comentarios", "value": s["total_devoluciones"], "color": theme.AMBER},
             {"label": "Sin enviar", "value": s["total_sin_enviar"], "color": theme.TEXT_MUTED}],
            center_label="documentos", height=200,
            title="En qué punto está cada documento"), 1)

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

        _section_header(p, "Heatmap cliente × estado").pack(fill="x", pady=(0, theme.SPACE_2))
        self._heatmap_grid(p, s["heatmap_cliente"][:15])

    def _heatmap_grid(self, parent, rows: list[dict]) -> None:
        if not rows:
            ui.empty_state(parent, "Sin datos.", compact=True, anchor="w", pady=(0, theme.SPACE_3))
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
                txt_col = theme.TEXT_ON_ACCENT if (val > 0 and intensity > 0.45) else (
                    theme.TEXT_MAIN if val > 0 else theme.TEXT_MUTED)
                ctk.CTkLabel(grid, text=str(val), font=theme.font(11, "bold" if val > 0 else "normal"),
                             text_color=txt_col, fg_color=bg, corner_radius=6,
                             width=70, height=26).grid(row=i + 1, column=j + 1, padx=2, pady=1)
            ctk.CTkLabel(grid, text=str(r["total"]), font=theme.FONT_SMALL_BOLD,
                         text_color=theme.TEXT_SUB).grid(row=i + 1, column=len(cols) + 1, padx=2, pady=1)

    # ════════════════════════════════════════════════════════════════════════
    #  CLIENTES
    # ════════════════════════════════════════════════════════════════════════

    def _load_clientes(self) -> None:
        def fetch():
            eventos = an.doc_events()
            return {
                "cuadrante": an.get_clientes_cuadrante(eventos),
                "retrabajo": an.get_retrabajo(eventos),
                "score": an.get_scorecard(),
                "top": ae.top_clientes(),
                "ciclo": an.get_ciclo_respuesta(eventos),
            }
        self._run("Clientes", fetch, self._render_clientes)

    def _render_clientes(self, d: dict) -> None:
        p = self._limpiar("Clientes")
        cuad, score, top = d["cuadrante"], d["score"], d["top"]
        mediana_global = d["ciclo"]["mediana"]
        self._status["Clientes"].configure(
            text=f"✓  {len(cuad)} clientes con respuestas medidas · {len(score)} en el scorecard",
            text_color=theme.TEXT_MUTED)

        # Cuadrante: días de respuesta contra trabajo repetido
        puntos = []
        for c in cuad[:22]:
            if c["pct_primera"] is None:
                continue
            tarde = c["mediana"] > mediana_global
            repite = c["pct_primera"] < 50
            color = theme.RED if (tarde and repite) else (
                theme.AMBER if (tarde or repite) else theme.GREEN)
            puntos.append({"x": c["mediana"], "y": c["pct_primera"], "r": c["n"],
                           "label": c["cliente"][:14], "color": color})
        charts.Bubble(
            p, puntos, x_label="días hasta contestar (mediana) →",
            y_label="% aprobado a la primera", height=280,
            title="Quién contesta rápido y quién hace repetir el trabajo",
            subtitle="el tamaño es el número de respuestas · arriba a la izquierda es lo bueno",
        ).pack(fill="x", pady=(0, theme.SPACE_3))

        # Los que más trabajo repetido generan
        fila = _fila(p)
        peores = [r for r in d["retrabajo"]["por_cliente"] if r["total"] >= 10][:10]
        caja = ctk.CTkFrame(fila, fg_color=theme.BG_CARD, corner_radius=12,
                            border_width=1, border_color=theme.BORDER)
        _celda(fila, caja, 0)
        _section_header(caja, "Menos aprobados a la primera").pack(
            fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_3, theme.SPACE_1))
        inner = ctk.CTkFrame(caja, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_3))
        if peores:
            for r in peores:
                _bar_row(inner, r["cliente"][:22], r["pct"], r["pct"] / 100,
                         _pct_color(r["pct"]), value_text=f"{r['pct']}%")
        else:
            ui.empty_state(inner, "Sin datos", compact=True, pady=0)

        # Peso de cada cliente en la cartera
        caja2 = ctk.CTkFrame(fila, fg_color=theme.BG_CARD, corner_radius=12,
                             border_width=1, border_color=theme.BORDER)
        _celda(fila, caja2, 1)
        _section_header(caja2, "Clientes por importe de pedido").pack(
            fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_3, theme.SPACE_1))
        inner2 = ctk.CTkFrame(caja2, fg_color="transparent")
        inner2.pack(fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_3))
        if top:
            tope = max(r["importe"] for r in top) or 1
            for r in top[:10]:
                _bar_row(inner2, str(r["cliente"])[:22], r["importe"],
                         r["importe"] / tope, theme.ACCENT,
                         value_text=charts.fmt_eur(r["importe"]))
        else:
            ui.empty_state(inner2, "El ERP no responde", compact=True, pady=0)

        # Scorecard
        _section_header(p, "Scorecard de clientes").pack(fill="x", pady=(0, theme.SPACE_2))
        if score:
            avg = round(sum(r["score"] for r in score) / len(score), 1)
            best = max(score, key=lambda r: r["score"])
            worst = min(score, key=lambda r: r["score"])
            kdefs = [("Score medio", avg, _score_color(avg), "sobre 100"),
                     ("Mejor cliente", best["client"][:18], theme.GREEN, f"{best['score']} pts"),
                     ("Peor cliente", worst["client"][:18], theme.RED, f"{worst['score']} pts")]
            kgrid = _fila(p, 3)
            for i, (lb, val, col, sub) in enumerate(kdefs):
                _celda(kgrid, _kpi_card(kgrid, lb, val, col, sub), i)

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
    #  COMERCIAL
    # ════════════════════════════════════════════════════════════════════════

    def _load_comercial(self) -> None:
        self._run("Comercial",
                  lambda: {"c": ae.comercial(), "mensual": ae.pedidos_mensuales(24),
                           "cartera": ae.cartera(), "erp": ae.disponible()},
                  self._render_comercial)

    def _render_comercial(self, d: dict) -> None:
        p = self._limpiar("Comercial")
        c, mensual = d["c"], d["mensual"]
        anios = c["por_anio"]
        if not anios:
            self._status["Comercial"].configure(
                text="✗  El ERP no responde: esta pestaña sale de su base de datos",
                text_color=theme.AMBER)
            ui.empty_state(p, "Sin conexión con el ERP",
                           "Revisa Ajustes ▸ Fuentes de datos.")
            return

        año = anios[-1]
        previo = anios[-2] if len(anios) > 1 else {}
        self._status["Comercial"].configure(
            text=f"✓  {sum(a['ofertas'] for a in anios)} ofertas desde {anios[0]['anio']} · "
                 f"la tasa de adjudicación solo cuenta las resueltas (ganadas frente a perdidas)",
            text_color=theme.TEXT_MUTED)

        ui.stat_strip(p, [
            (año["ofertas"], f"ofertas {año['anio']}", theme.TEXT_MAIN,
             f"{año['vivas']} aún sin resolver"),
            (f"{año['tasa']:.0f}%".replace(".", ","), "adjudicación", _pct_color(año["tasa"]),
             f"{año['ganadas']} ganadas · {año['perdidas']} perdidas"),
            (charts.fmt_eur(año["imp_ganadas"]), "adjudicado", theme.GREEN,
             f"de {charts.fmt_eur(año['of_importe'])} ofertados"),
            (año["pedidos"], "pedidos", theme.BLUE, charts.fmt_eur(año["importe"])),
            (charts.fmt_eur(d["cartera"]["importe"]), "cartera abierta", theme.ACCENT,
             f"{d['cartera']['pedidos']} pedidos vivos"),
        ], pady=(0, theme.SPACE_4))

        etiquetas = [str(a["anio"]) for a in anios]
        fila = _fila(p)
        _celda(fila, charts.BarChart(
            fila, etiquetas,
            [{"label": "Ganadas", "color": theme.GREEN, "values": [a["ganadas"] for a in anios]},
             {"label": "Perdidas", "color": theme.RED, "values": [a["perdidas"] for a in anios]},
             {"label": "Vivas", "color": theme.BLUE, "values": [a["vivas"] for a in anios]}],
            height=210, title="Ofertas por año",
            subtitle="las vivas del año en curso aún pueden caer de cualquier lado"), 0)
        _celda(fila, charts.LineChart(
            fila,
            series=[{"label": "Adjudicación", "color": theme.ACCENT,
                     "values": [a["tasa"] for a in anios]}],
            x_labels=etiquetas, unit="%", height=210,
            title="Tasa de adjudicación",
            subtitle="ganadas ÷ (ganadas + perdidas)"), 1)

        charts.LineChart(
            p,
            series=[{"label": "Este año", "color": theme.ACCENT, "values": mensual["importes"]},
                    {"label": "Año anterior", "color": theme.BORDER_STRONG,
                     "values": mensual["importes_previo"]}],
            x_labels=mensual["labels"], unit=" €", height=210,
            title="Importe de pedidos por mes",
            subtitle="frente al mismo mes del año anterior · el mes en curso va incompleto",
        ).pack(fill="x", pady=(0, theme.SPACE_3))

        # Mercado + comerciales
        fila = _fila(p)
        mercado = [m for m in c["mercado"] if m["ofertas"] > 10]
        _celda(fila, charts.BarChart(
            fila, [m["mercado"] for m in mercado],
            [{"label": "Adjudicación", "color": theme.ACCENT,
              "values": [m["tasa"] for m in mercado]}],
            unit="%", height=200, title="Nacional frente a exterior",
            subtitle="tasa de adjudicación por mercado"), 0)
        _celda(fila, charts.Donut(
            fila, [{"label": m["mercado"], "value": m["ofertas"],
                    "color": c_} for m, c_ in zip(mercado, (theme.ACCENT, theme.BLUE, theme.TEXT_MUTED))],
            center_label="ofertas", height=200, title="Reparto por mercado"), 1)

        _section_header(p, "Por comercial").pack(fill="x", pady=(0, theme.SPACE_2))
        cols = ["Comercial", "Ofertas", "Ganadas", "Perdidas", "Vivas", "Adjudicación", "Adjudicado"]
        filas = [r for r in c["por_comercial"] if r["ofertas"] >= 5]
        host = _table_host(p, _tbl_height(len(filas)))
        t = DataTable(host, columns=cols)
        t.pack(fill="both", expand=True)
        t.set_columns_anchor({c_: ("w" if c_ == "Comercial" else "center") for c_ in cols})
        t.tree.tag_configure("ok", foreground=theme.GREEN)
        t.tree.tag_configure("warn", foreground=theme.AMBER)
        t.tree.tag_configure("bad", foreground=theme.RED)
        for i, r in enumerate(filas):
            tier = "ok" if r["tasa"] >= 70 else ("warn" if r["tasa"] >= 45 else "bad")
            t.add_row(values=[r["iniciales"], r["ofertas"], r["ganada"], r["perdida"],
                              r["viva"], f"{r['tasa']:.0f}%".replace(".", ","),
                              charts.fmt_eur(r["imp_ganadas"])],
                      iid=f"cm_{i}", tags=(tier,))
        t.autofit_columns(max_per={"Comercial": 120})

        if previo:
            var = _delta(año["importe"], previo["importe"])
            ctk.CTkLabel(
                p, text=(f"En {año['anio']} se llevan {charts.fmt_eur(año['importe'])} en pedidos"
                         + (f", un {abs(var)}% {'más' if var >= 0 else 'menos'} que en "
                            f"{previo['anio']} a año cerrado." if var is not None else ".")),
                font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w").pack(
                fill="x", pady=(0, theme.SPACE_3))

    # ════════════════════════════════════════════════════════════════════════
    #  OPERACIONES
    # ════════════════════════════════════════════════════════════════════════

    def _load_operaciones(self) -> None:
        self._run("Operaciones",
                  lambda: {"ops": ae.operaciones(), "nc": ae.nc_por_anio(),
                           "erp": ae.disponible()},
                  self._render_operaciones)

    def _render_operaciones(self, d: dict) -> None:
        p = self._limpiar("Operaciones")
        ops = d["ops"]
        if not d["erp"]:
            self._status["Operaciones"].configure(
                text="✗  El ERP no responde: esta pestaña sale de su base de datos",
                text_color=theme.AMBER)
            ui.empty_state(p, "Sin conexión con el ERP", "Revisa Ajustes ▸ Fuentes de datos.")
            return

        taller = ops.get("taller", {})
        horas = ops.get("horas", {})
        compras = ops.get("compras", {})
        nc = ops.get("nc", {})
        equipos = ops.get("equipos", {})
        almacen = ops.get("almacen", {})
        ultima = horas.get("ultima")
        self._status["Operaciones"].configure(
            text=("✓  Taller, compras, calidad y almacén" +
                  (f" · última imputación de horas el {ultima:%d/%m/%Y}" if ultima else "")),
            text_color=theme.TEXT_MUTED)

        ui.stat_strip(p, [
            (taller.get("abiertos", 0), "pedidos en taller", theme.ACCENT,
             f"{taller.get('en_curso', 0)} en curso"),
            (taller.get("retrasados", 0), "retrasados",
             theme.RED if taller.get("retrasados") else theme.GREEN,
             f"el peor, {taller.get('retraso_max', 0)} días"),
            (charts.fmt_num(horas.get("total", 0)), "horas de taller", theme.BLUE,
             f"{charts.fmt_num(horas.get('imputadas', 0))} imputadas a pedido"),
            (compras.get("retrasadas", 0), "compras retrasadas",
             theme.RED if compras.get("retrasadas") else theme.GREEN,
             f"de {compras.get('lineas', 0)} líneas"),
            (nc.get("abiertas", 0), "NC sin cerrar",
             theme.AMBER if nc.get("abiertas") else theme.GREEN,
             f"{nc.get('abiertas_anio', 0)} de este año"),
        ], pady=(0, theme.SPACE_4))

        fila = _fila(p)
        anios_nc = d["nc"]
        _celda(fila, charts.BarChart(
            fila, [str(r["anio"]) for r in anios_nc],
            [{"label": "No conformidades", "color": theme.ROSE,
              "values": [r["n"] for r in anios_nc]}],
            height=200, title="No conformidades por año",
            subtitle=f"{nc.get('total', 0)} en total · {nc.get('cliente', 0)} las detectó el cliente"), 0)

        operaciones = horas.get("por_operacion", [])[:9]
        caja = ctk.CTkFrame(fila, fg_color=theme.BG_CARD, corner_radius=12,
                            border_width=1, border_color=theme.BORDER)
        _celda(fila, caja, 1)
        _section_header(caja, "Horas por operación").pack(
            fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_3, theme.SPACE_1))
        inner = ctk.CTkFrame(caja, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_3, pady=(0, theme.SPACE_3))
        if operaciones:
            tope = max(o["horas"] for o in operaciones) or 1
            for o in operaciones:
                _bar_row(inner, str(o["operacion"])[3:][:22], o["horas"],
                         o["horas"] / tope, theme.BLUE,
                         value_text=charts.fmt_num(o["horas"]) + " h")
        else:
            ui.empty_state(inner, "Sin imputaciones", compact=True, pady=0)

        # Detalle por área
        _section_header(p, "Detalle por área").pack(fill="x", pady=(0, theme.SPACE_2))
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x", pady=(0, theme.SPACE_3))
        for c in range(2):
            grid.grid_columnconfigure(c, weight=1, uniform="ops")
        tarjetas = [
            ("Taller", [
                (taller.get("abiertos", 0), "abiertos", theme.TEXT_MAIN),
                (taller.get("sin_empezar", 0), "sin empezar", theme.AMBER),
                (taller.get("antiguos", 0), "zombis", theme.TEXT_MUTED)],
             theme.AMBER,
             "Los «zombis» son pedidos con fechas imposibles del ERP; no cuentan como retraso."),
            ("Compras", [
                (compras.get("lineas", 0), "líneas", theme.TEXT_MAIN),
                (compras.get("pronto", 0), "llegan pronto", theme.BLUE),
                (compras.get("pedidos", 0), "pedidos afectados", theme.TEXT_SUB)],
             theme.ROSE, f"{compras.get('proveedores', 0)} proveedores implicados"),
            ("Calidad", [
                (nc.get("total", 0), "NC", theme.TEXT_MAIN),
                (nc.get("abiertas", 0), "sin cerrar", theme.RED),
                (equipos.get("vencidos", 0), "equipos vencidos", theme.AMBER)],
             theme.GREEN,
             f"{equipos.get('total', 0)} equipos de medida · {equipos.get('pronto', 0)} caducan pronto"),
            ("Almacén", [
                (almacen.get("en_almacen", 0), "en almacén", theme.TEXT_MAIN),
                (almacen.get("atascados", 0), "atascados", theme.RED),
                (f"{almacen.get('pct_semana', 0)}%", "salen en 7 días", theme.GREEN)],
             theme.BLUE,
             f"Lo más viejo lleva {almacen.get('dias_max', 0)} días esperando"),
        ]
        for i, (titulo, cifras, color, nota) in enumerate(tarjetas):
            _dept_card(grid, titulo, cifras, color, nota).grid(
                row=i // 2, column=i % 2, sticky="nsew",
                padx=(0 if i % 2 == 0 else theme.SPACE_3, 0), pady=(0, theme.SPACE_3))

    # ════════════════════════════════════════════════════════════════════════
    #  EQUIPO — rendimiento + carga
    # ════════════════════════════════════════════════════════════════════════

    def _load_equipo(self) -> None:
        # get_team_workload ya calcula el ranking internamente (members) → no
        # lo pedimos por separado para no recorrer el dataset dos veces.
        self._run("Equipo",
                  lambda: {"workload": an.get_team_workload(),
                           "overview": an.get_team_overview(),
                           "matriz": an.get_matriz_comercial()},
                  self._render_equipo)

    def _render_equipo(self, d: dict) -> None:
        p = self._limpiar("Equipo")
        wl = d["workload"]
        ranking = sorted(wl["members"], key=lambda x: x["pct"], reverse=True)
        overview = d["overview"]
        matriz = d["matriz"]
        self._status["Equipo"].configure(
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
                     text_color=theme.TEXT_ON_ACCENT).pack(expand=True)
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
            ui.empty_state(parent, "Sin datos.", compact=True, anchor="w", pady=(0, theme.SPACE_3))
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
