import imaplib
import email
import logging
import re
from email.header import decode_header
from email.utils import parsedate_to_datetime
from tnefparse import TNEF
from core.config import IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASS

logger = logging.getLogger(__name__)


def _safe_to_str(data) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data) if data is not None else ""


def _decompress_rtf(data: bytes, logger) -> str:
    """
    Descomprime RTF en formato LZFU (Microsoft Outlook).
    Si ya es RTF plano (empieza con {\\rtf), lo retorna directamente.
    """
    if len(data) < 4:
        return data.decode("utf-8", errors="replace")

    # Si los datos ya son RTF plano (no comprimido MAPI)
    if data[:4] in (b'{\\rt', b'\\rtf'):
        logger.info("TNEF RTF: datos son RTF directo, sin comprimir")
        return data.decode("utf-8", errors="replace")

    # Signature LZFU: comienza con 'LZFu' o similar compresión
    try:
        from compressed_rtf import decompress
        decompressed = decompress(data)
        logger.info("TNEF RTF: descomprimido con compressed_rtf")
        return decompressed.decode("utf-8", errors="replace")
    except ImportError:
        logger.warning("compressed_rtf no instalado")
    except Exception as e:
        logger.warning(f"compressed_rtf falló: {e}")

    # Fallback: intentar descompresión manual básica
    if data[:4] == b'LZFu' or b'LZFu' in data[:20]:
        try:
            import zlib
            idx = data.find(b'\x1f\x8d')
            if idx > 0:
                compressed = data[idx:]
                decompressed = zlib.decompress(compressed, -zlib.MAX_WBITS)
                logger.info("TNEF RTF: descomprimido con fallback zlib")
                return decompressed.decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Fallback descompresión falló: {e}")

    logger.warning("TNEF RTF: no se pudo descomprimir, usando como está")
    return data.decode("utf-8", errors="replace")


def _rtf_segment_to_text(segment: str) -> str:
    """
    Convierte un segmento de texto RTF puro (entre bloques \\htmltag) a texto plano.
    Elimina control words y grupos RTF que no aportan contenido visible.
    """
    # Decodificar escapes hex RTF: \'a0 → chr(0xa0), \'e9 → é, etc.
    def _hex_repl(m):
        try:
            return chr(int(m.group(1), 16))
        except ValueError:
            return ''
    segment = re.sub(r"\\'([0-9a-fA-F]{2})", _hex_repl, segment)
    # Eliminar grupos RTF completos: {\*\xxx ...} o {\xxx ...}
    segment = re.sub(r'\{[^{}]*\}', '', segment)
    # Eliminar control words: \palabra o \palabra123 seguido de espacio opcional
    segment = re.sub(r'\\[a-zA-Z]+[-]?\d*[ ]?', '', segment)
    # Eliminar llaves sueltas y backslashes restantes
    segment = segment.replace('{', '').replace('}', '').replace('\\', '')
    return segment


def _extract_html_from_outlook_rtf(rtf_str: str, logger) -> str | None:
    """
    Reconstruye el HTML completo desde RTF de Outlook.
    Outlook entrelaza:
      - {\*\htmltag <th>}  →  etiqueta HTML
      - texto RTF "Name "  →  contenido de texto entre etiquetas
      - {\*\htmltag </th>} →  cierre de etiqueta
    Hay que capturar AMBOS para reconstruir el HTML con contenido.
    """
    result = []
    last_end = 0

    for m in re.finditer(r'\{\\\*\\htmltag\d*\s*(.*?)\}', rtf_str, re.DOTALL):
        # Segmento RTF entre el último htmltag y este
        between = rtf_str[last_end:m.start()]
        if between.strip():
            text = _rtf_segment_to_text(between)
            if text.strip():
                result.append(text)

        # Contenido del bloque \htmltag (es HTML directo)
        result.append(m.group(1))
        last_end = m.end()

    if result:
        html = ''.join(result)
        if '<table' in html.lower() or '<tr' in html.lower():
            logger.info(f"RTF→HTML full: len={len(html)}")
            logger.debug("RTF→HTML primeros 600 chars: %s", html[:600])
            return html
        logger.info("RTF→HTML: sin tabla en resultado")
        return html if html.strip() else None

    # Alternativa: bloque HTML entre \htmlrtf0 ... \htmlrtf
    m = re.search(r'\\htmlrtf0\s*(.*?)\\htmlrtf', rtf_str, re.DOTALL)
    if m:
        html = _rtf_segment_to_text(m.group(1))
        if html.strip():
            logger.info("RTF→HTML: extraído bloque htmlrtf0")
            return html

    return None


