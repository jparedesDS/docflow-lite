"""DocuSign eSignature — JWT Server-to-Server (port LITE del docusign_service).

Requiere PyJWT, cryptography y requests. Credenciales en .env:
  DOCUSIGN_INTEGRATION_KEY, DOCUSIGN_USER_ID, DOCUSIGN_ACCOUNT_ID,
  DOCUSIGN_BASE_URL, DOCUSIGN_RSA_PRIVATE_KEY_PATH

Si faltan credenciales, `is_configured()` devuelve False y la vista muestra el
estado "no configurado" con las variables a rellenar.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta

import jwt
import requests

from core.config import (
    DOCUSIGN_INTEGRATION_KEY,
    DOCUSIGN_USER_ID,
    DOCUSIGN_ACCOUNT_ID,
    DOCUSIGN_BASE_URL,
    DOCUSIGN_RSA_PRIVATE_KEY_PATH,
)

logger = logging.getLogger(__name__)

# Estado → etiqueta + urgencia + color (compartido con la UI)
STATUS_META = {
    "sent":      {"label": "Enviado",    "urgency": "medium", "color": "#2563EB"},
    "delivered": {"label": "Entregado",  "urgency": "low",    "color": "#3B82F6"},
    "completed": {"label": "Completado", "urgency": "none",   "color": "#16A34A"},
    "declined":  {"label": "Rechazado",  "urgency": "high",   "color": "#DC2626"},
    "voided":    {"label": "Anulado",    "urgency": "none",   "color": "#64748B"},
    "created":   {"label": "Borrador",   "urgency": "none",   "color": "#64748B"},
    "timed_out": {"label": "Expirado",   "urgency": "high",   "color": "#D97706"},
}


def is_configured() -> bool:
    return bool(DOCUSIGN_INTEGRATION_KEY and DOCUSIGN_USER_ID and DOCUSIGN_ACCOUNT_ID)


def status_label(status: str) -> str:
    return STATUS_META.get(status, {}).get("label", status or "—")


def status_color(status: str) -> str:
    return STATUS_META.get(status, {}).get("color", "#64748B")


def kpis_from_envelopes(envelopes: list[dict]) -> dict:
    """Calcula los KPIs a partir de una lista de sobres YA descargada (sin red)."""
    counts = {s: 0 for s in STATUS_META}
    urgent = 0
    for env in envelopes:
        st = env.get("status", "created")
        counts[st] = counts.get(st, 0) + 1
        if env.get("urgency") == "high":
            urgent += 1
    return {"total": len(envelopes), "by_status": counts, "urgent": urgent}


class DocuSignService:
    """Cliente DocuSign eSignature vía JWT. Renueva el token al expirar."""

    def __init__(self):
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # ── Auth ────────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 300:
            return self._token
        if not is_configured():
            raise RuntimeError("DocuSign no configurado en .env")

        if not os.path.exists(DOCUSIGN_RSA_PRIVATE_KEY_PATH):
            raise RuntimeError(
                f"Clave RSA privada de DocuSign no encontrada en: {DOCUSIGN_RSA_PRIVATE_KEY_PATH}")
        with open(DOCUSIGN_RSA_PRIVATE_KEY_PATH, "r") as f:
            private_key = f.read()

        now = int(time.time())
        is_demo = "demo" in DOCUSIGN_BASE_URL
        auth_host = "account-d.docusign.com" if is_demo else "account.docusign.com"
        payload = {
            "iss": DOCUSIGN_INTEGRATION_KEY,
            "sub": DOCUSIGN_USER_ID,
            "aud": auth_host,
            "iat": now,
            "exp": now + 3600,
            "scope": "signature impersonation",
        }
        assertion = jwt.encode(payload, private_key, algorithm="RS256")
        resp = requests.post(
            f"https://{auth_host}/oauth/token",
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                  "assertion": assertion},
            timeout=10,
        )
        if not resp.ok:
            logger.error("DocuSign token error %s: %s", resp.status_code, resp.text)
            raise RuntimeError(f"DocuSign auth error {resp.status_code}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600)
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}",
                "Content-Type": "application/json", "Accept": "application/json"}

    def _base(self) -> str:
        return f"{DOCUSIGN_BASE_URL}/restapi/v2.1/accounts/{DOCUSIGN_ACCOUNT_ID}"

    # ── Envelopes ───────────────────────────────────────────────────────────

    def list_envelopes(self, status: str | None = None, days: int = 30) -> list[dict]:
        if days > 3650:
            from_date = "2015-01-01T00:00:00Z"
        else:
            from_date = (datetime.now(timezone.utc) - timedelta(days=days)).replace(
                hour=0, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")
        params: dict = {"from_date": from_date, "include": "recipients"}
        if status:
            params["status"] = status
        resp = requests.get(f"{self._base()}/envelopes", headers=self._headers(),
                            params=params, timeout=15)
        resp.raise_for_status()
        return [self._map_envelope(e) for e in resp.json().get("envelopes", [])]

    def get_envelope(self, envelope_id: str) -> dict:
        resp = requests.get(f"{self._base()}/envelopes/{envelope_id}",
                            headers=self._headers(),
                            params={"include": "recipients,audit_events"}, timeout=15)
        resp.raise_for_status()
        return self._map_envelope(resp.json(), full=True)

    def download_combined_pdf(self, envelope_id: str) -> bytes:
        headers = self._headers()
        headers["Accept"] = "application/pdf"
        resp = requests.get(f"{self._base()}/envelopes/{envelope_id}/documents/combined",
                            headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.content

    # ── KPIs ────────────────────────────────────────────────────────────────

    def get_kpis(self, days: int = 30) -> dict:
        envelopes = self.list_envelopes(days=days)
        counts = {s: 0 for s in STATUS_META}
        urgent = 0
        for env in envelopes:
            st = env.get("status", "created")
            counts[st] = counts.get(st, 0) + 1
            if env.get("urgency") == "high":
                urgent += 1
        return {"total": len(envelopes), "by_status": counts, "urgent": urgent, "days": days}

    # ── Normalización ───────────────────────────────────────────────────────

    def _map_envelope(self, raw: dict, full: bool = False) -> dict:
        status = raw.get("status", "created")
        meta = STATUS_META.get(status, {"label": status, "urgency": "none"})
        signers = raw.get("recipients", {}).get("signers", [])
        recipients = [{
            "name": s.get("name", ""), "email": s.get("email", ""),
            "status": s.get("status", ""), "signed_at": s.get("signedDateTime"),
        } for s in signers]
        result = {
            "id": raw.get("envelopeId", ""),
            "subject": raw.get("emailSubject", ""),
            "status": status, "status_label": meta["label"], "urgency": meta["urgency"],
            "sender": raw.get("sender", {}).get("email", ""),
            "sender_name": raw.get("sender", {}).get("userName", ""),
            "sent_at": raw.get("sentDateTime"),
            "completed_at": raw.get("completedDateTime"),
            "expires_at": raw.get("expireDateTime"),
            "recipients": recipients,
        }
        if full:
            events = raw.get("auditEvents", [])
            result["history"] = [{
                "event": e.get("eventFields", [{}])[0].get("value", ""),
                "date": e.get("logTime"),
                "user": (e.get("eventFields", [{}])[1].get("value", "")
                         if len(e.get("eventFields", [])) > 1 else ""),
            } for e in events]
        return result


_service: DocuSignService | None = None


def get_service() -> DocuSignService:
    global _service
    if _service is None:
        _service = DocuSignService()
    return _service
