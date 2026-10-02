"""
Tests del servicio de retención/anonimización de audio y transcripción de
llamadas (SPEC-041, extiende SPEC-021) contra PostgreSQL real.

Mismo patrón que `tests/test_retention_service.py` (SPEC-021): requiere el
`db` de `docker-compose.yml` con el esquema aplicado vía Alembic; si no hay
Postgres accesible se SKIPEAN automáticamente (ver
`tests/conftest.py::postgres_engine`).

CORRECCIÓN RLS (hallazgo BLACK PANTHER, confirmado por BLACK WIDOW/
WOLVERINE): `calls`/`call_transcripts` están en `TENANT_SCOPED_TABLES`
(`app/db/rls.py`) con RLS ENABLE+FORCE. Este módulo ahora ejerce
`run_call_retention_job`/`find_*_retention_candidates` con el fixture
`app_engine` (rol de aplicación NO-superusuario `omnicore_app`, ADR-008;
mismo rol con el que corre el job en producción), NO con `postgres_engine`
(rol owner/superusuario, SIEMPRE exento de RLS por regla fija de Postgres,
incluso con `FORCE ROW LEVEL SECURITY`). Antes de esta corrección los tests
usaban `postgres_engine` para EJERCER `run_call_retention_job`: "pasaban"
sin detectar que, con el rol real de producción, el job nunca fijaba
`app.tenant_id` y por lo tanto veía CERO filas — un falso positivo (mismo
patrón de defecto ya documentado en `test_rls_isolation.py`/
`test_whatsapp_routing.py`, ADR-008). `postgres_engine` se sigue usando SOLO
para bootstrap de fixtures (`_insert_call`/`_insert_transcript`, fuera de
cualquier RLS a propósito) y para verificar estado "administrativo" tras la
corrida (SELECT de verificación, no forma parte del camino que se prueba).

`find_audio_retention_candidates`/`find_transcript_retention_candidates` se
ejercitan aquí con una sesión de `app_engine` con `app.tenant_id` fijado
manualmente (`set_tenant_session`) — reflejan el uso interno que ahora hace
`run_call_retention_job` tenant por tenant. `run_call_retention_job` en sí
NO requiere que el llamador fije el tenant: internamente recorre todos los
tenants activos y fija `app.tenant_id` por cada uno.

Qué se verifica (criterios de aceptación de SPEC-041):
  1. Una llamada con audio reciente (dentro de la ventana) NUNCA es
     candidata, sin importar el resto de su estado.
  2. Una llamada con audio vencido SÍ es candidata a purga; una ya purgada
     (`audio_purged_at` seteado) no vuelve a serlo (idempotencia).
  3. En modo dry-run no se escribe nada (solo reporta).
  4. En modo habilitado: se aplica borrado lógico (C2) ANTES/junto con la
     purga física del blob de audio (usa `audio_store` real sobre un
     directorio temporal), se limpia `audio_ref` y se marca
     `audio_purged_at` — nunca DELETE físico de la fila `calls`.
  5. Ejecutar el job dos veces seguidas en modo habilitado es idempotente:
     la segunda corrida no encuentra candidatos ni vuelve a intentar purgar
     un blob ya borrado.
  6. Transcripción vencida se anonimiza (`segmentos` sobrescrito,
     `anonymized_at` seteado) sin DELETE físico de la fila.
  7. `run_call_retention_job` SÍ encuentra candidatos bajo RLS real (rol
     `omnicore_app`), demostrando la corrección del bloqueante RLS.

Qué se verifica ADEMÁS (criterios de aceptación de SPEC-058, ampliación al
origen mensajería, `messages.audio_ref`, MISMO job, selector ampliado):
  8. Un `Message` con audio reciente (dentro de la ventana) NUNCA es
     candidato.
  9. Un `Message` con audio vencido SÍ es candidato
     (`find_message_audio_retention_candidates`).
  10. Un `Message` ya purgado (`audio_purged_at` seteado) NO vuelve a ser
      candidato (idempotencia).
  11. `run_call_retention_job(enabled=True)` purga el audio de un `Message`
      vencido: `audio_ref` queda `NULL`, `audio_purged_at` queda seteado, y
      — la decisión de diseño clave de SPEC-058 — `Message.activo` sigue
      siendo `True` (a diferencia de `Call`, purgar el audio de un mensaje
      NO oculta el mensaje/su transcripción de texto).
  12. Ejecutar el job dos veces seguidas en modo habilitado es idempotente
      también para el origen mensajería.
  13. El plazo de retención de mensajería es configurable por parámetro
      (`audio_retention_days` reducido), mismo criterio que el de llamadas.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import set_tenant_session
from app.services.telefonia.audio_store import build_audio_ref, store_audio
from app.services.telefonia.call_retention_service import (
    find_audio_retention_candidates,
    find_message_audio_retention_candidates,
    find_transcript_retention_candidates,
    run_call_retention_job,
)


def _insert_call(
    engine,
    *,
    tenant_id,
    created_at,
    audio_ref=None,
    audio_purged_at=None,
    activo=True,
    numero="3009998888",
):
    call_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO calls "
                "(id, tenant_id, call_id, numero, direccion, estado, "
                " audio_ref, audio_purged_at, activo, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :call_id, :numero, :direccion, "
                " :estado, :audio_ref, :audio_purged_at, :activo, "
                " :created_at, :created_at)"
            ),
            {
                "id": call_id,
                "tenant_id": tenant_id,
                "call_id": f"call-{uuid.uuid4().hex[:8]}",
                "numero": numero,
                "direccion": "entrante",
                "estado": "finalizada",
                "audio_ref": audio_ref,
                "audio_purged_at": audio_purged_at,
                "activo": activo,
                "created_at": created_at,
            },
        )
    return call_id


def _insert_transcript(
    engine,
    *,
    tenant_id,
    call_row_id,
    created_at,
    anonymized_at=None,
    activo=True,
):
    transcript_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO call_transcripts "
                "(id, tenant_id, call_id, segmentos, idioma, modelo_stt, "
                " anonymized_at, activo, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :call_id, :segmentos, :idioma, "
                " :modelo_stt, :anonymized_at, :activo, :created_at, :created_at)"
            ),
            {
                "id": transcript_id,
                "tenant_id": tenant_id,
                "call_id": call_row_id,
                "segmentos": json.dumps(
                    [{"inicio": 0.0, "fin": 1.0, "texto": "Hola", "hablante": "agente"}]
                ),
                "idioma": "es",
                "modelo_stt": "faster-whisper/large-v3",
                "anonymized_at": anonymized_at,
                "activo": activo,
                "created_at": created_at,
            },
        )
    return transcript_id


def _insert_conversation(engine, *, tenant_id, contact_id, canal="whatsapp"):
    """Bootstrap mínimo de `conversations` (FK RESTRICT de `messages`),
    mismo patrón que `tests/test_messages_voice_note_data.py`."""
    conversation_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conversations (id, tenant_id, contact_id, canal) "
                "VALUES (:id, :tenant_id, :contact_id, :canal)"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "contact_id": contact_id,
                "canal": canal,
            },
        )
    return conversation_id


def _insert_message_with_audio(
    engine,
    *,
    tenant_id,
    conversation_id,
    created_at,
    audio_ref=None,
    audio_purged_at=None,
    activo=True,
    contenido="Transcripción de la nota de voz",
):
    """Inserta un `Message(tipo='audio')` directamente por SQL vía
    `postgres_engine` (bootstrap fuera de RLS, mismo criterio que
    `_insert_call`/`_insert_transcript`)."""
    message_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO messages "
                "(id, tenant_id, conversation_id, remitente, contenido, tipo, "
                " audio_ref, audio_purged_at, transcripcion_estado, activo, "
                " estado_entrega, wamid, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :conversation_id, 'contacto', "
                " :contenido, 'audio', :audio_ref, :audio_purged_at, 'ok', "
                " :activo, 'entregado', :wamid, :created_at, :created_at)"
            ),
            {
                "id": message_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "contenido": contenido,
                "audio_ref": audio_ref,
                "audio_purged_at": audio_purged_at,
                "activo": activo,
                "wamid": f"wamid.retention-test-{uuid.uuid4().hex[:16]}",
                "created_at": created_at,
            },
        )
    return message_id


def _session_with_tenant(engine, tenant_id) -> Session:
    """Sesión ORM con `app.tenant_id` fijado (`SET LOCAL`) dentro de una
    transacción explícita, usando `app_engine` (rol `omnicore_app`, ADR-008)
    — ejerce RLS real, mismo patrón que `tests/test_rls_isolation.py`."""
    session = Session(engine)
    session.begin()
    set_tenant_session(session, str(tenant_id))
    return session


def test_recent_call_with_audio_is_never_a_purge_candidate(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    recent_date = datetime.now(timezone.utc) - timedelta(days=1)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id="recent")
    call_id = _insert_call(
        postgres_engine,
        tenant_id=tenant_id,
        created_at=recent_date,
        audio_ref=audio_ref,
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        candidates = find_audio_retention_candidates(session, retention_days=30)
        session.rollback()
    assert call_id not in {c.id for c in candidates}


def test_old_call_with_audio_not_yet_purged_is_a_candidate(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id="old")
    call_id = _insert_call(
        postgres_engine, tenant_id=tenant_id, created_at=old_date, audio_ref=audio_ref
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        candidates = find_audio_retention_candidates(session, retention_days=30)
        candidate_ids = {c.id for c in candidates}
        session.rollback()
    assert call_id in candidate_ids


def test_already_purged_call_is_not_a_candidate_again(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    call_id = _insert_call(
        postgres_engine,
        tenant_id=tenant_id,
        created_at=old_date,
        audio_ref=None,
        audio_purged_at=old_date,
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        candidates = find_audio_retention_candidates(session, retention_days=30)
        session.rollback()
    assert call_id not in {c.id for c in candidates}


def test_session_without_tenant_fixed_finds_zero_candidates(
    app_engine, postgres_engine, two_tenants_with_data
):
    """Demuestra el defecto original (BLACK PANTHER): con `app_engine` (rol
    `omnicore_app`) y SIN `set_tenant_session`, la consulta ve 0 filas por
    RLS fail-closed, aunque exista una llamada vencida real en BD — esto es
    justamente lo que le pasaba a `run_call_retention_job` antes de la
    corrección, y por lo que ahora fija el tenant explícitamente por cada
    tenant activo antes de consultar."""
    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id="notenant")
    _insert_call(
        postgres_engine, tenant_id=tenant_id, created_at=old_date, audio_ref=audio_ref
    )

    with Session(app_engine) as session:
        candidates = find_audio_retention_candidates(session, retention_days=30)
    assert candidates == []


def test_dry_run_does_not_purge_audio_nor_write(
    app_engine, postgres_engine, two_tenants_with_data, tmp_path, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "audio_storage_path", str(tmp_path))

    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id="dryrun")
    store_audio(audio_ref=audio_ref, audio_bytes=b"fake-audio-bytes")
    call_id = _insert_call(
        postgres_engine, tenant_id=tenant_id, created_at=old_date, audio_ref=audio_ref
    )

    with Session(app_engine) as session:
        result = run_call_retention_job(
            session,
            audio_retention_days=30,
            transcript_retention_days=90,
            enabled=False,
        )

    assert result.dry_run is True
    assert result.audio_candidates_found >= 1
    assert result.purged_audio_call_ids == []

    # El blob NO fue borrado.
    resolved = tmp_path / audio_ref
    assert resolved.exists()

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT audio_ref, audio_purged_at, activo FROM calls WHERE id = :id"
            ),
            {"id": call_id},
        ).fetchone()
        assert row.audio_ref == audio_ref
        assert row.audio_purged_at is None


def test_enabled_run_soft_deletes_before_purging_audio_physically(
    app_engine, postgres_engine, two_tenants_with_data, tmp_path, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "audio_storage_path", str(tmp_path))

    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id="purgeme")
    store_audio(audio_ref=audio_ref, audio_bytes=b"fake-audio-bytes")
    call_id = _insert_call(
        postgres_engine,
        tenant_id=tenant_id,
        created_at=old_date,
        audio_ref=audio_ref,
        activo=True,  # aún activa — el job debe darla de baja lógica (C2)
        # ANTES/junto con la purga física.
    )

    with Session(app_engine) as session:
        result = run_call_retention_job(
            session, audio_retention_days=30, transcript_retention_days=90, enabled=True
        )

    assert result.dry_run is False
    assert str(call_id) in result.purged_audio_call_ids

    # El blob físico ya no existe (purga real).
    resolved = tmp_path / audio_ref
    assert not resolved.exists()

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT audio_ref, audio_purged_at, activo FROM calls WHERE id = :id"
            ),
            {"id": call_id},
        ).fetchone()
        assert row is not None, "La llamada fue borrada FÍSICAMENTE (viola C2)"
        assert row.audio_ref is None
        assert row.audio_purged_at is not None
        assert row.activo is False  # borrado lógico C2 aplicado


def test_enabled_run_twice_is_idempotent(
    app_engine, postgres_engine, two_tenants_with_data, tmp_path, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "audio_storage_path", str(tmp_path))

    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id="idem")
    store_audio(audio_ref=audio_ref, audio_bytes=b"fake-audio-bytes")
    _insert_call(
        postgres_engine, tenant_id=tenant_id, created_at=old_date, audio_ref=audio_ref
    )

    with Session(app_engine) as session:
        first = run_call_retention_job(
            session, audio_retention_days=30, transcript_retention_days=90, enabled=True
        )
    assert len(first.purged_audio_call_ids) >= 1

    # Segunda corrida: no debe fallar ni volver a "purgar" nada (0 candidatos).
    with Session(app_engine) as session:
        second = run_call_retention_job(
            session, audio_retention_days=30, transcript_retention_days=90, enabled=True
        )
    assert second.purged_audio_call_ids == []
    assert second.audio_candidates_found == 0


def test_old_transcript_is_anonymized_without_physical_delete(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=200)
    call_row_id = _insert_call(
        postgres_engine, tenant_id=tenant_id, created_at=old_date, audio_ref=None
    )
    transcript_id = _insert_transcript(
        postgres_engine,
        tenant_id=tenant_id,
        call_row_id=call_row_id,
        created_at=old_date,
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        candidates = find_transcript_retention_candidates(session, retention_days=90)
        assert transcript_id in {t.id for t in candidates}
        session.rollback()

    with Session(app_engine) as session:
        result = run_call_retention_job(
            session, audio_retention_days=30, transcript_retention_days=90, enabled=True
        )

    assert str(transcript_id) in result.anonymized_transcript_ids

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT segmentos, anonymized_at FROM call_transcripts WHERE id = :id"
            ),
            {"id": transcript_id},
        ).fetchone()
        assert row is not None, "La transcripción fue borrada FÍSICAMENTE (viola C2)"
        assert row.anonymized_at is not None
        segmentos = (
            row.segmentos
            if isinstance(row.segmentos, list)
            else json.loads(row.segmentos)
        )
        assert segmentos[0]["texto"] != "Hola"


# ---------------------------------------------------------------------------
# SPEC-058: ampliación del selector a `messages.audio_ref` (nota de voz de
# WhatsApp, mismo job, sin política paralela — RNF-64).
# ---------------------------------------------------------------------------


def test_recent_message_with_audio_is_never_a_purge_candidate(
    app_engine, postgres_engine, two_tenants_with_data
):
    data = two_tenants_with_data
    tenant_id = data["tenant_a_id"]
    recent_date = datetime.now(timezone.utc) - timedelta(days=1)
    conversation_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=data["contact_a_id"]
    )
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id="msg-recent")
    message_id = _insert_message_with_audio(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        created_at=recent_date,
        audio_ref=audio_ref,
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        candidates = find_message_audio_retention_candidates(session, retention_days=30)
        session.rollback()
    assert message_id not in {m.id for m in candidates}


def test_old_message_with_audio_not_yet_purged_is_a_candidate(
    app_engine, postgres_engine, two_tenants_with_data
):
    data = two_tenants_with_data
    tenant_id = data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    conversation_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=data["contact_a_id"]
    )
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id="msg-old")
    message_id = _insert_message_with_audio(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        created_at=old_date,
        audio_ref=audio_ref,
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        candidates = find_message_audio_retention_candidates(session, retention_days=30)
        candidate_ids = {m.id for m in candidates}
        session.rollback()
    assert message_id in candidate_ids


def test_already_purged_message_audio_is_not_a_candidate_again(
    app_engine, postgres_engine, two_tenants_with_data
):
    data = two_tenants_with_data
    tenant_id = data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    conversation_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=data["contact_a_id"]
    )
    message_id = _insert_message_with_audio(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        created_at=old_date,
        audio_ref=None,
        audio_purged_at=old_date,
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        candidates = find_message_audio_retention_candidates(session, retention_days=30)
        session.rollback()
    assert message_id not in {m.id for m in candidates}


def test_enabled_run_purges_message_audio_without_deactivating_message(
    app_engine, postgres_engine, two_tenants_with_data, tmp_path, monkeypatch
):
    """Criterio de aceptación clave de SPEC-058: purgar el audio de un
    `Message` NO lo desactiva (a diferencia de `Call`, donde el audio ES el
    artefacto principal) — el texto transcrito sigue visible en el
    historial de la conversación."""
    settings = get_settings()
    monkeypatch.setattr(settings, "audio_storage_path", str(tmp_path))

    data = two_tenants_with_data
    tenant_id = data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    conversation_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=data["contact_a_id"]
    )
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id="msg-purgeme")
    store_audio(audio_ref=audio_ref, audio_bytes=b"fake-voice-note-bytes")
    message_id = _insert_message_with_audio(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        created_at=old_date,
        audio_ref=audio_ref,
        activo=True,
    )

    with Session(app_engine) as session:
        result = run_call_retention_job(
            session, audio_retention_days=30, transcript_retention_days=90, enabled=True
        )

    assert result.dry_run is False
    assert str(message_id) in result.purged_message_audio_ids

    # El blob físico ya no existe (purga real).
    resolved = tmp_path / audio_ref
    assert not resolved.exists()

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT audio_ref, audio_purged_at, activo, contenido "
                "FROM messages WHERE id = :id"
            ),
            {"id": message_id},
        ).fetchone()
        assert row is not None, "El Message fue borrado FÍSICAMENTE (viola C2)"
        assert row.audio_ref is None
        assert row.audio_purged_at is not None
        # Decisión de diseño clave de SPEC-058 (NO reabrir): purgar el audio
        # de un Message NUNCA lo desactiva; su texto transcrito sigue vigente.
        assert row.activo is True
        assert row.contenido == "Transcripción de la nota de voz"


def test_message_audio_run_twice_is_idempotent(
    app_engine, postgres_engine, two_tenants_with_data, tmp_path, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "audio_storage_path", str(tmp_path))

    data = two_tenants_with_data
    tenant_id = data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    conversation_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=data["contact_a_id"]
    )
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id="msg-idem")
    store_audio(audio_ref=audio_ref, audio_bytes=b"fake-voice-note-bytes")
    _insert_message_with_audio(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        created_at=old_date,
        audio_ref=audio_ref,
    )

    with Session(app_engine) as session:
        first = run_call_retention_job(
            session, audio_retention_days=30, transcript_retention_days=90, enabled=True
        )
    assert len(first.purged_message_audio_ids) >= 1

    with Session(app_engine) as session:
        second = run_call_retention_job(
            session, audio_retention_days=30, transcript_retention_days=90, enabled=True
        )
    assert second.purged_message_audio_ids == []
    assert second.message_audio_candidates_found == 0


def test_message_audio_retention_days_is_configurable(
    app_engine, postgres_engine, two_tenants_with_data, tmp_path, monkeypatch
):
    """Criterio de aceptación explícito de SPEC-058 (RF-04): el plazo de
    retención de mensajería es configurable por parámetro — un audio de
    solo 5 días de antigüedad SÍ se purga si `audio_retention_days=3`."""
    settings = get_settings()
    monkeypatch.setattr(settings, "audio_storage_path", str(tmp_path))

    data = two_tenants_with_data
    tenant_id = data["tenant_a_id"]
    shortly_old_date = datetime.now(timezone.utc) - timedelta(days=5)
    conversation_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=data["contact_a_id"]
    )
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id="msg-shortplazo")
    store_audio(audio_ref=audio_ref, audio_bytes=b"fake-voice-note-bytes")
    message_id = _insert_message_with_audio(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        created_at=shortly_old_date,
        audio_ref=audio_ref,
    )

    with Session(app_engine) as session:
        result = run_call_retention_job(
            session, audio_retention_days=3, transcript_retention_days=90, enabled=True
        )

    assert str(message_id) in result.purged_message_audio_ids
    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT audio_purged_at FROM messages WHERE id = :id"),
            {"id": message_id},
        ).fetchone()
        assert row.audio_purged_at is not None
