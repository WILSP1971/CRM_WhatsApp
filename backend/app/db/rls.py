"""
Row Level Security (RLS) multi-tenant — ADR-004 / SPEC-012.

Centraliza la lista de tablas transaccionales sujetas a RLS y el SQL de las
políticas, para que:
  1. la migración de Alembic (`alembic/versions/..._rls_policies.py`) lo use
     al crear el esquema, y
  2. los tests de aislamiento (`tests/test_rls_isolation.py`) puedan referenciar
     la misma fuente de verdad (evita que la lista de tablas RLS se desincronice).

Patrón de política (pool-model, ADR-004):
  ALTER TABLE <tabla> ENABLE ROW LEVEL SECURITY;
  ALTER TABLE <tabla> FORCE ROW LEVEL SECURITY;
  CREATE POLICY tenant_isolation_<tabla> ON <tabla>
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

`current_setting(..., true)` con el segundo argumento `true` evita que la
consulta lance error si `app.tenant_id` NUNCA fue fijado en la sesión (en ese
caso devuelve NULL). PERO (CORRECCIÓN, verificado contra Postgres real): para
un GUC personalizado (`app.tenant_id` no está declarado en `postgresql.conf`),
una vez que la sesión/conexión lo fijó una vez con `SET LOCAL`/`set_config`
y la transacción termina (commit/rollback), `current_setting(..., true)` en
la SIGUIENTE transacción de esa misma conexión (reutilizada por el pool) NO
vuelve a devolver NULL — devuelve `''` (cadena vacía), un comportamiento
documentado de los "placeholder" GUC de PostgreSQL para parámetros
personalizados. `''::uuid` lanza `invalid input syntax for type uuid` en vez
de evaluarse a NULL, rompiendo el fail-closed con un error de BD real en vez
de "0 filas silenciosamente" — confirmado en vivo (no solo en el sandbox sin
Docker de costumbre, sino contra un Postgres real). El envoltorio
`NULLIF(..., '')` convierte esa cadena vacía en NULL ANTES del cast, así que
`tenant_id = NULL` sigue siendo siempre falsa → 0 filas visibles, preservando
el fail-closed exigido por ADR-004 tanto en la primera transacción de una
conexión nueva como en cualquier transacción posterior sobre una conexión
reciclada por el pool.

`tenants` (la tabla raíz) NO lleva `tenant_id` y por lo tanto NO lleva esta
política: el aislamiento de qué tenants existen no aplica al mismo mecanismo
(gestión de tenants es operación de plataforma, fuera del alcance de RLS por
fila; SPEC-013/administración decide quién puede leer `tenants`).
"""

TENANT_SCOPED_TABLES: list[str] = [
    "users",
    "contacts",
    "conversations",
    "messages",
    "documents",
    "chunks",
    "embeddings",
    "rag_drafts",
    "whatsapp_accounts",
    "calls",
    "call_transcripts",
    "pbx_lines",
]

TENANT_SESSION_VAR = "app.tenant_id"


def enable_rls_sql(table: str) -> list[str]:
    """Sentencias SQL para habilitar y forzar RLS + política de aislamiento en `table`."""
    policy_name = f"tenant_isolation_{table}"
    predicate = (
        f"tenant_id = NULLIF(current_setting('{TENANT_SESSION_VAR}', true), '')::uuid"
    )
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
        (
            f"CREATE POLICY {policy_name} ON {table} "
            f"USING ({predicate}) WITH CHECK ({predicate});"
        ),
    ]


def disable_rls_sql(table: str) -> list[str]:
    """Sentencias SQL de reversión (downgrade de Alembic)."""
    policy_name = f"tenant_isolation_{table}"
    return [
        f"DROP POLICY IF EXISTS {policy_name} ON {table};",
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
    ]
