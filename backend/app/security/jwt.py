"""
Emisión y validación de JWT — SPEC-013.

El token porta siempre:
  - `sub`: id del usuario (string, UUID).
  - `tenant_id`: id del tenant del usuario (string, UUID) — es la pieza que
    permite al middleware/dependencia de FastAPI fijar `SET LOCAL
    app.tenant_id` (ver `app/db/session.py::set_tenant_session`, SPEC-012)
    para que las políticas RLS (ADR-004) aíslen los datos de cada request.
  - `rol`: rol del usuario dentro del tenant (control de acceso, RF de SPEC-013).
  - `exp`/`iat`: expiración y emisión (RNF de sesión segura).

CHECKPOINT C3: la clave de firma (`JWT_SECRET_KEY`) se lee SOLO de variables
de entorno vía `app.core.config.get_settings()`; nunca hardcodeada aquí.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()

TOKEN_TYPE_ACCESS = "access"


class InvalidTokenError(Exception):
    """Token ausente, mal formado, con firma inválida o expirado."""


@dataclass(frozen=True)
class TokenPayload:
    """Datos extraídos y validados de un JWT de acceso."""

    sub: str  # user id
    tenant_id: str
    rol: str
    exp: datetime


def create_access_token(
    *,
    user_id: uuid.UUID | str,
    tenant_id: uuid.UUID | str,
    rol: str,
    expires_minutes: int | None = None,
) -> str:
    """Emite un JWT de acceso firmado, con `tenant_id` embebido (ADR-004)."""
    now = datetime.now(timezone.utc)
    expire_minutes = (
        expires_minutes
        if expires_minutes is not None
        else settings.jwt_access_token_expire_minutes
    )
    expire = now + timedelta(minutes=expire_minutes)

    to_encode = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "rol": rol,
        "type": TOKEN_TYPE_ACCESS,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(
        to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> TokenPayload:
    """Valida firma y expiración; devuelve el payload tipado.

    Lanza `InvalidTokenError` ante cualquier problema (firma inválida,
    expirado, claims faltantes, tipo de token incorrecto) — la dependencia
    de FastAPI la traduce a 401 sin filtrar detalles internos.
    """
    if not token:
        raise InvalidTokenError("Token ausente")

    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise InvalidTokenError("Token inválido o expirado") from exc

    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise InvalidTokenError("Tipo de token inesperado")

    sub = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    rol = payload.get("rol")
    exp = payload.get("exp")
    if not sub or not tenant_id or not rol or exp is None:
        raise InvalidTokenError("Claims incompletos en el token")

    return TokenPayload(
        sub=sub,
        tenant_id=tenant_id,
        rol=rol,
        exp=datetime.fromtimestamp(exp, tz=timezone.utc),
    )
