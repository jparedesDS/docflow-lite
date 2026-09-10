"""Un informe interactivo por cada pestaña de Analítica.

Seis documentos HTML autónomos —Pulso, Documentación, Clientes, Comercial,
Operaciones y Equipo— construidos con `report_kit`. Cada uno abre con el
hallazgo escrito en palabras y luego lo demuestra: el gráfico que toca según el
mensaje (evolución → línea, ranking → barras, desviación → divergente, relación
→ dispersión) y la tabla con el detalle para quien quiera bajar al caso.

Los datos salen de `analytics` (documentación) y `analytics_erp` (negocio), más
los servicios de cada departamento para el informe de operaciones.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from core.paths import state_dir
from core.services import analytics as an
from core.services import analytics_erp as ae
from core.services import report_kit as rk
from core.utils.fmt import dec, eur, num

logger = logging.getLogger(__name__)

# Clave → (título, subtítulo, función constructora). El orden es el de la app.
INFORMES = ("pulso", "documentacion", "clientes", "comercial", "operaciones", "equipo")

NOMBRES = {
    "pulso": "Pulso · el estado de la empresa",
    "documentacion": "Documentación · el ciclo del documento",
    "clientes": "Clientes · quién responde y quién hace repetir",
    "comercial": "Comercial · ofertas, adjudicación e ingresos",
    "operaciones": "Operaciones · taller, compras, calidad y almacén",
    "equipo": "Equipo · carga y ritmo",
}

_FUENTE_DOC = ("Documentación: seguimiento del ERP (historial de revisiones). "
               "Negocio y operaciones: base de datos del ERP de EIPSA.")


def _hoy() -> str:
    return date.today().strftime("%d/%m/%Y")


def _sino(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural


def _riesgo_color(riesgo: str) -> str:
    return {"fuera": rk.RED, "atrasado": rk.AMBER}.get(riesgo, rk.GREEN)


def _fecha(valor) -> str:
    """Fecha en dd/mm/aaaa; los servicios del ERP devuelven `date`, no texto."""
    if not valor:
        return "—"
    if hasattr(valor, "strftime"):
        return valor.strftime("%d/%m/%Y")
    return str(valor)[:10]


# ════════════════════════════════════════════════════════════════════════════
#  1 · PULSO
# ════════════════════════════════════════════════════════════════════════════

def pulso() -> rk.Report:
    resumen = an.get_summary()
    eventos = an.doc_events()
    actividad = an.get_actividad_mensual(18, eventos)
    ciclo = an.get_ciclo_respuesta(eventos)
    avance = an.get_avance_pedidos()
    mensual = ae.pedidos_mensuales(24)
    comercial = ae.comercial()
    cartera = ae.cartera()
    ops = ae.operaciones()

    anios = comercial["por_anio"]
    anio = anios[-1] if anios else {}
    atrasados = [r for r in avance if r["riesgo"] != "ok"]
    nuestros = sum(r["en_nuestro_tejado"] for r in avance)
    del_cliente = sum(r["en_cliente"] for r in avance)
    fact = ops.get("facturas", {})
    taller = ops.get("taller", {})
    compras = ops.get("compras", {})
    nc = ops.get("nc", {})

    doc = rk.Report(
        titulo="Pulso de la empresa",
        subtitulo="Cartera, ventas, documentación y operaciones en una sola lectura.",
        etiqueta="Dirección", fuentes=_FUENTE_DOC)

    lado = "nuestro" if nuestros > del_cliente else "del cliente"
    doc.titular(
        f"La cartera abierta son <b>{eur(cartera.get('importe', 0))}</b> en "
        f"{cartera.get('pedidos', 0)} pedidos, y el atasco de la documentación está "
        f"hoy en el lado <b>{lado}</b>.",
        [f"{anio.get('ofertas', 0)} ofertas en {anio.get('anio', '')} con un "
         f"<b>{anio.get('tasa', 0):.0f}% de adjudicación</b> sobre las resueltas; "
         f"{anio.get('vivas', 0)} siguen vivas.",
         f"El cliente tarda <b>{ciclo['mediana']} días</b> de mediana en contestar y solo "
         f"el {ciclo['dentro_15']}% lo hace dentro de 15.",
         f"<b>{len(atrasados)} de {len(avance)} pedidos</b> llevan la documentación "
         f"atrasada: {nuestros} documentos pendientes son nuestros y {del_cliente} "
         f"esperan al cliente.",
         f"{fact.get('pendientes', 0)} facturas sin cobrar por "
         f"<b>{eur(fact.get('importe_pendiente', 0))}</b>."])

    # ── La foto ──────────────────────────────────────────────────────────────
    s = doc.seccion("La foto", "las cifras que resumen el día")
    s.kpis([
        {"valor": eur(cartera.get("importe", 0)), "etiqueta": "Cartera abierta",
         "color": rk.ACCENT,
         "nota": f"{cartera.get('pedidos', 0)} pedidos · {cartera.get('fuera_plazo', 0)} fuera de plazo"},
        {"valor": eur(anio.get("importe", 0)), "etiqueta": f"Pedidos {anio.get('anio', '')}",
         "color": rk.GREEN, "nota": f"{anio.get('pedidos', 0)} pedidos firmados"},
        {"valor": f"{anio.get('tasa', 0):.0f}%", "etiqueta": "Adjudicación",
         "color": rk.color_pct(anio.get("tasa", 0)),
         "nota": f"{anio.get('ganadas', 0)} ganadas · {anio.get('perdidas', 0)} perdidas"},
        {"valor": resumen["docs_riesgo"], "etiqueta": "Docs en riesgo",
         "color": rk.RED if resumen["docs_riesgo"] else rk.GREEN,
         "nota": "críticos con +15 días sin respuesta"},
        {"valor": eur(fact.get("importe_pendiente", 0)), "etiqueta": "Por cobrar",
         "color": rk.AMBER, "nota": f"{fact.get('pendientes', 0)} facturas · la más vieja, "
                                    f"{fact.get('mas_antigua', 0)} días"},
    ])

    # ── El negocio ───────────────────────────────────────────────────────────
    s = doc.seccion("El negocio", "de dónde vienen los ingresos")
    total_2 = sum(mensual["importes"][-12:])
    total_1 = sum(mensual["importes_previo"][-12:])
    var = round(100 * (total_2 - total_1) / total_1) if total_1 else 0
    s.linea(
        (f"Los últimos 12 meses suman {eur(total_2)}, un {abs(var)}% "
         f"{'más' if var >= 0 else 'menos'} que los 12 anteriores"),
        "importe de pedidos firmados por mes · el mes en curso va incompleto",
        mensual["labels"],
        [{"label": "Este año", "color": rk.ACCENT, "valores": mensual["importes"]},
         {"label": "Año anterior", "color": rk.GREY, "valores": mensual["importes_previo"]}],
        unidad=" €", area=True, alto=280)

    estados = comercial["por_estado"]
    colores = {"Adjudicada": rk.GREEN, "Perdida": rk.RED, "Presentada": rk.BLUE,
               "Registrada": rk.BLUE, "Budgetary": rk.AMBER}
    s.anillo("Cómo acaban las ofertas", f"desde {ae.DESDE_ANIO}",
             [{"label": e["estado"], "valor": e["n"],
               "color": colores.get(e["estado"], rk.GREY)} for e in estados],
             centro="ofertas")
    mercado = [m for m in comercial["mercado"] if m["ofertas"] > 10]
    s.ranking("Adjudicación por mercado", "sobre ofertas resueltas",
              [{"label": m["mercado"], "valor": m["tasa"], "texto": f"{m['tasa']:.0f}%",
                "color": rk.color_pct(m["tasa"])} for m in mercado])

    # ── La documentación ─────────────────────────────────────────────────────
    s = doc.seccion("La documentación", "qué se mueve y qué se atasca")
    s.linea("Lo que entra y lo que sale cada mes",
            "movimientos del historial de revisiones · en agosto la empresa cierra",
            actividad["labels"],
            [{"label": "Enviados", "color": rk.BLUE, "valores": actividad["enviados"]},
             {"label": "Aprobados", "color": rk.GREEN, "valores": actividad["aprobados"]},
             {"label": "Devueltos", "color": rk.AMBER, "valores": actividad["devueltos"]}],
            alto=260)
    s.aviso(
        f"De los <b>{nuestros + del_cliente} documentos pendientes</b> en pedidos abiertos, "
        f"<b>{nuestros}</b> están en nuestro tejado (sin enviar o devueltos con comentarios) "
        f"y <b>{del_cliente}</b> esperan respuesta del cliente.",
        "aviso" if nuestros > del_cliente else "info")
    _tabla_atrasados(s, atrasados[:10],
                     "Los pedidos que peor van",
                     "ordenados por lo lejos que están de donde deberían")

    # ── El resto de la casa ──────────────────────────────────────────────────
    s = doc.seccion("El resto de la casa", "taller, compras y calidad")
    s.kpis([
        {"valor": taller.get("abiertos", 0), "etiqueta": "Pedidos en taller",
         "color": rk.INK, "nota": f"{taller.get('en_curso', 0)} en curso"},
        {"valor": taller.get("retrasados", 0), "etiqueta": "Retrasados en taller",
         "color": rk.RED if taller.get("retrasados") else rk.GREEN,
         "nota": f"el peor, {taller.get('retraso_max', 0)} días"},
        {"valor": compras.get("retrasadas", 0), "etiqueta": "Compras retrasadas",
         "color": rk.RED if compras.get("retrasadas") else rk.GREEN,
         "nota": f"de {compras.get('lineas', 0)} líneas pendientes"},
        {"valor": nc.get("abiertas", 0), "etiqueta": "NC sin cerrar",
         "color": rk.AMBER if nc.get("abiertas") else rk.GREEN,
         "nota": f"{nc.get('abiertas_anio', 0)} de este año"},
        {"valor": ops.get("almacen", {}).get("en_almacen", 0), "etiqueta": "En almacén",
         "color": rk.INK,
         "nota": f"{ops.get('almacen', {}).get('atascados', 0)} llevan demasiado"},
    ])
    s.nota_pie("El detalle de cada área está en el informe de Operaciones.")
    return doc


def _tabla_atrasados(s, filas: list, titulo: str, nota: str) -> None:
    """Tabla común de pedidos con la documentación atrasada."""
    cols = [{"t": "Pedido", "mono": True}, {"t": "Cliente"},
            {"t": "Aprobados", "num": True}, {"t": "% real", "num": True},
            {"t": "% esperado", "num": True}, {"t": "Desviación", "num": True},
            {"t": "Nuestros", "num": True}, {"t": "En cliente", "num": True},
            {"t": "Plazo", "num": True}]
    datos = []
    for r in filas:
        col = _riesgo_color(r["riesgo"])
        dias = r["dias_al_plazo"]
        plazo = "—" if dias is None else (f"{abs(dias)} d tarde" if dias < 0
                                          else f"faltan {dias} d")
        datos.append([
            r["pedido"], str(r["cliente"])[:30], f"{r['aprobados']}/{r['total']}",
            {"v": f"{r['pct']}%"}, {"v": f"{r['pct_esperado']}%", "color": rk.MUTED},
            {"v": f"{r['desviacion']:+d} pp", "color": col, "bold": True},
            {"v": r["en_nuestro_tejado"] or "—",
             "color": rk.AMBER if r["en_nuestro_tejado"] else rk.MUTED},
            {"v": r["en_cliente"] or "—", "color": rk.BLUE if r["en_cliente"] else rk.MUTED},
            {"v": plazo, "color": col}])
    s.tabla(titulo, cols, datos, nota=nota,
            vacio="Ningún pedido con la documentación atrasada.")


# ════════════════════════════════════════════════════════════════════════════
#  2 · DOCUMENTACIÓN
# ════════════════════════════════════════════════════════════════════════════

def documentacion() -> rk.Report:
    resumen = an.get_summary()
    eventos = an.doc_events()
    actividad = an.get_actividad_mensual(18, eventos)
    ciclo = an.get_ciclo_respuesta(eventos)
    retrabajo = an.get_retrabajo(eventos)
    avance = an.get_avance_pedidos()
    cuadrante = an.get_clientes_cuadrante(eventos)

    doc = rk.Report(
        titulo="El ciclo del documento",
        subtitulo="Cuánto tardamos, cuánto tarda el cliente y cuántas vueltas da cada documento.",
        etiqueta="Documentación", fuentes=_FUENTE_DOC)

    tarde = 100 - ciclo["dentro_15"]
    doc.titular(
        f"El cliente tarda <b>{ciclo['mediana']} días</b> de mediana en contestar, pero "
        f"<b>{tarde}% de las respuestas pasan de 15 días</b> y un 10% supera los "
        f"{ciclo['p90']}.",
        [f"Se aprueba a la primera el <b>{retrabajo['pct_primera']}%</b>: hacen falta "
         f"{retrabajo['media_envios']} envíos de media por documento aprobado, "
         f"{retrabajo['vueltas_extra']} envíos repetidos en total.",
         f"{actividad['total_enviados']} documentos enviados en los últimos 18 meses, "
         f"{actividad['total_aprobados']} aprobados y {actividad['total_devueltos']} devueltos.",
         f"<b>{sum(1 for r in avance if r['riesgo'] != 'ok')} pedidos</b> llevan la "
         f"documentación por detrás de su fecha."])

    # ── Ritmo ────────────────────────────────────────────────────────────────
    s = doc.seccion("Ritmo", "cuánto entra y cuánto sale cada mes")
    mensual = [v for v in ciclo["mediana_mensual"] if v is not None]
    delta = None
    if len(mensual) > 1 and mensual[-2]:
        delta = round(100 * (mensual[-1] - mensual[-2]) / mensual[-2])
    s.kpis([
        {"valor": f"{ciclo['mediana']} d", "etiqueta": "Respuesta del cliente",
         "color": rk.color_dias(ciclo["mediana"]), "delta": delta, "delta_bueno": False,
         "nota": f"mediana de {ciclo['n']} respuestas · media {dec(ciclo['media'])} d · "
                 f"la flecha compara el último mes cerrado con el anterior"},
        {"valor": f"{ciclo['dentro_15']}%", "etiqueta": "Dentro de 15 días",
         "color": rk.color_pct(ciclo["dentro_15"]), "nota": "el plazo con el que se reclama"},
        {"valor": f"{retrabajo['pct_primera']}%", "etiqueta": "Aprobado a la primera",
         "color": rk.color_pct(retrabajo["pct_primera"]),
         "nota": f"{retrabajo['a_la_primera']} de {retrabajo['aprobados']} aprobados"},
        {"valor": dec(retrabajo["media_envios"], 2),
         "etiqueta": "Envíos por documento",
         "color": rk.AMBER if retrabajo["media_envios"] > 1.5 else rk.GREEN,
         "nota": f"{retrabajo['vueltas_extra']} envíos repetidos"},
    ])
    s.linea("Agosto se nota: no sale un solo documento",
            "movimientos con fecha del historial de revisiones · el mes en curso va incompleto",
            actividad["labels"],
            [{"label": "Enviados", "color": rk.BLUE, "valores": actividad["enviados"]},
             {"label": "Aprobados", "color": rk.GREEN, "valores": actividad["aprobados"]},
             {"label": "Devueltos", "color": rk.AMBER, "valores": actividad["devueltos"]}],
            alto=280)

    # ── Cuánto tarda en volver ───────────────────────────────────────────────
    s = doc.seccion("Cuánto tarda en volver", "de cada envío a su respuesta")
    h = ciclo["histograma"]
    # El color va por tramo, no por serie: verde lo que llega en plazo, rojo lo
    # que ya no es normal. Chart.js acepta una lista de colores por barra.
    tramos = [rk.GREEN, rk.GREEN, rk.AMBER, rk.RED, rk.RED]
    s.barras("Más de la mitad de las respuestas llegan pasados los 15 días",
             f"reparto de las {ciclo['n']} respuestas medidas",
             [x["label"] for x in h],
             [{"label": "Respuestas", "color": tramos, "valores": [x["value"] for x in h]}],
             alto=250)
    s.nota_pie(f"Verde dentro de plazo, ámbar el aviso, rojo lo que ya no es normal. "
               f"El percentil 90 está en {ciclo['p90']} días: una de cada diez respuestas "
               f"tarda más que eso.")
    lentos = sorted([c for c in cuadrante if c["n"] >= 10],
                    key=lambda c: c["mediana"], reverse=True)[:10]
    s.ranking("Los clientes que más tardan", "mediana de días hasta contestar",
              [{"label": c["cliente"][:24], "valor": c["mediana"],
                "texto": f"{c['mediana']} d", "color": rk.color_dias(c["mediana"])}
               for c in lentos])
    rapidos = sorted([c for c in cuadrante if c["n"] >= 10], key=lambda c: c["mediana"])[:10]
    s.ranking("Y los que menos", "mismos criterios",
              [{"label": c["cliente"][:24], "valor": c["mediana"],
                "texto": f"{c['mediana']} d", "color": rk.color_dias(c["mediana"])}
               for c in rapidos])

    # ── Retrabajo ────────────────────────────────────────────────────────────
    s = doc.seccion("Retrabajo", "cuántas vueltas da un documento hasta aprobarse")
    peores = [r for r in retrabajo["por_cliente"] if r["total"] >= 10][:12]
    s.ranking("Dónde se repite más el trabajo", "% aprobado a la primera, de peor a mejor",
              [{"label": r["cliente"][:24], "valor": max(r["pct"], 1),
                "texto": f"{r['pct']}%", "color": rk.color_pct(r["pct"])} for r in peores],
              ancho="full")
    tipos = resumen["por_tipo_doc"][:12]
    s.tabla("Por tipo de documento",
            [{"t": "Tipo"}, {"t": "Aprobados", "num": True}, {"t": "En cliente", "num": True},
             {"t": "Con comentarios", "num": True}, {"t": "Sin enviar", "num": True},
             {"t": "Total", "num": True}, {"t": "% aprobado", "num": True}],
            [[t["tipo"], t["aprobado"], t["enviado"], t["com_menores"], t["sin_enviar"],
              t["total"],
              {"v": f"{round(100 * t['aprobado'] / t['total']) if t['total'] else 0}%",
               "color": rk.color_pct(round(100 * t["aprobado"] / t["total"]) if t["total"] else 0),
               "bold": True}]
             for t in tipos])

    # ── Avance por pedido ────────────────────────────────────────────────────
    s = doc.seccion("Avance por pedido", "quién va por detrás de su fecha")
    en_fecha = [r for r in avance if (r["dias_al_plazo"] or 0) >= 0]
    s.dispersion(
        "Por debajo de la línea, la documentación va con retraso",
        f"los {len(en_fecha)} pedidos que aún están dentro de fecha · "
        "el tamaño es el número de documentos",
        [{"x": r["pct_esperado"], "y": r["pct"], "r": 4 + (r["total"] ** 0.5) * 1.6,
          "label": r["pedido"], "color": _riesgo_color(r["riesgo"])} for r in en_fecha],
        eje_x="avance que tocaría a estas alturas (%)", eje_y="% aprobado de verdad",
        diagonal=True, alto=340)
    _tabla_atrasados(s, [r for r in avance if r["riesgo"] != "ok"],
                     "Todos los pedidos atrasados", "ordenados por desviación")

    # ── Estado actual ────────────────────────────────────────────────────────
    s = doc.seccion("Estado actual", "dónde está cada documento ahora mismo")
    s.anillo("El 92% de la cartera documental está aprobada", "sobre el total en seguimiento",
             [{"label": "Aprobado", "valor": resumen["total_aprobados"], "color": rk.GREEN},
              {"label": "En el cliente", "valor": resumen["total_enviados"], "color": rk.BLUE},
              {"label": "Con comentarios", "valor": resumen["total_devoluciones"], "color": rk.AMBER},
              {"label": "Sin enviar", "valor": resumen["total_sin_enviar"], "color": rk.GREY}],
             centro="documentos")
    heat = resumen["heatmap_cliente"][:12]
    s.ranking("Volumen por cliente", "documentos en seguimiento",
              [{"label": h["cliente"][:24], "valor": h["total"], "texto": str(h["total"]),
                "color": rk.ACCENT} for h in heat])
    return doc


# ════════════════════════════════════════════════════════════════════════════
#  3 · CLIENTES
# ════════════════════════════════════════════════════════════════════════════

def clientes() -> rk.Report:
    eventos = an.doc_events()
    cuadrante = an.get_clientes_cuadrante(eventos)
    retrabajo = an.get_retrabajo(eventos)
    score = an.get_scorecard()
    ciclo = an.get_ciclo_respuesta(eventos)
    top = ae.top_clientes(limite=15)

    doc = rk.Report(
        titulo="Quién responde y quién hace repetir",
        subtitulo="Los clientes ordenados por lo que cuesta trabajar con ellos, no por lo que facturan.",
        etiqueta="Clientes", fuentes=_FUENTE_DOC)

    mediana = ciclo["mediana"]
    malos = [c for c in cuadrante if c["mediana"] > mediana
             and (c["pct_primera"] or 0) < 50 and c["n"] >= 20]
    malos.sort(key=lambda c: -c["n"])
    nombres = ", ".join(c["cliente"][:18] for c in malos[:3]) or "ninguno"
    doc.titular(
        f"<b>{len(malos)} clientes</b> tardan más de la mediana ({mediana} días) "
        f"<i>y además</i> aprueban menos de la mitad a la primera: {nombres}.",
        [f"Son los que más trabajo repetido generan: cada documento suyo pasa por más "
         f"revisiones y cada revisión tarda más en volver.",
         f"{len(cuadrante)} clientes tienen respuestas suficientes para medirlos "
         f"({ciclo['n']} respuestas en total).",
         f"El scorecard puntúa {len(score)} clientes combinando aprobación a la primera, "
         f"días de respuesta y críticos parados."])

    # ── Cuadrante ────────────────────────────────────────────────────────────
    s = doc.seccion("El cuadrante", "rapidez frente a trabajo repetido")
    puntos = []
    for c in cuadrante[:26]:
        if c["pct_primera"] is None:
            continue
        tarde, repite = c["mediana"] > mediana, c["pct_primera"] < 50
        color = rk.RED if (tarde and repite) else (rk.AMBER if (tarde or repite) else rk.GREEN)
        puntos.append({"x": c["mediana"], "y": c["pct_primera"],
                       "r": 4 + (c["n"] ** 0.5) * 0.9, "label": c["cliente"][:18],
                       "color": color})
    s.dispersion(
        "Arriba a la izquierda están los clientes fáciles; abajo a la derecha, los caros",
        "el tamaño es el número de respuestas medidas",
        puntos, eje_x="días hasta contestar (mediana)",
        eje_y="% aprobado a la primera", alto=360)
    s.aviso(
        "Un cliente que tarda mucho <b>y</b> además devuelve todo con comentarios cuesta el "
        "doble: hay que perseguirle la respuesta y luego rehacer el documento. Son los de "
        "la esquina inferior derecha.", "aviso")

    # ── Peso ─────────────────────────────────────────────────────────────────
    s = doc.seccion("Peso de cada uno", "lo que aportan frente a lo que cuestan")
    if top:
        s.ranking("Por importe de pedido", f"desde {ae.DESDE_ANIO}",
                  [{"label": str(t["cliente"])[:24], "valor": t["importe"],
                    "texto": eur(t["importe"]), "color": rk.ACCENT} for t in top[:12]])
    s.ranking("Por volumen de documentación", "respuestas medidas",
              [{"label": c["cliente"][:24], "valor": c["n"], "texto": str(c["n"]),
                "color": rk.BLUE} for c in cuadrante[:12]])

    # ── Scorecard ────────────────────────────────────────────────────────────
    s = doc.seccion("Scorecard", "la nota de cada cliente, de 0 a 100")
    if score:
        media = round(sum(r["score"] for r in score) / len(score), 1)
        mejor, peor = max(score, key=lambda r: r["score"]), min(score, key=lambda r: r["score"])
        s.kpis([
            {"valor": dec(media), "etiqueta": "Score medio",
             "color": rk.color_pct(media, 80, 50), "nota": f"de {len(score)} clientes"},
            {"valor": mejor["client"][:20], "etiqueta": "Mejor cliente",
             "color": rk.GREEN, "nota": f"{mejor['score']} puntos"},
            {"valor": peor["client"][:20], "etiqueta": "Peor cliente",
             "color": rk.RED, "nota": f"{peor['score']} puntos"},
        ])
    dias_por_cliente = {c["cliente"]: c["mediana"] for c in cuadrante}
    primera = {r["cliente"]: r["pct"] for r in retrabajo["por_cliente"]}
    s.tabla("Todos los clientes",
            [{"t": "Cliente"}, {"t": "Score", "num": True},
             {"t": "Mediana respuesta", "num": True}, {"t": "% a la primera", "num": True},
             {"t": "Críticos +30d", "num": True}, {"t": "Documentos", "num": True}],
            [[r["client"],
              {"v": r["score"], "color": rk.color_pct(r["score"], 80, 50), "bold": True},
              {"v": (f"{dias_por_cliente[r['client']]} d"
                     if r["client"] in dias_por_cliente else "—"),
               "color": (rk.color_dias(dias_por_cliente[r["client"]])
                         if r["client"] in dias_por_cliente else rk.MUTED)},
              {"v": (f"{primera[r['client']]}%" if r["client"] in primera else "—"),
               "color": (rk.color_pct(primera[r["client"]]) if r["client"] in primera
                         else rk.MUTED)},
              {"v": r["critical_docs_count"] or "—",
               "color": rk.RED if r["critical_docs_count"] else rk.MUTED},
              r["total_docs"]]
             for r in score[:40]],
            nota="Score = 40% aprobación a la primera + 30% rapidez + 30% críticos al día")
    return doc


# ════════════════════════════════════════════════════════════════════════════
#  4 · COMERCIAL
# ════════════════════════════════════════════════════════════════════════════

def comercial() -> rk.Report:
    c = ae.comercial()
    mensual = ae.pedidos_mensuales(24)
    cartera = ae.cartera()
    pipe = ae.pipeline()
    top = ae.top_clientes(limite=15)

    anios = c["por_anio"]
    doc = rk.Report(
        titulo="Ofertas, adjudicación e ingresos",
        subtitulo="El embudo completo: qué se oferta, qué se gana y qué entra por la puerta.",
        etiqueta="Comercial",
        fuentes="Base de datos del ERP de EIPSA (ofertas y pedidos, importes incluidos).")

    if not anios:
        doc.titular("El ERP no responde: este informe sale de su base de datos.")
        doc.seccion("Sin datos").aviso(
            "No se ha podido conectar con el ERP. Revisa Ajustes ▸ Fuentes de datos y "
            "vuelve a generar el informe.", "mal")
        return doc

    anio = anios[-1]
    previo = anios[-2] if len(anios) > 1 else {}
    mercado = [m for m in c["mercado"] if m["ofertas"] > 10]
    nac = next((m for m in mercado if m["mercado"].lower().startswith("nac")), None)
    ext = next((m for m in mercado if m["mercado"].lower().startswith("ext")), None)

    puntos = [
        f"En {anio['anio']} van {anio['ofertas']} ofertas: {anio['ganadas']} ganadas, "
        f"{anio['perdidas']} perdidas y <b>{anio['vivas']} aún sin resolver</b>.",
        f"Adjudicado <b>{eur(anio['imp_ganadas'])}</b> de {eur(anio['of_importe'])} ofertados; "
        f"{anio['pedidos']} pedidos firmados por {eur(anio['importe'])}.",
    ]
    if nac and ext:
        puntos.append(
            f"Nacional adjudica al <b>{nac['tasa']:.0f}%</b> y exterior al "
            f"<b>{ext['tasa']:.0f}%</b>: fuera hacen falta más del doble de ofertas "
            f"para el mismo pedido.")
    if pipe["n"]:
        puntos.append(f"Hay <b>{eur(pipe['importe'])}</b> encima de la mesa en "
                      f"{pipe['n']} ofertas vivas.")

    doc.titular(
        f"La tasa de adjudicación se mantiene en el <b>{anio['tasa']:.0f}%</b> sobre las "
        f"ofertas resueltas, con {anio['vivas']} todavía en el aire.", puntos)

    # ── El año ───────────────────────────────────────────────────────────────
    s = doc.seccion("El año en curso", f"{anio['anio']} frente a {previo.get('anio', '—')}")
    s.kpis([
        {"valor": anio["ofertas"], "etiqueta": "Ofertas", "color": rk.INK,
         "nota": f"{anio['vivas']} sin resolver",
         "delta": _delta(anio["ofertas"], previo.get("ofertas"))},
        {"valor": f"{anio['tasa']:.0f}%", "etiqueta": "Adjudicación",
         "color": rk.color_pct(anio["tasa"]),
         "nota": f"{anio['ganadas']} de {anio['resueltas']} resueltas",
         "delta": _delta(anio["tasa"], previo.get("tasa"))},
        {"valor": eur(anio["imp_ganadas"]), "etiqueta": "Adjudicado", "color": rk.GREEN,
         "nota": f"de {eur(anio['of_importe'])} ofertados"},
        {"valor": anio["pedidos"], "etiqueta": "Pedidos firmados", "color": rk.BLUE,
         "nota": eur(anio["importe"]),
         "delta": _delta(anio["importe"], previo.get("importe"))},
        {"valor": eur(cartera["importe"]), "etiqueta": "Cartera abierta", "color": rk.ACCENT,
         "nota": f"{cartera['pedidos']} pedidos vivos"},
    ])

    # ── Evolución ────────────────────────────────────────────────────────────
    s = doc.seccion("Evolución", "cómo ha ido el embudo estos años")
    etiquetas = [str(a["anio"]) for a in anios]
    s.barras("Ganadas, perdidas y las que siguen en el aire",
             "las vivas del año en curso aún pueden caer de cualquier lado",
             etiquetas,
             [{"label": "Ganadas", "color": rk.GREEN, "valores": [a["ganadas"] for a in anios]},
              {"label": "Perdidas", "color": rk.RED, "valores": [a["perdidas"] for a in anios]},
              {"label": "Vivas", "color": rk.BLUE, "valores": [a["vivas"] for a in anios]}],
             alto=270)
    s.linea("La tasa de adjudicación", "ganadas ÷ (ganadas + perdidas)", etiquetas,
            [{"label": "Adjudicación", "color": rk.ACCENT, "valores": [a["tasa"] for a in anios]}],
            unidad="%", area=True, alto=230, ancho="half")
    s.barras("Importe de pedidos por año", "lo que se firmó cada año", etiquetas,
             [{"label": "Pedidos", "color": rk.ACCENT, "valores": [a["importe"] for a in anios]}],
             unidad=" €", alto=230, ancho="half")

    # ── Ingresos ─────────────────────────────────────────────────────────────
    s = doc.seccion("Ingresos mes a mes", "el detalle de los dos últimos años")
    s.linea("Contra el mismo mes del año anterior",
            "importe de pedidos firmados · el mes en curso va incompleto",
            mensual["labels"],
            [{"label": "Este año", "color": rk.ACCENT, "valores": mensual["importes"]},
             {"label": "Año anterior", "color": rk.GREY, "valores": mensual["importes_previo"]}],
            unidad=" €", area=True, alto=280)

    # ── Dónde ganamos ────────────────────────────────────────────────────────
    s = doc.seccion("Dónde ganamos", "por mercado y por comercial")
    if mercado:
        s.ranking("Adjudicación por mercado", "sobre ofertas resueltas",
                  [{"label": m["mercado"], "valor": m["tasa"], "texto": f"{m['tasa']:.0f}%",
                    "color": rk.color_pct(m["tasa"])} for m in mercado])
        s.anillo("Reparto de las ofertas", "cuántas se presentan a cada mercado",
                 [{"label": m["mercado"], "valor": m["ofertas"],
                   "color": col} for m, col in zip(mercado, (rk.ACCENT, rk.BLUE, rk.GREY))],
                 centro="ofertas")

    equipo = [r for r in c["por_comercial"] if r["resueltas"] >= 20]
    if equipo:
        media = sum(r["tasa"] for r in equipo) / len(equipo)
        equipo.sort(key=lambda r: r["tasa"] - media)
        s.divergente(
            f"Desviación de cada comercial sobre la media del equipo ({media:.0f}%)",
            "puntos porcentuales de tasa de adjudicación · solo con 20 ofertas resueltas o más",
            [{"label": r["iniciales"], "valor": round(r["tasa"] - media, 1),
              "color": rk.GREEN if r["tasa"] >= media else rk.AMBER} for r in equipo],
            unidad=" pp")
        s.tabla("Por comercial",
                [{"t": "Comercial", "mono": True}, {"t": "Ofertas", "num": True},
                 {"t": "Ganadas", "num": True}, {"t": "Perdidas", "num": True},
                 {"t": "Vivas", "num": True}, {"t": "Adjudicación", "num": True},
                 {"t": "Importe adjudicado", "num": True}],
                [[r["iniciales"], r["ofertas"], r["ganada"], r["perdida"],
                  {"v": r["viva"] or "—", "color": rk.MUTED if not r["viva"] else rk.BLUE},
                  {"v": f"{r['tasa']:.0f}%", "color": rk.color_pct(r["tasa"]), "bold": True},
                  eur(r["imp_ganadas"])]
                 for r in sorted(c["por_comercial"], key=lambda r: -r["imp_ganadas"])
                 if r["ofertas"] >= 5])

    # ── Pipeline ─────────────────────────────────────────────────────────────
    if pipe["n"]:
        s = doc.seccion("Lo que está en el aire", "ofertas presentadas sin resolver")
        s.kpis([
            {"valor": pipe["n"], "etiqueta": "Ofertas vivas", "color": rk.BLUE,
             "nota": "presentadas o registradas"},
            {"valor": eur(pipe["importe"]), "etiqueta": "Importe en juego",
             "color": rk.ACCENT, "nota": "si cayeran todas"},
            {"valor": f"{pipe['dias_max']} d", "etiqueta": "La más antigua",
             "color": rk.AMBER if pipe["dias_max"] > 90 else rk.INK,
             "nota": "desde que se registró"},
        ])
        s.tabla("Ofertas vivas",
                [{"t": "Oferta", "mono": True}, {"t": "Cliente"}, {"t": "Comercial", "mono": True},
                 {"t": "Importe", "num": True}, {"t": "Días", "num": True}, {"t": "Estado"}],
                [[r["oferta"], str(r["cliente"])[:30], r["comercial"], eur(r["importe"]),
                  {"v": r["dias"], "color": rk.AMBER if r["dias"] > 90 else rk.INK},
                  r["estado"]]
                 for r in pipe["ofertas"][:40]],
                nota="ordenadas por importe")

    # ── Clientes ─────────────────────────────────────────────────────────────
    if top:
        s = doc.seccion("Clientes por facturación", f"pedidos firmados desde {ae.DESDE_ANIO}")
        s.ranking("Los que más pesan", "importe de pedido",
                  [{"label": str(t["cliente"])[:26], "valor": t["importe"],
                    "texto": eur(t["importe"]), "color": rk.ACCENT} for t in top],
                  ancho="full")
    return doc


def _delta(actual, previo):
    if not previo or actual is None:
        return None
    try:
        return round(100 * (float(actual) - float(previo)) / float(previo))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


# ════════════════════════════════════════════════════════════════════════════
#  5 · OPERACIONES
# ════════════════════════════════════════════════════════════════════════════

def operaciones() -> rk.Report:
    from core.services import production, purchases, quality, warehouse

    ops = ae.operaciones()
    nc_anios = ae.nc_por_anio()
    taller = ops.get("taller", {})
    horas = ops.get("horas", {})
    compras_st = ops.get("compras", {})
    nc_st = ops.get("nc", {})
    equipos_st = ops.get("equipos", {})
    almacen_st = ops.get("almacen", {})

    doc = rk.Report(
        titulo="Taller, compras, calidad y almacén",
        subtitulo="Lo que pasa entre que entra el pedido y sale el material.",
        etiqueta="Operaciones",
        fuentes="Base de datos del ERP de EIPSA: fabricación, compras, verificación y expediciones.")

    ultima = horas.get("ultima")
    doc.titular(
        f"<b>{taller.get('retrasados', 0)} de {taller.get('abiertos', 0)} pedidos</b> en "
        f"taller van con retraso y hay <b>{compras_st.get('retrasadas', 0)} líneas de compra</b> "
        f"que ya deberían haber llegado.",
        [f"{num(horas.get('total', 0))} horas imputadas al taller, "
         f"{num(horas.get('imputadas', 0))} de ellas asignadas a un pedido concreto.",
         f"{nc_st.get('abiertas', 0)} no conformidades sin cerrar de "
         f"{nc_st.get('total', 0)} registradas.",
         f"{equipos_st.get('vencidos', 0)} equipos de medida con la calibración vencida.",
         (f"Ojo: la última imputación de horas es del {ultima:%d/%m/%Y}; "
          f"el parte de taller lleva tiempo sin usarse." if ultima else "")])

    s = doc.seccion("La foto", "el estado de las cuatro áreas")
    s.kpis([
        {"valor": taller.get("abiertos", 0), "etiqueta": "Pedidos en taller",
         "color": rk.ACCENT, "nota": f"{taller.get('en_curso', 0)} en curso · "
                                     f"{taller.get('sin_empezar', 0)} sin empezar"},
        {"valor": taller.get("retrasados", 0), "etiqueta": "Retrasados",
         "color": rk.RED if taller.get("retrasados") else rk.GREEN,
         "nota": f"el peor, {taller.get('retraso_max', 0)} días"},
        {"valor": compras_st.get("retrasadas", 0), "etiqueta": "Compras retrasadas",
         "color": rk.RED if compras_st.get("retrasadas") else rk.GREEN,
         "nota": f"de {compras_st.get('lineas', 0)} líneas · "
                 f"{compras_st.get('proveedores', 0)} proveedores"},
        {"valor": nc_st.get("abiertas", 0), "etiqueta": "NC sin cerrar",
         "color": rk.AMBER if nc_st.get("abiertas") else rk.GREEN,
         "nota": f"{nc_st.get('abiertas_anio', 0)} de este año"},
        {"valor": almacen_st.get("en_almacen", 0), "etiqueta": "En almacén",
         "color": rk.INK,
         "nota": f"{almacen_st.get('atascados', 0)} atascados · "
                 f"lo más viejo, {almacen_st.get('dias_max', 0)} días"},
    ])

    # ── Taller ───────────────────────────────────────────────────────────────
    s = doc.seccion("Taller", "qué se está fabricando y cuánto cuesta")
    try:
        filas = [r for r in production.active() if not r.get("antiguo")]
    except Exception:  # noqa: BLE001
        filas = []
    filas.sort(key=lambda r: -r.get("retraso", 0))
    peores = [r for r in filas if r.get("retraso", 0) > 0][:12]
    if peores:
        s.divergente(
            "Los pedidos que más tarde van en taller",
            "días de retraso sobre la fecha de entrega prevista",
            [{"label": r["pedido"], "valor": r["retraso"], "color": rk.RED}
             for r in reversed(peores)], unidad=" d")
    s.tabla("Pedidos abiertos en taller",
            [{"t": "Pedido", "mono": True}, {"t": "Cliente"}, {"t": "Equipo"},
             {"t": "Fabricación", "num": True}, {"t": "Montaje", "num": True},
             {"t": "Entrega prevista", "num": True}, {"t": "Retraso", "num": True}],
            [[r.get("pedido", ""), str(r.get("cliente", ""))[:26],
              str(r.get("equipo", ""))[:24],
              {"v": f"{r.get('taller', 0)}%",
               "color": rk.GREEN if r.get("taller", 0) >= 100 else rk.INK},
              {"v": f"{r.get('montaje', 0)}%",
               "color": rk.GREEN if r.get("montaje", 0) >= 100 else rk.INK},
              _fecha(r.get("prevista")),
              {"v": (f"{r['retraso']} d" if r.get("retraso", 0) > 0 else "—"),
               "color": rk.RED if r.get("retraso", 0) > 0 else rk.MUTED, "bold": True}]
             for r in filas[:30]],
            nota=f"{taller.get('antiguos', 0)} pedidos con fechas imposibles del ERP quedan fuera")
    operac = horas.get("por_operacion", [])[:10]
    if operac:
        s.ranking("Horas por operación", "dónde se va el tiempo del taller",
                  [{"label": str(o["operacion"])[3:][:24], "valor": o["horas"],
                    "texto": f"{num(o['horas'])} h", "color": rk.BLUE} for o in operac],
                  ancho="full")

    # ── Compras ──────────────────────────────────────────────────────────────
    s = doc.seccion("Compras", "material pendiente de recibir")
    try:
        lineas = purchases.pending()
    except Exception:  # noqa: BLE001
        lineas = []
    retrasadas = sorted([x for x in lineas if x.get("retraso", 0) > 0],
                        key=lambda x: -x["retraso"])
    if retrasadas:
        por_prov: dict[str, int] = {}
        for x in retrasadas:
            prov = str(x.get("proveedor", "")) or "—"
            por_prov[prov] = max(por_prov.get(prov, 0), x.get("retraso", 0))
        peores = sorted(por_prov.items(), key=lambda kv: -kv[1])[:10]
        s.ranking("Proveedores con material más retrasado", "días del peor retraso de cada uno",
                  [{"label": p[:24], "valor": d, "texto": f"{d} d", "color": rk.RED}
                   for p, d in peores])
    s.tabla("Líneas de compra retrasadas",
            [{"t": "Proveedor"}, {"t": "Material"}, {"t": "Pedidos", "mono": True},
             {"t": "Pendiente", "num": True}, {"t": "Prometido", "num": True},
             {"t": "Retraso", "num": True}],
            [[str(x.get("proveedor", ""))[:26], str(x.get("material", ""))[:44],
              ", ".join(x.get("pedidos") or [])[:22] or "—",
              num(x.get("pendiente", 0)),
              _fecha(x.get("prometido")),
              {"v": f"{x.get('retraso', 0)} d", "color": rk.RED, "bold": True}]
             for x in retrasadas[:30]],
            vacio="Ninguna compra retrasada.")

    # ── Calidad ──────────────────────────────────────────────────────────────
    s = doc.seccion("Calidad", "no conformidades y equipos de medida")
    if nc_anios:
        s.barras("No conformidades por año",
                 f"{nc_st.get('total', 0)} en total · "
                 f"{nc_st.get('cliente', 0)} las detectó el cliente este año",
                 [str(r["anio"]) for r in nc_anios],
                 [{"label": "NC", "color": rk.ROSE, "valores": [r["n"] for r in nc_anios]}],
                 alto=240, ancho="half")
    try:
        tipos = quality.nc_by_type()[:8]
    except Exception:  # noqa: BLE001
        tipos = []
    if tipos:
        s.ranking("Por tipo", "las más repetidas",
                  [{"label": str(t[0])[:26], "valor": t[1], "texto": str(t[1]),
                    "color": rk.ROSE} for t in tipos])
    try:
        equipos = [e for e in quality.equipment() if e.get("vencido")]
    except Exception:  # noqa: BLE001
        equipos = []
    equipos.sort(key=lambda e: e.get("dias") if e.get("dias") is not None else 0)
    s.tabla("Equipos de medida con la calibración vencida",
            [{"t": "Código", "mono": True}, {"t": "Tipo"}, {"t": "Familia"},
             {"t": "Ubicación"}, {"t": "Vencía el", "num": True},
             {"t": "Hace", "num": True}],
            [[str(e.get("codigo", ""))[:22], str(e.get("tipo", ""))[:30],
              e.get("familia", ""), str(e.get("ubicacion", ""))[:22],
              e["proxima"].strftime("%d/%m/%Y") if e.get("proxima") else "—",
              {"v": f"{abs(e['dias'])} d" if e.get("dias") is not None else "—",
               "color": rk.RED, "bold": True}]
             for e in equipos[:25]],
            nota=f"{equipos_st.get('total', 0)} equipos en total · "
                 f"{equipos_st.get('pronto', 0)} caducan pronto",
            vacio="Ningún equipo con la calibración vencida.")

    # ── Almacén ──────────────────────────────────────────────────────────────
    s = doc.seccion("Almacén", "material avisado y pendiente de salir")
    try:
        snap = warehouse.snapshot()
        stock, buckets = snap.get("stock", []), snap.get("buckets", [])
    except Exception:  # noqa: BLE001
        stock, buckets = [], []
    s.kpis([
        {"valor": almacen_st.get("en_almacen", 0), "etiqueta": "Esperando salida",
         "color": rk.INK, "nota": "avisados y sin enviar"},
        {"valor": almacen_st.get("atascados", 0), "etiqueta": "Atascados",
         "color": rk.RED if almacen_st.get("atascados") else rk.GREEN,
         "nota": "llevan demasiado tiempo"},
        {"valor": f"{almacen_st.get('pct_semana', 0)}%", "etiqueta": "Salen en 7 días",
         "color": rk.color_pct(almacen_st.get("pct_semana", 0)),
         "nota": f"mediana {almacen_st.get('mediana', 0)} días"},
    ])
    if buckets:
        # Verde lo que sale en una semana, rojo lo que se queda parado un mes.
        tramos = [rk.GREEN, rk.GREEN, rk.AMBER, rk.AMBER, rk.RED, rk.RED]
        s.barras("Cuánto tarda el material en salir una vez avisado",
                 f"repartos de los últimos {almacen_st.get('enviados', 0)} envíos",
                 [b[0] for b in buckets],
                 [{"label": "Envíos", "color": tramos[:len(buckets)],
                   "valores": [b[1] for b in buckets]}], alto=240)
    s.tabla("Material en almacén",
            [{"t": "Pedido", "mono": True}, {"t": "Cliente"}, {"t": "Avisado", "num": True},
             {"t": "Días esperando", "num": True}],
            [[r.get("pedido", ""), str(r.get("cliente", ""))[:30], _fecha(r.get("aviso")),
              {"v": r.get("dias", 0),
               "color": rk.RED if r.get("dias", 0) > 30 else (
                   rk.AMBER if r.get("dias", 0) > 7 else rk.INK), "bold": True}]
             for r in stock[:25]],
            vacio="Nada esperando en almacén.")
    return doc


# ════════════════════════════════════════════════════════════════════════════
#  6 · EQUIPO
# ════════════════════════════════════════════════════════════════════════════

def equipo() -> rk.Report:
    carga = an.get_team_workload()
    overview = an.get_team_overview()
    matriz = an.get_matriz_comercial()
    eventos = an.doc_events()
    ritmo = an.get_actividad_por_responsable(8, eventos)

    doc = rk.Report(
        titulo="Carga y ritmo del equipo",
        subtitulo="Cuánta documentación lleva cada uno, cómo va y qué tiene pendiente.",
        etiqueta="Equipo", fuentes=_FUENTE_DOC)

    miembros = carga["members"]
    sobrecargados = [a["responsable"] for a in carga["alerts"]]
    pendientes = sum(w["n_pendientes"] for w in overview)
    doc.titular(
        f"El equipo tiene <b>{pendientes} documentos pendientes de trabajar</b> repartidos "
        f"entre {len(overview)} personas."
        + (f" {', '.join(sobrecargados)} van por encima de lo normal."
           if sobrecargados else ""),
        [f"La carga media son {dec(carga['avg_load'])} documentos por persona; el máximo, "
         f"{carga['max_load']}.",
         f"{sum(w['criticos'] for w in overview)} documentos críticos siguen sin aprobar."])

    # ── Carga ────────────────────────────────────────────────────────────────
    s = doc.seccion("Cómo está repartida la carga", "documentos por persona y en qué estado")
    s.barras("Cada barra es una persona: verde lo aprobado, ámbar lo devuelto",
             "documentos en seguimiento por responsable",
             [m["responsable"] for m in miembros],
             [{"label": "Aprobados", "color": rk.GREEN,
               "valores": [m["aprobados"] for m in miembros]},
              {"label": "Devoluciones", "color": rk.AMBER,
               "valores": [m["devoluciones"] for m in miembros]},
              {"label": "Sin enviar", "color": rk.GREY,
               "valores": [m.get("sin_enviar", 0) for m in miembros]}],
             apiladas=True, alto=280)
    media = carga["avg_load"]
    s.divergente(f"Quién está por encima y por debajo de la media ({dec(media)} documentos)",
                 "diferencia respecto a la carga media del equipo",
                 [{"label": m["responsable"], "valor": round(m["total"] - media, 1),
                   "color": rk.AMBER if m["total"] > media else rk.BLUE}
                  for m in sorted(miembros, key=lambda m: m["total"] - media)],
                 unidad=" docs")

    # ── Ritmo ────────────────────────────────────────────────────────────────
    if ritmo["responsables"]:
        s = doc.seccion("Ritmo de los últimos meses", "envíos mes a mes de cada persona")
        paleta = [rk.ACCENT, rk.BLUE, rk.GREEN, rk.AMBER, rk.ROSE, rk.RED]
        series = [{"label": r["responsable"], "color": paleta[i % len(paleta)],
                   "valores": r["valores"]}
                  for i, r in enumerate(ritmo["responsables"][:6])]
        s.linea("Quién está enviando y quién se ha parado",
                "documentos enviados por mes · en agosto la empresa cierra",
                ritmo["labels"], series, alto=280)

    # ── Ranking ──────────────────────────────────────────────────────────────
    s = doc.seccion("Rendimiento", "el acumulado de cada uno")
    s.tabla("Ranking",
            [{"t": "Responsable", "mono": True}, {"t": "Documentos", "num": True},
             {"t": "Aprobados", "num": True}, {"t": "% completado", "num": True},
             {"t": "Devoluciones", "num": True}, {"t": "Tasa devolución", "num": True},
             {"t": "Críticos", "num": True}],
            [[r["responsable"], r["total"], r["aprobados"],
              {"v": f"{r['pct']}%", "color": rk.color_pct(r["pct"]), "bold": True},
              r["devoluciones"],
              {"v": f"{r['tasa_devolucion']}%",
               "color": rk.AMBER if r["tasa_devolucion"] > 10 else rk.INK},
              {"v": r["criticos"] or "—", "color": rk.RED if r["criticos"] else rk.MUTED}]
             for r in sorted(miembros, key=lambda r: -r["pct"])])

    # ── Pendientes ───────────────────────────────────────────────────────────
    s = doc.seccion("Lo que tiene cada uno encima de la mesa", "documentos que piden acción")
    for w in overview:
        if not w["pendientes"]:
            continue
        s.tabla(f"{w['nombre']} · {w['n_pendientes']} pendientes",
                [{"t": "Documento", "mono": True}, {"t": "Título"}, {"t": "Cliente"},
                 {"t": "Estado"}, {"t": "Días", "num": True}],
                [[p["doc_eipsa"] or "—", str(p["titulo"])[:44], str(p["cliente"])[:24],
                  p["estado"], {"v": p["dias"] or "—",
                                "color": rk.color_dias(p["dias"]) if p["dias"] else rk.MUTED}]
                 for p in w["pendientes"][:12]],
                buscador=False)

    # ── Matriz ───────────────────────────────────────────────────────────────
    if matriz:
        s = doc.seccion("Comercial × responsable de documento", "% de aprobación por pareja")
        comerciales = sorted({r["comercial"] for r in matriz})
        resp = sorted({r["resp_doc"] for r in matriz})
        celda = {(r["comercial"], r["resp_doc"]): r for r in matriz}
        s.tabla("Matriz de aprobación",
                [{"t": "Comercial", "mono": True}] + [{"t": r, "num": True} for r in resp],
                [[com] + [
                    {"v": f"{celda[(com, r)]['pct']}%",
                     "color": rk.color_pct(celda[(com, r)]["pct"]), "bold": True}
                    if (com, r) in celda else {"v": "·", "color": rk.LINE}
                    for r in resp]
                 for com in comerciales],
                buscador=False,
                nota="Vacío significa que esa pareja no ha coincidido en ningún documento")
    return doc


# ════════════════════════════════════════════════════════════════════════════
#  Generación
# ════════════════════════════════════════════════════════════════════════════

_BUILDERS = {"pulso": pulso, "documentacion": documentacion, "clientes": clientes,
             "comercial": comercial, "operaciones": operaciones, "equipo": equipo}


def build(clave: str) -> rk.Report:
    if clave not in _BUILDERS:
        raise ValueError(f"Informe desconocido: {clave}")
    return _BUILDERS[clave]()


def reports_dir():
    d = state_dir() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _nombre_archivo(clave: str) -> str:
    return f"Analisis_{clave.capitalize()}_{datetime.now():%Y-%m-%d}.html"


def generate(clave: str):
    """Genera el informe y lo guarda. Devuelve (Path, Report)."""
    doc = build(clave)
    html = doc.render()
    path = reports_dir() / _nombre_archivo(clave)
    path.write_text(html, encoding="utf-8")
    logger.info("Informe de análisis generado: %s", path)
    return path, doc


def post_to_teams(clave: str) -> dict:
    """Publica el titular del informe en el canal, con sus cifras."""
    import re

    from core.services import teams

    doc = build(clave)
    limpio = re.sub(r"<[^>]+>", "", doc._titular)
    facts = []
    for punto in doc._puntos[:4]:
        texto = re.sub(r"<[^>]+>", "", punto).strip()
        if not texto:
            continue
        # Se parte por el primer verbo largo para que la tarjeta tenga pares
        # etiqueta/valor en vez de un párrafo corrido.
        facts.append((texto[:38] + ("…" if len(texto) > 38 else ""), ""))
    return teams.post_card(doc.titulo, doc.subtitulo, limpio,
                           [(t, v) for t, v in facts])


def send_email(clave: str, to: list[str] | None = None,
               cc: list[str] | None = None) -> dict:
    """Manda el informe por correo con el HTML adjunto, como los demás."""
    if not to:
        return {"status": "skipped", "reason": "Sin destinatarios"}
    from core.services.smtp import send_html_email

    doc = build(clave)
    html = doc.render()
    nombre = _nombre_archivo(clave)
    cuerpo = (
        '<div style="font-family:Segoe UI,Arial,sans-serif;color:#0F172A;font-size:14px;'
        'line-height:1.6">'
        "<p>Hola,</p>"
        f"<p>Adjunto el informe <b>{rk.esc(doc.titulo)}</b>: {rk.esc(doc.subtitulo)}</p>"
        + (f'<p style="border-left:3px solid #4F46E5;padding-left:12px;color:#1e293b">'
           f'{doc._titular}</p>' if doc._titular else "")
        + "<p>Ábrelo en el navegador: los gráficos y las tablas son interactivos y "
          "lleva un botón para guardarlo en PDF.</p>"
          '<p style="color:#94A3B8;font-size:12px">Generado automáticamente por DocFlow.</p>'
          "</div>")
    resultado = send_html_email(
        to=to, cc=cc or [], subject=f"{doc.titulo} — {datetime.now():%d/%m/%Y}",
        html_body=cuerpo, attachment_eml=html.encode("utf-8"), attachment_name=nombre)
    try:
        (reports_dir() / nombre).write_text(html, encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("No se pudo guardar la copia local del informe", exc_info=True)
    resultado["status"] = "sent"
    resultado["recipients"] = to
    return resultado
