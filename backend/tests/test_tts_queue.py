"""Tests de `app.core.tts_queue` — SPEC-069 (cola `tts:jobs`).

Unitarios con `fakeredis` (SIN Postgres real, sin daemon Redis real, sin
motor Piper): cubren el encolado/consumo FIFO del job de síntesis, mismo
patrón que `tests/test_stt_queue.py`/`tests/test_whatsapp_outbound_queue.py`.
"""

from __future__ import annotations

import uuid

import fakeredis.aioredis
import pytest

from app.core.tts_queue import (
    TTS_JOB_MODO_ENVIAR,
    TTS_JOB_MODO_ESCUCHAR,
    TTS_JOBS_QUEUE_KEY,
    TtsSynthesisJob,
    dequeue_tts_job,
    enqueue_tts_job,
)


def test_tts_job_round_trip_json_preserves_fields():
    draft_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    job = TtsSynthesisJob(
        draft_id=draft_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        texto="Hola, su pedido está listo.",
        modo=TTS_JOB_MODO_ENVIAR,
    )

    restored = TtsSynthesisJob.from_json(job.to_json())

    assert restored.draft_id == draft_id
    assert restored.tenant_id == tenant_id
    assert restored.conversation_id == conversation_id
    assert restored.texto == "Hola, su pedido está listo."
    assert restored.modo == TTS_JOB_MODO_ENVIAR
    assert restored.job_id == job.job_id


def test_invalid_modo_raises_value_error():
    with pytest.raises(ValueError):
        TtsSynthesisJob(
            draft_id=str(uuid.uuid4()),
            tenant_id=str(uuid.uuid4()),
            conversation_id=str(uuid.uuid4()),
            texto="x",
            modo="enviar_ya",
        )


@pytest.mark.asyncio
async def test_enqueue_then_dequeue_returns_same_job_fifo():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    draft_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()

    enqueued = await enqueue_tts_job(
        redis_client,
        draft_id=draft_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        texto="guion aprobado",
        modo=TTS_JOB_MODO_ENVIAR,
    )
    dequeued = await dequeue_tts_job(redis_client)

    assert dequeued is not None
    assert dequeued.job_id == enqueued.job_id
    assert dequeued.draft_id == str(draft_id)
    assert dequeued.tenant_id == str(tenant_id)
    assert dequeued.conversation_id == str(conversation_id)
    assert dequeued.texto == "guion aprobado"
    assert dequeued.modo == TTS_JOB_MODO_ENVIAR


@pytest.mark.asyncio
async def test_dequeue_empty_queue_returns_none():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    result = await dequeue_tts_job(redis_client)

    assert result is None


@pytest.mark.asyncio
async def test_modo_escuchar_round_trip():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    await enqueue_tts_job(
        redis_client,
        draft_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        texto="escuchar antes de enviar",
        modo=TTS_JOB_MODO_ESCUCHAR,
    )
    dequeued = await dequeue_tts_job(redis_client)

    assert dequeued.modo == TTS_JOB_MODO_ESCUCHAR


@pytest.mark.asyncio
async def test_fifo_order_preserved_across_multiple_jobs():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    await enqueue_tts_job(
        redis_client,
        draft_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        texto="primero",
        modo=TTS_JOB_MODO_ENVIAR,
    )
    await enqueue_tts_job(
        redis_client,
        draft_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        texto="segundo",
        modo=TTS_JOB_MODO_ENVIAR,
    )

    first = await dequeue_tts_job(redis_client)
    second = await dequeue_tts_job(redis_client)

    assert first.texto == "primero"
    assert second.texto == "segundo"


def test_queue_key_matches_spec_tts_jobs():
    assert TTS_JOBS_QUEUE_KEY == "tts:jobs"


def test_from_json_tolerates_missing_enqueued_at(monkeypatch):
    """Compatibilidad hacia atrás (mismo criterio que `SttTranscriptionJob`):
    un mensaje sin `enqueued_at_epoch_seconds` no debe romper la
    deserialización."""
    import json

    raw = json.dumps(
        {
            "job_id": "abc",
            "draft_id": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
            "conversation_id": str(uuid.uuid4()),
            "texto": "x",
            "modo": TTS_JOB_MODO_ENVIAR,
        }
    )
    job = TtsSynthesisJob.from_json(raw)
    assert job.job_id == "abc"
    assert job.enqueued_at_epoch_seconds is not None
