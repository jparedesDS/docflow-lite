"""Informe interactivo (semanal / mensual) en HTML autocontenido.

Genera un informe web de un solo archivo `.html` con KPIs, gráficos interactivos
(Chart.js inline → funciona offline y es portable: se archiva o se adjunta por
email) y un resumen narrativo (Claude Haiku, con fallback a plantilla).

Estructura del informe:
  • Resumen narrativo (IA opcional)
  • KPIs del periodo con variación vs periodo anterior (Δ)
  • Actividad diaria/semanal (línea)
  • Distribución de actividad por estado (donut)
  • Actividad por responsable (barras)
  • Estado actual de la cartera (snapshot global)
  • Documentos en riesgo (tabla de antigüedad)

El "periodo" se calcula sobre los eventos datados del documento: las entradas
de `Historial Rev.` (envío / aprobación / devolución) más el envío de la
revisión actual (`Fecha Env. Doc.`). Los KPIs de cartera y la tabla de riesgo
son una foto del estado actual (no dependen del periodo).
"""

from __future__ import annotations

import html
import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.config import ANTHROPIC_API_KEY
from core.paths import resource_path, state_dir
from core.services import analytics as analytics_service
from core.services import monitoring as monitoring_service

logger = logging.getLogger(__name__)

_MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
          "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
_MESES_ABBR = ["", "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago",
               "sep", "oct", "nov", "dic"]

# Paleta del informe (fija, indigo — coherente con los emails, independiente del
# tema de la app para que el informe se vea igual archivado o reenviado).
ACCENT = "#4F46E5"
GREEN = "#16A34A"
AMBER = "#D97706"
RED = "#DC2626"
BLUE = "#2563EB"
SLATE = "#64748B"

# Placeholders de responsable que no representan personas reales.
_OCULTAR_RESP = {"", "SI", "ES", "Sin Asignar", "Sin asignar"}


# ════════════════════════════════════════════════════════════════════════════
#  Ventanas de periodo
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class Window:
    start: datetime
    end: datetime          # exclusivo
    label: str
    key: str               # p.ej. "2026-S25" o "2026-06"


def _period_window(period: str, ref: datetime) -> Window:
    ref = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "monthly":
        start = ref.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)
        label = f"{_MESES[start.month]} {start.year}"
        key = start.strftime("%Y-%m")
    else:  # weekly
        start = ref - timedelta(days=ref.weekday())  # lunes
        end = start + timedelta(days=7)
        last = end - timedelta(days=1)
        iso = start.isocalendar()
        label = (f"Semana {iso.week} · {start.day} {_MESES_ABBR[start.month]} – "
                 f"{last.day} {_MESES_ABBR[last.month]} {last.year}")
        key = f"{iso.year}-S{iso.week:02d}"
    return Window(start, end, label, key)


def _previous_window(period: str, cur_start: datetime) -> Window:
    prev_ref = cur_start - timedelta(days=1 if period == "monthly" else 7)
    return _period_window(period, prev_ref)


def get_available_periods(period: str, n: int = 8) -> list[tuple[str, str]]:
    """[(label, ref_date_iso), …] para los últimos `n` periodos (incluye el actual)."""
    out: list[tuple[str, str]] = []
    win = _period_window(period, datetime.now())
    for _ in range(n):
        out.append((win.label, win.start.isoformat()))
        win = _previous_window(period, win.start)
    return out


# ════════════════════════════════════════════════════════════════════════════
#  Eventos datados por documento
# ════════════════════════════════════════════════════════════════════════════

def _classify(estado: str) -> str | None:
    e = (estado or "").lower().strip()
    if "aprobado" in e:
        return "aprobado"
    if any(s in e for s in ("rechazado", "com.", "comentado", "devuel")):
        return "devuelto"
    if "enviado" in e:
        return "enviado"
    return None


def _doc_events(doc: dict) -> list[tuple[datetime, str]]:
    """Eventos (fecha, tipo) del documento. tipo ∈ {enviado, aprobado, devuelto}."""
    events: list[tuple[datetime, str]] = []
    seen: set[tuple] = set()
    hist = str(doc.get("Historial Rev.", "") or "")
    for tok in hist.split("//"):
        m = monitoring_service._REV_HIST_RE.search(tok)
        if not m:
            continue
        d = monitoring_service._parse_date(m.group(1))
        kind = _classify(m.group(2))
        if d is None or kind is None:
            continue
        key = (d.date(), kind)
        if key not in seen:
            seen.add(key)
            events.append((d, kind))

    # Envío de la revisión actual (no siempre figura en el historial)
    cur = monitoring_service._parse_date(doc.get("Fecha Env. Doc.") or doc.get("Fecha"))
    if cur is not None and (cur.date(), "enviado") not in seen:
        events.append((cur, "enviado"))
    return events


# ════════════════════════════════════════════════════════════════════════════
#  Construcción de datos del informe
# ════════════════════════════════════════════════════════════════════════════

def _num(v):
    return monitoring_service._try_int(v)


def _es_critico(d) -> bool:
    return str(d.get("Crítico", "") or "").lower().strip() in ("sí", "si")


def _delta(cur: int, prev: int) -> dict:
    diff = cur - prev
    pct = round(diff / prev * 100) if prev else None
    return {"diff": diff, "pct": pct}


def _series(cur_ev: list, win: Window, period: str) -> dict:
    if period == "monthly":
        ndays = (win.end - win.start).days
        labels = [str(i + 1) for i in range(ndays)]
        values = [0] * ndays
        for dt, *_ in cur_ev:
            idx = (dt.date() - win.start.date()).days
            if 0 <= idx < ndays:
                values[idx] += 1
        return {"labels": labels, "values": values}
    names = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    values = [0] * 7
    for dt, *_ in cur_ev:
        idx = (dt.date() - win.start.date()).days
        if 0 <= idx < 7:
            values[idx] += 1
    return {"labels": names, "values": values}


def _by_responsable(cur_ev_docs: list) -> dict:
    c: Counter = Counter()
    for _, _, doc in cur_ev_docs:
        resp = str(doc.get("Repsonsable", "") or "").strip()
        if resp in _OCULTAR_RESP:
            continue
        c[resp] += 1
    top = c.most_common(10)
    return {"labels": [k for k, _ in top], "values": [v for _, v in top]}


def _aging(docs: list, limit: int = 12) -> list[dict]:
    rows = []
    for d in docs:
        estado = str(d.get("Estado", "") or "").lower().strip()
        if "aprobado" in estado or estado == "enviado":
            continue
        dias = _num(d.get("Días Devolución"))
        if dias is None or dias <= 0:
            continue
        rows.append({
            "pedido": str(d.get("Nº Pedido", "") or ""),
            "doc": str(d.get("Nº Doc. EIPSA", "") or "") or str(d.get("Título", "") or ""),
            "resp": str(d.get("Repsonsable", "") or ""),
            "estado": str(d.get("Estado", "") or "Sin enviar"),
            "dias": int(dias),
            "critico": _es_critico(d),
        })
    rows.sort(key=lambda r: r["dias"], reverse=True)
    return rows[:limit]


def build_report_data(period: str = "weekly", ref_date: datetime | None = None,
                      with_ai: bool = True) -> dict:
    """Agrega todos los datos del informe para `period` ∈ {weekly, monthly}."""
    period = "monthly" if period == "monthly" else "weekly"
    docs = monitoring_service.get_monitoring_data()
    win = _period_window(period, ref_date or datetime.now())
    prev = _previous_window(period, win.start)

    cur_ev_docs, prev_ev = [], []
    for d in docs:
        for dt, kind in _doc_events(d):
            if win.start <= dt < win.end:
                cur_ev_docs.append((dt, kind, d))
            elif prev.start <= dt < prev.end:
                prev_ev.append((dt, kind))

    def _counts(evs) -> dict:
        c = {"movimientos": len(evs), "enviado": 0, "aprobado": 0, "devuelto": 0}
        for item in evs:
            kind = item[1]
            c[kind] = c.get(kind, 0) + 1
        return c

    cc = _counts(cur_ev_docs)
    pc = _counts(prev_ev)

    kpis = [
        {"label": "Movimientos", "value": cc["movimientos"],
         "delta": _delta(cc["movimientos"], pc["movimientos"]), "good_up": True},
        {"label": "Enviados", "value": cc["enviado"],
         "delta": _delta(cc["enviado"], pc["enviado"]), "good_up": True},
        {"label": "Aprobados", "value": cc["aprobado"],
         "delta": _delta(cc["aprobado"], pc["aprobado"]), "good_up": True},
        {"label": "Devoluciones", "value": cc["devuelto"],
         "delta": _delta(cc["devuelto"], pc["devuelto"]), "good_up": False},
    ]

    snap = monitoring_service.compute_kpis(docs)
    snapshot = {
        "total": snap["total"],
        "pct_global": snap["pct_completado"],
        "criticos": snap["criticos"],
        "riesgo": snap["criticos_15d"],
        "media_dias": snap["media_dias_devolucion"],
    }

    estado_donut = {
        "labels": ["Enviado", "Aprobado", "Devuelto"],
        "values": [cc["enviado"], cc["aprobado"], cc["devuelto"]],
        "colors": [BLUE, GREEN, AMBER],
    }

    data = {
        "meta": {
            "title": f"Informe {'mensual' if period == 'monthly' else 'semanal'} de documentación",
            "period_label": win.label,
            "period_kind": period,
            "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "prepared_by": "jparedesDS",
            "key": win.key,
        },
        "kpis": kpis,
        "series": _series(cur_ev_docs, win, period),
        "estado": estado_donut,
        "resp": _by_responsable(cur_ev_docs),
        "snapshot": snapshot,
        "aging": _aging(docs),
    }
    data["narrative"] = _narrative(data, with_ai=with_ai)
    return data


