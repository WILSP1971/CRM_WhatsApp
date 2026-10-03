"""instagram_accounts (routing instagram_business_account_id->tenant_id) +
resolve_tenant_by_instagram_account_id

SPEC-085 — Datos del canal Instagram DM (F0, espejo de SPEC-025/ADR-007/ADR-008):

- Crea `instagram_accounts (id, tenant_id, instagram_business_account_id
  UNIQUE, username, display_name, etiqueta, ...)` con RLS ENABLE+FORCE por
  `tenant_id` (entidad transaccional: 1 fila = 1 cuenta de Instagram Business
  dada de alta para 1 tenant) y borrado lógico (C2, `activo`) — mismo patrón
  exacto que `whatsapp_accounts` (migración `9368ae975625`).
- Crea la función `resolve_tenant_by_instagram_account_id(text) RETURNS uuid`
  (`SECURITY DEFINER`, `STABLE`, `SET search_path = pg_catalog, public`),
  copia literal del patrón de `resolve_tenant_by_phone_number_id` (migración
  `54c75efefe3c`, ADR-008): solo lectura, acotada a una fila
  (`instagram_business_account_id`, `activo = true`), `REVOKE ALL ... FROM
  PUBLIC` + `GRANT EXECUTE ... TO omnicore_app`.
- Migración ADITIVA: no toca `messages`/`whatsapp_accounts`/`conversations`
  (RF-03, CE-120, R-117 — cero regresión de WhatsApp).
- NO agrega columna de idempotencia nueva ni renombra `messages.wamid`
  (decisión de arquitecto, SPEC-085 §3.4, Q4=A): el `mid` de Instagram se
  persistirá (SPEC-087, fuera de alcance aquí) reutilizando esa columna
  existente.

Revision ID: b6841201da30
Revises: 0c3a64369baa
Create Date: 2026-10-03 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

from app.db.rls import disable_rls_sql, enable_rls_sql

# revision identifiers, used by Alembic.
revision: str = "b6841201da30"
down_revision: Union[str, None] = "0c3a64369baa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "instagram_accounts"
_FUNCTION_NAME = "resolve_tenant_by_instagram_account_id"
_APP_ROLE = "omnicore_app"

_CREATE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {_FUNCTION_NAME}(p_instagram_business_account_id text)
    RETURNS uuid
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = pg_catalog, public
AS $$
    SELECT tenant_id
    FROM instagram_accounts
    WHERE instagram_business_account_id = p_instagram_business_account_id
      AND activo = true
    LIMIT 1;
$$;
"""

_DROP_FUNCTION_SQL = f"DROP FUNCTION IF EXISTS {_FUNCTION_NAME}(text);"

# GRANT defensivo: en un entorno donde el rol de aplicación `omnicore_app`
# todavía no se creó (p.ej. `init-sql/01-roles-app.sh` no corrió sobre este
# volumen — BD preexistente sin bootstrap de ADR-008 aplicado), el GRANT no
# debe romper `alembic upgrade head`. Se verifica existencia del rol antes de
# otorgar EXECUTE; si el rol no existe todavía, se omite con un warning
# (mismo patrón defensivo que `54c75efefe3c`).
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
    # ------------------------------------------------------------------
    # instagram_accounts — routing instagram_business_account_id -> tenant_id
    # (RF-01)
    # ------------------------------------------------------------------
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
        sa.Column(
            "instagram_business_account_id", sa.String(length=64), nullable=False
        ),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
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
        sa.UniqueConstraint(
            "instagram_business_account_id",
            name="uq_instagram_accounts_instagram_business_account_id",
        ),
    )
    op.create_index("ix_instagram_accounts_tenant_id", _TABLE, ["tenant_id"])
    op.create_index(
        "ix_instagram_accounts_instagram_business_account_id",
        _TABLE,
        ["instagram_business_account_id"],
    )
    op.create_index("ix_instagram_accounts_activo", _TABLE, ["activo"])

    # RLS ENABLE + FORCE (ADR-004/ADR-007, RNF-04): tabla transaccional con
    # tenant_id propio, mismo criterio que whatsapp_accounts.
    for statement in enable_rls_sql(_TABLE):
        op.execute(statement)

    # ------------------------------------------------------------------
    # resolve_tenant_by_instagram_account_id — función SECURITY DEFINER
    # (ADR-008, RF-02)
    # ------------------------------------------------------------------
    op.execute(_CREATE_FUNCTION_SQL)

    # Solo lectura, acotada a una única entrada de routing (ADR-008 punto 3):
    # se revoca todo acceso público y se otorga EXECUTE únicamente al rol de
    # aplicación (nunca a PUBLIC ni a otros roles).
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION_NAME}(text) FROM PUBLIC;")
    op.execute(_GRANT_EXECUTE_SQL)


def downgrade() -> None:
    op.execute(_DROP_FUNCTION_SQL)

    for statement in disable_rls_sql(_TABLE):
        op.execute(statement)

    op.drop_index("ix_instagram_accounts_activo", table_name=_TABLE)
    op.drop_index(
        "ix_instagram_accounts_instagram_business_account_id", table_name=_TABLE
    )
    op.drop_index("ix_instagram_accounts_tenant_id", table_name=_TABLE)
    op.drop_table(_TABLE)
