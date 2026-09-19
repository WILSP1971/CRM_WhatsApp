"""Cola Redis de mensajes SALIENTES aprobados, pendientes de envío por Graph
API — SPEC-029, ADR-006. Consumida por `app/workers/wa_send_worker.py`.

Mismo patrón que `app.core.whatsapp_queue` (SPEC-026/027) y
`app.core.rag_queue`/`sentiment_queue`: la cola es persistente (Redis
`appendonly yes`) para que un reinicio de `api`/worker NUNCA pierda un envío
ya aprobado por el humano — el job sigue en Redis hasta que
`wa_send_worker` lo consume con éxito.

CHECKPOINT SENSIBLE (RF-02 SPEC-029): SOLO se encola un job DESPUÉS de que
`draft_review_service.approve_and_send` (SPEC-019, aprobación humana
explícita) ya persistió el `Message` saliente. Este módulo no decide cuándo
enviar — solo transporta la referencia (`message_id`) del mensaje YA
aprobado hasta el worker de envío. No contiene lógica de ventana de 24 h ni
de plantilla (eso vive en `wa_send_worker`, más cerca del cliente Graph).

CHECKPOINT C3: `REDIS_URL` viene exclusivamente de `Settings` (env). El job
NUNCA lleva el token de WhatsApp ni el contenido crudo del mensaje más allá
de lo necesario para que el worker lo relea de Postgres bajo RLS (se
transporta `message_id`/`tenant_id`/`conversation_id`, no un payload libre).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import redis.asyncio as redis_asyncio

OUTBOUND_QUEUE_KEY = "wa:outbound"


@dataclass(frozen=True)
class OutboundSendJob:
    """Job encolado tras la aprobación humana de un borrador/mensaje
    saliente por canal WhatsApp (SPEC-019 + SPEC-029).

    `message_id`/`tenant_id`/`conversation_id`: identifican el `Message` ya
    persistido (estado `estado_entrega="enviado"` en Postgres desde que se
    creó, pendiente de transporte real) que el worker debe enviar por Graph
    API. `job_id` es solo para trazabilidad en logs (no sustituye la
    idempotencia real, que se basa en que el worker solo envía mensajes SIN
    `wamid` todavía — ver `wa_send_worker.py`).
    """

    tenant_id: str
    conversation_id: str
    message_id: str
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_json(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "tenant_id": self.tenant_id,
                "conversation_id": self.conversation_id,
                "message_id": self.message_id,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "OutboundSendJob":
        data = json.loads(raw)
        return cls(
            tenant_id=data["tenant_id"],
            conversation_id=data["conversation_id"],
            message_id=data["message_id"],
            job_id=data["job_id"],
        )


async def enqueue_outbound_send(
    redis_client: redis_asyncio.Redis,
    *,
    tenant_id: uuid.UUID | str,
    conversation_id: uuid.UUID | str,
    message_id: uuid.UUID | str,
) -> OutboundSendJob:
    """Encola el envío de un mensaje YA aprobado por un humano (RF-02).

    Debe llamarse EXCLUSIVAMENTE después de que el `Message` esté persistido
    (p.ej. desde `approve_draft_endpoint`/`draft_review_service.
    approve_and_send`), nunca antes ni de forma automática.
    """
    job = OutboundSendJob(
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        message_id=str(message_id),
    )
    await redis_client.rpush(OUTBOUND_QUEUE_KEY, job.to_json())
    return job


async def dequeue_outbound_send(
    redis_client: redis_asyncio.Redis,
    *,
    timeout_seconds: int = 0,
) -> OutboundSendJob | None:
    """Extrae (bloqueante opcional) el siguiente job de envío pendiente.

    `timeout_seconds=0` hace un `LPOP` no bloqueante (usado en tests);
    `timeout_seconds>0` hace `BLPOP` (uso previsto por `wa_send_worker`).
    """
    if timeout_seconds > 0:
        result = await redis_client.blpop([OUTBOUND_QUEUE_KEY], timeout=timeout_seconds)
        if result is None:
            return None
        _, raw = result
    else:
        raw = await redis_client.lpop(OUTBOUND_QUEUE_KEY)
        if raw is None:
            return None
    return OutboundSendJob.from_json(raw)
