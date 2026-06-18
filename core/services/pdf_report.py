"""Reporte Ejecutivo de Documentación en PDF.

Genera un PDF presentable (portada + KPIs + gráficos + tablas) a partir de la
analítica de `core.services.analytics`. Dos variantes:

  • "esencial"  → portada + KPIs + distribución por estado + ranking de equipo.
  • "completo"  → lo anterior + top clientes (días de respuesta) + predicción de
                  pedidos en riesgo + scorecard de clientes.

Sin dependencias extra: usa reportlab (platypus + graphics) que ya está
instalado. Los gráficos (tarta, barras) se dibujan con reportlab.graphics, no
con matplotlib.
"""

from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

from core.services import analytics

logger = logging.getLogger(__name__)


# ── Paleta (alineada con el theme Industrial Indigo de la app) ────────────────
ACCENT = HexColor("#4F46E5")
INK = HexColor("#0F172A")
SUB = HexColor("#475569")
MUTED = HexColor("#94A3B8")
GREEN = HexColor("#16A34A")
BLUE = HexColor("#2563EB")
AMBER = HexColor("#D97706")
RED = HexColor("#DC2626")
LIGHT = HexColor("#F1F5F9")
CARD = HexColor("#F8FAFC")
BORDER = HexColor("#E2E8F0")
WHITE = colors.white

_MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
          "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


# ── Estilos ───────────────────────────────────────────────────────────────────

def _styles() -> dict:
    base = getSampleStyleSheet()
    s = {}
    s["cover_title"] = ParagraphStyle(
        "cover_title", parent=base["Title"], fontName="Helvetica-Bold",
        fontSize=26, leading=30, textColor=WHITE, alignment=TA_LEFT)
    s["cover_sub"] = ParagraphStyle(
        "cover_sub", fontName="Helvetica", fontSize=13, leading=17,
        textColor=HexColor("#C7D2FE"), alignment=TA_LEFT)
    s["h2"] = ParagraphStyle(
        "h2", fontName="Helvetica-Bold", fontSize=13, leading=16,
        textColor=INK, spaceBefore=4, spaceAfter=2)
    s["body"] = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=9.5, leading=13, textColor=SUB)
    s["kpi_val"] = ParagraphStyle(
        "kpi_val", fontName="Helvetica-Bold", fontSize=20, leading=22,
        alignment=TA_LEFT, textColor=INK)
    s["kpi_lbl"] = ParagraphStyle(
        "kpi_lbl", fontName="Helvetica-Bold", fontSize=7, leading=9,
        alignment=TA_LEFT, textColor=MUTED)
    s["kpi_sub"] = ParagraphStyle(
        "kpi_sub", fontName="Helvetica", fontSize=7, leading=9,
        alignment=TA_LEFT, textColor=SUB)
    s["th"] = ParagraphStyle(
        "th", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=WHITE)
    s["td"] = ParagraphStyle(
        "td", fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK)
    s["td_c"] = ParagraphStyle(
        "td_c", parent=s["td"], alignment=TA_CENTER)
    s["legend"] = ParagraphStyle(
        "legend", fontName="Helvetica", fontSize=8.5, leading=12, textColor=SUB)
    return s


# ── Helpers de flowables ──────────────────────────────────────────────────────

def _section(title: str, st: dict, color=ACCENT):
    """Cabecera de sección: título + filete de color."""
    return KeepTogether([
        Spacer(1, 6 * mm),
        Paragraph(title, st["h2"]),
        HRFlowable(width="100%", thickness=1.4, color=color,
                   spaceBefore=2, spaceAfter=4),
    ])


def _hex(color) -> str:
    """'#rrggbb' a partir de un HexColor de reportlab."""
    return "#" + color.hexval()[2:]


def _kpi_card(label: str, value: str, color, sub: str, st: dict) -> Table:
    inner = Table(
        [[Paragraph(label.upper(), st["kpi_lbl"])],
         [Paragraph(value, _val_style(st, color))],
         [Paragraph(sub, st["kpi_sub"])]],
        colWidths=[40 * mm])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, -1), (0, -1), 8),
        ("TOPPADDING", (0, 1), (0, 1), 0),
        ("BOTTOMPADDING", (0, 0), (0, 1), 1),
        ("LINEBEFORE", (0, 0), (0, -1), 2.4, color),
    ]))
    return inner


