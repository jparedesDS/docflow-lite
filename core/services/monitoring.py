"""MonitoringService LITE — merge data_erp + consulta_erp con columnas calculadas.

Port directo del servicio del DocFlow grande, sin dependencias de DB/Pydantic.
Genera la vista que consume la pantalla "Documentos" de la app Lite.
"""

import logging
import math
import os
import time
from datetime import date, datetime

import pandas as pd

from core.config import CONSULTA_ERP_PATH, DATA_ERP_PATH

logger = logging.getLogger(__name__)

CACHE_TTL = 60  # segundos


MONITORING_COLUMNS = [
    "Nº Pedido", "Responsable", "Nº Oferta", "Nº PO", "Cliente", "Material",
    "Fecha Pedido", "Fecha Prevista", "Nº Doc. Cliente", "Nº Doc. EIPSA",
    "Título", "Tipo Doc.", "Info/Review", "Repsonsable", "Días Envío",
    "Crítico", "Estado", "Nº Revisión", "Fecha Env. Doc.", "Días Devolución",
    "Seguimiento", "Historial Rev.",
]

# Columnas mostradas por defecto en la pantalla Documentos
VISIBLE_COLUMNS = [
    "Nº Pedido", "Nº Doc. EIPSA", "Título", "Cliente",
    "Repsonsable", "Tipo Doc.", "Crítico", "Info/Review",
    "Estado", "Nº Revisión", "Fecha Env. Doc.", "Días Devolución",
]


# ── Caché simple ──────────────────────────────────────────────────────────────

_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, builder, ttl: float = CACHE_TTL):
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    value = builder()
    _cache[key] = (now, value)
    return value


def invalidate_cache() -> None:
    _cache.clear()


