"""Analytics LITE — métricas de la sección Informes.

Port de analytics_service + supplier_scorecard_service del DocFlow grande, sin
DB ni Pydantic. Todo se calcula sobre monitoring.get_monitoring_data() con
parseo numérico tolerante (en lite los "Días*" pueden venir como int o "").

Expone:
  • get_summary()        → KPIs globales + por_cliente + por_tipo_doc + heatmap
  • get_ranking()        → rendimiento por responsable (doc)
  • get_team_workload()  → carga de trabajo + detección de sobrecarga
  • get_scorecard()      → scorecard de clientes (score 0-100)
  • get_predicciones()   → curva-S / predicción por pedido (reusa erp)
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, datetime

from core.services import monitoring

ESTADOS_APROBADOS = ("aprobado",)
ESTADOS_DEVOLUCION = ("com. menores", "com. mayores", "rechazado", "comentado")
ESTADOS_ENVIADOS = ("enviado",)


def _num(v):
    """float tolerante; None si no es numérico."""
    if v is None or v == "" or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    try:
        return float(str(v).strip().replace("%", "").replace(",", "."))
    except (ValueError, TypeError):
        return None


def _estado(d) -> str:
    return str(d.get("Estado", "") or "").lower().strip()


def _es_critico(d) -> bool:
    return str(d.get("Crítico", "") or "").lower().strip() in ("sí", "si")


def norm_cliente(valor) -> str:
    """Nombre de cliente comparable, para no contar el mismo dos veces.

    El ERP tiene «QATAR» y «Qatar», o «ARAMCO - RIYAS» y «ARAMCO / RIYAS», que
    son el mismo cliente escrito de dos formas y salían como dos filas. Se pasa
    a mayúsculas y se unifica el separador. No se toca nada más: «ARAMCO» a
    secas se queda aparte de «ARAMCO - RIYAS», que puede ser otro proyecto.
    """
    txt = re.sub(r"\s+", " ", str(valor or "").strip())
    if not txt:
        return "Sin Cliente"
    txt = re.sub(r"\s*[/\\-]\s*", " - ", txt)
    return txt.upper()


# ════════════════════════════════════════════════════════════════════════════
# Resumen
# ════════════════════════════════════════════════════════════════════════════

def get_summary() -> dict:
    docs = monitoring.get_monitoring_data()
    if not docs:
        return {
            "velocidad_media_dias": 0, "clientes_ok": 0, "total_clientes": 0,
            "docs_riesgo": 0, "a_vencer_3d": 0,
            "total_aprobados": 0, "total_enviados": 0,
            "total_devoluciones": 0, "total_sin_enviar": 0,
            "por_cliente": [], "por_tipo_doc": [], "heatmap_cliente": [],
        }

    total_aprobados = total_enviados = total_devoluciones = total_sin_enviar = 0
    docs_riesgo = a_vencer_3d = 0
    dias_vals: list[float] = []

    for d in docs:
        est = _estado(d)
        dd = _num(d.get("Días Devolución"))
        if "aprobado" in est:
            total_aprobados += 1
        elif est in ESTADOS_ENVIADOS:
            total_enviados += 1
        elif any(s in est for s in ESTADOS_DEVOLUCION):
            total_devoluciones += 1
        else:
            total_sin_enviar += 1

        if dd is not None and dd > 0:
            dias_vals.append(dd)
            if dd > 15 and "aprobado" not in est and _es_critico(d):
                docs_riesgo += 1
            if 0 < dd <= 3 and "aprobado" not in est:
                a_vencer_3d += 1

    velocidad = round(sum(dias_vals) / len(dias_vals), 1) if dias_vals else 0
    por_cliente = _por_cliente(docs)
    clientes_ok = sum(1 for c in por_cliente if c["pct"] >= 75)

    return {
        "velocidad_media_dias": velocidad,
        "clientes_ok": clientes_ok,
        "total_clientes": len(por_cliente),
        "docs_riesgo": docs_riesgo,
        "a_vencer_3d": a_vencer_3d,
        "total_aprobados": total_aprobados,
        "total_enviados": total_enviados,
        "total_devoluciones": total_devoluciones,
        "total_sin_enviar": total_sin_enviar,
        "por_cliente": por_cliente,
        "por_tipo_doc": _por_tipo_doc(docs),
        "heatmap_cliente": _heatmap(docs),
    }


def _por_cliente(docs) -> list[dict]:
    grupos = defaultdict(lambda: {"total": 0, "aprobados": 0, "enviados": 0, "dias": []})
    for d in docs:
        cliente = norm_cliente(d.get("Cliente"))
        est = _estado(d)
        dd = _num(d.get("Días Devolución"))
        g = grupos[cliente]
        g["total"] += 1
        if "aprobado" in est:
            g["aprobados"] += 1
        if dd is not None and dd > 0:
            g["dias"].append(dd)
        if est in ESTADOS_ENVIADOS or any(s in est for s in ESTADOS_DEVOLUCION):
            g["enviados"] += 1
    out = []
    for cliente, g in grupos.items():
        if g["enviados"] == 0 and g["aprobados"] == 0:
            continue
        pct = round(g["aprobados"] / g["total"] * 100) if g["total"] else 0
        media = round(sum(g["dias"]) / len(g["dias"]), 1) if g["dias"] else 0
        out.append({"cliente": cliente, "media_dias": media, "total": g["total"],
                    "aprobados": g["aprobados"], "pct": pct})
    out.sort(key=lambda x: x["media_dias"], reverse=True)
    return out


def _por_tipo_doc(docs) -> list[dict]:
    grupos = defaultdict(lambda: {"aprobado": 0, "enviado": 0, "com_menores": 0,
                                  "rechazado": 0, "sin_enviar": 0, "total": 0})
    for d in docs:
        tipo = str(d.get("Tipo Doc.", "") or "").strip() or "Sin Tipo"
        est = _estado(d)
        g = grupos[tipo]
        g["total"] += 1
        if "aprobado" in est:
            g["aprobado"] += 1
        elif est == "enviado":
            g["enviado"] += 1
        elif any(x in est for x in ("com. menores", "com. mayores", "comentado")):
            g["com_menores"] += 1
        elif "rechazado" in est:
            g["rechazado"] += 1
        else:
            g["sin_enviar"] += 1
    out = [{"tipo": t, **g} for t, g in grupos.items()]
    out.sort(key=lambda x: x["total"], reverse=True)
    return out


def _heatmap(docs) -> list[dict]:
    grupos = defaultdict(lambda: {"aprobado": 0, "enviado": 0, "com_menores": 0,
                                  "rechazado": 0, "sin_enviar": 0, "total": 0})
    for d in docs:
        cliente = norm_cliente(d.get("Cliente"))
        est = _estado(d)
        g = grupos[cliente]
        g["total"] += 1
        if "aprobado" in est:
            g["aprobado"] += 1
        elif est == "enviado":
            g["enviado"] += 1
        elif any(x in est for x in ("com. menores", "com. mayores", "comentado")):
            g["com_menores"] += 1
        elif "rechazado" in est:
            g["rechazado"] += 1
        else:
            g["sin_enviar"] += 1
    out = [{"cliente": c, **g} for c, g in grupos.items() if g["total"] > 0]
    out.sort(key=lambda x: x["total"], reverse=True)
    return out


# ════════════════════════════════════════════════════════════════════════════
# Equipo — rendimiento + carga
# ════════════════════════════════════════════════════════════════════════════

_OCULTAR_DOC = {"SI", "ES", "Sin Asignar"}


def get_ranking() -> list[dict]:
    """Rendimiento por responsable de documento (columna 'Repsonsable')."""
    docs = monitoring.get_monitoring_data()
    grupos = defaultdict(lambda: {
        "total": 0, "aprobados": 0, "criticos": 0, "devoluciones": 0,
        "sin_enviar": 0, "dias_aprobados": [], "dias_envio": [],
    })
    for d in docs:
        resp = str(d.get("Repsonsable", "") or "").strip() or "Sin Asignar"
        if resp in _OCULTAR_DOC:
            continue
        est = _estado(d)
        g = grupos[resp]
        g["total"] += 1
        if "aprobado" in est:
            g["aprobados"] += 1
            dd = _num(d.get("Días Devolución"))
            if dd is not None and dd > 0:
                g["dias_aprobados"].append(dd)
        if any(s in est for s in ESTADOS_DEVOLUCION):
            g["devoluciones"] += 1
        if _es_critico(d) and "aprobado" not in est:
            g["criticos"] += 1
        if not est or not (("aprobado" in est) or (est in ESTADOS_ENVIADOS)
                           or any(s in est for s in ESTADOS_DEVOLUCION)):
            g["sin_enviar"] += 1
        de = _num(d.get("Días Envío"))
        if de is not None and de > 0:
            g["dias_envio"].append(de)

    out = []
    for resp, g in grupos.items():
        pct = round(g["aprobados"] / g["total"] * 100) if g["total"] else 0
        vel = round(sum(g["dias_aprobados"]) / len(g["dias_aprobados"]), 1) if g["dias_aprobados"] else 0
        tasa = round(g["devoluciones"] / g["total"] * 100) if g["total"] else 0
        out.append({
            "responsable": resp, "total": g["total"], "aprobados": g["aprobados"],
            "pct": pct, "criticos": g["criticos"], "devoluciones": g["devoluciones"],
            "sin_enviar": g["sin_enviar"], "velocidad_media": vel, "tasa_devolucion": tasa,
        })
    out.sort(key=lambda x: x["pct"], reverse=True)
    return out


def get_team_overview() -> list[dict]:
    """Estado de la documentación por persona + documentos pendientes de trabajar.

    Por cada responsable de documento ('Repsonsable'): KPIs (total, aprobados, %,
    críticos, devoluciones, sin enviar) y la lista de documentos que requieren
    acción (no aprobados ni meramente enviados), ordenados por urgencia.
    """
    docs = monitoring.get_monitoring_data()
    grupos: dict[str, list] = defaultdict(list)
    for d in docs:
        resp = str(d.get("Repsonsable", "") or "").strip() or "Sin Asignar"
        if resp in _OCULTAR_DOC:
            continue
        grupos[resp].append(d)

    from core.config import USERS
    out = []
    for resp, items in grupos.items():
        total = len(items)
        aprobados = sum(1 for d in items if "aprobado" in _estado(d))
        criticos = sum(1 for d in items if _es_critico(d) and "aprobado" not in _estado(d))
        devoluciones = sum(1 for d in items if any(s in _estado(d) for s in ESTADOS_DEVOLUCION))
        sin_enviar = sum(1 for d in items
                         if not _estado(d) or _estado(d) == "sin enviar")
        pct = round(aprobados / total * 100) if total else 0

        pending = []
        for d in items:
            est = _estado(d)
            if "aprobado" in est or est == "enviado":
                continue  # hecho o en manos del cliente
            dd = _num(d.get("Días Devolución"))
            de = _num(d.get("Días Envío"))
            dias = int(dd) if (dd and dd > 0) else (int(de) if (de and de > 0) else 0)
            pending.append({
                "doc_eipsa": str(d.get("Nº Doc. EIPSA", "") or ""),
                "titulo": str(d.get("Título", "") or ""),
                "estado": str(d.get("Estado", "") or "Sin enviar"),
                "cliente": str(d.get("Cliente", "") or ""),
                "dias": dias,
                "critico": _es_critico(d),
            })
        pending.sort(key=lambda x: x["dias"], reverse=True)

        nombre = USERS.get(resp, {}).get("nombre", resp)
        out.append({
            "iniciales": resp, "nombre": nombre,
            "total": total, "aprobados": aprobados, "pct": pct,
            "criticos": criticos, "devoluciones": devoluciones, "sin_enviar": sin_enviar,
            "pendientes": pending, "n_pendientes": len(pending),
        })
    out.sort(key=lambda x: (x["n_pendientes"], x["criticos"]), reverse=True)
    return out


def get_matriz_comercial() -> list[dict]:
    """Matriz comercial (Responsable pedido) × responsable doc (Repsonsable) con
    % de aprobación por par."""
    docs = monitoring.get_monitoring_data()
    grupos: dict[tuple, dict] = defaultdict(lambda: {"total": 0, "aprobados": 0})
    for d in docs:
        comercial = str(d.get("Responsable", "") or "").strip() or "Sin Asignar"
        resp_doc = str(d.get("Repsonsable", "") or "").strip() or "Sin Asignar"
        if resp_doc in _OCULTAR_DOC:
            continue
        key = (comercial, resp_doc)
        grupos[key]["total"] += 1
        if "aprobado" in _estado(d):
            grupos[key]["aprobados"] += 1
    out = []
    for (comercial, resp_doc), g in grupos.items():
        pct = round(g["aprobados"] / g["total"] * 100) if g["total"] else 0
        out.append({"comercial": comercial, "resp_doc": resp_doc,
                    "total": g["total"], "aprobados": g["aprobados"], "pct": pct})
    out.sort(key=lambda x: (x["comercial"], x["resp_doc"]))
    return out


def get_team_workload() -> dict:
    """Distribución de carga + detección de sobrecarga (>1σ sobre la media)."""
    por_resp = get_ranking()
    if not por_resp:
        return {"members": [], "avg_load": 0, "max_load": 0, "std_dev": 0, "alerts": []}
    totals = [r["total"] for r in por_resp]
    avg = sum(totals) / len(totals)
    mx = max(totals)
    std = (sum((t - avg) ** 2 for t in totals) / len(totals)) ** 0.5 if len(totals) > 1 else 0
    alerts = []
    for r in por_resp:
        r["overload"] = r["total"] > avg + std
        r["underload"] = (r["total"] < avg - std) if avg > std else False
        if r["overload"]:
            alerts.append({"responsable": r["responsable"], "total": r["total"], "avg": round(avg)})
    members = sorted(por_resp, key=lambda x: x["total"], reverse=True)
    return {"members": members, "avg_load": round(avg, 1), "max_load": mx,
            "std_dev": round(std, 1), "alerts": alerts}


# ════════════════════════════════════════════════════════════════════════════
# Scorecard de clientes
# ════════════════════════════════════════════════════════════════════════════

def get_scorecard() -> list[dict]:
    """Score 0-100 por cliente.

    Score = 40% tasa aprobación (1ª rev) + 30% inverso días respuesta
            + 30% inverso ratio crítico (>30 días envío).
    """
    docs = monitoring.get_monitoring_data()
    if not docs:
        return []
    grupos = defaultdict(list)
    for d in docs:
        cliente = norm_cliente(d.get("Cliente"))
        if cliente != "Sin Cliente":
            grupos[cliente].append(d)

    results = []
    for cliente, items in grupos.items():
        results.append({"client": cliente, **_score_metrics(items)})
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def _score_metrics(items: list[dict]) -> dict:
    total = len(items)

    # Días respuesta medios
    dvals = [n for n in (_num(d.get("Días Devolución")) for d in items) if n is not None]
    avg_resp = round(sum(dvals) / len(dvals), 1) if dvals else 0.0

    # Tasa aprobación 1ª revisión (rev <= 1)
    first = [d for d in items if (_num(d.get("Nº Revisión")) or 0) <= 1]
    approval_first = 0.0
    if first:
        ap = sum(1 for d in first if "aprobado" in _estado(d))
        approval_first = round(ap / len(first) * 100, 1)

    # Críticos > 30 días de envío
    crit = [d for d in items if _es_critico(d)]
    crit_over30 = 0
    crit_pct = 0.0
    if crit:
        crit_over30 = sum(1 for d in crit if (_num(d.get("Días Envío")) or 0) > 30)
        crit_pct = round(crit_over30 / len(crit) * 100, 1)

    approval_c = approval_first * 0.4
    if avg_resp <= 0:
        resp_c = 100.0
    elif avg_resp >= 60:
        resp_c = 0.0
    else:
        resp_c = max(0, (60 - avg_resp) / 60 * 100)
    resp_c *= 0.3
    crit_c = max(0, (100 - crit_pct)) * 0.3
    score = round(approval_c + resp_c + crit_c, 1)

    return {
        "total_docs": total, "avg_response_days": avg_resp,
        "approval_rate_first_rev": approval_first,
        "critical_docs_count": crit_over30, "critical_over_30d_pct": crit_pct,
        "score": score,
    }


# ════════════════════════════════════════════════════════════════════════════
# Predicción (reusa la lógica de erp)
# ════════════════════════════════════════════════════════════════════════════

def get_predicciones() -> list[dict]:
    from core.services import erp
    return erp.get_seguimiento()


# ════════════════════════════════════════════════════════════════════════════
# Historia de cada documento — la columna «Historial Rev.»
#
# El ERP guarda en un solo campo todo lo que le ha pasado a un documento, de lo
# más nuevo a lo más viejo y separado por «//»:
#
#   04/09/2026 Enviado Rev. 1 // 21/08/2026 Com. Menores Rev. 0 // 31/07/2026 Enviado Rev. 0
#
# Son 9.677 hechos con fecha (2023-2026) que hasta ahora no se usaban para nada:
# de ahí salen la actividad mes a mes, el tiempo real que tarda el cliente en
# contestar y cuántas vueltas da un documento hasta que se aprueba.
# ════════════════════════════════════════════════════════════════════════════

_HIST_RE = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})\s+(.+?)\s+Rev\.\s*([A-Za-z0-9]*)\s*$")

MESES_ES = ("ene", "feb", "mar", "abr", "may", "jun",
            "jul", "ago", "sep", "oct", "nov", "dic")

_RESOLUCIONES = ("aprobado", "com. menores", "com. mayores", "comentado", "rechazado")


def _bucket(estado: str) -> str:
    """Agrupa el estado de un hecho en enviado / aprobado / devuelto."""
    e = estado.lower().strip()
    if "aprobado" in e:
        return "aprobado"
    if e.startswith("enviado"):
        return "enviado"
    if any(r in e for r in _RESOLUCIONES):
        return "devuelto"
    return ""


def doc_events(docs: list[dict] | None = None) -> list[dict]:
    """Todos los hechos con fecha de todos los documentos, de viejo a nuevo."""
    docs = monitoring.get_monitoring_data() if docs is None else docs
    out = []
    for d in docs:
        hist = str(d.get("Historial Rev.", "") or "")
        if not hist.strip():
            continue
        for trozo in hist.split("//"):
            m = _HIST_RE.match(trozo)
            if not m:
                continue
            dd, mm, yyyy, estado, rev = m.groups()
            try:
                f = date(int(yyyy), int(mm), int(dd))
            except ValueError:
                continue
            if not (2015 <= f.year <= date.today().year + 1):
                continue          # fechas basura del ERP (algún 2000 suelto)
            out.append({
                "fecha": f,
                "estado": estado.strip(),
                "grupo": _bucket(estado),
                "rev": rev.strip().upper(),
                "doc": str(d.get("Nº Doc. EIPSA", "") or ""),
                "pedido": str(d.get("Nº Pedido", "") or ""),
                "cliente": norm_cliente(d.get("Cliente")),
                "responsable": str(d.get("Repsonsable", "") or "").strip() or "Sin Asignar",
                "tipo": str(d.get("Tipo Doc.", "") or "").strip() or "Sin Tipo",
                "critico": _es_critico(d),
            })
    out.sort(key=lambda e: e["fecha"])
    return out


def _meses(n: int) -> list[tuple[int, int]]:
    """Los últimos `n` meses como (año, mes), terminando en el actual."""
    hoy = date.today()
    y, m = hoy.year, hoy.month
    fuera = []
    for _ in range(n):
        fuera.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(fuera))


def get_actividad_mensual(meses: int = 18, eventos: list[dict] | None = None) -> dict:
    """Documentos enviados / aprobados / devueltos por mes."""
    eventos = doc_events() if eventos is None else eventos
    periodo = _meses(meses)
    idx = {ym: i for i, ym in enumerate(periodo)}
    series = {k: [0] * len(periodo) for k in ("enviado", "aprobado", "devuelto")}
    for e in eventos:
        i = idx.get((e["fecha"].year, e["fecha"].month))
        if i is not None and e["grupo"]:
            series[e["grupo"]][i] += 1
    return {
        "labels": [f"{MESES_ES[m - 1]} {str(y)[2:]}" for y, m in periodo],
        "enviados": series["enviado"],
        "aprobados": series["aprobado"],
        "devueltos": series["devuelto"],
        "total_enviados": sum(series["enviado"]),
        "total_aprobados": sum(series["aprobado"]),
        "total_devueltos": sum(series["devuelto"]),
    }


def get_ciclo_respuesta(eventos: list[dict] | None = None) -> dict:
    """Cuánto tarda el cliente en contestar, de verdad.

    Empareja cada «Enviado» con la primera resolución posterior del mismo
    documento. No es lo mismo que la columna «Días Devolución» del ERP, que solo
    mira la última revisión: aquí entra todo el histórico.
    """
    eventos = doc_events() if eventos is None else eventos
    por_doc: dict[str, list] = defaultdict(list)
    for e in eventos:
        if e["doc"]:
            por_doc[e["doc"]].append(e)

    ciclos: list[dict] = []
    for hechos in por_doc.values():
        pendiente = None
        for e in hechos:                       # ya vienen ordenados por fecha
            if e["grupo"] == "enviado":
                pendiente = e
            elif pendiente is not None and e["grupo"] in ("aprobado", "devuelto"):
                dias = (e["fecha"] - pendiente["fecha"]).days
                if 0 <= dias <= 365:
                    ciclos.append({"dias": dias, "cliente": pendiente["cliente"],
                                   "fecha": e["fecha"], "resultado": e["grupo"],
                                   "critico": pendiente["critico"],
                                   "tipo": pendiente["tipo"]})
                pendiente = None

    # Mediana mes a mes: es lo que se pinta en el sparkline de la tarjeta, para
    # ver si el cliente está tardando más o menos que antes. Se deja fuera el mes
    # en curso: con cuatro respuestas contadas la mediana se dispara y la tarjeta
    # marcaba subidas del 200 % que no eran ciertas.
    periodo = _meses(13)[:-1]
    por_mes: dict[tuple, list] = {ym: [] for ym in periodo}
    for c in ciclos:
        clave = (c["fecha"].year, c["fecha"].month)
        if clave in por_mes:
            por_mes[clave].append(c["dias"])
    medianas = []
    for ym in periodo:
        vals = sorted(por_mes[ym])
        medianas.append(vals[len(vals) // 2] if vals else None)

    dias = sorted(c["dias"] for c in ciclos)
    n = len(dias)
    tramos = [("0-7 d", 0, 7), ("8-15 d", 8, 15), ("16-30 d", 16, 30),
              ("31-60 d", 31, 60), ("+60 d", 61, 10 ** 6)]
    histograma = [{"label": lb, "value": sum(1 for d in dias if lo <= d <= hi)}
                  for lb, lo, hi in tramos]
    return {
        "ciclos": ciclos,
        "n": n,
        "mediana": dias[n // 2] if n else 0,
        "media": round(sum(dias) / n, 1) if n else 0,
        "p90": dias[int(n * 0.9)] if n else 0,
        "histograma": histograma,
        "dentro_15": round(100 * sum(1 for d in dias if d <= 15) / n) if n else 0,
        "mediana_mensual": medianas,
        "labels_mensual": [f"{MESES_ES[m - 1]} {str(y)[2:]}" for y, m in periodo],
    }


def get_retrabajo(eventos: list[dict] | None = None) -> dict:
    """Cuántas vueltas da un documento hasta que se aprueba.

    «A la primera» = aprobado en la revisión 0. Cada revisión de más es trabajo
    que hubo que repetir, así que es la métrica que mejor mide la calidad de lo
    que se manda.
    """
    eventos = doc_events() if eventos is None else eventos
    aprobados: dict[str, dict] = {}
    envios: dict[str, int] = defaultdict(int)
    for e in eventos:
        if e["grupo"] == "enviado":
            envios[e["doc"]] += 1
        if e["grupo"] == "aprobado" and e["doc"] not in aprobados:
            aprobados[e["doc"]] = e

    primera = vueltas = 0
    por_cliente: dict[str, dict] = defaultdict(lambda: {"total": 0, "primera": 0})
    for doc, e in aprobados.items():
        n_envios = max(1, envios.get(doc, 1))
        a_la_primera = n_envios == 1 and e["rev"] in ("0", "", "A")
        primera += a_la_primera
        vueltas += n_envios - 1
        g = por_cliente[e["cliente"]]
        g["total"] += 1
        g["primera"] += a_la_primera

    total = len(aprobados)
    ranking = [{"cliente": c, "total": g["total"], "primera": g["primera"],
                "pct": round(100 * g["primera"] / g["total"]) if g["total"] else 0}
               for c, g in por_cliente.items() if g["total"] >= 5]
    ranking.sort(key=lambda r: r["pct"])
    return {
        "aprobados": total,
        "a_la_primera": primera,
        "pct_primera": round(100 * primera / total) if total else 0,
        "vueltas_extra": vueltas,
        "media_envios": round(1 + vueltas / total, 2) if total else 0,
        "por_cliente": ranking,
    }


def get_clientes_cuadrante(eventos: list[dict] | None = None) -> list[dict]:
    """Cliente a cliente: volumen, días medios de respuesta y % a la primera.

    Es lo que alimenta el cuadrante: sirve para ver de un vistazo quién manda
    mucho volumen y además contesta tarde.
    """
    ciclo = get_ciclo_respuesta(eventos)
    retra = {r["cliente"]: r for r in get_retrabajo(eventos)["por_cliente"]}
    por_cliente: dict[str, list] = defaultdict(list)
    for c in ciclo["ciclos"]:
        por_cliente[c["cliente"]].append(c["dias"])

    out = []
    for cliente, dias in por_cliente.items():
        if len(dias) < 3:
            continue
        dias_ord = sorted(dias)
        out.append({
            "cliente": cliente,
            "n": len(dias),
            "mediana": dias_ord[len(dias_ord) // 2],
            "media": round(sum(dias) / len(dias), 1),
            "pct_primera": retra.get(cliente, {}).get("pct"),
        })
    out.sort(key=lambda r: r["n"], reverse=True)
    return out


def get_fecha_datos(eventos: list[dict] | None = None) -> str:
    """Fecha del hecho más reciente, para avisar si los datos están parados."""
    eventos = doc_events() if eventos is None else eventos
    return eventos[-1]["fecha"].strftime("%d/%m/%Y") if eventos else ""


def _hoy() -> date:
    return datetime.now().date()
