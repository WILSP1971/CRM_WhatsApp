"""media_url/media_type de messages — referencia a la URL del CDN de Meta
para los adjuntos de DMs de Instagram (SPEC-088)

SPEC-088 — Columna ADITIVA en `messages` para persistir la REFERENCIA a la
media de los DMs de Instagram (la URL firmada del CDN de Meta,
`lookaside.fbsbx.com`, tal cual la entrega el payload del webhook) y su
`type`, SIN descargar ni cifrar el binario (política de Meta,
`chatwoot#8583`; decisión vinculante del Lead, ver SPEC-088 "NOTA DE
REVISIÓN POST-APROBACIÓN").

  - `messages.media_url` (String(2048), nullable): URL EXTERNA del CDN de
    Meta tal cual llega en `attachments[].payload.url` del webhook de
    Instagram DM (SPEC-086, `inbound_parser.InstagramMessageEvent.
    attachments`). Longitud holgada porque la URL firmada incluye
    `asset_id`/`signature` largos. NO es una ruta local, NO está cifrada, su
    ciclo de vida lo controla Meta (expira/se revoca cuando el usuario borra
    el contenido) — el backend NUNCA la resuelve ni abre una conexión hacia
    ella (RNF-NO-EGRESS-MEDIA). `NULL` para mensajes sin adjunto y para los
    de WhatsApp/webchat.
  - `messages.media_type` (String(32), nullable): tipo de adjunto tal como
    lo clasifica Meta en `attachments[].type` (p.ej. `"image"`, `"video"`,
    `"audio"`, `"file"`). `NULL` en los mismos casos que `media_url`.

EXPLÍCITAMENTE DISTINTO de `audio_ref` (SPEC-054/058, ADR-009): `audio_ref`
es una referencia OPACA a un blob de audio de WhatsApp que el backend
DESCARGÓ y CIFRÓ EN REPOSO (`audio_store`), con ciclo de vida gobernado por
el job de retención propio (SPEC-041/058). `media_url`/`media_type`, en
cambio, son la URL EXTERNA tal cual de Meta — nunca se descarga el binario,
nunca se cifra, y su expiración la controla Meta, no este backend. Esta
SPEC NO toca `audio_ref`/`audio_store`/ADR-009, que permanecen EXCLUSIVOS
de las notas de voz de WhatsApp.

Migración ADITIVA, no destructiva (R-117): no toca ninguna otra tabla ni
columna existente de `messages`. Sin backfill (no existe ninguna fuente
retroactiva de estos datos para filas ya persistidas).

Revision ID: c1d5e9a7f203
Revises: b6841201da30
Create Date: 2026-10-04 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d5e9a7f203"
down_revision: Union[str, None] = "b6841201da30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MESSAGES_TABLE = "messages"


def upgrade() -> None:
    op.add_column(
        _MESSAGES_TABLE,
        sa.Column("media_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        _MESSAGES_TABLE,
        sa.Column("media_type", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(_MESSAGES_TABLE, "media_type")
    op.drop_column(_MESSAGES_TABLE, "media_url")
