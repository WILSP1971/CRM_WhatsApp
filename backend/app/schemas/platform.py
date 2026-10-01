"""Esquemas del plano-plataforma — SPEC-075 (alta de tenants, ADR-015)."""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PlatformLoginRequest(BaseModel):
    """Credenciales de login del admin de plataforma (email unique GLOBAL,
    SIN `tenant_slug` — a diferencia de `LoginRequest` de SPEC-013, este
    plano no tiene concepto de tenant)."""

    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1)

    @field_validator("email")
    @classmethod
    def _valida_formato_email(cls, value: str) -> str:
        if not _EMAIL_RE.match(value):
            raise ValueError("email con formato inválido")
        return value.strip().lower()


class PlatformTokenResponse(BaseModel):
    """Respuesta de login de plataforma: JWT de plataforma (sin `tenant_id`)."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TenantProvisionRequest(BaseModel):
    """Body de `POST /platform/tenants` (RF-03 SPEC-075).

    Validación de formato aquí es la de "campos bien formados" (422 si
    falla la validación de Pydantic); la validación de NEGOCIO (slug
    reservado, colisión de slug/email) la hace
    `tenant_provisioning_service.provision_tenant` y el router la traduce a
    409/422 explícitos (nunca 500).
    """

    nombre: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100)
    admin_email: str = Field(..., min_length=3, max_length=255)
    admin_password: str = Field(..., min_length=8, max_length=255)
    admin_nombre: str = Field(..., min_length=1, max_length=255)

    @field_validator("admin_email")
    @classmethod
    def _valida_formato_admin_email(cls, value: str) -> str:
        if not _EMAIL_RE.match(value):
            raise ValueError("admin_email con formato inválido")
        return value.strip().lower()


class TenantProvisionResponse(BaseModel):
    """Respuesta 201 de `POST /platform/tenants` (RF-06: NUNCA password/hash)."""

    tenant_id: uuid.UUID
    slug: str
