"""tipo/audio_ref de messages — nota de voz de WhatsApp (SPEC-053, ADR-013)

SPEC-053 — Extensión aditiva de `messages` para modelar una nota de voz de
WhatsApp como un `Message` real (ADR-013: NUNCA como `call`/`call_transcript`,
esas tablas no se crean ni se tocan aquí):

  - `messages.tipo` (String, nullable): discriminador de tipo de mensaje.
    Valores válidos `"texto"` | `"audio"` (`TIPOS_MENSAJE_VALIDOS` en
    `app/models/message.py`). Backfill de los mensajes existentes a
    `"texto"` en esta misma migración (UPDATE no destructivo, ver decisión
    de diseño más abajo) para que el discriminador quede poblado desde ya
    en el camino de texto, en vez de dejarlo en NULL a interpretar por la
    capa de servicio.
  - `messages.contenido` pasa a **nullable** (relajación de constraint, no
    destructiva): un `Message(tipo="audio")` nace sin contenido hasta que
    SPEC-056 escribe la transcripción. Los mensajes de texto existentes y
    futuros siguen poblando `contenido` con normalidad (RF-03/RNF-64).
  - `messages.audio_ref` (String, nullable): referencia opaca al almacén de
    audio cifrado on-prem de SPEC-035, mismo patrón exacto que
    `calls.audio_ref` (SPEC-036/migración `a1f4c8d2e6b9`) — ni ruta física
    ni binario, `NULL` para mensajes de texto.
  - `messages.transcripcion_estado` (String, nullable): estado del ciclo de
    vida de la transcripción de la nota de voz. Valores válidos
    `"pendiente"` | `"ok"` | `"descartada_por_duracion"` | `"error"`
    (`TRANSCRIPCION_ESTADOS_VALIDOS` en el modelo). `NULL` para mensajes de
    texto (nunca aplica).
  - `messages.audio_duracion_seg` (Integer, nullable): duración en segundos
    de la nota de voz, para el límite de duración de SPEC-055 (fuera de
    alcance aquí). `NULL` para mensajes de texto.

Decisión de diseño — backfill de `tipo` (SPEC-053, criterio de aceptación):
se elige hacer un `UPDATE messages SET tipo = 'texto' WHERE tipo IS NULL`
dentro de la propia migración, en vez de dejar `tipo IS NULL` a interpretar
como texto por la capa de servicio. Motivo: es un UPDATE no destructivo (no
toca `contenido` ni ninguna otra columna, no reescribe historial, es
idempotente y reversible— el `downgrade` simplemente elimina la columna, sin
necesidad de revertir el UPDATE), dejando el discriminador **siempre
poblado** para todo mensaje de texto real desde el día 1. Es más simple y
más seguro que repartir la regla "NULL == texto" entre el modelo y cada
consulta/servicio que lea `tipo` (RNF-64, R-68).

RLS/`TenantMixin`/`SoftDeleteMixin` de `messages` quedan sin cambio (columnas
aditivas, la tabla ya está en `TENANT_SCOPED_TABLES` desde SPEC-012).

Revision ID: 807a0756643c
Revises: f6a3d8e1b4c7
Create Date: 2026-09-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "807a0756643c"
down_revision: Union[str, None] = "f6a3d8e1b4c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MESSAGES_TABLE = "messages"


def upgrade() -> None:
    op.add_column(
        _MESSAGES_TABLE, sa.Column("tipo", sa.String(length=20), nullable=True)
    )
    op.add_column(
        _MESSAGES_TABLE, sa.Column("audio_ref", sa.String(length=500), nullable=True)
    )
    op.add_column(
        _MESSAGES_TABLE,
        sa.Column("transcripcion_estado", sa.String(length=30), nullable=True),
    )
    op.add_column(
        _MESSAGES_TABLE,
        sa.Column("audio_duracion_seg", sa.Integer(), nullable=True),
    )

    # `contenido` pasa a nullable: relajación de constraint, no destructiva
    # (RF-03/RNF-64) — los mensajes de texto existentes ya tienen contenido
    # poblado y siguen intactos.
    op.alter_column(
        _MESSAGES_TABLE,
        "contenido",
        existing_type=sa.Text(),
        nullable=True,
    )

    # Backfill lógico no destructivo: todo mensaje preexistente es de texto
    # (ver decisión de diseño en el docstring del módulo).
    op.execute(
        sa.text(f"UPDATE {_MESSAGES_TABLE} SET tipo = 'texto' WHERE tipo IS NULL")
    )


def downgrade() -> None:
    # Decisión de diseño (corrección post-revisión de WOLVERINE): el downgrade
    # NO revierte `contenido` a `NOT NULL`. Esta migración habilita
    # explícitamente `Message(tipo="audio", contenido=NULL)` como caso de uso
    # legítimo (incluido el propio seed ficticio de SPEC-053,
    # `_seed_whatsapp_nota_voz_ficticia` en `app/db/seed.py`). Si al momento
    # de ejecutar el downgrade existe CUALQUIER fila con `contenido IS NULL`
    # (exactamente lo que este mismo cambio permite crear), forzar
    # `ALTER COLUMN contenido SET NOT NULL` falla en seco con
    # `NotNullViolation`, dejando la migración a medio revertir.
    #
    # Ademas, no hay ganancia real en reforzar la constraint aqui: ningun
    # mensaje de TEXTO depende de que se restaure el `NOT NULL` de `contenido`
    # — la aplicacion sigue poblando `contenido` para mensajes de texto por
    # convencion propia, no porque la base de datos lo exija. Una vez que
    # existen notas de voz reales en la tabla, "NOT NULL" ya no es una
    # garantia que se pueda sostener limpiamente en un downgrade generico.
    #
    # Por eso: dejamos `contenido` como `nullable=True` tambien en el
    # downgrade y este solo elimina las columnas nuevas de la SPEC-053.
    # No "corregir" esto de vuelta sin releer esta nota — ver SPEC-053 y la
    # revision de WOLVERINE que motivo este cambio.
    op.drop_column(_MESSAGES_TABLE, "audio_duracion_seg")
    op.drop_column(_MESSAGES_TABLE, "transcripcion_estado")
    op.drop_column(_MESSAGES_TABLE, "audio_ref")
    op.drop_column(_MESSAGES_TABLE, "tipo")
