"""Tests de `app.core.recording_queue` — SPEC-037 (cola `pbx:recordings:inbound`).

Unitarios con `fakeredis` (SIN Postgres real, sin daemon Redis real): cubren
el encolado/consumo FIFO del audio+metadatos crudo, mismo patrón que
`tests/test_whatsapp_queue.py`.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.core.recording_queue import (
    RECORDING_INBOUND_QUEUE_KEY,
    RecordingInboundJob,
    build_recording_inbound_job,
    dequeue_recording_inbound_event,
    enqueue_recording_inbound_event,
)


def test_recording_inbound_job_round_trip_json_preserves_fields():
    job = build_recording_inbound_job(
        call_id="call-1",
        numero="3001112222",
        numero_destino="6011234500",
        direccion="entrante",
        audio_bytes=b"audio-bytes-de-prueba",
        duracion=42,
    )

    restored = RecordingInboundJob.from_json(job.to_json())

    assert restored.call_id == "call-1"
    assert restored.numero_destino == "6011234500"
    assert restored.direccion == "entrante"
    assert restored.duracion == 42
    assert restored.audio_bytes == b"audio-bytes-de-prueba"
    assert restored.event_id == job.event_id


def test_recording_inbound_job_generates_unique_event_id():
    job_a = build_recording_inbound_job(
        call_id="a", numero="1", numero_destino="d", direccion="entrante", audio_bytes=b"x"
    )
    job_b = build_recording_inbound_job(
        call_id="b", numero="1", numero_destino="d", direccion="entrante", audio_bytes=b"x"
    )

    assert job_a.event_id != job_b.event_id


@pytest.mark.asyncio
async def test_enqueue_then_dequeue_returns_same_payload_fifo():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = build_recording_inbound_job(
        call_id="call-fifo",
        numero="300",
        numero_destino="601",
        direccion="saliente",
        audio_bytes=b"contenido-binario",
    )

    await enqueue_recording_inbound_event(redis_client, job=job)
    dequeued = await dequeue_recording_inbound_event(redis_client)

    assert dequeued is not None
    assert dequeued.call_id == "call-fifo"
    assert dequeued.audio_bytes == b"contenido-binario"


@pytest.mark.asyncio
async def test_dequeue_empty_queue_returns_none():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    result = await dequeue_recording_inbound_event(redis_client)

    assert result is None


@pytest.mark.asyncio
async def test_fifo_order_preserved_across_multiple_events():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    await enqueue_recording_inbound_event(
        redis_client,
        job=build_recording_inbound_job(
            call_id="primero", numero="1", numero_destino="d", direccion="entrante", audio_bytes=b"1"
        ),
    )
    await enqueue_recording_inbound_event(
        redis_client,
        job=build_recording_inbound_job(
            call_id="segundo", numero="1", numero_destino="d", direccion="entrante", audio_bytes=b"2"
        ),
    )

    first = await dequeue_recording_inbound_event(redis_client)
    second = await dequeue_recording_inbound_event(redis_client)

    assert first.call_id == "primero"
    assert second.call_id == "segundo"


def test_queue_key_matches_spec():
    assert RECORDING_INBOUND_QUEUE_KEY == "pbx:recordings:inbound"
