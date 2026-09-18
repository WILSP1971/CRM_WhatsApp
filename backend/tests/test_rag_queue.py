"""Tests de `app.core.rag_queue` — SPEC-017 RNF-06/R-28.

Unitarios/con `fakeredis` (SIN Postgres real, sin daemon Redis real): cubren
el encolado/consumo de jobs y la validación de `tenant_id` como UUID antes de
interpolarlo en la key Redis (MAYOR, revisión BLACK PANTHER).
"""

from __future__ import annotations

import uuid

import fakeredis.aioredis
import pytest

from app.core.rag_queue import (
    IngestJob,
    InvalidTenantIdError,
    dequeue_ingest_job,
    enqueue_ingest_job,
    ingest_queue_key,
)


def test_ingest_queue_key_accepts_valid_uuid():
    tenant_id = uuid.uuid4()
    key = ingest_queue_key(tenant_id)
    assert key == f"rag:ingest:{tenant_id}"


@pytest.mark.parametrize(
    "tenant_id_invalido",
    ["no-es-un-uuid", "", "1; DROP TABLE tenants;--", None, 12345],
)
def test_ingest_queue_key_rejects_non_uuid_tenant_id(tenant_id_invalido):
    with pytest.raises(InvalidTenantIdError):
        ingest_queue_key(tenant_id_invalido)


def test_ingest_job_rejects_invalid_tenant_id_at_construction():
    with pytest.raises(InvalidTenantIdError):
        IngestJob(tenant_id="no-es-uuid", document_id=str(uuid.uuid4()), text="hola")


def test_ingest_job_round_trip_json_preserves_fields():
    tenant_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    job = IngestJob(
        tenant_id=tenant_id,
        document_id=document_id,
        text="contenido de prueba",
        chunk_size=500,
        chunk_overlap=50,
    )

    restored = IngestJob.from_json(job.to_json())

    assert restored.tenant_id == tenant_id
    assert restored.document_id == document_id
    assert restored.text == "contenido de prueba"
    assert restored.chunk_size == 500
    assert restored.chunk_overlap == 50


@pytest.mark.asyncio
async def test_enqueue_then_dequeue_returns_same_job_fifo():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()

    enqueued = await enqueue_ingest_job(
        redis_client,
        tenant_id=tenant_id,
        document_id=document_id,
        text="documento de prueba",
        chunk_size=300,
        chunk_overlap=30,
    )

    dequeued = await dequeue_ingest_job(redis_client, tenant_id=tenant_id)

    assert dequeued is not None
    assert dequeued.tenant_id == enqueued.tenant_id
    assert dequeued.document_id == str(document_id)
    assert dequeued.text == "documento de prueba"
    assert dequeued.chunk_size == 300
    assert dequeued.chunk_overlap == 30


@pytest.mark.asyncio
async def test_dequeue_empty_queue_returns_none():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant_id = uuid.uuid4()

    result = await dequeue_ingest_job(redis_client, tenant_id=tenant_id)

    assert result is None


@pytest.mark.asyncio
async def test_jobs_of_different_tenants_are_namespaced_and_isolated():
    """R-23: la cola de un tenant nunca entrega el job de otro tenant."""
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    await enqueue_ingest_job(
        redis_client, tenant_id=tenant_a, document_id=uuid.uuid4(), text="doc de A"
    )

    job_para_b = await dequeue_ingest_job(redis_client, tenant_id=tenant_b)
    job_para_a = await dequeue_ingest_job(redis_client, tenant_id=tenant_a)

    assert job_para_b is None, "FUGA CROSS-TENANT: el tenant B recibió un job de A"
    assert job_para_a is not None
    assert job_para_a.text == "doc de A"
