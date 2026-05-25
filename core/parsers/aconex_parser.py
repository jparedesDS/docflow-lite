import re
import pandas as pd
from io import StringIO
from core.parsers.base_parser import (
    PRODOC_PO_MAP, PRODOC_MATERIAL_MAP, ACONEX_STATUS_MAP, ACONEX_PO_MAP,
    DOC_TYPE_MAP, apply_critico, fill_supp_nulls, apply_fecha, FINAL_COLUMNS,
    identify_client, get_responsable_initials, lookup_erp,
)

SENDER_MATCH = "noreply@aconex.com"
TRANSMITTAL_REGEX = r"[A-Z]{3}-[A-Z]{5}-\d{6}"


def can_parse(sender: str) -> bool:
    return SENDER_MATCH in sender.lower()


def extract_transmittal_code(subject: str) -> str | None:
    m = re.search(TRANSMITTAL_REGEX, subject)
    return m.group(0) if m else None


def parse(html_body: str, subject: str, received_time: str) -> pd.DataFrame:
    df_list = pd.read_html(StringIO(html_body), flavor='lxml')

    print(f"[ACONEX] {len(df_list)} tablas HTML encontradas", flush=True)
    for i, t in enumerate(df_list):
        print(f"[ACONEX] tabla[{i}]: cols={list(t.columns)}, filas={len(t)}", flush=True)

    if not df_list:
        raise ValueError("Email ACONEX no contiene tablas HTML")

    # Extraer Package de la tabla de metadata
    package_code = ''
    for candidate in df_list:
        if len(candidate) < 2:
            continue
        for _, row in candidate.iterrows():
            vals = [str(v).strip() for v in row.values if pd.notna(v)]
            if any('package' in v.lower() for v in vals):
                for v in vals:
                    if 'package' not in v.lower() and v:
                        package_code = v.split(' - ')[0].strip()
                        break
                break
        if package_code:
            break
    print(f"[ACONEX] package extraído: {package_code}", flush=True)

    # Selección dinámica: por nombre de columna O contenido de primeras filas
    HEADER_KEYS = ('document no', 'name', 'title', 'revision', 'rev', 'status', 'p.o')
    df = None
    header_row_idx = None
    for candidate in df_list:
        cols_lower = [str(c).lower() for c in candidate.columns]
        if any('name' in c for c in cols_lower) or any('p.o' in c for c in cols_lower):
            df = candidate.copy()
            break
        # Columnas numéricas: buscar fila de headers en las primeras 3 filas
        if all(isinstance(c, int) for c in candidate.columns) and len(candidate) > 1:
            for ri in range(min(3, len(candidate))):
                row_vals = [str(v).lower().strip() for v in candidate.iloc[ri]]
                hits = sum(1 for v in row_vals if any(k in v for k in HEADER_KEYS))
                if hits >= 2:
                    df = candidate.copy()
                    header_row_idx = ri
                    break
            if df is not None:
                break
    if df is None:
        df = max(df_list, key=len).copy()

    print(f"[ACONEX] tabla seleccionada: cols={list(df.columns)}, filas={len(df)}, header_row={header_row_idx}", flush=True)

    # Promover fila de headers y descartar filas anteriores
    if header_row_idx is not None:
        df.columns = df.iloc[header_row_idx].astype(str).str.strip()
        df = df.iloc[header_row_idx + 1:].reset_index(drop=True)
        print(f"[ACONEX] headers promovidos: {list(df.columns)}", flush=True)
    elif all(isinstance(c, int) for c in df.columns):
        df.columns = df.iloc[0].astype(str).str.strip()
        df = df.iloc[1:].reset_index(drop=True)
        print(f"[ACONEX] headers promovidos (fallback): {list(df.columns)}", flush=True)

    # Normalizar nombres de columna
    col_map = {}
    for c in df.columns:
        cl = str(c).lower().strip().replace('\xa0', ' ')
        if cl in ('name', 'document no.', 'document no', 'doc no', 'doc. no.', 'doc. no'):
            col_map[c] = 'Name'
        elif 'p.o' in cl or cl == 'po':
            col_map[c] = 'P.O.'
        elif cl == 'title':
            col_map[c] = 'Title'
        elif cl in ('rev', 'rev.', 'revision'):
            col_map[c] = 'Rev'
        elif 's.r' in cl or 'status' in cl:
            col_map[c] = 'S.R. Status'
    df.rename(columns=col_map, inplace=True)

    # Filtrar filas vacías y cabeceras repetidas
    if 'Name' in df.columns:
        df = df.dropna(subset=['Name'])
        df = df[df['Name'].astype(str).str.strip() != '']
        df = df[~df['Name'].astype(str).str.strip().isin(['Name', 'Document No.', 'Document No'])]
        df = df[~df['Name'].astype(str).str.contains('document register has been', case=False, na=False)]

    if df.empty:
        raise ValueError("No se encontraron filas de documentos en el email ACONEX")

    transmittal_code = extract_transmittal_code(subject)

    # PO → Nº Pedido (usar Package extraído de metadata, fallback a P.O. columna)
    if package_code:
        df['PO'] = package_code
        df['Nº Pedido'] = ACONEX_PO_MAP.get(package_code, package_code)
    elif 'P.O.' in df.columns:
        df['PO'] = df['P.O.'].astype(str).str.strip()
        df['Nº Pedido'] = df['PO'].map(PRODOC_PO_MAP).fillna(df['PO'])
    else:
        df['PO'] = ''
        df['Nº Pedido'] = ''

    # Doc. EIPSA / Doc. Cliente / Tipo de documento / Supp.
    if 'Name' in df.columns:
        name_col = df['Name'].astype(str).str.strip()
        df['Doc. EIPSA'] = name_col
        df['Doc. Cliente'] = name_col
        df['_doc_code'] = name_col.str.extract(r'-([A-Z]{2,5})-\d{3}', expand=False)
        df['Tipo de documento'] = df['_doc_code'].map(DOC_TYPE_MAP)
        df['Supp.'] = name_col.str.extract(r'(S\d{2})', expand=False)
    else:
        df['Doc. EIPSA'] = ''
        df['Doc. Cliente'] = ''
        df['Tipo de documento'] = ''

    # Estado — vacío (requiere Integration ID de ACONEX para acceder via API)
    df['Estado'] = ''

    # Title / Rev.
    if 'Title' in df.columns:
        df['Título'] = df['Title']
    if 'Rev' in df.columns:
        df['Rev.'] = df['Rev']

    # Material, Cliente, Responsable (lookup ERP por Nº Pedido)
    n_pedido = df['Nº Pedido'].iloc[0] if len(df) > 0 else ''
    erp_data = lookup_erp(n_pedido)
    df['Material'] = erp_data.get('Material', '')
    df['Cliente'] = erp_data.get('Cliente', '')
    df['Responsable'] = df['Nº Pedido'].apply(get_responsable_initials)

    fill_supp_nulls(df)
    apply_critico(df)
    apply_fecha(df, received_time)
    df['Nº Transmittal'] = transmittal_code or ''

    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = ''

    return df[FINAL_COLUMNS].copy()
