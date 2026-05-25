import re
import logging
import pandas as pd
from io import StringIO
from core.parsers.base_parser import (
    PRODOC_PO_MAP, PRODOC_MATERIAL_MAP, ACONEX_STATUS_MAP,
    DOC_TYPE_MAP, apply_critico, fill_supp_nulls, apply_fecha, FINAL_COLUMNS,
    identify_client, get_responsable_initials,
)

logger = logging.getLogger(__name__)

SENDER_MATCH = "prodoc.postmaster@woodplc.com"
TRANSMITTAL_REGEX = r'TL-\d{2,4}[A-Z0-9]+-VDC-\d{4}'

# Regex para detectar código de documento EIPSA en texto plano
EIPSA_DOC_RE = re.compile(
    r'\*?\s*(V-[A-Z0-9]+-\d{3,4}-\d{3,4}-[A-Z0-9]+-[A-Z]{2,5}-\d{3}[A-Z]?)',
    re.IGNORECASE
)

# Regex para PO (10 dígitos empezando por 7, o 9 dígitos empezando por 600)
PO_RE = re.compile(r'\b(7\d{9}|600\d{6})\b')

# Líneas residuales de URL-hash (>40 chars alfanuméricos seguidos de >)
URL_HASH_RE = re.compile(r'[A-Za-z0-9+/]{40,}>')


def can_parse(sender: str) -> bool:
    return SENDER_MATCH in sender.lower()


def extract_transmittal_code(subject: str) -> str | None:
    m = re.search(TRANSMITTAL_REGEX, subject)
    return m.group(0) if m else None


def _clean(series: pd.Series) -> pd.Series:
    """Elimina nbsp (\xa0), marcadores (*), y espacios sobrantes."""
    s = series.astype(str)
    s = s.str.replace('\xa0', ' ', regex=False)
    s = s.str.replace("'a0", ' ', regex=False)
    s = s.str.replace('\u00a0', ' ', regex=False)
    s = s.str.strip()
    s = s.str.replace(r'^\*\s*', '', regex=True)
    s = s.str.strip()
    return s


def _build_df_from_records(records: list[dict], subject: str, received_time: str) -> pd.DataFrame:
    """Construye el DataFrame final a partir de registros normalizados de documentos."""
    df = pd.DataFrame(records)

    if df.empty:
        return df

    # Doc. EIPSA y Doc. Cliente
    df['Doc. EIPSA'] = df.get('Name', pd.Series([''] * len(df)))
    df['Doc. Cliente'] = df['Doc. EIPSA']

    # PO → Nº Pedido
    df['PO'] = df.get('P.O.', pd.Series([''] * len(df))).fillna('')
    df['Nº Pedido'] = df['PO'].map(PRODOC_PO_MAP).fillna(df['PO'])

    # Título y Rev.
    df['Título'] = df.get('Title', pd.Series([''] * len(df))).fillna('')
    df['Rev.'] = df.get('Rev', pd.Series([''] * len(df))).fillna('')

    # Estado
    status_raw = df.get('S.R. Status', pd.Series([''] * len(df))).fillna('')
    df['Estado'] = status_raw.map(ACONEX_STATUS_MAP).fillna(status_raw)

    # Tipo de documento — extraer código del nombre
    name_col = df['Doc. EIPSA'].astype(str)
    df['_doc_code'] = name_col.str.extract(r'-([A-Z]{2,5})-\d{3}', expand=False)
    df['Tipo de documento'] = df['_doc_code'].map(DOC_TYPE_MAP)

    # Supp.
    df['Supp.'] = name_col.str.extract(r'(S\d{2})', expand=False)
    fill_supp_nulls(df)

    # Material, Cliente, Responsable, Crítico, Fecha
    df['Material'] = df['PO'].map(PRODOC_MATERIAL_MAP).fillna('')
    df['Cliente'] = df['PO'].apply(identify_client)
    df['Responsable'] = df['Nº Pedido'].apply(get_responsable_initials)
    apply_critico(df)
    apply_fecha(df, received_time)

    # Nº Transmittal
    df['Nº Transmittal'] = extract_transmittal_code(subject) or ''

    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = ''

    return df[FINAL_COLUMNS].copy()