def _val_style(st: dict, color):
    return ParagraphStyle("kpi_val_c", parent=st["kpi_val"], textColor=color)


def _kpi_row(cards: list[Table]) -> Table:
    row = Table([cards], colWidths=[44 * mm] * len(cards), hAlign="LEFT")
    row.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return row


def _pie_estado(aprob, env, dev, sin) -> Drawing:
    d = Drawing(170, 150)
    pie = Pie()
    pie.x, pie.y = 12, 10
    pie.width = pie.height = 130
    data = [aprob, env, dev, sin]
    pie.data = [max(v, 0) for v in data]
    pie.labels = None
    palette = [GREEN, BLUE, AMBER, MUTED]
    pie.slices.strokeColor = WHITE
    pie.slices.strokeWidth = 1.2
    for i, col in enumerate(palette):
        pie.slices[i].fillColor = col
    d.add(pie)
    return d


def _bar_clientes(top: list[dict]) -> Drawing:
    top = top[:8]
    names = [str(c["cliente"])[:16] for c in top]
    vals = [round(c["media_dias"], 1) for c in top]
    d = Drawing(440, 16 * len(top) + 30)
    bc = HorizontalBarChart()
    bc.x, bc.y = 95, 14
    bc.width = 320
    bc.height = 16 * len(top)
    bc.data = [vals]
    bc.bars[0].fillColor = ACCENT
    bc.bars[0].strokeColor = None
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = (max(vals) * 1.15) if vals else 1
    bc.valueAxis.labels.fontName = "Helvetica"
    bc.valueAxis.labels.fontSize = 7
    bc.valueAxis.strokeColor = BORDER
    bc.categoryAxis.categoryNames = names
    bc.categoryAxis.labels.fontName = "Helvetica"
    bc.categoryAxis.labels.fontSize = 7.5
    bc.categoryAxis.labels.dx = -4
    bc.categoryAxis.strokeColor = BORDER
    bc.barWidth = 9
    d.add(bc)
    # valor al final de cada barra
    if vals:
        span = bc.valueAxis.valueMax or 1
        for i, v in enumerate(vals):
            x = bc.x + (v / span) * bc.width + 4
            y = bc.y + bc.height - (i + 0.72) * (bc.height / len(vals))
            d.add(String(x, y, f"{v}d", fontName="Helvetica-Bold",
                         fontSize=7, fillColor=SUB))
    return d


def _legend(items: list[tuple], st: dict) -> Table:
    """items = [(texto, color), ...] en una fila con cuadraditos de color."""
    cells = []
    for txt, col in items:
        chip = Table([[" "]], colWidths=[4 * mm], rowHeights=[3 * mm])
        chip.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), col),
                                  ("BOX", (0, 0), (-1, -1), 0, col)]))
        cells.append(chip)
        cells.append(Paragraph(txt, st["legend"]))
    row = Table([cells], hAlign="LEFT")
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return row


def _table(header: list[str], rows: list[list], st: dict, col_widths,
           aligns=None) -> Table:
    head = [Paragraph(h, st["th"]) for h in header]
    body = [head]
    for r in rows:
        body.append([c if hasattr(c, "wrap") else Paragraph(str(c), st["td"]) for c in r])
    t = Table(body, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i, a in enumerate(aligns or []):
        if a != "l":
            style.append(("ALIGN", (i, 0), (i, -1), "CENTER" if a == "c" else "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def _pct_color(pct) -> HexColor:
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return SUB
    return GREEN if pct >= 75 else (AMBER if pct >= 50 else RED)


# ── Documento ─────────────────────────────────────────────────────────────────

def _cover(st: dict, ref: datetime) -> list:
    mes = f"{_MESES[ref.month]} {ref.year}"
    band = Table(
        [[Paragraph("REPORTE EJECUTIVO", st["cover_sub"])],
         [Paragraph("Documentación de Proyectos", st["cover_title"])],
         [Paragraph(mes, st["cover_sub"])]],
        colWidths=[170 * mm])
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (0, 0), 16),
        ("BOTTOMPADDING", (0, -1), (0, -1), 16),
    ]))
    return [band, Spacer(1, 8 * mm)]


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, 14 * mm, 190 * mm, 14 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 9 * mm, "DocFlow Lite · Reporte Ejecutivo")
    canvas.drawRightString(190 * mm, 9 * mm, f"Página {doc.page}  ·  © jparedesDS")
    canvas.restoreState()


