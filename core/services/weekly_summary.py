"""Resúmenes semanales (email ejecutivo + email personal por DC).

Port adaptado de weekly_summary_service del DocFlow grande:
- Anthropic opcional (si no hay key, genera párrafo fallback)
- Sin dependencias de repositorios SQL — usa core.services.monitoring
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta

from core.config import ANTHROPIC_API_KEY, USERS
from core.services import monitoring as monitoring_service
from core.services import smtp as smtp_service

logger = logging.getLogger(__name__)


# ── Estado display ────────────────────────────────────────────────────────────

_ESTADO_COLORS = {
    "aprobado":     ("Aprobado",     "#16A34A"),
    "enviado":      ("Enviado",      "#2563EB"),
    "com. menores": ("Com. Menores", "#D97706"),
    "com. mayores": ("Com. Mayores", "#DB2777"),
    "comentado":    ("Comentado",    "#CA8A04"),
    "rechazado":    ("Rechazado",    "#DC2626"),
    "sin enviar":   ("Sin Enviar",   "#64748B"),
}

ESTADOS_APROBADOS = {"aprobado"}
ESTADOS_PENDIENTES = {"enviado", "com. menores", "com. mayores", "rechazado", "comentado"}
ESTADOS_DEVOLUCION = {"com. menores", "com. mayores", "rechazado", "comentado"}

# Estados que se incluyen específicamente en el Monitoring Report Personal:
# devoluciones del cliente (com./rechazado/comentado) + sin enviar.
# NO incluye "enviado" (esperando respuesta) ni "aprobado".
ESTADOS_PERSONAL_PENDING = {
    "com. menores", "com. mayores", "comentado", "rechazado",
    "sin enviar", "",  # vacío equivale a "sin enviar"
}


# ── Helpers semanal ───────────────────────────────────────────────────────────

def _get_weekly_range() -> tuple[datetime, datetime]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_since_thu = (today.weekday() - 3) % 7
    end_thursday = today - timedelta(days=days_since_thu)
    start_thursday = end_thursday - timedelta(days=7)
    return start_thursday, end_thursday


def _parse_fecha_envio(val):
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    s = str(val).strip()
    head = s.split("T")[0] if "T" in s else s.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(head, fmt)
        except ValueError:
            continue
    return None


def _filter_weekly_docs(docs, start, end) -> list[dict]:
    result = []
    for d in docs:
        fecha_env = _parse_fecha_envio(d.get("Fecha Env. Doc."))
        if fecha_env and start <= fecha_env < end:
            result.append(d)
            continue
        estado = str(d.get("Estado", "") or "").lower().strip()
        dias = d.get("Días Devolución")
        if estado in ESTADOS_PENDIENTES and isinstance(dias, (int, float)) and 0 < dias <= 7:
            result.append(d)
    return result


# ── Recolección de datos ──────────────────────────────────────────────────────

def _collect_executive_data() -> dict:
    all_docs = monitoring_service.get_monitoring_data()

    start, end = _get_weekly_range()
    weekly_docs = _filter_weekly_docs(all_docs, start, end)

    total_weekly = len(weekly_docs)
    total_aprobados = sum(
        1 for d in weekly_docs
        if str(d.get("Estado", "") or "").lower().strip() in ESTADOS_APROBADOS
    )
    pct_aprobados = round(total_aprobados / total_weekly * 100) if total_weekly else 0

    dias_pendientes = []
    docs_riesgo = a_vencer_3d = 0
    for d in weekly_docs:
        estado = str(d.get("Estado", "") or "").lower().strip()
        dias = d.get("Días Devolución")
        if estado in ESTADOS_PENDIENTES and isinstance(dias, (int, float)) and dias > 0:
            dias_pendientes.append(dias)
            if dias > 15:
                docs_riesgo += 1
            if 0 < dias <= 3:
                a_vencer_3d += 1
    velocidad_media = round(sum(dias_pendientes) / len(dias_pendientes), 1) if dias_pendientes else 0

    total_global = len(all_docs)
    aprobados_global = sum(
        1 for d in all_docs
        if str(d.get("Estado", "") or "").lower().strip() in ESTADOS_APROBADOS
    )
    pct_global = round(aprobados_global / total_global * 100) if total_global else 0

    formatted_docs = []
    for d in weekly_docs:
        estado = str(d.get("Estado", "") or "").lower().strip()
        if estado in ESTADOS_APROBADOS:
            continue
        dias = d.get("Días Devolución", 0)
        if not isinstance(dias, (int, float)):
            dias = 0
        estado_display, _ = _ESTADO_COLORS.get(estado or "sin enviar", (estado.title(), "#64748B"))
        formatted_docs.append({
            "doc_eipsa": str(d.get("Nº Doc. EIPSA", "") or ""),
            "titulo": str(d.get("Título", "") or ""),
            "cliente": str(d.get("Cliente", "") or ""),
            "estado": estado,
            "estado_display": estado_display,
            "dias": int(dias) if isinstance(dias, (int, float)) else 0,
        })
    formatted_docs.sort(key=lambda x: x["dias"], reverse=True)

    return {
        "fecha": datetime.now().strftime("%Y-%m-%d"),
        "week_start": start.strftime("%d/%m"),
        "week_end": end.strftime("%d/%m"),
        "total_docs": total_weekly,
        "total_aprobados": total_aprobados,
        "pct_aprobados": pct_aprobados,
        "velocidad_media": velocidad_media,
        "docs_riesgo": docs_riesgo,
        "a_vencer_3d": a_vencer_3d,
        "total_global": total_global,
        "pct_global": pct_global,
        "weekly_docs": formatted_docs,
    }


def _collect_personal_data(initials: str, docs: list, team_avg_pct: float,
                           week_start_str: str = "", week_end_str: str = "") -> dict:
    user_info = USERS.get(initials, {})
    nombre = user_info.get("nombre", initials)

    my_docs = [d for d in docs if str(d.get("Repsonsable", "") or "").strip() == initials]
    my_total = len(my_docs)
    my_approved = sum(
        1 for d in my_docs
        if str(d.get("Estado", "") or "").lower().strip() in ESTADOS_APROBADOS
    )
    my_pct = round(my_approved / my_total * 100) if my_total else 0

    # Solo incluimos Com. Menores / Com. Mayores / Comentado / Rechazado / Sin Enviar.
    # Excluye: aprobado, enviado (en cliente), eliminado, HOLD, informativo, etc.
    my_pending = []
    my_critical = my_expiring = 0
    my_devol_count = 0
    my_sin_enviar = 0
    my_enviado = 0  # se mantiene por compat aunque no se incluya en la tabla
    for d in my_docs:
        estado = str(d.get("Estado", "") or "").lower().strip()
        if estado not in ESTADOS_PERSONAL_PENDING:
            continue

        dias = d.get("Días Devolución", 0)
        if not isinstance(dias, (int, float)):
            dias = 0
        critico = str(d.get("Crítico", "") or "").lower().strip()
        if critico in ("sí", "si"):
            my_critical += 1
        if 0 < dias <= 3:
            my_expiring += 1

        if estado in ESTADOS_DEVOLUCION:
            my_devol_count += 1
        else:
            my_sin_enviar += 1

        estado_norm = estado or "sin enviar"
        estado_display, _ = _ESTADO_COLORS.get(
            estado_norm, (estado.title() if estado else "Sin Enviar", "#64748B"),
        )
        my_pending.append({
            "doc_eipsa": str(d.get("Nº Doc. EIPSA", "") or ""),
            "titulo": str(d.get("Título", "") or ""),
            "tipo": str(d.get("Tipo Doc.", "") or ""),
            "cliente": str(d.get("Cliente", "") or ""),
            "estado": estado_norm,
            "estado_display": estado_display,
            "dias": int(dias) if isinstance(dias, (int, float)) else 0,
        })

    # Ordenar: por días descendentes (los más antiguos arriba = más urgentes)
    my_pending.sort(key=lambda x: x["dias"], reverse=True)

    return {
        "initials": initials,
        "nombre": nombre,
        "my_total": my_total,
        "my_approved": my_approved,
        "my_pct": my_pct,
        "my_devol_count": my_devol_count,
        "my_enviado_count": my_enviado,
        "my_sin_enviar_count": my_sin_enviar,
        "my_pending_total": len(my_pending),
        "team_avg_pct": team_avg_pct,
        "my_pending": my_pending,
        "my_critical": my_critical,
        "my_expiring": my_expiring,
        "week_start": week_start_str,
        "week_end": week_end_str,
    }


# ── HTML rendering ────────────────────────────────────────────────────────────

def _escape(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _email_shell(title: str, subtitle: str, content: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#EEF2F9;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#EEF2F9;padding:32px 0;">
<tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(30,45,125,0.10);">
  <tr><td style="background:#1A1D27;padding:0;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr><td style="height:4px;background:#4F46E5;font-size:1px;">&nbsp;</td></tr>
      <tr><td style="padding:24px 32px;">
        <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:700;letter-spacing:-0.02em;">{_escape(title)}</h1>
        <p style="margin:6px 0 0;color:#94a3b8;font-size:13px;">{_escape(subtitle)}</p>
      </td></tr>
    </table>
  </td></tr>
  {content}
  <tr><td style="padding:0;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr><td style="height:3px;background:#4F46E5;font-size:1px;">&nbsp;</td></tr>
      <tr><td style="background:#f8fafc;padding:18px 32px;">
        <p style="margin:0;font-size:12px;font-weight:700;color:#1A1D27;">DocFlow</p>
        <p style="margin:3px 0 0;font-size:11px;color:#94a3b8;">© 2026 jparedesDS &middot; Todos los derechos reservados</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def _kpi_cards_html(cards: list) -> str:
    def _card(value, label, color):
        return (
            f'<td width="33%" align="center" style="padding:0 4px;">'
            f'<table cellpadding="0" cellspacing="0" style="width:100%;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">'
            f'<tr><td style="height:4px;background:{color};font-size:1px;">&nbsp;</td></tr>'
            f'<tr><td style="padding:12px 8px;text-align:center;background:#ffffff;">'
            f'<p style="margin:0;font-size:24px;font-weight:800;color:{color};line-height:1;">{_escape(value)}</p>'
            f'<p style="margin:4px 0 0;font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.04em;">{label}</p>'
            f'</td></tr></table></td>'
        )
    row1 = "".join(_card(*c) for c in cards[:3])
    row2 = "".join(_card(*c) for c in cards[3:6]) if len(cards) > 3 else ""
    spacer = '<tr><td colspan="3" style="height:8px;font-size:1px;">&nbsp;</td></tr>' if row2 else ""
    row2_html = f"<tr>{row2}</tr>" if row2 else ""
    return f'<table width="100%" cellpadding="0" cellspacing="0"><tr>{row1}</tr>{spacer}{row2_html}</table>'


def _docs_table_html(docs: list, max_rows: int = 20) -> str:
    if not docs:
        return ""
    th = (
        "background:#1A1D27;color:#ffffff;padding:10px 12px;font-size:10px;"
        "font-weight:700;letter-spacing:0.06em;text-transform:uppercase;text-align:left;"
    )
    rows = ""
    for i, d in enumerate(docs[:max_rows]):
        bg = "#F8FAFC" if i % 2 == 0 else "#FFFFFF"
        dias = d["dias"]
        estado_raw = d["estado"]
        _, estado_color = _ESTADO_COLORS.get(estado_raw, (estado_raw.title(), "#64748B"))
        estado_display = d.get("estado_display", estado_raw.title())
        dias_color = "#DC2626" if dias > 15 else ("#D97706" if dias > 7 else "#1e293b")
        rows += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:7px 10px;border-bottom:1px solid #e2e8f0;font-size:11px;color:#1e293b;'
            f"font-family:\'Courier New\',monospace;white-space:nowrap;\">{_escape(d['doc_eipsa'][:20])}</td>"
            f'<td style="padding:7px 10px;border-bottom:1px solid #e2e8f0;font-size:11px;color:#1e293b;">{_escape(d["titulo"][:30])}</td>'
            f'<td style="padding:7px 10px;border-bottom:1px solid #e2e8f0;font-size:11px;color:#1e293b;">{_escape(d["cliente"][:15])}</td>'
            f'<td style="padding:7px 10px;border-bottom:1px solid #e2e8f0;">'
            f'<span style="display:inline-block;padding:2px 7px;border-radius:4px;font-size:9px;font-weight:600;'
            f'color:#fff;background:{estado_color};">{estado_display}</span></td>'
            f'<td style="padding:7px 10px;border-bottom:1px solid #e2e8f0;font-size:12px;font-weight:700;'
            f'color:{dias_color};text-align:center;">{dias}</td></tr>'
        )
    remaining = len(docs) - max_rows
    if remaining > 0:
        rows += (
            f'<tr><td colspan="5" style="padding:8px 12px;text-align:center;font-size:11px;color:#64748b;">'
            f'... y {remaining} documentos m&aacute;s</td></tr>'
        )
    return (
        f'<table cellpadding="0" cellspacing="0" style="width:100%;border-radius:8px;overflow:hidden;border:1px solid #e2e8f0;">'
        f'<thead><tr><th style="{th}">Doc. EIPSA</th><th style="{th}">T&iacute;tulo</th>'
        f'<th style="{th}">Cliente</th><th style="{th}">Estado</th>'
        f'<th style="{th}text-align:center;">D&iacute;as</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def _alert_box_html(count: int, message: str, color: str) -> str:
    if color == "amber":
        bg, border, text = "#FFFBEB", "#FDE68A", "#92400E"
    else:
        bg, border, text = "#FEF2F2", "#FECACA", "#991B1B"
    return (
        f'<table cellpadding="0" cellspacing="0" style="width:100%;margin-bottom:8px;"><tr>'
        f'<td style="padding:12px 16px;background:{bg};border:1px solid {border};border-radius:8px;">'
        f'<p style="margin:0;font-size:13px;color:{text};font-weight:600;">'
        f'&#9888; <strong>{count}</strong> {_escape(message)}</p></td></tr></table>'
    )


def _render_executive_html(data: dict, ai_paragraph: str) -> str:
    cards = [
        (str(data["total_docs"]), "Movimientos", "#2563EB"),
        (f'{data["total_aprobados"]} ({data["pct_aprobados"]}%)', "Aprobados", "#16A34A"),
        (f'{data["velocidad_media"]}d', "Vel. Media", "#4F46E5"),
        (str(data["docs_riesgo"]), "En Riesgo", "#DC2626"),
        (str(data["a_vencer_3d"]), "Vencen 3d", "#D97706"),
        (f'{data["pct_global"]}%', "Aprob. Global", "#0D9488"),
    ]
    table = _docs_table_html(data.get("weekly_docs", []))
    table_section = (
        f'<p style="margin:0 0 12px;font-size:10px;font-weight:700;color:#4F46E5;'
        f'text-transform:uppercase;letter-spacing:0.08em;">Movimientos de la Semana</p>{table}'
        if table else ""
    )
    content = f"""
  <tr><td style="padding:24px 28px 16px;background:#f8fafc;border-bottom:1px solid #e2e8f0;">
    {_kpi_cards_html(cards)}
  </td></tr>
  <tr><td style="padding:24px 28px 16px;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="border-left:4px solid #4F46E5;background:#F5F3FF;padding:16px 20px;border-radius:0 8px 8px 0;">
        <p style="margin:0;font-size:14px;color:#1e293b;line-height:1.7;">{_escape(ai_paragraph.strip())}</p>
      </td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:8px 28px 24px;">{table_section}</td></tr>"""
    return _email_shell(
        "DocFlow — Resumen Ejecutivo",
        f"Semana del {data['week_start']} al {data['week_end']}",
        content,
    )


