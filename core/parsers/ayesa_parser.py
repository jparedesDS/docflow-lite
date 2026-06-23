"""Parser del portal AYESA (devoluciones de documentación).

El correo de AYESA (remitente *@ayesa.com) trae una única tabla HTML con 4
columnas: Nombre/Name · Descripción/Description · Revisión/Revision ·
Observaciones/Comments, precedida de una fila con el enlace de descarga y una
fila de cabecera.

Particularidad: AYESA usa su propia numeración (proyecto 2206, ref
3000005785-2206-3000, códigos V-3005785-2206-300-XXX-NNN) que NO está en
data_erp. El enlace con el pedido se hace por AYESA_REF_PO_MAP (asunto → PO) y,
de ahí, el Nº Pedido / Cliente / Material salen del ERP por PO. Cada documento
se empareja con su Nº Doc. EIPSA por TIPO de documento (DL→VDDL, ITP→PPI, …).
"""

import re
from io import StringIO

import pandas as pd

from core.parsers.base_parser import (
    AYESA_DOC_TYPE_TO_ERP,
    AYESA_REF_PO_MAP,
    DOC_TYPE_MAP,
    FINAL_COLUMNS,
    apply_critico,
    apply_fecha,
    get_responsable_initials,
)

SENDER_MATCH = "@ayesa.com"

# Código de tipo dentro del código de doc de cliente: "...-DL-001" → "DL"
_DOC_TYPE_RE = re.compile(r"-([A-Z]{2,5})-\d+\s*$")
# Referencia del pedido en el asunto: "Documentos de <ref>:"
_REF_RE = re.compile(r"Documentos\s+de\s+([^:]+)", re.IGNORECASE)


def can_parse(sender: str) -> bool:
    return SENDER_MATCH in (sender or "").lower()


def extract_transmittal_code(subject: str) -> str | None:
    """Primer token del asunto (p.ej. 'P03_3630_EIP-2206-300-001')."""
    s = (subject or "").split(":")[0].strip()
    return s or None


def _extract_ref(subject: str) -> str:
    m = _REF_RE.search(subject or "")
    return m.group(1).strip() if m else ""


def _status_from_obs(obs: str) -> str:
    """Mapea el texto de Observaciones (ES/EN) a un Estado del ERP."""
    o = (obs or "").lower()
    if "rechaz" in o or "reject" in o:
        return "Rechazado"
    if "mayor" in o or "major" in o:
        return "Com. Mayores"
    if "comentario" in o or "comment" in o:
        return "Com. Menores"
    if "informaci" in o or "information" in o or "info only" in o:
        return "Informativo"
    if "aprob" in o or "approved" in o or "final" in o or "(af" in o:
        return "Aprobado"
    return (obs or "").strip()


def _sim(a: str, b: str) -> int:
    return len(set(a.split()) & set(b.split()))


def _erp_for_po(po: str) -> dict:
    """Resuelve Nº Pedido / Supp. / Cliente / Material + docs del pedido por PO.

    Lee del monitoring (ruta efectiva del data_erp), no del lookup roto de
    base_parser.
    """
    out = {"n_pedido": "", "supp": "S00", "cliente": "", "material": "", "docs": []}
    if not po:
        return out
    from core.services import monitoring
    rows = [d for d in monitoring.get_monitoring_data()
            if str(d.get("Nº PO", "")).strip() == str(po).strip()]
    if not rows:
        return out
    first = rows[0]
    ped = str(first.get("Nº Pedido", "")).strip()
    m = re.search(r"-(S\d{2})$", ped)
    if m:
        out["n_pedido"], out["supp"] = ped[:m.start()], m.group(1)
    else:
        out["n_pedido"] = ped
    out["cliente"] = str(first.get("Cliente", "") or "")
    out["material"] = str(first.get("Material", "") or "")
    out["docs"] = rows
    return out


def _match_eipsa(erp_docs: list, type_code: str, titulo: str) -> str:
    """Empareja el documento del email con su Nº Doc. EIPSA por Tipo Doc.

    Si hay varios del mismo tipo, desempata por similitud de título.
    """
    erp_tipo = AYESA_DOC_TYPE_TO_ERP.get((type_code or "").upper())
    if not erp_tipo:
        return ""
    cands = [d for d in erp_docs
             if str(d.get("Tipo Doc.", "")).strip().lower() == erp_tipo.lower()]
    if not cands:
        return ""
    if len(cands) > 1:
        t = (titulo or "").lower()
        cands.sort(key=lambda d: _sim(str(d.get("Título", "")).lower(), t), reverse=True)
    return str(cands[0].get("Nº Doc. EIPSA", "") or "")


def parse(html_body: str, subject: str, received_time: str) -> pd.DataFrame:
    tables = pd.read_html(StringIO(html_body))
    if not tables:
        raise ValueError("Email AYESA: no se encontró la tabla de documentos")
    rows = tables[0].values.tolist()

    # Saltar hasta después de la fila de cabecera (la que contiene 'Nombre'/'Name')
    start = 0
    for i, r in enumerate(rows):
        if any("nombre" in str(c).lower() for c in r):
            start = i + 1
            break

    records = []
    for r in rows[start:]:
        code = str(r[0]).strip() if len(r) > 0 else ""
        if not code or code.lower() == "nan" or "clic aquí" in code.lower() or "click here" in code.lower():
            continue
        records.append({
            "Doc. Cliente": code,
            "Título": str(r[1]).strip() if len(r) > 1 else "",
            "Rev.": str(r[2]).strip() if len(r) > 2 else "",
            "_obs": str(r[3]).strip() if len(r) > 3 else "",
        })
    if not records:
        raise ValueError("Email AYESA: no se detectaron documentos en la tabla")

    df = pd.DataFrame(records)
    df["Estado"] = df["_obs"].apply(_status_from_obs)
    df["_doc_code"] = df["Doc. Cliente"].apply(
        lambda c: (_DOC_TYPE_RE.search(c).group(1) if _DOC_TYPE_RE.search(c) else ""))
    df["Tipo de documento"] = df["_doc_code"].map(DOC_TYPE_MAP).fillna("")

    # Resolver pedido: asunto → ref → PO (mapa) → ERP por PO
    ref = _extract_ref(subject)
    po = AYESA_REF_PO_MAP.get(ref, "")
    erp = _erp_for_po(po)

    df["Doc. EIPSA"] = df.apply(
        lambda row: _match_eipsa(erp["docs"], row["_doc_code"], row["Título"]), axis=1)
    df["Nº Pedido"] = erp["n_pedido"] or ref
    df["Supp."] = erp["supp"]
    df["PO"] = po
    df["Cliente"] = erp["cliente"] or "AYESA"
    df["Material"] = erp["material"]
    df["Responsable"] = df["Nº Pedido"].apply(get_responsable_initials)

    apply_critico(df)
    apply_fecha(df, received_time)
    df["Nº Transmittal"] = extract_transmittal_code(subject) or ""

    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[FINAL_COLUMNS].copy()
