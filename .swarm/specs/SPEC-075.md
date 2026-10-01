# SPEC-075 — `tenant_provisioning_service` transaccional (tenant plano-plataforma + primer admin bajo RLS, atómico) + auth/guard `require_platform_admin` (independiente de SPEC-013) + endpoint `POST /platform/tenants` (unicidad slug/email → 409/422, no 500) + CLI interno de alta 🔴 SENSIBLE

- Estado: CERRADA — implementada por CAPTAIN AMERICA (`tenant_provisioning_service`, `platform_auth_service`, guard `require_platform_admin` con distinción 401/403 vía claim `type`, endpoint `POST /platform/tenants`, CLI `provision_tenant`, bootstrap idempotente) y verificada por el orquestador contra Postgres real (sandbox del implementador sin Docker): (a) bootstrap crea `platform_admin` e idempotente sin duplicar; (b) `POST /platform/tenants` con credenciales de plataforma → 201 `{tenant_id, slug}` sin password/hash, tenant+admin persistidos con `rol="admin"` y password hasheado; (c) el admin nuevo se loguea de inmediato por el flujo existente (SPEC-013) → 200, JWT con `tenant_id` y `rol="admin"` correctos; (d) sin credenciales → 401, JWT de tenant normal → 403 (nunca 401, confirma guard independiente); (e) slug/email duplicado → 409, nunca 500; (f) fallo inyectado a mitad del alta (flush) → rollback total, 0 filas huérfanas en `tenants`; `users` confirmado con RLS ENABLE+FORCE (`relrowsecurity=true`, `relforcerowsecurity=true`, sin bypass owner) — invariante top R-89/R-90 verificado directamente contra `pg_class`. Suite completa re-corrida tras la verificación: 719 passed, 11 failed (únicamente el caveat conocido de `test_rag_tts_api.py` + el flake de `test_privacy_api.py`, ambos ya documentados, cero regresión nueva), 1 skipped, 5 deselected (incluye el test `test_check_externos_pasa_en_verde_con_arbol_real`, lento por `grep -r` sobre un `.venv` de 1.2GB, verificado aparte de forma directa: `check-externos-backend.sh` → APROBADO en 96s). Responsable: CAPTAIN AMERICA · Colaboran/revisan: BLACK PANTHER, BLACK WIDOW, HAWKEYE, WOLVERINE · Prioridad: ALTA · Tipo: BACKEND/SERVICIO/API · Fase: F2
- Deriva de: PLAN-009 (F2, §2.IN.2/3/4/5, §3.1, §3.2, §3.3, §3.4, §4, §9, R-89/R-90/R-91/R-92/R-93/R-95/R-96/R-97, CE-88/CE-90/CE-91/CE-92/CE-93) · Clasificación: SENSIBLE (`.no-externo`) · Depende de SPEC-073/074 · Consume ADR-004/ADR-008/SPEC-012/SPEC-013

## Objetivo

Construir el **núcleo técnico** de PLAN-009: un `tenant_provisioning_service` que, en **una sola unidad atómica (todo o nada)**, (a) crea la fila raíz `tenants` (nombre + slug único, `activo=True`) con el **patrón de plataforma** (rol owner, **sin** `app.tenant_id`, como el seed hoy) y (b) fija `set_tenant_session(db, nuevo_tenant.id)` sobre la **MISMA** transacción y crea el **primer usuario `users`** (email normalizado, único por-tenant vía `uq_users_tenant_email`, `password_hash` con el hashing de SPEC-013, `rol="admin"`) **BAJO RLS efectiva** (patrón `auth_service`), **sin bypass genérico owner**. Cualquier fallo → **rollback total** (sin huérfanos). Se protege con un guard **`require_platform_admin`** (autenticación propia del admin de plataforma, **independiente** del login de tenant SPEC-013) y se expone en **`POST /platform/tenants`** con validación tipada y errores **409/422 (nunca 500)** en colisión de slug/email. Se añade un **CLI interno de alta** (mejora segura del seed manual) y el bootstrap del primer admin de plataforma.

## Contexto

