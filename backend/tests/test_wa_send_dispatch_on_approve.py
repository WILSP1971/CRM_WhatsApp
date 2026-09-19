"""Tests del DISPARO del envío por WhatsApp desde la aprobación humana —
SPEC-029 (RF-02) integrado con SPEC-019, contra PostgreSQL real (mismo
patrón/fixtures que `tests/test_rag_draft_review_api.py`). `AIClient`
mockeado (`FakeAIClient`), Redis vía `fakeredis.aioredis`: CERO llamadas a
Meta ni a un LLM real.

Verifica el criterio central de SPEC-029 sobre el DISPARO (no el transporte
en sí, cubierto en `tests/test_whatsapp_graph_client.py`/
`tests/test_wa_send_worker.py`):
  (a) aprobar un borrador en una conversación de canal "whatsapp" encola
      exactamente UN job en `wa:outbound` — y NUNCA antes de aprobar.
  (b) aprobar un borrador en una conversación de canal "webchat" NO encola
      nada en `wa:outbound` (el disparo es específico del canal).
  (c) generar/editar/descartar un borrador (sin aprobar) NUNCA encola nada
      en `wa:outbound`, sin importar el canal — el ÚNICO trigger es la
      aprobación humana explícita.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import fakeredis.aioredis
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import deps
from app.core.redis_client import get_redis_client
from app.core.whatsapp_outbound_queue import OUTBOUND_QUEUE_KEY, dequeue_outbound_send
from app.db.session import set_tenant_session
from app.main import app
from app.services.ai_service import get_ai_client
from app.workers.rag_ingest_worker import drain_one
from tests.rag_ai_client_fake import FakeAIClient

_TEXTO_BASE = (
    "Los envíos nacionales tardan de 3 a 5 días hábiles. "
    "Los envíos internacionales tardan de 10 a 15 días hábiles. "
    "El costo de envío nacional es gratis sobre pedidos de $150.000. "
    "Puedes rastrear tu pedido con el número de guía en el portal. "
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fake_redis():
    redis_instance = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.dependency_overrides[get_redis_client] = lambda: redis_instance
    yield redis_instance


@pytest.fixture
def api_as_tenant(postgres_engine):
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
                    nombre="Agente de Prueba",
                    rol="agente",
                    activo=True,
                )

            def fake_get_tenant_db():
                with postgres_engine.connect() as conn:
                    with conn.begin():
                        set_tenant_session(conn, str(self.tenant_id))
                        yield conn

            app.dependency_overrides[deps.get_current_user] = fake_get_current_user
            app.dependency_overrides[deps.get_tenant_db] = fake_get_tenant_db
            return self

        def __exit__(self, exc_type, exc, tb):
            for key in (deps.get_current_user, deps.get_tenant_db):
                app.dependency_overrides.pop(key, None)

    def _factory(tenant_id, user_email="agente@tenant.test"):
        return _Activator(tenant_id, user_email)

    return _factory


def _crear_tenant_con_conversacion_indexada(postgres_engine, fake_redis, *, canal: str):
    tenant_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    document_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO tenants (id, nombre, slug) VALUES (:id, :n, :s)"),
            {
                "id": tenant_id,
                "n": "Tenant WA Dispatch",
                "s": f"wad-{tenant_id.hex[:8]}",
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO contacts (id, tenant_id, nombre, telefono) "
                "VALUES (:id, :tenant_id, 'Contacto Dispatch', :tel)"
            ),
            {
                "id": contact_id,
                "tenant_id": tenant_id,
                "tel": f"3{tenant_id.int % 10**9}",
            },
        )
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
        conn.execute(
            sa.text(
                "INSERT INTO documents (id, tenant_id, nombre_archivo, tipo, estado) "
                "VALUES (:id, :tenant_id, 'faq-envios.txt', 'txt', 'pendiente')"
            ),
            {"id": document_id, "tenant_id": tenant_id},
        )

    fake = FakeAIClient()
    app.dependency_overrides[get_ai_client] = lambda: fake

    from app.core.rag_queue import enqueue_ingest_job

    async def _ingest():
        await enqueue_ingest_job(
            fake_redis,
            tenant_id=tenant_id,
            document_id=document_id,
            text=_TEXTO_BASE * 10,
            chunk_size=150,
            chunk_overlap=20,
        )

        def _session_factory() -> Session:
            return Session(postgres_engine)

        while await drain_one(
            fake_redis, tenant_id=tenant_id, session_factory=_session_factory
        ):
            pass

    asyncio.run(_ingest())
    app.dependency_overrides.pop(get_ai_client, None)

    return {
        "tenant_id": tenant_id,
        "contact_id": contact_id,
        "conversation_id": conversation_id,
        "document_id": document_id,
    }


def _use_fake_ai_client(**kwargs) -> FakeAIClient:
    fake = FakeAIClient(**kwargs)
    app.dependency_overrides[get_ai_client] = lambda: fake
    return fake


def _crear_borrador(client, api_as_tenant, data, query="¿Cuánto tardan los envíos?"):
    with api_as_tenant(data["tenant_id"]):
        _use_fake_ai_client()
        response = client.post(
            f"/api/v1/rag/conversations/{data['conversation_id']}/drafts",
            json={"query": query, "top_k": 5},
        )
    return response


async def _drain_outbound_queue(redis_client) -> list:
    jobs = []
    while True:
        job = await dequeue_outbound_send(redis_client, timeout_seconds=0)
        if job is None:
            break
        jobs.append(job)
    return jobs


# ---------------------------------------------------------------------------
# (a) canal "whatsapp" + aprobación -> exactamente 1 job en wa:outbound
# ---------------------------------------------------------------------------


def test_approve_on_whatsapp_conversation_enqueues_outbound_send(
    client, api_as_tenant, postgres_engine, fake_redis
):
    data = _crear_tenant_con_conversacion_indexada(
        postgres_engine, fake_redis, canal="whatsapp"
    )
    draft = _crear_borrador(client, api_as_tenant, data).json()
    draft_id = draft["id"]

    # Antes de aprobar: la cola de envío debe estar vacía (ni proponer ni
    # generar el borrador dispara nada hacia WhatsApp).
    assert asyncio.run(_drain_outbound_queue(fake_redis)) == []

    with api_as_tenant(data["tenant_id"], user_email="supervisor@tenant.test"):
        approve_response = client.post(
            f"/api/v1/rag/conversations/{data['conversation_id']}"
            f"/drafts/{draft_id}/approve"
        )

    assert approve_response.status_code == 200
    sent_message_id = approve_response.json()["sent_message_id"]

    jobs = asyncio.run(_drain_outbound_queue(fake_redis))
    assert len(jobs) == 1
    assert jobs[0].tenant_id == str(data["tenant_id"])
    assert jobs[0].conversation_id == str(data["conversation_id"])
    assert jobs[0].message_id == str(sent_message_id)


# ---------------------------------------------------------------------------
# (b) canal "webchat" + aprobación -> NADA encolado en wa:outbound
# ---------------------------------------------------------------------------


def test_approve_on_webchat_conversation_does_not_enqueue_outbound_send(
    client, api_as_tenant, postgres_engine, fake_redis
):
    data = _crear_tenant_con_conversacion_indexada(
        postgres_engine, fake_redis, canal="webchat"
    )
    draft = _crear_borrador(client, api_as_tenant, data).json()
    draft_id = draft["id"]

    with api_as_tenant(data["tenant_id"], user_email="supervisor@tenant.test"):
        approve_response = client.post(
            f"/api/v1/rag/conversations/{data['conversation_id']}"
            f"/drafts/{draft_id}/approve"
        )

    assert approve_response.status_code == 200
    assert asyncio.run(_drain_outbound_queue(fake_redis)) == []


# ---------------------------------------------------------------------------
# (c) Proponer/editar/descartar (SIN aprobar) NUNCA encola, en ningún canal
# ---------------------------------------------------------------------------


def test_creating_draft_on_whatsapp_conversation_never_enqueues_outbound_send(
    client, api_as_tenant, postgres_engine, fake_redis
):
    data = _crear_tenant_con_conversacion_indexada(
        postgres_engine, fake_redis, canal="whatsapp"
    )

    response = _crear_borrador(client, api_as_tenant, data)

    assert response.status_code == 201
    assert asyncio.run(_drain_outbound_queue(fake_redis)) == []


def test_discarding_draft_on_whatsapp_conversation_never_enqueues_outbound_send(
    client, api_as_tenant, postgres_engine, fake_redis
):
    data = _crear_tenant_con_conversacion_indexada(
        postgres_engine, fake_redis, canal="whatsapp"
    )
    draft = _crear_borrador(client, api_as_tenant, data).json()
    draft_id = draft["id"]

    with api_as_tenant(data["tenant_id"]):
        discard_response = client.post(
            f"/api/v1/rag/conversations/{data['conversation_id']}"
            f"/drafts/{draft_id}/discard"
        )

    assert discard_response.status_code == 200
    assert asyncio.run(_drain_outbound_queue(fake_redis)) == []


def test_outbound_queue_key_matches_spec_wa_outbound():
    assert OUTBOUND_QUEUE_KEY == "wa:outbound"
