"""
Tests HTTP de `app/api/calls.py` (SPEC-040) contra PostgreSQL real.

Mismo patrón que `tests/test_api_v1_integration.py` (SPEC-014): se ejercita
la API completa end-to-end vía `TestClient` + `dependency_overrides` de
`get_tenant_db`/`get_current_user` (fixtures `client`/`api_as_tenant` de
`tests/conftest.py`), inyectando una sesión real de Postgres con el
`tenant_id`/usuario de prueba ya resueltos. Requiere el `db` de
`docker-compose.yml` (PostgreSQL 16 + pgvector) con el esquema de SPEC-012
aplicado vía Alembic; si no hay Postgres accesible, se SKIPEAN
automáticamente vía el fixture `postgres_engine` (no se marcan como
aprobados en falso) — mismo criterio que el resto de la suite.

Qué se verifica (correcciones IMPORTANTES pedidas tras revisión de
BLACK PANTHER/WOLVERINE sobre SPEC-040):
  1. `GET /calls`: paginación, filtro `contact_id`, exclusión de inactivas.
  2. Aislamiento cross-tenant (RLS + filtro explícito, C2): un tenant no
     lista ni ve el detalle de una llamada de otro tenant (404 homogéneo).
  3. `GET /calls/{id}`: 404 (inactiva/inexistente/otro tenant); caso feliz
     con transcripción+sentimiento+resumen+borrador RAG (>=3 citas); rama
     sin transcripción/sin borrador/sin conversación enlazada.
  4. `GET /calls/{id}/audio`: 404 sin `audio_ref`; 404 si `AudioStoreError`
     (fallo de descifrado simulado); caso feliz sirviendo bytes
     `audio/wav`.
  5. Auditoría: `log_personal_data_access` se invoca en los 3 endpoints
     (capturada con `structlog.testing.capture_logs`, igual patrón que
     `tests/test_audit_log.py`).
  6. Filtro de bandeja unificada (hueco de regresión señalado por
     WOLVERINE): `GET /conversations` excluye las conversaciones de
     `canal="voz"` que materializan internamente las llamadas.
"""

from __future__ import annotations

import json
import uuid

import pytest
import sqlalchemy as sa
import structlog

from app.services.telefonia.audio_store import AudioStoreError

# `client` y `api_as_tenant` son fixtures compartidos de `tests/conftest.py`
# (mismo patrón que `tests/test_api_v1_integration.py`).


# ---------------------------------------------------------------------------
# Helpers de bootstrap directo en BD (mismo patrón que
# `tests/test_calls_voice_data.py`, SPEC-036): se insertan filas con el rol
# privilegiado (`postgres_engine`) fuera de RLS a propósito, para preparar
# datos de ambos tenants antes de ejercer la API con `api_as_tenant`.
# ---------------------------------------------------------------------------


def _insert_conversation(conn, tenant_id, contact_id, canal="voz"):
    conversation_id = uuid.uuid4()
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


def _insert_call(
    conn,
    tenant_id,
    call_id_str,
    *,
    conversation_id=None,
    contact_id=None,
    numero="3009998888",
    direccion="entrante",
    estado="finalizada",
    resumen=None,
    audio_ref=None,
    activo=True,
):
    row_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO calls "
            "(id, tenant_id, call_id, numero, direccion, estado, resumen, "
            "conversation_id, contact_id, audio_ref, activo) "
            "VALUES (:id, :tenant_id, :call_id, :numero, :direccion, :estado, "
            ":resumen, :conversation_id, :contact_id, :audio_ref, :activo)"
        ),
        {
            "id": row_id,
            "tenant_id": tenant_id,
            "call_id": call_id_str,
            "numero": numero,
            "direccion": direccion,
            "estado": estado,
            "resumen": resumen,
            "conversation_id": conversation_id,
            "contact_id": contact_id,
            "audio_ref": audio_ref,
            "activo": activo,
        },
    )
    return row_id