def _render_personal_html(data: dict) -> str:
    pending_count = data.get("my_pending_total", len(data["my_pending"]))
    devol = data.get("my_devol_count", 0)
    enviado = data.get("my_enviado_count", 0)
    sin_enviar = data.get("my_sin_enviar_count", 0)

    cards = [
        # Fila 1: dos categorías de pendientes + total
        (str(devol),         "Devoluciones",     "#DB2777"),
        (str(sin_enviar),    "Sin Enviar",       "#64748B"),
        (str(pending_count), "Pendientes Total", "#D97706" if pending_count > 0 else "#16A34A"),
        # Fila 2: KPIs personales
        (f'{data["my_pct"]}%', "Mi Aprob.", "#16A34A"),
        (str(data.get("my_critical", 0)), "Críticos", "#DC2626" if data.get("my_critical", 0) > 0 else "#64748B"),
        (str(data.get("my_expiring", 0)), "Vencen 3d", "#D97706" if data.get("my_expiring", 0) > 0 else "#64748B"),
    ]
    alerts = ""
    if data["my_expiring"] > 0:
        alerts += _alert_box_html(data["my_expiring"], "documentos vencen en 3 días", "amber")
    if data["my_critical"] > 0:
        alerts += _alert_box_html(data["my_critical"], "documentos críticos pendientes", "red")

    if pending_count == 0:
        green_box = (
            '<table cellpadding="0" cellspacing="0" style="width:100%;margin-bottom:16px;"><tr>'
            '<td style="padding:16px 20px;background:#F0FDF4;border:1px solid #BBF7D0;border-radius:8px;text-align:center;">'
            '<p style="margin:0;font-size:14px;color:#16A34A;font-weight:700;">&#10003; Sin documentos pendientes asignados</p>'
            '<p style="margin:4px 0 0;font-size:12px;color:#16A34A;">¡Todo tu trabajo está aprobado! 🎉</p>'
            '</td></tr></table>'
        )
    else:
        green_box = ""

    # Tabla con TODOS los pendientes (sin recorte por fecha)
    table = _docs_table_html(data["my_pending"], max_rows=50) if pending_count > 0 else ""
    table_section = (
        f'<p style="margin:0 0 12px;font-size:10px;font-weight:700;color:#4F46E5;'
        f'text-transform:uppercase;letter-spacing:0.08em;">Documentos pendientes asignados a ti ({pending_count})</p>{table}'
        if table else ""
    )
    content = f"""
  <tr><td style="padding:24px 28px 16px;background:#f8fafc;border-bottom:1px solid #e2e8f0;">
    {_kpi_cards_html(cards)}
  </td></tr>
  <tr><td style="padding:20px 28px 24px;">{alerts}{green_box}{table_section}</td></tr>"""
    subtitle = f'{data["nombre"]} ({data["initials"]})'
    if data.get("week_start") and data.get("week_end"):
        subtitle += f' — Semana del {data["week_start"]} al {data["week_end"]}'
    return _email_shell("DocFlow — Tus Pendientes", subtitle, content)


