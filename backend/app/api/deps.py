"""
Dependencias FastAPI de autenticación y tenant de sesión — SPEC-013.

`get_current_user` es el punto único de entrada que:
  1. Extrae y valida el JWT del header `Authorization: Bearer <token>`.
  2. Ante token ausente/inválido/expirado -> 401 (sin filtrar detalles).
  3. Fija `SET LOCAL app.tenant_id = <tenant_id del token>` en la sesión de
     BD (`app/db/session.py::set_tenant_session`, SPEC-012) ANTES de que el
     endpoint toque cualquier tabla -> activa RLS (ADR-004) para el resto de
     la petición. Así, aunque un endpoint tenga un bug y olvide filtrar por
     tenant, el motor de PostgreSQL igualmente aísla los datos.
  4. Carga el usuario autenticado (dentro de su propio tenant) y lo expone
     al endpoint.

Un usuario del tenant A nunca puede "cruzar" al tenant B con esta dependencia
porque el `tenant_id` viene firmado dentro del propio JWT (no es un parámetro
que el cliente pueda manipular en la petición).
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, set_tenant_session
from app.models.user import User
from app.security.jwt import InvalidTokenError, TokenPayload, decode_access_token

# `auto_error=False` para poder devolver un 401 propio y homogéneo (sin
# filtrar si fue "no header" vs "header mal formado" vs "token expirado").
_bearer_scheme = HTTPBearer(auto_error=False)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="No autenticado",
    headers={"WWW-Authenticate": "Bearer"},
)


def _decode_or_401(credentials: HTTPAuthorizationCredentials | None) -> TokenPayload:
    if credentials is None or not credentials.credentials:
        raise _CREDENTIALS_ERROR
    try:
        return decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise _CREDENTIALS_ERROR from exc


def get_current_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> TokenPayload:
    """Dependencia base: valida el JWT y devuelve su payload (401 si inválido)."""
    return _decode_or_401(credentials)


def get_tenant_db(
    token: TokenPayload = Depends(get_current_token),
) -> Generator[Session, None, None]:
    """Sesión de BD con el `tenant_id` del token ya fijado (activa RLS)."""
    db = SessionLocal()
    try:
        with db.begin():
            set_tenant_session(db, token.tenant_id)
            yield db
    finally:
        db.close()


def get_current_user(
    token: TokenPayload = Depends(get_current_token),
    db: Session = Depends(get_tenant_db),
) -> User:
    """Usuario autenticado, resuelto DENTRO del tenant fijado por el token.

    Al filtrar también por `User.tenant_id == token.tenant_id` (además de la
    RLS activa en la sesión) se obtiene defensa en profundidad: incluso si
    RLS no estuviera activa, la query ya está acotada al tenant del token.
    """
    user = db.scalar(
        select(User).where(
            User.id == token.sub,
            User.tenant_id == token.tenant_id,
            User.activo.is_(True),
        )
    )
    if user is None:
        raise _CREDENTIALS_ERROR
    return user
