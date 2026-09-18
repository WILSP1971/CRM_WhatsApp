"""
Modelo `tenants` — raíz del aislamiento multi-tenant (ADR-004, SPEC-012).

`tenants` NO lleva `tenant_id` (es la entidad raíz que define el tenant), pero
SÍ lleva borrado lógico (C2) y auditoría, ya que es una entidad transaccional
(alta/baja de clientes de la plataforma).
"""

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class Tenant(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )

    users: Mapped[list["User"]] = relationship(back_populates="tenant")  # noqa: F821
