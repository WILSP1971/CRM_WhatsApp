"""
Router `platform` — SPEC-075 (ADR-015, 🔴 SENSIBLE).

Endpoints:
  - POST /platform/auth/login : credenciales de `platform_admin` -> JWT de
    plataforma (independiente del login de tenant, SPEC-013).
  - POST /platform/tenants    : alta atómica de tenant + primer admin,
    protegida por `require_platform_admin`.

Superficie mínima (ADR-015 §Alternativas, Q1-B): alta administrativa
interna, SIN autoregistro público. No hay endpoint de alta de
`platform_admins` (eso es bootstrap/CLI, fuera de HTTP por diseño).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.platform_deps import require_platform_admin
from app.db.session import get_db
from app.models.platform_admin import PlatformAdmin
from app.schemas.platform import (
    PlatformLoginRequest,
    PlatformTokenResponse,
    TenantProvisionRequest,
    TenantProvisionResponse,
)
from app.services.platform_auth_service import (
    InvalidPlatformCredentialsError,
    PlatformLoginServiceUnavailableError,
    PlatformRateLimitedError,
    authenticate_platform_admin,
)
from app.services.tenant_provisioning_service import (
    EmailCollisionError,
    InvalidFieldError,
    InvalidPasswordError,
    InvalidSlugError,
    SlugCollisionError,
    provision_tenant,
)

router = APIRouter(prefix="/platform", tags=["Platform"])


@router.post("/auth/login", response_model=PlatformTokenResponse)
def platform_login(
    payload: PlatformLoginRequest, db=Depends(get_db)
) -> PlatformTokenResponse:
    """Login del admin de plataforma. Credenciales inválidas -> 401 genérico.

    Usa `get_db` (sesión de plataforma, sin `app.tenant_id`): `platform_admins`
    no lleva RLS (ADR-015), así que no hay ningún tenant que fijar aquí.
    """
    try:
        result = authenticate_platform_admin(
            db, email=payload.email, password=payload.password
        )
    except PlatformRateLimitedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos. Intente más tarde.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except InvalidPlatformCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        ) from exc
    except PlatformLoginServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de autenticación temporalmente no disponible.",
        ) from exc

    return PlatformTokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in_seconds,
    )


@router.post(
    "/tenants",
    response_model=TenantProvisionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"description": "No autenticado"},
        403: {"description": "Token de tenant presentado en un endpoint de plataforma"},
        409: {"description": "Slug o email ya en uso"},
        422: {"description": "Slug/password/campos con formato inválido"},
    },
)
def create_tenant(
    payload: TenantProvisionRequest,
    _platform_admin: PlatformAdmin = Depends(require_platform_admin),
    db=Depends(get_db),
) -> TenantProvisionResponse:
    """Alta atómica de tenant + primer admin (RF-01..RF-06 SPEC-075).

    `db` es la sesión de plataforma (`get_db`, sin tenant fijado):
    `provision_tenant` fija `app.tenant_id` DENTRO de su propia transacción
    una vez que conoce el tenant recién creado (patrón `auth_service`).
    """
    try:
        resultado = provision_tenant(
            db,
            nombre=payload.nombre,
            slug=payload.slug,
            admin_email=payload.admin_email,
            admin_password=payload.admin_password,
            admin_nombre=payload.admin_nombre,
        )
    except (InvalidSlugError, InvalidPasswordError, InvalidFieldError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except (SlugCollisionError, EmailCollisionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    return TenantProvisionResponse(tenant_id=resultado.tenant_id, slug=resultado.slug)
