"""Esquemas de `tenants` — SPEC-014 (solo lectura en este alcance)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class TenantOut(BaseModel):
    """Representación pública de un tenant (sin campos internos)."""

    id: uuid.UUID
    nombre: str
    slug: str
    activo: bool

    model_config = {"from_attributes": True}