def _parse_from_text(text: str, subject: str, received_time: str) -> pd.DataFrame:
    """
    Parser dedicado para emails PRODOC con formato multi-línea en text/plain.

    Formato típico por documento:
      Línea A: * V-23BLFE01A-...-CAL-001 <https://url-larga>   → marca inicio de doc
      Línea B: HASH_END>\t\tEQUIPMENT_TYPE                     → residuo URL, ignorar
      Línea C: CALCULATION SHEETS\t0\t7070000087               → Title, Rev, PO
      Línea D: SR.RM-2206-400\t2 - WITHOUT COMMENTS\tSend Final → Item, Status
    """
    lines = text.split('\n')

    # 1. Localizar sección "Documents:"
    docs_idx = None
    for i, line in enumerate(lines):
        if re.search(r'documents\s*:', line, re.IGNORECASE):
            docs_idx = i
            break
    if docs_idx is None:
        raise ValueError("No se encontró sección 'Documents:' en el texto plano")

    # 2. Localizar línea de headers (Name + P.O. o Status)
    header_idx = None
    for i in range(docs_idx, min(docs_idx + 15, len(lines))):
        line = lines[i]
        has_name = bool(re.search(r'\bname\b', line, re.IGNORECASE))
        has_po_or_status = bool(re.search(r'p\.o\.|status', line, re.IGNORECASE))
        if has_name and has_po_or_status:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("No se encontró línea de headers en sección Documents:")

    # 2b. Parsear header para obtener índices de columna
    header_line = lines[header_idx]
    raw_headers = header_line.split('\t') if '\t' in header_line else re.split(r'  +', header_line)

    col_idx = {}
    for i, h in enumerate(raw_headers):
        h_clean = h.strip().lower().replace('\xa0', ' ')
        if h_clean == 'name':
            col_idx['name'] = i
        elif h_clean == 'title':
            col_idx['title'] = i
        elif h_clean in ('rev', 'rev.', 'revision'):
            col_idx['rev'] = i
        elif 'p.o' in h_clean or h_clean == 'po':
            col_idx['po'] = i
        elif 'item' in h_clean:
            col_idx['item'] = i
        elif 's.r' in h_clean or 'status' in h_clean:
            col_idx['status'] = i

    print(f"[PRODOC TEXT] col_idx={col_idx}", flush=True)

    def _get_cell(cells, key):
        idx = col_idx.get(key)
        if idx is not None and idx < len(cells):
            return cells[idx].strip()
        return ''

    # 3. Iterar líneas desde header+1 agrupando por código EIPSA
    documents = []       # lista de dicts: {name, data_lines}
    current_name = None
    current_lines = []

    for line in lines[header_idx + 1:]:
        stripped = line.rstrip()

        # Parar en nueva sección (e.g. "Notes:", "Recipients:")
        if re.match(r'^[A-Z][A-Za-z\s]+:\s*$', stripped):
            break

        m = EIPSA_DOC_RE.search(stripped)
        if m:
            # Guardar documento anterior
            if current_name:
                documents.append({'name': current_name, 'data_lines': current_lines})
            current_name = m.group(1)
            current_lines = []
        elif current_name is not None:
            # Acumular línea de datos para el documento actual
            if stripped.strip():
                current_lines.append(stripped)

    # Guardar el último documento
    if current_name:
        documents.append({'name': current_name, 'data_lines': current_lines})

    if not documents:
        raise ValueError("No se encontraron documentos con código EIPSA en el texto plano")

    print(f"[PRODOC TEXT] {len(documents)} documentos extraídos del texto plano", flush=True)

    # 4. Extraer campos de cada documento usando índices de columna
    records = []
    for doc in documents:
        name = doc['name']
        title = ''
        rev = ''
        po = ''
        status = ''

        for line in doc['data_lines']:
            if URL_HASH_RE.search(line):
                continue

            cells = line.split('\t') if '\t' in line else re.split(r'  +', line)
            cells_stripped = [c.strip() for c in cells]

            # Saltar fila que contiene el código EIPSA
            if any(EIPSA_DOC_RE.search(c) for c in cells_stripped):
                continue

            # Línea C: buscar PO con regex en toda la línea (independiente de col_idx)
            po_match = PO_RE.search(line)
            if po_match and not po:
                po = po_match.group(1)
                # Rev: celda corta (1-3 chars alfanum) distinta del PO
                if not rev:
                    for cell in cells_stripped:
                        if cell and cell != po and re.fullmatch(r'[A-Za-z0-9]{1,3}', cell):
                            rev = cell
                            break
                # Title: primera celda no vacía de más de 3 chars que no sea el PO
                if not title:
                    for cell in cells_stripped:
                        if cell and cell != po and len(cell) > 3:
                            title = cell
                            break

            # Status: escanear TODAS las celdas contra ACONEX_STATUS_MAP (posición-independiente)
            if not status:
                for cell in cells_stripped:
                    if cell in ACONEX_STATUS_MAP:
                        status = cell
                        break

        records.append({
            'Name': name,
            'Title': title,
            'Rev': rev,
            'P.O.': po,
            'S.R. Status': status,
        })

    return _build_df_from_records(records, subject, received_time)


