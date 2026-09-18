"""Modelo `conversations` — hilos de conversación por canal (SPEC-012)."""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin


class Conversation(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    canal: Mapped[str] = mapped_column(String(50), nullable=False, default="webchat")
    estado: Mapped[str] = mapped_column(String(50), nullable=False, default="abierta")
