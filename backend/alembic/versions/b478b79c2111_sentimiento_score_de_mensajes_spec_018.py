"""sentimiento_score de mensajes (análisis de sentimiento LLM local)

SPEC-018 — Análisis de sentimiento del mensaje entrante con LLM local: agrega
`sentimiento_score` a `messages` para persistir el score [0,1] asociado a la
etiqueta `sentimiento` (columna ya existente desde la migración inicial,
`192207b090b0`, como `String(20)` nullable). `server_default="0"` no rompe
filas existentes (mensajes previos sin score quedan en 0, indistinguibles de
"sin clasificar" salvo por `sentimiento IS NULL`).

Revision ID: b478b79c2111
Revises: 62351eeed68d
Create Date: 2026-09-18 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b478b79c2111"
down_revision: Union[str, None] = "62351eeed68d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "sentimiento_score",
            sa.Numeric(precision=4, scale=3),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "sentimiento_score")
