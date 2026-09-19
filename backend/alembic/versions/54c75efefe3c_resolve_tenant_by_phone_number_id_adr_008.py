"""resolve_tenant_by_phone_number_id — función SECURITY DEFINER (ADR-008)

Corrige el BLOQUEANTE #2 de SPEC-025 (hallazgo BLACK PANTHER): la resolución
`phone_number_id -> tenant_id` que hace el webhook de WhatsApp ANTES de fijar
`app.tenant_id` (RLS, ADR-004/ADR-007) "funcionaba" solo porque el backend se
conectaba como superusuario `postgres` (que PostgreSQL nunca sujeta a RLS).
Con el rol de aplicación `omnicore_app` (ADR-008, NOSUPERUSER NOBYPASSRLS),
esa ruta deja de funcionar por accidente y necesita un mecanismo EXPLÍCITO.

Esta migración crea `resolve_tenant_by_phone_number_id(text) RETURNS uuid`:
  - `SECURITY DEFINER` + `STABLE` + `SET search_path = pg_catalog, public`
    (evita secuestro de search_path).
  - Propietaria del rol PRIVILEGIADO que ejecuta esta migración (Alembic usa
    `DATABASE_URL_MIGRATIONS`, ADR-008): al ejecutarse con los privilegios
    del owner, la función puede leer `whatsapp_accounts` sin que la sesión
    tenga `app.tenant_id` fijado, sin necesitar bypass general de RLS.
  - `REVOKE ALL ... FROM PUBLIC` + `GRANT EXECUTE ... TO omnicore_app`: única
    vía de acceso pre-tenant, acotada a esta consulta de solo lectura sobre
    una única fila (`phone_number_id`, `activo = true`).

Revision ID: 54c75efefe3c
Revises: 9368ae975625
Create Date: 2026-09-18 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "54c75efefe3c"
down_revision: Union[str, None] = "9368ae975625"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FUNCTION_NAME = "resolve_tenant_by_phone_number_id"
_APP_ROLE = "omnicore_app"

_CREATE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {_FUNCTION_NAME}(p_phone_number_id text)
    RETURNS uuid
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = pg_catalog, public
AS $$
    SELECT tenant_id
    FROM whatsapp_accounts
    WHERE phone_number_id = p_phone_number_id
      AND activo = true
    LIMIT 1;
$$;
"""

_DROP_FUNCTION_SQL = f"DROP FUNCTION IF EXISTS {_FUNCTION_NAME}(text);"

# GRANT defensivo: en un entorno donde el rol de aplicación `omnicore_app`
# todavía no se creó (p.ej. `init-sql/01-roles-app.sh` no corrió sobre este
# volumen — BD preexistente sin bootstrap de ADR-008 aplicado), el GRANT no
# debe romper `alembic upgrade head`. Se verifica existencia del rol antes de
# otorgar EXECUTE; si el rol no existe todavía, se omite con un warning (el
# runbook documenta aplicar el bootstrap de roles y luego re-ejecutar esta
# migración, o simplemente reiniciar el contenedor `db` una vez creado).
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
    op.execute(_CREATE_FUNCTION_SQL)

    # Solo lectura, acotada a una única entrada de routing (ADR-008 punto 3):
    # se revoca todo acceso público y se otorga EXECUTE únicamente al rol de
    # aplicación (nunca a PUBLIC ni a otros roles).
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION_NAME}(text) FROM PUBLIC;")
    op.execute(_GRANT_EXECUTE_SQL)


def downgrade() -> None:
    op.execute(_DROP_FUNCTION_SQL)
