"""Cola Redis para eventos entrantes crudos de WhatsApp (`wa:inbound`) —
SPEC-026 (webhook) / SPEC-027 (worker de ingesta, consumidor).

RNF-02 (ACK 200 p95 ≤ 500 ms): el endpoint `POST /api/v1/whatsapp/webhook`
NO procesa el evento inline (nada de dedup por `wamid`, resolución de
tenant, ni escritura en Postgres — eso es SPEC-027, ADR-007). Tras validar
la firma HMAC-SHA256, este módulo solo serializa el payload crudo (bytes
ya decodificados a texto) en una lista Redis persistente (mismo patrón que
`app.core.rag_queue`/`app.core.sentiment_queue`) y el endpoint responde 200
de inmediato. El worker de SPEC-027 (`BLPOP`/`LPOP` sobre `wa:inbound`) hace
el trabajo pesado FUERA del ciclo request/response, para no bloquear el ACK
que Meta espera (y evitar sus reintentos por timeout).

La cola es GLOBAL (`wa:inbound`), no namespaced por tenant: en este punto
del flujo el tenant AÚN NO se ha resuelto (eso lo hace el worker de SPEC-027
vía `resolve_tenant_by_phone_number_id`, ADR-007) — resolverlo en el propio
webhook antes de encolar violaría RNF-02 (tocaría Postgres en el request) y
duplicaría lógica que SPEC-027 ya centraliza. El job lleva un `event_id`
propio (no el `wamid`, que puede repetirse varias veces por evento y viene
DENTRO del payload) únicamente para trazabilidad/logs; la deduplicación real
por `wamid` es responsabilidad del worker (ADR-007 punto 1).

CHECKPOINT C3: `REDIS_URL` viene exclusivamente de `Settings` (env).
CHECKPOINT SENSIBLE: el job solo contiene el payload YA recibido y validado
por firma; este módulo no llama a la Graph API de Meta ni a ningún servicio
de IA (transporte de recepción, no inferencia; el egress de envío vive
exclusivamente en `app/integrations/whatsapp/`, ADR-006/SPEC-029).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import redis.asyncio as redis_asyncio

from app.core.config import get_settings

INBOUND_QUEUE_KEY = "wa:inbound"


@dataclass(frozen=True)
class InboundWebhookJob:
    """Job encolado para el worker de ingesta (SPEC-027).

    `raw_body`: el body EXACTO recibido de Meta (ya decodificado a `str`,
    UTF-8), tal cual llegó — el worker es quien lo parsea/valida de nuevo,
    sin depender de una re-serialización hecha aquí. `event_id`: identificador
    propio del job (UUID, generado al encolar) para trazabilidad en logs; NO
    sustituye la idempotencia por `wamid` que aplica el worker (ADR-007).
    """

    raw_body: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_json(self) -> str:
        return json.dumps({"event_id": self.event_id, "raw_body": self.raw_body})

    @classmethod
    def from_json(cls, raw: str) -> "InboundWebhookJob":
        data = json.loads(raw)
        return cls(raw_body=data["raw_body"], event_id=data["event_id"])


async def enqueue_inbound_webhook_event(
    redis_client: redis_asyncio.Redis,
    *,
    raw_body: str,
) -> InboundWebhookJob:
    """Encola el payload crudo del webhook (ya verificado por firma) para que
    el worker de SPEC-027 lo procese de forma asíncrona (RNF-02)."""
    job = InboundWebhookJob(raw_body=raw_body)
    await redis_client.rpush(INBOUND_QUEUE_KEY, job.to_json())
    return job


async def dequeue_inbound_webhook_event(
    redis_client: redis_asyncio.Redis,
    *,
    timeout_seconds: int = 0,
) -> InboundWebhookJob | None:
    """Extrae (bloqueante opcional) el siguiente evento crudo de la cola.

    `timeout_seconds=0` hace un `LPOP` no bloqueante (usado en tests);
    `timeout_seconds>0` hace `BLPOP` (uso previsto por el worker de SPEC-027).
    """
    if timeout_seconds > 0:
        result = await redis_client.blpop([INBOUND_QUEUE_KEY], timeout=timeout_seconds)
        if result is None:
            return None
        _, raw = result
    else:
        raw = await redis_client.lpop(INBOUND_QUEUE_KEY)
        if raw is None:
            return None
    return InboundWebhookJob.from_json(raw)


def get_settings_redis_url() -> str:
    """Helper explícito (evita construir la URL fuera de `Settings`, C3)."""
    return get_settings().redis_url