# ════════════════════════════════════════════════════════════════════════════
#  Narrativa (Claude Haiku con fallback)
# ════════════════════════════════════════════════════════════════════════════

def _fallback_narrative(d: dict) -> str:
    k = {x["label"]: x for x in d["kpis"]}
    mov = k["Movimientos"]
    diff = mov["delta"]["diff"]
    tend = ("se mantuvo estable" if diff == 0 else
            (f"creció en {diff}" if diff > 0 else f"bajó en {abs(diff)}"))
    resp = d["resp"]
    top_resp = f" El responsable con más actividad fue {resp['labels'][0]}." if resp["labels"] else ""
    return (
        f"Durante {d['meta']['period_label'].split('·')[0].strip().lower()} se registraron "
        f"{mov['value']} movimientos (la actividad {tend} respecto al periodo anterior): "
        f"{k['Enviados']['value']} envíos, {k['Aprobados']['value']} aprobaciones y "
        f"{k['Devoluciones']['value']} devoluciones. La cartera mantiene un "
        f"{d['snapshot']['pct_global']}% de aprobación global, con "
        f"{d['snapshot']['riesgo']} documento(s) crítico(s) en riesgo (+15 días sin respuesta)."
        f"{top_resp}"
    )


def _build_ai_prompt(d: dict) -> str:
    k = {x["label"]: x for x in d["kpis"]}
    def line(lbl):
        x = k[lbl]
        dd = x["delta"]["diff"]
        return f"- {lbl}: {x['value']} (Δ {'+' if dd >= 0 else ''}{dd} vs periodo anterior)"
    return f"""Eres un asistente ejecutivo de un equipo de Document Control (documentación técnica de ingeniería).
Redacta un PÁRRAFO EJECUTIVO BREVE (2-3 frases, español, tono profesional) para el
informe del periodo «{d['meta']['period_label']}» con estos datos:

{line('Movimientos')}
{line('Enviados')}
{line('Aprobados')}
{line('Devoluciones')}
- Aprobación global de la cartera: {d['snapshot']['pct_global']}%
- Documentos críticos en riesgo (+15 días): {d['snapshot']['riesgo']}
- Velocidad media de respuesta: {d['snapshot']['media_dias']} días

Menciona la tendencia, el punto de atención más crítico y una acción recomendada.
Solo un párrafo, sin HTML ni markdown, directo y accionable."""


def _ask_haiku(prompt: str) -> str | None:
    """Llama a Claude Haiku; devuelve el texto o None (sin key / fallo de red)."""
    if not (ANTHROPIC_API_KEY or "").strip():
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY.strip())
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        logger.warning("Haiku falló, usando fallback: %s", exc)
        return None


def _narrative(d: dict, with_ai: bool = True) -> str:
    if with_ai:
        txt = _ask_haiku(_build_ai_prompt(d))
        if txt:
            return txt
    return _fallback_narrative(d)


# ════════════════════════════════════════════════════════════════════════════
#  Render HTML autocontenido
# ════════════════════════════════════════════════════════════════════════════

def _esc(v) -> str:
    return html.escape(str(v), quote=True)


def _chartjs_source() -> str:
    """Devuelve el código de Chart.js para inyectarlo inline (offline). Si no se
    encuentra el vendor, devuelve un <script src> a jsdelivr como último recurso."""
    path = resource_path("assets/vendor/chart.umd.min.js")
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        logger.warning("Chart.js vendor no encontrado en %s; usando CDN", path)
        return ""


# Búsqueda + filtro por estado + orden por columna + filas expandibles.
# CSS y JS vanilla (sin dependencias), inyectados en los informes con tablas.
_TABLE_CSS = """
  .tbl-tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:12px;}
  .tbl-search,.tbl-status{font:inherit;font-size:13px;padding:7px 11px;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink);}
  .tbl-search{flex:1;min-width:170px;}
  .tbl-status{cursor:pointer;}
  .tbl-count{font-size:12px;color:var(--muted);font-weight:600;}
  .tbl-hint{font-size:12px;color:var(--muted);}
  th.sortable{cursor:pointer;user-select:none;white-space:nowrap;}
  th.sortable:hover{color:var(--accent);}
  th[data-dir=asc]::after{content:' \\25B2';font-size:9px;}
  th[data-dir=desc]::after{content:' \\25BC';font-size:9px;}
  tr.expandable{cursor:pointer;}
  tr.expandable:hover{background:#F8FAFC;}
  tr.expandable.open{background:#F5F3FF;}
  tr.expandable td:first-child::before{content:'\\25B8';color:var(--muted);margin-right:7px;font-size:10px;display:inline-block;}
  tr.expandable.open td:first-child::before{content:'\\25BE';}
  tr.detail td{background:#F8FAFC;padding:14px 16px;border-top:0;}
  .detail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px 20px;}
  .detail-grid .lab{margin:0;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);}
  .detail-grid .val{margin:2px 0 0;font-size:13px;word-break:break-word;}
  .detail-hist{margin:3px 0 0;font-family:'Consolas',monospace;font-size:12px;color:var(--sub);white-space:pre-wrap;word-break:break-word;}
  @media print{.tbl-tools{display:none;}tr.detail{display:none!important;}}
"""

_TABLE_JS = """
(function(){
  function norm(s){return (s||'').toString().toLowerCase();}
  function bodyRows(t){return Array.prototype.slice.call(t.tBodies[0].rows);}
  function dataRows(t){return bodyRows(t).filter(function(r){return !r.classList.contains('detail');});}
  function applyFilter(panel){
    var t=panel.querySelector('table'); if(!t||!t.tBodies.length) return;
    var s=panel.querySelector('.tbl-search'); var q=norm(s?s.value:'');
    var sel=panel.querySelector('.tbl-status'); var st=sel?sel.value:'';
    var shown=0,total=0;
    bodyRows(t).forEach(function(tr){
      if(tr.classList.contains('detail')) return;
      total++;
      var okQ=!q||norm(tr.textContent).indexOf(q)>=0;
      var okS=!st||st==='all'||tr.getAttribute('data-estado')===st;
      var show=okQ&&okS; tr.hidden=!show;
      var d=tr.nextElementSibling;
      if(d&&d.classList.contains('detail')&&!show){d.hidden=true;tr.classList.remove('open');}
      if(show) shown++;
    });
    var c=panel.querySelector('.tbl-count'); if(c) c.textContent=shown+' / '+total;
  }
  function wireSort(t){
    t.querySelectorAll('th[data-sort]').forEach(function(th){
      th.classList.add('sortable');
      th.addEventListener('click',function(){
        var idx=Array.prototype.indexOf.call(th.parentNode.children,th);
        var num=th.getAttribute('data-sort')==='num';
        var dir=th.getAttribute('data-dir')==='asc'?-1:1;
        th.parentNode.querySelectorAll('th').forEach(function(o){o.removeAttribute('data-dir');});
        th.setAttribute('data-dir',dir===1?'asc':'desc');
        var b=t.tBodies[0]; var rows=dataRows(t);
        rows.sort(function(a,c){
          var x=a.cells[idx].textContent.trim(),y=c.cells[idx].textContent.trim();
          if(num){x=parseFloat(x.replace(/[^0-9.-]/g,''))||0;y=parseFloat(y.replace(/[^0-9.-]/g,''))||0;return (x-y)*dir;}
          return x.localeCompare(y,'es')*dir;
        });
        rows.forEach(function(r){b.appendChild(r);});
      });
    });
  }
  function wireExpand(t){
    bodyRows(t).forEach(function(tr){
      if(!tr.classList.contains('expandable')) return;
      tr.addEventListener('click',function(){
        var d=tr.nextElementSibling;
        if(d&&d.classList.contains('detail')){d.hidden=!d.hidden;tr.classList.toggle('open');}
      });
    });
  }
  document.querySelectorAll('.tbl-panel').forEach(function(panel){
    var t=panel.querySelector('table'); if(!t) return;
    var s=panel.querySelector('.tbl-search'); if(s) s.addEventListener('input',function(){applyFilter(panel);});
    var sel=panel.querySelector('.tbl-status'); if(sel) sel.addEventListener('change',function(){applyFilter(panel);});
    if(t.querySelector('th[data-sort]')) wireSort(t);
    wireExpand(t);
    applyFilter(panel);
  });
})();
"""


