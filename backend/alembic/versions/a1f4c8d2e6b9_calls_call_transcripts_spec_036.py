"""calls / call_transcripts — datos de voz (SPEC-036, ADR-007/ADR-008/ADR-009)

SPEC-036 — Datos de voz: agrega las tablas `calls` (metadatos de la llamada,
`call_id` único por tenant como base de idempotencia, ADR-007) y
`call_transcripts` (segmentos con timestamps/hablante, idioma, modelo STT,
WER opcional) bajo RLS ENABLE+FORCE por `tenant_id` (ADR-004/ADR-008), con
borrado lógico (C2).

`calls` enlaza opcionalmente a `conversations` (`canal="voz"/"telefonia"`,
sin romper el contrato existente: `conversations.canal` ya es `String(50)`)
y a `contacts`, reutilizando el mismo bus de conversación que un mensaje de
texto (RF-04). `call_transcripts.call_id` referencia a `calls` (RF-02).

Fuera de alcance (otras SPECs): conector de ingesta/almacenamiento del audio
(SPEC-037), worker STT que puebla los segmentos (SPEC-038), política de
retención/purga del audio y la transcripción (SPEC-041).

Revision ID: a1f4c8d2e6b9
Revises: 54c75efefe3c
Create Date: 2026-09-20 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

from app.db.rls import disable_rls_sql, enable_rls_sql

# revision identifiers, used by Alembic.
revision: str = "a1f4c8d2e6b9"
down_revision: Union[str, None] = "54c75efefe3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CALLS_TABLE = "calls"
_TRANSCRIPTS_TABLE = "call_transcripts"


def _audit_columns():
    """Columnas de auditoría comunes a toda entidad transaccional (C2)."""
    return [
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
    ]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # calls — metadatos de la llamada (RF-01/RF-02/RF-04)
    # ------------------------------------------------------------------
    op.create_table(
        _CALLS_TABLE,
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
        sa.Column("call_id", sa.String(length=128), nullable=False),
        sa.Column("numero", sa.String(length=50), nullable=False),
        sa.Column("direccion", sa.String(length=20), nullable=False),
        sa.Column("duracion", sa.Integer(), nullable=True),
        sa.Column(
            "estado", sa.String(length=20), nullable=False, server_default="en_curso"
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("audio_ref", sa.String(length=500), nullable=True),
        *_audit_columns(),
        sa.UniqueConstraint("tenant_id", "call_id", name="uq_calls_tenant_call_id"),
    )
    op.create_index("ix_calls_tenant_id", _CALLS_TABLE, ["tenant_id"])
    op.create_index("ix_calls_conversation_id", _CALLS_TABLE, ["conversation_id"])
    op.create_index("ix_calls_contact_id", _CALLS_TABLE, ["contact_id"])
    op.create_index("ix_calls_activo", _CALLS_TABLE, ["activo"])

    # RLS ENABLE + FORCE (ADR-004/ADR-008, RNF-47): tabla transaccional con
    # tenant_id propio, potencial PHI (ADR-009).
    for statement in enable_rls_sql(_CALLS_TABLE):
        op.execute(statement)

    # ------------------------------------------------------------------
    # call_transcripts — segmentos con timestamps/hablante (RF-02/RNF-47)
    # ------------------------------------------------------------------
    op.create_table(
        _TRANSCRIPTS_TABLE,
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
            "call_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("calls.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("segmentos", postgresql.JSONB(), nullable=False),
        sa.Column("idioma", sa.String(length=10), nullable=False),
        sa.Column("modelo_stt", sa.String(length=100), nullable=False),
        sa.Column("wer", sa.Numeric(precision=5, scale=4), nullable=True),
        *_audit_columns(),
        sa.UniqueConstraint("call_id", name="uq_call_transcripts_call_id"),
    )
    op.create_index("ix_call_transcripts_tenant_id", _TRANSCRIPTS_TABLE, ["tenant_id"])
    op.create_index("ix_call_transcripts_call_id", _TRANSCRIPTS_TABLE, ["call_id"])
    op.create_index("ix_call_transcripts_activo", _TRANSCRIPTS_TABLE, ["activo"])

    for statement in enable_rls_sql(_TRANSCRIPTS_TABLE):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_rls_sql(_TRANSCRIPTS_TABLE):
        op.execute(statement)
    op.drop_table(_TRANSCRIPTS_TABLE)

    for statement in disable_rls_sql(_CALLS_TABLE):
        op.execute(statement)
    op.drop_table(_CALLS_TABLE)
