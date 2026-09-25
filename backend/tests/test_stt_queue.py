"""Tests de `app.core.stt_queue` — SPEC-037 encola, SPEC-038 consume (cola
`stt:jobs`).

Unitarios con `fakeredis` (SIN Postgres real, sin daemon Redis real): cubre
el contrato del mensaje `{call_id, audio_ref, tenant_id}` y el
encolado/consumo FIFO.
"""

from __future__ import annotations

import json
import time
import uuid

import fakeredis.aioredis
import pytest

from app.core.stt_queue import (
    STT_JOBS_QUEUE_KEY,
    SttTranscriptionJob,
    dequeue_stt_job,
    enqueue_stt_job,
)


def test_stt_job_round_trip_json_preserves_fields():
    call_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    job = SttTranscriptionJob(
        call_id=call_id, audio_ref="tenant/audio-1.enc", tenant_id=tenant_id
    )

    restored = SttTranscriptionJob.from_json(job.to_json())

    assert restored.call_id == call_id
    assert restored.audio_ref == "tenant/audio-1.enc"
    assert restored.tenant_id == tenant_id
    assert restored.job_id == job.job_id
    assert restored.enqueued_at_epoch_seconds == job.enqueued_at_epoch_seconds


def test_stt_job_populates_enqueued_at_epoch_seconds_at_construction_time():
    """Corrección WOLVERINE/BLACK PANTHER (SPEC-038): el timestamp de
    encolado se pobla en la CONSTRUCCIÓN del dataclass (momento real de
    encolado en `enqueue_stt_job`), no de forma aproximada más tarde en el
    worker."""
    antes = time.time()
    job = SttTranscriptionJob(
        call_id=str(uuid.uuid4()), audio_ref="ref.enc", tenant_id=str(uuid.uuid4())
    )
    despues = time.time()

    assert antes <= job.enqueued_at_epoch_seconds <= despues


def test_stt_job_from_json_tolerates_legacy_payload_without_enqueued_at():
    """Compatibilidad hacia atrás: un mensaje de un formato ANTERIOR sin
    `enqueued_at_epoch_seconds` (no debería existir en producción real —
    sistema nuevo sin mensajes en vuelo — pero se tolera por robustez) no
    debe romper la deserialización."""
    legacy_payload = json.dumps(
        {
            "job_id": str(uuid.uuid4()),
            "call_id": str(uuid.uuid4()),
            "audio_ref": "legacy-ref.enc",
            "tenant_id": str(uuid.uuid4()),
        }
    )

    antes = time.time()
    restored = SttTranscriptionJob.from_json(legacy_payload)
    despues = time.time()

    assert antes <= restored.enqueued_at_epoch_seconds <= despues


@pytest.mark.asyncio
async def test_enqueue_then_dequeue_returns_same_payload_fifo():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    call_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    enqueued = await enqueue_stt_job(
        redis_client, call_id=call_id, audio_ref="ref-1.enc", tenant_id=tenant_id
    )
    dequeued = await dequeue_stt_job(redis_client)

    assert dequeued is not None
    assert dequeued.call_id == str(call_id)
    assert dequeued.audio_ref == "ref-1.enc"
    assert dequeued.tenant_id == str(tenant_id)
    assert dequeued.job_id == enqueued.job_id
    assert dequeued.enqueued_at_epoch_seconds == enqueued.enqueued_at_epoch_seconds


@pytest.mark.asyncio
async def test_dequeue_empty_queue_returns_none():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    result = await dequeue_stt_job(redis_client)

    assert result is None


def test_queue_key_matches_spec():
    assert STT_JOBS_QUEUE_KEY == "stt:jobs"


# ---------------------------------------------------------------------------
# SPEC-055 (F2) — campo `destino` (aditivo, contrato extendido para SPEC-056)
# ---------------------------------------------------------------------------


def test_destino_defaults_to_call_prefix_when_not_specified():
    """CRÍTICO: preserva el comportamiento BYTE A BYTE de los jobs de
    llamadas existentes (Entregable #4) que no especifican `destino`."""
    call_id = str(uuid.uuid4())
    job = SttTranscriptionJob(
        call_id=call_id, audio_ref="ref.enc", tenant_id=str(uuid.uuid4())
    )

    assert job.destino == f"call:{call_id}"


def test_destino_can_be_set_explicitly_for_message_sink():
    call_id = str(uuid.uuid4())
    job = SttTranscriptionJob(
        call_id=call_id,
        audio_ref="ref.enc",
        tenant_id=str(uuid.uuid4()),
        destino=f"message:{call_id}",
    )

    assert job.destino == f"message:{call_id}"


def test_destino_round_trips_through_json():
    call_id = str(uuid.uuid4())
    job = SttTranscriptionJob(
        call_id=call_id,
        audio_ref="ref.enc",
        tenant_id=str(uuid.uuid4()),
        destino=f"message:{call_id}",
    )

    restored = SttTranscriptionJob.from_json(job.to_json())

    assert restored.destino == f"message:{call_id}"


def test_destino_legacy_payload_without_field_defaults_to_call_prefix():
    """Compatibilidad hacia atrás: un job en vuelo de un formato ANTERIOR sin
    `destino` (encolado antes de SPEC-055) no rompe la deserialización — se
    calcula el default `call:{call_id}`, igual que si se hubiera construido
    hoy sin especificarlo."""
    call_id = str(uuid.uuid4())
    legacy_payload = json.dumps(
        {
            "job_id": str(uuid.uuid4()),
            "call_id": call_id,
            "audio_ref": "legacy-ref.enc",
            "tenant_id": str(uuid.uuid4()),
            "enqueued_at_epoch_seconds": time.time(),
        }
    )

    restored = SttTranscriptionJob.from_json(legacy_payload)

    assert restored.destino == f"call:{call_id}"


@pytest.mark.asyncio
async def test_enqueue_stt_job_without_destino_preserves_call_jobs_default_behavior():
    """CRÍTICO (SPEC-055): `enqueue_stt_job` sin `destino` (uso actual de
    `recording_ingest_worker`, Entregable #4) produce el MISMO job que antes
    de esta SPEC — `destino` se calcula como `call:{call_id}`."""
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    call_id = uuid.uuid4()

    enqueued = await enqueue_stt_job(
        redis_client,
        call_id=call_id,
        audio_ref="ref-call.enc",
        tenant_id=uuid.uuid4(),
    )
    dequeued = await dequeue_stt_job(redis_client)

    assert enqueued.destino == f"call:{call_id}"
    assert dequeued.destino == f"call:{call_id}"


@pytest.mark.asyncio
async def test_enqueue_stt_job_with_destino_message_sink():
    """SPEC-055: el worker de ingesta de WhatsApp encola con
    `destino='message:{id}'` (PRODUCTOR) — el `stt_worker` (SPEC-056,
    CONSUMIDOR) leerá este campo para enrutar el sink de escritura."""
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    message_id = uuid.uuid4()

    enqueued = await enqueue_stt_job(
        redis_client,
        call_id=str(message_id),
        audio_ref="ref-message.enc",
        tenant_id=uuid.uuid4(),
        destino=f"message:{message_id}",
    )
    dequeued = await dequeue_stt_job(redis_client)

    assert enqueued.destino == f"message:{message_id}"
    assert dequeued.destino == f"message:{message_id}"
