"""Tests de `app.core.sentiment_queue` — SPEC-018.

Unitarios con `fakeredis` (SIN Postgres real, sin daemon Redis real): cubren
el encolado/consumo de jobs, la notificación al worker y la validación de
`tenant_id` como UUID antes de interpolarlo en la key Redis (mismo criterio
de defensa aplicado en `app.core.rag_queue`, SPEC-017).
"""

from __future__ import annotations

import uuid

import fakeredis.aioredis
import pytest

from app.core.sentiment_queue import (
    NOTIFY_KEY,
    InvalidTenantIdError,
    SentimentJob,
    dequeue_sentiment_job,
    enqueue_sentiment_job,
    sentiment_queue_key,
)


def test_sentiment_queue_key_accepts_valid_uuid():
    tenant_id = uuid.uuid4()
    key = sentiment_queue_key(tenant_id)
    assert key == f"sentiment:analyze:{tenant_id}"


@pytest.mark.parametrize(
    "tenant_id_invalido",
    ["no-es-un-uuid", "", "1; DROP TABLE messages;--", None, 12345],
)
def test_sentiment_queue_key_rejects_non_uuid_tenant_id(tenant_id_invalido):
    with pytest.raises(InvalidTenantIdError):
        sentiment_queue_key(tenant_id_invalido)


def test_sentiment_job_rejects_invalid_tenant_id_at_construction():
    with pytest.raises(InvalidTenantIdError):
        SentimentJob(tenant_id="no-es-uuid", message_id=str(uuid.uuid4()))


def test_sentiment_job_round_trip_json_preserves_fields():
    tenant_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    job = SentimentJob(tenant_id=tenant_id, message_id=message_id)

    restored = SentimentJob.from_json(job.to_json())

    assert restored.tenant_id == tenant_id
    assert restored.message_id == message_id


@pytest.mark.asyncio
async def test_enqueue_then_dequeue_returns_same_job_fifo():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant_id = uuid.uuid4()
    message_id = uuid.uuid4()

    enqueued = await enqueue_sentiment_job(
        redis_client, tenant_id=tenant_id, message_id=message_id
    )
    dequeued = await dequeue_sentiment_job(redis_client, tenant_id=tenant_id)

    assert dequeued is not None
    assert dequeued.tenant_id == enqueued.tenant_id
    assert dequeued.message_id == str(message_id)


@pytest.mark.asyncio
async def test_enqueue_also_publishes_notification_for_worker():
    """El worker genérico escucha `NOTIFY_KEY` para saber en qué cola de
    tenant hacer `BLPOP` a continuación (mismo patrón que `rag_ingest_worker`).
    """
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant_id = uuid.uuid4()

    await enqueue_sentiment_job(
        redis_client, tenant_id=tenant_id, message_id=uuid.uuid4()
    )

    notified_tenant = await redis_client.lpop(NOTIFY_KEY)
    assert notified_tenant == str(tenant_id)


@pytest.mark.asyncio
async def test_dequeue_empty_queue_returns_none():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant_id = uuid.uuid4()

    result = await dequeue_sentiment_job(redis_client, tenant_id=tenant_id)

    assert result is None


@pytest.mark.asyncio
async def test_jobs_of_different_tenants_are_namespaced_and_isolated():
    """R-23: la cola de un tenant nunca entrega el job de otro tenant."""
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    await enqueue_sentiment_job(
        redis_client, tenant_id=tenant_a, message_id=uuid.uuid4()
    )

    job_para_b = await dequeue_sentiment_job(redis_client, tenant_id=tenant_b)
    job_para_a = await dequeue_sentiment_job(redis_client, tenant_id=tenant_a)

    assert job_para_b is None, "FUGA CROSS-TENANT: el tenant B recibió un job de A"
    assert job_para_a is not None
