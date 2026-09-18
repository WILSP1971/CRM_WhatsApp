"""Modelo `messages` — mensajes persistidos de una conversación (SPEC-012,
extendido por SPEC-015 con estado de entrega del WebChat y por SPEC-018 con
el sentimiento clasificado por el LLM local)."""

import uuid

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin

# Etiquetas de sentimiento válidas (SPEC-018 RF-07).
SENTIMIENTOS_VALIDOS = {"positivo", "neutral", "negativo"}

# Estados de entrega del canal WebChat (SPEC-015, RF/criterio de aceptación
# "estados de entrega enviado/entregado/leído"). Progresión monotónica:
# enviado -> entregado -> leido (nunca retrocede).
ESTADOS_ENTREGA_VALIDOS = {"enviado", "entregado", "leido"}


class Message(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    remitente: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # "contacto" | "agente" | "ia"
    contenido: Mapped[str] = mapped_column(Text, nullable=False)
    sentimiento: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # "positivo" | "neutral" | "negativo" (SPEC-018), None = sin clasificar
    sentimiento_score: Mapped[float | None] = mapped_column(
        Numeric(precision=4, scale=3), nullable=True
    )  # score [0,1] del LLM local (SPEC-018), None = sin clasificar
    estado_entrega: Mapped[str] = mapped_column(
        String(20), nullable=False, default="enviado"
    )  # "enviado" | "entregado" | "leido" (SPEC-015)