def _decode_header_value(value):
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for data, charset in parts:
        if isinstance(data, bytes):
            result.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(data)
    return "".join(result)


def _connect(folder="INBOX", imap_user=None, imap_pass=None):
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    conn.login(imap_user or IMAP_USER, imap_pass or IMAP_PASS)
    conn.select(folder)
    return conn


def list_all(folder="INBOX", imap_user=None, imap_pass=None):
    conn = _connect(folder, imap_user, imap_pass)
    try:
        _, data = conn.search(None, "ALL")
        uids = data[0].split() if data[0] else []
        results = []
        for uid in uids:
            _, msg_data = conn.fetch(uid, "(BODY.PEEK[HEADER] FLAGS)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            sender = _decode_header_value(msg.get("From", ""))
            subject = _decode_header_value(msg.get("Subject", ""))
            date_str = msg.get("Date", "")
            try:
                dt = parsedate_to_datetime(date_str)
                date_iso = dt.isoformat()
            except Exception:
                date_iso = date_str
            results.append({
                "uid": uid.decode(),
                "subject": subject,
                "from": sender,
                "date": date_iso,
            })
        return list(reversed(results))
    finally:
        conn.close()
        conn.logout()


def list_unread(folder="INBOX", imap_user=None, imap_pass=None):
    conn = _connect(folder, imap_user, imap_pass)
    try:
        _, data = conn.search(None, "UNSEEN")
        uids = data[0].split() if data[0] else []
        results = []
        for uid in uids:
            _, msg_data = conn.fetch(uid, "(BODY.PEEK[HEADER] FLAGS)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            sender = _decode_header_value(msg.get("From", ""))
            subject = _decode_header_value(msg.get("Subject", ""))
            date_str = msg.get("Date", "")
            try:
                dt = parsedate_to_datetime(date_str)
                date_iso = dt.isoformat()
            except Exception:
                date_iso = date_str
            results.append({
                "uid": uid.decode(),
                "subject": subject,
                "from": sender,
                "date": date_iso,
            })
        return list(reversed(results))
    finally:
        conn.close()
        conn.logout()


_IMAP_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def list_since(days=30, folder="INBOX", imap_user=None, imap_pass=None, limit=300):
    """Lista los correos recibidos en los últimos `days` días (cabeceras + flag leído).

    El mes se escribe en inglés a mano porque IMAP SINCE no acepta locales.
    """
    from datetime import datetime, timedelta
    d = datetime.now() - timedelta(days=max(1, days))
    since = f"{d.day:02d}-{_IMAP_MONTHS[d.month - 1]}-{d.year}"

    conn = _connect(folder, imap_user, imap_pass)
    try:
        _, data = conn.search(None, "SINCE", since)
        uids = data[0].split() if data and data[0] else []
        uids = list(reversed(uids))[:limit]
        results = []
        fields = ("(FLAGS BODY.PEEK[HEADER.FIELDS "
                  "(FROM SUBJECT DATE MESSAGE-ID REPLY-TO RETURN-PATH AUTHENTICATION-RESULTS)])")
        for i in range(0, len(uids), 250):              # descarga en LOTE
            batch = b",".join(uids[i:i + 250])
            try:
                _, md = conn.fetch(batch, fields)
            except Exception:
                continue
            for item in md:
                if not (isinstance(item, tuple) and len(item) >= 2 and item[1]):
                    continue
                info = item[0].decode(errors="replace") if isinstance(item[0], bytes) else str(item[0])
                seq = (re.match(r"\s*(\d+)", info) or [None, ""])[1]
                msg = email.message_from_bytes(item[1])
                date_str = msg.get("Date", "")
                try:
                    date_iso = parsedate_to_datetime(date_str).isoformat()
                except Exception:
                    date_iso = date_str
                results.append({
                    "uid": seq,
                    "subject": _decode_header_value(msg.get("Subject", "")),
                    "from": _decode_header_value(msg.get("From", "")),
                    "date": date_iso,
                    "is_read": "\\Seen" in info,
                    "is_answered": "\\Answered" in info,
                    "message_id": (msg.get("Message-ID", "") or "").strip(),
                    "auth_results": "; ".join(msg.get_all("Authentication-Results", []) or []),
                    "reply_to": _decode_header_value(msg.get("Reply-To", "")),
                    "return_path": msg.get("Return-Path", ""),
                })
        return results
    finally:
        try:
            conn.close()
        except Exception:
            pass
        conn.logout()


_SENT_NAMES = {"sent", "sent items", "inbox.sent", "inbox.sent items", "enviados",
               "elementos enviados", "[gmail]/sent mail"}


def find_sent_folder(conn) -> str | None:
    """Localiza la carpeta de Enviados (por atributo \\Sent o por nombre común)."""
    try:
        typ, data = conn.list()
    except Exception:
        return None
    if typ != "OK" or not data:
        return None
    fallback = None
    for line in data:
        s = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
        names = re.findall(r'"([^"]*)"', s)
        name = names[-1] if names else s.split()[-1]
        if "\\sent" in s.lower():
            return name
        if name.lower() in _SENT_NAMES and fallback is None:
            fallback = name
    return fallback


_SKIP_FOLDER_TOKENS = ("trash", "papelera", "junk", "spam", "drafts", "borrador",
                       "deleted", "eliminados")
_SKIP_FOLDER_ATTRS = ("\\trash", "\\junk", "\\drafts", "\\noselect")

# Solo las cabeceras que necesita el cruce (payload mínimo → mucho más rápido)
_SENT_FIELDS = ("(BODY.PEEK[HEADER.FIELDS "
                "(MESSAGE-ID IN-REPLY-TO REFERENCES TO CC SUBJECT DATE FROM)])")


def _parse_fetch_messages(md) -> list:
    """Parsea la respuesta de un FETCH en lote → lista de email.Message."""
    out = []
    for item in md:
        if isinstance(item, tuple) and len(item) >= 2 and item[1]:
            try:
                out.append(email.message_from_bytes(item[1]))
            except Exception:
                pass
    return out


def _all_folders(conn) -> list[str]:
    """Todas las carpetas seleccionables (excluye papelera/spam/borradores)."""
    try:
        typ, data = conn.list()
    except Exception:
        return []
    if typ != "OK" or not data:
        return []
    out = []
    for line in data:
        s = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
        low = s.lower()
        if any(a in low for a in _SKIP_FOLDER_ATTRS):
            continue
        names = re.findall(r'"([^"]*)"', s)
        name = names[-1] if names else (s.split()[-1] if s.split() else "")
        if not name or name in ("/", "."):
            continue
        if any(tok in name.lower() for tok in _SKIP_FOLDER_TOKENS):
            continue
        out.append(name)
    return out


def list_sent_index(days=30, imap_user=None, imap_pass=None, limit=1200):
    """Indexa los correos ENVIADOS POR el propio buzón en CUALQUIER carpeta (no
    solo «Enviados»), por si el comercial archiva sus respuestas en carpetas.

    Filtra server-side por remitente = el propio usuario (SEARCH FROM), de modo
    que NUNCA toca correos recibidos ni descarga cuerpos. Solo lectura (EXAMINE)
    + BODY.PEEK. Devuelve [{refs, to, subject, from, date, folder}].
    """
    from datetime import datetime, timedelta
    from email.utils import getaddresses

    self_addr = (imap_user or "").strip()
    conn = _connect("INBOX", imap_user, imap_pass)
    try:
        folders = _all_folders(conn)
        d = datetime.now() - timedelta(days=max(1, days))
        since = f"{d.day:02d}-{_IMAP_MONTHS[d.month - 1]}-{d.year}"
        out = []
        for fname in folders:
            if len(out) >= limit:
                break
            try:
                conn.select(f'"{fname}"' if " " in fname else fname, readonly=True)
            except Exception:
                continue
            try:
                if self_addr:
                    _, data = conn.search(None, "SINCE", since, "FROM", self_addr)
                else:
                    _, data = conn.search(None, "SINCE", since)
            except Exception:
                continue
            uids = data[0].split() if data and data[0] else []
            if not uids:
                continue
            remaining = limit - len(out)
            uids = uids[-remaining:]                 # los más recientes
            for i in range(0, len(uids), 250):        # descarga en LOTE
                batch = b",".join(uids[i:i + 250])
                try:
                    _, md = conn.fetch(batch, _SENT_FIELDS)
                except Exception:
                    continue
                for msg in _parse_fetch_messages(md):
                    refs = set()
                    for h in ("In-Reply-To", "References"):
                        refs.update(re.findall(r"<[^>]+>", msg.get(h, "") or ""))
                    recips = [a.lower() for _, a in
                              getaddresses([msg.get("To", ""), msg.get("Cc", "")]) if a]
                    date_str = msg.get("Date", "")
                    try:
                        date_iso = parsedate_to_datetime(date_str).isoformat()
                    except Exception:
                        date_iso = date_str
                    out.append({
                        "refs": refs,
                        "to": recips,
                        "subject": _decode_header_value(msg.get("Subject", "")),
                        "from": _decode_header_value(msg.get("From", "")),
                        "date": date_iso,
                        "folder": fname,
                        "own_msgid": (msg.get("Message-ID", "") or "").strip(),
                    })
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass
        conn.logout()


def fetch_email(uid, folder="INBOX", imap_user=None, imap_pass=None):
    conn = _connect(folder, imap_user, imap_pass)
    try:
        _, msg_data = conn.fetch(uid.encode() if isinstance(uid, str) else uid, "(BODY.PEEK[])")
        raw = msg_data[0][1]
        return email.message_from_bytes(raw)
    finally:
        conn.close()
        conn.logout()


def fetch_by_msgid(folder, msgid, imap_user=None, imap_pass=None):
    """Trae UN email por su Message-ID en una carpeta concreta (solo-lectura,
    BODY.PEEK). Devuelve email.Message o None. Para ver el cuerpo de una
    respuesta enviada bajo demanda."""
    if not msgid:
        return None
    conn = _connect("INBOX", imap_user, imap_pass)
    try:
        try:
            conn.select(f'"{folder}"' if " " in (folder or "") else (folder or "INBOX"),
                        readonly=True)
        except Exception:
            return None
        try:
            _, data = conn.uid("SEARCH", None, "HEADER", "Message-ID", msgid)
        except Exception:
            return None
        uids = data[0].split() if data and data[0] else []
        if not uids:
            return None
        try:
            _, md = conn.uid("FETCH", uids[-1], "(BODY.PEEK[])")
        except Exception:
            return None
        if not md or not md[0]:
            return None
        return email.message_from_bytes(md[0][1])
    finally:
        try:
            conn.close()
        except Exception:
            pass
        conn.logout()


def fetch_raw(uid, folder="INBOX", imap_user=None, imap_pass=None) -> bytes:
    """Devuelve el email completo como bytes (para adjuntar como .eml)."""
    conn = _connect(folder, imap_user, imap_pass)
    try:
        _, msg_data = conn.fetch(uid.encode() if isinstance(uid, str) else uid, "(BODY.PEEK[])")
        return msg_data[0][1]
    finally:
        conn.close()
        conn.logout()


def mark_as_read(uid, folder="INBOX", imap_user=None, imap_pass=None):
    conn = _connect(folder, imap_user, imap_pass)
    try:
        conn.store(uid.encode() if isinstance(uid, str) else uid, "+FLAGS", "\\Seen")
    finally:
        conn.close()
        conn.logout()


def _text_table_to_html(text: str) -> str | None:
    """
    Convierte tabla del text/plain a HTML.
    Busca la sección "Documents:" y extrae tabla con headers Name, Title, P.O., etc.
    """
    lines = text.split('\n')

    # Encontrar sección "Documents:" o "Uploaded Document Table:"
    docs_idx = None
    for i, line in enumerate(lines):
        ll = line.lower()
        if 'documents:' in ll or 'uploaded document' in ll or 'document table' in ll:
            docs_idx = i
            break
    if docs_idx is None:
        return None

    # Buscar línea de headers DESPUÉS de la sección (con Name/Document No., Title, etc.)
    header_idx = None
    for i in range(docs_idx, min(docs_idx + 10, len(lines))):
        line = lines[i]
        ll = line.lower()
        has_name = 'name' in ll or 'document no' in ll or 'doc no' in ll
        has_other = 'title' in ll or 'p.o' in ll or 'revision' in ll or 'status' in ll
        if has_name and has_other:
            header_idx = i
            break
    if header_idx is None:
        return None

    header_line = lines[header_idx]

    # Separador: detectar tab o espacios múltiples
    sep = '\t' if '\t' in header_line else None

    if sep:
        raw_headers = header_line.split(sep)
    else:
        # Espacios múltiples como separador
        raw_headers = re.split(r'\s{2,}', header_line)

    headers = [h.strip() for h in raw_headers if h.strip()]

    if len(headers) < 3:
        logger.debug("TEXT→HTML headers insuficientes: %s", headers)
        return None

    logger.debug("TEXT→HTML encontrado en línea %d, headers=%s, sep=%r", header_idx, headers, sep)

    # Extraer filas de datos (después del header, hasta línea vacía o sección nueva)
    rows = []
    for line_idx in range(header_idx + 1, len(lines)):
        line = lines[line_idx].rstrip()

        # Parar si encontramos otra sección o línea vacía significativa
        if re.match(r'^[A-Z\s]+:$', line):  # Nueva sección tipo "Notes:" o "Recipients:"
            break
        if not line.strip():
            if len(rows) > 3:  # Si ya tenemos datos, salir en línea vacía
                break
            continue

        # Parsear célula
        if sep:
            cells = line.split(sep, len(headers) - 1)  # Máximo split
        else:
            cells = re.split(r'\s{2,}', line, maxsplit=len(headers) - 1)

        # Limpiar URLs y artefactos de primera celda
        cleaned = []
        for c in cells:
            c = re.sub(r'\s*<https?://[^>]+>\s*', '', c).strip()
            if len(cleaned) == 0:
                c = re.sub(r'^\s*\*+\s*', '', c).strip()
            cleaned.append(c)

        # Descartar filas de metadatos: solo tienen 1 columna con datos
        # (Date, URL suelta, número de transmittal sin columnas acompañantes)
        non_empty = sum(1 for c in cleaned if c.strip())
        if non_empty < 2:
            continue

        rows.append(cleaned)

    if not rows:
        logger.debug("TEXT→HTML no hay filas de datos")
        return None

    # Generar HTML
    html = '<html><body><table><thead><tr>'
    html += ''.join(f'<th>{h}</th>' for h in headers)
    html += '</tr></thead><tbody>'
    for row in rows:
        html += '<tr>'
        for i in range(len(headers)):
            val = row[i] if i < len(row) else ''
            html += f'<td>{val}</td>'
        html += '</tr>'
    html += '</tbody></table></body></html>'

    logger.debug("TEXT→HTML OK: %d filas", len(rows))
    return html


def get_plain_body(msg) -> str:
    """Retorna el cuerpo text/plain del mensaje, o '' si no existe."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace")
    else:
        if msg.get_content_type() == "text/plain":
            charset = msg.get_content_charset() or "utf-8"
            return msg.get_payload(decode=True).decode(charset, errors="replace")
    return ""


def get_html_body(msg):
    # Single-pass MIME tree walk
    html_parts, tnef_parts, plain_parts = [], [], []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                html_parts.append(part)
            elif ct == "application/ms-tnef":
                payload = part.get_payload(decode=True)
                if payload:
                    tnef_parts.append(payload)
            elif ct == "text/plain":
                plain_parts.append(part)
    else:
        ct = msg.get_content_type()
        if ct == "text/html":
            html_parts.append(msg)
        elif ct == "text/plain":
            plain_parts.append(msg)

    # Intento 1: text/html directo (TR, ACONEX, etc.)
    for part in html_parts:
        payload = part.get_payload(decode=True)
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")

    # Intento 2: extraer HTML de TNEF (emails GAIA/Outlook)
    for tnef_idx, tnef_data in enumerate(tnef_parts):
        try:
            tnef = TNEF(tnef_data)
            logger.debug("TNEF#%d htmlbody=%s, rtfbody=%s, body=%s, attachments=%d",
                         tnef_idx, bool(tnef.htmlbody), bool(tnef.rtfbody), bool(tnef.body), len(tnef.attachments))

            # 2a: htmlbody con contenido real → devolver directamente
            if tnef.htmlbody:
                html_str = _safe_to_str(tnef.htmlbody)
                has_table = '<table' in html_str.lower()
                has_cell_text = bool(re.search(r'<t[hd][^>]*>\s*[^<\s&]', html_str, re.IGNORECASE))
                is_empty_skeleton = has_table and not has_cell_text
                if not is_empty_skeleton:
                    logger.debug("TNEF#%d htmlbody con contenido → usar", tnef_idx)
                    return html_str
                logger.debug("TNEF#%d htmlbody es esqueleto vacío → saltar", tnef_idx)

            # 2b: buscar HTML en adjuntos TNEF (.htm/.html embebidos)
            for att in tnef.attachments:
                att_name = getattr(att, 'name', '') or ''
                if att_name.lower().endswith(('.htm', '.html')):
                    att_data = getattr(att, 'data', None)
                    if att_data:
                        html_str = _safe_to_str(att_data)
                        if '<table' in html_str.lower():
                            logger.debug("TNEF#%d adjunto HTML '%s' con tabla → usar", tnef_idx, att_name)
                            return html_str

            # 2c: rtfbody → extraer HTML (para emails GAIA que sí funcionan)
            if tnef.rtfbody:
                rtf_bytes = tnef.rtfbody if isinstance(tnef.rtfbody, bytes) else tnef.rtfbody.encode()
                rtf_str = _decompress_rtf(rtf_bytes, logger)
                html = _extract_html_from_outlook_rtf(rtf_str, logger)
                if html:
                    # Verificar que la tabla tenga datos reales (no solo asteriscos)
                    cells = re.findall(r'<t[dh][^>]*>\s*([^<]*\S[^<]*)</t[dh]>', html, re.IGNORECASE)
                    real = [c for c in cells if c.strip() not in ('', '*', 'Name')]
                    if len(real) > 0:
                        logger.debug("TNEF#%d RTF→HTML con datos reales → usar", tnef_idx)
                        return html
                    logger.debug("TNEF#%d RTF→HTML tabla sin datos reales → saltar", tnef_idx)

            # 2d: body plano de TNEF
            if tnef.body:
                body_str = _safe_to_str(tnef.body)
                html_from_text = _text_table_to_html(body_str)
                if html_from_text:
                    logger.debug("TNEF#%d body → text_table_to_html → OK", tnef_idx)
                    return html_from_text

            # 2e: adjuntos texto/RTF dentro del TNEF como último recurso
            for att in tnef.attachments:
                att_name = getattr(att, 'name', '') or ''
                att_data = getattr(att, 'data', None)
                if not att_data:
                    continue
                # Adjuntos .rtf embebidos
                if att_name.lower().endswith('.rtf'):
                    rtf_str = _safe_to_str(att_data)
                    html = _extract_html_from_outlook_rtf(rtf_str, logger)
                    if html and '<table' in html.lower():
                        logger.debug("TNEF#%d adjunto RTF '%s' → HTML → usar", tnef_idx, att_name)
                        return html
                # Adjuntos .txt embebidos
                if att_name.lower().endswith('.txt'):
                    text = _safe_to_str(att_data)
                    html_from_text = _text_table_to_html(text)
                    if html_from_text:
                        logger.debug("TNEF#%d adjunto TXT '%s' → tabla → usar", tnef_idx, att_name)
                        return html_from_text

        except Exception as e:
            logger.warning(f"Error decodificando TNEF#{tnef_idx}: {e}")
            continue

    # Intento 3: text/plain → construir HTML tabla (PRODOC, emails sin text/html ni TNEF usable)
    for part in plain_parts:
        charset = part.get_content_charset() or "utf-8"
        plain = part.get_payload(decode=True).decode(charset, errors="replace")
        html_from_text = _text_table_to_html(plain)
        if html_from_text:
            logger.debug("text/plain → HTML tabla OK")
            return html_from_text

    return ""