def _insert_message(
    conn,
    tenant_id,
    conversation_id,
    *,
    remitente="contacto",
    contenido="segmento transcrito",
    sentimiento=None,
    sentimiento_score=None,
    activo=True,
):
    message_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO messages "
            "(id, tenant_id, conversation_id, remitente, contenido, "
            "sentimiento, sentimiento_score, activo) "
            "VALUES (:id, :tenant_id, :conversation_id, :remitente, :contenido, "
            ":sentimiento, :sentimiento_score, :activo)"
        ),
        {
            "id": message_id,
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "remitente": remitente,
            "contenido": contenido,
            "sentimiento": sentimiento,
            "sentimiento_score": sentimiento_score,
            "activo": activo,
        },
    )
    return message_id


def _make_citations(n=3):
    return [
        {
            "source": f"doc-{i}.pdf",
            "excerpt": f"fragmento citado {i}",
            "similarityScore": 0.9,
            "chunk_id": str(uuid.uuid4()),
            "document_id": str(uuid.uuid4()),
        }
        for i in range(n)
    ]


def _insert_rag_draft(
    conn,
    tenant_id,
    conversation_id,
    *,
    content="Respuesta propuesta al contacto.",
    citations=None,
    estado="propuesto",
    activo=True,
):
    draft_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO rag_drafts "
            "(id, tenant_id, conversation_id, query, content_original, content, "
            "model, citations, estado, activo) "
            "VALUES (:id, :tenant_id, :conversation_id, :query, :content_original, "
            ":content, :model, :citations, :estado, :activo)"
        ),
        {
            "id": draft_id,
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "query": "consulta del contacto",
            "content_original": content,
            "content": content,
            "model": "test-model",
            "citations": json.dumps(citations or _make_citations()),
            "estado": estado,
            "activo": activo,
        },
    )
    return draft_id


def _insert_call_transcript(
    conn,
    tenant_id,
    call_row_id,
    *,
    segmentos=None,
    idioma="es",
    modelo_stt="faster-whisper/large-v3",
):
    transcript_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO call_transcripts "
            "(id, tenant_id, call_id, segmentos, idioma, modelo_stt) "
            "VALUES (:id, :tenant_id, :call_id, :segmentos, :idioma, :modelo_stt)"
        ),
        {
            "id": transcript_id,
            "tenant_id": tenant_id,
            "call_id": call_row_id,
            "segmentos": json.dumps(
                segmentos
                or [{"inicio": 0.0, "fin": 1.0, "texto": "Hola", "hablante": "agente"}]
            ),
            "idioma": idioma,
            "modelo_stt": modelo_stt,
        },
    )
    return transcript_id


# ---------------------------------------------------------------------------
# GET /calls — listado: paginación, filtro contact_id, exclusión de inactivas
# ---------------------------------------------------------------------------


