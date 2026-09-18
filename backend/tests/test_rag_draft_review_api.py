"""Tests de integración de la revisión human-in-the-loop del borrador RAG —
SPEC-019, contra PostgreSQL real (mismo patrón que `tests/test_rag_api.py`,
SPEC-017). `AIClient` mockeado (`FakeAIClient`); ningún test llama a un
modelo real. Redis vía `fakeredis.aioredis` (fan-out de la aprobación).

Verifica los criterios de aceptación de SPEC-019:
  - Generar/proponer un borrador NO crea ni envía ningún `Message` saliente.
  - Editar el borrador cambia el texto final (sin enviar nada).
  - SOLO aprobar crea el `Message` saliente, con el texto final vigente
    (editado si el agente lo cambió) y registra `approved_by` (trazabilidad).
  - Descartar el borrador no genera ningún envío ni mensaje persistido.
  - Aislamiento por tenant: un borrador de un tenant no es accesible por otro.
  - Auth requerida en todos los endpoints de borrador.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import fakeredis.aioredis
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import deps
from app.core.redis_client import get_redis_client
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
    """Mismo patrón que `tests/test_rag_api.py::api_as_tenant`."""

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


@pytest.fixture
def tenant_con_conversacion_indexada(postgres_engine, fake_redis):
    """Crea un tenant + contacto + conversación + documento YA indexado
    (drenando la cola de ingesta), listo para generar un borrador RAG."""
    tenant_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    document_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO tenants (id, nombre, slug) VALUES (:id, :n, :s)"),
            {"id": tenant_id, "n": "Tenant Draft", "s": f"draft-{tenant_id.hex[:8]}"},
        )
        conn.execute(
            sa.text(
                "INSERT INTO contacts (id, tenant_id, nombre, telefono) "
                "VALUES (:id, :tenant_id, 'Contacto Draft', :tel)"
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
                "VALUES (:id, :tenant_id, :contact_id, 'webchat', 'abierta')"
            ),
            {"id": conversation_id, "tenant_id": tenant_id, "contact_id": contact_id},
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

    import asyncio

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


def _count_outgoing_messages(postgres_engine, conversation_id: uuid.UUID) -> int:
    with postgres_engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT count(*) FROM messages WHERE conversation_id = :cid "
                "AND remitente = 'agente' AND activo IS true"
            ),
            {"cid": conversation_id},
        ).scalar_one()


def _crear_borrador(client, api_as_tenant, data, query="¿Cuánto tardan los envíos?"):
    with api_as_tenant(data["tenant_id"]):
        _use_fake_ai_client()
        response = client.post(
            f"/api/v1/rag/conversations/{data['conversation_id']}/drafts",
            json={"query": query, "top_k": 5},
        )
    return response


def test_create_draft_does_not_create_or_send_any_message(
    client, api_as_tenant, tenant_con_conversacion_indexada, postgres_engine
):
    """Criterio SPEC-019: generar el borrador NO crea ni envía ningún
    mensaje saliente al contacto."""
    data = tenant_con_conversacion_indexada

    response = _crear_borrador(client, api_as_tenant, data)

    assert response.status_code == 201
    body = response.json()
    assert body["estado"] == "propuesto"
    assert len(body["citations"]) >= 3
    assert body["sent_message_id"] is None
    assert body["content"] == body["content_original"]

    assert _count_outgoing_messages(postgres_engine, data["conversation_id"]) == 0


def test_approve_creates_the_outgoing_message_only_after_explicit_approval(
    client, api_as_tenant, tenant_con_conversacion_indexada, postgres_engine, fake_redis
):
    """Criterio central de SPEC-019: SOLO tras aprobar se crea el mensaje
    saliente; antes de eso, cero mensajes de "agente" persistidos."""
    data = tenant_con_conversacion_indexada
    draft = _crear_borrador(client, api_as_tenant, data).json()
    draft_id = draft["id"]

    assert _count_outgoing_messages(postgres_engine, data["conversation_id"]) == 0

    with api_as_tenant(data["tenant_id"], user_email="supervisor@tenant.test"):
        approve_response = client.post(
            f"/api/v1/rag/conversations/{data['conversation_id']}"
            f"/drafts/{draft_id}/approve"
        )

    assert approve_response.status_code == 200
    body = approve_response.json()
    assert body["draft"]["estado"] == "aprobado"
    assert body["draft"]["approved_by"] == "supervisor@tenant.test"
    assert body["sent_message_id"] == body["draft"]["sent_message_id"]

    assert _count_outgoing_messages(postgres_engine, data["conversation_id"]) == 1

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT contenido, remitente, created_by FROM messages WHERE id = :id"
            ),
            {"id": body["sent_message_id"]},
        ).fetchone()
    assert row.remitente == "agente"
    assert row.contenido == draft["content"]
    assert row.created_by == "supervisor@tenant.test"


def test_edit_draft_changes_final_text_before_sending(
    client, api_as_tenant, tenant_con_conversacion_indexada, postgres_engine
):
    """Criterio SPEC-019: un borrador editado envía el texto final EDITADO,
    no el original generado por el RAG."""
    data = tenant_con_conversacion_indexada
    draft = _crear_borrador(client, api_as_tenant, data).json()
    draft_id = draft["id"]
    texto_editado = "Respuesta revisada manualmente por el agente humano."

    with api_as_tenant(data["tenant_id"], user_email="editor@tenant.test"):
        edit_response = client.patch(
            f"/api/v1/rag/conversations/{data['conversation_id']}"
            f"/drafts/{draft_id}",
            json={"content": texto_editado},
        )
    assert edit_response.status_code == 200
    edited = edit_response.json()
    assert edited["estado"] == "editado"
    assert edited["content"] == texto_editado
    assert edited["content_original"] == draft["content_original"]

    # MAYOR (revisión BLACK PANTHER): `created_by` (quién generó el borrador)
    # se conserva; el editor se registra por separado en `edited_by`.
    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT created_by, edited_by FROM rag_drafts WHERE id = :id"),
            {"id": draft_id},
        ).fetchone()
    assert row.created_by == "agente@tenant.test"  # quien generó el borrador
    assert row.created_by != "editor@tenant.test"
    assert row.edited_by == "editor@tenant.test"

    # Editar tampoco envía nada.
    assert _count_outgoing_messages(postgres_engine, data["conversation_id"]) == 0

    with api_as_tenant(data["tenant_id"]):
        approve_response = client.post(
            f"/api/v1/rag/conversations/{data['conversation_id']}"
            f"/drafts/{draft_id}/approve"
        )
    assert approve_response.status_code == 200
    sent_id = approve_response.json()["sent_message_id"]

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT contenido FROM messages WHERE id = :id"),
            {"id": sent_id},
        ).fetchone()
    assert row.contenido == texto_editado


def test_discard_draft_never_sends_anything(
    client, api_as_tenant, tenant_con_conversacion_indexada, postgres_engine
):
    """Criterio SPEC-019: descartar un borrador no genera ningún envío ni
    mensaje persistido de salida, y bloquea aprobación/edición posteriores."""
    data = tenant_con_conversacion_indexada
    draft = _crear_borrador(client, api_as_tenant, data).json()
    draft_id = draft["id"]

    with api_as_tenant(data["tenant_id"]):
        discard_response = client.post(
            f"/api/v1/rag/conversations/{data['conversation_id']}"
            f"/drafts/{draft_id}/discard"
        )
    assert discard_response.status_code == 200
    assert discard_response.json()["estado"] == "descartado"

    assert _count_outgoing_messages(postgres_engine, data["conversation_id"]) == 0

    # Un borrador descartado ya no admite aprobación (estado terminal).
    with api_as_tenant(data["tenant_id"]):
        approve_after_discard = client.post(
            f"/api/v1/rag/conversations/{data['conversation_id']}"
            f"/drafts/{draft_id}/approve"
        )
    assert approve_after_discard.status_code == 409
    assert _count_outgoing_messages(postgres_engine, data["conversation_id"]) == 0


def test_approved_draft_cannot_be_approved_or_edited_again(
    client, api_as_tenant, tenant_con_conversacion_indexada, postgres_engine
):
    """Un borrador ya aprobado (estado terminal) no admite doble envío."""
    data = tenant_con_conversacion_indexada
    draft = _crear_borrador(client, api_as_tenant, data).json()
    draft_id = draft["id"]

    with api_as_tenant(data["tenant_id"]):
        client.post(
            f"/api/v1/rag/conversations/{data['conversation_id']}"
            f"/drafts/{draft_id}/approve"
        )

    with api_as_tenant(data["tenant_id"]):
        second_approve = client.post(
            f"/api/v1/rag/conversations/{data['conversation_id']}"
            f"/drafts/{draft_id}/approve"
        )
    assert second_approve.status_code == 409
    # Nunca un segundo mensaje saliente por el mismo borrador.
    assert _count_outgoing_messages(postgres_engine, data["conversation_id"]) == 1


def test_approve_service_never_calls_create_message_when_update_rowcount_is_zero(
    monkeypatch,
):
    """Test de la ruta atómica (rowcount==0) que corre SIN daemon/Postgres:
    verifica, a nivel de `draft_review_service.approve_and_send`, que si el
    UPDATE condicional no afecta ninguna fila (porque, p.ej., una request
    concurrente ya aprobó/descartó el borrador entre la lectura y la
    escritura), la función JAMÁS invoca `create_message` — que es la
    garantía real de "nunca dos mensajes" ante una carrera (BLOQUEANTE de
    la revisión de BLACK PANTHER a SPEC-019).

    No usa una base de datos real: reemplaza `db.execute` por un doble que
    simula el `CursorResult` de un `UPDATE ... WHERE estado IN (...)` con
    `rowcount == 0` (la fila ya no cumple el `WHERE`), exactamente lo que
    devolvería SQLAlchemy/psycopg cuando otra transacción ganó la carrera.
    """
    import uuid as uuid_module
    from unittest.mock import MagicMock

    from app.models.rag_draft import RagDraft
    from app.services.rag import draft_review_service

    draft = RagDraft(
        id=uuid_module.uuid4(),
        tenant_id=uuid_module.uuid4(),
        conversation_id=uuid_module.uuid4(),
        query="¿algo?",
        content_original="borrador original",
        content="borrador original",
        model="qwen2.5-fake",
        citations=[],
        estado="propuesto",
        created_by="agente@tenant.test",
    )

    fake_db = MagicMock()
    fake_update_result = MagicMock()
    fake_update_result.rowcount = 0  # otra transacción ya ganó la carrera
    fake_db.execute.return_value = fake_update_result

    create_message_spy = MagicMock()
    monkeypatch.setattr(draft_review_service, "create_message", create_message_spy)

    with pytest.raises(draft_review_service.DraftNotMutableError):
        draft_review_service.approve_and_send(
            fake_db, draft, approved_by="agente-2@tenant.test"
        )

    # La garantía central: rowcount == 0 -> jamás se llega a crear el mensaje.
    create_message_spy.assert_not_called()
    fake_db.refresh.assert_not_called()


def test_concurrent_approve_requests_only_send_one_message(
    client, api_as_tenant, tenant_con_conversacion_indexada, postgres_engine
):
    """Test de CONCURRENCIA end-to-end contra PostgreSQL real (se SKIPEA sin
    Postgres accesible, mismo patrón que el resto de este archivo; correr en
    CI): dos requests `approve` disparadas al mismo tiempo (dos hilos, dos
    conexiones/transacciones reales) sobre el MISMO borrador deben resultar
    en EXACTAMENTE un `Message` saliente — la segunda debe fallar con 409
    (el UPDATE condicional serializa las transacciones a nivel de fila de
    PostgreSQL: la segunda transacción espera el lock de la primera y, al
    verlo ya `aprobado`, su `WHERE estado IN (...)` no matchea ninguna fila).
    """
    import threading

    data = tenant_con_conversacion_indexada
    draft = _crear_borrador(client, api_as_tenant, data).json()
    draft_id = draft["id"]

    resultados: list[int] = []
    barrera = threading.Barrier(2)

    # El override de dependencias de FastAPI (`app.dependency_overrides`) es
    # un diccionario GLOBAL de la app: se fija UNA sola vez aquí (fuera de
    # los hilos) para evitar que el `__enter__`/`__exit__` (que hace `pop`)
    # de un hilo interfiera con la petición HTTP en vuelo del otro — eso
    # sería una carrera del propio arnés de test, no del código bajo prueba.
    with api_as_tenant(data["tenant_id"]):

        def _approve() -> None:
            barrera.wait(timeout=5)
            response = client.post(
                f"/api/v1/rag/conversations/{data['conversation_id']}"
                f"/drafts/{draft_id}/approve"
            )
            resultados.append(response.status_code)

        hilo_a = threading.Thread(target=_approve)
        hilo_b = threading.Thread(target=_approve)
        hilo_a.start()
        hilo_b.start()
        hilo_a.join(timeout=10)
        hilo_b.join(timeout=10)

    assert sorted(resultados) == [200, 409], (
        "Exactamente una de las dos aprobaciones concurrentes debe tener "
        f"éxito (200) y la otra debe rechazarse (409); se obtuvo {resultados}"
    )
    assert _count_outgoing_messages(postgres_engine, data["conversation_id"]) == 1


def test_draft_isolated_by_tenant(
    client, api_as_tenant, tenant_con_conversacion_indexada
):
    """RLS: un borrador de un tenant no es accesible por otro tenant."""
    data = tenant_con_conversacion_indexada
    draft = _crear_borrador(client, api_as_tenant, data).json()
    draft_id = draft["id"]

    otro_tenant_id = uuid.uuid4()
    with api_as_tenant(otro_tenant_id):
        get_response = client.get(
            f"/api/v1/rag/conversations/{data['conversation_id']}" f"/drafts/{draft_id}"
        )
    assert get_response.status_code == 404

    with api_as_tenant(otro_tenant_id):
        approve_response = client.post(
            f"/api/v1/rag/conversations/{data['conversation_id']}"
            f"/drafts/{draft_id}/approve"
        )
    assert approve_response.status_code == 404


def test_draft_endpoints_require_authentication(client):
    """Sin JWT, los endpoints de borrador devuelven 401 (no 500 ni datos)."""
    conversation_id = uuid.uuid4()
    draft_id = uuid.uuid4()

    responses = [
        client.post(
            f"/api/v1/rag/conversations/{conversation_id}/drafts",
            json={"query": "hola"},
        ),
        client.get(f"/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}"),
        client.patch(
            f"/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}",
            json={"content": "x"},
        ),
        client.post(
            f"/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/approve"
        ),
        client.post(
            f"/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/discard"
        ),
    ]
    for response in responses:
        assert response.status_code == 401
