"""Tests de `app.services.rag.draft_service` — SPEC-017 (criterio central).

Requiere PostgreSQL real con `pgvector`; se SKIPEA automáticamente sin
Postgres accesible (`tests/conftest.py::postgres_engine`). `AIClient`
mockeado (`FakeAIClient`): sin modelo real ni GPU.

Verifica (criterios de aceptación SPEC-017):
  (c) el borrador generado incluye ≥3 citas con `source`+`excerpt`+
      `similarityScore`, y esas citas apuntan a chunks reales del documento
      ingerido (trazabilidad verificable);
  - si no hay suficiente contexto (<3 chunks recuperables), se rechaza
    explícitamente en vez de fabricar citas falsas.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.session import set_tenant_session
from app.services.ai_service import AIServiceUnavailableError
from app.services.rag.draft_service import (
    MIN_CITATIONS,
    InsufficientContextError,
    generate_rag_draft,
)
from app.services.rag.ingest_service import ingest_document
from tests.rag_ai_client_fake import FakeAIClient


def _crear_tenant_con_documento_indexado(postgres_engine, texto: str, chunk_size=100):
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO tenants (id, nombre, slug) VALUES (:id, :nombre, :slug)"
            ),
            {
                "id": tenant_id,
                "nombre": "Tenant Draft",
                "slug": f"draft-{tenant_id.hex[:8]}",
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO documents (id, tenant_id, nombre_archivo, tipo, estado) "
                "VALUES (:id, :tenant_id, 'manual-servicio.txt', 'txt', 'pendiente')"
            ),
            {"id": document_id, "tenant_id": tenant_id},
        )

    ai_client = FakeAIClient()
    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            ingest_document(
                db,
                ai_client,
                document_id=document_id,
                text=texto,
                chunk_size=chunk_size,
            )
    return tenant_id, document_id, ai_client


def test_borrador_incluye_al_menos_3_citas_trazables(postgres_engine):
    texto = (
        "Horario de atención: lunes a viernes de 8am a 6pm. "
        "Política de reembolsos: 30 días calendario desde la compra. "
        "Canal de soporte prioritario: WhatsApp Business verificado. "
        "Garantía extendida disponible para productos electrónicos. "
    ) * 5
    tenant_id, document_id, ai_client = _crear_tenant_con_documento_indexado(
        postgres_engine, texto
    )

    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            result = generate_rag_draft(
                db, ai_client, query="¿Cuál es el horario de atención?", top_k=5
            )

    assert result.content
    assert len(result.citations) >= MIN_CITATIONS
    for citation in result.citations:
        assert citation.source == "manual-servicio.txt"
        assert citation.excerpt.strip() != ""
        assert 0.0 <= citation.similarity_score <= 1.0
        # Trazabilidad: cada cita apunta a un chunk/documento reales.
        assert uuid.UUID(citation.chunk_id)
        assert uuid.UUID(citation.document_id) == document_id


def test_borrador_falla_explicito_si_no_hay_suficiente_contexto(postgres_engine):
    """Si el tenant no tiene al menos MIN_CITATIONS chunks recuperables, se
    rechaza explícitamente (nunca se fabrican citas de relleno)."""
    tenant_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO tenants (id, nombre, slug) VALUES (:id, :nombre, :slug)"
            ),
            {
                "id": tenant_id,
                "nombre": "Tenant Sin Contexto",
                "slug": f"sincontexto-{tenant_id.hex[:8]}",
            },
        )

    ai_client = FakeAIClient()
    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            with pytest.raises(InsufficientContextError):
                generate_rag_draft(db, ai_client, query="¿algo?", top_k=5)


def test_borrador_propaga_modo_degradado_si_ia_no_disponible(postgres_engine):
    """R-21: si el LLM local no responde tras recuperar contexto suficiente,
    se propaga el error de servicio (el endpoint lo traduce a 503) en vez de
    devolver un borrador fabricado."""
    texto = "Contenido de prueba suficientemente largo para varios chunks. " * 20
    tenant_id, document_id, _ = _crear_tenant_con_documento_indexado(
        postgres_engine, texto
    )

    ai_client_no_disponible = FakeAIClient(unavailable=True)
    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            with pytest.raises(AIServiceUnavailableError):
                generate_rag_draft(
                    db, ai_client_no_disponible, query="cualquier consulta", top_k=5
                )
