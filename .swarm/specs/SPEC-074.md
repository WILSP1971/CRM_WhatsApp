# SPEC-074 — Modelo de datos aditivo: migración Alembic de `platform_admins` (sin `tenant_id`, NO scoped, sin RLS) + semántica de `rol="admin"` del primer usuario del tenant (columna `rol` existente, sin cambio de esquema en `users`) 🔴 SENSIBLE

- Estado: APROBADA (bloque PLAN-009, 2026-09-30). · Responsable: CAPTAIN AMERICA · Colaboran/revisan: BLACK PANTHER, BLACK WIDOW, HAWKEYE, WOLVERINE · Prioridad: ALTA · Tipo: BACKEND/MIGRACIÓN · Fase: F1
- Deriva de: PLAN-009 (F1, §2.IN.1/4, §3.2, §4, §9, R-94/R-95, CE-91/CE-94) · Clasificación: SENSIBLE (`.no-externo`) · Depende de SPEC-073/ADR-015 · Consume ADR-004/ADR-008/SPEC-012/SPEC-013

## Objetivo

Materializar la decisión (a) de ADR-015: crear —mediante una **migración Alembic aditiva**— la tabla **`platform_admins`** como concepto separado fuera del modelo tenant-scoped (**sin `tenant_id`**, **NO** en `TENANT_SCOPED_TABLES`, **sin política RLS** por fila, análoga a `tenants`), con su propio `email` (único global), `password_hash`, `nombre`, `activo` (C2) + timestamps. Además, **documentar y fijar la semántica de `rol="admin"`** para el primer usuario del tenant, reutilizando la columna `rol` **ya existente** de `users` (str 50, default `"agente"`) **sin cambio de esquema**. Todo es **aditivo**: sin backfill destructivo, cero impacto en tenants/usuarios existentes.

## Contexto

`tenants` es la raíz del aislamiento sin `tenant_id`, no scoped (`app/models/tenant.py`, `rls.py:37-40,43-56`); `platform_admins` será su análoga en el plano-plataforma. `users` tiene `uq_users_tenant_email` (email único por-tenant) y `rol` (str 50, default `"agente"`) ya en el esquema (`app/models/user.py`) — hoy **no hay** valor `"admin"` reservado; esta SPEC lo documenta como valor de negocio, no como cambio de esquema. El proyecto usa mixins `Base`/`TimestampMixin`/`SoftDeleteMixin` (`app/db/base.py`); `platform_admins` reutilizará `TimestampMixin`/`SoftDeleteMixin` pero **NO** `TenantMixin` (no lleva `tenant_id`). La migración sigue el patrón Alembic de SPEC-012 (aditivo, con downgrade). El hashing de password es el de SPEC-013 (`app/security/passwords.py`, bcrypt) — esta SPEC solo deja `password_hash` preparada, no la llena (eso es F2/bootstrap).

**Naturaleza aditiva (importante):** la migración solo **añade** una tabla nueva no scoped y no toca `users`/`tenants`/`whatsapp_accounts` ni ninguna tabla existente. `platform_admins` **NO** se añade a `TENANT_SCOPED_TABLES` (no lleva política RLS) — es una decisión de seguridad de ADR-015 (plano-plataforma), no un olvido.

## Alcance

### IN
- **Modelo SQLAlchemy `PlatformAdmin`** (`app/models/platform_admin.py`): `id` (uuid `gen_random_uuid()`, PK), `email` (String 255, **unique global**, index), `password_hash` (String 255, nullable — lo llena el bootstrap F2), `nombre` (String 255), + `TimestampMixin` + `SoftDeleteMixin` (`activo` bool, C2). **Sin `tenant_id`**, **sin `TenantMixin`**.
- **Migración Alembic aditiva** que crea la tabla `platform_admins` (con la constraint `unique(email)` nombrada, p. ej. `uq_platform_admins_email`) y su `downgrade` (drop de tabla). **No** ejecuta `enable_rls_sql` sobre ella; **no** la añade a `TENANT_SCOPED_TABLES`.
- **Verificación explícita** de que `platform_admins` **no** está en `TENANT_SCOPED_TABLES` (`rls.py:43-56`) y de que ninguna política `tenant_isolation_platform_admins` se crea (test/aserto en SPEC-076).
- **Semántica documentada de `rol="admin"`** para el primer usuario del tenant: valor de texto en la columna `rol` existente de `users` (default sigue `"agente"` para el resto); **sin migración de esquema en `users`**, sin nuevo tipo/enum. Documentación en el modelo/docstring + nota para el runbook (SPEC-076).
- **Registro de la tabla** en la metadata/`Base` para que Alembic autogenere/valide y para que el mapeo esté disponible a F2.

