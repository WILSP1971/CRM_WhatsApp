"""platform_admins (plano-plataforma, sin tenant_id, sin RLS) — SPEC-074

ADR-015 — Mecanismo del "admin de plataforma": tabla `platform_admins`
**separada**, fuera del modelo tenant-scoped: `id` (uuid), `email`
(unique GLOBAL, no por-tenant), `password_hash` (nullable — lo llena el
bootstrap de SPEC-075), `nombre`, `activo` (borrado lógico C2) + timestamps.

Análoga a `tenants` (plano-plataforma): **NO** lleva `tenant_id`, **NO** se
añade a `app.db.rls.TENANT_SCOPED_TABLES` y por lo tanto **NO** se le aplica
`enable_rls_sql` (sin `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`, sin
política `tenant_isolation_platform_admins`). Esto es una decisión de
seguridad de ADR-015 (el admin de plataforma opera por encima de todos los
tenants), no un olvido — verificado explícitamente en SPEC-076.

Migración 100% aditiva: tabla nueva, no toca `users`/`tenants` ni ninguna
tabla existente. Sin backfill, sin password por defecto (C3).

Revision ID: 0c3a64369baa
Revises: ff1eb9091a91
Create Date: 2026-10-01 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0c3a64369baa"
down_revision: Union[str, None] = "ff1eb9091a91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "platform_admins"


def upgrade() -> None:
    # platform_admins: plano-plataforma, análoga a `tenants` — SIN tenant_id,
    # SIN política RLS por fila (ADR-015). No se llama a `enable_rls_sql` ni
    # se añade esta tabla a `TENANT_SCOPED_TABLES` (app/db/rls.py).
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("email", name="uq_platform_admins_email"),
    )
    op.create_index("ix_platform_admins_email", _TABLE, ["email"])
    op.create_index("ix_platform_admins_activo", _TABLE, ["activo"])


def downgrade() -> None:
    op.drop_index("ix_platform_admins_activo", table_name=_TABLE)
    op.drop_index("ix_platform_admins_email", table_name=_TABLE)
    op.drop_table(_TABLE)
