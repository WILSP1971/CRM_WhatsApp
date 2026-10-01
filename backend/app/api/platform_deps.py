"""
Dependencias FastAPI de autenticación del admin de plataforma — SPEC-075
(ADR-015).

`require_platform_admin` es el guard que protege `POST /platform/tenants`
(y cualquier endpoint futuro de plano-plataforma). Es DELIBERADAMENTE
independiente de `app/api/deps.py` (`get_current_token`/`get_current_user`,
SPEC-013): valida un JWT de PLATAFORMA (`decode_platform_access_token`,
`type="platform_access"`) contra la tabla `platform_admins` (sin RLS,
ADR-015), nunca contra `users`/tenant.

Semántica de error exigida por SPEC-075 (RF-04/CE-92):
  - Sin credenciales (header ausente) -> 401.
  - Credenciales mal formadas/expiradas/firma inválida -> 401.
  - JWT de TENANT válido (`type="access"`, SPEC-013) presentado aquí -> 403
    (se distingue explícitamente de "no autenticado": el token SÍ es válido,
    pero es del plano equivocado — no debe confundirse con un simple 401).
  - JWT de plataforma válido mapeado a un `platform_admin` inactivo/borrado
    -> 401 (mismo criterio que `get_current_user`: el token pudo ser válido
    en su momento, pero el actor ya no tiene acceso).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.platform_admin import PlatformAdmin
from app.security.jwt import (
    InvalidTokenError,
    decode_access_token,
    decode_platform_access_token,
)

_bearer_scheme = HTTPBearer(auto_error=False)

_NOT_AUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="No autenticado",
    headers={"WWW-Authenticate": "Bearer"},
)

_WRONG_TOKEN_PLANE = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Este endpoint requiere credenciales de administrador de plataforma",
)


def _get_platform_db() -> Session:
    """Sesión de BD de plano-plataforma (sin `app.tenant_id`, `platform_admins`
    no lleva RLS por diseño — ADR-015). Se cierra explícitamente al terminar
    la request (no es un generador porque no necesita envolver en `db.begin()`:
    esta dependencia solo hace SELECT, nunca escribe)."""
    return SessionLocal()


def require_platform_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> PlatformAdmin:
    """Guard de plano-plataforma: exige un JWT de plataforma válido.

    Si el token presentado es un JWT de TENANT normal (`type="access"`,
    SPEC-013) en vez de uno de plataforma, se rechaza con 403 (no 401): el
    token es válido en su propio plano, pero no autoriza esta operación.
    """
    if credentials is None or not credentials.credentials:
        raise _NOT_AUTHENTICATED

    token = credentials.credentials

    try:
        payload = decode_platform_access_token(token)
    except InvalidTokenError:
        # Antes de responder 401 genérico, distingue el caso "es un JWT de
        # TENANT válido" (SPEC-013) para devolver 403 en su lugar (RF-04).
        try:
            decode_access_token(token)
        except InvalidTokenError:
            raise _NOT_AUTHENTICATED from None
        else:
            raise _WRONG_TOKEN_PLANE from None

    db = _get_platform_db()
    try:
        admin = db.scalar(
            select(PlatformAdmin).where(
                PlatformAdmin.id == payload.sub,
                PlatformAdmin.activo.is_(True),
            )
        )
    finally:
        db.close()

    if admin is None:
        raise _NOT_AUTHENTICATED
    return admin
