"""retencion/purga de audio de mensajería (SPEC-058, extiende SPEC-041)

Agrega la columna de marca de purga física usada por
`app.services.telefonia.call_retention_service` (MISMO job de retención de
audio/transcripción de llamadas de SPEC-041, ahora con un selector ampliado
que cubre también el origen mensajería, SPEC-053/RNF-64: "un solo régimen de
retención... el mismo job cubre voz y mensajería, sin política paralela"):

  - `messages.audio_purged_at`: timestamp de cuándo el job de retención purgó
    FÍSICAMENTE el blob de audio de la nota de voz de WhatsApp del almacén
    cifrado (SPEC-035) y limpió `audio_ref`. `NULL` mientras el audio no ha
    sido purgado (nunca hubo audio, o el audio sigue vigente dentro de la
    ventana de retención). Mismo criterio que `calls.audio_purged_at`
    (migración gemela `f6a3d8e1b4c7`, SPEC-041): el criterio de idempotencia
    del job usa ESTA columna, no `audio_ref IS NULL` (que también sería
    `NULL`/vacío para un `Message` de tipo "texto" que nunca tuvo audio, un
    caso que no debe confundirse con "audio ya purgado").

    NO confundir con `messages.transcripcion_estado` (SPEC-053): esa columna
    rastrea el ciclo de vida de la TRANSCRIPCIÓN de texto (pendiente/ok/
    descartada_por_duracion/error, escrita por el worker STT de SPEC-056);
    `audio_purged_at` rastrea el ciclo de vida, independiente, de la purga
    física del AUDIO original. Son dos relojes distintos a propósito (ver
    docstring de `app.services.telefonia.call_retention_service`, sección
    SPEC-058): la transcripción en `Message.contenido` sigue la política de
    retención de `Message`/contactos (SPEC-021) y NO se ve afectada por que
    el audio ya haya sido purgado.

Es `nullable=True` y no rompe filas existentes (todos los `Message` de tipo
"texto" y las notas de voz ya insertadas antes de esta migración quedan con
`audio_purged_at = NULL`, tal como si el audio siguiera vigente, hasta que el
job los evalúe contra la ventana de retención configurada).

Nunca implica DELETE físico de la fila `Message` (C2): a diferencia de
`Call` (donde purgar el audio implica dar de baja lógica TODA la fila, ya
que el audio es su artefacto principal), para `Message` la purga del audio
NO toca `Message.activo` — el payload principal de un `Message` de nota de
voz es su transcripción de texto (`Message.contenido`), que vive bajo un
ciclo de vida independiente (SPEC-021); ver
`app.services.telefonia.call_retention_service._purge_message_audio` para la
decisión de diseño completa.

Revision ID: a9a3e9b21673
Revises: a2fd6d06f701
Create Date: 2026-09-26 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9a3e9b21673"
down_revision: Union[str, None] = "a2fd6d06f701"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MESSAGES_TABLE = "messages"


def upgrade() -> None:
    op.add_column(
        _MESSAGES_TABLE,
        sa.Column("audio_purged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(_MESSAGES_TABLE, "audio_purged_at")
