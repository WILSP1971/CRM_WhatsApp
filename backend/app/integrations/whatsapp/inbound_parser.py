"""Parser del payload crudo de eventos entrantes de WhatsApp Cloud API —
SPEC-027 (worker de ingesta), ADR-007.

Este módulo es PURO (sin I/O, sin Postgres, sin Redis, sin llamadas a Meta):
solo interpreta el JSON crudo (`InboundWebhookJob.raw_body`, ya encolado por
SPEC-026) y extrae los campos necesarios para la resolución de tenant y la
persistencia (SPEC-027). Vive en `app/integrations/whatsapp/` porque es parte
del módulo de transporte del canal (interpreta el formato de Meta), pero NO
importa `app.workers`/`app.services.rag`/Ollama (mismo criterio de separación
que ya aplica `webhook.py`, verificado por `check-externos-backend.sh`).

Forma del payload (WhatsApp Cloud API, formato estable de Meta):

    {
      "object": "whatsapp_business_account",
      "entry": [{
        "id": "<business_account_id>",
        "changes": [{
          "field": "messages",
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": "<id>", "display_phone_number": "..."},
            "contacts": [{"wa_id": "<wa_id>", "profile": {"name": "..."}}],
            "messages": [{
              "id": "<wamid>",
              "from": "<wa_id>",
              "timestamp": "...",
              "type": "text",
              "text": {"body": "..."}
            }],
            "statuses": [...]   # conciliación de envíos salientes -> SPEC-030,
                                 # parseado por parse_status_events (más abajo)
          }
        }]
      }]
    }

`value.messages[]` (mensajes ENTRANTES) es alcance de SPEC-027;
`value.statuses[]` (callbacks de estado de mensajes SALIENTES) es SPEC-030,
parseado por `parse_status_events` en este mismo módulo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


class InboundEventParseError(ValueError):
    """El `raw_body` no es JSON válido o no tiene la forma esperada."""


@dataclass(frozen=True)
class InboundMessageEvent:
    """Un mensaje ENTRANTE ya extraído y normalizado del payload de Meta.

    `wamid`: id de mensaje de WhatsApp (clave de idempotencia, ADR-007).
    `phone_number_id`: número RECEPTOR (base de la resolución de tenant).
    `wa_id`: identificador del contacto remitente (número de WhatsApp).
    `tipo`/`texto`: tipo del mensaje ("text", "image", ...) y cuerpo textual
    si aplica; para tipos no-texto `texto` es `None` (se persiste un
    marcador, no se descarta el mensaje).
    `contact_name`: nombre de perfil de WhatsApp del contacto, si Meta lo
    envía (`contacts[].profile.name`), solo informativo.
    """

    wamid: str
    phone_number_id: str
    wa_id: str
    tipo: str
    texto: str | None
    contact_name: str | None = None


def parse_inbound_message_events(raw_body: str) -> list[InboundMessageEvent]:
    """Extrae los mensajes ENTRANTES (`value.messages[]`) del payload crudo.

    Un solo evento de webhook puede traer varios `entry`/`changes`/mensajes
    (Meta puede agrupar varios envíos en una sola entrega); se devuelven
    TODOS los mensajes entrantes encontrados, en orden. `value.statuses[]`
    (SPEC-030) y `changes` sin `field == "messages"` se ignoran sin error:
    no son responsabilidad de este worker.

    Un payload malformado (no JSON, o sin la clave `entry`) lanza
    `InboundEventParseError` — el worker lo captura y descarta el evento sin
    reventar (RNF-05, robustez).
    """
    try:
        data = json.loads(raw_body)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InboundEventParseError(f"raw_body no es JSON válido: {exc}") from exc

    if not isinstance(data, dict) or "entry" not in data:
        raise InboundEventParseError(
            "payload sin 'entry': no es un evento de Meta válido"
        )

    events: list[InboundMessageEvent] = []

    for entry in data.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue  # otros campos (p.ej. cambios de perfil) fuera de alcance
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            phone_number_id = metadata.get("phone_number_id")
            if not phone_number_id:
                continue  # sin número receptor no hay forma de enrutar; se ignora

            contacts_by_wa_id = {
                c.get("wa_id"): (c.get("profile") or {}).get("name")
                for c in (value.get("contacts") or [])
                if c.get("wa_id")
            }

            for message in value.get("messages") or []:
                wamid = message.get("id")
                wa_id = message.get("from")
                tipo = message.get("type")
                if not wamid or not wa_id or not tipo:
                    continue  # mensaje incompleto/corrupto: se ignora, no revienta

                texto = None
                if tipo == "text":
                    texto = (message.get("text") or {}).get("body")

                events.append(
                    InboundMessageEvent(
                        wamid=wamid,
                        phone_number_id=phone_number_id,
                        wa_id=wa_id,
                        tipo=tipo,
                        texto=texto,
                        contact_name=contacts_by_wa_id.get(wa_id),
                    )
                )

    return events


@dataclass(frozen=True)
class StatusEvent:
    """Un callback de estado (`value.statuses[]`) ya extraído y normalizado
    del payload de Meta — SPEC-030.

    `wamid`: id del mensaje SALIENTE al que corresponde este status (mismo
    `wamid` persistido en `messages.wamid` al enviar, SPEC-029); es la clave
    de conciliación (ADR-007).
    `phone_number_id`: número emisor (base de la resolución de tenant, mismo
    mecanismo que `InboundMessageEvent`).
    `status`: valor crudo de Meta (`"sent" | "delivered" | "read" | "failed"`),
    sin mapear todavía al vocabulario interno (`app.models.message`) — el
    mapeo es responsabilidad del worker, no del parser (que se mantiene puro).
    `error_titles`: motivos de `errors[]` cuando `status == "failed"`
    (solo `title`/`code`, NUNCA contenido de mensajes ni PII del contacto);
    lista vacía si Meta no reporta errores o el status no es `failed`.
    """

    wamid: str
    phone_number_id: str
    status: str
    error_titles: list[str] = field(default_factory=list)


def parse_status_events(raw_body: str) -> list[StatusEvent]:
    """Extrae los callbacks de estado (`value.statuses[]`) del payload crudo
    — SPEC-030. Mismo criterio de robustez que `parse_inbound_message_events`:
    un `entry`/`change` puede traer varios statuses, se devuelven todos en
    orden; `changes` sin `field == "messages"` o sin `statuses[]` se ignoran
    sin error (no son responsabilidad de este parser).

    Un payload malformado (no JSON, o sin la clave `entry`) lanza
    `InboundEventParseError` — el worker lo captura y descarta el evento sin
    reventar, mismo contrato que `parse_inbound_message_events`.
    """
    try:
        data = json.loads(raw_body)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InboundEventParseError(f"raw_body no es JSON válido: {exc}") from exc

    if not isinstance(data, dict) or "entry" not in data:
        raise InboundEventParseError(
            "payload sin 'entry': no es un evento de Meta válido"
        )

    events: list[StatusEvent] = []

    for entry in data.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue  # los statuses de Meta llegan bajo field == "messages"
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            phone_number_id = metadata.get("phone_number_id")
            if not phone_number_id:
                continue  # sin número emisor no hay forma de enrutar; se ignora

            for status in value.get("statuses") or []:
                wamid = status.get("id")
                status_value = status.get("status")
                if not wamid or not status_value:
                    continue  # status incompleto/corrupto: se ignora, no revienta

                error_titles = [
                    err.get("title")
                    for err in (status.get("errors") or [])
                    if err.get("title")
                ]

                events.append(
                    StatusEvent(
                        wamid=wamid,
                        phone_number_id=phone_number_id,
                        status=status_value,
                        error_titles=error_titles,
                    )
                )

    return events
