"""Motor de informes HTML: la carrocería común de todos los informes de análisis.

Un informe se compone, no se escribe a mano:

    doc = report_kit.Report("Documentación", "Cómo va el ciclo del documento")
    doc.titular("El cliente tarda 14 días de mediana en contestar", ["…", "…"])
    s = doc.seccion("Ritmo", "cuánto entra y cuánto sale")
    s.kpis([...]); s.linea(...); s.tabla(...)
    html = doc.render()

El resultado es UN archivo .html que funciona sin conexión (Chart.js va dentro),
se puede archivar, mandar por correo e imprimir a PDF.

Criterios de diseño, tomados de las guías de Datawrapper y del Visual Vocabulary
del Financial Times (ver README del módulo de informes):

· **El título dice el hallazgo, no la dimensión.** «El cliente tarda 14 días» en
  vez de «Días de respuesta». Lo primero que se lee tiene que ser la conclusión.
· **El gris es el color más importante.** Se colorea solo lo que significa algo
  —verde bien, ámbar aviso, rojo mal, acento lo nuestro—; el resto va en gris
  para que el color destaque de verdad.
· **Etiquetar al lado del dato** en vez de leyendas que obligan a ir y volver.
· **Dos niveles de jerarquía** por bloque, no más.
· **Cifras abreviadas** (1,2 M €) y la unidad repetida en ejes y notas.
· **Nunca rotar los rótulos del eje**: si no caben, se saltan o se cambia a barras
  horizontales.
· **El gráfico según el mensaje**: evolución → línea; ranking → barras ordenadas;
  parte de un todo → apilada o anillo; relación → dispersión; reparto → histograma;
  desviación → barras divergentes.
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from core.paths import resource_path
from core.utils.fmt import eur, num, pct  # noqa: F401 — reexport para los informes

logger = logging.getLogger(__name__)

# Paleta: la misma de la app, para que el informe y la pantalla se reconozcan.
INK, SUB, MUTED, LINE = "#0F172A", "#475569", "#94A3B8", "#E2E8F0"
BG, CARD = "#F6F7FB", "#FFFFFF"
ACCENT = "#4F46E5"
GREEN, AMBER, RED, BLUE, ROSE, GREY = "#16A34A", "#D97706", "#DC2626", "#2563EB", "#DB2777", "#94A3B8"

COLOR = {"ok": GREEN, "aviso": AMBER, "mal": RED, "info": BLUE,
         "acento": ACCENT, "neutro": GREY, "rosa": ROSE}

_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def esc(v) -> str:
    return html.escape(str(v), quote=True)


def _chartjs() -> str:
    """Chart.js embebido para que el informe funcione sin conexión."""
    try:
        return resource_path("assets/vendor/chart.umd.min.js").read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.warning("Chart.js no encontrado en assets/vendor; el informe usará el CDN")
        return ""


def color_pct(p: float, bueno: float = 75, regular: float = 50) -> str:
    return GREEN if p >= bueno else (AMBER if p >= regular else RED)


def color_dias(d: float, bien: float = 15, regular: float = 30) -> str:
    return GREEN if d <= bien else (AMBER if d <= regular else RED)


# ════════════════════════════════════════════════════════════════════════════
#  Bloques
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class Bloque:
    html: str = ""
    chart: tuple | None = None           # (canvas_id, config) para el payload JS


class Seccion:
    """Un apartado del informe: título, nota y los bloques que lo componen."""

    def __init__(self, doc: "Report", titulo: str, nota: str = ""):
        self.doc = doc
        self.titulo = titulo
        self.nota = nota
        self.bloques: list[Bloque] = []

    # ── Texto ────────────────────────────────────────────────────────────────

    def nota_pie(self, texto: str) -> "Seccion":
        self.bloques.append(Bloque(f'<p class="nota">{texto}</p>'))
        return self

    def aviso(self, texto: str, tipo: str = "info") -> "Seccion":
        """Recuadro con el hallazgo destacado. `tipo` ∈ info | ok | aviso | mal."""
        self.bloques.append(Bloque(
            f'<div class="callout {esc(tipo)}"><p>{texto}</p></div>'))
        return self

    # ── Cifras ───────────────────────────────────────────────────────────────

    def kpis(self, tarjetas: list[dict]) -> "Seccion":
        """Fila de métricas: {valor, etiqueta, nota, color, delta, delta_bueno}."""
        celdas = []
        for k in tarjetas:
            delta = ""
            if k.get("delta") is not None:
                d = k["delta"]
                sube = d >= 0
                mejora = sube == k.get("delta_bueno", True)
                delta = (f'<span class="delta {"up" if mejora else "down"}">'
                         f'{"▲" if sube else "▼"} {abs(d):.0f}%</span>'.replace(".", ","))
            celdas.append(
                f'<div class="kpi"><p class="kpi-lab">{esc(k["etiqueta"])}</p>'
                f'<p class="kpi-val" style="color:{k.get("color", INK)}">'
                f'{esc(k["valor"])}{delta}</p>'
                f'<p class="kpi-sub">{esc(k.get("nota", ""))}</p></div>')
        self.bloques.append(Bloque(f'<div class="kpis">{"".join(celdas)}</div>'))
        return self

    # ── Gráficos (Chart.js) ──────────────────────────────────────────────────

    def _chart(self, titulo: str, nota: str, config: dict, alto: int = 260,
               leyenda: list | None = None, ancho: str = "full") -> "Seccion":
        cid = f"c{len(self.doc._charts)}"
        leg = ""
        if leyenda:
            chips = "".join(f'<span><i style="background:{c}"></i>{esc(t)}</span>'
                            for t, c in leyenda)
            leg = f'<div class="legend">{chips}</div>'
        self.bloques.append(Bloque(
            f'<figure class="card chart {ancho}">'
            f'<figcaption><h3>{esc(titulo)}</h3>'
            f'{f"<p>{esc(nota)}</p>" if nota else ""}</figcaption>'
            f'{leg}<div class="canvas" style="height:{alto}px">'
            f'<canvas id="{cid}"></canvas></div></figure>',
            chart=(cid, config)))
        self.doc._charts.append(cid)
        return self

    def linea(self, titulo: str, nota: str, labels: list, series: list,
              unidad: str = "", alto: int = 260, area: bool = False,
              ancho: str = "full") -> "Seccion":
        """Evolución en el tiempo. `series` = [{label, color, valores}]."""
        datasets = [{
            "label": s["label"], "data": s["valores"], "borderColor": s["color"],
            "backgroundColor": (s["color"] + "22") if area else s["color"],
            "fill": bool(area), "tension": 0.25, "borderWidth": 2,
            "pointRadius": 2.5, "pointHoverRadius": 5,
        } for s in series]
        return self._chart(titulo, nota, {
            "type": "line",
            "data": {"labels": labels, "datasets": datasets},
            "options": {"unidad": unidad, "ejeY": True},
        }, alto=alto, ancho=ancho,
            leyenda=[(s["label"], s["color"]) for s in series] if len(series) > 1 else None)

    def barras(self, titulo: str, nota: str, labels: list, series: list,
               unidad: str = "", alto: int = 260, apiladas: bool = False,
               ancho: str = "full") -> "Seccion":
        """Magnitud o parte de un todo. `series` = [{label, color, valores}]."""
        datasets = [{"label": s["label"], "data": s["valores"],
                     "backgroundColor": s["color"], "borderRadius": 3,
                     "maxBarThickness": 46} for s in series]
        return self._chart(titulo, nota, {
            "type": "bar",
            "data": {"labels": labels, "datasets": datasets},
            "options": {"unidad": unidad, "ejeY": True, "apiladas": apiladas},
        }, alto=alto, ancho=ancho,
            leyenda=[(s["label"], s["color"]) for s in series] if len(series) > 1 else None)

    def divergente(self, titulo: str, nota: str, filas: list, unidad: str = "",
                   alto: int | None = None, ancho: str = "full") -> "Seccion":
        """Desviación respecto a cero: barras horizontales a un lado y al otro.

        `filas` = [{label, valor, color}]. Es el gráfico que toca cuando lo que
        importa es cuánto se separa algo de su referencia, no su valor absoluto.
        """
        alto = alto or max(180, 26 * len(filas) + 40)
        return self._chart(titulo, nota, {
            "type": "bar",
            "data": {"labels": [f["label"] for f in filas],
                     "datasets": [{"data": [f["valor"] for f in filas],
                                   "backgroundColor": [f.get("color", ACCENT) for f in filas],
                                   "borderRadius": 3, "maxBarThickness": 18}]},
            "options": {"unidad": unidad, "horizontal": True, "cero": True},
        }, alto=alto, ancho=ancho)

    def anillo(self, titulo: str, nota: str, trozos: list, centro: str = "",
               alto: int = 260, ancho: str = "half") -> "Seccion":
        """Parte de un todo. `trozos` = [{label, valor, color}]."""
        vivos = [t for t in trozos if t["valor"] > 0]
        total = sum(t["valor"] for t in vivos)
        return self._chart(titulo, nota, {
            "type": "doughnut",
            "data": {"labels": [t["label"] for t in vivos],
                     "datasets": [{"data": [t["valor"] for t in vivos],
                                   "backgroundColor": [t["color"] for t in vivos],
                                   "borderWidth": 0}]},
            "options": {"anillo": True, "centro": centro or num(total)},
        }, alto=alto, ancho=ancho,
            leyenda=[(f'{t["label"]} · {num(t["valor"])}', t["color"]) for t in vivos])

    def dispersion(self, titulo: str, nota: str, puntos: list, eje_x: str,
                   eje_y: str, alto: int = 320, diagonal: bool = False,
                   ancho: str = "full") -> "Seccion":
        """Relación entre dos variables. `puntos` = [{x, y, r, label, color}]."""
        return self._chart(titulo, nota, {
            "type": "bubble",
            "data": {"datasets": [{
                "data": [{"x": p["x"], "y": p["y"], "r": p.get("r", 6),
                          "nombre": p.get("label", "")} for p in puntos],
                "backgroundColor": [p.get("color", ACCENT) + "66" for p in puntos],
                "borderColor": [p.get("color", ACCENT) for p in puntos],
                "borderWidth": 1.5}]},
            "options": {"ejeXTitulo": eje_x, "ejeYTitulo": eje_y, "diagonal": diagonal},
        }, alto=alto, ancho=ancho)

    # ── Ranking en HTML (sin JS: se imprime bien y se lee sin gráfico) ───────

    def ranking(self, titulo: str, nota: str, filas: list, unidad: str = "",
                ancho: str = "half") -> "Seccion":
        """Barras horizontales en HTML. `filas` = [{label, valor, texto, color}]."""
        tope = max((abs(f["valor"]) for f in filas), default=1) or 1
        cuerpo = []
        for f in filas:
            ancho_pct = max(1.5, abs(f["valor"]) / tope * 100)
            cuerpo.append(
                f'<div class="rank-row"><span class="rank-lab">{esc(f["label"])}</span>'
                f'<span class="rank-track"><i style="width:{ancho_pct:.1f}%;'
                f'background:{f.get("color", ACCENT)}"></i></span>'
                f'<span class="rank-val" style="color:{f.get("color", INK)}">'
                f'{esc(f.get("texto", num(f["valor"]) + unidad))}</span></div>')
        self.bloques.append(Bloque(
            f'<div class="card {ancho}"><h3>{esc(titulo)}</h3>'
            f'{f"<p class=\'sub\'>{esc(nota)}</p>" if nota else ""}'
            f'<div class="rank">{"".join(cuerpo)}</div></div>'))
        return self

    # ── Tabla ────────────────────────────────────────────────────────────────

    def tabla(self, titulo: str, columnas: list, filas: list, nota: str = "",
              buscador: bool = True, vacio: str = "Sin datos.") -> "Seccion":
        """Tabla ordenable y filtrable.

        `columnas` = [{"t": título, "num": bool, "w": ancho opcional}]
        `filas`    = [[celda, …]] donde cada celda es str o {"v": valor, "color", "bold"}
        """
        cabecera = "".join(
            f'<th data-sort="{"num" if c.get("num") else "text"}"'
            f'{f" style=\'width:{c[chr(119)]}\'" if c.get("w") else ""}>{esc(c["t"])}</th>'
            for c in columnas)
        cuerpo = []
        for fila in filas:
            celdas = []
            for i, celda in enumerate(fila):
                col = columnas[i] if i < len(columnas) else {}
                estilo = "text-align:center;" if col.get("num") else ""
                if isinstance(celda, dict):
                    if celda.get("color"):
                        estilo += f'color:{celda["color"]};'
                    if celda.get("bold"):
                        estilo += "font-weight:600;"
                    texto = esc(celda.get("v", ""))
                else:
                    texto = esc(celda)
                clase = ' class="mono"' if col.get("mono") else ""
                celdas.append(f'<td{clase} style="{estilo}">{texto}</td>')
            cuerpo.append(f'<tr>{"".join(celdas)}</tr>')
        if not cuerpo:
            cuerpo = [f'<tr><td colspan="{len(columnas)}" class="empty">{esc(vacio)}</td></tr>']
        herramientas = (
            '<div class="tbl-tools"><input class="tbl-search" type="text" '
            'placeholder="Buscar…"><span class="tbl-count"></span>'
            '<span class="tbl-hint">· clic en una columna para ordenar</span></div>'
            if buscador else "")
        self.bloques.append(Bloque(
            f'<div class="card tbl-panel"><h3>{esc(titulo)}</h3>'
            f'{f"<p class=\'sub\'>{esc(nota)}</p>" if nota else ""}'
            f'{herramientas}<table><thead><tr>{cabecera}</tr></thead>'
            f'<tbody>{"".join(cuerpo)}</tbody></table></div>'))
        return self


# ════════════════════════════════════════════════════════════════════════════
#  Documento
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class Report:
    titulo: str
    subtitulo: str = ""
    etiqueta: str = "Análisis"
    periodo: str = ""
    fuentes: str = ""
    secciones: list = field(default_factory=list)
    _charts: list = field(default_factory=list)
    _titular: str = ""
    _puntos: list = field(default_factory=list)

    def titular(self, texto: str, puntos: list | None = None) -> "Report":
        """El resumen en palabras: lo que hay que saber sin mirar un gráfico."""
        self._titular = texto
        self._puntos = puntos or []
        return self

    def seccion(self, titulo: str, nota: str = "") -> Seccion:
        s = Seccion(self, titulo, nota)
        self.secciones.append(s)
        return s

    # ── Render ───────────────────────────────────────────────────────────────

    def render(self) -> str:
        ahora = datetime.now()
        periodo = self.periodo or f"{_MESES[ahora.month - 1].capitalize()} {ahora.year}"

        nav = "".join(
            f'<a href="#s{i}">{esc(s.titulo)}</a>'
            for i, s in enumerate(self.secciones))

        cuerpo, payload = [], {}
        for i, s in enumerate(self.secciones):
            bloques = []
            for b in s.bloques:
                bloques.append(b.html)
                if b.chart:
                    payload[b.chart[0]] = b.chart[1]
            cuerpo.append(
                f'<section id="s{i}"><div class="sec-head"><h2>'
                f'<span class="sec-num">{i + 1:02d}</span>{esc(s.titulo)}</h2>'
                f'{f"<p>{esc(s.nota)}</p>" if s.nota else ""}</div>'
                f'<div class="grid">{"".join(bloques)}</div></section>')

        puntos = ""
        if self._puntos:
            puntos = ("<ul>" + "".join(f"<li>{p}</li>" for p in self._puntos) + "</ul>")
        titular = ""
        if self._titular:
            titular = (f'<div class="titular"><p class="lead">{self._titular}</p>{puntos}</div>')

        chartjs = _chartjs()
        tag = (f"<script>{chartjs}</script>" if chartjs else
               '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>')

        return (
            "<!DOCTYPE html>\n<html lang=\"es\">\n<head>\n"
            '<meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f"<title>{esc(self.titulo)} · {esc(periodo)}</title>\n"
            f"<style>{_CSS}</style>\n</head>\n<body>\n"
            '<header class="top">\n  <div class="wrap hd">\n'
            '    <div class="brand"><span class="mark">◆</span>'
            f'<span><b>DocFlow</b> · {esc(self.etiqueta)}</span></div>\n'
            '    <button class="pdf no-print" onclick="window.print()">Descargar PDF</button>\n'
            "  </div>\n</header>\n"
            '<div class="wrap">\n'
            f"  <h1>{esc(self.titulo)}</h1>\n"
            f'  <p class="dek">{esc(self.subtitulo)}</p>\n'
            f'  <p class="meta">{esc(periodo)} · generado el '
            f'{ahora.strftime("%d/%m/%Y a las %H:%M")}</p>\n'
            f"  {titular}\n"
            f'  <nav class="toc no-print">{nav}</nav>\n'
            f'  {"".join(cuerpo)}\n'
            '  <footer>\n'
            f'    <p>{esc(self.fuentes or "Datos del ERP de EIPSA y del seguimiento de documentación.")}</p>\n'
            '    <p>DocFlow · informe generado automáticamente</p>\n'
            "  </footer>\n</div>\n"
            f"{tag}\n<script>var PAYLOAD={json.dumps(payload, ensure_ascii=False)};{_CHART_JS}</script>\n"
            f"<script>{_TABLE_JS}</script>\n</body>\n</html>"
        )


# ════════════════════════════════════════════════════════════════════════════
#  Hoja de estilo
# ════════════════════════════════════════════════════════════════════════════

_CSS = """
:root{--ink:#0F172A;--sub:#475569;--muted:#94A3B8;--line:#E2E8F0;--bg:#F6F7FB;
      --card:#FFFFFF;--accent:#4F46E5;--accent-soft:#EEF2FF;}
*{box-sizing:border-box;}
body{margin:0;background:var(--bg);color:var(--ink);font-size:15px;line-height:1.6;
     font-family:'Segoe UI',system-ui,-apple-system,Roboto,Arial,sans-serif;
     -webkit-font-smoothing:antialiased;}
.wrap{max-width:1080px;margin:0 auto;padding:0 24px;}
header.top{background:var(--ink);color:#fff;position:sticky;top:0;z-index:30;}
header.top .hd{display:flex;align-items:center;justify-content:space-between;height:52px;}
.brand{display:flex;align-items:center;gap:10px;font-size:14px;letter-spacing:.01em;}
.brand .mark{width:24px;height:24px;border-radius:6px;background:var(--accent);
             display:inline-flex;align-items:center;justify-content:center;font-size:12px;}
.pdf{font:inherit;font-size:13px;font-weight:600;color:var(--ink);background:#fff;
     border:0;border-radius:7px;padding:7px 14px;cursor:pointer;}
.pdf:hover{background:#E2E8F0;}
h1{font-size:32px;line-height:1.2;letter-spacing:-.02em;margin:34px 0 6px;}
.dek{margin:0;font-size:17px;color:var(--sub);max-width:70ch;}
.meta{margin:8px 0 0;font-size:13px;color:var(--muted);}
.titular{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);
         border-radius:0 12px 12px 0;padding:20px 24px;margin:24px 0 8px;}
.titular .lead{margin:0;font-size:18px;line-height:1.55;font-weight:600;letter-spacing:-.01em;}
.titular ul{margin:12px 0 0;padding-left:20px;color:var(--sub);font-size:14.5px;}
.titular li{margin:5px 0;}
.titular b{color:var(--ink);}
.toc{display:flex;flex-wrap:wrap;gap:6px;margin:22px 0 8px;padding:8px 0;
     border-top:1px solid var(--line);border-bottom:1px solid var(--line);}
.toc a{font-size:12.5px;color:var(--sub);text-decoration:none;padding:5px 11px;
       border-radius:20px;white-space:nowrap;}
.toc a:hover{background:var(--accent-soft);color:var(--accent);}
section{margin:38px 0 0;scroll-margin-top:64px;}
.sec-head h2{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:var(--accent);
             margin:0;font-weight:700;display:flex;align-items:baseline;gap:10px;}
.sec-num{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums;}
.sec-head p{margin:4px 0 0;font-size:14px;color:var(--sub);}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:14px;}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;
      grid-column:span 2;min-width:0;}
