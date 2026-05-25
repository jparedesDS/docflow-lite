import re
import pandas as pd
from io import StringIO
from core.parsers.base_parser import (
    SENDOC_PO_MAP, SENDOC_MATERIAL_MAP, SENDOC_STATUS_MAP,
    DOC_TYPE_MAP, apply_critico, fill_supp_nulls, apply_fecha, FINAL_COLUMNS,
    identify_client, get_responsable_initials, lookup_erp, lookup_erp_by_npo,
)

SENDER_MATCH = "adminsendoc@corporate.sener"
TRANSMITTAL_REGEX = r"([A-Z0-9]+(?:-[A-Z0-9]+)+)"
DOC_TYPE_KEYWORDS = r"(DRAWINGS|LIST|VDDL|IND|DOS|ITP|NDE|CER|PH|DD|WD)"


def can_parse(sender: str) -> bool:
    return SENDER_MATCH in sender.lower()


def extract_transmittal_code(subject: str) -> str | None:
    m = re.search(TRANSMITTAL_REGEX, subject)
    return m.group(0) if m else None


def parse(html_body: str, subject: str, received_time: str) -> pd.DataFrame:
    df_list = pd.read_html(StringIO(html_body))
    if len(df_list) < 2:
        raise ValueError("Email SENDOC no contiene las tablas esperadas")

    # SENDOC: tablas [0] y [1] son key-value pairs, se transponen y concatenan
    df0 = df_list[0].set_index(df_list[0].columns[0]).T
    df1 = df_list[1].set_index(df_list[1].columns[0]).T
    df0.index = [0]
    df1.index = [0]
    df = pd.concat([df0, df1], axis=1)
    # Normalizar nombres de columna: eliminar espacios extra
    df.columns = df.columns.str.strip()

    transmittal_code = extract_transmittal_code(subject)

    # ProcessFlow → Nº Pedido y Supp. (separando sufijo -Sxx del mapping)
    if "ProcessFlow" in df.columns:
        process_flow = str(df["ProcessFlow"].iloc[0]).strip()
        df["PO"] = process_flow
        raw_mapped = SENDOC_PO_MAP.get(process_flow, process_flow)
        supp_match = re.search(r'-(S\d{2})$', raw_mapped)
        if supp_match:
            df["Nº Pedido"] = raw_mapped[:supp_match.start()]
            df["Supp."] = supp_match.group(1)
        else:
            df["Nº Pedido"] = raw_mapped
            df["Supp."] = "S00"
    else:
        df["Nº Pedido"] = ""
        df["PO"] = ""
        df["Supp."] = "S00"

    # Purchase Order del email → sobreescribe PO si está disponible
    if "Purchase Order" in df.columns:
        po_raw = str(df["Purchase Order"].iloc[0]).split("(")[0].strip()
        if po_raw and po_raw != "nan":
            df["PO"] = po_raw

    # Fallback: si Nº Pedido no resuelto por SENDOC_PO_MAP, buscar por Purchase Order en ERP
    po_value = str(df["PO"].iloc[0]).strip() if len(df) > 0 else ""
    erp_by_npo = lookup_erp_by_npo(po_value) if po_value and po_value != "nan" else {}
    if erp_by_npo.get("Nº Pedido"):
        n_pedido_erp = erp_by_npo["Nº Pedido"]
        supp_match = re.search(r'-(S\d{2})$', n_pedido_erp)
        if supp_match:
            df["Nº Pedido"] = n_pedido_erp[:supp_match.start()]
            df["Supp."] = supp_match.group(1)
        else:
            df["Nº Pedido"] = n_pedido_erp

    # Doc type from Title
    if "Title" in df.columns:
        df["_doc_code"] = df["Title"].str.extract(DOC_TYPE_KEYWORDS, expand=False)
        df["Tipo de documento"] = df["_doc_code"].map(DOC_TYPE_MAP)
        df["Título"] = df["Title"]
    elif "Doc. Title" in df.columns:
        df["_doc_code"] = df["Doc. Title"].str.extract(DOC_TYPE_KEYWORDS, expand=False)
        df["Tipo de documento"] = df["_doc_code"].map(DOC_TYPE_MAP)
        df["Título"] = df["Doc. Title"]
    else:
        df["Tipo de documento"] = ""
        df["Título"] = ""

    # Columna documento: acepta varios nombres de columna
    ref_col = None
    for candidate_col in ("Reference", "Document number", "Doc. Number", "Document No"):
        if candidate_col in df.columns:
            ref_col = candidate_col
            break

    if ref_col:
        df["Doc. EIPSA"] = df[ref_col]
        df["Doc. Cliente"] = df[ref_col]
    else:
        df["Doc. EIPSA"] = ""
        df["Doc. Cliente"] = ""

    # Rev — buscar con variantes de nombre (capitalización diferente)
    rev_col = next((c for c in df.columns if c.strip().lower() == "system revision"), None)
    if rev_col:
        df["Rev."] = df[rev_col]
    else:
        df["Rev."] = ""

    # Status via Step
    if "Step" in df.columns:
        df["Estado"] = df["Step"].map(SENDOC_STATUS_MAP).fillna(df["Step"])
    else:
        df["Estado"] = ""

    # Material, Cliente y Responsable via ERP / mappings
    n_pedido = df["Nº Pedido"].iloc[0] if len(df) > 0 else ""
    erp_data = lookup_erp(n_pedido)

    # Si lookup por Nº Pedido no devuelve datos, usar los del lookup por Nº PO
    if not erp_data and erp_by_npo:
        erp_data = erp_by_npo

    # Material: ERP → SENDOC_MATERIAL_MAP → vacío
    if erp_data.get("Material"):
        df["Material"] = erp_data["Material"]
    elif "ProcessFlow" in df.columns:
        process_flow = str(df["ProcessFlow"].iloc[0]).strip()
        df["Material"] = SENDOC_MATERIAL_MAP.get(process_flow, "")
    else:
        df["Material"] = ""

    # Cliente: ERP → identify_client por PO
    if erp_data.get("Cliente"):
        df["Cliente"] = erp_data["Cliente"]
    else:
        df["Cliente"] = identify_client(po_value)

    df["Responsable"] = df["Nº Pedido"].apply(get_responsable_initials)

    apply_critico(df)
    apply_fecha(df, received_time)
    df["Nº Transmittal"] = transmittal_code or ""

    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[FINAL_COLUMNS].copy()
