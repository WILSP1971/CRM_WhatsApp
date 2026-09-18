"""anonymized_at de contacts (SPEC-021, HABEAS DATA/GDPR-like)

Agrega `anonymized_at` a `contacts` para registrar cuándo se anonimizaron
los datos personales de un contacto (ejercicio del derecho del titular vía
`app.api.privacy` o job de retención `app.services.retention_service`).
`nullable=True` no rompe filas existentes (un contacto nunca anonimizado
simplemente tiene `anonymized_at IS NULL`). Nunca implica DELETE físico
(C2): la fila y su `tenant_id`/RLS se mantienen intactos.

Revision ID: c3d9a1f5e8b2
Revises: 8f2b6d4a1c7e
Create Date: 2026-09-18 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d9a1f5e8b2"
down_revision: Union[str, None] = "8f2b6d4a1c7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contacts", "anonymized_at")
