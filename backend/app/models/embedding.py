"""
Modelo `embeddings` — vectores pgvector asociados a un `chunk` (SPEC-012).

Dimensión 768 (nomic-embed-text, ver `.env.example` OLLAMA_EMBED_MODEL). La
generación real de los vectores es de SPEC-016/017; aquí solo se deja la
columna vectorial y el índice preparados (criterio de aceptación SPEC-012).
"""

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin

EMBEDDING_DIM = 768  # nomic-embed-text


class Embedding(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    vector: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
