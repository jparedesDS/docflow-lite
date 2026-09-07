"""Equipos (tags), órdenes de fabricación y cabecera de pedido — desde el ERP.

Lectura SOLO-LECTURA del PostgreSQL local del ERP (misma conexión que erp_db):
  · tags_data.tags_flow / tags_temp / tags_level / tags_others → equipos del
    pedido (4 familias unificadas bajo una clave común en español).
  · fabrication.fab_order → órdenes de trabajo por equipo y plano (inicio/fin).
  · public.orders → cabecera de seguimiento (taller, entrega, material, aval…).

Sustituye a data_tags.xlsx (un export estático que solo cubría un pedido).
Nunca escribe en el ERP. Si el ERP no está disponible, `fetch_pedido_bundle`
devuelve available=False y la vista lo explica sin romperse.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from decimal import Decimal

from core.services import erp_db

logger = logging.getLogger(__name__)

CACHE_TTL = 120     # s — por pedido
PING_TTL = 60       # s — disponibilidad del ERP

_cache: dict[str, tuple[float, object]] = {}


def invalidate_cache() -> None:
    _cache.clear()


def _cached(key: str, builder, ttl: float):
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    value = builder()
    _cache[key] = (now, value)
    return value


# ── Familias y columnas comunes ───────────────────────────────────────────────

# tabla → (familia, columna tamaño, columna rating, columna facing, columna tipo)
_TABLES = {
    "tags_flow":   ("Caudal",      "line_size",      "rating",           "facing",           "item_type"),
    "tags_temp":   ("Temperatura", "size",           "rating",           "facing",           "item_type"),
    "tags_level":  ("Nivel",       "proc_conn_size", "proc_conn_rating", "proc_conn_facing", "item_type"),
    "tags_others": ("Otros",       None,             None,               None,               "description"),
}

# Columnas internas que no interesan al control documental (códigos de
# almacén, precios y facturación).
_EXCLUDE_PREFIXES = ("code_", "quant_", "trad_", "id_tag")
_EXCLUDE_COLS = {
    "min_price", "medium_price", "pvp_price", "notes_prices", "amount",
    "pos_fact", "subpos_fact", "amount_fact", "diff_amount", "box_br", "box_pl",
    "description_fact", "notes_fact", "invoice_number", "percent_invoiced",
}

# Etiquetas de caudal (las 121 columnas del antiguo data_tags.xlsx, tal cual
# las nombraba su fila descriptora). Muchas se comparten con temp/nivel/otros.
FLOW_LABELS = {
    "tag": "TAG", "tag_state": "Estado", "num_offer": "Nº Oferta", "num_order": "Nº Pedido",
    "num_po": "PO", "position": "Posición", "subposition": "Subposición", "item_type": "Tipo",
    "line_size": "Tamaño Línea", "rating": "Rating", "facing": "Facing", "schedule": "Schedule",
    "flange_material": "Mat. Brida", "flange_type": "Tipo Brida", "tube_material": "Mat. Tubo",
    "tapping_size": "Tamaño Tomas", "tapping_number": "Nº Tomas", "tapping_orientation": "Orient. Tomas",
    "element_material": "Mat. Elemento", "plate_type": "Tipo Placa", "plate_thk": "Esp. Placa",
    "plate_std": "Std Paca", "gasket_material": "Mat. Junta", "bolts_material": "Mat. Torn.",
    "nuts_material": "Mat. Tuercas", "valve_conn": "Con. Vlv.", "valve_material_body": "Mat. Cuerpo Vlv.",
    "stages_number": "Nº Saltos", "pipe_spec": "Pipe Spec.", "aprox_weight": "Peso (mm)",
    "aprox_length": "Long. (mm)", "nace": "NACE", "offer_notes": "Notas Oferta",
    "commercial_changes": "Cambios Com.", "contractual_date": "Fecha Contr.", "orif_diam": "øOrif. (mm)",
    "dv_diam": "øD/V (mm)", "gasket_quantity": "Cant. Juntas", "bolts_size": "Tamaño Torn.",
    "bolts_quantity": "Cant. Torn", "plug_material": "Mat. Tapón", "plug_quantity": "Cant. Tapón",
    "jack_screw_material": "Mat. Extractor", "jack_screw_size": "Tamaño Extractor",
    "jack_screw_quantity": "Cant. Extractor", "rtj_porta_material": "Mat. Porta RTJ",
    "rtj_thickness": "Espesor RTJ", "rtj_r_type": "Tipo RTJ", "notes_flange": "Notas Brida",
    "notes_stud": "Notas Tornillos", "notes_nuts": "Notas Tuercas", "notes_plate": "Notas Placa",
    "notes_gasket": "Notas Junta", "notes_plug": "Notas Tapones", "notes_jack_screw": "Notas Extractor",
    "pipe_int_diam": "øInt. Línea", "plate_ext_diam": "øExt. Placa", "plate_c_dim": "Cota C Placa",
    "handle_height": "Alto Mango", "handle_width": "Ancho Mango", "handle_thickness": "Espesor Mango",
    "rtj_p_diam": "Cota P RTJ", "rtj_e_dim": "Cota E RTJ", "rtj_f_dim": "Cota F RTJ",
    "o_flange": "O Brida", "a_flange": "A Brida", "c_flange": "C Brida", "y_flange": "Y Brida",
    "x_flange": "X Brida", "r_flange": "R Brida", "d_flange": "D Brida", "t_flange": "T Brida",
    "bore_bolts_diam": "øBore Torn.", "cones_material": "Mat. Conos Vent.", "a_venturi": "A Venturi",
    "d_venturi": "D Venturi", "e_venturi": "E Venturi", "f_venturi": "F Venturi",
    "g_venturi": "G Venturi", "c_venturi": "C Venturi", "h_venturi": "H Venturi", "t_venturi": "T Venturi",
    "technical_changes": "Cambios Tec.", "technical_notes": "Notas Tec.", "notes_equipment": "Notas Equipo",
    "calc_num_doc_eipsa": "Doc EIPSA Calc.", "dwg_num_doc_eipsa": "Doc EIPSA Plano",
    "purchase_order": "Orden de Compra", "purchase_order_date": "Fecha Orden Compra",
    "purchase_order_notes": "Notas Orden Compra", "dim_drawing": "Plano Dim.",
    "dim_drawing_rev": "Rev. Plano Dim.", "dim_drawing_date": "Fecha Plano Dim.", "of_drawing": "Plano OF",
    "of_drawing_rev": "Rev. Plano OF", "of_drawing_date": "Fecha Plano OF",
    "heat_number_plate": "Colada Placa", "cert_plate": "Cert. Placa", "heat_number_flange": "Colada Brida",
    "cert_flange": "Cert. Brida", "pmi_date": "Fecha PMI", "ph1_date": "Fecha PH1", "ph2_date": "Fecha PH2",
    "lp_date": "Fecha LP", "hard_date": "Fecha Dureza", "final_verif_dim_date": "Fecha Verif. Dim.",
    "final_verif_dim_state": "Estado Verif. Dim.", "final_verif_dim_obs": "Notas Verif. Dim",
    "final_verif_of_eq_date": "Fecha Verif. OF", "final_verif_of_eq_state": "Estado Verif. OF",
    "final_verif_of_eq_obs": "Notas Verif. OF", "tag_images": "Fotos", "tag_images2": "Fotos 2",
    "fab_state": "Estado Fab.", "inspection": "Inspeccion", "irc_date": "Fecha IRC",
    "rn_delivery": "Envío RN", "rn_date": "Fecha RN", "dim_drawing_path": "Ruta Dim.",
    "of_drawing_path": "Ruta OF",
}

# Etiquetas de temperatura / nivel / otros y detalle de inspección.
COMMON_LABELS = {
    # temperatura
    "tw_type": "Tipo TW", "size": "Tamaño", "std_tw": "Std TW", "material_tw": "Mat. TW",
    "std_length": "Long. Std", "ins_length": "Long. Inserción", "root_diam": "ø Raíz",
    "tip_diam": "ø Punta", "bore_diam": "ø Bore", "radius_dim": "Radio", "tip_thk": "Esp. Punta",
    "sensor_element": "Elemento Sensor", "wire_size": "Sección Cable", "sheath_stem_material": "Mat. Vaina",
    "sheath_stem_diam": "ø Vaina", "insulation": "Aislamiento", "temp_inf": "Temp. Inf.",
    "temp_sup": "Temp. Sup.", "nipple_ext_material": "Mat. Niple Ext.", "nipple_ext_length": "Long. Niple Ext.",
    "head_case_material": "Mat. Cabeza", "head_certification": "Cert. Cabeza",
    "elec_conn_case_diam": "Conex. Eléctrica", "tt_cerblock": "Bloque Cerámico",
    "material_flange_lj": "Mat. Brida LJ", "puntal": "Puntal", "tube_t": "Tubo T",
    "stress": "Stress", "geometry": "Geometría", "conical_length": "Long. Cónica",
    "straigth_length": "Long. Recta", "calculation_notes": "Notas Cálculo", "plug": "Tapón",
    "base_tw_diam": "ø Base TW", "notes_tw": "Notas TW", "notes_sensor": "Notas Sensor",
    "length_cut_tw": "Long. Corte TW", "dim_a_sensor": "Dim. A Sensor", "dim_b_sensor": "Dim. B Sensor",
    "dim_l_sensor": "Dim. L Sensor", "dwg_notes": "Notas Plano", "of_sensor_drawing": "Plano OF Sensor",
    "of_sensor_drawing_rev": "Rev. Plano OF Sensor", "of_sensor_drawing_date": "Fecha Plano OF Sensor",
    "heat_number_bar": "Colada Barra", "cert_bar": "Cert. Barra", "fab_sensor_state": "Estado Fab. Sensor",
    "fab_tw_state": "Estado Fab. TW", "final_verif_of_sensor_date": "Fecha Verif. OF Sensor",
    "final_verif_of_sensor_state": "Estado Verif. OF Sensor", "final_verif_of_sensor_obs": "Notas Verif. OF Sensor",
    "inspection_date": "Fecha Inspección", "equipment_state": "Estado Equipo", "item_quantity": "Cantidad",
    "paint_system": "Pintura", "material_certificate": "Cert. Material",
    # nivel
    "model_num": "Modelo", "body_material": "Mat. Cuerpo", "proc_conn_type": "Tipo Conex. Proceso",
    "proc_conn_size": "Tamaño Conex.", "proc_conn_rating": "Rating Conex.", "proc_conn_facing": "Facing Conex.",
    "conn_type": "Tipo Conexión", "visibility": "Visibilidad", "cc_length": "Long. C-C",
    "valve_type": "Tipo Válvula", "dv_conn": "Conex. D/V", "dv_size": "Tamaño D/V", "dv_rating": "Rating D/V",
    "dv_facing": "Facing D/V", "gasket_mica": "Junta / Mica", "stud_nuts_material": "Mat. Espárragos/Tuercas",
    "illuminator": "Iluminador", "float_material": "Mat. Flotador", "case_cover_material": "Mat. Caja/Tapa",
    "scale_type": "Tipo Escala", "flags": "Banderas", "ip_code": "IP", "nipple_hex": "Niple Hex.",
    "nipple_tub": "Niple Tubo", "antifrost": "Antihielo", "float_dim": "Dim. Flotador",
    "flange_gasket": "Junta Brida", "dwg_state": "Estado Plano", "dwg_state_date": "Fecha Estado Plano",
    "of_date": "Fecha OF", "heat_number_body": "Colada Cuerpo", "cert_body": "Cert. Cuerpo",
    "heat_number_body_vlv": "Colada Cuerpo Vlv.", "cert_body_vlv": "Cert. Cuerpo Vlv.",
    "heat_number_flange_vlv": "Colada Brida Vlv.", "cert_flange_vlv": "Cert. Brida Vlv.",
    # otros
    "description": "Descripción", "heat_number": "Colada", "cert_heat_number": "Cert. Colada",
    # detalle de inspección (todas las familias)
    "ph1_manometer": "Manómetro PH1", "ph1_pressure": "Presión PH1", "ph1_state": "Estado PH1",
    "ph1_obs": "Obs. PH1", "ph2_manometer": "Manómetro PH2", "ph2_pressure": "Presión PH2",
    "ph2_state": "Estado PH2", "ph2_obs": "Obs. PH2", "lp_hn_liq1": "LP Líquido 1",
    "lp_hn_liq2": "LP Líquido 2", "lp_hn_liq3": "LP Líquido 3", "lp_state": "Estado LP", "lp_obs": "Obs. LP",
    "hard_hardness": "Dureza", "hard_hardness_hb": "Dureza HB", "hard_ball": "Bola", "hard_force": "Fuerza",
    "hard_hn": "HN Dureza", "hard_state": "Estado Dureza", "hard_obs": "Obs. Dureza",
}


def label_for(col: str) -> str | None:
    """Etiqueta española de una columna del ERP (None si no interesa mostrarla)."""
    if col.startswith(_EXCLUDE_PREFIXES) or col in _EXCLUDE_COLS or col == "order_type_tag":
        return None
    return FLOW_LABELS.get(col) or COMMON_LABELS.get(col)


# ── Formato de valores ────────────────────────────────────────────────────────

def _fmt(v) -> str:
    """Valor del ERP → texto limpio ('' para nulos, fechas dd/mm/aaaa, sin '.0')."""
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, Decimal):
        return str(int(v)) if v == v.to_integral_value() else str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    s = str(v).strip()
    return "" if s.lower() in ("none", "nan", "null") else s


def _first(*vals) -> str:
    for v in vals:
        if v:
            return v
    return ""


# ── Disponibilidad ────────────────────────────────────────────────────────────

def is_available() -> bool:
    """¿Responde el Postgres local del ERP? Cacheado PING_TTL s; nunca lanza."""
    def ping():
        if not erp_db.is_configured():
            return False
        try:
            conn = erp_db._connect()
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1;")
                cur.fetchone()
                cur.close()
            finally:
                conn.close()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.info("ERP no disponible: %s", str(exc).splitlines()[0] if str(exc) else exc)
            return False
    return _cached("ping", ping, PING_TTL)


# ── Consultas ─────────────────────────────────────────────────────────────────

def _pedido_where(base: str) -> tuple[str, tuple]:
    """num_order exacto o con sufijo de suministro (-S00, -S01…)."""
    return "(num_order = %s OR num_order LIKE %s)", (base, f"{base}-S%")


def _query_tags(cur, base: str) -> list[dict]:
    out: list[dict] = []
    where, params = _pedido_where(base)
    for table, (familia, c_size, c_rating, c_facing, c_tipo) in _TABLES.items():
        cur.execute(f"SELECT * FROM tags_data.{table} WHERE {where} ORDER BY position, tag;", params)
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            raw = dict(zip(cols, row))
            rec: dict = {}
            for col, val in raw.items():
                lab = label_for(col)
                if lab:
                    rec[lab] = _fmt(val)
            rec.update({
                "Familia": familia,
                "TAG": _fmt(raw.get("tag")),
                "Nº Pedido": _fmt(raw.get("num_order")),
                "Tipo": _fmt(raw.get(c_tipo)),
                "Tamaño": _fmt(raw.get(c_size)) if c_size else "",
                "Rating": _fmt(raw.get(c_rating)) if c_rating else "",
                "Facing": _fmt(raw.get(c_facing)) if c_facing else "",
                "Estado": _fmt(raw.get("tag_state")),
                "Estado Fab.": _fmt(raw.get("fab_state")),
                "Inspección": _fmt(raw.get("inspection")),
                "Plano Dim.": _fmt(raw.get("dim_drawing")),
                "Rev. Plano Dim.": _fmt(raw.get("dim_drawing_rev")),
                "Plano OF": _fmt(raw.get("of_drawing")),
                "Doc EIPSA Calc.": _fmt(raw.get("calc_num_doc_eipsa")),
                "Doc EIPSA Plano": _fmt(raw.get("dwg_num_doc_eipsa")),
                "_tabla": table,
                "_order_type_tag": _fmt(raw.get("order_type_tag")),
                "_ots": [],
            })
            # Un mismo TAG aparece una vez por revisión: la antigua queda
            # SUPERADO y la actual PURCHASED / FOR INVOICING. Vigente = actual.
            state = rec["Estado"].upper()
            rec["_vigente"] = state not in ("SUPERADO", "DELETED")
            if state == "DELETED" or rec["Estado Fab."].upper() == "ELIMINADO":
                rec["_eliminado"] = True
            out.append(rec)
    return out


def _query_fab_orders(cur, base: str) -> list[dict]:
    cur.execute("""SELECT tag, element, qty_element, ot_num, qty_ot, start_date, end_date, type_equipment
                   FROM fabrication.fab_order WHERE tag = %s OR tag LIKE %s
                   ORDER BY start_date NULLS LAST, ot_num;""", (base, f"{base}-S%"))
    out = []
    for tag, element, qty, ot, qty_ot, start, end, teq in cur.fetchall():
        key, _, plano = str(tag or "").partition(" // ")
        out.append({
            "tag_key": key.strip(), "plano": plano.strip(), "elemento": _fmt(element),
            "cantidad": _fmt(qty), "ot": _fmt(ot), "cantidad_ot": _fmt(qty_ot),
            "inicio": _fmt(start), "fin": _fmt(end), "tipo_equipo": _fmt(teq),
            "terminada": end is not None,
        })
    return out


def _query_header(cur, base: str) -> dict:
    where, params = _pedido_where(base)
    cur.execute(f"""SELECT num_order, expected_date_workshop, recep_date_workshop, delivery_notification,
                           material_available, closed, warranty_bond, warranty_bond_state,
                           warranty_bond_expiring_date, porc_workshop, porc_assembly, porc_deliveries,
                           date_factory, last_date_deliveries, partial_date_deliveries, items_number
                    FROM public.orders WHERE {where} ORDER BY num_order LIMIT 1;""", params)
    row = cur.fetchone()
    if not row:
        return {}
    cols = [d[0] for d in cur.description]
    r = {c: _fmt(v) for c, v in zip(cols, row)}
    aval = r["warranty_bond"]
    if aval and r["warranty_bond_state"]:
        aval = f"{aval} · {r['warranty_bond_state']}"
    if aval and r["warranty_bond_expiring_date"]:
        aval = f"{aval} (vence {r['warranty_bond_expiring_date']})"
    return {
        "Prev. taller": r["expected_date_workshop"],
        "Recep. taller": r["recep_date_workshop"],
        "Aviso entrega": r["delivery_notification"],
        "Material disponible": r["material_available"],
        "Aval": aval,
        "Cerrado": r["closed"],
        "_raw": r,
    }


def _attach_fab_orders(tags: list[dict], fab_orders: list[dict]) -> None:
    """Engancha a cada tag sus OTs (por order_type_tag). Las OTs del pedido
    (clave sin equipo) quedan disponibles como 'generales'."""
    by_key: dict[str, list[dict]] = {}
    for fo in fab_orders:
        by_key.setdefault(fo["tag_key"], []).append(fo)
    for t in tags:
        key = t.get("_order_type_tag") or ""
        ots = by_key.get(key, []) if key else []
        t["_ots"] = ots
        abiertas = sum(1 for o in ots if not o["terminada"])
        cerradas = len(ots) - abiertas
        t["_ot_abiertas"], t["_ot_cerradas"] = abiertas, cerradas
        t["OTs"] = (f"{cerradas}/{len(ots)} terminadas" if ots else "")


def fetch_pedido_bundle(pedido: str) -> dict:
    """Todo lo que Seguimiento necesita del ERP para un pedido (base o con -Sxx).

    Returns {available, tags, fab_orders, fab_generales, header}. Cacheado.
    """
    base = _base_pedido(pedido)
    if not base:
        return {"available": False, "tags": [], "fab_orders": [], "fab_generales": [], "header": {}}

    def build():
        if not is_available():
            return {"available": False, "tags": [], "fab_orders": [], "fab_generales": [], "header": {}}
        conn = erp_db._connect()
        try:
            cur = conn.cursor()
            cur.execute("SET statement_timeout = 20000;")
            tags = _query_tags(cur, base)
            fab = _query_fab_orders(cur, base)
            header = _query_header(cur, base)
            cur.close()
        finally:
            conn.close()
        _attach_fab_orders(tags, fab)
        keys = {t.get("_order_type_tag") for t in tags}
        generales = [o for o in fab if o["tag_key"] not in keys]
        return {"available": True, "tags": tags, "fab_orders": fab,
                "fab_generales": generales, "header": header}

    try:
        return _cached(f"bundle::{base}", build, CACHE_TTL)
    except Exception as exc:  # noqa: BLE001 — la vista degrada, nunca rompe
        logger.warning("ERP tags/OTs de %s: %s", base, str(exc).splitlines()[0] if str(exc) else exc)
        return {"available": False, "tags": [], "fab_orders": [], "fab_generales": [], "header": {},
                "error": str(exc).splitlines()[0] if str(exc) else repr(exc)}


def fetch_tags(pedido: str) -> list[dict]:
    return fetch_pedido_bundle(pedido)["tags"]


def _base_pedido(p) -> str:
    p = str(p or "").strip()
    return p[:-4] if len(p) > 4 and p[-4:-2].upper() == "-S" and p[-2:].isdigit() else p
