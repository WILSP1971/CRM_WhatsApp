"""
Modelo `users` — usuarios/agentes de un tenant (SPEC-012).

Alcance SPEC-012: solo el esquema, RLS y borrado lógico. Hashing de contraseñas,
roles finos y emisión de JWT son de SPEC-013 (fuera de alcance aquí); se deja la
columna `password_hash` preparada para que SPEC-013 la use.
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