def generate_executive_pdf(variant: str = "completo",
                           ref_date: datetime | None = None) -> bytes:
    """Genera el PDF y devuelve los bytes. variant ∈ {'completo','esencial'}."""
    variant = "esencial" if str(variant).lower().startswith("esen") else "completo"
    ref = ref_date or datetime.now()
    st = _styles()

    summary = analytics.get_summary()
    ranking = analytics.get_ranking()

    total = (summary["total_aprobados"] + summary["total_enviados"]
             + summary["total_devoluciones"] + summary["total_sin_enviar"])
    pct_aprob = round(summary["total_aprobados"] / total * 100) if total else 0

    flow: list = []
    flow += _cover(st, ref)

    # ── KPIs ─────────────────────────────────────────────────────────────
    cards = [
        _kpi_card("Documentos", f"{total}", ACCENT, "en seguimiento", st),
        _kpi_card("Aprobados", f"{pct_aprob}%", GREEN,
                  f"{summary['total_aprobados']} docs", st),
        _kpi_card("Velocidad media", f"{summary['velocidad_media_dias']}d", BLUE,
                  "días de respuesta", st),
        _kpi_card("En riesgo", f"{summary['docs_riesgo']}",
                  RED if summary["docs_riesgo"] else GREEN, "críticos +15d", st),
    ]
    flow.append(_kpi_row(cards))
    flow.append(Spacer(1, 2 * mm))
    cards2 = [
        _kpi_card("Clientes", f"{summary['total_clientes']}", INK, "activos", st),
        _kpi_card("Clientes OK", f"{summary['clientes_ok']}", GREEN,
                  "≥75% aprobados", st),
        _kpi_card("Vencen ≤3d", f"{summary['a_vencer_3d']}",
                  AMBER if summary["a_vencer_3d"] else GREEN, "casi fuera de plazo", st),
        _kpi_card("Devoluciones", f"{summary['total_devoluciones']}", AMBER,
                  "pendientes de revisar", st),
    ]
    flow.append(_kpi_row(cards2))

    # ── Distribución por estado (tarta) ──────────────────────────────────
    flow.append(_section("Distribución por estado", st))
    pie = _pie_estado(summary["total_aprobados"], summary["total_enviados"],
                      summary["total_devoluciones"], summary["total_sin_enviar"])
    legend = _legend([
        (f"Aprobado · {summary['total_aprobados']}", GREEN),
        (f"Enviado · {summary['total_enviados']}", BLUE),
        (f"Devoluciones · {summary['total_devoluciones']}", AMBER),
        (f"Sin enviar · {summary['total_sin_enviar']}", MUTED),
    ], st)
    dist = Table([[pie, legend]], colWidths=[60 * mm, 110 * mm])
    dist.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    flow.append(dist)

    # ── Ranking de equipo ────────────────────────────────────────────────
    flow.append(_section("Ranking de equipo", st))
    rows = []
    for i, r in enumerate(ranking):
        pct_p = Paragraph(
            f'<font color="{_hex(_pct_color(r["pct"]))}"><b>{r["pct"]}%</b></font>',
            st["td_c"])
        rows.append([f"#{i+1}", r["responsable"], r["total"], r["aprobados"],
                     pct_p, r["devoluciones"], f'{r["tasa_devolucion"]}%', r["criticos"]])
    flow.append(_table(
        ["#", "Responsable", "Total", "Aprob.", "% Compl.", "Devol.", "Tasa Dev.", "Críticos"],
        rows, st, col_widths=[10 * mm, 38 * mm, 18 * mm, 18 * mm, 22 * mm, 18 * mm, 22 * mm, 20 * mm],
        aligns=["c", "l", "c", "c", "c", "c", "c", "c"]))

    # ── (COMPLETO) secciones adicionales ─────────────────────────────────
    if variant == "completo":
        flow.append(PageBreak())

        # Top clientes por días de respuesta
        flow.append(_section("Top clientes · días medios de respuesta", st))
        top = summary["por_cliente"][:8]
        if top:
            flow.append(_bar_clientes(top))
        else:
            flow.append(Paragraph("Sin datos.", st["body"]))

        # Predicción de pedidos en riesgo
        flow.append(_section("Predicción de pedidos · en riesgo de retraso", st))
        pred = [x for x in analytics.get_predicciones()
                if x.get("pct_esperado") is not None and x.get("en_plazo") is False]
        pred.sort(key=lambda x: (x["pct"] - x["pct_esperado"]))
        if pred:
            rows = []
            for x in pred[:14]:
                desv = x["pct"] - x["pct_esperado"]
                rows.append([x["pedido"], f'{x["pct"]}%', f'{x["pct_esperado"]}%',
                             f'{desv}pp', f'{x["aprobados"]}/{x["total"]}',
                             x.get("fecha_prevista") or "—", x.get("prediccion_fecha") or "—"])
            flow.append(_table(
                ["Pedido", "% Real", "% Esper.", "Desv.", "Aprob/Total", "Fecha Prev.", "Pred. Fin"],
                rows, st, col_widths=[34 * mm, 18 * mm, 20 * mm, 18 * mm, 24 * mm, 26 * mm, 26 * mm],
                aligns=["l", "c", "c", "c", "c", "c", "c"]))
        else:
            flow.append(Paragraph("✓ Ningún pedido con predicción de retraso.", st["body"]))

        # Scorecard de clientes
        flow.append(_section("Scorecard de clientes", st))
        score = analytics.get_scorecard()[:18]
        rows = []
        for r in score:
            sc_p = Paragraph(
                f'<font color="{_hex(_pct_color(r["score"]))}"><b>{round(r["score"])}</b></font>',
                st["td_c"])
            rows.append([r["client"], sc_p, f'{round(r["approval_rate_first_rev"])}%',
                         r["avg_response_days"], r["critical_docs_count"], r["total_docs"]])
        flow.append(_table(
            ["Cliente", "Score", "% Aprob 1ªRev", "Días Resp.", "Crít. +30d", "Total"],
            rows, st, col_widths=[46 * mm, 18 * mm, 28 * mm, 24 * mm, 24 * mm, 20 * mm],
            aligns=["l", "c", "c", "c", "c", "c"]))

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=16 * mm, bottomMargin=20 * mm,
        title=f"Reporte Ejecutivo {_MESES[ref.month]} {ref.year}",
        author="DocFlow Lite")
    doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def default_filename(variant: str = "completo", ref_date: datetime | None = None) -> str:
    ref = ref_date or datetime.now()
    suf = "Esencial" if str(variant).lower().startswith("esen") else "Completo"
    return f"Reporte_Ejecutivo_{suf}_{ref.strftime('%Y-%m')}.pdf"