Patrones reutilizables verificados en código:
- **Fila raíz `tenants` con patrón de plataforma:** `seed.py:49-62` inserta en `tenants` con el engine directo (rol owner) **sin** `app.tenant_id` — correcto para `tenants` (no scoped). El servicio reutiliza este patrón para el paso (a), añadiendo `nombre` + `slug` (UNIQUE) + `activo=True`.
- **Crear `users` bajo RLS:** `auth_service.authenticate()` (`auth_service.py:75-98`) fija `set_tenant_session(db, tenant.id)` (`session.py:32-60`, vía `set_config(:var,:valor,true)`) **antes** de tocar `users` (scoped, RLS ENABLE+FORCE, `rls.py:44`). El servicio replica exactamente eso para el paso (b): tras insertar `tenants`, fija `app.tenant_id` del **nuevo** tenant en la MISMA sesión/transacción y crea el `user` admin. El rol `omnicore_app` es NOSUPERUSER NOBYPASSRLS (ADR-008): **PROHIBIDO** el bypass owner para `users` (bug recurrente documentado en `retention_service`/`call_retention_service`).
- **Atomicidad:** `session.py` ofrece `SessionLocal`/`tenant_scoped_session`; el servicio abre **una** transacción (`db.begin()`) que cubre INSERT `tenants` + `set_tenant_session` + INSERT `users`, con `commit`/`rollback` únicos.
- **Auth propia:** `deps.py` define `get_current_token`/`get_tenant_db`/`get_current_user` (JWT de tenant, SPEC-013). El guard `require_platform_admin` es **distinto**: valida credenciales de `platform_admins` (SPEC-074) — **no** contamina ni toca el login de tenant. `passwords.py` (bcrypt) se reutiliza para hashear/verificar tanto el `user` admin como el `platform_admin`.
- **Hashing:** `app/security/passwords.py::hash_password`/`verify_password` (bcrypt_sha256) — mismo mecanismo de SPEC-013 para el `user` admin y para `platform_admins`.
- **Endpoint hoy:** `app/api/tenants.py` solo expone `GET /tenants/me` (sin creación ni listado global — comentario explícito de que un listado global sería fuga). Esta SPEC **añade** la creación bajo `/platform/tenants`, **sin** tocar `GET /tenants/me`.

**Invariante de frontera de privilegio (ADR-015 §3.3, NO se relaja):** el **único** INSERT con privilegio elevado es el de la fila raíz `tenants` (no scoped). Todo lo scoped (`users`) se inserta **con `app.tenant_id` fijado**. Verificación negativa: el servicio no crea `users` con una sesión owner sin tenant.

## Alcance

### IN
- **`tenant_provisioning_service`** (`app/services/tenant_provisioning_service.py`) con una función atómica que, en **una sola transacción**:
  1. Normaliza/valida `nombre`, `slug` (formato: minúsculas, guiones, sin espacios; longitud ≤100; **lista de reservados** p. ej. `platform`, `admin`, `api`, `me`) y `admin_email` (normalizado `.strip().lower()`, como en `auth_service`).
  2. INSERT `tenants` (`nombre`, `slug` UNIQUE, `activo=True`) con el patrón de plataforma (sin `app.tenant_id`). Colisión de `slug` (unique global) → excepción tipada de dominio (→ 409).
  3. `set_tenant_session(db, nuevo_tenant.id)` sobre la MISMA sesión/transacción.
  4. INSERT `users` (email normalizado, `password_hash = hash_password(admin_password)`, `nombre`, `rol="admin"`, `activo=True`) **bajo RLS**. Colisión `uq_users_tenant_email` → excepción tipada de dominio (→ 409/422).
  5. `commit` (ambas filas) | cualquier fallo → **rollback total** (0 filas persistidas: ni tenant ni admin).
- **Guard `require_platform_admin`** (`app/api/deps.py` o módulo `app/api/platform_deps.py`) que autentica al admin de plataforma por su **propio** mecanismo (credencial/JWT de plataforma sobre `platform_admins`, `activo=True`), **independiente** de `get_current_user`/`get_tenant_db` (SPEC-013 intacto). Sin credenciales de plataforma → **401**; con un JWT de tenant normal (agente/admin de tenant) → **403**.
- **Endpoint `POST /platform/tenants`** (`app/api/platform.py`) protegido por `require_platform_admin`, con:
  - Entrada tipada (schema Pydantic): `nombre`, `slug`, `admin_email`, `admin_password`, `admin_nombre`.
  - Respuesta **201** `{ tenant_id, slug }` (sin exponer el password ni el hash).
  - Errores **tipados**: colisión de slug (global) o email (por-tenant) → **409**; validación de formato (slug inválido/reservado, email/campos mal formados, password corta) → **422**. **Nunca 500** por colisión/validación.
