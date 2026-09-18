# SPEC-012 — Modelo de datos multi-tenant + migraciones + Row-Level Security

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, WOLVERINE · Prioridad: ALTA · Tipo: BACKEND/DATOS · Fase: F1
- Deriva de: PLAN-002 (F1) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Definir el esquema de datos multi-tenant con migraciones versionadas (Alembic), **políticas RLS `FORCE` por `tenant_id`**, borrado lógico Activo/Inactivo (C2) y `pgvector` habilitado; con seed ficticio por tenant.

## Contexto

Fase F1: prerequisito duro de SPEC-013..SPEC-019 (sin esquema/RLS no hay auth aislada ni persistencia). El aislamiento se fuerza a nivel de motor con RLS `FORCE`; toda tabla transaccional lleva `tenant_id` NOT NULL y flag `activo`. Base de CE-22 (aislamiento probado). Decide RLS vs schema-por-tenant → ADR-004.

## Alcance

### IN
- Tablas: `tenants`, `users`, `contacts`, `conversations`, `messages`, `documents`, `chunks`, `embeddings` (+ tablas de roles/sesión si aplica).
- `tenant_id` NOT NULL en toda entidad transaccional; FK y índices por tenant.
- Columna `pgvector` en `embeddings`; índice vectorial (HNSW/IVF) preparado.
- Políticas **RLS `ENABLE` + `FORCE`** por `tenant_id` usando variable de sesión (p.ej. `app.tenant_id`).
- Borrado lógico: columna `activo` (Activo/Inactivo) + columnas de auditoría (`created_at`, `updated_at`, `created_by`).
- Migraciones versionadas con Alembic; seed ficticio con ≥2 tenants aislados.

### OUT
- Inyección del `tenant_id` en la sesión desde el middleware de auth (SPEC-013).
- Lógica de negocio de endpoints (SPEC-014).
- Ingesta/generación de embeddings reales (SPEC-016/017).

## Dependencias
- Depende de SPEC-011 (infra + db). Prerequisito de SPEC-013, 014, 015, 016, 017, 018, 019.

## Requisitos funcionales
- RF Todas las entidades transaccionales tienen `tenant_id` y `activo`.
- RF RLS impide leer/escribir filas de otro tenant aunque el query no filtre por `tenant_id`.
- RF El borrado es lógico (marca `activo=false`); no hay DELETE físico transaccional.
- RF Migraciones aplicables e idempotentes; seed carga ≥2 tenants con datos disjuntos.

## Requisitos no funcionales
- RNF-02 Aislamiento multi-tenant por RLS `FORCE`.
- RNF-07 Migraciones versionadas; esquema como fuente de verdad.
- Índice vectorial dimensionado para recuperación p95 ≤ 300 ms (validado en SPEC-017/022).

## Criterios de aceptación (verificables)
- [ ] `alembic upgrade head` crea todo el esquema desde cero sin errores.
- [ ] Toda tabla transaccional tiene `tenant_id NOT NULL` y columna `activo`.
- [ ] RLS está `ENABLE` **y** `FORCE` en todas las tablas con `tenant_id`.
- [ ] Con `app.tenant_id = A`, un `SELECT` sin WHERE devuelve **solo** filas del tenant A (0 filas de B).
- [ ] Un intento de `UPDATE/DELETE` de fila de otro tenant afecta 0 filas.
- [ ] No existe `DELETE` físico en el código de dominio para entidades transaccionales (borrado lógico).
- [ ] Seed carga ≥2 tenants con datos disjuntos verificables.
- [ ] `pgvector` habilitado y columna de embeddings con índice creado.

## Notas de seguridad (C2/C3)
- C2: borrado lógico Activo/Inactivo en todas las entidades transaccionales.
- C3: cadenas de conexión y credenciales de migración vía env; nunca en el repo.

## Restricción SENSIBLE aplicable
- Multi-tenant aislado por RLS (SUP-25). Sin procesamiento externo: el esquema y los vectores viven en PostgreSQL on-prem.

## Riesgos
- R-23 (RLS mal configurado → fuga cross-tenant): RLS `FORCE` + test cross-tenant (SPEC-022).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-002).

## Nota ADR
- Requiere **ADR-004**: aislamiento multi-tenant RLS (pool-model) vs schema-por-tenant.