# ── AI paragraph (opcional) ───────────────────────────────────────────────────

def _build_ai_prompt(data: dict) -> str:
    return f"""Eres un asistente ejecutivo de un equipo de Document Control (ingeniería de documentación técnica).
Genera un PÁRRAFO EJECUTIVO BREVE (2-3 frases narrativas) en ESPAÑOL con estos datos
de la semana ({data['week_start']} al {data['week_end']}):

- Movimientos esta semana: {data['total_docs']}
- Aprobados esta semana: {data['pct_aprobados']}% ({data['total_aprobados']}/{data['total_docs']})
- Velocidad media devolución: {data['velocidad_media']} días
- Documentos en riesgo (>15 días): {data['docs_riesgo']}
- A vencer en 3 días: {data['a_vencer_3d']}
- Aprobación global del proyecto: {data['pct_global']}% ({data['total_global']} docs totales)

Menciona la tendencia general, el punto de atención más crítico, y una acción recomendada.
Solo un párrafo corto narrativo. Sin HTML ni markdown. Sé directo y accionable."""


def _fallback_paragraph(data: dict) -> str:
    return (
        f"Esta semana ({data['week_start']} al {data['week_end']}) se registraron "
        f"{data['total_docs']} movimientos con una velocidad media de devolución de "
        f"{data['velocidad_media']} días. El {data['pct_aprobados']}% está aprobado "
        f"({data['total_aprobados']}/{data['total_docs']}), con una aprobación global "
        f"del proyecto del {data['pct_global']}%. Hay {data['docs_riesgo']} documentos "
        f"en riesgo y {data['a_vencer_3d']} por vencer en 3 días."
    )


