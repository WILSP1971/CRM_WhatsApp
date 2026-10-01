"""
Servicio de autenticación del admin de plataforma — SPEC-075 (ADR-015).

Mecanismo elegido: JWT de plataforma (`create_platform_access_token`,
`app/security/jwt.py`), independiente del JWT de tenant (SPEC-013). Se
descarta HTTP Basic/Bearer de credencial estática porque:
  - el JWT reutiliza la infraestructura de verificación ya existente
    (`decode_*`, manejo de expiración) sin inventar un segundo esquema de
    cabecera;
  - permite expirar la sesión de un admin de plataforma igual que a un
    usuario de tenant (RNF de sesión segura), cosa que un Basic Auth con
    password en cada request no ofrece de forma natural;
  - mantiene el mismo patrón de "login -> token -> Bearer" que ya conocen
    los clientes de esta API (consistencia de integración).

Este servicio NUNCA toca `users`/`tenants` ni usa `set_tenant_session`:
`platform_admins` es una tabla plano-plataforma sin RLS (ADR-015 §1), y su
login no necesita descubrir ningún tenant.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.platform_admin import PlatformAdmin
from app.security.jwt import create_platform_access_token
from app.security.passwords import verify_password
from app.security.rate_limit import (
    LoginRateLimitExceeded,
    RateLimitBackendUnavailableError,
    login_rate_limiter,
)

# Clave sintética de "tenant_slug" para el rate-limiter compartido
# (`LoginRateLimiter`, SPEC-013): mantiene el contador de intentos fallidos
# del login de PLATAFORMA en un espacio de claves separado del de cualquier
# tenant real (ningún tenant puede tener este slug, está en `RESERVED_SLUGS`
# de `tenant_provisioning_service.py`).
_RATE_LIMIT_NAMESPACE = "__platform__"


class InvalidPlatformCredentialsError(Exception):
    """Credenciales inválidas (email/password) — mapeado a 401 genérico."""


class PlatformRateLimitedError(Exception):
    """Demasiados intentos fallidos de login de plataforma — mapeado a 429."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Rate limit de login de plataforma excedido")


class PlatformLoginServiceUnavailableError(Exception):
    """Backend de rate-limit (Redis) inaccesible en modo estricto — mapeado a 503."""


@dataclass(frozen=True)
class PlatformLoginResult:
    access_token: str
    expires_in_seconds: int
    platform_admin: PlatformAdmin


def authenticate_platform_admin(
    db: Session, *, email: str, password: str
) -> PlatformLoginResult:
    """Valida credenciales de un `platform_admin` (unique GLOBAL de email).

    Mismo criterio de "mensaje genérico" que `auth_service.authenticate`:
    email inexistente, password incorrecta o admin inactivo devuelven el
    MISMO error (no se filtra cuál fue la causa).
    """
    email_normalizado = email.strip().lower()

    admin = db.scalar(
        select(PlatformAdmin).where(
            PlatformAdmin.email == email_normalizado,
            PlatformAdmin.activo.is_(True),
        )
    )

    password_ok = bool(admin) and verify_password(password, admin.password_hash or "")

    if not password_ok:
        try:
            login_rate_limiter.check_and_increment(
                _RATE_LIMIT_NAMESPACE, email_normalizado
            )
        except LoginRateLimitExceeded as exc:
            raise PlatformRateLimitedError(exc.retry_after_seconds) from exc
        except RateLimitBackendUnavailableError as exc:
            raise PlatformLoginServiceUnavailableError(
                "Rate-limit de login de plataforma no disponible (Redis inaccesible)"
            ) from exc
        raise InvalidPlatformCredentialsError("Credenciales inválidas")

    login_rate_limiter.reset(_RATE_LIMIT_NAMESPACE, email_normalizado)

    token = create_platform_access_token(platform_admin_id=admin.id)
    from app.core.config import get_settings

    settings = get_settings()
    return PlatformLoginResult(
        access_token=token,
        expires_in_seconds=settings.jwt_access_token_expire_minutes * 60,
        platform_admin=admin,
    )
