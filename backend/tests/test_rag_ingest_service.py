"""Tests de `app.services.rag.ingest_service` — SPEC-017 RF-06.

Requiere PostgreSQL real con `pgvector` (el `db` de `docker-compose.yml`,
esquema de SPEC-012 aplicado vía Alembic). Si no hay Postgres accesible
(p.ej. este sandbox sin daemon Docker), se SKIPEAN automáticamente vía el
fixture `postgres_engine` (`tests/conftest.py`) — mismo patrón que
`tests/test_rls_isolation.py`/`tests/test_api_v1_integration.py`.

`AIClient` está SIEMPRE mockeado (`tests/rag_ai_client_fake.py`): ningún test
aquí llama a un modelo real ni requiere GPU/Ollama.

Verifica (criterios de aceptación SPEC-017):
  (a) la ingesta crea chunks + embeddings dentro del tenant y transiciona el
      documento a `indexado`;
  (b) un documento sin texto indexable queda en `error`;
  (c) el modo degradado (AIClient no disponible) deja el documento en `error`
      sin lanzar una excepción sin control (R-21), y los chunks/embeddings
      insertados PARCIALMENTE en ese intento fallido quedan inactivos (no
      visibles a `retrieval_service`, corrección MENOR de BLACK PANTHER);
  (d) un reintento sobre un documento ya indexado es idempotente: no duplica
      chunks/embeddings activos (R-28).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.session import set_tenant_session
from app.services.rag.ingest_service import (
    ESTADO_ERROR,
    ESTADO_INDEXADO,
    ingest_document,
)
from tests.rag_ai_client_fake import FakeAIClient


class _FlakyAfterNAIClient(FakeAIClient):
    """Doble que falla a partir del N-ésimo `embed()` (simula una caída del
    servicio de IA a mitad de un documento con varios chunks)."""

    def __init__(self, fail_after: int):
        super().__init__()
        self._fail_after = fail_after

    def embed(self, text: str, *, model: str | None = None):
        if len(self.embed_calls) >= self._fail_after:
            from app.services.ai_service import AIServiceUnavailableError

            raise AIServiceUnavailableError("caída simulada a mitad de documento")
        return super().embed(text)


def _crear_tenant_y_documento(postgres_engine) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO tenants (id, nombre, slug) VALUES (:id, :nombre, :slug)"
            ),
            {
                "id": tenant_id,
                "nombre": "Tenant RAG",
                "slug": f"rag-{tenant_id.hex[:8]}",
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO documents (id, tenant_id, nombre_archivo, tipo, estado) "
                "VALUES (:id, :tenant_id, :nombre_archivo, :tipo, 'pendiente')"
            ),
            {
                "id": document_id,
                "tenant_id": tenant_id,
                "nombre_archivo": "manual-onboarding.txt",
                "tipo": "txt",
            },
        )
    return tenant_id, document_id


def test_ingesta_crea_chunks_y_embeddings_y_marca_indexado(postgres_engine):
    tenant_id, document_id = _crear_tenant_y_documento(postgres_engine)
    ai_client = FakeAIClient()
    texto = "El horario de atención es de 8am a 6pm. " * 40

    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            result = ingest_document(
                db,
                ai_client,
                document_id=document_id,
                text=texto,
                chunk_size=200,
                chunk_overlap=20,
            )

    assert result.estado == ESTADO_INDEXADO
    assert result.chunks_creados > 0
    assert len(ai_client.embed_calls) == result.chunks_creados

    with postgres_engine.connect() as conn:
        document = conn.execute(
            sa.text("SELECT estado FROM documents WHERE id = :id"), {"id": document_id}
        ).fetchone()
        assert document.estado == ESTADO_INDEXADO

        chunks = conn.execute(
            sa.text("SELECT id, tenant_id, activo FROM chunks WHERE document_id = :id"),
            {"id": document_id},
        ).fetchall()
        assert len(chunks) == result.chunks_creados
        assert all(c.tenant_id == tenant_id for c in chunks)
        assert all(c.activo for c in chunks)

        chunk_ids = [c.id for c in chunks]
        embeddings = conn.execute(
            sa.text(
                "SELECT chunk_id, tenant_id, activo FROM embeddings "
                "WHERE chunk_id = ANY(:chunk_ids)"
            ),
            {"chunk_ids": chunk_ids},
        ).fetchall()
        assert len(embeddings) == result.chunks_creados
        assert all(e.tenant_id == tenant_id for e in embeddings)
        assert all(e.activo for e in embeddings)


def test_documento_sin_texto_indexable_queda_en_error(postgres_engine):
    tenant_id, document_id = _crear_tenant_y_documento(postgres_engine)
    ai_client = FakeAIClient()

    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            result = ingest_document(db, ai_client, document_id=document_id, text="   ")

    assert result.estado == ESTADO_ERROR
    assert result.chunks_creados == 0
    assert result.error


def test_modo_degradado_ai_no_disponible_deja_documento_en_error(postgres_engine):
    """R-21: si el servicio de IA local no responde, el documento queda en
    `error` (reintentable) en vez de propagar una excepción sin control."""
    tenant_id, document_id = _crear_tenant_y_documento(postgres_engine)
    ai_client = FakeAIClient(unavailable=True)

    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            result = ingest_document(
                db, ai_client, document_id=document_id, text="contenido de prueba " * 20
            )

    assert result.estado == ESTADO_ERROR
    assert result.error is not None


def test_fallo_a_mitad_de_documento_invalida_chunks_parciales(postgres_engine):
    """MENOR (revisión BLACK PANTHER): si `AIClient.embed` falla a mitad de
    un documento con varios chunks, los chunks/embeddings YA insertados en
    ESE intento no deben quedar `activo=True` (visibles a retrieval) mientras
    el documento está en `error`."""
    tenant_id, document_id = _crear_tenant_y_documento(postgres_engine)
    # chunk_size pequeño para forzar varios chunks; falla después del primero.
    ai_client = _FlakyAfterNAIClient(fail_after=1)
    texto = (
        "Fragmento uno de contenido. Fragmento dos de contenido. Fragmento tres. " * 5
    )

    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            result = ingest_document(
                db, ai_client, document_id=document_id, text=texto, chunk_size=40
            )

    assert result.estado == ESTADO_ERROR

    with postgres_engine.connect() as conn:
        chunks_activos = conn.execute(
            sa.text(
                "SELECT count(*) FROM chunks WHERE document_id = :id AND activo IS true"
            ),
            {"id": document_id},
        ).scalar_one()
        embeddings_activos = conn.execute(
            sa.text(
                "SELECT count(*) FROM embeddings e "
                "JOIN chunks c ON c.id = e.chunk_id "
                "WHERE c.document_id = :id AND e.activo IS true"
            ),
            {"id": document_id},
        ).scalar_one()

    assert chunks_activos == 0, (
        "Un chunk insertado en un intento fallido no debe quedar activo "
        "(visible a retrieval_service)"
    )
    assert embeddings_activos == 0


def test_reintento_es_idempotente_no_duplica_chunks_activos(postgres_engine):
    """R-28: reintentar la ingesta de un documento ya indexado no acumula
    chunks/embeddings duplicados activos (los del intento previo se
    invalidan, borrado lógico C2)."""
    tenant_id, document_id = _crear_tenant_y_documento(postgres_engine)
    ai_client = FakeAIClient()
    texto = "Política de reembolsos: 30 días calendario desde la compra. " * 30

    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            primer_resultado = ingest_document(
                db, ai_client, document_id=document_id, text=texto, chunk_size=150
            )

    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            segundo_resultado = ingest_document(
                db, ai_client, document_id=document_id, text=texto, chunk_size=150
            )

    assert primer_resultado.estado == ESTADO_INDEXADO
    assert segundo_resultado.estado == ESTADO_INDEXADO

    with postgres_engine.connect() as conn:
        chunks_activos = conn.execute(
            sa.text(
                "SELECT count(*) FROM chunks WHERE document_id = :id AND activo IS true"
            ),
            {"id": document_id},
        ).scalar_one()
        chunks_totales = conn.execute(
            sa.text("SELECT count(*) FROM chunks WHERE document_id = :id"),
            {"id": document_id},
        ).scalar_one()

    # Mismo número de chunks activos que produce un único intento (no se
    # duplican), aunque en la tabla física queden también los inactivos del
    # primer intento (borrado lógico, C2 — nunca DELETE físico).
    assert chunks_activos == segundo_resultado.chunks_creados
    assert (
        chunks_totales
        == primer_resultado.chunks_creados + segundo_resultado.chunks_creados
    )
