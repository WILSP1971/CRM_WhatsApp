"""whatsapp_accounts (routing phone_number_id->tenant_id) + wamid de messages

SPEC-025 — Datos del canal WhatsApp (ADR-007):

- Crea `whatsapp_accounts (id, tenant_id, phone_number_id UNIQUE,
  display_phone_number, etiqueta, ...)` con RLS ENABLE+FORCE por `tenant_id`
  (entidad transaccional: 1 fila = 1 número de WhatsApp Business dado de
  alta para 1 tenant) y borrado lógico (C2, `activo`).
- Agrega `messages.wamid` (id de mensaje de WhatsApp, nullable — None para
  mensajes de otros canales) con restricción de unicidad, base de la
  idempotencia de ingesta (ADR-007, SPEC-027).
- Migración aditiva: no toca `remitente`/`sentimiento`/`estado_entrega` ya
  existentes en `messages` (RNF-07, sin regresión).

Revision ID: 9368ae975625
Revises: c3d9a1f5e8b2
Create Date: 2026-09-18 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

from app.db.rls import disable_rls_sql, enable_rls_sql

# revision identifiers, used by Alembic.
revision: str = "9368ae975625"
down_revision: Union[str, None] = "c3d9a1f5e8b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "whatsapp_accounts"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # whatsapp_accounts — routing phone_number_id -> tenant_id (RF-01)
    # ------------------------------------------------------------------
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("phone_number_id", sa.String(length=64), nullable=False),
        sa.Column("display_phone_number", sa.String(length=50), nullable=True),
        sa.Column("etiqueta", sa.String(length=255), nullable=True),
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
        sa.UniqueConstraint(
            "phone_number_id", name="uq_whatsapp_accounts_phone_number_id"
        ),
    )
    op.create_index("ix_whatsapp_accounts_tenant_id", _TABLE, ["tenant_id"])
    op.create_index("ix_whatsapp_accounts_phone_number_id", _TABLE, ["phone_number_id"])
    op.create_index("ix_whatsapp_accounts_activo", _TABLE, ["activo"])

    # RLS ENABLE + FORCE (ADR-004/ADR-007, RNF-04): tabla transaccional con
    # tenant_id propio, no una tabla de plataforma sin filas por tenant.
    for statement in enable_rls_sql(_TABLE):
        op.execute(statement)

    # ------------------------------------------------------------------
    # messages.wamid — idempotencia de ingesta de WhatsApp (RF-02, ADR-007)
    # ------------------------------------------------------------------
    op.add_column(
        "messages",
        sa.Column("wamid", sa.String(length=128), nullable=True),
    )
    op.create_unique_constraint("uq_messages_wamid", "messages", ["wamid"])


def downgrade() -> None:
    op.drop_constraint("uq_messages_wamid", "messages", type_="unique")
    op.drop_column("messages", "wamid")

    for statement in disable_rls_sql(_TABLE):
        op.execute(statement)

    op.drop_index("ix_whatsapp_accounts_activo", table_name=_TABLE)
    op.drop_index("ix_whatsapp_accounts_phone_number_id", table_name=_TABLE)
    op.drop_index("ix_whatsapp_accounts_tenant_id", table_name=_TABLE)
    op.drop_table(_TABLE)
