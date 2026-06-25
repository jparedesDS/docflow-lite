"""Notificaciones a Microsoft Teams vía webhook (Workflows / Power Automate).

Publica una Adaptive Card de resumen en un canal. La URL del webhook se
configura en Ajustes ▸ Fuentes de datos (o por la variable de entorno
TEAMS_WEBHOOK_URL).

Cómo obtener la URL (Teams Workflows, el sucesor de los conectores O365):
  Canal ▸ ··· ▸ Workflows ▸ plantilla "Publicar en un canal cuando se reciba
  una solicitud de webhook" ▸ copiar la URL generada.

Sin dependencias externas: usa urllib (stdlib). El payload es una Adaptive Card
envuelta en el formato de mensaje que esperan los flujos de Teams.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

from core import preferences as pref

logger = logging.getLogger(__name__)


def webhook_url() -> str:
    url = pref.get("teams_webhook_url") or os.getenv("TEAMS_WEBHOOK_URL", "")
    return (url or "").strip()


def is_configured() -> bool:
    return bool(webhook_url())


def _adaptive_card(title: str, subtitle: str, text: str, facts: list,
                   link_text: str | None, link_url: str | None) -> dict:
    body: list[dict] = [
        {"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": title, "wrap": True},
    ]
    if subtitle:
        body.append({"type": "TextBlock", "text": subtitle, "isSubtle": True,
                     "spacing": "None", "wrap": True})
    if text:
        body.append({"type": "TextBlock", "text": text, "wrap": True, "spacing": "Medium"})
    if facts:
        body.append({"type": "FactSet",
                     "facts": [{"title": str(k), "value": str(v)} for k, v in facts]})
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
    }
    if link_text and link_url:
        card["actions"] = [{"type": "Action.OpenUrl", "title": link_text, "url": link_url}]
    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": card,
        }],
    }


def post_card(title: str, subtitle: str = "", text: str = "", facts: list | None = None,
              link_text: str | None = None, link_url: str | None = None,
              timeout: int = 15) -> dict:
    """Publica una tarjeta en el canal configurado. Devuelve {ok, status|error}."""
    url = webhook_url()
    if not url:
        return {"ok": False, "error": "No hay webhook de Teams configurado "
                                      "(Ajustes ▸ Fuentes de datos)."}
    payload = _adaptive_card(title, subtitle, text, facts or [], link_text, link_url)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            logger.info("Teams webhook → HTTP %s", code)
            return {"ok": 200 <= code < 300, "status": code}
    except Exception as exc:
        logger.warning("Error publicando en Teams: %s", exc)
        return {"ok": False, "error": str(exc)}