def _generate_ai_paragraph(data: dict) -> str:
    api_key = (ANTHROPIC_API_KEY or "").strip()
    if not api_key:
        return _fallback_paragraph(data)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": _build_ai_prompt(data)}],
        )
        return message.content[0].text
    except Exception as exc:
        logger.warning("Anthropic falló, usando fallback: %s", exc)
        return _fallback_paragraph(data)


# ── API pública ───────────────────────────────────────────────────────────────

def send_executive_email(to: list[str] | None = None, cc: list[str] | None = None) -> dict:
    data = _collect_executive_data()
    ai_paragraph = _generate_ai_paragraph(data)
    html = _render_executive_html(data, ai_paragraph)
    subject = f"DocFlow — Resumen Ejecutivo ({data['fecha']})"

    if not to:
        recipients_raw = os.getenv("WEEKLY_EXECUTIVE_RECIPIENTS", "")
        to = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    if not to:
        return {"status": "skipped", "reason": "No recipients configured"}

    smtp_service.send_html_email(to=to, cc=cc or [], subject=subject, html_body=html)
    return {"status": "sent", "type": "executive", "recipients": to, "fecha": data["fecha"]}


def send_personal_emails(to_cc: list[str] | None = None, user_filter=None) -> dict:
    docs = monitoring_service.get_monitoring_data()
    start, end = _get_weekly_range()
    week_start_str = start.strftime("%d/%m")
    week_end_str = end.strftime("%d/%m")

    total_all = len(docs)
    approved_all = sum(
        1 for d in docs
        if str(d.get("Estado", "") or "").lower().strip() in ESTADOS_APROBADOS
    )
    team_avg_pct = round(approved_all / total_all * 100, 1) if total_all else 0

    users_to_send = USERS
    if user_filter and user_filter != "all" and isinstance(user_filter, list):
        users_to_send = {k: v for k, v in USERS.items() if k in user_filter}

    sent_to = []
    skipped: list[str] = []
    for initials, user_info in users_to_send.items():
        pdata = _collect_personal_data(initials, docs, team_avg_pct, week_start_str, week_end_str)
        if pdata["my_total"] == 0:
            skipped.append(initials)
            continue
        html = _render_personal_html(pdata)
        fecha = datetime.now().strftime("%Y-%m-%d")
        subject = f"DocFlow — Tu Resumen Semanal ({fecha})"
        email = user_info["emails"][0]
        smtp_service.send_html_email(to=[email], cc=to_cc or [], subject=subject, html_body=html)
        sent_to.append(email)
        time.sleep(1)

    return {"status": "sent", "type": "personal", "sent_to": sent_to, "count": len(sent_to), "skipped": skipped}