- **CLI interno de alta** (`app/db/provision_tenant.py` o comando `python -m ...`) que invoca el mismo servicio (mejora segura del seed manual): da de alta un tenant + primer admin sin ejecutar SQL a mano; credenciales por argumento/env (C3), nunca hardcodeadas.
- **Bootstrap del primer admin de plataforma** (seed/CLI de plataforma, `app/db/bootstrap_platform_admin.py` o extensión del seed): crea un `platform_admins` con `password_hash` bcrypt a partir de credenciales **fuera del código** (env/secreto, C3), idempotente (`ON CONFLICT (email) DO NOTHING` o equivalente). Mismo plano que el seed de `tenants`.
- **Registro del router** `platform` en la app (sin tocar el router `tenants` existente).

### OUT
- ADR-015 (SPEC-073) y modelo/migración de `platform_admins` + semántica `rol` (SPEC-074) — se consumen aquí.
- Pruebas e2e/seguridad/no-regresión y runbook (SPEC-076).
- UI/pantalla de alta en la SPA (OUT por defecto, PLAN-009 §3.5).
- Conectar canal WhatsApp, verificación de email/SMTP, planes/cuotas/billing, gestión de más usuarios/roles finos, baja/offboarding, migración de tenants existentes (todo OUT, PLAN-009 §2).
- Cambios en `auth_service`/login de tenant salvo el guard reutilizable `require_platform_admin` que **no** altera SPEC-013.
- Cualquier egress nuevo.

## Dependencias
- Depende de **SPEC-073/ADR-015** (frontera de privilegio, atomicidad, mecanismo del admin de plataforma) y **SPEC-074** (tabla `platform_admins` + `rol="admin"`). Reutiliza `session.py::set_tenant_session`, `seed.py` (patrón plataforma), `auth_service` (patrón de creación bajo RLS), `passwords.py` (bcrypt), `deps.py` (patrón de guard). Consume ADR-004/ADR-008 (RLS efectiva) sin rediseño. **Prerequisito de SPEC-076.**

## Requisitos funcionales
- RF-01 El servicio crea, en **una sola transacción atómica**, la fila raíz `tenants` (patrón plataforma, sin `app.tenant_id`) y el primer `user` admin (bajo RLS con `app.tenant_id` fijado); commit único; cualquier fallo → rollback total sin huérfanos.
- RF-02 El `user` admin se crea **siempre** con `set_tenant_session(db, nuevo_tenant.id)` fijado (patrón `auth_service`), **nunca** con sesión owner sin tenant (invariante verificable).
- RF-03 El `user` admin nace con `rol="admin"`, email normalizado (`.strip().lower()`), `password_hash` bcrypt (SPEC-013), `activo=True`.
- RF-04 El endpoint `POST /platform/tenants` solo es alcanzable por un admin de plataforma autenticado (`require_platform_admin`); sin credenciales → 401; con JWT de tenant → 403.
- RF-05 Colisión de slug (global) → 409; colisión de email por-tenant → 409/422; formato inválido (slug reservado/mal formado, email/campos inválidos, password corta) → 422. **Nunca 500.**
- RF-06 Respuesta 201 `{ tenant_id, slug }` sin exponer password ni hash; el primer admin puede loguearse de inmediato por el flujo existente (SPEC-013, sin cambios).
- RF-07 Existe un CLI interno que da de alta tenant + primer admin vía el mismo servicio (sin SQL manual), con credenciales por argumento/env.
- RF-08 Existe bootstrap del primer admin de plataforma por seed/CLI (credenciales fuera del código, idempotente).

## Requisitos no funcionales
- RNF-RLS El primer `user` admin vive bajo RLS efectiva (rol `omnicore_app` NOSUPERUSER NOBYPASSRLS, ADR-008); el privilegio elevado se limita a la fila raíz `tenants`; **prohibido** bypass genérico owner para `users` (R-90).
- RNF-ATOMIC Atomicidad todo-o-nada: ambas filas en la misma transacción; fallo → rollback total (R-91).
- RNF-TIPADO Errores de unicidad/validación **tipados** (409/422), nunca 500; sin filtrar detalle interno (R-93).
- RNF-C3 Passwords hasheados (bcrypt, SPEC-013) para `user` admin y `platform_admins`; cero secretos en logs/respuesta; credenciales de bootstrap/CLI fuera del código (R-95/R-96).
- RNF-AISLAMIENTO-AUTH La auth del admin de plataforma es independiente del login de tenant (SPEC-013 intacto); no contamina `auth_service`/`get_current_user`.
- RNF-NO-EGRESS Sin egress nuevo: sin IA externa, SMTP ni Meta; `graph.facebook.com` (ADR-006) no se toca; `check-externos-backend.sh` verde.

