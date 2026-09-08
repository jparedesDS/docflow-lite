"""Lectura SOLO-LECTURA del PostgreSQL local del ERP EIPSA.

El ERP (EIPSA-ERP_CLOUD.exe) ejecuta su PostgreSQL en la propia máquina
(`localhost:5432`). Este servicio se conecta en modo *read only* y regenera
`consulta_erp` (Nº Pedido, Nº Oferta, Responsable en iniciales, fechas, cliente…)
desde `public.orders` ⨝ `public.offers` ⨝ `users_data.initials`. **Nunca escribe
en el ERP.**

Conexión (sin credenciales en el código):
  · host      → preferencia ``erp_db_host`` (default ``127.0.0.1``; el host del
                database.ini antiguo, 10.1.20.252, está muerto).
  · database/user → preferencias ``erp_db_name`` / ``erp_db_user`` o el
                ``database.ini`` del ERP.
  · password  → almacén de secretos (``erp_db_pass``) → ``database.ini``.
  · database.ini → preferencia ``erp_db_ini`` (default el del share del ERP).
"""

from __future__ import annotations

import configparser
import logging
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from core import credentials
from core import preferences

logger = logging.getLogger(__name__)

DEFAULT_INI = r"M:\Comunes\EIPSA-ERP\00 BASE DE DATOS\ERP EIPSA\database.ini"
DEFAULT_HOST = "127.0.0.1"

# Columnas de consulta_erp (orden del export original del ERP).
CONSULTA_COLUMNS = [
    "Nº Pedido", "Nº Oferta", "Año", "Responsable", "Fecha Pedido",
    "Fecha Prevista", "Nº Referencia", "Cliente", "Cl. Final / Planta",
    "Proyecto", "Tipo Equipo", "Nº Equipos", "Notas Pedido", "Importante Oferta",
    "F. Creación Líneas", "F. Act. Líneas/Portal", "Fecha Fabricación",
    "% Fabricación", "Obs. Fabricación", "Fecha Montaje", "% Montaje",
    "Obs. Montaje", "Fecha Envío", "% Envío", "Obs. Envío",
]

# Responsable ya viene resuelto a iniciales (LB, AC, LM…) por el join con
# users_data.initials. "No hay datos" → vacío.
_SQL_CONSULTA = """
    SELECT o.num_order                       AS "Nº Pedido",
           o.num_offer                       AS "Nº Oferta",
           o.order_year                      AS "Año",
           CASE WHEN i.initials IS NULL OR i.initials = 'No hay datos'
                THEN '' ELSE i.initials END  AS "Responsable",
           o.order_date                      AS "Fecha Pedido",
           o.expected_date                   AS "Fecha Prevista",
           o.num_ref_order                   AS "Nº Referencia",
           f.client                          AS "Cliente",
           f.final_client                    AS "Cl. Final / Planta",
           f.project                         AS "Proyecto",
           f.material                        AS "Tipo Equipo",
           o.items_number                    AS "Nº Equipos",
           o.notes                           AS "Notas Pedido",
           f.important                       AS "Importante Oferta",
           o.lines_creation_date             AS "F. Creación Líneas",
           o.lines_activation_date           AS "F. Act. Líneas/Portal",
           o.date_factory                    AS "Fecha Fabricación",
           o.porc_workshop                   AS "% Fabricación",
           o.obs_workshop                    AS "Obs. Fabricación",
           o.porc_assembly                   AS "% Montaje",
           o.obs_assembly                    AS "Obs. Montaje",
           o.last_date_deliveries            AS "Fecha Envío",
           o.porc_deliveries                 AS "% Envío",
           o.obs_deliveries                  AS "Obs. Envío"
    FROM public.orders o
    LEFT JOIN public.offers f        ON f.num_offer = o.num_offer
    LEFT JOIN users_data.initials i  ON lower(i.username) = lower(f.responsible)
    ORDER BY o.num_order
"""


# Columnas de data_erp (documentos), en el orden del export original del ERP.
DATA_COLUMNS = [
    "Nº Pedido", "Fecha Pedido", "Fecha Prevista", "Nº PO", "Cliente", "Material",
    "Nº Doc. Cliente", "Nº Doc. EIPSA", "Título", "Tipo Doc.", "Crítico",
    "Info/Review", "Días Envío", "Repsonsable", "Estado", "Nº Revisión",
    "Fecha", "Seguimiento", "Historial Rev.",
]