def _kpi_card_html(k: dict) -> str:
    d = k["delta"]
    diff = d["diff"]
    if diff == 0 or d["pct"] is None and diff == 0:
        delta_html = '<span class="delta flat">— sin cambios</span>'
    else:
        up = diff > 0
        good = up if k["good_up"] else not up
        cls = "up" if good else "down"
        arrow = "▲" if up else "▼"
        pct = f" ({'+' if up else ''}{d['pct']}%)" if d["pct"] is not None else ""
        delta_html = f'<span class="delta {cls}">{arrow} {"+" if up else ""}{diff}{pct}</span>'
    return (
        f'<div class="kpi"><p class="kpi-label">{_esc(k["label"])}</p>'
        f'<p class="kpi-value">{_esc(k["value"])}</p>{delta_html}</div>'
    )


def _aging_rows_html(rows: list[dict]) -> str:
    if not rows:
        return ('<tr><td colspan="4" class="empty">Sin documentos pendientes con '
                'antigüedad registrada.</td></tr>')
    mx = max((r["dias"] for r in rows), default=1) or 1
    out = []
    for r in rows:
        dias = r["dias"]
        col = RED if dias > 15 else (AMBER if dias > 7 else GREEN)
        pct = min(100, round(dias / mx * 100))
        crit = ' <span class="crit">crítico</span>' if r["critico"] else ""
        out.append(
            f'<tr><td class="mono">{_esc(r["pedido"])}</td>'
            f'<td class="muted">{_esc(r["doc"][:42])}{crit}</td>'
            f'<td>{_esc(r["resp"])}</td>'
            f'<td><div class="bar-wrap"><div class="bar-track">'
            f'<div class="bar-fill" style="width:{pct}%;background:{col}"></div></div>'
            f'<span style="color:{col};font-weight:600">{dias}</span></div></td></tr>'
        )
    return "".join(out)


def render_html(data: dict) -> str:
    meta = data["meta"]
    kpis_html = "".join(_kpi_card_html(k) for k in data["kpis"])
    aging_html = _aging_rows_html(data["aging"])
    chartjs = _chartjs_source()
    chart_tag = (f"<script>{chartjs}</script>" if chartjs else
                 '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>')

    payload = json.dumps({
        "series": data["series"],
        "estado": data["estado"],
        "resp": data["resp"],
        "accent": ACCENT,
    }, ensure_ascii=False)

    snap = data["snapshot"]
    is_month = meta["period_kind"] == "monthly"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(meta['title'])} · {_esc(meta['period_label'])}</title>