def get_executive_preview() -> str:
    data = _collect_executive_data()
    ai_paragraph = _generate_ai_paragraph(data)
    return _render_executive_html(data, ai_paragraph)


def get_personal_preview(initials: str = "JP") -> str:
    docs = monitoring_service.get_monitoring_data()
    start, end = _get_weekly_range()
    week_start_str = start.strftime("%d/%m")
    week_end_str = end.strftime("%d/%m")

    total_all = len(docs)
    approved_all = sum(
        1 for d in docs
        if str(d.get("Estado", "") or "").lower().strip() in ESTADOS_APROBADOS
    )
    team_avg_pct = round(approved_all / total_all * 100, 1) if total_all else 0

    pdata = _collect_personal_data(initials, docs, team_avg_pct, week_start_str, week_end_str)
    return _render_personal_html(pdata)


# ── Teams (tarjeta de pendientes por persona) ─────────────────────────────────

def _personal_card_args(pdata: dict) -> dict:
    pend = pdata.get("my_pending_total", 0)
    nombre = pdata.get("nombre", pdata.get("initials", ""))
    ini = pdata.get("initials", "")
    facts = [
        ("Pendientes", pend),
        ("Devoluciones", pdata.get("my_devol_count", 0)),
        ("Sin enviar", pdata.get("my_sin_enviar_count", 0)),
        ("Críticos", pdata.get("my_critical", 0)),
        ("Vencen ≤3d", pdata.get("my_expiring", 0)),
    ]
    lines = []
    for d in pdata.get("my_pending", [])[:8]:
        dias = d.get("dias") or 0
        emoji = "🔴" if dias > 15 else ("🟡" if dias > 7 else "⚪")
        estado = d.get("estado_display") or d.get("estado") or ""
        suf = f" · {dias}d" if dias else ""
        seg = [d.get("doc_eipsa") or "—"]
        tipo = (d.get("tipo") or "").strip()
        if tipo:
            seg.append(tipo)
        seg.append(estado)
        lines.append(f"{emoji} " + " · ".join(seg) + suf)
    rest = pend - 8
    if rest > 0:
        lines.append(f"… y {rest} más")
    text = "\n\n".join(lines) if lines else "✅ Sin documentos pendientes. ¡Todo al día!"
    subtitle = f"{pend} documento(s) por realizar" if pend else "Sin pendientes"
    return {"title": f"Pendientes · {nombre} ({ini})", "subtitle": subtitle,
            "text": text, "facts": facts}


