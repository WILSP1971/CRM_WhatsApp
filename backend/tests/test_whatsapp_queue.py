"""Tests de `app.core.whatsapp_queue` — SPEC-026 (cola `wa:inbound`).

Unitarios con `fakeredis` (SIN Postgres real, sin daemon Redis real): cubren
el encolado/consumo FIFO del payload crudo, mismo patrón que
`tests/test_rag_queue.py`/`tests/test_sentiment_queue.py`.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.core.whatsapp_queue import (
    INBOUND_QUEUE_KEY,
    InboundWebhookJob,
    dequeue_inbound_webhook_event,
    enqueue_inbound_webhook_event,
)


def test_inbound_webhook_job_round_trip_json_preserves_fields():
    job = InboundWebhookJob(raw_body='{"hola":"mundo"}')

    restored = InboundWebhookJob.from_json(job.to_json())

    assert restored.raw_body == '{"hola":"mundo"}'
    assert restored.event_id == job.event_id


def test_inbound_webhook_job_generates_unique_event_id():
    job_a = InboundWebhookJob(raw_body="a")
    job_b = InboundWebhookJob(raw_body="b")

    assert job_a.event_id != job_b.event_id


@pytest.mark.asyncio
async def test_enqueue_then_dequeue_returns_same_payload_fifo():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    enqueued = await enqueue_inbound_webhook_event(redis_client, raw_body="evento-1")
    dequeued = await dequeue_inbound_webhook_event(redis_client)

    assert dequeued is not None
    assert dequeued.raw_body == "evento-1"
    assert dequeued.event_id == enqueued.event_id


@pytest.mark.asyncio
async def test_dequeue_empty_queue_returns_none():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    result = await dequeue_inbound_webhook_event(redis_client)

    assert result is None


@pytest.mark.asyncio
async def test_fifo_order_preserved_across_multiple_events():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    await enqueue_inbound_webhook_event(redis_client, raw_body="primero")
    await enqueue_inbound_webhook_event(redis_client, raw_body="segundo")

    first = await dequeue_inbound_webhook_event(redis_client)
    second = await dequeue_inbound_webhook_event(redis_client)

    assert first.raw_body == "primero"
    assert second.raw_body == "segundo"


def test_queue_key_matches_spec_wa_inbound():
    assert INBOUND_QUEUE_KEY == "wa:inbound"
