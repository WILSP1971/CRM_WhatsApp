"""Tests de `app.workers.tts_worker` — SPEC-069, ADR-014.

MARCADO PARA CI (requiere PostgreSQL real, `tests/conftest.py::
postgres_engine`, mismo patrón que `tests/test_stt_worker.py`): se SKIPEA
automáticamente sin Postgres accesible. `fakeredis` para las colas
(`tts:jobs` como entrada, `wa:outbound` como salida best-effort); el motor
Piper se MOCKEA (`app.services.telefonia.tts_engine.synthesize_to_ogg_opus`)
para no depender de pesos reales en la suite de CI general — la síntesis
REAL con Piper/ffmpeg se cubre por separado en `tests/test_tts_engine.py`.

Cubre los criterios de aceptación de SPEC-069 relativos al worker:
  (a) un job "enviar" sintetiza, persiste el clip transitorio cifrado
      (`audio_store`), marca `tts_estado="listo"` y encola `wa:outbound`
      tipo "audio" — SOLO si el draft YA tiene `sent_message_id` (invariante
      de aprobación verificado por el worker antes de despachar el envío).
  (b) un job "escuchar" sintetiza y marca `tts_estado="listo"` SIN encolar
      ningún envío.
  (c) IDEMPOTENCIA (RF-02): un segundo job para el MISMO draft ya `"listo"`
      es no-op — no se sintetiza dos veces (el motor mockeado NO se invoca
      una segunda vez).
  (d) fallo de síntesis (guion demasiado largo / motor lanza error) marca
      `tts_estado="error"` sin encolar ningún envío.
  (e) el worker NUNCA importa el cliente de subida de WhatsApp (verificado
      también por `check-externos-backend.sh`, aquí por inspección directa
      de imports del módulo).
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import fakeredis.aioredis
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.tts_queue import (
    TTS_JOB_MODO_ENVIAR,
    TTS_JOB_MODO_ESCUCHAR,
    TtsSynthesisJob,
)
from app.core.whatsapp_outbound_queue import dequeue_outbound_send
from app.services.telefonia.tts_engine import (
    SynthesisResult,
    SynthesizableTextTooLongError,
)
from app.workers import tts_worker


def _session_factory(postgres_engine):
    def _factory() -> Session:
        return Session(postgres_engine)

    return _factory


def _crear_tenant(engine, nombre: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO tenants (id, nombre, slug) VALUES (:id, :n, :s)"),
            {
                "id": tenant_id,
                "n": nombre,
                "s": f"{nombre.lower()}-{tenant_id.hex[:8]}",
            },
        )
    return tenant_id


def _crear_contacto(engine, tenant_id: uuid.UUID, telefono: str) -> uuid.UUID:
    contact_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO contacts (id, tenant_id, nombre, telefono) "
                "VALUES (:id, :tenant_id, 'Contacto TTS Worker', :telefono)"
            ),
            {"id": contact_id, "tenant_id": tenant_id, "telefono": telefono},
        )
    return contact_id


def _crear_conversacion(
    engine, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conversations (id, tenant_id, contact_id, canal, estado) "
                "VALUES (:id, :tenant_id, :contact_id, 'whatsapp', 'abierta')"
            ),
            {"id": conversation_id, "tenant_id": tenant_id, "contact_id": contact_id},
        )
    return conversation_id


def _crear_mensaje(
    engine, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> uuid.UUID:
    message_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO messages "
                "(id, tenant_id, conversation_id, remitente, contenido, estado_entrega) "
                "VALUES (:id, :tenant_id, :conversation_id, 'agente', 'Su pedido llega mañana', 'enviado')"
            ),
            {
                "id": message_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
            },
        )
    return message_id


def _crear_draft(
    engine,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    sent_message_id: uuid.UUID | None = None,
    tts_estado: str | None = None,
    content: str = "Su pedido llega mañana.",
) -> uuid.UUID:
    import json

    draft_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO rag_drafts "
                "(id, tenant_id, conversation_id, query, content_original, content, "
                "model, citations, estado, respuesta_modo, tts_estado, sent_message_id, activo) "
                "VALUES (:id, :tenant_id, :conversation_id, 'query', :content, :content, "
                "'test-model', :citations, 'aprobado', 'audio', :tts_estado, :sent_message_id, true)"
            ),
            {
                "id": draft_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "content": content,
                "citations": json.dumps([]),
                "tts_estado": tts_estado,
                "sent_message_id": sent_message_id,
            },
        )
    return draft_id


def _draft_row(engine, draft_id: uuid.UUID):
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT tts_estado, audio_salida_ref FROM rag_drafts WHERE id = :id"
            ),
            {"id": draft_id},
        ).fetchone()


def _fake_synthesis_result(texto: str) -> SynthesisResult:
    return SynthesisResult(
        ogg_opus_bytes=b"OggS-fake-clip-bytes",
        texto_normalizado=texto,
        modelo_tts="piper/es_ES-davefx-medium",
        tiempo_sintesis_segundos=0.1,
        tiempo_transcodificacion_segundos=0.05,
    )


@pytest.fixture
def audio_store_tmp(tmp_path):
    from app.core.config import get_settings

    settings = get_settings()
    original = settings.audio_storage_path
    settings.audio_storage_path = str(tmp_path)
    yield tmp_path
    settings.audio_storage_path = original


# ---------------------------------------------------------------------------
# (a) Job "enviar": sintetiza, persiste, marca listo, encola wa:outbound
# ---------------------------------------------------------------------------


def test_process_job_enviar_synthesizes_and_enqueues_outbound_audio(
    postgres_engine, audio_store_tmp
):
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsWorkerEnviar")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573001110001")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    message_id = _crear_mensaje(postgres_engine, tenant_id, conversation_id)
    draft_id = _crear_draft(
        postgres_engine, tenant_id, conversation_id, sent_message_id=message_id
    )

    # `server=` EXPLÍCITO (compartido): `process_job` encola el envío por
    # dentro de su propio `run_coroutine_best_effort` (su propio loop/
    # `asyncio.run`, ver `_dispatch_send_best_effort`); el `dequeue` de abajo
    # corre en OTRO `asyncio.run()` (otro loop) — reutilizar el MISMO
    # objeto `FakeRedis` entre dos loops revienta con `RuntimeError: ...
    # is bound to a different event loop`. Con un `FakeServer` explícito,
    # cada lado usa su propio cliente/loop apuntando al mismo estado
    # compartido (mismo criterio que `tests/test_rag_tts_api.py`).
    fake_server = fakeredis.FakeServer()
    redis_client = fakeredis.aioredis.FakeRedis(
        server=fake_server, decode_responses=True
    )
    job = TtsSynthesisJob(
        draft_id=str(draft_id),
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        texto="Su pedido llega mañana.",
        modo=TTS_JOB_MODO_ENVIAR,
    )

    with patch(
        "app.workers.tts_worker.synthesize_to_ogg_opus",
        return_value=_fake_synthesis_result("Su pedido llega mañana."),
    ) as mock_synth:
        tts_worker.process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
        )

    assert mock_synth.call_count == 1

    row = _draft_row(postgres_engine, draft_id)
    assert row.tts_estado == "listo"
    assert row.audio_salida_ref is not None

    import asyncio

    redis_for_check = fakeredis.aioredis.FakeRedis(
        server=fake_server, decode_responses=True
    )
    outbound_job = asyncio.run(dequeue_outbound_send(redis_for_check))
    assert outbound_job is not None
    assert outbound_job.tipo == "audio"
    assert outbound_job.message_id == str(message_id)
    assert outbound_job.audio_ref == row.audio_salida_ref


def test_process_job_enviar_without_sent_message_id_does_not_enqueue_send(
    postgres_engine, audio_store_tmp
):
    """Defensa en profundidad: si por alguna razón un job "enviar" llegara
    para un draft SIN `sent_message_id` (no debería ocurrir en producción —
    el endpoint solo encola tras `approve_and_send` exitoso), el worker
    sintetiza (deja el clip listo) pero NUNCA encola un envío sin un
    `Message` real que enlazar — nunca inventa un destino."""
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsWorkerSinMensaje")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573001110002")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    draft_id = _crear_draft(
        postgres_engine, tenant_id, conversation_id, sent_message_id=None
    )

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = TtsSynthesisJob(
        draft_id=str(draft_id),
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        texto="Su pedido llega mañana.",
        modo=TTS_JOB_MODO_ENVIAR,
    )

    with patch(
        "app.workers.tts_worker.synthesize_to_ogg_opus",
        return_value=_fake_synthesis_result("Su pedido llega mañana."),
    ):
        tts_worker.process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
        )

    row = _draft_row(postgres_engine, draft_id)
    assert row.tts_estado == "listo"

    import asyncio

    assert asyncio.run(dequeue_outbound_send(redis_client)) is None


# ---------------------------------------------------------------------------
# (b) Job "escuchar": sintetiza, marca listo, SIN encolar envío
# ---------------------------------------------------------------------------


def test_process_job_escuchar_synthesizes_without_sending(
    postgres_engine, audio_store_tmp
):
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsWorkerEscuchar")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573001110003")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    draft_id = _crear_draft(
        postgres_engine, tenant_id, conversation_id, sent_message_id=None
    )

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = TtsSynthesisJob(
        draft_id=str(draft_id),
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        texto="Su pedido llega mañana.",
        modo=TTS_JOB_MODO_ESCUCHAR,
    )

    with patch(
        "app.workers.tts_worker.synthesize_to_ogg_opus",
        return_value=_fake_synthesis_result("Su pedido llega mañana."),
    ) as mock_synth:
        tts_worker.process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
        )

    assert mock_synth.call_count == 1
    row = _draft_row(postgres_engine, draft_id)
    assert row.tts_estado == "listo"
    assert row.audio_salida_ref is not None

    import asyncio

    assert asyncio.run(dequeue_outbound_send(redis_client)) is None


# ---------------------------------------------------------------------------
# (c) Idempotencia (RF-02): un draft ya "listo" no se resintetiza
# ---------------------------------------------------------------------------


def test_process_job_skips_synthesis_when_already_listo(
    postgres_engine, audio_store_tmp
):
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsWorkerIdempotente")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573001110004")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    draft_id = _crear_draft(
        postgres_engine,
        tenant_id,
        conversation_id,
        sent_message_id=None,
        tts_estado="listo",
    )

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = TtsSynthesisJob(
        draft_id=str(draft_id),
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        texto="Su pedido llega mañana.",
        modo=TTS_JOB_MODO_ESCUCHAR,
    )

    with patch("app.workers.tts_worker.synthesize_to_ogg_opus") as mock_synth:
        tts_worker.process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
        )

    mock_synth.assert_not_called()


def test_process_job_skips_synthesis_when_already_generando(
    postgres_engine, audio_store_tmp
):
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsWorkerGenerando")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573001110005")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    draft_id = _crear_draft(
        postgres_engine,
        tenant_id,
        conversation_id,
        sent_message_id=None,
        tts_estado="generando",
    )

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = TtsSynthesisJob(
        draft_id=str(draft_id),
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        texto="Su pedido llega mañana.",
        modo=TTS_JOB_MODO_ESCUCHAR,
    )

    with patch("app.workers.tts_worker.synthesize_to_ogg_opus") as mock_synth:
        tts_worker.process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
        )

    mock_synth.assert_not_called()


# ---------------------------------------------------------------------------
# (d) Fallo de síntesis marca error, sin encolar envío
# ---------------------------------------------------------------------------


def test_process_job_synthesis_failure_marks_error_without_enqueueing_send(
    postgres_engine, audio_store_tmp
):
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsWorkerError")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573001110006")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    message_id = _crear_mensaje(postgres_engine, tenant_id, conversation_id)
    draft_id = _crear_draft(
        postgres_engine, tenant_id, conversation_id, sent_message_id=message_id
    )

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = TtsSynthesisJob(
        draft_id=str(draft_id),
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        texto="x" * 900,
        modo=TTS_JOB_MODO_ENVIAR,
    )

    with patch(
        "app.workers.tts_worker.synthesize_to_ogg_opus",
        side_effect=SynthesizableTextTooLongError("demasiado largo"),
    ):
        tts_worker.process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
        )

    row = _draft_row(postgres_engine, draft_id)
    assert row.tts_estado == "error"
    assert row.audio_salida_ref is None

    import asyncio

    assert asyncio.run(dequeue_outbound_send(redis_client)) is None


def test_process_job_retries_after_previous_error(postgres_engine, audio_store_tmp):
    """RF-07: un error previo NO bloquea reintentar — `tts_estado="error"`
    es un estado desde el que SÍ se puede iniciar una nueva síntesis."""
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsWorkerReintento")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573001110007")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    draft_id = _crear_draft(
        postgres_engine,
        tenant_id,
        conversation_id,
        sent_message_id=None,
        tts_estado="error",
    )

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = TtsSynthesisJob(
        draft_id=str(draft_id),
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        texto="Su pedido llega mañana.",
        modo=TTS_JOB_MODO_ESCUCHAR,
    )

    with patch(
        "app.workers.tts_worker.synthesize_to_ogg_opus",
        return_value=_fake_synthesis_result("Su pedido llega mañana."),
    ) as mock_synth:
        tts_worker.process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
        )

    mock_synth.assert_called_once()
    row = _draft_row(postgres_engine, draft_id)
    assert row.tts_estado == "listo"


# ---------------------------------------------------------------------------
# (e) El worker NUNCA importa el cliente de subida de WhatsApp
# ---------------------------------------------------------------------------


def test_tts_worker_module_never_imports_whatsapp_upload_client():
    import inspect

    source = inspect.getsource(tts_worker)
    assert "graph_client" not in source
    assert "GraphApiClient" not in source
    assert "import httpx" not in source
    assert "graph.facebook.com" not in source
