"""Análisis de confianza de un correo — ¿legítimo o posible phishing?

Se basa SOLO en señales presentes en las cabeceras (sin servicios externos):

  1. Autenticación SPF/DKIM/DMARC (cabecera `Authentication-Results`, que el
     servidor de correo estampa al recibir). Es la señal más fiable: prueba
     criptográficamente que el correo viene del dominio que dice ser.
  2. Suplantación de marca: el nombre visible dice "SAP Ariba" pero el dominio
     del remitente no es de Ariba ni de confianza.
  3. Coherencia From / Reply-To.
  4. Lista de dominios de confianza: portales conocidos + allowlist del usuario.

Criterio EQUILIBRADO: solo marca 'sospechoso' ante señal fuerte (falla de
autenticación, suplantación de marca clara, o reply-to a email gratuito sin
autenticar). Minimiza falsos positivos sobre clientes reales.
"""

from __future__ import annotations

import re
from email.utils import parseaddr

VERIFICADO = "verificado"
PRECAUCION = "precaucion"
SOSPECHOSO = "sospechoso"

LEVEL_META = {
    VERIFICADO: {"label": "Verificado", "icon": "✓", "color": "#16A34A", "rank": 0},
    PRECAUCION: {"label": "Precaución", "icon": "!", "color": "#D97706", "rank": 1},
    SOSPECHOSO: {"label": "Sospechoso", "icon": "⛔", "color": "#DC2626", "rank": 2},
}

# Dominios de portales legítimos (subcadena del dominio del remitente)
PORTAL_DOMAINS = [
    "ariba.com", "jaggaer.com", "sciquest.com", "coupahost.com", "coupa.com",
    "aconex.com", "oracle.com", "oraclecloud.com", "gep.com", "ivalua.com",
    "tradeshift.com", "synertrade.com", "proactis.com", "achilles.com",
    "tungsten-network.com", "tejari.com", "vortal.biz", "negometrix.com",
]

# Tokens de marca para detectar suplantación en el nombre visible
BRAND_TOKENS = ["ariba", "jaggaer", "coupa", "aconex", "ivalua", "tradeshift",
                "proactis", "achilles", "tungsten", "tejari", "vortal",
                "negometrix", "gep smart"]

FREE_PROVIDERS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.es", "outlook.com",
    "outlook.es", "live.com", "yahoo.com", "yahoo.es", "icloud.com", "aol.com",
    "gmx.com", "gmx.es", "protonmail.com", "proton.me", "mail.com", "zoho.com",
}


def _addr(header: str) -> str:
    return (parseaddr(header or "")[1] or "").strip().lower()


def _display(header: str) -> str:
    return (parseaddr(header or "")[0] or "").strip()


def _domain(addr: str) -> str:
    return addr.split("@", 1)[1].lower() if "@" in addr else ""


def parse_auth(auth_results: str) -> dict:
    """Extrae spf/dkim/dmarc del header Authentication-Results."""
    s = (auth_results or "").lower()
    out = {}
    for key in ("spf", "dkim", "dmarc"):
        m = re.search(rf"\b{key}=([a-z]+)", s)
        out[key] = m.group(1) if m else ""
    return out


def is_portal_domain(domain: str) -> bool:
    return any(pd in domain for pd in PORTAL_DOMAINS)


def analyze(meta: dict, trusted_domains=None) -> dict:
    """Veredicto de confianza de un correo.

    `meta` necesita: from, auth_results, reply_to (opcional).
    Devuelve dict con level/score/reasons/auth/from_domain/…
    """
    trusted = {d.lower().strip() for d in (trusted_domains or []) if d}

    from_dom = _domain(_addr(meta.get("from", "")))
    display = _display(meta.get("from", ""))
    reply_dom = _domain(_addr(meta.get("reply_to", "")))
    auth = parse_auth(meta.get("auth_results", ""))

    passes = [k for k in ("spf", "dkim", "dmarc") if auth.get(k) == "pass"]
    hard_fail = [k for k in ("spf", "dkim", "dmarc") if auth.get(k) == "fail"]

    portal = is_portal_domain(from_dom)
    trusted_dom = bool(from_dom) and (from_dom in trusted or portal
                                      or any(from_dom.endswith("." + t) for t in trusted))

    # Suplantación de marca: el nombre visible nombra un portal/marca pero el
    # correo NO viene del dominio real del portal ni de un dominio de confianza.
    # Cubre tanto dominios sin relación como lookalikes ("ariba-portal.net").
    dl = display.lower()
    brand_spoof = next((tok for tok in BRAND_TOKENS
                        if tok in dl and not portal and not trusted_dom), None)

    reply_mismatch = bool(reply_dom and reply_dom != from_dom and reply_dom not in trusted)

    reasons: list[str] = []
    level = PRECAUCION

    if hard_fail:
        level = SOSPECHOSO
        reasons.append(f"Falla la autenticación ({', '.join(m.upper() for m in hard_fail)}): "
                       f"el dominio {from_dom or '—'} no autorizó este envío.")
    elif brand_spoof:
        level = SOSPECHOSO
        reasons.append(f"Posible suplantación: el nombre dice «{display}» pero el dominio "
                       f"es {from_dom or '—'}, que no es de {brand_spoof}.")
    elif reply_mismatch and not passes and reply_dom in FREE_PROVIDERS:
        level = SOSPECHOSO
        reasons.append(f"Al responder iría a {reply_dom} (distinto del remitente {from_dom}) "
                       f"y el correo no está autenticado.")
    elif trusted_dom and not hard_fail:
        level = VERIFICADO
        reasons.append("Dominio de portal/proveedor conocido."
                       if portal else "Remitente en tu lista de confianza.")
    elif auth.get("dmarc") == "pass" or ("spf" in passes and "dkim" in passes):
        level = VERIFICADO
        reasons.append(f"Autenticación verificada ({'+'.join(p.upper() for p in passes)}).")
    else:
        level = PRECAUCION
        if not any(auth.values()):
            reasons.append("Sin datos de autenticación en las cabeceras.")
        elif passes:
            reasons.append(f"Autenticación parcial ({'+'.join(p.upper() for p in passes)}).")
        else:
            reasons.append("Autenticación no concluyente.")
        if from_dom in FREE_PROVIDERS:
            reasons.append(f"Remitente de correo gratuito ({from_dom}).")

    # Aviso informativo (no cambia el nivel si no fue determinante)
    if reply_mismatch and level != SOSPECHOSO:
        reasons.append(f"Responder iría a otro dominio: {reply_dom}.")

    score = {VERIFICADO: 90, PRECAUCION: 50, SOSPECHOSO: 10}[level]
    return {
        "level": level,
        "score": score,
        "reasons": reasons,
        "auth": auth,
        "from_domain": from_dom,
        "reply_domain": reply_dom,
        "trusted": trusted_dom,
        "is_portal": portal,
    }
