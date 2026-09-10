"""Parser del portal SACYR / Proarc (Proarc@SACYR <sacyr@proarconline.com>).

El correo trae una tabla HTML de tres columnas —Document number · Title · Rev—
con los documentos del workflow, y en el asunto el nº de flujo y el PO del
cliente::

    Supplier Document Issue: 4000079 - WF#:4000079-REC627-627-J-C.181752/01-SP-OBTS-000002
    - DISC:270 - PO:REC627-627-J-C.181752/01 OBTS-000002

Particularidades:

· **No trae la resolución del documento.** El correo solo avisa de que los
  documentos se han distribuido; los comentarios están en el enlace de
  SharePoint del apartado «Comments». Por eso el Estado sale vacío y se pone a
  mano en la preview, igual que en Document Space.

· **La numeración del correo no es literalmente la del ERP.** SACYR escribe
  ``REC627-627-J-C.181752/01-00004`` y en el ERP ese mismo documento está como
  ``V-REC627-627-J-C.181752/01-004``: sobra el prefijo del proveedor y el nº de
  orden va con menos ceros. Se emparejan comparando el número final y exigiendo
  que un código termine como el otro, así que no hace falta ningún mapa por
  pedido: el pedido, el Nº Doc. EIPSA, el tipo y el crítico salen del ERP.
"""

import logging
import re
from io import StringIO

import pandas as pd

from core.parsers.base_parser import (
    FINAL_COLUMNS,
    apply_critico,
    apply_fecha,
    erp_client_code_index,
    erp_header_from_row,
    get_responsable_initials,
    norm_doc_code,
)

logger = logging.getLogger(__name__)

SENDER_MATCH = "proarconline.com"

# Asunto: «… WF#:<flujo> - DISC:270 - PO:<po del cliente> …»
_WF_RE = re.compile(r"WF#\s*:\s*(\S+)", re.I)
_PO_RE = re.compile(r"\bPO\s*:\s*(\S+)", re.I)

# Código de documento: todo lo anterior al nº de orden final («…/01-00004»).
_CODE_RE = re.compile(r"^(.*)-0*(\d+)$")

# Cabecera de la tabla de documentos del correo.
_DOC_COL = ("document number", "document no", "document no.")
_TITLE_COL = ("title", "document title")
_REV_COL = ("rev", "rev.", "revision")

# Longitud mínima del tramo común entre el código del correo y el del ERP para
# darlos por el mismo documento (evita casar por un sufijo corto casual).
_MIN_BASE = 8


def can_parse(sender: str) -> bool:
    return SENDER_MATCH in (sender or "").lower()


def matches_subject(subject: str) -> bool:
    """Solo los avisos de documentos, que son los que traen tabla.

    Del mismo remitente llegan también avisos del propio Proarc (altas, avisos
    de caducidad de contraseña…) que no son devoluciones y reventarían el parseo.
    """
    subject = subject or ""
    if _WF_RE.search(subject) and _PO_RE.search(subject):
        return True
    if "supplier document" in subject.lower():
        logger.warning(
            "SACYR: '%s' parece un aviso de documentos pero no trae WF#/PO en el "
            "asunto; el correo se ignora.", subject)
    return False


def extract_transmittal_code(subject: str) -> str | None:
    m = _WF_RE.search(subject or "")
    return m.group(1) if m else None


def extract_po(subject: str) -> str:
    m = _PO_RE.search(subject or "")
    return m.group(1) if m else ""


# ── Emparejado con el ERP ─────────────────────────────────────────────────────

def _split_code(code) -> tuple[str, int | None]:
    """Código de documento partido en (tramo común, nº de orden)."""
    m = _CODE_RE.match(norm_doc_code(code))
    return (m.group(1), int(m.group(2))) if m else ("", None)


def _index_by_order(index: dict) -> dict:
    """{nº de orden → [(tramo común, fila del ERP)]} para buscar sin el prefijo."""
    out: dict[int, list] = {}
    for code, row in index.items():
        base, num = _split_code(code)
        if num is not None and len(base) >= _MIN_BASE:
            out.setdefault(num, []).append((base, row))
    return out


def _erp_row(code: str, index: dict, by_order: dict) -> dict | None:
    """Fila del ERP de un documento del correo: exacta o por nº de orden."""
    row = index.get(norm_doc_code(code))
    if row is not None:
        return row
    base, num = _split_code(code)
    if num is None or len(base) < _MIN_BASE:
        return None
    for erp_base, erp_row in by_order.get(num, ()):
        if erp_base.endswith(base) or base.endswith(erp_base):
            return erp_row
    return None