def _team_avg_pct(docs: list) -> float:
    total = len(docs)
    approved = sum(1 for d in docs
                   if str(d.get("Estado", "") or "").lower().strip() in ESTADOS_APROBADOS)
    return round(approved / total * 100, 1) if total else 0


# Buzones compartidos: se evitan como destinatario de mensajes personales (un
# DM de Teams debe ir a la cuenta personal, no al buzón de documentación).
_SHARED_MAILBOXES = {"documentacion@eipsa.es"}


def _user_email(initials: str) -> str | None:
    emails = USERS.get(initials, {}).get("emails") or []
    personal = [e for e in emails if e.lower().strip() not in _SHARED_MAILBOXES]
    if personal:
        return personal[0]
    return emails[0] if emails else None


def _render_personal_pdf(pdata: dict) -> bytes | None:
    """PDF idéntico al email: renderiza el mismo HTML (_render_personal_html)
    con wkhtmltopdf. Devuelve None si wkhtmltopdf no está disponible."""
    from core.services.htmlpdf import html_to_pdf
    return html_to_pdf(_render_personal_html(pdata))


def _save_personal_report(initials: str, pdata: dict) -> tuple[str | None, str | None, list]:
    """Genera el informe personal y devuelve (texto_enlace, url, enlaces_extra).

    Con Nextcloud configurado sube PDF (vista en línea) + HTML (descarga) y
    enlaza ambos. Sin Nextcloud, cae a fichero local/red (solo HTML)."""
    html = _render_personal_html(pdata)
    html_name = f"Pendientes_{initials}.html"
    pdf_name = f"Pendientes_{initials}.pdf"

    # 1) Nextcloud → URLs http clicables (PDF se ve en línea, HTML se descarga)
    try:
        from core.services import nextcloud
        if nextcloud.is_configured():
            pdf_url = html_url = None
            try:
                pdf_bytes = _render_personal_pdf(pdata)
                if pdf_bytes:
                    pdf_url = nextcloud.upload_report(pdf_name, pdf_bytes,
                                                      content_type="application/pdf", view=True)
            except Exception:
                logger.debug("PDF personal falló", exc_info=True)
            html_url = nextcloud.upload_report(html_name, html)
            if pdf_url:
                extra = [("Versión HTML", html_url)] if html_url else []
                return "Ver informe (PDF)", pdf_url, extra
            if html_url:
                return "Descargar informe (HTML)", html_url, []
    except Exception:
        logger.debug("Subida a Nextcloud falló", exc_info=True)

    # 2/3) Fallback a fichero (red o local), solo HTML
    try:
        from pathlib import Path

        from core import preferences as pref
        from core.services.interactive_report import reports_dir

        share = (pref.get("reports_share_dir") or "").strip()
        base = Path(share) if share else reports_dir()
        base.mkdir(parents=True, exist_ok=True)
        path = base / html_name
        path.write_text(html, encoding="utf-8")
        return "Abrir informe completo", path.as_uri(), []
    except Exception:
        logger.debug("No se pudo guardar/enlazar el informe personal", exc_info=True)
        return None, None, []


