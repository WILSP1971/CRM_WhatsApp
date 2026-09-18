"""Esquemas del pipeline RAG — SPEC-017 y del borrador human-in-the-loop —
SPEC-019.

`CitationOut` implementa el contrato `rag.citations` del Entregable #1:
cada cita expone `source` (documento origen), `excerpt` (fragmento citado) y
`similarityScore` (score de similitud coseno, 0..1).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.services.rag.chunking import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE
from app.services.rag.retrieval_service import DEFAULT_TOP_K, MAX_TOP_K

# Longitud máxima del excerpt devuelto por HTTP en una cita (MENOR, revisión
# BLACK PANTHER): evita payloads enormes cuando `chunk_size` se configura
# alto; el excerpt es solo para que el agente humano ubique la fuente citada,
# no para reproducir el chunk completo en la respuesta de la API.
MAX_CITATION_EXCERPT_LENGTH = 500


class IngestRequest(BaseModel):
    """Solicitud de ingesta: texto crudo ya extraído del archivo (la
    extracción PDF/DOCX/MD/TXT a texto plano es responsabilidad del
    llamador/almacenamiento de archivos, fuera de alcance de SPEC-017)."""

    text: str = Field(..., min_length=1)
    chunk_size: int = Field(default=DEFAULT_CHUNK_SIZE, gt=0, le=8000)
    chunk_overlap: int = Field(default=DEFAULT_CHUNK_OVERLAP, ge=0, le=4000)


class IngestQueuedOut(BaseModel):
    """Confirmación de encolado (RNF-06: ingesta asíncrona no bloqueante)."""

    document_id: uuid.UUID
    estado: str = Field(description="Estado del documento tras encolar (pendiente).")
    mensaje: str = "Ingesta encolada para procesamiento asíncrono."


class IngestResultOut(BaseModel):
    """Resultado de una ingesta ya procesada (síncrona o tras drenar la cola)."""

    document_id: uuid.UUID
    estado: str
    chunks_creados: int
    error: str | None = None


class RagDraftRequest(BaseModel):
    """Solicitud de borrador RAG a partir de una consulta/pregunta."""

    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=DEFAULT_TOP_K, gt=0, le=MAX_TOP_K)


class CitationOut(BaseModel):
    """Cita trazable — contrato `rag.citations` (Entregable #1).

    `excerpt` se trunca a `MAX_CITATION_EXCERPT_LENGTH` caracteres (MENOR,
    revisión BLACK PANTHER): el chunk completo persiste en `chunks.contenido`
    (BD) para trazabilidad; la API solo expone un fragmento acotado.
    """

    source: str
    excerpt: str
    similarityScore: float = Field(..., ge=0.0, le=1.0)
    chunk_id: uuid.UUID
    document_id: uuid.UUID

    @field_validator("excerpt")
    @classmethod
    def _truncar_excerpt(cls, value: str) -> str:
        if len(value) <= MAX_CITATION_EXCERPT_LENGTH:
            return value
        return value[:MAX_CITATION_EXCERPT_LENGTH].rstrip() + "…"


class RagDraftOut(BaseModel):
    """Borrador generado por el LLM local con ≥3 citas trazables.

    NO se envía automáticamente al contacto (human-in-the-loop es SPEC-019);
    este endpoint solo produce el borrador para revisión humana posterior.
    """

    content: str
    model: str
    citations: list[CitationOut] = Field(..., min_length=3)


# ---------------------------------------------------------------------------
# Borrador human-in-the-loop (SPEC-019)
# ---------------------------------------------------------------------------


class DraftCreateRequest(BaseModel):
    """Solicitud para proponer un borrador RAG asociado a una conversación."""

    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=DEFAULT_TOP_K, gt=0, le=MAX_TOP_K)


class DraftEditRequest(BaseModel):
    """Edición del texto final del borrador por el agente humano."""

    content: str = Field(..., min_length=1)


class DraftOut(BaseModel):
    """Estado vigente de un borrador RAG (SPEC-019).

    `content` es SIEMPRE el texto final (editado si el agente lo cambió,
    original si aún no); `content_original` se conserva para auditoría de lo
    que propuso la IA. `sent_message_id` es `None` hasta la aprobación
    explícita (RF central de SPEC-019: nada se envía antes de eso).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    query: str
    content: str
    content_original: str
    model: str
    citations: list[CitationOut] = Field(..., min_length=3)
    estado: str
    edited_by: str | None
    approved_by: str | None
    sent_message_id: uuid.UUID | None
    activo: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DraftApproveOut(BaseModel):
    """Resultado de aprobar y enviar un borrador: el borrador final + el
    mensaje saliente recién creado (única vía de envío, SPEC-019)."""

    draft: DraftOut
    sent_message_id: uuid.UUID