def _read_excel(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        logger.warning("Archivo no encontrado: %s", path)
        return pd.DataFrame()
    return pd.read_excel(path, engine="openpyxl")


# ── Helpers de fechas ─────────────────────────────────────────────────────────

def _parse_date(val):
    if val is None or (isinstance(val, float) and math.isnan(val)) or val == "":
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    s = str(val).strip()
    if not s:
        return None
    head = s.split("T")[0] if "T" in s else s.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(head, fmt)
        except ValueError:
            continue
    return None


def _calc_dias_devolucion(row):
    estado = str(row.get("Estado", "")).lower().strip()
    if "aprobado" in estado:
        return 0
    fecha_env = row.get("Fecha Env. Doc.") or row.get("Fecha", "")
    d = _parse_date(fecha_env)
    if d:
        return (datetime.now() - d).days
    return ""


def _calc_dias_envio(row):
    existing = row.get("Días Envío")
    if existing not in ("", None) and not (isinstance(existing, float) and math.isnan(existing)):
        try:
            return int(float(existing))
        except (ValueError, TypeError):
            pass
    fecha_pedido = _parse_date(row.get("Fecha Pedido"))
    fecha_env = _parse_date(row.get("Fecha Env. Doc.") or row.get("Fecha"))
    if fecha_pedido and fecha_env:
        return (fecha_env - fecha_pedido).days
    if fecha_pedido:
        return (datetime.now() - fecha_pedido).days
    return ""


# ── API pública ───────────────────────────────────────────────────────────────

def get_monitoring_data(
    pedido: str = "",
    cliente: str = "",
    estado: str = "",
    responsable: str = "",
    query: str = "",
) -> list[dict]:
    """Devuelve la lista completa de documentos con columnas calculadas + filtros opcionales."""
    docs = _cached("merged", _build_merged_dataset)
    if not docs:
        return []

    rows = docs
    if pedido:
        rows = [r for r in rows if pedido.lower() in str(r.get("Nº Pedido", "")).lower()]
    if cliente:
        rows = [r for r in rows if cliente.lower() in str(r.get("Cliente", "")).lower()]
    if estado:
        rows = [r for r in rows if estado.lower() in str(r.get("Estado", "")).lower()]
    if responsable:
        rl = responsable.lower()
        rows = [
            r for r in rows
            if rl in str(r.get("Responsable", "")).lower()
            or rl in str(r.get("Repsonsable", "")).lower()
        ]
    if query:
        q = query.lower()
        rows = [r for r in rows if any(q in str(v).lower() for v in r.values())]
    return rows


def _build_merged_dataset() -> list[dict]:
    # Resolver paths efectivos (preferencias > default). Importar lazy para
    # evitar import circular en arranque temprano.
    from core import data_source
    data_path = data_source.get_effective_path("data_erp")
    consulta_path = data_source.get_effective_path("consulta_erp")

    data_df = _read_excel(data_path)
    if data_df.empty:
        return []
    consulta_df = _read_excel(consulta_path)

    # Merge con consulta_erp. Normalizamos Nº Pedido en ambos lados a string
    # uppercase + strip para tolerar variaciones de case (P-25/017-S00 vs
    # P-25/017-s00) y espacios accidentales.
    if not consulta_df.empty and "Nº Pedido" in consulta_df.columns:
        lookup_cols = ["Nº Pedido"]
        for col in ("Responsable", "Nº Oferta", "Fecha Pedido", "Fecha Prevista"):
            if col in consulta_df.columns:
                lookup_cols.append(col)
        lookup = consulta_df[lookup_cols].drop_duplicates(subset=["Nº Pedido"]).copy()

        # Clave normalizada para el join (no se queda en el resultado)
        data_df["_pedido_key"] = data_df["Nº Pedido"].astype(str).str.strip().str.upper()
        lookup["_pedido_key"] = lookup["Nº Pedido"].astype(str).str.strip().str.upper()
        lookup_no_pedido = lookup.drop(columns=["Nº Pedido"])
        data_df = data_df.merge(
            lookup_no_pedido, on="_pedido_key", how="left", suffixes=("", "_consulta"),
        )
        data_df.drop(columns=["_pedido_key"], inplace=True)

        # Aviso si el merge no produjo ningún match — suele significar que
        # consulta_erp es de un período distinto al de data_erp (o ruta vieja).
        for c in ("Responsable", "Nº Oferta"):
            if c in data_df.columns:
                n_filled = data_df[c].notna().sum()
                if n_filled == 0:
                    import logging as _logging
                    _logging.getLogger(__name__).warning(
                        "Merge con consulta_erp: columna %r quedó 100%% vacía. "
                        "Revisa que consulta_erp.xlsx cubra el rango de pedidos de "
                        "data_erp.xlsx (Centro de Reportes → Fuente de datos).", c,
                    )
                    break  # un solo warning basta
        for col in ("Fecha Pedido", "Fecha Prevista"):
            col_c = col + "_consulta"
            if col_c in data_df.columns:
                if col not in data_df.columns:
                    data_df[col] = data_df[col_c]
                else:
                    mask = data_df[col].isna() | (data_df[col].astype(str).str.strip() == "")
                    data_df.loc[mask, col] = data_df.loc[mask, col_c].values
                data_df.drop(columns=[col_c], inplace=True)

    # Renombrar Fecha → Fecha Env. Doc.
    if "Fecha" in data_df.columns and "Fecha Env. Doc." not in data_df.columns:
        data_df.rename(columns={"Fecha": "Fecha Env. Doc."}, inplace=True)

    # Columnas calculadas
    data_df["Días Devolución"] = data_df.apply(_calc_dias_devolucion, axis=1)
    data_df["Días Envío"] = data_df.apply(_calc_dias_envio, axis=1)

    # Reordenar
    final_cols = [c for c in MONITORING_COLUMNS if c in data_df.columns]
    extra = [c for c in data_df.columns if c not in final_cols]
    merged = data_df[final_cols + extra]

    # Excluir Eliminado
    if "Estado" in merged.columns:
        mask = ~merged["Estado"].astype(str).str.strip().str.lower().isin(
            ["eliminado", "deleted", "borrado"]
        )
        merged = merged[mask]

    result = merged.fillna("").to_dict(orient="records")
    for row in result:
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                row[k] = ""
    return result


def get_columns() -> list[str]:
    docs = _cached("merged", _build_merged_dataset)
    if not docs:
        return list(VISIBLE_COLUMNS)
    keys = list(docs[0].keys())
    return [c for c in MONITORING_COLUMNS if c in keys] + [c for c in keys if c not in MONITORING_COLUMNS]


# ── KPIs ──────────────────────────────────────────────────────────────────────

ESTADOS_DEVOLUCION = ("com. menores", "com. mayores", "rechazado", "comentado")


def _try_int(v) -> int | None:
    """Convierte un valor a int de forma tolerante. Devuelve None si no es posible."""
    try:
        return int(float(v)) if v not in (None, "", "nan") else None
    except (ValueError, TypeError):
        return None


def compute_kpis(docs: list[dict]) -> dict:
    total = len(docs)
    aprobados = enviados = devoluciones = criticos = sin_enviar = criticos_15d = 0
    dias_devolucion_vals: list[float] = []
    for d in docs:
        estado = str(d.get("Estado", "") or "").lower().strip()
        critico = str(d.get("Crítico", "") or "").lower().strip()
        es_critico = critico in ("sí", "si")

        if not estado or estado == "sin enviar":
            sin_enviar += 1
        elif estado == "enviado":
            enviados += 1
        elif any(s in estado for s in ESTADOS_DEVOLUCION):
            devoluciones += 1
            dd = _try_int(d.get("Días Devolución"))
            if dd is not None and dd > 0:
                dias_devolucion_vals.append(float(dd))

        if "aprobado" in estado:
            aprobados += 1

        # Crítico: excluye aprobados Y eliminados (alineado con DocFlow original)
        if es_critico and "aprobado" not in estado and "eliminado" not in estado:
            criticos += 1
            dd = _try_int(d.get("Días Devolución"))
            if dd is not None and dd >= 15:
                criticos_15d += 1

    pct = round(aprobados / total * 100, 1) if total > 0 else 0
    media_dias = round(sum(dias_devolucion_vals) / len(dias_devolucion_vals), 1) if dias_devolucion_vals else 0
    return {
        "total": total,
        "aprobados": aprobados,
        "enviados": enviados,
        "devoluciones": devoluciones,
        "criticos": criticos,
        "criticos_15d": criticos_15d,
        "sin_enviar": sin_enviar,
        "pct_completado": pct,
        "media_dias_devolucion": media_dias,
    }


# Filtros rápidos por KPI (devuelven una sub-lista del dataset)
def filter_by_kpi(docs: list[dict], kpi: str) -> list[dict]:
    if not kpi or kpi == "total":
        return docs
    out = []
    for d in docs:
        estado = str(d.get("Estado", "") or "").lower().strip()
        critico = str(d.get("Crítico", "") or "").lower().strip()
        es_critico = critico in ("sí", "si")

        if kpi == "aprobados" and "aprobado" in estado:
            out.append(d)
        elif kpi == "enviados" and estado == "enviado":
            out.append(d)
        elif kpi == "devoluciones" and any(s in estado for s in ESTADOS_DEVOLUCION):
            out.append(d)
        elif kpi == "sin_enviar" and (not estado or estado == "sin enviar"):
            out.append(d)
        elif kpi == "criticos" and es_critico and "aprobado" not in estado:
            out.append(d)
        elif kpi == "criticos_15d" and es_critico and "aprobado" not in estado:
            try:
                if int(float(d.get("Días Devolución", 0) or 0)) >= 15:
                    out.append(d)
            except (ValueError, TypeError):
                pass
    return out


def _normalize_pedido(pedido_raw: str) -> str:
    """Quita sufijos -S00/-S01/... para agrupar por pedido base."""
    import re
    return re.sub(r"(?i)-s\d{1,3}$", "", (pedido_raw or "").strip())


def get_status_global() -> list[dict]:
    """Agrupa documentos por Nº Pedido (sin suplemento) y calcula KPIs por pedido.

    Mismo formato que el método del DocFlow original — útil para el preview
    Status Global y para enriquecer datos del email ejecutivo.
    """
    from collections import defaultdict

    docs = get_monitoring_data()
    if not docs:
        return []

    pedidos = defaultdict(lambda: {
        "docs": [], "total": 0,
        "aprobados": 0, "pendientes": 0, "sin_enviar": 0,
        "reclamados": 0, "comentados": 0, "criticos": 0,
        "dias_max": 0, "suplementos": set(),
    })

    APROBADOS = ("aprobado",)
    RECLAMADOS = ("rechazado",)
    COMENTADOS = ("com. menores", "com. mayores", "comentado")

    for doc in docs:
        pedido_raw = str(doc.get("Nº Pedido", "") or "").strip() or "SIN PEDIDO"
        pedido = _normalize_pedido(pedido_raw)
        if pedido_raw != pedido:
            pedidos[pedido]["suplementos"].add(pedido_raw)

        estado = str(doc.get("Estado", "") or "").lower().strip()
        critico = str(doc.get("Crítico", "") or "").lower().strip()

        p = pedidos[pedido]
        p["docs"].append(doc)
        p["total"] += 1

        if not estado:
            p["sin_enviar"] += 1
        elif any(s in estado for s in APROBADOS):
            p["aprobados"] += 1
        elif any(s in estado for s in RECLAMADOS):
            p["reclamados"] += 1
        elif any(s in estado for s in COMENTADOS):
            p["comentados"] += 1
        else:
            p["pendientes"] += 1

        if critico in ("sí", "si"):
            p["criticos"] += 1

        d = _try_int(doc.get("Días Envío"))
        if d is not None and d > p["dias_max"]:
            p["dias_max"] = d

    result = []
    for pedido, data in pedidos.items():
        pct = round((data["aprobados"] / data["total"]) * 100) if data["total"] > 0 else 0
        first = data["docs"][0] if data["docs"] else {}
        suplementos = sorted(data["suplementos"])
        result.append({
            "pedido": pedido,
            "cliente": str(first.get("Cliente", "") or ""),
            "responsable": str(first.get("Repsonsable", "") or ""),
            "npo": str(first.get("Nº PO", "") or ""),
            "noferta": str(first.get("Nº Oferta", "") or ""),
            "material": str(first.get("Material", "") or ""),
            "total": data["total"],
            "aprobados": data["aprobados"],
            "pendientes": data["pendientes"],
            "sin_enviar": data["sin_enviar"],
            "reclamados": data["reclamados"],
            "comentados": data["comentados"],
            "criticos": data["criticos"],
            "pct_completado": pct,
            "dias_max": data["dias_max"],
            "suplementos": len(suplementos),
            "suplementos_detalle": suplementos,
        })

    result.sort(key=lambda x: (x["pct_completado"], -x["criticos"]))
    return result


def get_monitoring_report_sections() -> dict:
    """Devuelve los datos del monitoring divididos en secciones + KPIs.

    Usado por el generador de Excel multi-hoja.
    """
    docs = get_monitoring_data()
    if not docs:
        return {
            "all_docs": [], "enviados": [], "devoluciones": [],
            "criticos": [], "criticos_15d": [],
            "sin_enviar": [], "status_global": [], "kpis": {},
        }

    enviados, devoluciones, criticos, sin_enviar = [], [], [], []
    for doc in docs:
        estado = str(doc.get("Estado", "") or "").lower().strip()
        critico = str(doc.get("Crítico", "") or "").lower().strip()
        es_critico = critico in ("sí", "si")

        if not estado or estado == "sin enviar":
            sin_enviar.append(doc)
        elif estado == "enviado":
            enviados.append(doc)
        elif any(s in estado for s in ESTADOS_DEVOLUCION):
            devoluciones.append(doc)

        if es_critico and "aprobado" not in estado and "eliminado" not in estado:
            criticos.append(doc)

    criticos_15d = [
        d for d in criticos
        if _try_int(d.get("Días Devolución")) is not None
        and _try_int(d.get("Días Devolución")) >= 15
    ]

    kpis = compute_kpis(docs)
    from datetime import datetime as _dt
    kpis["generado"] = _dt.now().strftime("%d/%m/%Y %H:%M")

    return {
        "all_docs": docs,
        "enviados": enviados,
        "devoluciones": devoluciones,
        "criticos": criticos,
        "criticos_15d": criticos_15d,
        "sin_enviar": sin_enviar,
        "status_global": get_status_global(),
        "kpis": kpis,
    }


def file_status() -> dict:
    """Estado de los Excels (paths efectivos)."""
    from core import data_source
    data_path = data_source.get_effective_path("data_erp")
    consulta_path = data_source.get_effective_path("consulta_erp")
    return {
        "data_erp": {"path": data_path, "exists": os.path.exists(data_path)},
        "consulta_erp": {"path": consulta_path, "exists": os.path.exists(consulta_path)},
    }
