"""Parser para Técnicas Reunidas (EGESDOC) — egesdoc@grupotr.es
   Formato: tabla HTML en posición [5] con columnas:
   Vendor Number, TR Number, Title, Vendor Rev, TR Rev, Return Status
"""
import re
import pandas as pd
from io import StringIO
from core.parsers.base_parser import (
    DOC_TYPE_MAP, apply_critico, fill_supp_nulls, apply_fecha, FINAL_COLUMNS,
    identify_client, get_responsable_initials,
)

SENDER_MATCH = "egesdoc@grupotr.es"

# Status mapping específico de Técnicas Reunidas
TR_STATUS_MAP = {
    "A - REJECTED": "Rechazado",
    "B - REVIEWED WITH MAJOR COMMENTS": "Com. Mayores",
    "C - REVIEWED WITH MINOR COMMENTS": "Com. Menores",
    "F - REVIEWED WITHOUT COMMENTS": "Aprobado",
    "F - ACCEPTED WITHOUT COMMENTS": "Aprobado",
    "W - ISSUED FOR CERTIFICATION": "Certificación",
    "M - VOID": "Eliminado",
    "R - REVIEWED AS BUILT": "Aprobado",
}

# Material por últimos 3 dígitos del PO
TR_MATERIAL_MAP = {
    "411": "TEMPERATURA", "412": "TEMPERATURA",
    "610": "BIMETÁLICOS", "620": "TEMPERATURA",
    "640": "TEMPERATURA", "710": "NIVEL VIDRIO",
    "740": "TUBERÍAS", "910": "CAUDAL",
    "911": "SALTOS MULTIPLES", "920": "ORIFICIOS",
    "960": "ORIFICIOS", "010": "VALVULAS",
}

# Reemplazos de título
TITLE_REPLACEMENTS = {
    "SPECIFICATIONS AND TECHNICAL DATA": "CÁLCULOS Y PLANOS -",
    "OVERALL DRAWING WITH PRINCIPAL DIMENSIONS AND WEIGHTS": "PLANOS DIMENSIONALES",
    "EQUIPMENT CALCULATION SHEETS": "HOJAS DE CÁLCULOS",
}


def can_parse(sender: str) -> bool:
    return SENDER_MATCH in sender.lower()


def extract_transmittal_code(subject: str) -> str | None:
    # PO de 10 dígitos del subject
    m = re.search(r"(\d{10})", subject)
    return m.group(0) if m else None


def parse(html_body: str, subject: str, received_time: str) -> pd.DataFrame:
    df_list = pd.read_html(StringIO(html_body))

    # La tabla de datos suele estar en posición [5], pero buscamos la que tenga
    # la columna "Vendor Number" por robustez
    df = None
    for candidate in df_list:
        cols_lower = [str(c).lower() for c in candidate.columns]
        if any("vendor number" in c for c in cols_lower):
            df = candidate.copy()
            break

    if df is not None and isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(s) for s in col if str(s) != "nan").strip()
                      for col in df.columns]

    # Fallback: posición [5]
    if df is None:
        if len(df_list) > 5:
            df = df_list[5].copy()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [" ".join(str(s) for s in col if str(s) != "nan").strip()
                              for col in df.columns]
        else:
            raise ValueError(f"Email EGESDOC: no se encontró tabla con 'Vendor Number'. Tablas disponibles: {len(df_list)}")

    # Seleccionar columnas esperadas
    expected = ["Vendor Number", "TR Number", "Title", "Vendor Rev", "TR Rev", "Return Status"]
    available = [c for c in expected if c in df.columns]
    if not available:
        raise ValueError(f"Email EGESDOC: columnas no coinciden. Encontradas: {list(df.columns)}")
    df = df[available].copy()

    # Filtrar filas sin datos reales (cabeceras duplicadas, separadores vacíos del HTML)
    # Usamos TR Number como columna clave (es el Doc. Cliente)
    key_col = "TR Number" if "TR Number" in df.columns else (available[0] if available else None)
    if key_col:
        col_names_set = set(str(c).strip() for c in df.columns)
        df = df[df[key_col].notna()].copy()
        df = df[df[key_col].astype(str).str.strip().str.len() > 0].copy()
        df = df[df[key_col].astype(str).str.strip() != "nan"].copy()
        # Eliminar filas donde el valor coincide con un nombre de columna (cabeceras repetidas)
        df = df[~df[key_col].astype(str).str.strip().isin(col_names_set)].copy()
    df = df.reset_index(drop=True)

    # Doc type code: primer grupo de letras del Vendor Number
    if "Vendor Number" in df.columns:
        df["_doc_code"] = df["Vendor Number"].str.extract(r"-([A-Za-z#&]+)-", expand=False)
        df["Tipo de documento"] = df["_doc_code"].map(DOC_TYPE_MAP)

        # Suplemento: extraer S00, S01, etc del Vendor Number
        df["Supp."] = df["Vendor Number"].str.extract(r"([S]+\d+)", expand=False)

        # Nº Pedido: extraer patrón XX-YYY → P-XX/YYY
        df["Nº Pedido"] = df["Vendor Number"].str.extract(r"(\d+-\d+)", expand=False)
        df["Nº Pedido"] = df["Nº Pedido"].str.replace("-", "/")
        df["Nº Pedido"] = "P-" + df["Nº Pedido"].astype(str)

        df["Doc. EIPSA"] = df["Vendor Number"]
    else:
        df["_doc_code"] = ""
        df["Tipo de documento"] = ""
        df["Supp."] = "S00"
        df["Nº Pedido"] = ""
        df["Doc. EIPSA"] = ""

    # PO del subject (10 dígitos)
    po_match = re.search(r"(\d{10})", subject)
    po = po_match.group(0) if po_match else ""
    df["PO"] = po

    # Material: últimos 3 dígitos del PO
    if po and len(po) >= 3:
        last3 = po[-3:]
        df["Material"] = TR_MATERIAL_MAP.get(last3, po)
    else:
        df["Material"] = ""

    # TR Number → Doc. Cliente
    if "TR Number" in df.columns:
        df["Doc. Cliente"] = df["TR Number"]
    else:
        df["Doc. Cliente"] = ""

    # Title → Título (con reemplazos)
    if "Title" in df.columns:
        def replace_title(text):
            if not isinstance(text, str):
                return text
            for k, v in TITLE_REPLACEMENTS.items():
                if k in text:
                    return text.replace(k, v)
            return text
        df["Título"] = df["Title"].apply(replace_title)
    else:
        df["Título"] = ""

    # Rev
    if "Vendor Rev" in df.columns:
        df["Rev."] = df["Vendor Rev"]
    else:
        df["Rev."] = ""

    # Status
    if "Return Status" in df.columns:
        df["Estado"] = df["Return Status"].map(TR_STATUS_MAP).fillna(df["Return Status"])
    else:
        df["Estado"] = ""

    # Cliente: primeros 5 dígitos del PO
    df["Cliente"] = identify_client(po)

    # Responsable: iniciales por Nº Pedido
    if "Nº Pedido" in df.columns:
        df["Responsable"] = df["Nº Pedido"].apply(lambda x: get_responsable_initials(str(x)))
    else:
        df["Responsable"] = ""

    df["Nº Transmittal"] = po

    fill_supp_nulls(df)
    apply_critico(df)
    apply_fecha(df, received_time)

    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[FINAL_COLUMNS].copy()
