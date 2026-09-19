"""Modelo `messages` — mensajes persistidos de una conversación (SPEC-012,
extendido por SPEC-015 con estado de entrega del WebChat, por SPEC-018 con
el sentimiento clasificado por el LLM local y por SPEC-025 con el `wamid`
de WhatsApp para idempotencia)."""

import uuid

from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin

# Etiquetas de sentimiento válidas (SPEC-018 RF-07).
SENTIMIENTOS_VALIDOS = {"positivo", "neutral", "negativo"}

# Estados de entrega (SPEC-015, criterio de aceptación "estados de entrega
# enviado/entregado/leído"). Progresión monotónica: enviado -> entregado ->
# leido (nunca retrocede). SPEC-025 reutiliza el mismo campo/contrato como
# estado de transporte del canal WhatsApp (RF-02): no se añade una columna
# de estado paralela, ya que el mismo vocabulario aplica ("enviado" tras el
# ACK de la API de WhatsApp, "entregado"/"leido" por los statuses del
# webhook, conciliados en SPEC-030). Se documenta aquí para que quede
# explícito en el contrato del modelo (no hay regresión, RNF-07).
ESTADOS_ENTREGA_VALIDOS = {"enviado", "entregado", "leido"}

# `failed` (SPEC-029, RF-04): estado TERMINAL propio del transporte de
# ENVÍO por Graph API (`app/workers/wa_send_worker.py`) — ni la Graph API ni
# los reintentos idempotentes lograron entregar el mensaje (429/5xx
# agotados, ventana de 24h bloqueada sin plantilla HSM, o configuración de
# envío incompleta). Deliberadamente SEPARADO de `ESTADOS_ENTREGA_VALIDOS`
# (que modela la progresión enviado -> entregado -> leido de los callbacks
# de estado, SPEC-015/030): `update_delivery_status` (progresión monotónica)
# NUNCA debe aceptar `failed` como argumento, así que no se añade a ese set;
# `wa_send_worker` asigna `message.estado_entrega = "failed"` directamente,
# fuera de esa función, exactamente una vez por mensaje que no logró
# transportarse.
ESTADO_ENTREGA_FAILED = "failed"


class Message(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("wamid", name="uq_messages_wamid"),)

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
    )  # "enviado" | "entregado" | "leido" (SPEC-015; reutilizado por SPEC-025
    # como estado de transporte de WhatsApp, ver comentario de
    # ESTADOS_ENTREGA_VALIDOS arriba)
    wamid: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # id de mensaje de WhatsApp (Meta), UNIQUE cuando no es None — base de
    # idempotencia (ADR-007). None para mensajes de otros canales (webchat).
