"""índices de soporte para analytics_service (SPEC-062, PLAN-007 F0)

Migración ADITIVA (solo `CREATE INDEX`, sin tocar RLS/columnas existentes)
que añade los índices que `app.services.analytics_service` necesita para
que sus agregaciones (filtro por rango de fechas + canal/estado, window
functions de tiempos de respuesta) corran con buen plan de ejecución
(RNF-73). Estado verificado ANTES de esta migración (revisado en el propio
esquema, migración inicial `192207b090b0` y siguientes): ya existían
`ix_messages_conversation_id`, `ix_conversations_tenant_id` (vía
`TenantMixin`) e `ix_conversations_activo` (vía `SoftDeleteMixin`), pero
NINGÚN índice cubría `created_at` de `messages` ni de `conversations`, ni
`conversations.canal`/`conversations.estado` — las 4 funciones de
`analytics_service` filtran/agrupan por esas columnas en cada llamada.

Índices añadidos:

  1. `ix_messages_conversation_id_created_at` — compuesto
     `(conversation_id, created_at)` sobre `messages`. Es el índice más
     importante de esta migración: `get_response_time_metrics` calcula
     `LAG(remitente) OVER (PARTITION BY conversation_id ORDER BY
     created_at)` y una window `MIN(...) OVER (PARTITION BY conversation_id
     ORDER BY created_at ROWS BETWEEN CURRENT ROW AND UNBOUNDED
     FOLLOWING)` — ambas particionan por `conversation_id` y ordenan por
     `created_at`; este compuesto permite a PostgreSQL recorrer cada
     partición ya ordenada sin un `Sort` completo en memoria por
     conversación.
  2. `ix_conversations_created_at` — sobre `conversations.created_at`, para
     el filtro de rango `[desde, hasta]` y el `GROUP BY
     date_trunc('day', created_at)` de la serie diaria en
     `get_conversation_metrics`/`get_conversion_rate`.
  3. `ix_conversations_canal` — sobre `conversations.canal`. Se añade
     (a diferencia de `estado`, que NO se indexa aquí) porque el filtro
     opcional `canal=...` de las 4 funciones públicas de `analytics_service`
     es el único predicado de igualdad que puede reducir drásticamente el
     conjunto de filas ANTES de aplicar el filtro de rango — con pocos
     valores distintos (`CANALES_VALIDOS` es un conjunto pequeño y estable)
     un índice sobre `canal` sigue siendo selectivo cuando se combina con
     el rango de fechas. `estado` (solo 2 valores: "abierta"/"cerrada") es
     mucho menos selectivo por sí solo — el `GROUP BY estado` ya lo resuelve
     bien el índice de `created_at` acotando primero el rango; no se
     sobre-indexa aquí a propósito (queda para que THOR mida en SPEC-065 si
     hiciera falta ajustar, según el criterio explícito de SPEC-062).

Revision ID: b1c8f3d5a704
Revises: a9a3e9b21673
Create Date: 2026-09-27 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c8f3d5a704"
down_revision: Union[str, None] = "a9a3e9b21673"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MESSAGES_TABLE = "messages"
_CONVERSATIONS_TABLE = "conversations"


def upgrade() -> None:
    op.create_index(
        "ix_messages_conversation_id_created_at",
        _MESSAGES_TABLE,
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_conversations_created_at",
        _CONVERSATIONS_TABLE,
        ["created_at"],
    )
    op.create_index(
        "ix_conversations_canal",
        _CONVERSATIONS_TABLE,
        ["canal"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_canal", table_name=_CONVERSATIONS_TABLE)
    op.drop_index("ix_conversations_created_at", table_name=_CONVERSATIONS_TABLE)
    op.drop_index(
        "ix_messages_conversation_id_created_at", table_name=_MESSAGES_TABLE
    )