def post_personal_to_teams(initials: str = "JP") -> dict:
    """Publica en Teams la tarjeta de pendientes de una persona."""
    from core.services import teams
    docs = monitoring_service.get_monitoring_data()
    start, end = _get_weekly_range()
    pdata = _collect_personal_data(initials, docs, _team_avg_pct(docs),
                                   start.strftime("%d/%m"), end.strftime("%d/%m"))
    link_text, link_url, extra = _save_personal_report(initials, pdata)
    return teams.post_card(recipient=_user_email(initials), link_text=link_text,
                           link_url=link_url, extra_links=extra, **_personal_card_args(pdata))


def post_all_personal_to_teams(user_filter=None) -> dict:
    """Publica una tarjeta por persona (omite quienes no tienen pendientes)."""
    from core.services import teams
    docs = monitoring_service.get_monitoring_data()
    start, end = _get_weekly_range()
    ws, we = start.strftime("%d/%m"), end.strftime("%d/%m")
    avg = _team_avg_pct(docs)

    users = USERS
    if user_filter and user_filter != "all" and isinstance(user_filter, list):
        users = {k: v for k, v in USERS.items() if k in user_filter}

    sent, skipped, errors = [], [], []
    for initials in users:
        pdata = _collect_personal_data(initials, docs, avg, ws, we)
        if pdata["my_pending_total"] == 0:
            skipped.append(initials)
            continue
        link_text, link_url, extra = _save_personal_report(initials, pdata)
        res = teams.post_card(recipient=_user_email(initials), link_text=link_text,
                              link_url=link_url, extra_links=extra, **_personal_card_args(pdata))
        (sent if res.get("ok") else errors).append(initials)
        time.sleep(0.4)
    return {"status": "sent", "sent": sent, "skipped": skipped,
            "errors": errors, "count": len(sent)}
