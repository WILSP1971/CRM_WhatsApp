"""estado_entrega de mensajes (WebChat)

SPEC-015 — Canal WebChat propio: agrega `estado_entrega` a `messages` para
soportar los estados de entrega (enviado/entregado/leído) del criterio de
aceptación "Los mensajes registran estado de entrega".

Revision ID: 62351eeed68d
Revises: 192207b090b0
Create Date: 2026-09-18 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "62351eeed68d"
down_revision: Union[str, None] = "192207b090b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "estado_entrega",
            sa.String(length=20),
            nullable=False,
            server_default="enviado",
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "estado_entrega")
