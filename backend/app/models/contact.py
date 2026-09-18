"""Modelo `contacts` — contactos/clientes del tenant (SPEC-012).

`anonymized_at` (SPEC-021, HABEAS DATA/GDPR-like): timestamp de cuándo se
anonimizaron los datos personales de este contacto (por ejercicio del
derecho del titular vía `app.api.privacy` o por el job de retención
`app.services.retention_service`). `None` = nunca anonimizado. Anonimizar
NUNCA es un DELETE físico (C2): la fila permanece, con `nombre`/`telefono`/
`email` sobrescritos por marcadores no identificantes y `activo=False`.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin


class Contact(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "telefono", name="uq_contacts_tenant_telefono"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    anonymized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
