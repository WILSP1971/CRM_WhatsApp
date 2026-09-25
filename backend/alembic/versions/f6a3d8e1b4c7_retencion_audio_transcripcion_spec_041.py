"""retencion/purga de audio y transcripcion (SPEC-041, extiende SPEC-021)

Agrega las columnas de marca de purga/anonimización usadas por
`app.services.telefonia.call_retention_service` (job de retención de audio y
transcripción, paralelo a `app.services.retention_service` de SPEC-021):

  - `calls.audio_purged_at`: timestamp de cuándo el job de retención purgó
    FÍSICAMENTE el blob de audio del almacén cifrado (SPEC-035) y limpió
    `audio_ref`. `NULL` mientras el audio no ha sido purgado (nunca hubo
    audio, o el audio sigue vigente dentro de la ventana de retención).
    Se distingue de "nunca hubo audio" (que ya no deja rastro alguno) porque
    aquí SIEMPRE se conserva la marca de cuándo se purgó, aunque `audio_ref`
    quede en `NULL` igual que en el caso "nunca hubo audio" — el criterio de
    idempotencia del job usa esta columna, no `audio_ref IS NULL`.
  - `call_transcripts.anonymized_at`: timestamp de cuándo el job anonimizó el
    contenido de `segmentos` (sobrescrito por un marcador no identificante,
    mismo patrón que `contacts.anonymized_at` de SPEC-021/migración
    `c3d9a1f5e8b2`). `NULL` mientras la transcripción no ha sido anonimizada.

Ambas columnas son `nullable=True` y no rompen filas existentes. Nunca
implican DELETE físico de la fila (C2): solo se purga/anonimiza el contenido
sensible (blob de audio / texto de la transcripción), la fila y su
`tenant_id`/RLS se mantienen intactos para trazabilidad.

Revision ID: f6a3d8e1b4c7
Revises: e2a7c9f14b03
Create Date: 2026-09-21 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a3d8e1b4c7"
down_revision: Union[str, None] = "e2a7c9f14b03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CALLS_TABLE = "calls"
_CALL_TRANSCRIPTS_TABLE = "call_transcripts"


def upgrade() -> None:
    op.add_column(
        _CALLS_TABLE,
        sa.Column("audio_purged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        _CALL_TRANSCRIPTS_TABLE,
        sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(_CALL_TRANSCRIPTS_TABLE, "anonymized_at")
    op.drop_column(_CALLS_TABLE, "audio_purged_at")