def _erp_by_po(po: str) -> dict | None:
    """Primera fila del pedido cuyo Nº PO cierra el PO del correo.

    Red de seguridad para un pedido cuyos Nº Doc. Cliente aún no están puestos:
    el ERP guarda «C.181752/01» y SACYR manda «REC627-627-J-C.181752/01».
    """
    po = norm_doc_code(po)
    if len(po) < _MIN_BASE:
        return None
    from core.services import monitoring
    for d in monitoring.get_monitoring_data():
        erp_po = norm_doc_code(d.get("Nº PO"))
        if len(erp_po) >= _MIN_BASE and po.endswith(erp_po):
            return d
    return None


# ── Tabla de documentos ───────────────────────────────────────────────────────

def _documents_table(html_body: str) -> pd.DataFrame:
    """Doc. Cliente / Título / Rev. de la tabla del correo."""
    try:
        tables = pd.read_html(StringIO(html_body), flavor="lxml")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Email SACYR: no se pudo leer el HTML ({exc})") from exc
    if not tables:
        raise ValueError("Email SACYR: el correo no trae ninguna tabla")

    for t in tables:
        if len(t.columns) < 3 or t.empty:
            continue
        # La cabecera viene como primera fila, no como nombre de columna.
        head = [str(v).strip().lower().rstrip(".") for v in t.iloc[0]]
        if not any(h in _DOC_COL for h in head):
            continue
        cols = {}
        for i, h in enumerate(head):
            if h in _DOC_COL:
                cols["Doc. Cliente"] = i
            elif h in _TITLE_COL:
                cols["Título"] = i
            elif h in _REV_COL:
                cols["Rev."] = i
        rows = []
        for _, r in t.iloc[1:].iterrows():
            code = str(r.iloc[cols["Doc. Cliente"]]).strip()
            if not code or code.lower() == "nan":
                continue
            rows.append({
                "Doc. Cliente": code,
                "Título": str(r.iloc[cols["Título"]]).strip() if "Título" in cols else "",
                "Rev.": str(r.iloc[cols["Rev."]]).strip() if "Rev." in cols else "",
            })
        if rows:
            return pd.DataFrame(rows)

    raise ValueError("Email SACYR: no se encontró la tabla de documentos")


def parse(html_body: str, subject: str, received_time: str) -> pd.DataFrame:
    df = _documents_table(html_body)
    df["Título"] = df["Título"].replace("nan", "")
    df["Rev."] = df["Rev."].replace("nan", "")

    index = erp_client_code_index()
    by_order = _index_by_order(index)
    matched = [_erp_row(c, index, by_order) for c in df["Doc. Cliente"]]

    po = extract_po(subject)
    hit = next((m for m in matched if m is not None), None) or _erp_by_po(po)
    if hit is None:
        logger.warning("SACYR: ningún documento de '%s' casa con el ERP (PO %s); "
                       "el pedido habrá que ponerlo a mano.", subject, po or "?")
        header = {"n_pedido": "", "supp": "S00", "cliente": "", "material": "", "po": ""}
    else:
        header = erp_header_from_row(hit)

    df["Nº Pedido"] = header["n_pedido"]
    df["Supp."] = header["supp"]
    df["Cliente"] = header["cliente"]
    df["Material"] = header["material"]
    df["PO"] = header["po"] or po
    df["Responsable"] = df["Nº Pedido"].apply(get_responsable_initials)

    # Del ERP, por documento: nº EIPSA, tipo y crítico. El título del correo
    # manda (es el que ve el cliente); si viene vacío, el del ERP.
    df["Doc. EIPSA"] = [str((m or {}).get("Nº Doc. EIPSA", "") or "") for m in matched]
    df["Tipo de documento"] = [str((m or {}).get("Tipo Doc.", "") or "") for m in matched]
    df["Título"] = [t or str((m or {}).get("Título", "") or "")
                    for t, m in zip(df["Título"], matched)]

    # El correo no trae la resolución (está en el SharePoint de «Comments»):
    # el estado se pone a mano en la preview.
    df["Estado"] = ""

    apply_critico(df)
    df["Crítico"] = [str((m or {}).get("Crítico", "") or "") or cur
                     for cur, m in zip(df["Crítico"], matched)]
    apply_fecha(df, received_time)
    df["Nº Transmittal"] = extract_transmittal_code(subject) or ""

    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[FINAL_COLUMNS].copy()
