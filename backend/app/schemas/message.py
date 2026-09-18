"""Esquemas de `messages` — SPEC-014."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

REMITENTES_VALIDOS = {"contacto", "agente", "ia"}


class MessageCreate(BaseModel):
    """Payload de alta de mensaje dentro de una conversación del tenant."""

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


class MessageOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    remitente: str
    contenido: str
    sentimiento: str | None
    sentimiento_score: float | None
    estado_entrega: str
    activo: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
