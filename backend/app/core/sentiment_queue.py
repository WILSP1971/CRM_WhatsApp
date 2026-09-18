"""Cola Redis para clasificación de sentimiento asíncrona — SPEC-018.

RF ("la clasificación no bloquea la recepción/persistencia del mensaje"):
tras persistir un mensaje entrante, `app.services.message_service.
create_message` encola un job LIGERO (solo `tenant_id` + `message_id`, el
mensaje YA está persistido en Postgres) en una lista Redis namespaced por
tenant y retorna de inmediato; el trabajo de hablar con el LLM local
(`AIClient.chat`, potencialmente varios cientos de ms) lo hace el proceso
worker (`app/workers/sentiment_worker.py`, servicio `sentiment_worker` del
compose) FUERA del ciclo request/response, mismo patrón que la cola de
ingesta RAG (`app.core.rag_queue`, SPEC-017).

A diferencia de `rag_queue` (que encola el texto completo del documento para
sobrevivir un reinicio de la API a mitad de un job largo), aquí el job solo
referencia el `message_id`: el mensaje ya quedó persistido de forma síncrona
ANTES de encolar, así que un reinicio de la API o del worker nunca pierde el
contenido — a lo sumo pierde la clasificación pendiente, que es idempotente
(reencolar el mismo `message_id` simplemente sobrescribe `sentimiento`/
`sentimiento_score`, sin efectos secundarios acumulativos).

Namespacing (R-23, mismo criterio que `app.core.rag_queue`): la clave de la
lista incluye el `tenant_id` para que un consumidor nunca mezcle jobs de
distintos tenants por accidente. `sentiment_queue_key` exige que `tenant_id`
sea un UUID válido antes de interpolarlo en la key Redis.

CHECKPOINT C3: `REDIS_URL` viene exclusivamente de `Settings` (env).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import redis.asyncio as redis_asyncio

_SENTIMENT_QUEUE_PREFIX = "sentiment:analyze"

# Canal de notificación ligero (mismo patrón que `rag_ingest_worker.NOTIFY_KEY`):
# el worker genérico escucha aquí para saber en qué cola de tenant hacer
# `BLPOP` a continuación, sin conocer de antemano la lista de tenants activos.
NOTIFY_KEY = "sentiment:analyze:notify"


class InvalidTenantIdError(ValueError):
    """`tenant_id` no es un UUID válido — nunca se interpola en la key Redis."""


def _validate_tenant_id(tenant_id: uuid.UUID | str) -> str:
    try:
        return str(uuid.UUID(str(tenant_id)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidTenantIdError(
            f"tenant_id inválido para la cola de sentimiento: {tenant_id!r}"
        ) from exc


def sentiment_queue_key(tenant_id: uuid.UUID | str) -> str:
    """Nombre de la lista Redis de análisis de sentimiento para un tenant."""
    return f"{_SENTIMENT_QUEUE_PREFIX}:{_validate_tenant_id(tenant_id)}"


@dataclass(frozen=True)
class SentimentJob:
    """Job de clasificación de sentimiento: referencia un mensaje ya
    persistido (el worker relee `contenido` de BD, ver docstring del módulo).
    """

    tenant_id: str
    message_id: str

    def __post_init__(self) -> None:
        _validate_tenant_id(self.tenant_id)

    def to_json(self) -> str:
        return json.dumps({"tenant_id": self.tenant_id, "message_id": self.message_id})

    @classmethod
    def from_json(cls, raw: str) -> "SentimentJob":
        data = json.loads(raw)
        return cls(tenant_id=data["tenant_id"], message_id=data["message_id"])


async def enqueue_sentiment_job(
    redis_client: redis_asyncio.Redis,
    *,
    tenant_id: uuid.UUID | str,
    message_id: uuid.UUID | str,
) -> SentimentJob:
    """Encola un job de clasificación de sentimiento (no bloqueante, RF)."""
    job = SentimentJob(
        tenant_id=_validate_tenant_id(tenant_id), message_id=str(message_id)
    )
    await redis_client.rpush(sentiment_queue_key(job.tenant_id), job.to_json())
    await redis_client.rpush(NOTIFY_KEY, job.tenant_id)
    return job


async def dequeue_sentiment_job(
    redis_client: redis_asyncio.Redis,
    *,
    tenant_id: uuid.UUID | str,
    timeout_seconds: int = 0,
) -> SentimentJob | None:
    """Extrae (bloqueante opcional) el siguiente job pendiente de un tenant.

    `timeout_seconds=0` hace un `LPOP` no bloqueante (usado en tests);
    `timeout_seconds>0` hace `BLPOP` (usado por el worker real).
    """
    key = sentiment_queue_key(tenant_id)
    if timeout_seconds > 0:
        result = await redis_client.blpop([key], timeout=timeout_seconds)
        if result is None:
            return None
        _, raw = result
    else:
        raw = await redis_client.lpop(key)
        if raw is None:
            return None
    return SentimentJob.from_json(raw)