<style>
  :root {{ --accent:{ACCENT}; --ink:#0F172A; --sub:#475569; --muted:#94A3B8;
           --line:#E2E8F0; --card:#FFFFFF; --bg:#EEF1F8; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
          font-family:'Segoe UI',system-ui,-apple-system,Roboto,Arial,sans-serif;
          line-height:1.5; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:32px 20px 56px; }}
  header {{ display:flex; align-items:center; justify-content:space-between; gap:16px;
            flex-wrap:wrap; border-bottom:2px solid var(--accent); padding-bottom:18px; }}
  .brand {{ display:flex; align-items:center; gap:14px; }}
  .logo {{ width:44px; height:44px; border-radius:10px; background:var(--accent);
           display:flex; align-items:center; justify-content:center; color:#fff;
           font-size:22px; font-weight:700; }}
  h1 {{ font-size:21px; margin:0; letter-spacing:-.01em; }}
  .sub {{ color:var(--sub); font-size:13px; margin:3px 0 0; }}
  .badge {{ background:var(--accent); color:#fff; font-size:13px; font-weight:600;
            padding:7px 16px; border-radius:8px; white-space:nowrap; }}
  .narr {{ background:#F5F3FF; border-left:4px solid var(--accent); border-radius:0 10px 10px 0;
           padding:16px 20px; margin:22px 0; font-size:14.5px; color:#1e293b; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--accent);
        margin:30px 0 12px; font-weight:700; }}
  .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }}
  .kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; }}
  .kpi-label {{ margin:0; font-size:12px; color:var(--sub); }}
  .kpi-value {{ margin:6px 0 4px; font-size:30px; font-weight:700; line-height:1; }}
  .delta {{ font-size:12px; font-weight:600; }}
  .delta.up {{ color:{GREEN}; }} .delta.down {{ color:{RED}; }} .delta.flat {{ color:var(--muted); }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px 20px; }}
  .card h3 {{ margin:0 0 14px; font-size:14px; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:14px; margin-bottom:10px; font-size:12px; color:var(--sub); }}
  .legend i {{ width:10px; height:10px; border-radius:2px; display:inline-block; margin-right:5px; vertical-align:middle; }}
  .chart-box {{ position:relative; height:230px; }}
  .snap {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }}
  .snap .kpi-value {{ font-size:26px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.04em;
        color:var(--muted); font-weight:600; padding:8px 10px; }}
  td {{ padding:9px 10px; border-top:1px solid var(--line); }}
  td.mono {{ font-family:'Consolas',monospace; }}
  td.muted {{ color:var(--sub); }}
  .crit {{ color:{RED}; font-size:11px; font-weight:600; }}
  .empty {{ text-align:center; color:var(--muted); padding:18px; }}
  .bar-wrap {{ display:flex; align-items:center; gap:9px; }}
  .bar-track {{ flex:1; height:6px; border-radius:3px; background:#EEF1F8; overflow:hidden; }}
  .bar-fill {{ height:6px; border-radius:3px; }}
  footer {{ margin-top:34px; padding-top:16px; border-top:1px solid var(--line);
            display:flex; justify-content:space-between; color:var(--muted); font-size:12px; }}
  footer a {{ color:var(--accent); text-decoration:none; }}
  @media (max-width:720px) {{ .kpis,.snap {{ grid-template-columns:repeat(2,1fr); }} .grid2 {{ grid-template-columns:1fr; }} }}
  @media print {{ body {{ background:#fff; }} .wrap {{ max-width:none; }}
    .card,.kpi {{ break-inside:avoid; }} h2 {{ break-after:avoid; }} }}
{_TABLE_CSS}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="logo">◆</div>
      <div>
        <h1>{_esc(meta['title'])}</h1>
        <p class="sub">{_esc(meta['period_label'])} · generado {_esc(meta['generated'])}</p>
      </div>
    </div>
    <span class="badge">{'Mensual' if is_month else 'Semanal'}</span>
  </header>

  <div class="narr">{_esc(data['narrative'])}</div>

  <h2>KPIs del periodo</h2>
  <div class="kpis">{kpis_html}</div>

  <h2>Análisis del periodo</h2>
  <div class="grid2">
    <div class="card">
      <h3>Distribución de actividad por estado</h3>
      <div class="legend">
        <span><i style="background:{BLUE}"></i>Enviado</span>
        <span><i style="background:{GREEN}"></i>Aprobado</span>
        <span><i style="background:{AMBER}"></i>Devuelto</span>
      </div>
      <div class="chart-box"><canvas id="estadoChart"></canvas></div>
    </div>
    <div class="card">
      <h3>Actividad por responsable</h3>
      <div class="chart-box"><canvas id="respChart"></canvas></div>
    </div>
  </div>
  <div class="card" style="margin-top:16px">
    <h3>Actividad {'diaria' if not is_month else 'por día del mes'}</h3>
    <div class="chart-box"><canvas id="dailyChart"></canvas></div>
  </div>

  <h2>Estado actual de la cartera</h2>
  <div class="snap">
    <div class="kpi"><p class="kpi-label">Documentos totales</p><p class="kpi-value">{snap['total']}</p></div>
    <div class="kpi"><p class="kpi-label">Aprobación global</p><p class="kpi-value" style="color:{GREEN}">{snap['pct_global']}%</p></div>
    <div class="kpi"><p class="kpi-label">Críticos</p><p class="kpi-value" style="color:{RED if snap['criticos'] else GREEN}">{snap['criticos']}</p></div>
    <div class="kpi"><p class="kpi-label">En riesgo (+15d)</p><p class="kpi-value" style="color:{RED if snap['riesgo'] else GREEN}">{snap['riesgo']}</p></div>
  </div>

  <h2>Documentos en riesgo · mayor antigüedad sin movimiento</h2>
  <div class="tbl-panel card" style="padding:14px 16px">
    <div class="tbl-tools">
      <input class="tbl-search" type="text" placeholder="Buscar pedido, documento o responsable…">
      <span class="tbl-count"></span>
    </div>
    <table>
      <thead><tr><th data-sort="text">Pedido</th><th data-sort="text">Documento</th>
        <th data-sort="text">Resp.</th><th data-sort="num" style="width:160px">Días sin mover</th></tr></thead>
      <tbody>{aging_html}</tbody>
    </table>
  </div>

  <footer>
    <span>DocFlow · Informe de documentación</span>
    <span>© 2026 <a href="https://github.com/jparedesDS">{_esc(meta['prepared_by'])}</a></span>
  </footer>
</div>
{chart_tag}
<script>
(function() {{
  var D = {payload};
  if (typeof Chart === "undefined") return;
  Chart.defaults.font.family = "'Segoe UI',system-ui,sans-serif";
  Chart.defaults.color = "#64748B";
  var noLegend = {{ legend: {{ display: false }} }};
  new Chart(document.getElementById("estadoChart"), {{
    type: "doughnut",
    data: {{ labels: D.estado.labels, datasets: [{{ data: D.estado.values,
             backgroundColor: D.estado.colors, borderWidth: 0 }}] }},
    options: {{ responsive: true, maintainAspectRatio: false, cutout: "62%",
               plugins: noLegend }}
  }});
  new Chart(document.getElementById("respChart"), {{
    type: "bar",
    data: {{ labels: D.resp.labels, datasets: [{{ data: D.resp.values,
             backgroundColor: D.accent, borderRadius: 4 }}] }},
    options: {{ indexAxis: "y", responsive: true, maintainAspectRatio: false,
               plugins: noLegend, scales: {{ x: {{ beginAtZero: true,
               ticks: {{ precision: 0 }} }} }} }}
  }});
  new Chart(document.getElementById("dailyChart"), {{
    type: "line",
    data: {{ labels: D.series.labels, datasets: [{{ data: D.series.values,
             borderColor: D.accent, backgroundColor: "rgba(79,70,229,.14)",
             fill: true, tension: .35, pointRadius: 3,
             pointBackgroundColor: D.accent }}] }},
    options: {{ responsive: true, maintainAspectRatio: false, plugins: noLegend,
               scales: {{ y: {{ beginAtZero: true, ticks: {{ precision: 0 }} }} }} }}
  }});
}})();
</script>
<script>{_TABLE_JS}</script>
</body>
</html>"""


# ════════════════════════════════════════════════════════════════════════════
#  Persistencia / envío
# ════════════════════════════════════════════════════════════════════════════

def reports_dir():
    p = state_dir() / "reports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_filename(data: dict) -> str:
    kind = "Mensual" if data["meta"]["period_kind"] == "monthly" else "Semanal"
    return f"Informe_{kind}_{data['meta']['key']}.html"


def generate(period: str = "weekly", ref_date: datetime | None = None,
             with_ai: bool = True):
    """Construye los datos, renderiza el HTML y lo guarda en state/reports/.
    Devuelve (Path, data)."""
    data = build_report_data(period, ref_date, with_ai=with_ai)
    html_str = render_html(data)
    path = reports_dir() / default_filename(data)
    path.write_text(html_str, encoding="utf-8")
    logger.info("Informe generado: %s", path)
    return path, data


def _email_body(data: dict) -> str:
    meta = data["meta"]
    return (
        '<div style="font-family:Segoe UI,Arial,sans-serif;color:#0F172A;font-size:14px;line-height:1.6">'
        f'<p>Hola,</p>'
        f'<p>Adjunto el <b>{_esc(meta["title"])}</b> correspondiente a '
        f'<b>{_esc(meta["period_label"])}</b>. Ábrelo en el navegador para ver los '
        f'gráficos interactivos (KPIs, actividad, responsables y documentos en riesgo).</p>'
        '<p style="color:#475569">Generado automáticamente por DocFlow.</p>'
        '<p style="color:#94A3B8;font-size:12px">© jparedesDS</p>'
        '</div>'
    )


def send_email(period: str = "weekly", to: list[str] | None = None,
               cc: list[str] | None = None, ref_date: datetime | None = None) -> dict:
    """Genera el informe y lo envía adjunto (.html) por SMTP."""
    if not to:
        return {"status": "skipped", "reason": "Sin destinatarios"}
    from core.services.smtp import send_html_email

    data = build_report_data(period, ref_date)
    html_str = render_html(data)
    fname = default_filename(data)
    subject = f"{data['meta']['title']} — {data['meta']['period_label']}"
    result = send_html_email(
        to=to, cc=cc or [], subject=subject, html_body=_email_body(data),
        attachment_eml=html_str.encode("utf-8"), attachment_name=fname)
    # Guarda también copia local
    try:
        (reports_dir() / fname).write_text(html_str, encoding="utf-8")
    except Exception:
        logger.debug("No se pudo guardar copia local del informe", exc_info=True)
    result["status"] = "sent"
    result["recipients"] = to
    return result


# ════════════════════════════════════════════════════════════════════════════
#  Reporte Ejecutivo (analítica global, interactivo)
# ════════════════════════════════════════════════════════════════════════════

def _pct_color(p) -> str:
    try:
        p = float(p)
    except (TypeError, ValueError):
        return SLATE
    return GREEN if p >= 75 else (AMBER if p >= 50 else RED)


def _score_color(s) -> str:
    try:
        s = float(s)
    except (TypeError, ValueError):
        return SLATE
    return GREEN if s >= 80 else (AMBER if s >= 50 else RED)


def build_executive_report_data(ref_date: datetime | None = None,
                                with_ai: bool = True) -> dict:
    """Datos del reporte ejecutivo (foto global de la cartera)."""
    summary = analytics_service.get_summary()
    ranking = analytics_service.get_ranking()
    pred_all = analytics_service.get_predicciones()
    score = analytics_service.get_scorecard()
    ref = ref_date or datetime.now()

    total = (summary["total_aprobados"] + summary["total_enviados"]
             + summary["total_devoluciones"] + summary["total_sin_enviar"])
    pct = round(summary["total_aprobados"] / total * 100) if total else 0

    top_cli = summary["por_cliente"][:8]
    pred_risk = [x for x in pred_all
                 if x.get("pct_esperado") is not None and x.get("en_plazo") is False]
    pred_risk.sort(key=lambda x: (x["pct"] - x["pct_esperado"]))

    kpis = [
        {"label": "Documentos", "value": total, "color": ACCENT, "sub": "en seguimiento"},
        {"label": "Aprobación global", "value": f"{pct}%", "color": GREEN,
         "sub": f"{summary['total_aprobados']} aprobados"},
        {"label": "Velocidad media", "value": f"{summary['velocidad_media_dias']}d",
         "color": BLUE, "sub": "respuesta cliente"},
        {"label": "En riesgo", "value": summary["docs_riesgo"],
         "color": RED if summary["docs_riesgo"] else GREEN, "sub": "críticos +15d"},
        {"label": "Clientes OK", "value": f"{summary['clientes_ok']}/{summary['total_clientes']}",
         "color": GREEN, "sub": "≥75% aprobado"},
        {"label": "Vencen ≤3d", "value": summary["a_vencer_3d"],
         "color": AMBER if summary["a_vencer_3d"] else GREEN, "sub": "casi fuera de plazo"},
    ]

    data = {
        "meta": {
            "title": "Reporte ejecutivo de documentación",
            "period_label": f"{_MESES[ref.month]} {ref.year}",
            "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "prepared_by": "jparedesDS",
            "key": ref.strftime("%Y-%m"),
        },
        "totals": {"total": total, "pct": pct,
                   "aprobados": summary["total_aprobados"],
                   "enviados": summary["total_enviados"],
                   "devoluciones": summary["total_devoluciones"],
                   "sin_enviar": summary["total_sin_enviar"]},
        "kpis": kpis,
        "estado": {"labels": ["Aprobado", "Enviado", "Devoluciones", "Sin enviar"],
                   "values": [summary["total_aprobados"], summary["total_enviados"],
                              summary["total_devoluciones"], summary["total_sin_enviar"]],
                   "colors": [GREEN, BLUE, AMBER, SLATE]},
        "clientes": {"labels": [str(c["cliente"])[:18] for c in top_cli],
                     "values": [c["media_dias"] for c in top_cli]},
        "ranking": ranking,
        "pred": pred_risk[:14],
        "scorecard": score[:18],
    }
    data["narrative"] = _executive_narrative(data, with_ai=with_ai)
    return data


def _executive_fallback(d: dict) -> str:
    t = d["totals"]
    n_risk = len(d["pred"])
    riesgo = next((k["value"] for k in d["kpis"] if k["label"] == "En riesgo"), 0)
    return (
        f"La cartera reúne {t['total']} documentos con un {t['pct']}% de aprobación global "
        f"({t['aprobados']} aprobados, {t['enviados']} en revisión del cliente y "
        f"{t['devoluciones']} con comentarios). Hay {riesgo} documento(s) crítico(s) en riesgo "
        f"y {n_risk} pedido(s) con previsión de retraso que requieren seguimiento prioritario."
    )


def _executive_ai_prompt(d: dict) -> str:
    t = d["totals"]
    riesgo = next((k["value"] for k in d["kpis"] if k["label"] == "En riesgo"), 0)
    vel = next((k["value"] for k in d["kpis"] if k["label"] == "Velocidad media"), "")
    top_resp = ", ".join(f"{r['responsable']} ({r['pct']}%)" for r in d["ranking"][:3])
    return f"""Eres un asistente ejecutivo de Document Control. Redacta un PÁRRAFO EJECUTIVO
(3-4 frases, español, profesional) para la dirección, con la foto global de la cartera
de documentación técnica ({d['meta']['period_label']}):
- Documentos totales: {t['total']} · aprobación global: {t['pct']}%
- Aprobados: {t['aprobados']} · enviados (en cliente): {t['enviados']} · devoluciones: {t['devoluciones']} · sin enviar: {t['sin_enviar']}
- Velocidad media de respuesta: {vel}
- Documentos críticos en riesgo (+15 días): {riesgo}
- Pedidos con previsión de retraso: {len(d['pred'])}
- Mejores responsables por % aprobación: {top_resp or 'n/d'}

Resume el estado general, destaca el riesgo principal y propón una acción. Sin HTML ni markdown."""


def _executive_narrative(d: dict, with_ai: bool = True) -> str:
    if with_ai:
        txt = _ask_haiku(_executive_ai_prompt(d))
        if txt:
            return txt
    return _executive_fallback(d)


def _exec_kpi_html(k: dict) -> str:
    return (
        f'<div class="kpi"><p class="kpi-label">{_esc(k["label"])}</p>'
        f'<p class="kpi-value" style="color:{k["color"]}">{_esc(k["value"])}</p>'
        f'<p class="kpi-sub">{_esc(k["sub"])}</p></div>'
    )


def _exec_ranking_html(ranking: list[dict]) -> str:
    if not ranking:
        return '<tr><td colspan="8" class="empty">Sin datos de equipo.</td></tr>'
    out = []
    for i, r in enumerate(ranking):
        col = _pct_color(r["pct"])
        out.append(
            f'<tr><td style="text-align:center;color:var(--muted)">#{i + 1}</td>'
            f'<td>{_esc(r["responsable"])}</td>'
            f'<td style="text-align:center">{r["total"]}</td>'
            f'<td style="text-align:center">{r["aprobados"]}</td>'
            f'<td style="text-align:center;color:{col};font-weight:600">{r["pct"]}%</td>'
            f'<td style="text-align:center">{r["devoluciones"]}</td>'
            f'<td style="text-align:center">{r["tasa_devolucion"]}%</td>'
            f'<td style="text-align:center">{r["criticos"]}</td></tr>'
        )
    return "".join(out)


def _exec_pred_html(pred: list[dict]) -> str:
    if not pred:
        return ('<tr><td colspan="7" class="empty">Ningún pedido con previsión de '
                'retraso. ✓</td></tr>')
    out = []
    for x in pred:
        desv = x["pct"] - x["pct_esperado"]
        out.append(
            f'<tr><td class="mono">{_esc(x["pedido"])}</td>'
            f'<td style="text-align:center">{x["pct"]}%</td>'
            f'<td style="text-align:center">{x["pct_esperado"]}%</td>'
            f'<td style="text-align:center;color:{RED};font-weight:600">{desv}pp</td>'
            f'<td style="text-align:center">{x["aprobados"]}/{x["total"]}</td>'
            f'<td style="text-align:center">{_esc(x.get("fecha_prevista") or "—")}</td>'
            f'<td style="text-align:center">{_esc(x.get("prediccion_fecha") or "—")}</td></tr>'
        )
    return "".join(out)


def _exec_scorecard_html(score: list[dict]) -> str:
    if not score:
        return '<tr><td colspan="6" class="empty">Sin datos de scorecard.</td></tr>'
    out = []
    for r in score:
        sc = round(r["score"])
        col = _score_color(sc)
        out.append(
            f'<tr><td>{_esc(r["client"])}</td>'
            f'<td><div class="bar-wrap"><div class="bar-track">'
            f'<div class="bar-fill" style="width:{min(100, sc)}%;background:{col}"></div></div>'
            f'<span style="color:{col};font-weight:600">{sc}</span></div></td>'
            f'<td style="text-align:center">{round(r["approval_rate_first_rev"])}%</td>'
            f'<td style="text-align:center">{r["avg_response_days"]}</td>'
            f'<td style="text-align:center">{r["critical_docs_count"]}</td>'
            f'<td style="text-align:center">{r["total_docs"]}</td></tr>'
        )
    return "".join(out)


def render_executive_html(data: dict) -> str:
    meta = data["meta"]
    chartjs = _chartjs_source()
    chart_tag = (f"<script>{chartjs}</script>" if chartjs else
                 '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>')
    payload = json.dumps({"estado": data["estado"], "clientes": data["clientes"],
                          "accent": ACCENT}, ensure_ascii=False)
    kpis_html = "".join(_exec_kpi_html(k) for k in data["kpis"])

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(meta['title'])} · {_esc(meta['period_label'])}</title>
<style>
  :root {{ --accent:{ACCENT}; --ink:#0F172A; --sub:#475569; --muted:#94A3B8;
           --line:#E2E8F0; --card:#FFFFFF; --bg:#EEF1F8; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
          font-family:'Segoe UI',system-ui,-apple-system,Roboto,Arial,sans-serif; line-height:1.5; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:32px 20px 56px; }}
  header {{ display:flex; align-items:center; justify-content:space-between; gap:16px;
            flex-wrap:wrap; border-bottom:2px solid var(--accent); padding-bottom:18px; }}
  .brand {{ display:flex; align-items:center; gap:14px; }}
  .logo {{ width:44px; height:44px; border-radius:10px; background:var(--accent);
           display:flex; align-items:center; justify-content:center; color:#fff;
           font-size:22px; font-weight:700; }}
  h1 {{ font-size:21px; margin:0; letter-spacing:-.01em; }}
  .sub {{ color:var(--sub); font-size:13px; margin:3px 0 0; }}
  .badge {{ background:var(--accent); color:#fff; font-size:13px; font-weight:600;
            padding:7px 16px; border-radius:8px; white-space:nowrap; }}
  .narr {{ background:#F5F3FF; border-left:4px solid var(--accent); border-radius:0 10px 10px 0;
           padding:16px 20px; margin:22px 0; font-size:14.5px; color:#1e293b; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--accent);
        margin:30px 0 12px; font-weight:700; }}
  .kpis {{ display:grid; grid-template-columns:repeat(6,1fr); gap:12px; }}
  .kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; }}
  .kpi-label {{ margin:0; font-size:11px; color:var(--sub); }}
  .kpi-value {{ margin:5px 0 2px; font-size:25px; font-weight:700; line-height:1; }}
  .kpi-sub {{ margin:0; font-size:11px; color:var(--muted); }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px 20px; }}
  .card h3 {{ margin:0 0 14px; font-size:14px; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:14px; margin-bottom:10px; font-size:12px; color:var(--sub); }}
  .legend i {{ width:10px; height:10px; border-radius:2px; display:inline-block; margin-right:5px; vertical-align:middle; }}
  .chart-box {{ position:relative; height:240px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
  th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.04em;
        color:var(--muted); font-weight:600; padding:8px 10px; border-bottom:1px solid var(--line); }}
  td {{ padding:8px 10px; border-top:1px solid var(--line); }}
  td.mono {{ font-family:'Consolas',monospace; white-space:nowrap; }}
  .empty {{ text-align:center; color:var(--muted); padding:18px; }}
  .bar-wrap {{ display:flex; align-items:center; gap:9px; }}
  .bar-track {{ flex:1; height:6px; border-radius:3px; background:#EEF1F8; overflow:hidden; max-width:120px; }}
  .bar-fill {{ height:6px; border-radius:3px; }}
  footer {{ margin-top:34px; padding-top:16px; border-top:1px solid var(--line);
            display:flex; justify-content:space-between; color:var(--muted); font-size:12px; }}
  footer a {{ color:var(--accent); text-decoration:none; }}
  @media (max-width:720px) {{ .kpis {{ grid-template-columns:repeat(3,1fr); }} .grid2 {{ grid-template-columns:1fr; }} }}
  @media print {{ body {{ background:#fff; }} .wrap {{ max-width:none; }}
    .card,.kpi {{ break-inside:avoid; }} h2 {{ break-after:avoid; }} }}
{_TABLE_CSS}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="logo">◆</div>
      <div>
        <h1>{_esc(meta['title'])}</h1>
        <p class="sub">{_esc(meta['period_label'])} · generado {_esc(meta['generated'])}</p>
      </div>
    </div>
    <span class="badge">Ejecutivo</span>
  </header>

  <div class="narr">{_esc(data['narrative'])}</div>

  <h2>Indicadores clave</h2>
  <div class="kpis">{kpis_html}</div>

  <h2>Distribución y clientes</h2>
  <div class="grid2">
    <div class="card">
      <h3>Distribución por estado</h3>
      <div class="legend">
        <span><i style="background:{GREEN}"></i>Aprobado</span>
        <span><i style="background:{BLUE}"></i>Enviado</span>
        <span><i style="background:{AMBER}"></i>Devoluciones</span>
        <span><i style="background:{SLATE}"></i>Sin enviar</span>
      </div>
      <div class="chart-box"><canvas id="estadoChart"></canvas></div>
    </div>
    <div class="card">
      <h3>Top clientes · días medios de respuesta</h3>
      <div class="chart-box"><canvas id="clientesChart"></canvas></div>
    </div>
  </div>

  <h2>Ranking de equipo</h2>
  <div class="tbl-panel card" style="padding:14px 16px">
    <div class="tbl-tools">
      <input class="tbl-search" type="text" placeholder="Buscar responsable…">
      <span class="tbl-count"></span>
      <span class="tbl-hint">· clic en una columna para ordenar</span>
    </div>
    <table>
      <thead><tr><th data-sort="num">#</th><th data-sort="text">Responsable</th>
        <th data-sort="num">Total</th><th data-sort="num">Aprob.</th>
        <th data-sort="num">% Compl.</th><th data-sort="num">Devol.</th>
        <th data-sort="num">Tasa Dev.</th><th data-sort="num">Críticos</th></tr></thead>
      <tbody>{_exec_ranking_html(data['ranking'])}</tbody>
    </table>
  </div>

  <h2>Pedidos en riesgo de retraso</h2>
  <div class="tbl-panel card" style="padding:14px 16px">
    <div class="tbl-tools">
      <input class="tbl-search" type="text" placeholder="Buscar pedido…">
      <span class="tbl-count"></span>
      <span class="tbl-hint">· clic en una columna para ordenar</span>
    </div>
    <table>
      <thead><tr><th data-sort="text">Pedido</th><th data-sort="num">% Real</th>
        <th data-sort="num">% Esper.</th><th data-sort="num">Desv.</th>
        <th data-sort="text">Aprob/Total</th><th data-sort="text">Fecha prev.</th>
        <th data-sort="text">Pred. fin</th></tr></thead>
      <tbody>{_exec_pred_html(data['pred'])}</tbody>
    </table>
  </div>

  <h2>Scorecard de clientes</h2>
  <div class="tbl-panel card" style="padding:14px 16px">
    <div class="tbl-tools">
      <input class="tbl-search" type="text" placeholder="Buscar cliente…">
      <span class="tbl-count"></span>
      <span class="tbl-hint">· clic en una columna para ordenar</span>
    </div>
    <table>
      <thead><tr><th data-sort="text">Cliente</th><th data-sort="num">Score</th>
        <th data-sort="num">% Aprob. 1ªRev</th><th data-sort="num">Días resp.</th>
        <th data-sort="num">Crít. +30d</th><th data-sort="num">Total</th></tr></thead>
      <tbody>{_exec_scorecard_html(data['scorecard'])}</tbody>
    </table>
  </div>

  <footer>
    <span>DocFlow · Reporte ejecutivo</span>
    <span>© 2026 <a href="https://github.com/jparedesDS">{_esc(meta['prepared_by'])}</a></span>
  </footer>
</div>
{chart_tag}
<script>
(function() {{
  var D = {payload};
  if (typeof Chart === "undefined") return;
  Chart.defaults.font.family = "'Segoe UI',system-ui,sans-serif";
  Chart.defaults.color = "#64748B";
  var noLegend = {{ legend: {{ display: false }} }};
  new Chart(document.getElementById("estadoChart"), {{
    type: "doughnut",
    data: {{ labels: D.estado.labels, datasets: [{{ data: D.estado.values,
             backgroundColor: D.estado.colors, borderWidth: 0 }}] }},
    options: {{ responsive: true, maintainAspectRatio: false, cutout: "62%", plugins: noLegend }}
  }});
  new Chart(document.getElementById("clientesChart"), {{
    type: "bar",
    data: {{ labels: D.clientes.labels, datasets: [{{ data: D.clientes.values,
             backgroundColor: D.accent, borderRadius: 4 }}] }},
    options: {{ indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: noLegend,
               scales: {{ x: {{ beginAtZero: true, title: {{ display: true, text: "días" }} }} }} }}
  }});
}})();
</script>
<script>{_TABLE_JS}</script>
</body>
</html>"""


def generate_executive(ref_date: datetime | None = None, with_ai: bool = True):
    """Genera el reporte ejecutivo HTML y lo guarda. Devuelve (Path, data)."""
    data = build_executive_report_data(ref_date, with_ai=with_ai)
    html_str = render_executive_html(data)
    path = reports_dir() / f"Reporte_Ejecutivo_{data['meta']['key']}.html"
    path.write_text(html_str, encoding="utf-8")
    logger.info("Reporte ejecutivo generado: %s", path)
    return path, data


def _executive_email_body(data: dict) -> str:
    meta = data["meta"]
    return (
        '<div style="font-family:Segoe UI,Arial,sans-serif;color:#0F172A;font-size:14px;line-height:1.6">'
        f'<p>Hola,</p>'
        f'<p>Adjunto el <b>{_esc(meta["title"])}</b> de <b>{_esc(meta["period_label"])}</b>: '
        f'KPIs globales, distribución por estado, ranking del equipo, pedidos en riesgo y '
        f'scorecard de clientes. Ábrelo en el navegador para ver los gráficos interactivos.</p>'
        '<p style="color:#475569">Generado automáticamente por DocFlow.</p>'
        '<p style="color:#94A3B8;font-size:12px">© jparedesDS</p>'
        '</div>'
    )


def send_executive_html_email(to: list[str] | None = None, cc: list[str] | None = None,
                              ref_date: datetime | None = None) -> dict:
    if not to:
        return {"status": "skipped", "reason": "Sin destinatarios"}
    from core.services.smtp import send_html_email

    data = build_executive_report_data(ref_date)
    html_str = render_executive_html(data)
    fname = f"Reporte_Ejecutivo_{data['meta']['key']}.html"
    subject = f"{data['meta']['title']} — {data['meta']['period_label']}"
    result = send_html_email(
        to=to, cc=cc or [], subject=subject, html_body=_executive_email_body(data),
        attachment_eml=html_str.encode("utf-8"), attachment_name=fname)
    try:
        (reports_dir() / fname).write_text(html_str, encoding="utf-8")
    except Exception:
        logger.debug("No se pudo guardar copia local del reporte ejecutivo", exc_info=True)
    result["status"] = "sent"
    result["recipients"] = to
    return result


# ════════════════════════════════════════════════════════════════════════════
#  Informe por pedido
# ════════════════════════════════════════════════════════════════════════════

_ESTADO_CHIP = {
    "aprobado": ("Aprobado", GREEN),
    "rechazado": ("Rechazado", RED),
    "com. menores": ("Com. menores", AMBER),
    "com. mayores": ("Com. mayores", AMBER),
    "comentado": ("Comentado", AMBER),
    "enviado": ("Enviado", BLUE),
}


def _estado_label_color(estado: str) -> tuple[str, str]:
    e = (estado or "").lower().strip()
    if not e or e == "sin enviar":
        return ("Sin enviar", SLATE)
    for k, (lbl, col) in _ESTADO_CHIP.items():
        if k in e:
            return (lbl, col)
    return (str(estado).strip().title(), SLATE)


def list_pedidos() -> list[dict]:
    """[{pedido, cliente, total}, …] para poblar selectores (orden pedido desc)."""
    rows = monitoring_service.get_status_global()
    out = [{"pedido": r["pedido"], "cliente": r["cliente"], "total": r["total"]} for r in rows]
    out.sort(key=lambda r: r["pedido"], reverse=True)
    return out


def _pedido_prediction(base: str) -> dict | None:
    try:
        from core.services import erp
        for x in erp.get_seguimiento():
            if monitoring_service._normalize_pedido(str(x.get("pedido", ""))) == base:
                return x
    except Exception:
        logger.debug("Predicción de pedido no disponible", exc_info=True)
    return None


def build_pedido_report_data(pedido: str, with_ai: bool = True) -> dict:
    base = monitoring_service._normalize_pedido(pedido)
    all_docs = monitoring_service.get_monitoring_data()
    docs = [d for d in all_docs
            if monitoring_service._normalize_pedido(str(d.get("Nº Pedido", ""))) == base]

    first = docs[0] if docs else {}
    info = {
        "cliente": str(first.get("Cliente", "") or ""),
        "po": str(first.get("Nº PO", "") or ""),
        "oferta": str(first.get("Nº Oferta", "") or ""),
        "material": str(first.get("Material", "") or ""),
        "comercial": str(first.get("Responsable", "") or ""),
        "fecha_pedido": monitoring_service.fmt_date_ddmmyyyy(first.get("Fecha Pedido")),
        "fecha_prevista": monitoring_service.fmt_date_ddmmyyyy(first.get("Fecha Prevista")),
    }

    ap = en = dev = sin = crit = 0
    dias_max = 0
    tipo_counter: Counter = Counter()
    table = []
    for d in docs:
        est = str(d.get("Estado", "") or "").lower().strip()
        if "aprobado" in est:
            ap += 1
            ekey = "aprobado"
        elif est == "enviado":
            en += 1
            ekey = "enviado"
        elif any(s in est for s in ("rechazado", "com.", "comentado", "devuel")):
            dev += 1
            ekey = "devuelto"
        else:
            sin += 1
            ekey = "sin"
        if _es_critico(d) and "aprobado" not in est:
            crit += 1
        de = _num(d.get("Días Envío"))
        if de and de > dias_max:
            dias_max = de
        tipo_counter[str(d.get("Tipo Doc.", "") or "—").strip() or "—"] += 1
        dd = _num(d.get("Días Devolución"))
        lbl, col = _estado_label_color(d.get("Estado", ""))
        ms = monitoring_service.revision_milestones(d)
        table.append({
            "doc": str(d.get("Nº Doc. EIPSA", "") or ""),
            "titulo": str(d.get("Título", "") or ""),
            "tipo": str(d.get("Tipo Doc.", "") or ""),
            "rev": str(d.get("Nº Revisión", "") or ""),
            "estado_label": lbl, "estado_color": col, "estado_key": ekey,
            "fecha": monitoring_service.fmt_date_ddmmyyyy(d.get("Fecha Env. Doc.")),
            "first_send": monitoring_service.fmt_date_ddmmyyyy(ms["first_send"]),
            "first_appr": monitoring_service.fmt_date_ddmmyyyy(ms["first_approval"]),
            "dias": int(dd) if (dd and dd > 0) else 0,
            "dias_envio": int(de) if de else None,
            "info": str(d.get("Info/Review", "") or ""),
            "historial": str(d.get("Historial Rev.", "") or ""),
            "critico": _es_critico(d),
        })
    table.sort(key=lambda r: r["doc"])

    total = len(docs)
    pct = round(ap / total * 100) if total else 0
    tipo_top = tipo_counter.most_common(8)

    data = {
        "meta": {
            "title": f"Informe del pedido {base}",
            "pedido": base,
            "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "prepared_by": "jparedesDS",
            "key": base.replace("/", "-").replace(" ", ""),
        },
        "info": info,
        "kpis": {"total": total, "aprobados": ap, "pct": pct, "enviados": en,
                 "devoluciones": dev, "sin_enviar": sin, "criticos": crit, "dias_max": dias_max},
        "estado": {"labels": ["Aprobado", "Enviado", "Devuelto", "Sin enviar"],
                   "values": [ap, en, dev, sin], "colors": [GREEN, BLUE, AMBER, SLATE]},
        "tipo": {"labels": [t for t, _ in tipo_top], "values": [v for _, v in tipo_top]},
        "prediction": _pedido_prediction(base),
        "table": table,
    }
    data["narrative"] = _pedido_narrative(data, with_ai=with_ai)
    return data


def _pedido_fallback(d: dict) -> str:
    k, info = d["kpis"], d["info"]
    pred = d["prediction"] or {}
    plazo = ""
    if pred.get("en_plazo") is True:
        plazo = " Según la curva-S, el pedido avanza en plazo."
    elif pred.get("en_plazo") is False:
        plazo = " Atención: la previsión indica riesgo de retraso respecto a la fecha prevista."
    cli = f" ({info['cliente']})" if info["cliente"] else ""
    return (
        f"El pedido {d['meta']['pedido']}{cli} reúne {k['total']} documentos, de los cuales "
        f"{k['aprobados']} están aprobados ({k['pct']}%). Quedan {k['enviados']} en revisión del "
        f"cliente, {k['devoluciones']} con comentarios y {k['sin_enviar']} sin enviar, con "
        f"{k['criticos']} crítico(s) pendiente(s).{plazo}"
    )


def _pedido_ai_prompt(d: dict) -> str:
    k, info = d["kpis"], d["info"]
    pred = d["prediction"] or {}
    return f"""Eres un asistente de Document Control. Redacta un PÁRRAFO EJECUTIVO BREVE
(2-3 frases, español, profesional) sobre el estado del pedido {d['meta']['pedido']}
(cliente {info['cliente'] or 'n/d'}) con estos datos:
- Documentos totales: {k['total']}
- Aprobados: {k['aprobados']} ({k['pct']}%)
- Enviados (en revisión del cliente): {k['enviados']}
- Con devoluciones/comentarios: {k['devoluciones']}
- Sin enviar: {k['sin_enviar']}
- Críticos pendientes: {k['criticos']}
- Avance esperado (curva-S): {pred.get('pct_esperado')}% · ¿en plazo?: {pred.get('en_plazo')} · fecha prevista: {pred.get('fecha_prevista')}

Menciona el avance global, el riesgo principal y una acción recomendada. Sin HTML ni markdown."""


def _pedido_narrative(d: dict, with_ai: bool = True) -> str:
    if with_ai:
        txt = _ask_haiku(_pedido_ai_prompt(d))
        if txt:
            return txt
    return _pedido_fallback(d)


def _pedido_table_html(rows: list[dict]) -> str:
    if not rows:
        return ('<tr><td colspan="9" class="empty">Este pedido no tiene documentos '
                'registrados.</td></tr>')
    out = []
    for r in rows:
        dias = r["dias"]
        dcol = RED if dias > 15 else (AMBER if dias > 7 else SLATE)
        crit = ' <span class="crit">crítico</span>' if r["critico"] else ""
        out.append(
            f'<tr class="expandable" data-estado="{r.get("estado_key", "")}">'
            f'<td class="mono">{_esc(r["doc"])}</td>'
            f'<td class="muted">{_esc(r["titulo"][:52])}{crit}</td>'
            f'<td>{_esc(r["tipo"])}</td>'
            f'<td style="text-align:center">{_esc(r["rev"])}</td>'
            f'<td><span class="chip" style="background:{r["estado_color"]}">{_esc(r["estado_label"])}</span></td>'
            f'<td>{_esc(r["fecha"]) or "—"}</td>'
            f'<td>{_esc(r["first_send"]) or "—"}</td>'
            f'<td>{_esc(r["first_appr"]) or "—"}</td>'
            f'<td style="text-align:center;color:{dcol};font-weight:600">{dias or "—"}</td></tr>'
            f'<tr class="detail" hidden><td colspan="9">{_pedido_detail_html(r)}</td></tr>'
        )
    return "".join(out)


def _pedido_detail_html(r: dict) -> str:
    de = r.get("dias_envio")
    items = [
        ("Título completo", r.get("titulo") or "—"),
        ("Info / Review", r.get("info") or "—"),
        ("Días desde envío", de if de not in ("", None) else "—"),
        ("Crítico", "Sí" if r.get("critico") else "No"),
    ]
    grid = "".join(
        f'<div><p class="lab">{_esc(lab)}</p><p class="val">{_esc(val)}</p></div>'
        for lab, val in items)
    hist = (r.get("historial") or "").strip()
    hist_html = (
        f'<div style="margin-top:10px"><p class="lab">Historial de revisiones</p>'
        f'<p class="detail-hist">{_esc(hist)}</p></div>'
        if hist else "")
    return f'<div class="detail-grid">{grid}</div>{hist_html}'


def _pedido_prediction_html(pred: dict | None) -> str:
    if not pred or pred.get("pct_esperado") is None:
        return ""
    real = pred.get("pct", 0)
    esp = pred.get("pct_esperado", 0)
    en_plazo = pred.get("en_plazo")
    if en_plazo is True:
        badge = f'<span class="chip" style="background:{GREEN}">En plazo</span>'
    elif en_plazo is False:
        badge = f'<span class="chip" style="background:{RED}">En riesgo</span>'
    else:
        badge = ""
    return (
        '<div class="card" style="margin-top:16px"><h3>Predicción · curva-S</h3>'
        '<div class="info-grid">'
        f'<div><p class="lab">Avance real</p><p class="val">{real}%</p></div>'
        f'<div><p class="lab">Avance esperado</p><p class="val">{esp}%</p></div>'
        f'<div><p class="lab">Fecha prevista</p><p class="val">{_esc(pred.get("fecha_prevista") or "—")}</p></div>'
        f'<div><p class="lab">Predicción fin</p><p class="val">{_esc(pred.get("prediccion_fecha") or "—")}</p></div>'
        f'<div><p class="lab">Situación</p><p class="val">{badge or "—"}</p></div>'
        '</div></div>'
    )


def render_pedido_html(data: dict) -> str:
    meta, info, k = data["meta"], data["info"], data["kpis"]
    chartjs = _chartjs_source()
    chart_tag = (f"<script>{chartjs}</script>" if chartjs else
                 '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>')
    payload = json.dumps({"estado": data["estado"], "tipo": data["tipo"], "accent": ACCENT},
                         ensure_ascii=False)
    pred_html = _pedido_prediction_html(data["prediction"])
    table_html = _pedido_table_html(data["table"])

    def field(lab, val):
        return f'<div><p class="lab">{lab}</p><p class="val">{_esc(val or "—")}</p></div>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(meta['title'])}</title>
<style>
  :root {{ --accent:{ACCENT}; --ink:#0F172A; --sub:#475569; --muted:#94A3B8;
           --line:#E2E8F0; --card:#FFFFFF; --bg:#EEF1F8; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
          font-family:'Segoe UI',system-ui,-apple-system,Roboto,Arial,sans-serif; line-height:1.5; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:32px 20px 56px; }}
  header {{ display:flex; align-items:center; justify-content:space-between; gap:16px;
            flex-wrap:wrap; border-bottom:2px solid var(--accent); padding-bottom:18px; }}
  .brand {{ display:flex; align-items:center; gap:14px; }}
  .logo {{ width:44px; height:44px; border-radius:10px; background:var(--accent);
           display:flex; align-items:center; justify-content:center; color:#fff;
           font-size:22px; font-weight:700; }}
  h1 {{ font-size:21px; margin:0; letter-spacing:-.01em; }}
  .sub {{ color:var(--sub); font-size:13px; margin:3px 0 0; }}
  .badge {{ background:var(--accent); color:#fff; font-size:13px; font-weight:600;
            padding:7px 16px; border-radius:8px; white-space:nowrap; }}
  .narr {{ background:#F5F3FF; border-left:4px solid var(--accent); border-radius:0 10px 10px 0;
           padding:16px 20px; margin:22px 0; font-size:14.5px; color:#1e293b; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--accent);
        margin:30px 0 12px; font-weight:700; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px 20px; }}
  .card h3 {{ margin:0 0 14px; font-size:14px; }}
  .info-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px 24px; }}
  .info-grid .lab {{ margin:0; font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }}
  .info-grid .val {{ margin:3px 0 0; font-size:14px; font-weight:600; }}
  .kpis {{ display:grid; grid-template-columns:repeat(6,1fr); gap:12px; }}
  .kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; }}
  .kpi-label {{ margin:0; font-size:11px; color:var(--sub); }}
  .kpi-value {{ margin:5px 0 0; font-size:26px; font-weight:700; line-height:1; }}
  .prog {{ margin:14px 0 0; }}
  .prog-track {{ height:10px; border-radius:5px; background:var(--line); overflow:hidden; }}
  .prog-fill {{ height:10px; border-radius:5px; background:{GREEN}; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:14px; margin-bottom:10px; font-size:12px; color:var(--sub); }}
  .legend i {{ width:10px; height:10px; border-radius:2px; display:inline-block; margin-right:5px; vertical-align:middle; }}
  .chart-box {{ position:relative; height:230px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
  th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.04em;
        color:var(--muted); font-weight:600; padding:8px 10px; border-bottom:1px solid var(--line); }}
  td {{ padding:8px 10px; border-top:1px solid var(--line); }}
  td.mono {{ font-family:'Consolas',monospace; white-space:nowrap; }}
  td.muted {{ color:var(--sub); }}
  .chip {{ display:inline-block; padding:2px 9px; border-radius:6px; font-size:11px; font-weight:600; color:#fff; }}
  .crit {{ color:{RED}; font-size:11px; font-weight:600; }}
  .empty {{ text-align:center; color:var(--muted); padding:18px; }}
  footer {{ margin-top:34px; padding-top:16px; border-top:1px solid var(--line);
            display:flex; justify-content:space-between; color:var(--muted); font-size:12px; }}
  footer a {{ color:var(--accent); text-decoration:none; }}
  @media (max-width:720px) {{ .kpis {{ grid-template-columns:repeat(3,1fr); }} .grid2 {{ grid-template-columns:1fr; }} }}
  @media print {{ body {{ background:#fff; }} .wrap {{ max-width:none; }}
    .card,.kpi {{ break-inside:avoid; }} h2 {{ break-after:avoid; }}
    .pagebreak {{ break-before:page; }} }}
{_TABLE_CSS}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="logo">◆</div>
      <div>
        <h1>{_esc(meta['title'])}</h1>
        <p class="sub">{_esc(info['cliente'] or 'Cliente n/d')} · generado {_esc(meta['generated'])}</p>
      </div>
    </div>
    <span class="badge">Pedido</span>
  </header>

  <div class="narr">{_esc(data['narrative'])}</div>

  <h2>Ficha del pedido</h2>
  <div class="card">
    <div class="info-grid">
      {field("Cliente", info['cliente'])}
      {field("Nº PO", info['po'])}
      {field("Nº Oferta", info['oferta'])}
      {field("Material", info['material'])}
      {field("Comercial", info['comercial'])}
      {field("Fecha pedido", info['fecha_pedido'])}
      {field("Fecha prevista", info['fecha_prevista'])}
    </div>
  </div>

  <h2>Estado del pedido</h2>
  <div class="kpis">
    <div class="kpi"><p class="kpi-label">Documentos</p><p class="kpi-value">{k['total']}</p></div>
    <div class="kpi"><p class="kpi-label">Aprobado</p><p class="kpi-value" style="color:{GREEN}">{k['pct']}%</p></div>
    <div class="kpi"><p class="kpi-label">Enviados</p><p class="kpi-value" style="color:{BLUE}">{k['enviados']}</p></div>
    <div class="kpi"><p class="kpi-label">Devoluciones</p><p class="kpi-value" style="color:{AMBER}">{k['devoluciones']}</p></div>
    <div class="kpi"><p class="kpi-label">Sin enviar</p><p class="kpi-value" style="color:{SLATE}">{k['sin_enviar']}</p></div>
    <div class="kpi"><p class="kpi-label">Críticos</p><p class="kpi-value" style="color:{RED if k['criticos'] else GREEN}">{k['criticos']}</p></div>
  </div>
  <div class="prog"><div class="prog-track"><div class="prog-fill" style="width:{k['pct']}%"></div></div></div>

  <div class="grid2" style="margin-top:18px">
    <div class="card">
      <h3>Distribución por estado</h3>
      <div class="legend">
        <span><i style="background:{GREEN}"></i>Aprobado</span>
        <span><i style="background:{BLUE}"></i>Enviado</span>
        <span><i style="background:{AMBER}"></i>Devuelto</span>
        <span><i style="background:{SLATE}"></i>Sin enviar</span>
      </div>
      <div class="chart-box"><canvas id="estadoChart"></canvas></div>
    </div>
    <div class="card">
      <h3>Por tipo de documento</h3>
      <div class="chart-box"><canvas id="tipoChart"></canvas></div>
    </div>
  </div>
  {pred_html}

  <div class="pagebreak"></div>
  <h2>Estado de toda la documentación · {k['total']} documentos</h2>
  <div class="tbl-panel card" style="padding:14px 16px">
    <div class="tbl-tools">
      <input class="tbl-search" type="text" placeholder="Buscar Nº doc, título o tipo…">
      <select class="tbl-status">
        <option value="all">Todos los estados</option>
        <option value="aprobado">Aprobado</option>
        <option value="enviado">Enviado</option>
        <option value="devuelto">Devuelto</option>
        <option value="sin">Sin enviar</option>
      </select>
      <span class="tbl-count"></span>
      <span class="tbl-hint">· clic en una fila para ver el detalle</span>
    </div>
    <table>
      <thead><tr><th>Nº Doc. EIPSA</th><th>Título</th><th>Tipo</th><th>Rev.</th>
        <th>Estado</th><th>Fecha env.</th><th>1ª Env. (Rev.0)</th><th>1ª Aprob.</th><th>Días</th></tr></thead>
      <tbody>{table_html}</tbody>
    </table>
  </div>

  <footer>
    <span>DocFlow · Informe de pedido {_esc(meta['pedido'])}</span>
    <span>© 2026 <a href="https://github.com/jparedesDS">{_esc(meta['prepared_by'])}</a></span>
  </footer>
</div>
{chart_tag}
<script>
(function() {{
  var D = {payload};
  if (typeof Chart === "undefined") return;
  Chart.defaults.font.family = "'Segoe UI',system-ui,sans-serif";
  Chart.defaults.color = "#64748B";
  var noLegend = {{ legend: {{ display: false }} }};
  new Chart(document.getElementById("estadoChart"), {{
    type: "doughnut",
    data: {{ labels: D.estado.labels, datasets: [{{ data: D.estado.values,
             backgroundColor: D.estado.colors, borderWidth: 0 }}] }},
    options: {{ responsive: true, maintainAspectRatio: false, cutout: "62%", plugins: noLegend }}
  }});
  new Chart(document.getElementById("tipoChart"), {{
    type: "bar",
    data: {{ labels: D.tipo.labels, datasets: [{{ data: D.tipo.values,
             backgroundColor: D.accent, borderRadius: 4 }}] }},
    options: {{ indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: noLegend,
               scales: {{ x: {{ beginAtZero: true, ticks: {{ precision: 0 }} }} }} }}
  }});
}})();
</script>
<script>{_TABLE_JS}</script>
</body>
</html>"""


def _pedido_email_body(data: dict) -> str:
    meta, info = data["meta"], data["info"]
    return (
        '<div style="font-family:Segoe UI,Arial,sans-serif;color:#0F172A;font-size:14px;line-height:1.6">'
        f'<p>Hola,</p>'
        f'<p>Adjunto el <b>{_esc(meta["title"])}</b>'
        + (f' (cliente <b>{_esc(info["cliente"])}</b>)' if info["cliente"] else '')
        + '. Ábrelo en el navegador para ver los KPIs, la predicción y la tabla completa '
        'de toda la documentación del pedido.</p>'
        '<p style="color:#475569">Generado automáticamente por DocFlow.</p>'
        '<p style="color:#94A3B8;font-size:12px">© jparedesDS</p>'
        '</div>'
    )


def generate_pedido(pedido: str, with_ai: bool = True):
    """Genera el informe HTML de un pedido y lo guarda. Devuelve (Path, data)."""
    data = build_pedido_report_data(pedido, with_ai=with_ai)
    html_str = render_pedido_html(data)
    path = reports_dir() / f"Informe_Pedido_{data['meta']['key']}.html"
    path.write_text(html_str, encoding="utf-8")
    logger.info("Informe de pedido generado: %s", path)
    return path, data


def send_pedido_email(pedido: str, to: list[str] | None = None,
                      cc: list[str] | None = None) -> dict:
    if not to:
        return {"status": "skipped", "reason": "Sin destinatarios"}
    from core.services.smtp import send_html_email

    data = build_pedido_report_data(pedido)
    html_str = render_pedido_html(data)
    fname = f"Informe_Pedido_{data['meta']['key']}.html"
    subject = f"{data['meta']['title']}" + (f" — {data['info']['cliente']}" if data['info']['cliente'] else "")
    result = send_html_email(
        to=to, cc=cc or [], subject=subject, html_body=_pedido_email_body(data),
        attachment_eml=html_str.encode("utf-8"), attachment_name=fname)
    try:
        (reports_dir() / fname).write_text(html_str, encoding="utf-8")
    except Exception:
        logger.debug("No se pudo guardar copia local del informe de pedido", exc_info=True)
    result["status"] = "sent"
    result["recipients"] = to
    return result
