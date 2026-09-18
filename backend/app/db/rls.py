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
      USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
      WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

`current_setting(..., true)` con el segundo argumento `true` evita que la
consulta lance error si `app.tenant_id` no fue fijado (sesión "sin tenant");
en ese caso `current_setting` devuelve NULL y la comparación `tenant_id = NULL`
es siempre falsa → 0 filas visibles (fail-closed, tal como exige ADR-004).

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
]

TENANT_SESSION_VAR = "app.tenant_id"


def enable_rls_sql(table: str) -> list[str]:
    """Sentencias SQL para habilitar y forzar RLS + política de aislamiento en `table`."""
    policy_name = f"tenant_isolation_{table}"
    predicate = f"tenant_id = current_setting('{TENANT_SESSION_VAR}', true)::uuid"
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
