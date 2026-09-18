"""Esquemas de `contacts` — SPEC-014.

Nota de compatibilidad con `src/lib/types.ts` (`Contact` de la SPA, SPEC-020):
el modelo de dominio de este slice (`app/models/contact.py`, SPEC-012) es
deliberadamente más simple que el `Contact` de la maqueta (sin `company`,
`tags`, `sector`, `lifetimeValue`, etc., que son campos de la fase RAG/KPI
fuera de este alcance). SPEC-020 hará el adaptador de forma explícita al
reemplazar los mocks; aquí se documenta la diferencia en vez de inventar
columnas no pedidas por SPEC-012/014.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ContactBase(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=255)
    telefono: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)

    @field_validator("nombre")
    @classmethod
    def _nombre_no_vacio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("nombre no puede estar vacío")
        return value


class ContactCreate(ContactBase):
    """Payload de alta de contacto."""


class ContactUpdate(BaseModel):
    """Payload de actualización parcial (PATCH) de contacto."""

    nombre: str | None = Field(default=None, min_length=1, max_length=255)
    telefono: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)

    @field_validator("nombre")
    @classmethod
    def _nombre_no_vacio(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("nombre no puede estar vacío")
        return value


class ContactOut(ContactBase):
    """Representación pública de un contacto (sin campos internos)."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    activo: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
