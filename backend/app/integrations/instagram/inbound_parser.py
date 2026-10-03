"""Parser del payload crudo de eventos entrantes de Instagram DM — SPEC-086
(F1), espejo del criterio de `app.integrations.whatsapp.inbound_parser`
(SPEC-027), pero sobre un formato de Meta DISTINTO (N-1 del SPEC-086).

Este módulo es PURO (sin I/O, sin Postgres, sin Redis, sin llamadas a Meta):
solo interpreta el JSON crudo (`InboundInstagramJob.raw_body`, ya encolado
por SPEC-086) y extrae los campos necesarios para la resolución de tenant y
la persistencia (SPEC-087, fuera de alcance aquí). Vive en
`app/integrations/instagram/` porque es parte del módulo de transporte del
canal (interpreta el formato de Meta), pero NO importa
`app.workers`/`app.services.rag`/Ollama (mismo criterio de separación que ya
aplica `webhook.py`, verificado por `check-externos-backend.sh`).

Forma del payload (Instagram Messaging API via Graph API Webhooks, DISTINTA
de WhatsApp Cloud API — NO usa `entry[].changes[].value.messages[]`):

    {
      "object": "instagram",
      "entry": [{
        "id": "<instagram_business_account_id>",
        "time": 1700000000,
        "messaging": [{
          "sender": {"id": "<sender_id>"},
          "recipient": {"id": "<instagram_business_account_id>"},
          "timestamp": 1700000000,
          "message": {
            "mid": "<mid>",
            "text": "...",
            "attachments": [{"type": "image", "payload": {"url": "..."}}]
          }
        }]
      }]
    }

La clave de routing es `recipient.id` (el `instagram_business_account_id`
receptor, análogo al `phone_number_id` de WhatsApp). El id de mensaje es
`message.mid` (análogo al `wamid`). Eventos `messaging[]` que NO sean
mensajes entrantes (echo-backs del propio negocio, `message.is_echo`, o
callbacks de estado como `delivery`/`read` sin `message`) se ignoran sin
error: no son responsabilidad de este parser (conciliación de estados
salientes es SPEC-089).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


class InboundEventParseError(ValueError):
    """El `raw_body` no es JSON válido o no tiene la forma esperada."""


@dataclass(frozen=True)
class InstagramMessageEvent:
    """Un mensaje ENTRANTE ya extraído y normalizado del payload de Meta.

    `mid`: id de mensaje de Instagram (clave de idempotencia, análogo al
    `wamid` de WhatsApp — persistido en la misma columna `messages.wamid`,
    ver docstring de `app.models.instagram_account`).
    `instagram_account_id`: `recipient.id` — cuenta de Instagram Business
    RECEPTORA (base de la resolución de tenant, análogo a `phone_number_id`).
    `sender_id`: `sender.id` — identificador del usuario de Instagram que
    envía el DM.
    `tipo`/`texto`: tipo del mensaje (`"text"` si trae `message.text`,
    `"attachment"` si solo trae `attachments[]` sin texto) y cuerpo textual
    si aplica; `texto` es `None` para mensajes sin texto (p.ej. solo media).
    `attachments`: lista normalizada de `{"type": ..., "url": ...}` extraída
    de `message.attachments[]` (insumo de SPEC-088, descarga de media).
    """

    mid: str
    instagram_account_id: str
    sender_id: str
    tipo: str
    texto: str | None
    attachments: list[dict[str, str | None]] = field(default_factory=list)


def _normalize_attachments(raw_attachments: object) -> list[dict[str, str | None]]:
    """Extrae `{"type", "url"}` de `message.attachments[]`, ignorando
    entradas malformadas sin reventar (robustez, mismo criterio que el resto
    del parser)."""
    if not isinstance(raw_attachments, list):
        return []

    normalized: list[dict[str, str | None]] = []
    for attachment in raw_attachments:
        if not isinstance(attachment, dict):
            continue
        attachment_type = attachment.get("type")
        payload = attachment.get("payload") or {}
        url = payload.get("url") if isinstance(payload, dict) else None
        normalized.append({"type": attachment_type, "url": url})
    return normalized


def parse_inbound_instagram_events(raw_body: str) -> list[InstagramMessageEvent]:
    """Extrae los mensajes ENTRANTES (`entry[].messaging[]`) del payload
    crudo de Instagram.

    Un solo evento de webhook puede traer varios `entry`/`messaging` (Meta
    puede agrupar varios envíos en una sola entrega); se devuelven TODOS los
    mensajes entrantes encontrados, en orden.

    Eventos sin `message` (p.ej. callbacks `delivery`/`read`), eco de
    mensajes propios (`message.is_echo`) y entradas sin `mid`/`sender.id`/
    `recipient.id` se ignoran sin error: no son responsabilidad de este
    parser (RF-04).

    Un payload malformado (no JSON, `object` distinto de `"instagram"`, o
    sin la clave `entry`) lanza `InboundEventParseError` — el worker lo
    captura y descarta el evento sin reventar (robustez, RF-04).
    """
    try:
        data = json.loads(raw_body)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InboundEventParseError(f"raw_body no es JSON válido: {exc}") from exc

    if not isinstance(data, dict) or "entry" not in data:
        raise InboundEventParseError(
            "payload sin 'entry': no es un evento de Meta válido"
        )

    if data.get("object") != "instagram":
        raise InboundEventParseError(
            "payload con 'object' distinto de 'instagram': formato inesperado"
        )

    events: list[InstagramMessageEvent] = []

    for entry in data.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for messaging_event in entry.get("messaging") or []:
            if not isinstance(messaging_event, dict):
                continue

            message = messaging_event.get("message")
            if not isinstance(message, dict):
                continue  # callback de status (delivery/read), no es un mensaje entrante

            if message.get("is_echo"):
                continue  # eco de un mensaje saliente propio, no entrante

            sender = messaging_event.get("sender") or {}
            recipient = messaging_event.get("recipient") or {}
            sender_id = sender.get("id") if isinstance(sender, dict) else None
            instagram_account_id = (
                recipient.get("id") if isinstance(recipient, dict) else None
            )
            mid = message.get("mid")

            if not mid or not sender_id or not instagram_account_id:
                continue  # mensaje incompleto/corrupto: se ignora, no revienta

            texto = message.get("text")
            attachments = _normalize_attachments(message.get("attachments"))
            tipo = "text" if texto else "attachment"

            events.append(
                InstagramMessageEvent(
                    mid=mid,
                    instagram_account_id=instagram_account_id,
                    sender_id=sender_id,
                    tipo=tipo,
                    texto=texto,
                    attachments=attachments,
                )
            )

    return events