def _parse_from_html(html_body: str, subject: str, received_time: str) -> pd.DataFrame:
    """Parser HTML original (fallback)."""
    # 1. Parsear tabla HTML — la que tenga columna 'Name' o 'P.O.'
    df_list = pd.read_html(StringIO(html_body), flavor='lxml')
    df = None
    for candidate in df_list:
        cols_lower = [str(c).lower() for c in candidate.columns]
        if any('name' in c for c in cols_lower) or any('p.o' in c for c in cols_lower):
            df = candidate.copy()
            break
    if df is None:
        df = max(df_list, key=len).copy()

    print(f"[PRODOC HTML] columnas={list(df.columns)}, filas={len(df)}", flush=True)

    # 2. Normalizar nombres de columnas
    col_map = {}
    for c in df.columns:
        cl = str(c).lower().strip().replace('\xa0', ' ')
        if cl == 'name':
            col_map[c] = 'Name'
        elif 'p.o' in cl or cl == 'po':
            col_map[c] = 'P.O.'
        elif cl == 'title':
            col_map[c] = 'Title'
        elif cl == 'rev':
            col_map[c] = 'Rev'
        elif 's.r' in cl or 'status' in cl:
            col_map[c] = 'S.R. Status'
    df.rename(columns=col_map, inplace=True)

    # 3. Filtrar filas vacías y cabeceras repetidas
    if 'Name' in df.columns:
        df = df.dropna(subset=['Name'])
        cleaned_name = _clean(df['Name'])
        df = df[cleaned_name != '']
        df = df[cleaned_name != 'Name']
        key_cols = [c for c in ['P.O.', 'Rev', 'S.R. Status', 'Title'] if c in df.columns]
        if key_cols:
            has_data = df[key_cols].apply(
                lambda col: col.notna() & (_clean(col.astype(str)) != '') & (_clean(col.astype(str)) != 'nan'),
                axis=0
            ).any(axis=1)
            df = df[has_data]

    if df.empty:
        raise ValueError("No se encontraron filas de documentos en la tabla PRODOC")

    # 4. Construir registros normalizados
    name_col = _clean(df['Name']) if 'Name' in df.columns else pd.Series([''] * len(df))
    records = []
    for i, row in df.iterrows():
        records.append({
            'Name': name_col.loc[i] if i in name_col.index else '',
            'Title': _clean(pd.Series([row.get('Title', '')])).iloc[0],
            'Rev': _clean(pd.Series([row.get('Rev', '')])).iloc[0],
            'P.O.': _clean(pd.Series([row.get('P.O.', '')])).iloc[0],
            'S.R. Status': _clean(pd.Series([row.get('S.R. Status', '')])).iloc[0],
        })

    return _build_df_from_records(records, subject, received_time)


def parse(html_body: str, subject: str, received_time: str, plain_body: str = "") -> pd.DataFrame:
    # Estrategia 1: Parser de texto multi-línea (PRODOC siempre tiene texto plano)
    if plain_body.strip():
        try:
            df = _parse_from_text(plain_body, subject, received_time)
            if not df.empty:
                return df
        except Exception as e:
            logger.warning(f"[PRODOC] parser texto falló: {e}, intentando HTML")

    # Estrategia 2: Parser HTML (fallback)
    return _parse_from_html(html_body, subject, received_time)
