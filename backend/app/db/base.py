"""
Declarative base y mixins comunes para los modelos ORM (SPEC-012).

- `Base`: declarative base de SQLAlchemy 2.0, punto único que Alembic usa
  (`target_metadata = Base.metadata`) para autogenerar/validar migraciones.
- `TimestampMixin`: columnas de auditoría `created_at`/`updated_at`.
- `TenantMixin`: columna `tenant_id` NOT NULL obligatoria en toda entidad
  transaccional (ADR-004, RF de SPEC-012). Cada tabla que la use es candidata
  a política RLS (ver `app/db/rls.py`).
- `SoftDeleteMixin`: borrado lógico (CHECKPOINT C2) — columna `activo`
  (Activo/Inactivo) en lugar de DELETE físico, más `created_by` de auditoría.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base compartida por todos los modelos del dominio."""

    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Columnas de auditoría temporal (created_at/updated_at)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class TenantMixin:
    """
    Columna `tenant_id` NOT NULL obligatoria para toda entidad transaccional
    (ADR-004: aislamiento multi-tenant por RLS, pool-model).

    La FK apunta a `tenants.id`. El aislamiento real lo fuerza la política RLS
    correspondiente (ver `app/db/rls.py`), no esta FK por sí sola.
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class SoftDeleteMixin:
    """
    Borrado lógico (CHECKPOINT C2): jamás DELETE físico en entidades
    transaccionales. `activo=True` (Activo) / `activo=False` (Inactivo).
    """

    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


def uuid_pk() -> Mapped[uuid.UUID]:
    """Helper para declarar una PK UUID con default server-side (gen_random_uuid())."""
    raise NotImplementedError(
        "Usar mapped_column directamente; ver modelos en app/models/"
    )
