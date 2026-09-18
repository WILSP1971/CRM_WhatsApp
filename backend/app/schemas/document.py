"""Esquemas de `documents` — SPEC-014.

Alcance SPEC-014: alta de metadatos del documento y CRUD tenant-aware. La
ingesta/chunking/embeddings reales (estado `pendiente` -> `indexado`/`error`)
son de SPEC-016/017 (fuera de alcance aquí), igual que ya documenta
`app/models/document.py` (SPEC-012).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

TIPOS_VALIDOS = {"pdf", "md", "docx", "txt"}
ESTADOS_VALIDOS = {"pendiente", "indexado", "error"}


class DocumentCreate(BaseModel):
    nombre_archivo: str = Field(..., min_length=1, max_length=500)
    tipo: str = Field(..., max_length=20)

    @field_validator("tipo")
    @classmethod
    def _valida_tipo(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in TIPOS_VALIDOS:
            raise ValueError(f"tipo inválido: debe ser uno de {sorted(TIPOS_VALIDOS)}")
        return value

    @field_validator("nombre_archivo")
    @classmethod
    def _nombre_no_vacio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("nombre_archivo no puede estar vacío")
        return value


class DocumentOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    nombre_archivo: str
    tipo: str
    estado: str
    activo: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
