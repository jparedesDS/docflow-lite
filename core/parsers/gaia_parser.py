import re
import pandas as pd
from io import StringIO
from core.parsers.base_parser import (
    GAIA_MATERIAL_MAP, GAIA_STATUS_MAP,
    DOC_TYPE_MAP, apply_critico, fill_supp_nulls, apply_fecha, FINAL_COLUMNS,
    identify_client, get_responsable_initials, PO_CLIENT_MAP,
)


def _parse_gaia_text(text: str, logger) -> list:
    """
    Parsea RTF convertido a texto plano.
    Extrae el código de referencia con regex (patrón conocido) y luego
    parsea el resto de cada línea para obtener Rev. y Título.
    """
    try:
        lines = text.split('\n')
        logger.info(f"GAIA text parse: {len(lines)} líneas raw")

        # Patrón para códigos de referencia GAIA: empieza con 6 dígitos + letra/dígito,
        # seguido de segmentos con guiones, termina en 2-5 letras mayúsculas + 4 dígitos
        REF_RE = re.compile(r'^(\d{6}[A-Z0-9][A-Z0-9-]+-[A-Z]{2,5}-\d{4})\s+(.*)', re.IGNORECASE)

        data_rows = []
        for line in lines:
            line_stripped = line.strip()
            m = REF_RE.match(line_stripped)
            if not m:
                continue

            ref = m.group(1)
            rest = m.group(2).strip()

            # Dividir el resto por 2+ espacios para detectar columnas separadas
            parts = re.split(r'\s{2,}', rest)
            parts = [p.strip() for p in parts if p.strip()]

            client_ref, rev, title = '', '', ''

            if len(parts) == 0:
                pass
            elif len(parts) == 1:
                # Un solo bloque: puede ser "01 Título texto" o solo título
                first_word = parts[0].split()[0] if parts[0].split() else ''
                if 1 <= len(first_word) <= 3 and first_word.replace('.', '').isalnum():
                    # Primer token corto → tratarlo como Rev.
                    rev = first_word
                    title = parts[0][len(first_word):].strip()
                else:
                    title = parts[0]
            elif len(parts) == 2:
                # Dos bloques: puede ser [rev, título] o [client_ref, título]
                if len(parts[0]) <= 3:
                    rev, title = parts[0], parts[1]
                else:
                    client_ref, title = parts[0], parts[1]
            else:
                # 3+ bloques: client_ref, rev, título
                client_ref = parts[0]
                rev = parts[1]
                title = ' '.join(parts[2:])

            data_rows.append({
                'Reference': ref,
                'Doc. Client Ref.': client_ref,
                'Doc. Rev.': rev,
                'Doc. Title': title,
            })
            logger.info(f"GAIA row: ref={ref[:30]}... rev={rev!r} title={title[:40]!r}")

            if len(data_rows) >= 50:
                break

        logger.info(f"GAIA text parse: {len(data_rows)} filas encontradas")

        if not data_rows:
            return []

        df = pd.DataFrame(data_rows)
        return [df]

    except Exception as e:
        logger.error(f"GAIA text parse error: {e}", exc_info=True)
        return []

# GAIA/Technip emails
SENDER_MATCHES = ["gaia", "technip"]

# Transmittal code: e.g. 214726C-TEN-EIPSA-TN-OD-0024
TRANSMITTAL_REGEX = r"(\b\w+-[A-Z]+-[A-Z]+-[A-Z]+-[A-Z]+-\d+)"


def can_parse(sender: str) -> bool:
    s = sender.lower()
    return any(m in s for m in SENDER_MATCHES)


def extract_transmittal_code(subject: str) -> str | None:
    """Extrae el código de transmittal del subject GAIA.
    Ejemplo: '[GAIA] Notification: 214726C-TEN-EIPSA-TN-OD-0024 - Code 3 - ...'
    """
    m = re.search(TRANSMITTAL_REGEX, subject)
    if m:
        return m.group(1)
    # Fallback: primer bloque alfanumérico con guiones tras 'Notification:'
    m2 = re.search(r"Notification:\s*(\S+)", subject)
    if m2:
        code = m2.group(1).rstrip(" -")
        return code
    return None


def extract_status_from_subject(subject: str) -> str:
    """Extrae 'Code X' del subject y lo mapea a estado español."""
    m = re.search(r"Code\s+(\d)", subject)
    if m:
        key = f"Code {m.group(1)}"
        return GAIA_STATUS_MAP.get(key, key)
    return ""