def test_list_calls_is_paginated_and_excludes_inactive(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        active_id = _insert_call(
            conn, data["tenant_a_id"], f"call-active-{uuid.uuid4().hex[:8]}"
        )
        inactive_id = _insert_call(
            conn,
            data["tenant_a_id"],
            f"call-inactive-{uuid.uuid4().hex[:8]}",
            activo=False,
        )

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get("/api/v1/calls", params={"page": 1, "page_size": 20})

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert "total" in body
    visible_ids = {c["id"] for c in body["items"]}
    assert str(active_id) in visible_ids
    assert str(inactive_id) not in visible_ids


def test_list_calls_filters_by_contact_id(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        matching_id = _insert_call(
            conn,
            data["tenant_a_id"],
            f"call-match-{uuid.uuid4().hex[:8]}",
            contact_id=data["contact_a_id"],
        )
        other_id = _insert_call(
            conn, data["tenant_a_id"], f"call-other-{uuid.uuid4().hex[:8]}"
        )

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(
            "/api/v1/calls", params={"contact_id": str(data["contact_a_id"])}
        )

    assert response.status_code == 200
    visible_ids = {c["id"] for c in response.json()["items"]}
    assert str(matching_id) in visible_ids
    assert str(other_id) not in visible_ids


def test_list_calls_emits_personal_data_access_audit(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        _insert_call(conn, data["tenant_a_id"], f"call-audit-{uuid.uuid4().hex[:8]}")

    with structlog.testing.capture_logs() as captured:
        with api_as_tenant(data["tenant_a_id"]):
            response = client.get("/api/v1/calls")

    assert response.status_code == 200
    audit_entries = [e for e in captured if e.get("event") == "personal_data_access"]
    assert len(audit_entries) == 1
    assert audit_entries[0]["action"] == "list"
    assert audit_entries[0]["resource"] == "calls"


# ---------------------------------------------------------------------------
# Aislamiento cross-tenant — listado y detalle
# ---------------------------------------------------------------------------


def test_tenant_a_cannot_list_calls_of_tenant_b(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        call_b_id = _insert_call(
            conn, data["tenant_b_id"], f"call-b-{uuid.uuid4().hex[:8]}"
        )

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get("/api/v1/calls")

    assert response.status_code == 200
    visible_ids = {c["id"] for c in response.json()["items"]}
    assert str(call_b_id) not in visible_ids


def test_tenant_a_cannot_read_call_detail_of_tenant_b(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    """404 homogéneo: no distinguible de "no existe" (mismo criterio que
    `test_tenant_a_cannot_read_contact_of_tenant_b`)."""
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        call_b_id = _insert_call(
            conn, data["tenant_b_id"], f"call-b-detail-{uuid.uuid4().hex[:8]}"
        )

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(f"/api/v1/calls/{call_b_id}")

    assert response.status_code == 404


def test_tenant_a_cannot_read_call_audio_of_tenant_b(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        call_b_id = _insert_call(
            conn,
            data["tenant_b_id"],
            f"call-b-audio-{uuid.uuid4().hex[:8]}",
            audio_ref=f"{data['tenant_b_id']}/fake.enc",
        )

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(f"/api/v1/calls/{call_b_id}/audio")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /calls/{id} — detalle: 404, caso feliz, ramas vacías
# ---------------------------------------------------------------------------


def test_get_call_detail_404_for_inexistent_call(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(f"/api/v1/calls/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_call_detail_404_for_inactive_call(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        call_id = _insert_call(
            conn,
            data["tenant_a_id"],
            f"call-inactive-detail-{uuid.uuid4().hex[:8]}",
            activo=False,
        )

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(f"/api/v1/calls/{call_id}")
    assert response.status_code == 404


def test_get_call_detail_happy_path_with_transcript_sentiment_and_rag_draft(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    """Caso feliz: transcripción + sentimiento + resumen + borrador RAG con
    >=3 citas (RF-01/RF-02 SPEC-040)."""
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        conversation_id = _insert_conversation(
            conn, data["tenant_a_id"], data["contact_a_id"], canal="voz"
        )
        call_id = _insert_call(
            conn,
            data["tenant_a_id"],
            f"call-happy-{uuid.uuid4().hex[:8]}",
            conversation_id=conversation_id,
            contact_id=data["contact_a_id"],
            resumen="Resumen de la llamada.",
            audio_ref=f"{data['tenant_a_id']}/happy.enc",
        )
        _insert_call_transcript(conn, data["tenant_a_id"], call_id)
        _insert_message(
            conn,
            data["tenant_a_id"],
            conversation_id,
            sentimiento="positivo",
            sentimiento_score=0.87,
        )
        _insert_rag_draft(
            conn, data["tenant_a_id"], conversation_id, citations=_make_citations(3)
        )

    with structlog.testing.capture_logs() as captured:
        with api_as_tenant(data["tenant_a_id"]):
            response = client.get(f"/api/v1/calls/{call_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["call"]["id"] == str(call_id)
    assert body["call"]["resumen"] == "Resumen de la llamada."
    assert body["call"]["audio_disponible"] is True

    assert body["transcript"] is not None
    assert len(body["transcript"]["segmentos"]) >= 1

    assert body["sentiment"]["sentimiento"] == "positivo"
    assert body["sentiment"]["sentimiento_score"] == pytest.approx(0.87)

    assert body["rag_draft"] is not None
    assert len(body["rag_draft"]["citations"]) >= 3

    audit_entries = [e for e in captured if e.get("event") == "personal_data_access"]
    assert len(audit_entries) == 1
    assert audit_entries[0]["action"] == "read"
    assert audit_entries[0]["resource"] == "calls"
    assert audit_entries[0]["resource_id"] == str(call_id)


def test_get_call_detail_without_transcript_draft_or_conversation(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    """Rama sin transcripción/sin borrador/sin conversación enlazada: la
    respuesta no debe fallar, con esos campos en null/vacío."""
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        call_id = _insert_call(
            conn, data["tenant_a_id"], f"call-bare-{uuid.uuid4().hex[:8]}"
        )

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(f"/api/v1/calls/{call_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] is None
    assert body["rag_draft"] is None
    assert body["sentiment"]["sentimiento"] is None
    assert body["sentiment"]["sentimiento_score"] is None
    assert body["call"]["conversation_id"] is None
    assert body["call"]["audio_disponible"] is False


# ---------------------------------------------------------------------------
# GET /calls/{id}/audio
# ---------------------------------------------------------------------------


def test_get_call_audio_404_when_no_audio_ref(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        call_id = _insert_call(
            conn, data["tenant_a_id"], f"call-noaudio-{uuid.uuid4().hex[:8]}"
        )

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(f"/api/v1/calls/{call_id}/audio")

    assert response.status_code == 404


def test_get_call_audio_404_when_audio_store_error(
    client, api_as_tenant, two_tenants_with_data, postgres_engine, monkeypatch
):
    """Simula fallo de descifrado (`AudioStoreError`): nunca debe filtrar un
    500 ni detalles de infraestructura (C3)."""
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        call_id = _insert_call(
            conn,
            data["tenant_a_id"],
            f"call-storeerror-{uuid.uuid4().hex[:8]}",
            audio_ref=f"{data['tenant_a_id']}/corrupt.enc",
        )

    def _raise_store_error(*, audio_ref):
        raise AudioStoreError("fallo simulado de descifrado")

    monkeypatch.setattr("app.api.calls.load_audio", _raise_store_error)

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(f"/api/v1/calls/{call_id}/audio")

    assert response.status_code == 404


def test_get_call_audio_happy_path_serves_wav_bytes(
    client, api_as_tenant, two_tenants_with_data, postgres_engine, monkeypatch
):
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        call_id = _insert_call(
            conn,
            data["tenant_a_id"],
            f"call-audio-ok-{uuid.uuid4().hex[:8]}",
            audio_ref=f"{data['tenant_a_id']}/ok.enc",
        )

    fake_audio_bytes = b"RIFF....WAVEfake-audio-bytes"

    def _fake_load_audio(*, audio_ref):
        return fake_audio_bytes

    monkeypatch.setattr("app.api.calls.load_audio", _fake_load_audio)

    with structlog.testing.capture_logs() as captured:
        with api_as_tenant(data["tenant_a_id"]):
            response = client.get(f"/api/v1/calls/{call_id}/audio")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == fake_audio_bytes

    audit_entries = [e for e in captured if e.get("event") == "personal_data_access"]
    assert len(audit_entries) == 1
    assert audit_entries[0]["action"] == "read"
    assert audit_entries[0]["resource"] == "calls_audio"
    assert audit_entries[0]["resource_id"] == str(call_id)


# ---------------------------------------------------------------------------
# Filtro de bandeja unificada (hueco de regresión señalado por WOLVERINE):
# `GET /conversations` excluye conversaciones de canal="voz".
# ---------------------------------------------------------------------------


def test_list_conversations_excludes_voz_channel(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        voz_conversation_id = _insert_conversation(
            conn, data["tenant_a_id"], data["contact_a_id"], canal="voz"
        )

    with api_as_tenant(data["tenant_a_id"]):
        response = client.post(
            "/api/v1/conversations",
            json={"contact_id": str(data["contact_a_id"]), "canal": "webchat"},
        )
        assert response.status_code == 201
        webchat_conversation_id = response.json()["id"]

        list_response = client.get("/api/v1/conversations")

    assert list_response.status_code == 200
    visible_ids = {c["id"] for c in list_response.json()["items"]}
    assert str(voz_conversation_id) not in visible_ids
    assert webchat_conversation_id in visible_ids
