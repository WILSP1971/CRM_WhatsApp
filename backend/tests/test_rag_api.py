"""Tests de integración de `app/api/rag.py` — SPEC-017, contra PostgreSQL real
+ Redis real (o `fakeredis`, mismo doble usado por SPEC-015 para el pub/sub
del WebChat).

Requiere el `db` de `docker-compose.yml` (pgvector); se SKIPEA automáticamente
sin Postgres accesible (`tests/conftest.py::postgres_engine`), mismo patrón
que `tests/test_api_v1_integration.py`. `AIClient` mockeado vía
`app.dependency_overrides[get_ai_client]` (SPEC-016): ningún test llama a un
modelo real. La cola Redis usa `fakeredis.aioredis` (mismo doble ya usado en
`tests/test_ws_chat_integration.py` para SPEC-015): NO requiere un daemon
Redis real para los tests de contrato HTTP de encolado/consumo.

Verifica el contrato HTTP + cola de SPEC-017 (RNF-06/R-28):
  - `POST /rag/documents/{id}/ingest` responde 202 de inmediato SIN procesar
    la ingesta en el propio request (queda en Redis); el documento sigue
    `pendiente` hasta que el WORKER (`app.workers.rag_ingest_worker`) drena
    la cola — el endpoint YA NO usa `BackgroundTasks` in-process.
  - Tras drenar la cola con el worker, el documento queda `indexado` y las
    citas de `/rag/draft` son trazables (≥3, `source`/`excerpt`/
    `similarityScore`).
  - Aislamiento cross-tenant: un tenant no puede ingestar/consultar
    documentos de otro tenant (404); un job no puede alterar datos de un
    tenant distinto al dueño real del documento.
  - Modo degradado: si el `AIClient` no está disponible, `/rag/draft`
    responde 503 (no 500 ni un borrador fabricado).
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


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fake_redis():
    """Doble de Redis en memoria (protocolo `redis.asyncio`), mismo patrón
    que `tests/test_ws_chat_integration.py` (SPEC-015): permite probar el
    encolado/consumo SIN un daemon Redis real."""
    redis_instance = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.dependency_overrides[get_redis_client] = lambda: redis_instance
    yield redis_instance


@pytest.fixture
def api_as_tenant(postgres_engine):
    """Mismo patrón que `tests/test_api_v1_integration.py::api_as_tenant`."""

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
def tenant_con_documento(postgres_engine):
    """Crea un tenant + documento `pendiente` reales, listo para ingestar."""
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO tenants (id, nombre, slug) VALUES (:id, :nombre, :slug)"
            ),
            {
                "id": tenant_id,
                "nombre": "Tenant API RAG",
                "slug": f"api-rag-{tenant_id.hex[:8]}",
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO documents (id, tenant_id, nombre_archivo, tipo, estado) "
                "VALUES (:id, :tenant_id, 'faq-envios.txt', 'txt', 'pendiente')"
            ),
            {"id": document_id, "tenant_id": tenant_id},
        )
    return {"tenant_id": tenant_id, "document_id": document_id}


def _use_fake_ai_client(**kwargs) -> FakeAIClient:
    fake = FakeAIClient(**kwargs)
    app.dependency_overrides[get_ai_client] = lambda: fake
    return fake


def _session_factory_for(postgres_engine):
    def _factory() -> Session:
        return Session(postgres_engine)

    return _factory


async def _drain_all(fake_redis, tenant_id, postgres_engine) -> int:
    """Simula el proceso worker: drena todos los jobs pendientes de un
    tenant, usando una `Session` sobre el MISMO `postgres_engine` de test
    (en vez del `SessionLocal` cacheado de producción)."""
    procesados = 0
    session_factory = _session_factory_for(postgres_engine)
    while await drain_one(
        fake_redis, tenant_id=tenant_id, session_factory=session_factory
    ):
        procesados += 1
    return procesados


def test_ingest_endpoint_enqueues_and_does_not_process_inline(
    client, api_as_tenant, tenant_con_documento, fake_redis, postgres_engine
):
    """El endpoint SOLO encola (RNF-06/R-28): el documento sigue `pendiente`
    inmediatamente después del 202, porque el procesamiento real lo hace el
    worker (no un `BackgroundTask` in-process del propio request)."""
    data = tenant_con_documento
    _use_fake_ai_client()

    with api_as_tenant(data["tenant_id"]):
        response = client.post(
            f"/api/v1/rag/documents/{data['document_id']}/ingest",
            json={
                "text": "Los envíos nacionales tardan de 3 a 5 días hábiles. " * 20,
                "chunk_size": 150,
                "chunk_overlap": 20,
            },
        )

    assert response.status_code == 202
    body = response.json()
    assert body["document_id"] == str(data["document_id"])

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT estado FROM documents WHERE id = :id"),
            {"id": data["document_id"]},
        ).fetchone()
        assert row.estado == "pendiente", (
            "El endpoint no debe procesar la ingesta inline; debe quedar "
            "encolada hasta que el worker la consuma"
        )


@pytest.mark.asyncio
async def test_worker_drains_queue_and_document_ends_indexed(
    client, api_as_tenant, tenant_con_documento, fake_redis, postgres_engine
):
    """Tras encolar vía HTTP, el WORKER (`drain_one`/`process_job`) consume
    el job real de Redis y deja el documento `indexado` con chunks/embeddings
    persistidos — verifica el cableado end-to-end de la cola (BLOQUEANTE de
    la revisión: la cola deja de ser código muerto)."""
    data = tenant_con_documento
    _use_fake_ai_client()

    with api_as_tenant(data["tenant_id"]):
        response = client.post(
            f"/api/v1/rag/documents/{data['document_id']}/ingest",
            json={
                "text": "Los envíos nacionales tardan de 3 a 5 días hábiles. " * 20,
                "chunk_size": 150,
                "chunk_overlap": 20,
            },
        )
    assert response.status_code == 202

    procesados = await _drain_all(fake_redis, data["tenant_id"], postgres_engine)
    assert procesados == 1

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT estado FROM documents WHERE id = :id"),
            {"id": data["document_id"]},
        ).fetchone()
        assert row.estado == "indexado"

        chunks = conn.execute(
            sa.text(
                "SELECT count(*) FROM chunks WHERE document_id = :id AND activo IS true"
            ),
            {"id": data["document_id"]},
        ).scalar_one()
        assert chunks > 0


def test_ingest_endpoint_404_for_document_of_other_tenant(
    client, api_as_tenant, tenant_con_documento, fake_redis
):
    """Un tenant no puede ingestar un documento de otro tenant (RLS/404)."""
    data = tenant_con_documento
    _use_fake_ai_client()
    otro_tenant_id = uuid.uuid4()

    with api_as_tenant(otro_tenant_id):
        response = client.post(
            f"/api/v1/rag/documents/{data['document_id']}/ingest",
            json={"text": "contenido irrelevante"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_draft_endpoint_returns_at_least_3_traceable_citations(
    client, api_as_tenant, tenant_con_documento, fake_redis, postgres_engine
):
    data = tenant_con_documento
    _use_fake_ai_client()

    with api_as_tenant(data["tenant_id"]):
        ingest_response = client.post(
            f"/api/v1/rag/documents/{data['document_id']}/ingest",
            json={
                "text": (
                    "Los envíos nacionales tardan de 3 a 5 días hábiles. "
                    "Los envíos internacionales tardan de 10 a 15 días hábiles. "
                    "El costo de envío nacional es gratis sobre pedidos de $150.000. "
                    "Puedes rastrear tu pedido con el número de guía en el portal. "
                )
                * 10,
                "chunk_size": 150,
                "chunk_overlap": 20,
            },
        )
        assert ingest_response.status_code == 202

    await _drain_all(fake_redis, data["tenant_id"], postgres_engine)

    with api_as_tenant(data["tenant_id"]):
        draft_response = client.post(
            "/api/v1/rag/draft",
            json={"query": "¿Cuánto tardan los envíos nacionales?", "top_k": 5},
        )

    assert draft_response.status_code == 200
    body = draft_response.json()
    assert body["content"]
    assert len(body["citations"]) >= 3
    for citation in body["citations"]:
        assert citation["source"] == "faq-envios.txt"
        assert citation["excerpt"]
        assert 0.0 <= citation["similarityScore"] <= 1.0
        assert citation["chunk_id"]
        assert citation["document_id"] == str(data["document_id"])


@pytest.mark.asyncio
async def test_draft_endpoint_returns_503_when_ai_unavailable(
    client, api_as_tenant, tenant_con_documento, fake_redis, postgres_engine
):
    """Modo degradado (R-21): sin servicio de IA disponible, 503 explícito."""
    data = tenant_con_documento

    with api_as_tenant(data["tenant_id"]):
        _use_fake_ai_client()
        ingest_response = client.post(
            f"/api/v1/rag/documents/{data['document_id']}/ingest",
            json={"text": "Contenido de prueba para indexar correctamente. " * 20},
        )
        assert ingest_response.status_code == 202

    await _drain_all(fake_redis, data["tenant_id"], postgres_engine)

    with api_as_tenant(data["tenant_id"]):
        _use_fake_ai_client(unavailable=True)
        draft_response = client.post(
            "/api/v1/rag/draft", json={"query": "cualquier cosa", "top_k": 5}
        )

    assert draft_response.status_code == 503


@pytest.mark.asyncio
async def test_draft_endpoint_isolated_by_tenant_never_cites_other_tenant_document(
    client, api_as_tenant, postgres_engine, fake_redis
):
    """Aislamiento cross-tenant en el flujo completo API: el tenant B jamás
    recibe citas de un documento del tenant A, aunque pregunte lo mismo."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    doc_a = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO tenants (id, nombre, slug) VALUES (:id, :n, :s)"),
            [
                {"id": tenant_a, "n": "Tenant A RAG", "s": f"a-rag-{tenant_a.hex[:8]}"},
                {"id": tenant_b, "n": "Tenant B RAG", "s": f"b-rag-{tenant_b.hex[:8]}"},
            ],
        )
        conn.execute(
            sa.text(
                "INSERT INTO documents (id, tenant_id, nombre_archivo, tipo, estado) "
                "VALUES (:id, :tenant_id, 'confidencial-a.txt', 'txt', 'pendiente')"
            ),
            {"id": doc_a, "tenant_id": tenant_a},
        )

    with api_as_tenant(tenant_a):
        _use_fake_ai_client()
        ingest_response = client.post(
            f"/api/v1/rag/documents/{doc_a}/ingest",
            json={"text": "Información confidencial exclusiva del tenant A. " * 20},
        )
        assert ingest_response.status_code == 202

    await _drain_all(fake_redis, tenant_a, postgres_engine)

    with api_as_tenant(tenant_b):
        _use_fake_ai_client()
        draft_response = client.post(
            "/api/v1/rag/draft",
            json={"query": "información confidencial exclusiva", "top_k": 5},
        )

    # El tenant B no tiene documentos propios indexados -> sin contexto
    # suficiente para citas -> 404 explícito, NUNCA citas del tenant A.
    assert draft_response.status_code == 404
