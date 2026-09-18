"""Router `tenants` — SPEC-014 (lectura del tenant propio del usuario autenticado).

Alcance SPEC-014: "lectura de `tenants`". No se expone un listado global de
tenants (sería una fuga cross-tenant/administrativa fuera de alcance); un
usuario autenticado solo puede leer el tenant al que pertenece su propio JWT.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_db
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.tenant import TenantOut

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.get(
    "/me",
    response_model=TenantOut,
    responses={401: {"description": "No autenticado"}},
)
def get_my_tenant(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> TenantOut:
    """Tenant del usuario autenticado (único tenant accesible desde este JWT)."""
    tenant = db.scalar(
        select(Tenant).where(
            Tenant.id == current_user.tenant_id, Tenant.activo.is_(True)
        )
    )
    if tenant is None:
        # No debería ocurrir (FK + RLS ya lo garantizan), pero se responde
        # 404 tipado en vez de dejar pasar un 500 si algún día se relaja RLS.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant no encontrado"
        )
    return TenantOut.model_validate(tenant)
