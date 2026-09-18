"""Cola Redis para ingesta/indexado asíncrono de documentos RAG — SPEC-017.

RNF-06 (ingesta no bloqueante) + R-28 (reintentos idempotentes): el endpoint
HTTP de ingesta encola el job COMPLETO (tenant, documento, texto y parámetros
de chunking) en una lista Redis persistente (`redis-server --appendonly yes`,
ver `docker-compose.yml`) y responde de inmediato; el trabajo pesado
(chunking + embeddings + persistencia) lo hace el proceso worker
(`app/workers/rag_ingest_worker.py`, servicio `rag_worker` del compose) FUERA
del ciclo request/response y FUERA del proceso de la API.

Al encolar el texto dentro del propio job (no solo el id del documento), un
reinicio/caída de la API a mitad de ingesta NO pierde el trabajo: el job
sigue en Redis (persistido en disco por `appendonly yes`) hasta que el
worker lo consume (`BLPOP`) y lo procesa; si el worker falla a medias, el job
ya fue extraído de la cola pero `ingest_document` es idempotente (invalida
chunks/embeddings previos del documento antes de re-indexar, ver
`app/services/rag/ingest_service.py`) — un reencolado manual del mismo
`document_id`/texto no duplica vectores.

Namespacing (R-23, mismo criterio que `app.core.redis_client.channel_name`):
la clave de la lista incluye el `tenant_id` para que un consumidor nunca
mezcle trabajos de distintos tenants por accidente, aunque comparta la misma
conexión Redis física. `ingest_queue_key` exige que `tenant_id` sea un UUID
válido (defensa en profundidad: nunca se interpola un valor arbitrario del
cliente en el nombre de la clave Redis).

CHECKPOINT C3: `REDIS_URL` viene exclusivamente de `Settings` (env).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import redis.asyncio as redis_asyncio

from app.core.config import get_settings
from app.services.rag.chunking import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE

_INGEST_QUEUE_PREFIX = "rag:ingest"


class InvalidTenantIdError(ValueError):
    """`tenant_id` no es un UUID válido — nunca se interpola en la key Redis."""


def _validate_tenant_id(tenant_id: uuid.UUID | str) -> str:
    try:
        return str(uuid.UUID(str(tenant_id)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidTenantIdError(
            f"tenant_id inválido para la cola de ingesta RAG: {tenant_id!r}"
        ) from exc


def ingest_queue_key(tenant_id: uuid.UUID | str) -> str:
    """Nombre de la lista Redis de ingesta RAG para un tenant.

    Valida `tenant_id` como UUID ANTES de interpolarlo: una key Redis
    construida a partir de un valor no controlado podría usarse para
    namespacing arbitrario/colisión de claves entre tenants.
    """
    return f"{_INGEST_QUEUE_PREFIX}:{_validate_tenant_id(tenant_id)}"


@dataclass(frozen=True)
class IngestJob:
    """Job de ingesta completo: incluye el texto para que un reinicio de la
    API no pierda el trabajo (el job persiste en Redis hasta ser consumido).
    """

    tenant_id: str
    document_id: str
    text: str
    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP

    def __post_init__(self) -> None:
        # Valida tenant_id también al construir el job (no solo al calcular
        # la key), para fallar lo antes posible ante un job mal formado.
        _validate_tenant_id(self.tenant_id)

    def to_json(self) -> str:
        return json.dumps(
            {
                "tenant_id": self.tenant_id,
                "document_id": self.document_id,
                "text": self.text,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "IngestJob":
        data = json.loads(raw)
        return cls(
            tenant_id=data["tenant_id"],
            document_id=data["document_id"],
            text=data["text"],
            chunk_size=data.get("chunk_size", DEFAULT_CHUNK_SIZE),
            chunk_overlap=data.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP),
        )


async def enqueue_ingest_job(
    redis_client: redis_asyncio.Redis,
    *,
    tenant_id: uuid.UUID | str,
    document_id: uuid.UUID | str,
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> IngestJob:
    """Encola un job de ingesta completo (no bloqueante, RNF-06/R-28)."""
    job = IngestJob(
        tenant_id=_validate_tenant_id(tenant_id),
        document_id=str(document_id),
        text=text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    await redis_client.rpush(ingest_queue_key(job.tenant_id), job.to_json())
    return job


async def dequeue_ingest_job(
    redis_client: redis_asyncio.Redis,
    *,
    tenant_id: uuid.UUID | str,
    timeout_seconds: int = 0,
) -> IngestJob | None:
    """Extrae (bloqueante opcional) el siguiente job de ingesta de un tenant.

    `timeout_seconds=0` hace un `LPOP` no bloqueante (usado en tests);
    `timeout_seconds>0` hace `BLPOP` (usado por el worker real, RNF-06).
    """
    key = ingest_queue_key(tenant_id)
    if timeout_seconds > 0:
        result = await redis_client.blpop([key], timeout=timeout_seconds)
        if result is None:
            return None
        _, raw = result
    else:
        raw = await redis_client.lpop(key)
        if raw is None:
            return None
    return IngestJob.from_json(raw)


def get_settings_redis_url() -> str:
    """Helper explícito (evita construir la URL fuera de `Settings`, C3)."""
    return get_settings().redis_url
