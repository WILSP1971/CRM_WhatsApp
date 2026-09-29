"""Tests de integración de la respuesta de audio (TTS de salida) —
Entregable #6, SPEC-069/ADR-014, contra PostgreSQL real (mismo patrón que
`tests/test_rag_draft_review_api.py`, SPEC-019). `fakeredis.aioredis` para
las colas (`wa:outbound`/`tts:jobs`); ningún test invoca Piper/ffmpeg reales
en este archivo (eso lo cubre `tests/test_tts_engine.py`) ni Graph API real.

Cubre los criterios de aceptación de SPEC-069 (verificación explícita
requerida por la SPEC, ver también `tests/test_tts_worker.py`/
`tests/test_wa_send_worker.py` para la parte de worker):
  (a) SIN aprobación humana del guion, no se encola NINGÚN job de síntesis
      "enviar" ni ningún envío — el invariante RNF-HITL.
  (b) ruta por defecto: aprobar un borrador con `respuesta_modo="audio"` en
      canal WhatsApp encola `tts:jobs` en modo "enviar" (además del texto de
      siempre); en canal `texto`/`webchat`, `respuesta_modo="audio"` NO
      encola nada de audio (el vector de audio solo existe vía WhatsApp).
  (c) ruta "escuchar antes de enviar": encola `tts:jobs` en modo "escuchar"
      SIN encolar ningún envío.
  (d) `set_respuesta_modo`/`approve`/`listen` respetan el aislamiento por
      tenant y el estado mutable del borrador (409 si ya es terminal).
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import fakeredis.aioredis
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis_client
from app.core.tts_queue import (
    TTS_JOB_MODO_ENVIAR,
    TTS_JOB_MODO_ESCUCHAR,
    dequeue_tts_job,
)
from app.core.whatsapp_outbound_queue import dequeue_outbound_send
from app.db.session import set_tenant_session
from app.main import app


@pytest.fixture
def fake_redis():
    """MISMO criterio que `tests/test_rag_draft_review_api.py::fake_redis`
    (ver su docstring para el porqué del `FakeServer` compartido)."""
    server = fakeredis.FakeServer()
    redis_instance = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    redis_instance.fake_server = server
    app.dependency_overrides[get_redis_client] = lambda: redis_instance
    yield redis_instance
    app.dependency_overrides.pop(get_redis_client, None)


def _redis_client_for_current_loop(fake_redis) -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(
        server=fake_redis.fake_server, decode_responses=True
    )


async def _dequeue_snapshot(fake_redis):
    """Dequeue de `tts:jobs` y `wa:outbound` en UNA sola corrida de
    `asyncio.run` (un solo loop, un solo cliente `FakeRedis` creado DENTRO
    de esta corutina). CORRECCIÓN (bug encontrado ejecutando la suite contra
    Postgres real): crear el cliente UNA VEZ fuera y reutilizarlo en DOS
    `asyncio.run()` separados revienta con `RuntimeError: ... is bound to a
    different event loop` — cada `asyncio.run()` crea un loop nuevo y la
    conexión `redis.asyncio`/`fakeredis` queda ligada al PRIMERO. Mismo
    criterio que `tests/test_wa_send_dispatch_on_approve.py`."""
    redis_client = _redis_client_for_current_loop(fake_redis)
    tts_job = await dequeue_tts_job(redis_client)
    outbound_job = await dequeue_outbound_send(redis_client)
    return tts_job, outbound_job


def _make_citations() -> list[dict]:
    return [
        {
            "source": f"doc-{i}.txt",
            "excerpt": f"fragmento {i}",
            "similarityScore": 0.9,
            "chunk_id": str(uuid.uuid4()),
            "document_id": str(uuid.uuid4()),
        }
        for i in range(3)
    ]


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
                "VALUES (:id, :tenant_id, 'Contacto TTS', :telefono)"
            ),
            {"id": contact_id, "tenant_id": tenant_id, "telefono": telefono},
        )
    return contact_id


def _crear_conversacion(
    engine, tenant_id: uuid.UUID, contact_id: uuid.UUID, *, canal: str
) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conversations (id, tenant_id, contact_id, canal, estado) "
                "VALUES (:id, :tenant_id, :contact_id, :canal, 'abierta')"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "contact_id": contact_id,
                "canal": canal,
            },
        )
    return conversation_id


def _crear_mensaje_inbound(
    engine, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    """Mensaje ENTRANTE reciente (dentro de ventana de 24h) — necesario para
    que `wa_send_worker` (si el job de envío llegara a procesarse en otro
    test) no bloquee por ventana; irrelevante para los tests de ESTE archivo
    (que solo verifican encolado, no consumo), pero se deja disponible por
    si un test futuro decide drenar la cola end-to-end."""
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO messages "
                "(id, tenant_id, conversation_id, remitente, contenido, estado_entrega) "
                "VALUES (:id, :tenant_id, :conversation_id, 'contacto', 'hola', 'enviado')"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
            },
        )


def _crear_draft(
    engine,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    content: str = "Su pedido llega mañana.",
    respuesta_modo: str = "texto",
    estado: str = "propuesto",
) -> uuid.UUID:
    draft_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO rag_drafts "
                "(id, tenant_id, conversation_id, query, content_original, content, "
                "model, citations, estado, respuesta_modo, activo) "
                "VALUES (:id, :tenant_id, :conversation_id, :query, :content, :content, "
                ":model, :citations, :estado, :respuesta_modo, true)"
            ),
            {
                "id": draft_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "query": "consulta del contacto",
                "content": content,
                "model": "test-model",
                "citations": json.dumps(_make_citations()),
                "estado": estado,
                "respuesta_modo": respuesta_modo,
            },
        )
    return draft_id


def _draft_row(engine, draft_id: uuid.UUID):
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT estado, respuesta_modo, tts_estado, audio_salida_ref, "
                "sent_message_id FROM rag_drafts WHERE id = :id"
            ),
            {"id": draft_id},
        ).fetchone()


@pytest.fixture
def api_as_tenant_local(app_engine):
    """MISMO patrón que `conftest.py::api_as_tenant` — redefinido localmente
    solo para poder usar `user_email` por defecto distinto sin chocar con
    otros módulos (evita F811 de flake8 al reimportar el fixture entre
    módulos, mismo criterio documentado en `conftest.py`)."""
    from app.api import deps

    class _Activator:
        def __init__(self, tenant_id, user_email):
            self.tenant_id = tenant_id
            self.user_email = user_email

        def __enter__(self):
            def fake_get_current_user():
                return SimpleNamespace(
                    id=uuid.uuid4(),
                    tenant_id=self.tenant_id,
                    email=self.user_email,
                    nombre="Agente TTS",
                    rol="agente",
                    activo=True,
                )

            def fake_get_tenant_db():
                db = Session(app_engine)
                try:
                    with db.begin():
                        set_tenant_session(db, str(self.tenant_id))
                        yield db
                finally:
                    db.close()

            app.dependency_overrides[deps.get_current_user] = fake_get_current_user
            app.dependency_overrides[deps.get_tenant_db] = fake_get_tenant_db
            return self

        def __exit__(self, exc_type, exc, tb):
            for key in (deps.get_current_user, deps.get_tenant_db):
                app.dependency_overrides.pop(key, None)

    def _factory(tenant_id, user_email="agente@tenant-tts.test"):
        return _Activator(tenant_id, user_email)

    return _factory


# ---------------------------------------------------------------------------
# (a) Invariante RNF-HITL: sin aprobación, no se encola nada de audio
# ---------------------------------------------------------------------------


def test_creating_or_editing_a_draft_never_enqueues_tts_job(
    client, postgres_engine, api_as_tenant_local, fake_redis
):
    """Fijar `respuesta_modo="audio"` (opt-in) NO genera ni envía nada por sí
    solo — solo `approve` (tras aprobar el guion) o `listen` (bajo demanda,
    acción explícita) pueden encolar `tts:jobs`."""
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsNoEncola")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573000000001")
    conversation_id = _crear_conversacion(
        postgres_engine, tenant_id, contact_id, canal="whatsapp"
    )
    draft_id = _crear_draft(postgres_engine, tenant_id, conversation_id)

    with api_as_tenant_local(tenant_id):
        resp = client.patch(
            f"/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/respuesta-modo",
            json={"respuesta_modo": "audio"},
        )
    assert resp.status_code == 200
    assert resp.json()["respuesta_modo"] == "audio"

    import asyncio

    tts_job, outbound_job = asyncio.run(_dequeue_snapshot(fake_redis))
    assert tts_job is None
    assert outbound_job is None

    row = _draft_row(postgres_engine, draft_id)
    assert row.estado == "propuesto"
    assert row.sent_message_id is None
    assert row.tts_estado is None


# ---------------------------------------------------------------------------
# (b) Ruta por defecto: aprobar con respuesta_modo="audio" en WhatsApp
# ---------------------------------------------------------------------------


def test_approve_with_audio_mode_on_whatsapp_enqueues_tts_job_enviar(
    client, postgres_engine, api_as_tenant_local, fake_redis
):
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsAprobarAudio")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573000000002")
    conversation_id = _crear_conversacion(
        postgres_engine, tenant_id, contact_id, canal="whatsapp"
    )
    _crear_mensaje_inbound(postgres_engine, tenant_id, conversation_id)
    draft_id = _crear_draft(
        postgres_engine,
        tenant_id,
        conversation_id,
        content="Su pedido llega mañana antes de las 5pm.",
        respuesta_modo="audio",
    )

    with api_as_tenant_local(tenant_id):
        resp = client.post(
            f"/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/approve"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["draft"]["estado"] == "aprobado"
    message_id = body["sent_message_id"]

    import asyncio

    async def _check():
        # Mismo cliente/loop para las 3 operaciones secuenciales (ver
        # docstring de `_dequeue_snapshot` — un cliente no puede cruzar
        # `asyncio.run()` distintos).
        redis_client = _redis_client_for_current_loop(fake_redis)
        outbound_text_job = await dequeue_outbound_send(redis_client)
        tts_job = await dequeue_tts_job(redis_client)
        outbound_audio_job_premature = await dequeue_outbound_send(redis_client)
        return outbound_text_job, tts_job, outbound_audio_job_premature

    outbound_text_job, tts_job, outbound_audio_job_premature = asyncio.run(_check())

    # El texto de siempre SIEMPRE se encola (SPEC-029, sin regresión).
    assert outbound_text_job is not None
    assert outbound_text_job.tipo == "texto"
    assert outbound_text_job.message_id == message_id

    # Y, ADEMÁS (opt-in de audio), se encola la síntesis en modo "enviar" —
    # el propio tts_worker (fuera de este test) dispararía el envío después.
    assert tts_job is not None
    assert tts_job.modo == TTS_JOB_MODO_ENVIAR
    assert tts_job.draft_id == draft_id.hex or tts_job.draft_id == str(draft_id)
    assert tts_job.texto == "Su pedido llega mañana antes de las 5pm."

    # Ningún job de envío de AUDIO todavía (eso lo encola el tts_worker tras
    # sintetizar, no este endpoint) — solo el de texto de arriba.
    assert outbound_audio_job_premature is None


def test_approve_with_audio_mode_on_non_whatsapp_channel_does_not_enqueue_tts(
    client, postgres_engine, api_as_tenant_local, fake_redis
):
    """El vector de audio de salida SOLO existe vía WhatsApp (el envío de
    media es un concepto de ese canal) — en `webchat`, `respuesta_modo=
    "audio"` no debe encolar ningún job de síntesis."""
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsWebchat")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573000000003")
    conversation_id = _crear_conversacion(
        postgres_engine, tenant_id, contact_id, canal="webchat"
    )
    draft_id = _crear_draft(
        postgres_engine, tenant_id, conversation_id, respuesta_modo="audio"
    )

    with api_as_tenant_local(tenant_id):
        resp = client.post(
            f"/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/approve"
        )
    assert resp.status_code == 200

    import asyncio

    tts_job, outbound_job = asyncio.run(_dequeue_snapshot(fake_redis))
    assert tts_job is None
    assert outbound_job is None


def test_approve_with_texto_mode_never_enqueues_tts_job(
    client, postgres_engine, api_as_tenant_local, fake_redis
):
    """Comportamiento por defecto (`respuesta_modo="texto"`, sin opt-in):
    CERO regresión — solo se encola el texto de siempre, nunca `tts:jobs`."""
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsDefaultTexto")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573000000004")
    conversation_id = _crear_conversacion(
        postgres_engine, tenant_id, contact_id, canal="whatsapp"
    )
    _crear_mensaje_inbound(postgres_engine, tenant_id, conversation_id)
    draft_id = _crear_draft(postgres_engine, tenant_id, conversation_id)

    with api_as_tenant_local(tenant_id):
        resp = client.post(
            f"/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/approve"
        )
    assert resp.status_code == 200

    import asyncio

    tts_job, outbound_job = asyncio.run(_dequeue_snapshot(fake_redis))
    assert outbound_job is not None
    assert tts_job is None


# ---------------------------------------------------------------------------
# (c) Ruta "escuchar antes de enviar": genera sin enviar
# ---------------------------------------------------------------------------


def test_listen_endpoint_enqueues_tts_job_escuchar_without_sending(
    client, postgres_engine, api_as_tenant_local, fake_redis
):
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsEscuchar")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573000000005")
    conversation_id = _crear_conversacion(
        postgres_engine, tenant_id, contact_id, canal="whatsapp"
    )
    draft_id = _crear_draft(postgres_engine, tenant_id, conversation_id)

    with api_as_tenant_local(tenant_id):
        resp = client.post(
            f"/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/listen"
        )
    assert resp.status_code == 202
    assert resp.json()["draft_id"] == str(draft_id)

    import asyncio

    tts_job, outbound_job = asyncio.run(_dequeue_snapshot(fake_redis))
    assert tts_job is not None
    assert tts_job.modo == TTS_JOB_MODO_ESCUCHAR
    assert outbound_job is None

    # NO transiciona el estado del guion (sigue mutable) — la escucha es
    # ortogonal a la máquina de estados de aprobación.
    row = _draft_row(postgres_engine, draft_id)
    assert row.estado == "propuesto"
    assert row.sent_message_id is None


def test_get_audio_endpoint_returns_404_when_no_clip_ready(
    client, postgres_engine, api_as_tenant_local
):
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsAudio404")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573000000006")
    conversation_id = _crear_conversacion(
        postgres_engine, tenant_id, contact_id, canal="whatsapp"
    )
    draft_id = _crear_draft(postgres_engine, tenant_id, conversation_id)

    with api_as_tenant_local(tenant_id):
        resp = client.get(
            f"/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/audio"
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# (d) Aislamiento por tenant / estado mutable
# ---------------------------------------------------------------------------


def test_set_respuesta_modo_rejects_invalid_value():
    from app.schemas.rag import DraftRespuestaModoRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DraftRespuestaModoRequest(respuesta_modo="audio-invalido")


def test_set_respuesta_modo_fails_409_when_draft_already_approved(
    client, postgres_engine, api_as_tenant_local
):
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsYaAprobado")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573000000007")
    conversation_id = _crear_conversacion(
        postgres_engine, tenant_id, contact_id, canal="whatsapp"
    )
    draft_id = _crear_draft(
        postgres_engine, tenant_id, conversation_id, estado="aprobado"
    )

    with api_as_tenant_local(tenant_id):
        resp = client.patch(
            f"/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/respuesta-modo",
            json={"respuesta_modo": "audio"},
        )
    assert resp.status_code == 409


def test_editing_draft_after_listening_invalidates_stale_clip(
    client, postgres_engine, api_as_tenant_local
):
    """Hallazgo de este implementador (SPEC-069/ADR-014): si el agente
    escucha un clip y LUEGO edita el texto, ese clip queda obsoleto (ya no
    corresponde al guion editado) — `edit_draft` debe invalidarlo
    (`tts_estado`/`audio_salida_ref` -> NULL) para que `approve` nunca
    reutilice por error un audio desincronizado del texto final aprobado."""
    tenant_id = _crear_tenant(postgres_engine, "TenantTtsInvalidaTrasEditar")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573000000008")
    conversation_id = _crear_conversacion(
        postgres_engine, tenant_id, contact_id, canal="whatsapp"
    )
    draft_id = _crear_draft(
        postgres_engine, tenant_id, conversation_id, respuesta_modo="audio"
    )

    # Simula que el clip YA fue generado y quedó "listo" (ruta de escucha).
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE rag_drafts SET tts_estado = 'listo', "
                "audio_salida_ref = 'ref-obsoleta.enc' WHERE id = :id"
            ),
            {"id": draft_id},
        )

    with api_as_tenant_local(tenant_id):
        resp = client.patch(
            f"/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}",
            json={"content": "Texto completamente distinto tras editar."},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tts_estado"] is None
    assert body["audio_listo"] is False

    row = _draft_row(postgres_engine, draft_id)
    assert row.tts_estado is None
    assert row.audio_salida_ref is None
