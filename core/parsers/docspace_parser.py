import re
import pandas as pd
from io import StringIO
from core.parsers.base_parser import (
    DOC_TYPE_MAP, apply_critico, fill_supp_nulls, apply_fecha, FINAL_COLUMNS,
    identify_client, get_responsable_initials, lookup_erp,
)

SENDER_MATCH = "hec.co.kr"
TRANSMITTAL_REGEX = r'\[([A-Z0-9&]+(?:-[A-Z0-9]+)*)\]'

# project_key → (Nº Pedido, Supp., Material)
DOCSPACE_PROJECT_MAP = {
    "JUS&ICS2": ("P-24/070", "S00", "CAUDAL"),
}


def can_parse(sender: str) -> bool:
    return SENDER_MATCH in sender.lower()


def extract_transmittal_code(subject: str) -> str | None:
    m = re.search(TRANSMITTAL_REGEX, subject)
    return m.group(1) if m else None


def _get_project_key(transmittal_code: str | None) -> str:
    """Extrae la clave de proyecto del transmittal code (primer segmento antes de '-CI')."""
    if not transmittal_code:
        return ""
    # Ej: "JUS&ICS2-CI0021-HS-EI-T-0029" → "JUS&ICS2"
    parts = transmittal_code.split("-")
    if parts:
        return parts[0]
    return transmittal_code


def parse(html_body: str, subject: str, received_time: str) -> pd.DataFrame:
    try:
        df_list = pd.read_html(StringIO(html_body), flavor="lxml")
    except Exception:
        df_list = []

    print(f"[DOCSPACE] {len(df_list)} tablas HTML encontradas", flush=True)
    for i, t in enumerate(df_list):
        print(f"[DOCSPACE] tabla[{i}]: cols={list(t.columns)}, filas={len(t)}", flush=True)

    if not df_list:
        raise ValueError("Email Document Space no contiene tablas HTML")

    # Candidatos de nombre de columna para Doc. Cliente
    DOC_COL_CANDIDATES = ("doc. no", "doc no", "file name", "filename", "document no", "document no.")
    TITLE_COL_CANDIDATES = ("title", "document title", "doc. title")
    REV_COL_CANDIDATES = ("rev. no.", "rev. no", "rev no", "rev.", "rev", "revision")
    STATUS_COL_CANDIDATES = ("review result", "status", "result", "review code")

    ALL_KEYS = DOC_COL_CANDIDATES + TITLE_COL_CANDIDATES + REV_COL_CANDIDATES + STATUS_COL_CANDIDATES

    df = None
    header_row_idx = None

    for candidate in df_list:
        # Aplanar MultiIndex si lo hay
        if isinstance(candidate.columns, pd.MultiIndex):
            candidate.columns = [" ".join(str(s) for s in col).strip() for col in candidate.columns]

        cols_lower = [str(c).lower().strip() for c in candidate.columns]

        # Caso A: columnas ya nombradas que coinciden directamente
        if any(any(k in cl for k in DOC_COL_CANDIDATES) for cl in cols_lower):
            df = candidate.copy()
            break

        # Caso B: columnas numéricas → buscar fila header en primeras 3 filas
        if all(isinstance(c, (int, float)) for c in candidate.columns) and len(candidate) > 1:
            for ri in range(min(3, len(candidate))):
                row_vals = [str(v).lower().strip() for v in candidate.iloc[ri]]
                hits = sum(1 for v in row_vals if any(k in v for k in ALL_KEYS))
                if hits >= 2:
                    df = candidate.copy()
                    header_row_idx = ri
                    break
            if df is not None:
                break

    if df is None:
        # Fallback: tabla más grande
        df = max(df_list, key=len).copy()

    # Aplanar MultiIndex en tabla seleccionada
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(s) for s in col).strip() for col in df.columns]

    # Promover fila como header si se detectó
    if header_row_idx is not None:
        df.columns = df.iloc[header_row_idx].astype(str).str.strip().str.lower()
        df = df.iloc[header_row_idx + 1:].reset_index(drop=True)
    elif all(isinstance(c, (int, float)) for c in df.columns) and len(df) > 0:
        # Fallback: promover primera fila como header
        df.columns = df.iloc[0].astype(str).str.strip().str.lower()
        df = df.iloc[1:].reset_index(drop=True)

    print(f"[DOCSPACE] tabla seleccionada: cols={list(df.columns)}", flush=True)

    # Normalizar columnas
    col_map = {}
    for c in df.columns:
        cl = str(c).lower().strip().replace("\xa0", " ")
        if any(k == cl for k in DOC_COL_CANDIDATES):
            col_map[c] = "Doc. Cliente"
        elif any(k == cl for k in TITLE_COL_CANDIDATES):
            col_map[c] = "Title"
        elif any(k == cl for k in REV_COL_CANDIDATES):
            col_map[c] = "Rev"
        elif any(k == cl for k in STATUS_COL_CANDIDATES):
            col_map[c] = "Review Result"
    df.rename(columns=col_map, inplace=True)

    # Filtrar filas vacías y cabeceras duplicadas
    if "Doc. Cliente" in df.columns:
        df = df.dropna(subset=["Doc. Cliente"])
        df = df[df["Doc. Cliente"].astype(str).str.strip() != ""]
        df = df[~df["Doc. Cliente"].astype(str).str.strip().str.lower().isin(
            list(DOC_COL_CANDIDATES) + ["doc. no", "nan"]
        )]
        df = df[~df["Doc. Cliente"].astype(str).str.strip().str.startswith("Unnamed")]
    else:
        raise ValueError("No se encontró columna de documento en el email Document Space")

    if df.empty:
        raise ValueError("No se encontraron filas de documentos en el email Document Space")

    df = df.reset_index(drop=True)

    # Transmittal code y project key
    transmittal_code = extract_transmittal_code(subject)
    project_key = _get_project_key(transmittal_code)
    n_pedido, supp, material = DOCSPACE_PROJECT_MAP.get(project_key, ("", "S00", ""))

    # PO para identify_client: usar project_key completo (primeros 5 chars → JUS&I)
    po_for_client = project_key
    cliente = identify_client(po_for_client)

    df["PO"] = project_key
    df["Nº Pedido"] = n_pedido
    df["Supp."] = supp
    df["Material"] = material
    df["Cliente"] = cliente
    df["Responsable"] = get_responsable_initials(n_pedido)

    # Doc. EIPSA vacío (no disponible en email)
    df["Doc. EIPSA"] = ""

    # Título y Rev.
    df["Título"] = df["Title"].astype(str).str.strip() if "Title" in df.columns else ""
    df["Rev."] = df["Rev"].astype(str).str.strip() if "Rev" in df.columns else ""

    # Estado: vacío si no hay columna, editable en UI
    if "Review Result" in df.columns:
        df["Estado"] = df["Review Result"].astype(str).str.strip().replace("nan", "")
    else:
        df["Estado"] = ""

    # Tipo de documento inferido del código del documento
    df["_doc_code"] = df["Doc. Cliente"].astype(str).str.extract(
        r'-([A-Z]{2,5})-\d{3,}', expand=False
    )
    df["Tipo de documento"] = df["_doc_code"].map(DOC_TYPE_MAP)

    apply_critico(df)
    fill_supp_nulls(df)
    apply_fecha(df, received_time)
    df["Nº Transmittal"] = transmittal_code or ""

    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[FINAL_COLUMNS].copy()
