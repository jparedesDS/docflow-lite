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
from collections import defaultdict

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
        cliente = str(d.get("Cliente", "") or "").strip() or "Sin Cliente"
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
        cliente = str(d.get("Cliente", "") or "").strip() or "Sin Cliente"
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
        cliente = str(d.get("Cliente", "") or "").strip()
        if cliente:
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
