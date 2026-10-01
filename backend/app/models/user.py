"""
Modelo `users` — usuarios/agentes de un tenant (SPEC-012).

Alcance SPEC-012: solo el esquema, RLS y borrado lógico. Hashing de contraseñas,
roles finos y emisión de JWT son de SPEC-013 (fuera de alcance aquí); se deja la
columna `password_hash` preparada para que SPEC-013 la use.

Semántica de `rol` (ADR-015/SPEC-074): `rol` sigue siendo texto libre (String(50),
sin enum/validación en esquema ni en `app/schemas/auth.py`, para no romper
usuarios existentes con roles ad-hoc). El default para usuarios creados por los
flujos ya existentes sigue siendo `"agente"`. A partir de SPEC-075, el PRIMER
usuario de un tenant recién aprovisionado (provisioning atómico tenant+admin,
ADR-015 punto 5) nace con `rol="admin"`: es un valor de texto reconocido por
convención de negocio (no por constraint de BD) que denota al administrador
inicial de esa sede/tenant, quien en fases futuras (OUT de SPEC-074/075) podrá
gestionar más usuarios/roles finos del propio tenant. No confundir con
`PlatformAdmin` (`app/models/platform_admin.py`): ese es un actor de
plano-plataforma, sin `tenant_id`, que puede crear tenants nuevos; `rol="admin"`
aquí es un usuario de tenant normal (fila de `users`, bajo RLS), solo que es el
primero y con ese valor de `rol`.
"""

import uuid

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin


class User(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rol: Mapped[str] = mapped_column(String(50), nullable=False, default="agente")

    tenant: Mapped["Tenant"] = relationship(back_populates="users")  # noqa: F821
