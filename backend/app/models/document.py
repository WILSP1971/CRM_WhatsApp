"""
Modelo `documents` — documentos fuente para RAG (SPEC-012).

Alcance SPEC-012: solo el esquema/tabla y su aislamiento por RLS. La ingesta,
el chunking real y la generación de embeddings son de SPEC-016/017 (fuera de
alcance aquí); `estado` se deja preparado como lo pide SPEC-012 §Alcance.
"""

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin


class Document(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    nombre_archivo: Mapped[str] = mapped_column(String(500), nullable=False)
    tipo: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # pdf | md | docx | txt
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    # pendiente | indexado | error (SPEC-016/017 gestionan la transición real)
