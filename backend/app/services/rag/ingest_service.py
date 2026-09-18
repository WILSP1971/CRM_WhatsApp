"""Servicio de ingesta RAG: documento -> chunking -> embeddings -> pgvector.

SPEC-017 RF-06. Orquesta:
  1. Lee el `Document` (ya creado por SPEC-014, `app/api/documents.py`) y su
     texto crudo (provisto por el llamador; la extracción de PDF/DOCX/MD/TXT
     a texto plano es responsabilidad del llamador/worker, fuera del alcance
     de este servicio de dominio).
  2. Chunking configurable (`app.services.rag.chunking`).
  3. Embeddings locales vía `AIClient.embed` (SPEC-016, Ollama interno).
  4. Persiste `Chunk` + `Embedding` (esquema pgvector de SPEC-012), bajo el
     mismo `tenant_id` del documento (RLS/ADR-004).
  5. Transiciona `Document.estado`: pendiente -> indexado | error.

Idempotencia (R-28, reintentos): si el documento ya tiene chunks/embeddings
activos de un intento previo, se marcan inactivos (borrado lógico, C2) antes
de volver a indexar, para no duplicar vectores en un reintento.

Modo degradado (R-21): si `AIClient` está no disponible (Ollama caído/modelo
no cargado), el documento queda en estado `error` (no lanza una excepción sin
control hacia el llamador HTTP) y admite reintento idempotente posterior.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.embedding import Embedding
from app.services.ai_service import AIClient, AIServiceError
from app.services.rag.chunking import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    split_into_chunks,
)

ESTADO_PENDIENTE = "pendiente"
ESTADO_INDEXADO = "indexado"
ESTADO_ERROR = "error"


class DocumentNotFoundError(LookupError):
    """El documento no existe o no está activo dentro del tenant de sesión."""


@dataclass(frozen=True)
class IngestResult:
    document_id: uuid.UUID
    estado: str
    chunks_creados: int
    error: str | None = None


def _get_document_activo(db: Session, document_id: uuid.UUID) -> Document:
    document = db.scalar(
        select(Document).where(Document.id == document_id, Document.activo.is_(True))
    )
    if document is None:
        raise DocumentNotFoundError(f"Documento {document_id} no encontrado o inactivo")
    return document


def _invalidar_chunks_previos(db: Session, document: Document) -> None:
    """Borrado lógico (C2) de chunks/embeddings de un intento previo, para que
    un reintento idempotente no acumule vectores duplicados."""
    chunks_previos = db.scalars(
        select(Chunk).where(
            Chunk.document_id == document.id,
            Chunk.tenant_id == document.tenant_id,
            Chunk.activo.is_(True),
        )
    ).all()
    if not chunks_previos:
        return

    chunk_ids = [chunk.id for chunk in chunks_previos]
    embeddings_previos = db.scalars(
        select(Embedding).where(
            Embedding.chunk_id.in_(chunk_ids),
            Embedding.tenant_id == document.tenant_id,
            Embedding.activo.is_(True),
        )
    ).all()
    for embedding in embeddings_previos:
        embedding.activo = False
    for chunk in chunks_previos:
        chunk.activo = False
    db.flush()


def ingest_document(
    db: Session,
    ai_client: AIClient,
    *,
    document_id: uuid.UUID,
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    created_by: str | None = None,
) -> IngestResult:
    """Ejecuta la ingesta completa de un documento (síncrona).

    Se ejecuta dentro de la sesión de BD con `tenant_id` ya fijado (RLS,
    `get_tenant_db`/`tenant_scoped_session`), tanto si la invoca el endpoint
    HTTP directamente (documentos pequeños) como el worker que consume la
    cola Redis (`app/workers/rag_ingest_worker.py`, documentos grandes).
    """
    document = _get_document_activo(db, document_id)

    # Reintento idempotente (R-28): limpia vectores de un intento anterior
    # antes de re-indexar, sin importar si el intento anterior fue éxito o error.
    _invalidar_chunks_previos(db, document)

    text_chunks = split_into_chunks(
        text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    if not text_chunks:
        document.estado = ESTADO_ERROR
        db.flush()
        return IngestResult(
            document_id=document.id,
            estado=ESTADO_ERROR,
            chunks_creados=0,
            error="El documento no contiene texto indexable",
        )

    chunks_insertados_este_intento: list[Chunk] = []
    try:
        creados = 0
        for text_chunk in text_chunks:
            chunk = Chunk(
                tenant_id=document.tenant_id,
                document_id=document.id,
                orden=text_chunk.orden,
                contenido=text_chunk.contenido,
                created_by=created_by,
            )
            db.add(chunk)
            db.flush()  # necesita chunk.id para la FK de Embedding
            chunks_insertados_este_intento.append(chunk)

            embedding_result = ai_client.embed(text_chunk.contenido)
            embedding = Embedding(
                tenant_id=document.tenant_id,
                chunk_id=chunk.id,
                vector=embedding_result.vector,
                created_by=created_by,
            )
            db.add(embedding)
            creados += 1

        db.flush()
    except AIServiceError as exc:
        # Modo degradado (R-21): no se propaga una excepción sin control; el
        # documento queda en `error` para reintento posterior.
        #
        # MENOR (revisión BLACK PANTHER): los chunks ya insertados EN ESTE
        # intento (p.ej. si `ai_client.embed` falla a mitad de documento) se
        # invalidan aquí mismo (borrado lógico, C2) para que `retrieval_service`
        # NUNCA los vea como `activo=True` mientras el documento está en
        # `error` — antes quedaban visibles hasta el siguiente reintento
        # exitoso, una ventana de vectores parciales/incompletos consultables.
        for chunk_parcial in chunks_insertados_este_intento:
            for embedding_parcial in db.scalars(
                select(Embedding).where(
                    Embedding.chunk_id == chunk_parcial.id,
                    Embedding.activo.is_(True),
                )
            ).all():
                embedding_parcial.activo = False
            chunk_parcial.activo = False
        document.estado = ESTADO_ERROR
        db.flush()
        return IngestResult(
            document_id=document.id,
            estado=ESTADO_ERROR,
            chunks_creados=0,
            error=str(exc),
        )

    document.estado = ESTADO_INDEXADO
    db.flush()
    return IngestResult(
        document_id=document.id, estado=ESTADO_INDEXADO, chunks_creados=creados
    )
