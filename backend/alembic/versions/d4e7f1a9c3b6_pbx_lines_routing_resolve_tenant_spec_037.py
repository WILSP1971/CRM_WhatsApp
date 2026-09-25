"""pbx_lines (routing numero_destino->tenant_id) + resolve_tenant_by_pbx_line

SPEC-037 — Conector de ingesta de grabaciones (F2), ADR-007/ADR-008:

- Crea `pbx_lines (id, tenant_id, numero_destino UNIQUE, etiqueta, ...)` con
  RLS ENABLE+FORCE por `tenant_id` (entidad transaccional: 1 fila = 1 línea/
  DID de telefonía dado de alta para 1 tenant) y borrado lógico (C2,
  `activo`). Mismo patrón que `whatsapp_accounts` (SPEC-025).
- Crea `resolve_tenant_by_pbx_line(text) RETURNS uuid`: función
  `SECURITY DEFINER` + `STABLE` + `SET search_path` fijo, propietaria del rol
  privilegiado que ejecuta esta migración (Alembic, `DATABASE_URL_MIGRATIONS`,
  ADR-008), con `GRANT EXECUTE` acotado al rol de aplicación `omnicore_app`
  (`REVOKE ALL FROM PUBLIC`). Resuelve el tenant de una llamada entrante ANTES
  de fijar `app.tenant_id` de sesión (RLS), mismo mecanismo que
  `resolve_tenant_by_phone_number_id` (migración `54c75efefe3c`).

Migración aditiva: no toca `calls`/`call_transcripts` (SPEC-036) ni ninguna
tabla existente.

Revision ID: d4e7f1a9c3b6
Revises: a1f4c8d2e6b9
Create Date: 2026-09-20 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

from app.db.rls import disable_rls_sql, enable_rls_sql

# revision identifiers, used by Alembic.
revision: str = "d4e7f1a9c3b6"
down_revision: Union[str, None] = "a1f4c8d2e6b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "pbx_lines"
_FUNCTION_NAME = "resolve_tenant_by_pbx_line"
_APP_ROLE = "omnicore_app"

_CREATE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {_FUNCTION_NAME}(p_numero_destino text)
    RETURNS uuid
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = pg_catalog, public
AS $$
    SELECT tenant_id
    FROM pbx_lines
    WHERE numero_destino = p_numero_destino
      AND activo = true
    LIMIT 1;
$$;
"""

_DROP_FUNCTION_SQL = f"DROP FUNCTION IF EXISTS {_FUNCTION_NAME}(text);"

# GRANT defensivo (igual que 54c75efefe3c): si el rol de aplicación todavía
# no existe (BD preexistente sin bootstrap ADR-008), no rompe `upgrade head`.
_GRANT_EXECUTE_SQL = f"""
DO
$$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN
        EXECUTE 'GRANT EXECUTE ON FUNCTION {_FUNCTION_NAME}(text) TO {_APP_ROLE}';
    ELSE
        RAISE WARNING
            'Rol % no existe todavia: EXECUTE de {_FUNCTION_NAME}(text) no '
            'otorgado. Aplica init-sql/01-roles-app.sh (ADR-008) y vuelve a '
            'ejecutar esta migracion (o el GRANT manualmente).', '{_APP_ROLE}';
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("numero_destino", sa.String(length=50), nullable=False),
        sa.Column("etiqueta", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("numero_destino", name="uq_pbx_lines_numero_destino"),
    )
    op.create_index("ix_pbx_lines_tenant_id", _TABLE, ["tenant_id"])
    op.create_index("ix_pbx_lines_numero_destino", _TABLE, ["numero_destino"])
    op.create_index("ix_pbx_lines_activo", _TABLE, ["activo"])

    # RLS ENABLE + FORCE (ADR-004/ADR-008, RNF-47): tabla transaccional con
    # tenant_id propio.
    for statement in enable_rls_sql(_TABLE):
        op.execute(statement)

    op.execute(_CREATE_FUNCTION_SQL)
    # Solo lectura, acotada a una única entrada de routing (mismo criterio
    # que resolve_tenant_by_phone_number_id, ADR-008 punto 3).
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION_NAME}(text) FROM PUBLIC;")
    op.execute(_GRANT_EXECUTE_SQL)


def downgrade() -> None:
    op.execute(_DROP_FUNCTION_SQL)

    for statement in disable_rls_sql(_TABLE):
        op.execute(statement)

    op.drop_index("ix_pbx_lines_activo", table_name=_TABLE)
    op.drop_index("ix_pbx_lines_numero_destino", table_name=_TABLE)
    op.drop_index("ix_pbx_lines_tenant_id", table_name=_TABLE)
    op.drop_table(_TABLE)
