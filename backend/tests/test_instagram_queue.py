"""Tests de `app.core.instagram_queue` — SPEC-086 (cola `ig:inbound`).
Espejo EXACTO de `test_whatsapp_queue.py` (SPEC-026).

Unitarios con `fakeredis` (SIN Postgres real, sin daemon Redis real): cubren
el encolado/consumo FIFO del payload crudo.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.core.instagram_queue import (
    INBOUND_QUEUE_KEY,
    InboundInstagramJob,
    dequeue_inbound_instagram_event,
    enqueue_inbound_instagram_event,
)


def test_inbound_instagram_job_round_trip_json_preserves_fields():
    job = InboundInstagramJob(raw_body='{"hola":"mundo"}')

    restored = InboundInstagramJob.from_json(job.to_json())

    assert restored.raw_body == '{"hola":"mundo"}'
    assert restored.event_id == job.event_id


def test_inbound_instagram_job_generates_unique_event_id():
    job_a = InboundInstagramJob(raw_body="a")
    job_b = InboundInstagramJob(raw_body="b")

    assert job_a.event_id != job_b.event_id


@pytest.mark.asyncio
async def test_enqueue_then_dequeue_returns_same_payload_fifo():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    enqueued = await enqueue_inbound_instagram_event(redis_client, raw_body="evento-1")
    dequeued = await dequeue_inbound_instagram_event(redis_client)

    assert dequeued is not None
    assert dequeued.raw_body == "evento-1"
    assert dequeued.event_id == enqueued.event_id


@pytest.mark.asyncio
async def test_dequeue_empty_queue_returns_none():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    result = await dequeue_inbound_instagram_event(redis_client)

    assert result is None


@pytest.mark.asyncio
async def test_fifo_order_preserved_across_multiple_events():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    await enqueue_inbound_instagram_event(redis_client, raw_body="primero")
    await enqueue_inbound_instagram_event(redis_client, raw_body="segundo")

    first = await dequeue_inbound_instagram_event(redis_client)
    second = await dequeue_inbound_instagram_event(redis_client)

    assert first.raw_body == "primero"
    assert second.raw_body == "segundo"


def test_queue_key_matches_spec_ig_inbound():
    assert INBOUND_QUEUE_KEY == "ig:inbound"
