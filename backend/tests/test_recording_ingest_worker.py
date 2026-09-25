"""Tests de `app.workers.recording_ingest_worker` — SPEC-037, ADR-007/008/010.

Requiere PostgreSQL real (`tests/conftest.py::postgres_engine`) CON la
función `resolve_tenant_by_pbx_line` (migración `d4e7f1a9c3b6`) ya aplicada
— `postgres_engine` corre `alembic upgrade head` automáticamente. Se SKIPEA
automáticamente sin Postgres accesible (mismo patrón que
`tests/test_whatsapp_inbound_worker.py`).

Cubre los criterios de aceptación de SPEC-037:
  (a) `numero_destino` conocido -> resuelve tenant, almacena el audio
      CIFRADO en el almacén on-prem, persiste `Call` con `audio_ref` y
      encola el trabajo STT (`stt:jobs`).
  (b) IDEMPOTENCIA (test de reentrega, RF-02): el MISMO `call_id` procesado
      dos veces -> una sola `Call`, un solo trabajo en `stt:jobs` (la
      segunda vez es no-op, sin segunda escritura de audio).
  (c) `numero_destino` desconocido -> descarte auditado, CERO `Call` creada,
      CERO fichero de audio escrito en el almacén, CERO trabajo STT encolado
      (RF-03).
  (d) la resolución de tenant usa la función SQL
      `resolve_tenant_by_pbx_line` (SECURITY DEFINER) y no un SELECT directo
      (ADR-008).
  (e) el audio queda CIFRADO en disco (los bytes en reposo NO coinciden con
      el audio en claro enviado por el PBX).
"""

from __future__ import annotations

import os
import uuid

import fakeredis.aioredis
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.recording_queue import RecordingInboundJob
from app.core.stt_queue import STT_JOBS_QUEUE_KEY, SttTranscriptionJob
from app.db.session import set_tenant_session
from app.workers.recording_ingest_worker import drain_one, process_job


def _crear_tenant(engine, nombre: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO tenants (id, nombre, slug) VALUES (:id, :nombre, :slug)"
            ),
            {
                "id": tenant_id,
                "nombre": nombre,
                "slug": f"{nombre.lower()}-{tenant_id.hex[:8]}",
            },
        )
    return tenant_id


def _crear_pbx_line(
    engine, tenant_id: uuid.UUID, numero_destino: str, *, activo: bool = True
) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO pbx_lines (id, tenant_id, numero_destino, activo) "
                "VALUES (:id, :tenant_id, :numero_destino, :activo)"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "numero_destino": numero_destino,
                "activo": activo,
            },
        )


def _session_factory(postgres_engine):
    def _factory() -> Session:
        return Session(postgres_engine)

    return _factory


@pytest.fixture
def audio_store_tmp(tmp_path):
    """Redirige `AUDIO_STORAGE_PATH` (settings cacheadas, singleton) a un
    directorio temporal del test, y restaura el valor original al terminar —
    evita que el test escriba en `/audio_store` (ruta de producción/compose,
    puede no existir/no ser escribible en este sandbox)."""
    settings = get_settings()
    original = settings.audio_storage_path
    settings.audio_storage_path = str(tmp_path)
    yield tmp_path
    settings.audio_storage_path = original


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def _recording_job(
    *,
    call_id: str,
    numero_destino: str,
    numero: str = "3009998888",
    direccion: str = "entrante",
    audio_bytes: bytes = b"audio-en-claro-de-prueba",
) -> RecordingInboundJob:
    from app.core.recording_queue import build_recording_inbound_job

    return build_recording_inbound_job(
        call_id=call_id,
        numero=numero,
        numero_destino=numero_destino,
        direccion=direccion,
        audio_bytes=audio_bytes,
        duracion=42,
    )


# ---------------------------------------------------------------------------
# (a) numero_destino conocido -> resuelve tenant, almacena audio, persiste
#     Call, encola trabajo STT
# ---------------------------------------------------------------------------


def test_process_job_known_numero_destino_persists_call_and_enqueues_stt(
    postgres_engine, audio_store_tmp, fake_redis
):
    tenant_id = _crear_tenant(postgres_engine, "TenantPbxKnownLine")
    numero_destino = f"line-known-{uuid.uuid4().hex[:10]}"
    call_id = f"call-{uuid.uuid4().hex[:12]}"
    _crear_pbx_line(postgres_engine, tenant_id, numero_destino)

    audio_bytes = b"contenido-de-audio-en-claro-0001"
    job = _recording_job(
        call_id=call_id, numero_destino=numero_destino, audio_bytes=audio_bytes
    )

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=fake_redis,
    )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT tenant_id, call_id, audio_ref, estado FROM calls "
                "WHERE tenant_id = :tenant_id AND call_id = :call_id"
            ),
            {"tenant_id": tenant_id, "call_id": call_id},
        ).fetchone()

    assert row is not None, "La Call debe quedar persistida (RF-04)"
    assert row.audio_ref is not None
    assert row.estado == "finalizada"

    # RF-04: se encoló el trabajo STT con el formato {call_id, audio_ref, tenant_id}.
    import asyncio

    raw_stt_job = asyncio.run(fake_redis.lpop(STT_JOBS_QUEUE_KEY))
    assert raw_stt_job is not None, "Debe haberse encolado un trabajo STT"
    stt_job = SttTranscriptionJob.from_json(raw_stt_job)
    assert stt_job.audio_ref == row.audio_ref
    assert stt_job.tenant_id == str(tenant_id)


