"""Esquemas de `conversations` — SPEC-014."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Valores válidos de dominio (alineados con `ConversationStatus`/`Channel` de
# `src/lib/types.ts`, con `webchat` como canal por defecto del slice #2,
# PLAN-002 §2 IN.3). No se usa `Enum` de Python para no acoplar la validación
# de negocio a un tipo rígido antes de que SPEC-015 defina el flujo real del
# canal; se valida por pertenencia a un conjunto en el propio esquema.
CANALES_VALIDOS = {"whatsapp", "instagram", "messenger", "webchat"}
ESTADOS_VALIDOS = {"abierta", "pendiente", "escalada", "cerrada"}


class ConversationCreate(BaseModel):
    """Payload de alta de conversación (dentro del tenant autenticado)."""

    contact_id: uuid.UUID
    canal: str = Field(default="webchat", max_length=50)
    estado: str = Field(default="abierta", max_length=50)

    @field_validator("canal")
    @classmethod
    def _valida_canal(cls, value: str) -> str:
        if value not in CANALES_VALIDOS:
            raise ValueError(
                f"canal inválido: debe ser uno de {sorted(CANALES_VALIDOS)}"
            )
        return value

    @field_validator("estado")
    @classmethod
    def _valida_estado(cls, value: str) -> str:
        if value not in ESTADOS_VALIDOS:
            raise ValueError(
                f"estado inválido: debe ser uno de {sorted(ESTADOS_VALIDOS)}"
            )
        return value


class ConversationUpdate(BaseModel):
    """Payload de actualización parcial (PATCH) de conversación."""

    estado: str | None = Field(default=None, max_length=50)

    @field_validator("estado")
    @classmethod
    def _valida_estado(cls, value: str | None) -> str | None:
        if value is not None and value not in ESTADOS_VALIDOS:
            raise ValueError(
                f"estado inválido: debe ser uno de {sorted(ESTADOS_VALIDOS)}"
            )
        return value


class ConversationOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID
    canal: str
    estado: str
    activo: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
