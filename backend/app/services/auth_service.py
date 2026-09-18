"""
Servicio de autenticación — SPEC-013.

Reglas de negocio centrales:
  - El login se resuelve SIEMPRE dentro de un tenant (`tenant_slug`): un
    usuario de un tenant nunca puede autenticarse "cruzando" a otro, porque
    la búsqueda del usuario ya está acotada por `Tenant.slug` + `User.email`
    (constraint `uq_users_tenant_email`), antes incluso de tocar RLS.
  - Solo usuarios `activo=True` (borrado lógico, C2) pueden autenticarse.
  - Las credenciales inválidas (tenant inexistente, email inexistente,
    password incorrecta, usuario inactivo) devuelven el MISMO error genérico
    para no filtrar información (RF de SPEC-013: "login inválido devuelve
    401 sin filtrar información").
  - Esta consulta de login se hace con el engine "de plataforma" (sin tenant
    de sesión fijado aún, `app/db/session.py::get_db`), igual que el seed de
    SPEC-012: hace falta leer `tenants`/`users` para *descubrir* el tenant_id
    antes de poder fijarlo. Una vez emitido el JWT, TODO el resto de la
    petición (incluida `GET /auth/me`) opera con `set_tenant_session` fijado
    (ver `app/api/deps.py`), que es lo que activa RLS (ADR-004).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.user import User
from app.security.jwt import create_access_token
from app.security.passwords import verify_password
from app.security.rate_limit import (
    LoginRateLimitExceeded,
    RateLimitBackendUnavailableError,
    login_rate_limiter,
)


class InvalidCredentialsError(Exception):
    """Credenciales inválidas (tenant/email/password) — mapeado a 401 genérico."""


class RateLimitedError(Exception):
    """Demasiados intentos fallidos de login — mapeado a 429."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Rate limit de login excedido")


class LoginServiceUnavailableError(Exception):
    """Backend de rate-limit (Redis) inaccesible en modo estricto — mapeado a 503."""


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    expires_in_seconds: int
    user: User


def authenticate(
    db: Session, *, tenant_slug: str, email: str, password: str
) -> LoginResult:
    """Valida credenciales DENTRO del tenant identificado por `tenant_slug`.

    Lanza `RateLimitedError` si se superó el máximo de intentos fallidos, o
    `InvalidCredentialsError` ante cualquier combinación inválida (mensaje
    genérico, sin distinguir "tenant no existe" de "password incorrecta").
    """
    email_normalizado = email.strip().lower()

    tenant = db.scalar(
        select(Tenant).where(Tenant.slug == tenant_slug, Tenant.activo.is_(True))
    )

    user: User | None = None
    if tenant is not None:
        user = db.scalar(
            select(User).where(
                User.tenant_id == tenant.id,
                User.email == email_normalizado,
                User.activo.is_(True),
            )
        )

    password_ok = bool(user) and verify_password(password, user.password_hash or "")

    if not password_ok:
        try:
            login_rate_limiter.check_and_increment(tenant_slug, email_normalizado)
        except LoginRateLimitExceeded as exc:
            raise RateLimitedError(exc.retry_after_seconds) from exc
        except RateLimitBackendUnavailableError as exc:
            raise LoginServiceUnavailableError(
                "Rate-limit de login no disponible (Redis inaccesible)"
            ) from exc
        raise InvalidCredentialsError("Credenciales inválidas")

    # Login exitoso: limpia el contador de intentos fallidos de esta clave.
    login_rate_limiter.reset(tenant_slug, email_normalizado)

    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id, rol=user.rol)
    from app.core.config import get_settings

    settings = get_settings()
    return LoginResult(
        access_token=token,
        expires_in_seconds=settings.jwt_access_token_expire_minutes * 60,
        user=user,
    )