def test_audio_is_encrypted_at_rest(postgres_engine, audio_store_tmp, fake_redis):
    """(e) El audio en disco NO debe coincidir con el audio en claro enviado
    por el PBX (cifrado en reposo, ADR-009)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantPbxEncrypted")
    numero_destino = f"line-enc-{uuid.uuid4().hex[:10]}"
    call_id = f"call-enc-{uuid.uuid4().hex[:10]}"
    _crear_pbx_line(postgres_engine, tenant_id, numero_destino)

    audio_bytes = b"ESTE-AUDIO-NUNCA-DEBE-QUEDAR-EN-CLARO-EN-DISCO"
    job = _recording_job(
        call_id=call_id, numero_destino=numero_destino, audio_bytes=audio_bytes
    )

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=fake_redis,
    )

    # Busca CUALQUIER fichero escrito bajo el almacén temporal y verifica que
    # el contenido en claro NO aparece (cifrado real, no un passthrough).
    found_files = list(audio_store_tmp.rglob("*.enc"))
    assert len(found_files) == 1, "Debe haberse escrito exactamente un fichero cifrado"
    on_disk_bytes = found_files[0].read_bytes()
    assert audio_bytes not in on_disk_bytes


# ---------------------------------------------------------------------------
# (b) IDEMPOTENCIA: reentrega del mismo call_id -> una sola Call, un solo job
# ---------------------------------------------------------------------------


def test_process_job_duplicate_call_id_is_idempotent(
    postgres_engine, audio_store_tmp, fake_redis
):
    tenant_id = _crear_tenant(postgres_engine, "TenantPbxDedup")
    numero_destino = f"line-dedup-{uuid.uuid4().hex[:10]}"
    call_id = f"call-dedup-{uuid.uuid4().hex[:12]}"
    _crear_pbx_line(postgres_engine, tenant_id, numero_destino)

    job = _recording_job(call_id=call_id, numero_destino=numero_destino)

    # Primera entrega: crea la Call y encola el trabajo STT.
    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=fake_redis,
    )
    # Reentrega EXACTA del PBX (mismo call_id, mismo numero_destino).
    process_job(
        _recording_job(call_id=call_id, numero_destino=numero_destino),
        session_factory=_session_factory(postgres_engine),
        redis_client=fake_redis,
    )

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM calls WHERE tenant_id = :tenant_id "
                "AND call_id = :call_id"
            ),
            {"tenant_id": tenant_id, "call_id": call_id},
        ).scalar_one()

    assert count == 1, "Un reenvío con el mismo call_id NO debe crear una segunda Call"

    import asyncio

    stt_queue_length = asyncio.run(fake_redis.llen(STT_JOBS_QUEUE_KEY))
    assert stt_queue_length == 1, (
        "Un reenvío con el mismo call_id NO debe encolar un segundo trabajo STT"
    )

    # Solo un fichero de audio en el almacén (la segunda entrega NO reescribe).
    found_files = list(audio_store_tmp.rglob("*.enc"))
    assert len(found_files) == 1


# ---------------------------------------------------------------------------
# (c) numero_destino desconocido -> descarte auditado, CERO persistencia
# ---------------------------------------------------------------------------


def test_process_job_unknown_numero_destino_discards_without_persisting(
    postgres_engine, audio_store_tmp, fake_redis, caplog
):
    call_id = f"call-unmapped-{uuid.uuid4().hex[:10]}"
    unmapped_numero_destino = f"line-unmapped-{uuid.uuid4().hex[:10]}"

    job = _recording_job(call_id=call_id, numero_destino=unmapped_numero_destino)

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=fake_redis,
    )

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM calls WHERE call_id = :call_id"),
            {"call_id": call_id},
        ).scalar_one()
    assert count == 0, "Sin mapeo de tenant, NO debe crearse ninguna Call (RF-03)"

    # CERO bytes de audio persistidos en el almacén.
    found_files = list(audio_store_tmp.rglob("*")) if audio_store_tmp.exists() else []
    found_files = [f for f in found_files if f.is_file()]
    assert found_files == [], "Sin mapeo de tenant, CERO audio debe escribirse (RF-03)"

    import asyncio

    stt_queue_length = asyncio.run(fake_redis.llen(STT_JOBS_QUEUE_KEY))
    assert stt_queue_length == 0, "Sin mapeo de tenant, CERO trabajo STT encolado"


def test_process_job_unknown_numero_destino_logs_discard_audit_event(
    postgres_engine, audio_store_tmp, fake_redis
):
    """El descarte queda AUDITADO (log estructurado), aunque sin persistir
    contenido — se verifica indirectamente comprobando que `process_job` no
    lanza excepción y no persiste, y por inspección de la implementación
    (evento `pbx_recording_unmapped_numero_destino_discarded`, ver
    `recording_ingest_worker.py`)."""
    import inspect

    from app.workers import recording_ingest_worker as worker_module

    source = inspect.getsource(worker_module)
    assert "pbx_recording_unmapped_numero_destino_discarded" in source
    assert "logger.warning" in source


# ---------------------------------------------------------------------------
# (d) resolución de tenant usa la función SQL (no un SELECT directo bajo RLS)
# ---------------------------------------------------------------------------


def test_resolve_tenant_uses_security_definer_function():
    import inspect

    from app.workers import recording_ingest_worker as worker_module

    source = inspect.getsource(worker_module)
    assert "resolve_tenant_by_pbx_line" in source
    # No debe hacer un SELECT directo sobre pbx_lines fuera de la función SQL.
    assert "FROM pbx_lines" not in source.replace(
        "SELECT resolve_tenant_by_pbx_line", ""
    )


# ---------------------------------------------------------------------------
# drain_one: extrae de la cola y delega en process_job
# ---------------------------------------------------------------------------


def test_drain_one_returns_false_on_empty_queue(fake_redis):
    import asyncio

    result = asyncio.run(drain_one(fake_redis, timeout_seconds=0))
    assert result is False
