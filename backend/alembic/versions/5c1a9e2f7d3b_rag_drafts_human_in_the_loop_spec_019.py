"""rag_drafts human-in-the-loop (SPEC-019)

SPEC-019 — Borrador RAG human-in-the-loop: agrega la tabla `rag_drafts` que
persiste el borrador generado por SPEC-017 asociado a una conversación, con
su máquina de estados (`propuesto`/`editado`/`aprobado`/`descartado`) y la
trazabilidad de quién aprobó el envío (`approved_by`) y a qué `Message`
saliente dio origen (`sent_message_id`, NULL hasta la aprobación explícita).

Revision ID: 5c1a9e2f7d3b
Revises: b478b79c2111
Create Date: 2026-09-18 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

from app.db.rls import disable_rls_sql, enable_rls_sql

# revision identifiers, used by Alembic.
revision: str = "5c1a9e2f7d3b"
down_revision: Union[str, None] = "b478b79c2111"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "rag_drafts"


def upgrade() -> None:
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
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("content_original", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column(
            "estado", sa.String(length=20), nullable=False, server_default="propuesto"
        ),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column(
            "sent_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="RESTRICT"),
            nullable=True,
        ),
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
    )
    op.create_index("ix_rag_drafts_tenant_id", _TABLE, ["tenant_id"])
    op.create_index("ix_rag_drafts_conversation_id", _TABLE, ["conversation_id"])
    op.create_index("ix_rag_drafts_activo", _TABLE, ["activo"])

    for statement in enable_rls_sql(_TABLE):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_rls_sql(_TABLE):
        op.execute(statement)

    op.drop_table(_TABLE)
