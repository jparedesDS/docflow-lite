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

import html
import json
import logging
import os
import urllib.error
import urllib.request

from core import preferences as pref

logger = logging.getLogger(__name__)


def webhook_url() -> str:
    url = pref.get("teams_webhook_url") or os.getenv("TEAMS_WEBHOOK_URL", "")
    return (url or "").strip()


def is_configured() -> bool:
    return bool(webhook_url())


def _summary_html(title: str, subtitle: str, text: str, facts: list,
                  link_text: str | None = None, link_url: str | None = None) -> str:
    """Resumen en HTML para la acción «Publicar mensaje» del flowbot (Teams
    renderiza HTML básico: negrita, saltos, listas y enlaces)."""
    def esc(s):
        return html.escape(str(s))

    parts = [
        "📋 <b>DocFlow</b> &nbsp;·&nbsp; <i>Control de Documentación</i>",
        f"<b>{esc(title)}</b>",
    ]
    if subtitle:
        parts.append(f"<i>{esc(subtitle)}</i>")
    if facts:
        chips = " &nbsp;&#124;&nbsp; ".join(f"<b>{esc(v)}</b> {esc(k)}" for k, v in facts)
        parts.append(chips)
    if text:
        lines = [ln for ln in str(text).split("\n\n") if ln.strip()]
        if lines:
            items = "".join(f"<li>{esc(ln)}</li>" for ln in lines)
            parts.append(f"<ul>{items}</ul>")
    if link_text and link_url:
        parts.append(f'🔗 <a href="{esc(link_url)}">{esc(link_text)}</a>')
    return "<br>".join(parts)


def _adaptive_card(title: str, subtitle: str, text: str, facts: list,
                   link_text: str | None, link_url: str | None,
                   recipient: str | None = None) -> dict:
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
    msg = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": card,
        }],
    }
    # Campos opcionales para flujos de Power Automate que publican en chat
    # privado: `recipient` (email/UPN) y la tarjeta para mapear la acción en un
    # clic — `card` como objeto y `card_json` ya serializada (cadena JSON), que
    # es lo que espera el campo "Adaptive Card" de la acción «Publicar tarjeta
    # en un chat o canal». Un webhook de canal los ignora sin más.
    if recipient:
        msg["recipient"] = recipient
        msg["card"] = card
        msg["card_json"] = json.dumps(card, ensure_ascii=False)
        # Alternativa robusta: mensaje HTML simple para la acción «Publicar
        # mensaje» (sin JSON de tarjeta adaptable, que da problemas en el flowbot).
        msg["message_html"] = _summary_html(title, subtitle, text, facts,
                                            link_text, link_url)
    return msg


def post_card(title: str, subtitle: str = "", text: str = "", facts: list | None = None,
              link_text: str | None = None, link_url: str | None = None,
              recipient: str | None = None, timeout: int = 15) -> dict:
    """Publica una tarjeta vía el webhook configurado. Devuelve {ok, status|error}.

    `recipient` (email/UPN) es opcional: lo añade al payload para flujos de
    Power Automate que publiquen en el chat privado de esa persona; un webhook
    de canal lo ignora.
    """
    url = webhook_url()
    if not url:
        return {"ok": False, "error": "No hay webhook de Teams configurado "
                                      "(Ajustes ▸ Fuentes de datos)."}
    payload = _adaptive_card(title, subtitle, text, facts or [], link_text, link_url, recipient)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            logger.info("Teams webhook → HTTP %s", code)
            return {"ok": 200 <= code < 300, "status": code}
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace").strip()[:400]
        except Exception:
            pass
        logger.warning("Teams webhook HTTP %s: %s", exc.code, body or exc.reason)
        hint = ""
        if exc.code == 401:
            hint = (" — 401: revisa que la URL del webhook esté completa (incluido "
                    "el parámetro sig=…), que el flujo esté activado y que el "
                    "disparador permita llamadas anónimas.")
        return {"ok": False, "error": f"HTTP {exc.code}: {body or exc.reason}{hint}"}
    except Exception as exc:
        logger.warning("Error publicando en Teams: %s", exc)
        return {"ok": False, "error": str(exc)}