# Documentos + cabecera del pedido. `Repsonsable` conserva el typo del export
# original (es el responsable del DOCUMENTO, distinto del comercial de la consulta).
_SQL_DATA = """
    SELECT d.num_order                       AS "Nº Pedido",
           o.order_date                      AS "Fecha Pedido",
           o.expected_date                   AS "Fecha Prevista",
           o.num_ref_order                   AS "Nº PO",
           f.client                          AS "Cliente",
           p.variable                        AS "Material",
           d.num_doc_client                  AS "Nº Doc. Cliente",
           d.num_doc_eipsa                   AS "Nº Doc. EIPSA",
           d.doc_title                       AS "Título",
           t.doc_type                        AS "Tipo Doc.",
           d.critical                        AS "Crítico",
           d.review_info                     AS "Info/Review",
           d.sending_days                    AS "Días Envío",
           d.doc_responsible                 AS "Repsonsable",
           d.state                           AS "Estado",
           d.revision                        AS "Nº Revisión",
           d.state_date                      AS "Fecha",
           d.tracking                        AS "Seguimiento",
           h.hist_rev_column                 AS "Historial Rev."
    FROM public.documentation d
    LEFT JOIN public.orders o        ON o.num_order = d.num_order
    LEFT JOIN public.offers f        ON f.num_offer = o.num_offer
    LEFT JOIN public.document_type t ON t.id = d.doc_type_id
    LEFT JOIN public.product_type p  ON p.material = f.material
    LEFT JOIN public.hist_doc h      ON h.num_doc_eipsa = d.num_doc_eipsa
                                    AND coalesce(d.num_doc_eipsa, '') <> ''
    ORDER BY d.num_order, d.num_doc_eipsa
"""


# ── Configuración de conexión ─────────────────────────────────────────────────

def _read_ini() -> dict:
    path = preferences.get("erp_db_ini") or DEFAULT_INI
    out: dict = {}
    try:
        if Path(path).exists():
            cp = configparser.ConfigParser()
            cp.read(path)
            if cp.has_section("postgresql"):
                out = dict(cp["postgresql"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("No se pudo leer database.ini (%s): %s", path, exc)
    return out


def _conn_params() -> dict:
    ini = _read_ini()
    host = preferences.get("erp_db_host") or DEFAULT_HOST
    dbname = preferences.get("erp_db_name") or ini.get("database", "ERP_EIPSA")
    user = preferences.get("erp_db_user") or ini.get("user", "")
    password = credentials.get("erp_db_pass", env_fallback="ERP_DB_PASS") or ini.get("password", "")
    return {"host": host, "dbname": dbname, "user": user, "password": password}


def is_configured() -> bool:
    p = _conn_params()
    return bool(p["dbname"] and p["user"] and p["password"])


def _connect():
    import psycopg2  # import perezoso: la app funciona sin el ERP disponible

    params = _conn_params()
    conn = psycopg2.connect(connect_timeout=6, **params)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def test_connection() -> tuple[bool, str]:
    """(ok, mensaje). No modifica nada."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT current_database(), count(*) FROM public.orders;")
        db, n = cur.fetchone()
        cur.close(); conn.close()
        return True, f"Conectado a {db} · {n} pedidos"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc).splitlines()[0] if str(exc) else repr(exc)


# ── Lectura ───────────────────────────────────────────────────────────────────

def fetch_consulta_df() -> pd.DataFrame:
    """DataFrame con el equivalente a consulta_erp, Responsable en iniciales."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = 30000;")
        cur.execute(_SQL_CONSULTA)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=cols)
    for c in CONSULTA_COLUMNS:
        if c not in df.columns:
            df[c] = ""            # p.ej. "Fecha Montaje": sin origen en el ERP
    return df[CONSULTA_COLUMNS]


def _fmt_date(value) -> str:
    """Fechas del ERP al formato del export (DD-MM-YYYY); el resto, tal cual."""
    if value is None or value == "":
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d-%m-%Y")
    return str(value)


