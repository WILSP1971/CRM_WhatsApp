"""
Router de autenticación — SPEC-013.

Endpoints:
  - POST /auth/login  : credenciales -> JWT con tenant_id embebido.
  - POST /auth/logout : invalida la sesión del lado cliente (ver nota abajo).
  - GET  /auth/me      : usuario autenticado (requiere JWT válido; RLS activa).

Nota sobre logout (JWT stateless, sin alcance de blacklist en SPEC-013):
SPEC-013 no incluye Redis como blacklist de tokens revocados (eso sería
alcance adicional no pedido). `POST /auth/logout` es la respuesta semántica
estándar (200 + instrucción de descartar el token) para que el cliente borre
su almacenamiento local; el token igualmente expira por `exp` (RNF de sesión
segura). Si el Lead requiere revocación server-side inmediata, es una SPEC
nueva (lista de revocación en Redis).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user, get_tenant_db
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserOut
from app.services.auth_service import (
    InvalidCredentialsError,
    LoginServiceUnavailableError,
    RateLimitedError,
    authenticate,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db=Depends(get_db)) -> TokenResponse:
    """Login dentro de un tenant. Credenciales inválidas -> 401 genérico.

    Usa la sesión "de plataforma" (`get_db`, sin tenant de sesión fijado)
    porque el propósito de este endpoint es precisamente *descubrir* el
    tenant a partir de `tenant_slug` antes de que exista un JWT que fijar.
    """
    try:
        result = authenticate(
            db,
            tenant_slug=payload.tenant_slug,
            email=payload.email,
            password=payload.password,
        )
    except RateLimitedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos. Intente más tarde.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        ) from exc
    except LoginServiceUnavailableError as exc:
        # Rate-limit estricto (LOGIN_RATE_LIMIT_STRICT_REDIS) sin Redis
        # disponible: se rechaza explícitamente en vez de degradar de forma
        # insegura (BLACK WIDOW, SPEC-013 MEDIO-2).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de autenticación temporalmente no disponible.",
        ) from exc

    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in_seconds,
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(current_user: User = Depends(get_current_user)) -> dict:
    """Requiere JWT válido; instruye al cliente a descartar el token.

    (JWT stateless: no hay blacklist server-side en el alcance de SPEC-013;
    ver nota de módulo.)
    """
    return {"detail": "Sesión finalizada. Descarte el token en el cliente."}


@router.get("/me", response_model=UserOut)
def me(
    current_user: User = Depends(get_current_user),
    db=Depends(get_tenant_db),
) -> UserOut:
    """Usuario autenticado. `db` ya tiene fijado `app.tenant_id` (RLS activa)."""
    return UserOut.model_validate(current_user)