def _email_body_html(ref: datetime) -> str:
    mes = f"{_MESES[ref.month]} {ref.year}"
    return (
        '<div style="font-family:Segoe UI,Arial,sans-serif;color:#0F172A;font-size:14px;'
        'line-height:1.6">'
        f'<p>Hola,</p>'
        f'<p>Adjunto el <b>Reporte Ejecutivo de Documentación</b> correspondiente a '
        f'<b>{mes}</b>: KPIs globales, distribución por estado, ranking del equipo, '
        f'predicción de pedidos en riesgo y scorecard de clientes.</p>'
        '<p style="color:#475569">Generado automáticamente por DocFlow Lite.</p>'
        '<p style="color:#94A3B8;font-size:12px">© jparedesDS</p>'
        '</div>'
    )


def send_executive_pdf_email(to: list[str], cc: list[str] | None = None,
                             variant: str = "completo",
                             ref_date: datetime | None = None) -> dict:
    """Genera el PDF y lo envía adjunto por SMTP. Devuelve el resultado del envío."""
    from core.services.smtp import send_html_email

    ref = ref_date or datetime.now()
    pdf = generate_executive_pdf(variant, ref)
    fname = default_filename(variant, ref)
    subject = f"Reporte Ejecutivo de Documentación — {_MESES[ref.month]} {ref.year}"
    return send_html_email(
        to=to, cc=cc or [], subject=subject, html_body=_email_body_html(ref),
        attachment_eml=pdf, attachment_name=fname)