def fetch_data_erp_df() -> pd.DataFrame:
    """DataFrame con el equivalente a data_erp (documentos + cabecera del pedido)."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = 60000;")
        cur.execute(_SQL_DATA)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=cols)
    for c in ("Fecha Pedido", "Fecha Prevista"):
        if c in df.columns:
            df[c] = df[c].map(_fmt_date)
    for c in DATA_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[DATA_COLUMNS].reset_index(drop=True)


def _write_xlsx(df: pd.DataFrame, target: Path, make_backup: bool) -> str | None:
    """Vuelca el DataFrame a `target` de forma atómica (tmp + replace) y devuelve
    la ruta del backup si se hizo."""
    backup = None
    if make_backup and target.exists():
        backup = target.with_name(f"{target.stem}.backup-{datetime.now():%Y%m%d_%H%M%S}{target.suffix}")
        shutil.copy2(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Escritura atómica: tmp + replace, para que el refresco no deje al lector
    # (Documentos/reportes) con un fichero a medio escribir.
    tmp = target.with_name(f"{target.stem}.tmp-{datetime.now():%H%M%S}{target.suffix}")
    df.to_excel(tmp, index=False, engine="openpyxl")
    import os
    os.replace(tmp, target)
    try:
        from core.services import monitoring
        monitoring.invalidate_cache()      # el cambio se ve sin reiniciar
    except Exception:  # noqa: BLE001
        pass
    return str(backup) if backup else None


def refresh_data_erp(dest: str | None = None, make_backup: bool = True) -> dict:
    """Regenera data_erp.xlsx (documentos) desde el ERP. Read-only sobre el DB.

    Returns dict {rows, path, backup}.
    """
    from core import data_source

    df = fetch_data_erp_df()
    target = Path(dest) if dest else Path(data_source.get_effective_path("data_erp"))
    backup = _write_xlsx(df, target, make_backup)
    logger.info("data_erp regenerado: %d documentos -> %s", len(df), target)
    return {"rows": len(df), "path": str(target), "backup": backup}


def refresh_consulta_erp(dest: str | None = None, make_backup: bool = True) -> dict:
    """Regenera consulta_erp.xlsx desde el ERP. Read-only sobre el DB.

    make_backup=True crea una copia .backup-<ts> del fichero anterior (para el
    botón manual). El refresco automático (cada hora) usa make_backup=False para
    no acumular decenas de backups al día.

    Returns dict {rows, path, backup, con_responsable, con_oferta}.
    """
    from core import data_source

    df = fetch_consulta_df()
    target = Path(dest) if dest else Path(data_source.get_effective_path("consulta_erp"))
    backup = _write_xlsx(df, target, make_backup)

    resp = int((df["Responsable"].astype(str).str.strip() != "").sum())
    ofe = int((df["Nº Oferta"].astype(str).str.strip() != "").sum())
    logger.info("consulta_erp regenerado: %d pedidos (%d resp, %d oferta) -> %s",
                len(df), resp, ofe, target)
    return {
        "rows": len(df), "path": str(target), "backup": backup,
        "con_responsable": resp, "con_oferta": ofe,
    }


def refresh_all(make_backup: bool = True) -> dict:
    """Regenera los DOS ficheros desde el ERP: documentos (data_erp) y pedidos
    (consulta_erp). Devuelve {data: {...}, consulta: {...}}."""
    return {"data": refresh_data_erp(make_backup=make_backup),
            "consulta": refresh_consulta_erp(make_backup=make_backup)}


def auto_refresh() -> bool:
    """Refresco silencioso para el scheduler (al arrancar y cada hora).

    Nunca lanza: si el ERP está cerrado o el Postgres local no responde, lo
    registra y sigue (la app funciona con los Excel que ya haya en disco).
    """
    try:
        if not is_configured():
            logger.info("ERP: refresco omitido (sin configuración de conexión)")
            return False
        res = refresh_all(make_backup=False)
        logger.info("ERP: refrescado — %d documentos, %d pedidos",
                    res["data"]["rows"], res["consulta"]["rows"])
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).splitlines()[0] if str(exc) else repr(exc)
        logger.warning("ERP: refresco automático falló (¿ERP/Postgres cerrado?): %s", msg)
        return False
