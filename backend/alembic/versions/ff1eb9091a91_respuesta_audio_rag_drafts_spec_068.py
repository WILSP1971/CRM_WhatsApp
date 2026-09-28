"""respuesta_modo/tts_estado/audio_salida_ref de rag_drafts (SPEC-068, ADR-014)

Migración ADITIVA que soporta el Entregable #6 (TTS de respuesta en notas de
voz, ADR-014): el humano sigue aprobando el **guion** (`rag_drafts`,
SPEC-019) exactamente como hoy; estos campos solo describen el modo de
respuesta y el estado de la ruta opcional "escuchar antes de enviar". No
introduce ningún servicio/worker de síntesis (eso es SPEC-069, fuera de
alcance aquí) ni cambia la máquina de estados de `estado`
(`propuesto→editado→aprobado/descartado`, intacta).

Columnas añadidas a `rag_drafts`:

  - `respuesta_modo` (String(20), **NOT NULL**, `server_default='texto'`):
    discriminador opt-in (Q2-A, ADR-014) — `"texto"` (default, comportamiento
    actual idéntico) | `"audio"` (el agente eligió responder con nota de voz
    TTS). `NOT NULL` con `server_default` para que las filas existentes
    queden pobladas con `"texto"` sin necesidad de un `UPDATE` explícito (el
    propio `server_default` de PostgreSQL rellena las filas preexistentes al
    añadir la columna) — más simple que el patrón de backfill vía `UPDATE`
    de SPEC-053 porque aquí el default es constante y no depende de ninguna
    condición (a diferencia de `messages.tipo`, que solo se poblaba para las
    filas con `tipo IS NULL`).
  - `tts_estado` (String(20), nullable): estado de la ruta OPCIONAL
    "escuchar antes de enviar" (Q1-C) — `NULL` mientras nadie la solicita;
    valores válidos una vez usada: `no_solicitado`/`generando`/`listo`/
    `error` (`TTS_ESTADO_VALIDOS` en `app/models/rag_draft.py`).
  - `audio_salida_ref` (String(500), nullable): referencia opaca al almacén
    cifrado (mismo patrón que `messages.audio_ref`/`calls.audio_ref`,
    SPEC-035/036/053) del clip TTS de salida. `NULL` por defecto (ADR-012
    §5: no se persiste el clip salvo auditoría, régimen SPEC-041).

RLS/`TenantMixin`/`SoftDeleteMixin` de `rag_drafts` quedan sin cambio
(columnas puramente aditivas; la tabla ya está en `TENANT_SCOPED_TABLES`
desde SPEC-012/SPEC-019). Sin backfill destructivo, sin secretos (C2/C3).

Revision ID: ff1eb9091a91
Revises: b1c8f3d5a704
Create Date: 2026-09-28 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ff1eb9091a91"
down_revision: Union[str, None] = "b1c8f3d5a704"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RAG_DRAFTS_TABLE = "rag_drafts"


def upgrade() -> None:
    op.add_column(
        _RAG_DRAFTS_TABLE,
        sa.Column(
            "respuesta_modo",
            sa.String(length=20),
            nullable=False,
            server_default="texto",
        ),
    )
    op.add_column(
        _RAG_DRAFTS_TABLE,
        sa.Column("tts_estado", sa.String(length=20), nullable=True),
    )
    op.add_column(
        _RAG_DRAFTS_TABLE,
        sa.Column("audio_salida_ref", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(_RAG_DRAFTS_TABLE, "audio_salida_ref")
    op.drop_column(_RAG_DRAFTS_TABLE, "tts_estado")
    op.drop_column(_RAG_DRAFTS_TABLE, "respuesta_modo")
