"""
Modelo `platform_admins` — admin de plataforma, plano separado del tenant
(ADR-015, SPEC-074).

`platform_admins` es, igual que `tenants`, una entidad de **plano-plataforma**:
NO lleva `tenant_id`, NO usa `TenantMixin`, NO está en `TENANT_SCOPED_TABLES`
(`app/db/rls.py`) y por lo tanto NO tiene política RLS por fila. Su `email` es
**único GLOBAL** (no por-tenant como `users.uq_users_tenant_email`), porque esta
tabla no tiene concepto de tenant.

Su autenticación/autorización es independiente del login de tenant (SPEC-013):
un guard `require_platform_admin` propio (SPEC-075, fuera de alcance aquí).
Esta SPEC (SPEC-074) solo deja el modelo y la migración; el servicio de
provisioning, el guard, el endpoint y el CLI que llenan `password_hash` son de
SPEC-075.
"""

import uuid

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class PlatformAdmin(Base, TimestampMixin, SoftDeleteMixin):
    """Admin de plataforma (ADR-015): puede dar de alta tenants nuevos.

    Reutiliza `TimestampMixin`/`SoftDeleteMixin` (ninguno de los dos asume
    `tenant_id`; eso solo lo introduce `TenantMixin`, que esta tabla NO usa).
    `activo` (de `SoftDeleteMixin`) es el borrado lógico C2: nunca DELETE
    físico de un admin de plataforma.
    """

    __tablename__ = "platform_admins"
    __table_args__ = (UniqueConstraint("email", name="uq_platform_admins_email"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
