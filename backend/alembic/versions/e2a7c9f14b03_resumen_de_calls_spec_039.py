"""resumen de calls — enriquecimiento IA local sobre la transcripcion (SPEC-039)

SPEC-039 — Enriquecimiento IA local sobre la transcripción: agrega la
columna `resumen` (Text, nullable) a `calls` para persistir el resumen de la
llamada generado por el LLM local
(`app.services.call_summary_service.generate_call_summary`), tras persistir
`call_transcripts` (`stt_worker`, SPEC-038).

Decisión de diseño (documentada en `app/models/call.py`): campo simple en
`calls` (mismo criterio que `audio_ref`, SPEC-035/036) en vez de una tabla
nueva — el resumen es 1:1 con la llamada, se escribe una sola vez tras
transcribir, sin caso de uso de múltiples resúmenes históricos en el alcance
actual.

`resumen` es `nullable=True`: `None` mientras la llamada no tiene
transcripción, o si el LLM local estuvo indisponible al intentar resumir
(modo degradado, R-21) — nunca bloquea ni revierte la persistencia de la
transcripción ya confirmada por SPEC-038.

Revision ID: e2a7c9f14b03
Revises: d4e7f1a9c3b6
Create Date: 2026-09-20 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2a7c9f14b03"
down_revision: Union[str, None] = "d4e7f1a9c3b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CALLS_TABLE = "calls"


def upgrade() -> None:
    op.add_column(_CALLS_TABLE, sa.Column("resumen", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column(_CALLS_TABLE, "resumen")
