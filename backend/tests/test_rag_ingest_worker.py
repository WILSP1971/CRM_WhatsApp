"""Tests de `app.workers.rag_ingest_worker` — SPEC-017 RNF-06/R-28.

Requiere PostgreSQL real (`tests/conftest.py::postgres_engine`); se SKIPEA
automáticamente sin Postgres accesible. `AIClient` mockeado
(`tests/rag_ai_client_fake.py`).

Verifica (revisión BLACK PANTHER, MAYOR):
  (a) `process_job` con un `tenant_id` que NO coincide con el dueño real del
      documento se RECHAZA (`TenantMismatchError`) SIN fijar RLS ni escribir
      nada — defensa contra un job forjado/corrupto en la cola;
  (b) `process_job` con un `document_id` inexistente no falla con una
      excepción sin control (se loguea y no hace nada);
  (c) `process_job` con el tenant correcto sí indexa con normalidad (caso
      feliz, para contrastar con (a)).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.rag_queue import IngestJob
from app.workers.rag_ingest_worker import TenantMismatchError, process_job
from tests.rag_ai_client_fake import FakeAIClient


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


def _session_factory(postgres_engine):
    def _factory() -> Session:
        return Session(postgres_engine)

    return _factory


def test_process_job_rejects_forged_tenant_id_mismatch(postgres_engine):
    """MAYOR (BLACK PANTHER): un job cuyo `tenant_id` no coincide con el
    dueño real del documento se rechaza ANTES de fijar `app.tenant_id` o
    escribir cualquier chunk/embedding."""
    tenant_real = _crear_tenant(postgres_engine, "TenantReal")
    tenant_atacante = _crear_tenant(postgres_engine, "TenantAtacante")
    document_id = _crear_documento(postgres_engine, tenant_real, "confidencial.txt")

    job_forjado = IngestJob(
        tenant_id=str(tenant_atacante),  # tenant_id NO es el dueño real
        document_id=str(document_id),
        text="Intento de leer/escribir bajo un tenant_id ajeno. " * 10,
    )

    try:
        process_job(
            job_forjado,
            ai_client=FakeAIClient(),
            session_factory=_session_factory(postgres_engine),
        )
        raised = False
    except TenantMismatchError:
        raised = True

    assert raised, "Un job con tenant_id no coincidente debe ser rechazado"

    with postgres_engine.connect() as conn:
        documento = conn.execute(
            sa.text("SELECT estado FROM documents WHERE id = :id"),
            {"id": document_id},
        ).fetchone()
        chunks = conn.execute(
            sa.text("SELECT count(*) FROM chunks WHERE document_id = :id"),
            {"id": document_id},
        ).scalar_one()

    assert documento.estado == "pendiente", (
        "Un job rechazado por tenant_id no coincidente no debe alterar el "
        "estado del documento"
    )
    assert chunks == 0, "Un job rechazado no debe insertar chunks"


def test_process_job_unknown_document_does_not_raise(postgres_engine):
    """Un job que referencia un documento inexistente no debe propagar una
    excepción sin control (se loguea y se descarta)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSinDocumento")
    job = IngestJob(
        tenant_id=str(tenant_id),
        document_id=str(uuid.uuid4()),  # no existe
        text="contenido irrelevante",
    )

    process_job(
        job, ai_client=FakeAIClient(), session_factory=_session_factory(postgres_engine)
    )  # no debe lanzar


def test_process_job_with_matching_tenant_indexes_normally(postgres_engine):
    """Caso feliz de contraste: con el `tenant_id` correcto, el job procesa
    con normalidad y el documento queda indexado."""
    tenant_id = _crear_tenant(postgres_engine, "TenantCorrecto")
    document_id = _crear_documento(postgres_engine, tenant_id, "manual.txt")
    job = IngestJob(
        tenant_id=str(tenant_id),
        document_id=str(document_id),
        text="Contenido legítimo del propio tenant para indexar. " * 15,
        chunk_size=120,
    )

    process_job(
        job, ai_client=FakeAIClient(), session_factory=_session_factory(postgres_engine)
    )

    with postgres_engine.connect() as conn:
        documento = conn.execute(
            sa.text("SELECT estado FROM documents WHERE id = :id"),
            {"id": document_id},
        ).fetchone()
        chunks_activos = conn.execute(
            sa.text(
                "SELECT count(*) FROM chunks WHERE document_id = :id AND activo IS true"
            ),
            {"id": document_id},
        ).scalar_one()

    assert documento.estado == "indexado"
    assert chunks_activos > 0