.card.half{grid-column:span 1;}
.card h3{margin:0;font-size:15px;letter-spacing:-.01em;line-height:1.35;}
.card .sub,figcaption p{margin:4px 0 0;font-size:13px;color:var(--muted);}
figure.chart{margin:0;}
figure.chart figcaption{margin-bottom:12px;}
.canvas{position:relative;}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:0 0 10px;font-size:12.5px;color:var(--sub);}
.legend i{width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:6px;}
.kpis{grid-column:span 2;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:15px 16px;}
.kpi-lab{margin:0;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
         font-weight:600;}
.kpi-val{margin:7px 0 3px;font-size:27px;font-weight:700;line-height:1;letter-spacing:-.02em;
         font-variant-numeric:tabular-nums;display:flex;align-items:baseline;gap:8px;}
.kpi-sub{margin:0;font-size:12px;color:var(--muted);line-height:1.45;}
.delta{font-size:12px;font-weight:600;}
.delta.up{color:#16A34A;} .delta.down{color:#DC2626;}
.callout{grid-column:span 2;border-radius:10px;padding:14px 18px;font-size:14.5px;
         border:1px solid var(--line);background:var(--card);border-left:4px solid var(--muted);}
.callout p{margin:0;} .callout b{font-weight:600;}
.callout.info{border-left-color:#2563EB;background:#EFF6FF;}
.callout.ok{border-left-color:#16A34A;background:#F0FDF4;}
.callout.aviso{border-left-color:#D97706;background:#FFFBEB;}
.callout.mal{border-left-color:#DC2626;background:#FEF2F2;}
.nota{grid-column:span 2;margin:0;font-size:13px;color:var(--muted);}
.rank{margin-top:12px;}
.rank-row{display:flex;align-items:center;gap:12px;padding:4px 0;font-size:13.5px;}
.rank-lab{flex:0 0 150px;color:var(--sub);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.rank-track{flex:1;height:9px;background:#EEF1F8;border-radius:5px;overflow:hidden;}
.rank-track i{display:block;height:9px;border-radius:5px;}
.rank-val{flex:0 0 88px;text-align:right;font-weight:600;font-variant-numeric:tabular-nums;}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px;}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
   font-weight:600;padding:9px 10px;border-bottom:1px solid var(--line);white-space:nowrap;}
td{padding:9px 10px;border-top:1px solid var(--line);font-variant-numeric:tabular-nums;}
tbody tr:hover{background:#F8FAFC;}
td.mono{font-family:'Consolas','SF Mono',monospace;white-space:nowrap;}
.empty{text-align:center;color:var(--muted);padding:22px;}
.tbl-tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:12px;}
.tbl-search{font:inherit;font-size:13px;padding:7px 11px;border:1px solid var(--line);
            border-radius:8px;background:#fff;color:var(--ink);flex:1;min-width:170px;}
.tbl-count{font-size:12px;color:var(--muted);font-weight:600;}
.tbl-hint{font-size:12px;color:var(--muted);}
th.sortable{cursor:pointer;user-select:none;}
th.sortable:hover{color:var(--accent);}
th[data-dir=asc]::after{content:' \\25B2';font-size:9px;}
th[data-dir=desc]::after{content:' \\25BC';font-size:9px;}
footer{margin:48px 0 40px;padding-top:18px;border-top:1px solid var(--line);
       display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;
       color:var(--muted);font-size:12px;}
footer p{margin:0;}
@media (max-width:820px){.grid{grid-template-columns:1fr;}.card,.card.half,.kpis,.callout{grid-column:span 1;}
  h1{font-size:26px;}}
@media print{
  body{background:#fff;font-size:11.5px;}
  header.top{position:static;}
  .no-print{display:none!important;}
  .wrap{max-width:none;padding:0;}
  .card,.kpi,figure.chart{break-inside:avoid;box-shadow:none;}
  section{break-inside:auto;} .sec-head{break-after:avoid;}
  h1{font-size:22px;margin-top:12px;}
}
"""

# Chart.js: valores por defecto sobrios y un intérprete de los `options` propios
# del kit (unidad, horizontal, diagonal…), para no repetir configuración.
_CHART_JS = """
(function(){
  if (typeof Chart === "undefined") return;
  var INK="#0F172A", MUTED="#94A3B8", LINE="#E2E8F0";
  Chart.defaults.font.family="'Segoe UI',system-ui,sans-serif";
  Chart.defaults.font.size=11.5;
  Chart.defaults.color=MUTED;
  Chart.defaults.plugins.legend.display=false;
  Chart.defaults.plugins.tooltip.backgroundColor=INK;
  Chart.defaults.plugins.tooltip.padding=10;
  Chart.defaults.plugins.tooltip.cornerRadius=8;
  Chart.defaults.plugins.tooltip.displayColors=false;
  Chart.defaults.maintainAspectRatio=false;

  function corto(v){
    var a=Math.abs(v);
    if(a>=1e6) return (v/1e6).toFixed(1).replace(".",",").replace(",0","")+" M";
    if(a>=1000) return (v/1000).toFixed(1).replace(".",",").replace(",0","")+"k";
    return (Math.round(v*10)/10).toString().replace(".",",");
  }

  // Línea de referencia en diagonal (para el gráfico de avance por pedido)
  var diagonal={id:"diagonal",beforeDatasetsDraw:function(ch,a,o){
    if(!o||!o.activa) return;
    var x=ch.scales.x, y=ch.scales.y, c=ch.ctx;
    c.save(); c.strokeStyle="#CBD5E1"; c.setLineDash([5,4]); c.lineWidth=1;
    c.beginPath(); c.moveTo(x.getPixelForValue(x.min), y.getPixelForValue(y.min));
    c.lineTo(x.getPixelForValue(x.max), y.getPixelForValue(y.max)); c.stroke();
    c.setLineDash([]); c.fillStyle="#94A3B8"; c.font="11px 'Segoe UI',sans-serif";
    c.textAlign="right"; c.fillText("al día", x.getPixelForValue(x.max)-4,
                                   y.getPixelForValue(y.max)+14);
    c.restore();
  }};
  Chart.register(diagonal);

  Object.keys(PAYLOAD).forEach(function(id){
    var el=document.getElementById(id); if(!el) return;
    var cfg=PAYLOAD[id], o=cfg.options||{}, unidad=o.unidad||"";
    var opts={plugins:{diagonal:{activa:!!o.diagonal}},
              scales:{}, interaction:{mode:"index",intersect:false}};

    if(cfg.type==="doughnut"){
      opts.cutout="64%"; opts.scales={};
      opts.plugins.tooltip={callbacks:{label:function(c){
        return c.label+": "+corto(c.parsed);}}};
      if(o.centro){
        opts.plugins.centro={texto:o.centro};
      }
    } else if(cfg.type==="bubble"){
      opts.interaction={mode:"nearest",intersect:true};
      opts.scales={x:{title:{display:true,text:o.ejeXTitulo||"",color:MUTED},
                      grid:{color:LINE},border:{display:false},beginAtZero:true},
                   y:{title:{display:true,text:o.ejeYTitulo||"",color:MUTED},
                      grid:{color:LINE},border:{display:false},beginAtZero:true}};
      opts.plugins.tooltip={callbacks:{label:function(c){
        var d=c.raw; return (d.nombre||"")+": "+corto(d.x)+" / "+corto(d.y);}}};
    } else {
      var eje={grid:{color:LINE},border:{display:false},beginAtZero:true,
               ticks:{callback:function(v){return corto(v)+unidad;}}};
      var cat={grid:{display:false},border:{display:false},
               ticks:{autoSkip:true,maxRotation:0}};
      if(o.horizontal){ opts.indexAxis="y"; opts.scales={x:eje,y:cat};
        opts.interaction={mode:"nearest",intersect:true}; }
      else { opts.scales={x:cat,y:eje}; }
      if(o.apiladas){ opts.scales.x.stacked=true; opts.scales.y.stacked=true; }
      opts.plugins.tooltip={callbacks:{label:function(c){
        var v=(o.horizontal?c.parsed.x:c.parsed.y);
        return (c.dataset.label?c.dataset.label+": ":"")+corto(v)+unidad;}}};
    }
    new Chart(el,{type:cfg.type,data:cfg.data,options:opts});
  });

  // Total en el centro del anillo
  Chart.register({id:"centro",afterDraw:function(ch,a,o){
    if(!o||!o.texto) return;
    var c=ch.ctx, m=ch.getDatasetMeta(0);
    if(!m.data.length) return;
    var x=m.data[0].x, y=m.data[0].y;
    c.save(); c.textAlign="center"; c.fillStyle=INK;
    c.font="700 20px 'Segoe UI',sans-serif"; c.fillText(o.texto,x,y+4);
    c.restore();
  }});
})();
"""

_TABLE_JS = """
(function(){
  function norm(s){return (s||'').toString().toLowerCase();}
  document.querySelectorAll('.tbl-panel').forEach(function(panel){
    var t=panel.querySelector('table'); if(!t||!t.tBodies.length) return;
    var rows=function(){return Array.prototype.slice.call(t.tBodies[0].rows);};
    function filtra(){
      var s=panel.querySelector('.tbl-search'); var q=norm(s?s.value:'');
      var n=0, total=0;
      rows().forEach(function(tr){
        if(tr.querySelector('.empty')) return;
        total++;
        var ok=!q||norm(tr.textContent).indexOf(q)>=0;
        tr.hidden=!ok; if(ok) n++;
      });
      var c=panel.querySelector('.tbl-count'); if(c) c.textContent=n+' / '+total;
    }
    var s=panel.querySelector('.tbl-search');
    if(s) s.addEventListener('input',filtra);
    t.querySelectorAll('th[data-sort]').forEach(function(th){
      th.classList.add('sortable');
      th.addEventListener('click',function(){
        var idx=Array.prototype.indexOf.call(th.parentNode.children,th);
        var esNum=th.getAttribute('data-sort')==='num';
        var dir=th.getAttribute('data-dir')==='asc'?-1:1;
        th.parentNode.querySelectorAll('th').forEach(function(o){o.removeAttribute('data-dir');});
        th.setAttribute('data-dir',dir===1?'asc':'desc');
        var b=t.tBodies[0], r=rows().filter(function(x){return !x.querySelector('.empty');});
        r.sort(function(a,c){
          var x=a.cells[idx].textContent.trim(), y=c.cells[idx].textContent.trim();
          if(esNum){x=parseFloat(x.replace(/\\./g,'').replace(',','.').replace(/[^0-9.-]/g,''))||0;
                    y=parseFloat(y.replace(/\\./g,'').replace(',','.').replace(/[^0-9.-]/g,''))||0;
                    return (x-y)*dir;}
          return x.localeCompare(y,'es')*dir;
        });
        r.forEach(function(x){b.appendChild(x);});
      });
    });
    filtra();
  });
})();
"""
