"""edited_by de rag_drafts (revisión BLACK PANTHER SPEC-019)

Agrega `edited_by` a `rag_drafts` para registrar quién editó el texto final
SIN sobrescribir `created_by` (quién generó/propuso originalmente el
borrador). Antes de este cambio, `edit_draft` machacaba `created_by` con el
editor, perdiendo el origen del borrador (hallazgo MAYOR de la revisión de
BLACK PANTHER a SPEC-019). `nullable=True` no rompe filas existentes (un
borrador nunca editado simplemente no tiene `edited_by`).

Revision ID: 8f2b6d4a1c7e
Revises: 5c1a9e2f7d3b
Create Date: 2026-09-18 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f2b6d4a1c7e"
down_revision: Union[str, None] = "5c1a9e2f7d3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rag_drafts",
        sa.Column("edited_by", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rag_drafts", "edited_by")
