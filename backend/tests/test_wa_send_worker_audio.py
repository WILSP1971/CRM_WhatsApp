"""Tests de la rama de envío de AUDIO de `app.workers.wa_send_worker` —
Entregable #6, SPEC-069, ADR-014. Extiende `tests/test_wa_send_worker.py`
(SPEC-029) reutilizando sus helpers de fixtures — MISMO patrón/criterio de
mocking (`_FakeGraphClient`, sin `httpx` real).

MARCADO PARA CI (requiere PostgreSQL real): se SKIPEA automáticamente sin
Postgres accesible.

Cubre:
  (a) job `tipo="audio"` dentro de ventana -> `send_audio_message` invocado
      con el binario leído/descifrado de `audio_store`; `wamid` persistido.
  (b) retención por defecto: tras un envío exitoso, el clip se PURGA del
      almacén (no queda persistido) — `RESPUESTA_TTS_PERSIST_ENABLED=false`.
  (c) con `RESPUESTA_TTS_PERSIST_ENABLED=true`, el clip NO se purga y
      `rag_drafts.audio_salida_ref` queda poblado (régimen SPEC-041).
  (d) fuera de ventana de 24h -> el audio NUNCA usa plantilla HSM, se
      bloquea como `failed` sin invocar la Graph API.
  (e) `audio_ref` ausente en el job -> `failed` sin invocar la Graph API.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.core.whatsapp_outbound_queue import OUTBOUND_TIPO_AUDIO, OutboundSendJob
from app.services.telefonia import audio_store
from app.workers import wa_send_worker
from tests.test_wa_send_worker import (
    _FakeGraphClient,
    _crear_contacto,
    _crear_conversacion,
    _crear_mensaje_aprobado,
    _crear_mensaje_inbound,
    _crear_tenant,
    _crear_whatsapp_account,
    _leer_mensaje,
    _session_factory,
)

_AUDIO_MIME_TYPE = "audio/ogg; codecs=opus"


@pytest.fixture
def audio_store_tmp(tmp_path):
    from app.core.config import get_settings

    settings = get_settings()
    original = settings.audio_storage_path
    settings.audio_storage_path = str(tmp_path)
    yield tmp_path
    settings.audio_storage_path = original


@pytest.fixture
def respuesta_tts_persist_disabled(monkeypatch):
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("RESPUESTA_TTS_PERSIST_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def respuesta_tts_persist_enabled(monkeypatch):
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("RESPUESTA_TTS_PERSIST_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _crear_draft_para_mensaje(
    engine, tenant_id, conversation_id, message_id
) -> uuid.UUID:
    import json

    draft_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO rag_drafts "
                "(id, tenant_id, conversation_id, query, content_original, content, "
                "model, citations, estado, respuesta_modo, sent_message_id, activo) "
                "VALUES (:id, :tenant_id, :conversation_id, 'q', 'c', 'c', "
                "'m', :citations, 'aprobado', 'audio', :sent_message_id, true)"
            ),
            {
                "id": draft_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "citations": json.dumps([]),
                "sent_message_id": message_id,
            },
        )
    return draft_id


def _audio_job(
    *, tenant_id, conversation_id, message_id, audio_ref, mime_type=_AUDIO_MIME_TYPE
):
    return OutboundSendJob(
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        message_id=str(message_id),
        tipo=OUTBOUND_TIPO_AUDIO,
        audio_ref=audio_ref,
        audio_mime_type=mime_type,
    )


# ---------------------------------------------------------------------------
# (a)/(b) Envío exitoso dentro de ventana -> send_audio_message + purga
# ---------------------------------------------------------------------------


def test_process_job_audio_within_window_sends_and_purges_by_default(
    postgres_engine, audio_store_tmp, respuesta_tts_persist_disabled
):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaSendAudioDefault")
    _crear_whatsapp_account(postgres_engine, tenant_id, f"pni-{uuid.uuid4().hex[:8]}")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573002220001")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    _crear_mensaje_inbound(
        postgres_engine,
        tenant_id,
        conversation_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    message_id = _crear_mensaje_aprobado(
        postgres_engine, tenant_id, conversation_id, contenido="Su pedido llega mañana."
    )

    audio_ref = audio_store.build_audio_ref(
        tenant_id=tenant_id, call_id=str(uuid.uuid4())
    )
    audio_store.store_audio(audio_ref=audio_ref, audio_bytes=b"clip-ogg-opus-fake")

    fake_client = _FakeGraphClient(wamid=f"wamid.AUDIO-OK-{uuid.uuid4().hex[:10]}")

    wa_send_worker.process_job(
        _audio_job(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message_id=message_id,
            audio_ref=audio_ref,
        ),
        session_factory=_session_factory(postgres_engine),
        graph_client=fake_client,
    )

    assert len(fake_client.audio_calls) == 1
    assert fake_client.audio_calls[0]["audio_bytes"] == b"clip-ogg-opus-fake"
    assert fake_client.audio_calls[0]["mime_type"] == _AUDIO_MIME_TYPE
    assert fake_client.text_calls == []
    assert fake_client.template_calls == []

    row = _leer_mensaje(postgres_engine, message_id)
    assert row.wamid == fake_client.wamid
    assert row.estado_entrega == "enviado"

    # Retención por defecto: el clip se purga tras el envío exitoso.
    with pytest.raises(audio_store.AudioStoreError):
        audio_store.load_audio(audio_ref=audio_ref)


def test_process_job_audio_with_persist_enabled_keeps_clip_and_populates_ref(
    postgres_engine, audio_store_tmp, respuesta_tts_persist_enabled
):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaSendAudioPersist")
    _crear_whatsapp_account(postgres_engine, tenant_id, f"pni-{uuid.uuid4().hex[:8]}")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573002220002")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    _crear_mensaje_inbound(
        postgres_engine,
        tenant_id,
        conversation_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    message_id = _crear_mensaje_aprobado(
        postgres_engine, tenant_id, conversation_id, contenido="Su pedido llega mañana."
    )
    draft_id = _crear_draft_para_mensaje(
        postgres_engine, tenant_id, conversation_id, message_id
    )

    audio_ref = audio_store.build_audio_ref(
        tenant_id=tenant_id, call_id=str(uuid.uuid4())
    )
    audio_store.store_audio(audio_ref=audio_ref, audio_bytes=b"clip-a-retener")

    fake_client = _FakeGraphClient(wamid=f"wamid.AUDIO-PERSIST-{uuid.uuid4().hex[:10]}")

    wa_send_worker.process_job(
        _audio_job(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message_id=message_id,
            audio_ref=audio_ref,
        ),
        session_factory=_session_factory(postgres_engine),
        graph_client=fake_client,
    )

    assert len(fake_client.audio_calls) == 1

    # El clip NO se purga con la política de auditoría activa.
    assert audio_store.load_audio(audio_ref=audio_ref) == b"clip-a-retener"

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT audio_salida_ref FROM rag_drafts WHERE id = :id"),
            {"id": draft_id},
        ).fetchone()
    assert row.audio_salida_ref == audio_ref


# ---------------------------------------------------------------------------
# (d) Fuera de ventana -> bloqueado, sin plantilla HSM para audio
# ---------------------------------------------------------------------------


def test_process_job_audio_outside_window_blocks_as_failed_never_uses_template(
    postgres_engine, audio_store_tmp, monkeypatch
):
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("WHATSAPP_TEMPLATE_NAME", "ventana_utilitaria")
    get_settings.cache_clear()

    tenant_id = _crear_tenant(postgres_engine, "TenantWaSendAudioFueraVentana")
    _crear_whatsapp_account(postgres_engine, tenant_id, f"pni-{uuid.uuid4().hex[:8]}")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573002220003")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    _crear_mensaje_inbound(
        postgres_engine,
        tenant_id,
        conversation_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    message_id = _crear_mensaje_aprobado(
        postgres_engine, tenant_id, conversation_id, contenido="Su pedido llega mañana."
    )
    audio_ref = audio_store.build_audio_ref(
        tenant_id=tenant_id, call_id=str(uuid.uuid4())
    )
    audio_store.store_audio(audio_ref=audio_ref, audio_bytes=b"clip-fuera-de-ventana")
    fake_client = _FakeGraphClient()

    try:
        wa_send_worker.process_job(
            _audio_job(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message_id=message_id,
                audio_ref=audio_ref,
            ),
            session_factory=_session_factory(postgres_engine),
            graph_client=fake_client,
        )
    finally:
        get_settings.cache_clear()

    assert fake_client.audio_calls == []
    assert fake_client.text_calls == []
    assert fake_client.template_calls == []
    row = _leer_mensaje(postgres_engine, message_id)
    assert row.estado_entrega == "failed"
    assert row.wamid is None

    # El clip NO se toca (ni se purga ni se envía) ante un bloqueo — sigue
    # disponible para un reintento manual/futuro.
    assert audio_store.load_audio(audio_ref=audio_ref) == b"clip-fuera-de-ventana"


# ---------------------------------------------------------------------------
# (e) audio_ref ausente -> failed sin invocar la Graph API
# ---------------------------------------------------------------------------


def test_process_job_audio_without_audio_ref_fails_without_calling_graph_api(
    postgres_engine, audio_store_tmp
):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaSendAudioSinRef")
    _crear_whatsapp_account(postgres_engine, tenant_id, f"pni-{uuid.uuid4().hex[:8]}")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573002220004")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    _crear_mensaje_inbound(
        postgres_engine,
        tenant_id,
        conversation_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    message_id = _crear_mensaje_aprobado(
        postgres_engine, tenant_id, conversation_id, contenido="Su pedido llega mañana."
    )
    fake_client = _FakeGraphClient()

    wa_send_worker.process_job(
        _audio_job(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message_id=message_id,
            audio_ref=None,
        ),
        session_factory=_session_factory(postgres_engine),
        graph_client=fake_client,
    )

    assert fake_client.audio_calls == []
    row = _leer_mensaje(postgres_engine, message_id)
    assert row.estado_entrega == "failed"
