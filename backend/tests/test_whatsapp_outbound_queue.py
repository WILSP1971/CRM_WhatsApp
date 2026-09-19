"""Tests de `app.core.whatsapp_outbound_queue` — SPEC-029 (cola `wa:outbound`).

Unitarios con `fakeredis` (SIN Postgres real, sin daemon Redis real, SIN
llamadas a Meta): cubren el encolado/consumo FIFO del job de envío, mismo
patrón que `tests/test_whatsapp_queue.py` (SPEC-026).
"""

from __future__ import annotations

import uuid

import fakeredis.aioredis
import pytest

from app.core.whatsapp_outbound_queue import (
    OUTBOUND_QUEUE_KEY,
    OutboundSendJob,
    dequeue_outbound_send,
    enqueue_outbound_send,
)


def test_outbound_send_job_round_trip_json_preserves_fields():
    tenant_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    job = OutboundSendJob(
        tenant_id=tenant_id, conversation_id=conversation_id, message_id=message_id
    )

    restored = OutboundSendJob.from_json(job.to_json())

    assert restored.tenant_id == tenant_id
    assert restored.conversation_id == conversation_id
    assert restored.message_id == message_id
    assert restored.job_id == job.job_id


@pytest.mark.asyncio
async def test_enqueue_then_dequeue_returns_same_job_fifo():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    message_id = uuid.uuid4()

    enqueued = await enqueue_outbound_send(
        redis_client,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=message_id,
    )
    dequeued = await dequeue_outbound_send(redis_client)

    assert dequeued is not None
    assert dequeued.job_id == enqueued.job_id
    assert dequeued.tenant_id == str(tenant_id)
    assert dequeued.conversation_id == str(conversation_id)
    assert dequeued.message_id == str(message_id)


@pytest.mark.asyncio
async def test_dequeue_empty_queue_returns_none():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    result = await dequeue_outbound_send(redis_client)

    assert result is None


@pytest.mark.asyncio
async def test_fifo_order_preserved_across_multiple_jobs():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    await enqueue_outbound_send(
        redis_client,
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id="primero",
    )
    await enqueue_outbound_send(
        redis_client,
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id="segundo",
    )

    first = await dequeue_outbound_send(redis_client)
    second = await dequeue_outbound_send(redis_client)

    assert first.message_id == "primero"
    assert second.message_id == "segundo"


def test_queue_key_matches_spec_wa_outbound():
    assert OUTBOUND_QUEUE_KEY == "wa:outbound"