## Criterios de aceptación (verificables)
- [ ] `POST /platform/tenants` con credenciales de admin de plataforma → 201 `{ tenant_id, slug }`; tenant + primer admin (`rol="admin"`) persistidos (CE-88).
- [ ] El primer admin se loguea de inmediato por el flujo existente (`tenant_slug`+email+password, SPEC-013) → 200 con JWT (`tenant_id` correcto, `rol="admin"`) (CE-90; test detallado en SPEC-076).
- [ ] El `user` admin se crea con `app.tenant_id` fijado (no con sesión owner); el privilegio elevado se limita a la fila raíz `tenants` (CE-91; verificado en SPEC-076).
- [ ] Sin credenciales de plataforma → 401; con JWT de agente/admin de un tenant → 403; solo admin de plataforma → 201 (CE-92).
- [ ] Colisión de slug (global) o email (por-tenant) → 409/422 (**nunca 500**); fallo inyectado a mitad del alta → rollback total, 0 filas (CE-93; tests en SPEC-076).
- [ ] La respuesta y los logs no exponen el password ni el hash; `password_hash` presente y hasheado (bcrypt).
- [ ] El CLI interno da de alta tenant + primer admin sin SQL manual; el bootstrap del primer admin de plataforma corre con credenciales fuera del código, idempotente.
- [ ] `GET /tenants/me` y el login de tenant (SPEC-013) quedan intactos; `check-externos-backend.sh` verde.

## Notas de seguridad (C2/C3)
- C2: `tenants.activo` y `users.activo` = True al crear; borrado lógico respetado (la baja es OUT, otra fase).
- C3: passwords hasheados con bcrypt (SPEC-013) para el `user` admin y `platform_admins`; token/credencial de plataforma nunca en logs; la respuesta 201 no incluye password ni hash; credenciales de CLI/bootstrap por env/argumento, nunca hardcodeadas.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (sin egress nuevo): el servicio crea la raíz de aislamiento (`tenants`) y el primer admin bajo RLS. La **única** operación con privilegio elevado es el INSERT en la fila raíz `tenants` (no scoped, como el seed); `users` siempre bajo RLS. No hay llamada a IA externa/SMTP/Meta; `graph.facebook.com` (ADR-006) no se toca; ningún dominio/IP nuevo. `check-externos-backend.sh` en verde.

## Riesgos
- R-89 (**fuga cross-tenant en el alta**): el `user` admin se crea bajo RLS con `app.tenant_id` fijado (patrón `auth_service`); RLS no se rediseña; test cross-tenant en SPEC-076. **Top.**
- R-90 (**bypass owner para `users`**): prohibido por diseño; privilegio elevado solo para `tenants`; test de cero bypass en SPEC-076. **Top.**
- R-92 (**superficie de abuso del endpoint**): `require_platform_admin` independiente de SPEC-013; sin credenciales → 401, JWT de tenant → 403; alta interna (no pública) → superficie mínima; bootstrap por seed/CLI. **Top.**
- R-91 (huérfanos): atomicidad todo-o-nada; rollback total ante fallo (test de fallo inyectado, SPEC-076).
- R-93 (colisión sin manejo tipado → 500): validación previa + captura tipada de `unique(slug)`/`uq_users_tenant_email` → 409/422; nunca 500.
- R-95 (secreto en claro): bcrypt (SPEC-013); cero secretos en logs/respuesta.
- R-96 (bootstrap huevo-gallina): seed/CLI de plataforma, credenciales fuera del código.
- R-97 (slug inválido/reservado o colisión con seed `clinica-demo-norte/sur`): validación de formato + reservados + unicidad global; convive con los slugs del seed (ON CONFLICT es el patrón).

## Checkpoints aplicables
- C2 (borrado lógico `activo`). C3 (passwords hasheados, cero secretos, credenciales fuera del código). C4 (criterios verificables). C6 (servicio sensible que crea la raíz de aislamiento → notificación Telegram en deploy). C8 (origen PLAN-009 / `prompt-lab/prompts/PROMPT-009-ONBOARDING-MULTITENANT.md`).