### OUT
- ADR-015 (SPEC-073, se consume).
- `tenant_provisioning_service`, guard `require_platform_admin`, endpoint, CLI y bootstrap real que llena `password_hash` (SPEC-075).
- Cualquier política RLS sobre `platform_admins` (por diseño no lleva, ADR-015).
- Gestión de más usuarios/roles finos del tenant (OUT del plan).
- Pruebas e2e/seguridad/no-regresión y runbook (SPEC-076).

## Dependencias
- Depende de **SPEC-073/ADR-015** (puerta de diseño: define `platform_admins` separado y la semántica de `rol="admin"`). Reutiliza SPEC-012 (`Base`/mixins, patrón de migración RLS, `rls.py`), SPEC-013 (`password_hash` bcrypt, se prepara). **Prerequisito de SPEC-075** (el servicio necesita la tabla y el modelo).

## Requisitos funcionales
- RF-01 Existe el modelo `PlatformAdmin` con `id`, `email` (unique global, index), `password_hash` (nullable), `nombre`, `activo` + timestamps, **sin `tenant_id`**.
- RF-02 Existe una migración Alembic **aditiva** que crea `platform_admins` con `unique(email)` nombrada y su `downgrade` (drop), sin tocar tablas existentes.
- RF-03 `platform_admins` **NO** está en `TENANT_SCOPED_TABLES` y **NO** tiene política RLS por fila (verificable).
- RF-04 La semántica de `rol="admin"` para el primer usuario del tenant queda documentada; la columna `rol` de `users` **no** cambia de esquema (default sigue `"agente"`).
- RF-05 La migración es reversible (`downgrade` limpia `platform_admins`) y no ejecuta backfill destructivo.

## Requisitos no funcionales
- RNF-ADITIVO Cero impacto en tenants/usuarios existentes: `GET /tenants/me`, login (SPEC-013), seed y fases #1–#6 intactos tras la migración (R-94).
- RNF-C3 `password_hash` preparada para bcrypt (SPEC-013); ningún secreto/valor por defecto de password en la migración ni en el modelo.
- RNF-C2 `platform_admins` lleva borrado lógico (`activo`); no se borra físicamente.
- RNF-COHERENCIA El modelo/migración es coherente con ADR-015 (no scoped, sin RLS) y con el patrón de SPEC-012.

## Criterios de aceptación (verificables)
- [ ] Existe `app/models/platform_admin.py` con `PlatformAdmin` (id, email unique global+index, password_hash nullable, nombre, activo, timestamps; **sin `tenant_id`/`TenantMixin`**).
- [ ] Existe una migración Alembic que crea `platform_admins` con `uq_platform_admins_email` y `downgrade` que la elimina; `alembic upgrade`/`downgrade` corren limpias.
- [ ] `platform_admins` **no** aparece en `TENANT_SCOPED_TABLES` y no existe política `tenant_isolation_platform_admins` (verificado en SPEC-076).
- [ ] La semántica de `rol="admin"` queda documentada; el esquema de `users` **no** cambia (default sigue `"agente"`; sin migración sobre `users`).
- [ ] Tras aplicar la migración, login/`GET /tenants/me`/seed y suites #1–#6 pasan sin modificar asserts (verificado en SPEC-076).
- [ ] No hay backfill destructivo; `downgrade` no deja residuos.

## Notas de seguridad (C2/C3)
- C2: `platform_admins.activo` (borrado lógico); nunca borrado físico. Coherente con `tenants`/`users`.
- C3: `password_hash` nullable preparada para bcrypt (SPEC-013); **ningún** password en claro ni default en migración/modelo; el llenado real es bootstrap F2 con credenciales fuera del código.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (sin egress nuevo): la migración crea la tabla que gobierna quién puede crear la raíz de aislamiento; no introduce ningún dominio/IP externo; `check-externos-backend.sh` sigue verde. `platform_admins` sin RLS es una decisión de plano-plataforma (ADR-015), no una relajación del aislamiento de datos de tenant.

## Riesgos
- R-94 (**regresión de existentes**): migración estrictamente aditiva (tabla nueva no scoped, `users` intacto); suites #1–#6 verdes (verificado en SPEC-076).
- R-95 (secreto en claro): `password_hash` sin valor por defecto; sin credenciales en la migración; hashing bcrypt (SPEC-013) al llenar en F2.
- R-97 (colisión/unicidad): `unique(email)` global en `platform_admins`; la unicidad de slug/email de tenant es de F2.
- Riesgo de diseño: añadir `platform_admins` a `TENANT_SCOPED_TABLES` por error → aserto negativo explícito en SPEC-076 lo detecta.

## Checkpoints aplicables
- C2 (borrado lógico `activo`). C3 (password_hash preparada, sin secretos en migración). C4 (criterios verificables). C6 (cambio sensible → notificación Telegram en deploy de la migración). C8 (origen PLAN-009 / `prompt-lab/prompts/PROMPT-009-ONBOARDING-MULTITENANT.md`).
