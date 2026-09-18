"""Esquemas del canal WebChat por WebSocket — SPEC-015.

Protocolo de mensajes JSON sobre el WebSocket (bidireccional):

Entrantes (cliente -> servidor):
  - {"type": "message", "remitente": "contacto"|"agente", "contenido": "..."}
  - {"type": "read", "message_id": "<uuid>"}  (marca un mensaje como leído)

Salientes (servidor -> cliente), vía fan-out Redis pub/sub:
  - {"type": "message", "message": <MessageOut>}
  - {"type": "delivery_status", "message_id": "<uuid>", "estado_entrega": "..."}
  - {"type": "error", "detail": "..."}
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.message import REMITENTES_VALIDOS, MessageOut


class WsIncomingMessage(BaseModel):
    """Mensaje entrante del WebSocket (`type: "message"`)."""

    type: str = Field(default="message")
    remitente: str = Field(..., max_length=20)
    contenido: str = Field(..., min_length=1)

    @field_validator("remitente")
    @classmethod
    def _valida_remitente(cls, value: str) -> str:
        if value not in REMITENTES_VALIDOS:
            raise ValueError(
                f"remitente inválido: debe ser uno de {sorted(REMITENTES_VALIDOS)}"
            )
        return value

    @field_validator("contenido")
    @classmethod
    def _contenido_no_vacio(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("contenido no puede estar vacío")
        return value


class WsReadReceipt(BaseModel):
    """Evento de lectura entrante (`type: "read"`)."""

    type: str = Field(default="read")
    message_id: uuid.UUID


class WsOutgoingMessage(BaseModel):
    """Envoltorio saliente para difusión de un mensaje persistido."""

    type: str = "message"
    message: MessageOut


class WsDeliveryStatus(BaseModel):
    """Envoltorio saliente para un cambio de estado de entrega."""

    type: str = "delivery_status"
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    estado_entrega: str


class WsErrorEvent(BaseModel):
    """Envoltorio saliente de error (validación, payload malformado, etc.)."""

    type: str = "error"
    detail: str