def parse(html_body: str, subject: str, received_time: str) -> pd.DataFrame:
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"GAIA parse: html_body length={len(html_body)}, first 200 chars: {html_body[:200]}")

    df_list = None

    # Intento 1: Parsear como HTML con tablas
    if '<table' in html_body.lower():
        try:
            df_list = pd.read_html(StringIO(html_body))
            logger.info(f"GAIA: {len(df_list)} tablas encontradas en HTML")
        except Exception as e:
            logger.warning(f"pd.read_html failed: {e}")

    # Intento 2: Si no hay tablas HTML o falló, parsear RTF como texto
    if not df_list:
        logger.info("GAIA: No tablas HTML, intentando parsear RTF/texto plano")
        df_list = _parse_gaia_text(html_body, logger)

    if not df_list:
        logger.error(f"No se pudieron extraer datos. HTML: {html_body[:500]}")
        raise ValueError("Email GAIA: no se encontraron datos tabulares")

    # Buscar tabla que contenga columna "Reference"
    df = None
    for candidate in df_list:
        cols_lower = [str(c).lower().strip() for c in candidate.columns]
        if any("reference" in c for c in cols_lower):
            df = candidate.copy()
            break

    if df is None:
        # Fallback: usar la tabla más grande
        df = max(df_list, key=len).copy()

    # Normalizar nombres de columnas
    col_map = {}
    for c in df.columns:
        cl = str(c).lower().strip()
        if "reference" in cl and "client" not in cl:
            col_map[c] = "Reference"
        elif "client" in cl and "ref" in cl:
            col_map[c] = "Doc. Client Ref."
        elif "rev" in cl:
            col_map[c] = "Doc. Rev."
        elif "title" in cl or "título" in cl:
            col_map[c] = "Doc. Title"
    df.rename(columns=col_map, inplace=True)

    # Filtrar filas vacías y cabeceras duplicadas
    if "Reference" in df.columns:
        df = df.dropna(subset=["Reference"])
        df = df[df["Reference"].astype(str).str.strip() != ""]
        df = df[df["Reference"].astype(str) != "Reference"]

    transmittal_code = extract_transmittal_code(subject)
    status = extract_status_from_subject(subject)

    # --- Extraer campos de la columna Reference ---
    ref_col = df["Reference"].astype(str) if "Reference" in df.columns else pd.Series([""] * len(df))

    # Doc type code: último grupo de letras antes del sufijo numérico final
    # e.g. ...-VDDL-0001 → VDDL, ...-WD-0001 → WD
    df["_doc_code"] = ref_col.str.extract(r"-([A-Z]{2,4})-\d{4}$", expand=False)
    df["Tipo de documento"] = df["_doc_code"].map(DOC_TYPE_MAP)

    # Nº Pedido: buscar -AÑO(2d)-PEDIDO(3d)- justo antes del DOCTYPE-NNNN final
    # Ejemplo: ...-001-24-087-VDDL-0001 → P-24/087
    pedido_parts = ref_col.str.extract(r"-(\d{2})-(\d{3})-[A-Z]{2,5}-\d{4}$", expand=True)
    df["Nº Pedido"] = pedido_parts.apply(
        lambda row: f"P-{row[0]}/{row[1]}" if pd.notna(row[0]) else "",
        axis=1
    )

    # PO: primer segmento del Reference antes del primer '-'
    df["PO"] = ref_col.str.split("-").str[0]

    # Supp.: buscar patrón S + dígitos
    supp_extracted = ref_col.str.extract(r"(S\d+)", expand=False)
    df["Supp."] = supp_extracted

    # Material
    df["Material"] = df["PO"].map(GAIA_MATERIAL_MAP).fillna("")

    # Cliente
    df["Cliente"] = df["PO"].apply(identify_client)

    # Responsable
    df["Responsable"] = df["Nº Pedido"].apply(get_responsable_initials)

    # Status (mismo para todas las filas, viene del subject)
    df["Estado"] = status

    # Doc. EIPSA: en GAIA no existe columna EIPSA; usamos Reference como Doc. EIPSA
    df["Doc. EIPSA"] = ref_col

    # Doc. Cliente: la columna "Reference" del email GAIA ES la referencia del cliente
    df["Doc. Cliente"] = ref_col

    # Si existe "Doc. Client Ref." y tiene datos, usarla como Doc. Cliente
    if "Doc. Client Ref." in df.columns:
        client_ref = df["Doc. Client Ref."].astype(str).str.strip()
        mask = (client_ref != "") & (client_ref.str.lower() != "nan")
        df.loc[mask, "Doc. Cliente"] = client_ref[mask]

    # Título
    df["Título"] = df["Doc. Title"].astype(str) if "Doc. Title" in df.columns else ""

    # Rev.
    df["Rev."] = df["Doc. Rev."].astype(str) if "Doc. Rev." in df.columns else ""

    fill_supp_nulls(df)
    apply_critico(df)
    apply_fecha(df, received_time)
    df["Nº Transmittal"] = transmittal_code or ""

    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[FINAL_COLUMNS].copy()
