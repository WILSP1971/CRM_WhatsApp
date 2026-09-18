"""Tests de `app.services.rag.retrieval_service` — SPEC-017 RF-07.

Requiere PostgreSQL real con `pgvector`; se SKIPEA automáticamente sin
Postgres accesible (`tests/conftest.py::postgres_engine`), mismo patrón que
`tests/test_rls_isolation.py`. `AIClient` mockeado (`FakeAIClient`).

Verifica (criterios de aceptación SPEC-017):
  (b) la recuperación devuelve solo chunks del tenant, ordenados por
      similitud (score descendente / distancia coseno ascendente);
  (d) aislamiento cross-tenant: un tenant NUNCA recupera chunks/documentos
      de otro tenant, aunque la query coincida semánticamente.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.session import set_tenant_session
from app.services.rag.ingest_service import ingest_document
from app.services.rag.retrieval_service import TopKConfigError, retrieve_top_k
from tests.rag_ai_client_fake import FakeAIClient

import pytest


def _crear_tenant(postgres_engine, nombre: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
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


def _crear_documento(
    postgres_engine, tenant_id: uuid.UUID, nombre_archivo: str
) -> uuid.UUID:
    document_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO documents (id, tenant_id, nombre_archivo, tipo, estado) "
                "VALUES (:id, :tenant_id, :nombre_archivo, 'txt', 'pendiente')"
            ),
            {
                "id": document_id,
                "tenant_id": tenant_id,
                "nombre_archivo": nombre_archivo,
            },
        )
    return document_id


def _ingest(postgres_engine, tenant_id, document_id, text, ai_client, chunk_size=120):
    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            return ingest_document(
                db, ai_client, document_id=document_id, text=text, chunk_size=chunk_size
            )


def test_recuperacion_devuelve_chunks_ordenados_por_similitud(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantOrden")
    document_id = _crear_documento(postgres_engine, tenant_id, "faq.txt")
    ai_client = FakeAIClient()

    # Tres fragmentos claramente distintos entre sí para que el fake de
    # embeddings determinístico produzca similitudes distinguibles.
    texto = (
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA. "
        "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB. "
        "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC."
    )
    result = _ingest(
        postgres_engine, tenant_id, document_id, texto, ai_client, chunk_size=80
    )
    assert result.chunks_creados >= 3

    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            # Consulta idéntica al primer fragmento: debe recuperarlo primero.
            retrieved = retrieve_top_k(
                db,
                ai_client,
                query="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                top_k=3,
            )

    assert len(retrieved) == 3
    scores = [r.similarity_score for r in retrieved]
    assert scores == sorted(
        scores, reverse=True
    ), "Los resultados deben venir ordenados por score descendente"
    assert all(r.document_id == str(document_id) for r in retrieved)
    # El chunk más similar a la consulta "AAA..." debe contener "A".
    assert "A" in retrieved[0].excerpt


def test_recuperacion_solo_devuelve_chunks_del_tenant_autenticado(postgres_engine):
    tenant_a = _crear_tenant(postgres_engine, "TenantAisladoA")
    tenant_b = _crear_tenant(postgres_engine, "TenantAisladoB")
    doc_a = _crear_documento(postgres_engine, tenant_a, "politica-a.txt")
    doc_b = _crear_documento(postgres_engine, tenant_b, "politica-b.txt")

    ai_client = FakeAIClient()
    texto_a = "Política confidencial del tenant A sobre reembolsos y garantías. " * 10
    texto_b = "Política confidencial del tenant B sobre reembolsos y garantías. " * 10

    _ingest(postgres_engine, tenant_a, doc_a, texto_a, ai_client)
    _ingest(postgres_engine, tenant_b, doc_b, texto_b, ai_client)

    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_a))
            retrieved_as_a = retrieve_top_k(
                db, ai_client, query="política de reembolsos y garantías", top_k=10
            )

    assert len(retrieved_as_a) > 0
    assert all(
        r.document_id == str(doc_a) for r in retrieved_as_a
    ), "FUGA CROSS-TENANT: el tenant A recuperó chunks del documento del tenant B"
    fuentes = {r.source for r in retrieved_as_a}
    assert fuentes == {"politica-a.txt"}


def test_recuperacion_excluye_documentos_inactivos_borrado_logico(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantBorradoLogico")
    document_id = _crear_documento(postgres_engine, tenant_id, "obsoleto.txt")
    ai_client = FakeAIClient()

    _ingest(
        postgres_engine,
        tenant_id,
        document_id,
        "Contenido que será borrado lógicamente después de indexar. " * 10,
        ai_client,
    )

    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE documents SET activo = false WHERE id = :id"),
            {"id": document_id},
        )

    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            retrieved = retrieve_top_k(
                db, ai_client, query="contenido borrado lógicamente", top_k=5
            )

    assert (
        retrieved == []
    ), "Un documento inactivo (C2) no debe aparecer en la recuperación"


def test_top_k_fuera_de_rango_lanza_error(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantTopK")
    ai_client = FakeAIClient()

    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            with pytest.raises(TopKConfigError):
                retrieve_top_k(db, ai_client, query="algo", top_k=0)
            with pytest.raises(TopKConfigError):
                retrieve_top_k(db, ai_client, query="algo", top_k=999)
