"""mime_type de messages — media descargado de WhatsApp (SPEC-054)

SPEC-054 — Extensión aditiva de `messages` para persistir el `mime_type`
reportado por Meta al resolver la metadata de un media entrante (nota de voz
de WhatsApp, ADR-013 sigue aplicando: la nota de voz vive como un `Message`
real, no como `call`/`call_transcript`):

  - `messages.mime_type` (String, nullable): tipo MIME del media descargado
    (p.ej. `"audio/ogg; codecs=opus"`), tal cual lo reporta Meta en el paso 1
    de `GraphMediaClient` (`resolve_media_metadata`). `NULL` para mensajes de
    texto y para notas de voz cuya descarga falló antes de resolver esa
    metadata (`transcripcion_estado="error"`).

Corrección post-revisión (WOLVERINE, SPEC-054): el RF de SPEC-054 exige
explícitamente la persistencia del `mime_type` en los campos opcionales del
`Message`, pero la columna nunca se agregó — `media_client.py` lo recibía de
Meta, lo logueaba, y se perdía. Esta migración corrige esa omisión; NO se
edita la migración ya cerrada de SPEC-053 (`807a0756643c`), que agregó
`tipo`/`audio_ref`/`transcripcion_estado`/`audio_duracion_seg`.

No requiere backfill: no existe ninguna fuente retroactiva del `mime_type`
para las filas ya persistidas antes de este cambio (el binario ya descargado
no se vuelve a resolver contra Graph API solo para poblar esta columna) — se
deja `NULL` para esas filas, sin efecto sobre `contenido`/`audio_ref` ya
almacenados.

RLS/`TenantMixin`/`SoftDeleteMixin` de `messages` quedan sin cambio (columna
aditiva, la tabla ya está en `TENANT_SCOPED_TABLES` desde SPEC-012).

Revision ID: a2fd6d06f701
Revises: 807a0756643c
Create Date: 2026-09-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2fd6d06f701"
down_revision: Union[str, None] = "807a0756643c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MESSAGES_TABLE = "messages"


def upgrade() -> None:
    op.add_column(
        _MESSAGES_TABLE, sa.Column("mime_type", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column(_MESSAGES_TABLE, "mime_type")
