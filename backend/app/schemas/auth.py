"""Esquemas de autenticación — SPEC-013 (login/logout/me)."""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    """Credenciales de login. `tenant_slug` identifica el tenant del usuario:
    RF-01/RF de SPEC-013 exigen que el login valide credenciales DENTRO del
    tenant (un email puede repetirse entre tenants, ver constraint
    `uq_users_tenant_email` en `app/models/user.py`).

    Nota: se valida el formato de email con una expresión regular simple en
    vez de `pydantic[email]` para no añadir una dependencia (`email-validator`)
    fuera del alcance de SPEC-013/requirements.txt actuales.
    """

    tenant_slug: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1)

    @field_validator("email")
    @classmethod
    def _valida_formato_email(cls, value: str) -> str:
        if not _EMAIL_RE.match(value):
            raise ValueError("email con formato inválido")
        return value.strip().lower()


class TokenResponse(BaseModel):
    """Respuesta de login: JWT de acceso con `tenant_id` embebido."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    """Representación pública del usuario autenticado (sin `password_hash`)."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    nombre: str
    rol: str
    activo: bool

    model_config = {"from_attributes": True}
