#!/bin/bash
# ============================================================================
# 01-roles-app.sh — Rol de aplicación no-superusuario (ADR-008)
# ============================================================================
# Montado en `docker-entrypoint-initdb.d` del servicio `db` (docker-compose.yml).
# La imagen oficial `pgvector/pgvector:pg16` (basada en postgres:16) ejecuta
# TODO `.sh`/`.sql`/`.sql.gz` de ese directorio, en orden alfabético, SOLO la
# primera vez que se inicializa un volumen de datos vacío. En un volumen ya
# inicializado este script NO se re-ejecuta (comportamiento estándar de la
# imagen); para bases de datos EXISTENTES, aplicar manualmente una vez
# (documentado en RUNBOOK.md).
#
# Contexto (ADR-008, hallazgo BLACK PANTHER en SPEC-025):
# PostgreSQL NUNCA aplica Row Level Security a superusuarios ni a roles con
# BYPASSRLS, sin importar `FORCE ROW LEVEL SECURITY` (ADR-004). El backend
# (api/workers) NO debe conectarse como `postgres` (superusuario) en runtime.
#
# Este script crea:
#   1. `omnicore_app` — rol NO-superusuario, SIN bypass de RLS
#      (NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE), con permisos
#      MÍNIMOS: USAGE de schema + SELECT/INSERT/UPDATE de tablas de datos +
#      USAGE/SELECT de secuencias. CERO DDL (sin CREATE/ALTER/DROP). Es el
#      rol de runtime de api/workers (`DB_USER`/`DATABASE_URL` de runtime,
#      ver `.env.example`).
#   2. DEFAULT PRIVILEGES: cualquier tabla/secuencia que el rol propietario
#      (quien ejecuta Alembic, `POSTGRES_USER`/`DB_MIGRATION_USER`, por
#      defecto `postgres`) cree EN EL FUTURO hereda automáticamente esos
#      mismos permisos para `omnicore_app`, sin GRANTs manuales por cada
#      migración nueva.
#
# El rol propietario/DDL (owner del esquema, `postgres` por defecto o
# `DB_MIGRATION_USER` si se configura uno distinto) NO cambia: Alembic y el
# bootstrap del contenedor lo siguen usando. Este script SOLO añade el rol de
# aplicación acotado, no toca al propietario.
#
# CHECKPOINT C3 (secretos): la contraseña de `omnicore_app` se lee de la
# variable de entorno `DB_APP_PASSWORD` (propagada al contenedor `db` desde
# `docker-compose.yml` / `.env`), NUNCA hardcodeada en este script ni en el
# repo. Si falta, el script aborta (fail-fast) en vez de crear el rol sin
# contraseña o con un valor débil por defecto.
set -euo pipefail

: "${POSTGRES_DB:?POSTGRES_DB requerido (definido por la imagen oficial)}"
: "${POSTGRES_USER:?POSTGRES_USER requerido (rol propietario/DDL, definido por la imagen oficial)}"
: "${DB_APP_PASSWORD:?DB_APP_PASSWORD requerido (CHECKPOINT C3): contraseña del rol de aplicación omnicore_app. Configúrala en .env / docker-compose.yml, nunca hardcodeada.}"

DB_APP_ROLE="${DB_APP_ROLE:-omnicore_app}"

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
  -v db_app_role="${DB_APP_ROLE}" \
  -v db_app_password="${DB_APP_PASSWORD}" \
  -v db_owner_role="${POSTGRES_USER}" \
  <<-'EOSQL'
    DO
    $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_app_role') THEN
            EXECUTE format(
                'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                'NOREPLICATION NOBYPASSRLS PASSWORD %L',
                :'db_app_role', :'db_app_password'
            );
        ELSE
            -- Idempotente: si el rol ya existe (p.ej. reintento de arranque
            -- del contenedor sobre el mismo volumen), sincroniza la
            -- contraseña y reafirma los atributos de seguridad (nunca deja
            -- el rol con privilegios más amplios de los aquí definidos).
            EXECUTE format(
                'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                'NOREPLICATION NOBYPASSRLS PASSWORD %L',
                :'db_app_role', :'db_app_password'
            );
        END IF;
    END
    $$;

    -- Permite conectarse a la base de datos y usar el schema `public`.
    -- Ningún privilegio de DDL: sin CREATE en schema (no puede crear
    -- tablas), sin ser OWNER de ningún objeto. Solo DML (filas), nunca DDL
    -- (estructura).
    SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'db_app_role') \gexec
    SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'db_app_role') \gexec
    SELECT format('REVOKE CREATE ON SCHEMA public FROM %I', :'db_app_role') \gexec

    -- GRANTs sobre tablas/secuencias que YA existan al momento del arranque
    -- (relevante solo si el volumen se reinicializa después de que Alembic
    -- ya corrió; en un volumen nuevo no hay tablas todavía y son no-op).
    SELECT format('GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO %I', :'db_app_role') \gexec
    SELECT format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', :'db_app_role') \gexec

    -- DEFAULT PRIVILEGES: tablas/secuencias que el rol propietario
    -- (Alembic/DDL, POSTGRES_USER) cree EN EL FUTURO heredan automáticamente
    -- estos mismos permisos para el rol de aplicación.
    SELECT format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO %I',
        :'db_owner_role', :'db_app_role'
    ) \gexec
    SELECT format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO %I',
        :'db_owner_role', :'db_app_role'
    ) \gexec

    -- Explícitamente SIN GRANT de DELETE físico a nivel de rol (C2: borrado
    -- lógico vía UPDATE activo=false, no DELETE). Explícitamente SIN
    -- CREATE/ALTER/DROP/TRUNCATE/REFERENCES/TRIGGER: el rol de app NO puede
    -- ejecutar DDL (verificado en tests, ADR-008 criterio 3).
EOSQL

echo "[01-roles-app.sh] Rol de aplicación '${DB_APP_ROLE}' creado/actualizado (NOSUPERUSER NOBYPASSRLS, GRANTs mínimos DML) — ADR-008."
