# SPEC-076 — Pruebas + seguridad + docs/runbook + no-regresión del alta de tenant: aislamiento cross-tenant, atomicidad, unicidad tipada, cero bypass RLS, protección del endpoint, passwords hasheados, cero regresión #1–#6, runbook del alta + bootstrap del admin de plataforma + nota de deprecación del seed, cobertura ≥80% 🔴 SENSIBLE

- Estado: CERRADA — cierra el slice completo de PLAN-009. HAWKEYE escribió `tests/test_platform_provisioning.py` + `tests/test_platform_api.py` + `tests/test_platform_cli_and_bootstrap.py` (62 tests) cubriendo aislamiento cross-tenant (RF-01), atomicidad por fallo inyectado (RF-02, dos rutas: `set_tenant_session` y `db.flush`), unicidad tipada 409/422 nunca 500 (RF-03), cero bypass RLS verificado por orden de llamadas instrumentado + SQL directo (RF-04), protección del endpoint 401/403/201 (RF-05), login inmediato del admin nuevo vía flujo existente SPEC-013 (RF-06), secretos nunca expuestos + hash bcrypt (RF-07), aserto de modelo `platform_admins` sin RLS/sin política (RF-08) y contrato del CLI/bootstrap (RF-10). QUICKSILVER añadió la sección "Onboarding multi-tenant (PLAN-009)" a `RUNBOOK.md` (alta vía API+CLI, bootstrap del admin de plataforma, nota de deprecación de `seed.py` para producción, troubleshooting). El orquestador verificó ambas entregas contra Postgres real y corrigió 3 imprecisiones antes de cerrar: (1) runbook decía que `POST /platform/auth/login` devuelve 201, el código no fija `status_code` → es 200; (2) runbook usaba `jq '.data | length'` contra `GET /contacts`, pero `Page[T]` expone `items`, no `data`; (3) un test parametrizado de HAWKEYE esperaba que un slug con mayúsculas (sin otros defectos) lanzara `InvalidSlugError`, pero `_normalizar_slug` hace `.strip().lower()` ANTES de validar (mismo criterio que `admin_email`, documentado en el propio docstring del servicio) — comportamiento de producción deliberado, no un bug; se corrigió el test y se documentó el contrato explícitamente, y se corrigieron las 3 menciones equivalentes en el runbook ("mayúsculas" no es la causa real del 422, el espacio/underscore/guion sí). Cobertura real medida contra Postgres: 93% combinado (`platform_deps.py` 100%, `tenant_provisioning_service.py` 98%, `bootstrap_platform_admin.py` 97%, `platform.py`/`provision_tenant.py` 90%, `platform_auth_service.py` 84% tras añadir tests directos de `authenticate_platform_admin` que HAWKEYE no cubrió inicialmente — todos ≥80%, RNF-COBERTURA cumplido). Suite completa re-corrida: 781 passed, 11 failed (únicamente el caveat ya documentado de `test_rag_tts_api.py` y el flake de `test_privacy_api.py`, cero regresión nueva), 1 skipped, 5 deselected. `check-externos-backend.sh` verde. PLAN-009 queda completo (SPEC-073/074/075/076 todas CERRADA). · Responsable: HAWKEYE · Colaboran/revisan: BLACK WIDOW, WOLVERINE, QUICKSILVER, BLACK PANTHER, CAPTAIN AMERICA · Prioridad: ALTA · Tipo: PRUEBAS/SEGURIDAD/DOCS · Fase: F3
- Deriva de: PLAN-009 (F3, §2.IN.6/7, §3.1–§3.4, §4, §5, §9, §10, R-89..R-97, CE-88..CE-94) · Clasificación: SENSIBLE (`.no-externo`) · Depende de SPEC-073/074/075 · Consume ADR-004/ADR-008/ADR-015/SPEC-012/SPEC-013

## Objetivo

Verificar y cerrar el slice de alta de tenant de PLAN-009 con una suite de **pruebas + seguridad + no-regresión** y el **runbook** operativo. Debe demostrar, de forma objetiva y auditable: (1) **aislamiento cross-tenant** del tenant recién creado (no ve ni es visto por otros); (2) **atomicidad** (fallo inyectado → 0 filas, sin huérfanos); (3) **unicidad tipada** (slug/email → 409/422, **nunca 500**); (4) **cero bypass RLS** (el `user` admin nunca se crea con sesión owner); (5) **protección del endpoint** (sin credenciales de plataforma → 401/403; JWT de tenant → 403); (6) **passwords hasheados + cero secretos en logs** (C3); (7) **cero regresión** de login/`GET /tenants/me`/seed/fases #1–#6 (suites existentes sin modificar asserts); (8) **cobertura ≥80%** del código nuevo; y (9) el **runbook** del nuevo flujo de alta + bootstrap del admin de plataforma + nota explícita de que el seed queda solo para demo/pruebas (el alta de producción real usa el flujo nuevo, decisión ya confirmada por el Lead, PLAN-009 §12.4).

## Contexto

Patrón de test de aislamiento existente: `tests/test_rls_isolation.py` fija `app.tenant_id` de sesión y verifica 0 filas cruzadas — esta SPEC lo reutiliza para el tenant recién provisionado. La atomicidad se apoya en la transacción única de `tenant_provisioning_service` (SPEC-075): un fallo inyectado (p. ej. violar `uq_users_tenant_email` a propósito, o forzar excepción tras el INSERT de `tenants`) debe dejar **0 filas** (ni tenant ni admin). El guard `require_platform_admin` (SPEC-075) es independiente de SPEC-013: los tests negativos usan (a) sin credenciales, (b) JWT de agente/admin de un tenant, (c) admin de plataforma válido. El bug recurrente de bypass owner (`retention_service`/`call_retention_service`) es la referencia para el test de "cero bypass": el `user` admin debe crearse con `app.tenant_id` fijado. `check-externos-backend.sh` debe seguir verde (sin egress nuevo). El runbook sigue el patrón de SPEC-061/072 (documentación de flujo + bootstrap + nota operativa).

**F3 fusiona pruebas+seguridad+docs** (PLAN-009 §4/§8): el alcance es acotado (un servicio + un endpoint + una tabla), el grueso es seguridad/pruebas y el runbook es breve (sin deploy de infra nueva ni motor a documentar).

## Alcance

### IN
- **Test de aislamiento cross-tenant obligatorio** (patrón `tests/test_rls_isolation.py`): se provisiona un tenant nuevo; fijando `app.tenant_id` de **otro** tenant se verifica **0 filas** del nuevo (`users`/datos scoped); el tenant nuevo no ve ni es visto por otros (CE-89).
- **Test de atomicidad**: fallo inyectado a mitad del alta (violar `uq_users_tenant_email`; forzar excepción tras INSERT `tenants`) → **rollback total**, 0 filas persistidas (ni tenant huérfano ni admin huérfano) (CE-93/R-91).
- **Test de unicidad tipada**: slug duplicado (global) → **409**; email duplicado por-tenant → **409/422**; slug reservado/mal formado, email/campos inválidos, password corta → **422**. **Ningún 500** en colisión/validación (CE-93/R-93).
- **Test de cero bypass RLS**: el `user` admin se crea **con `app.tenant_id` fijado** (patrón `auth_service`), **no** con sesión owner; el privilegio elevado se limita a la fila raíz `tenants`; verificación de que el servicio no inserta `users` con una sesión sin tenant (CE-91/R-90).
- **Test de protección del endpoint** (superficie de abuso, R-92): sin credenciales de plataforma → **401**; con JWT de agente/admin de un **tenant** → **403**; con admin de plataforma válido → **201** (CE-92).
- **Test de login inmediato** (activación inmediata, Q3-A): alta → login del primer admin por el flujo existente (SPEC-013) → **200** con JWT (`tenant_id` correcto, `rol="admin"`) (CE-90).
- **Test de secretos seguros (C3)**: la respuesta 201 y los logs **no** exponen el password ni el hash; `password_hash` presente y hasheado (bcrypt); credenciales de CLI/bootstrap por env/argumento (R-95).
- **Aserto de modelo (SPEC-074)**: `platform_admins` **no** está en `TENANT_SCOPED_TABLES` y **no** tiene política `tenant_isolation_platform_admins` (decisión de ADR-015, no olvido).
- **Cero regresión #1–#6**: suites existentes de login, `GET /tenants/me`, seed y fases #1–#6 pasan **sin modificar asserts** (CE-94/R-94); `check-externos-backend.sh` verde.
- **Verificación de alcance acotado (OUT)**: no aparece implementado canal WhatsApp en el alta, verificación de email/SMTP, planes/billing, UI, ni autoregistro público (CE-94).
- **Cobertura ≥80%** del código nuevo (servicio, guard, endpoint, CLI, bootstrap).
- **Runbook** (`docs/` o `backend/docs/`): (a) cómo un admin de plataforma da de alta una sede vía API (`POST /platform/tenants`) y vía CLI interno; (b) cómo se crea/gestiona el **primer admin de plataforma** (bootstrap por seed/CLI, credenciales fuera del código); (c) **nota explícita**: el seed/SQL queda **solo para demo/pruebas**; el alta de producción real usa el flujo nuevo (decisión confirmada por el Lead, PLAN-009 §12.4).

### OUT
- ADR-015 (SPEC-073), modelo/migración (SPEC-074), servicio/endpoint/CLI/bootstrap (SPEC-075) — se prueban aquí, no se implementan.
- UI/pantalla de alta, canal WhatsApp, verificación email, planes/billing, baja/offboarding, migración de tenants existentes (OUT del plan).
- Rediseño de RLS o del login de tenant (se consumen intactos).
- Cualquier egress nuevo.

## Dependencias
- Depende de **SPEC-073/074/075** (prueba el slice completo). Reutiliza `tests/test_rls_isolation.py` (patrón de aislamiento), `auth_service`/`deps` (login de tenant para el test de login inmediato), `passwords.py` (verificación de hash), `check-externos-backend.sh` (egress). Consume ADR-004/ADR-008/ADR-015. **Cierra el slice** (DoD PLAN-009 §10).

## Requisitos funcionales
- RF-01 Test cross-tenant: el tenant recién provisionado está aislado por RLS (0 filas cruzadas fijando `app.tenant_id` de otro tenant).
- RF-02 Test de atomicidad: fallo inyectado → rollback total, 0 filas (sin tenant/admin huérfanos).
- RF-03 Test de unicidad: slug (global)/email (por-tenant) → 409/422; slug reservado/inválido, campos/password inválidos → 422; nunca 500.
- RF-04 Test de cero bypass RLS: el `user` admin se crea con `app.tenant_id` fijado, no con owner.
- RF-05 Test de protección: sin credenciales → 401; JWT de tenant → 403; admin de plataforma → 201.
- RF-06 Test de login inmediato: alta → login del primer admin (SPEC-013) → 200, `rol="admin"`.
- RF-07 Test de secretos: respuesta/logs sin password/hash; hash bcrypt presente.
- RF-08 Aserto: `platform_admins` no scoped/sin RLS.
- RF-09 Cero regresión #1–#6 (suites verdes sin modificar asserts); `check-externos-backend.sh` verde; alcance OUT no implementado.
- RF-10 Runbook con flujo de alta (API+CLI), bootstrap del admin de plataforma y nota de deprecación del seed para producción.

## Requisitos no funcionales
- RNF-COBERTURA Cobertura del código nuevo ≥80%.
- RNF-AISLAMIENTO Los tests corren bajo RLS efectiva (rol app no-superusuario, ADR-008); ningún test relaja RLS para "hacer pasar" el alta.
- RNF-C3 Ningún test/fixture/runbook contiene secretos ni PII real; datos ficticios; passwords de prueba no reales.
- RNF-NO-EGRESS Los tests no introducen egress; `check-externos-backend.sh` verde; el alta no alcanza IA externa/SMTP/Meta.
- RNF-REPRO La suite es reproducible contra Postgres real (patrón `tests/test_rls_isolation.py`).

## Criterios de aceptación (verificables)
- [ ] Test cross-tenant: el tenant nuevo no ve ni es visto por otros (0 filas fijando `app.tenant_id` cruzado) (CE-89).
- [ ] Test de atomicidad: fallo inyectado → 0 filas (sin huérfanos) (CE-93).
- [ ] Test de unicidad: slug/email duplicados → 409/422; slug reservado/inválido → 422; **ningún 500** (CE-93).
- [ ] Test de cero bypass RLS: `users` se inserta con `app.tenant_id` fijado, no con owner; privilegio elevado solo para `tenants` (CE-91).
- [ ] Test de protección: sin credenciales → 401; JWT de tenant → 403; admin de plataforma → 201 (CE-92).
- [ ] Test de login inmediato: alta → login del primer admin (SPEC-013) → 200, `tenant_id` correcto, `rol="admin"` (CE-90).
- [ ] Test de secretos: respuesta/logs sin password/hash; `password_hash` bcrypt presente (CE-91/C3).
- [ ] Aserto: `platform_admins` no está en `TENANT_SCOPED_TABLES` y no tiene política RLS.
- [ ] Suites #1–#6 (login, `GET /tenants/me`, seed) verdes sin modificar asserts; `check-externos-backend.sh` verde; OUT no implementado (CE-94).
- [ ] Cobertura del código nuevo ≥80%.
- [ ] Runbook con: alta vía API+CLI, bootstrap del admin de plataforma, y nota explícita de que el seed queda solo para demo/pruebas (alta de producción = flujo nuevo).

## Notas de seguridad (C2/C3)
- C2: los tests respetan borrado lógico (`activo`); no borran físicamente; el runbook nota que la baja/offboarding es otra fase.
- C3: sin secretos/PII real en tests/fixtures/runbook; passwords de prueba ficticios; credenciales de bootstrap por env; ningún hash/secreto en logs o en el runbook.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (sin egress nuevo): la suite prueba la creación de la raíz de aislamiento sin introducir ningún dominio/IP externo; `graph.facebook.com` (ADR-006) no se toca; `check-externos-backend.sh` en verde. El test de aislamiento cross-tenant es la evidencia central de que el tenant nuevo queda aislado desde el primer commit.

## Riesgos
- R-89 (**fuga cross-tenant**): test cross-tenant obligatorio (patrón `tests/test_rls_isolation.py`) es la puerta de evidencia. **Top.**
- R-92 (**superficie de abuso del endpoint**): tests negativos (sin credenciales/JWT de tenant → 401/403). **Top.**
- R-90 (**bypass owner**): test de cero bypass (el `user` admin con `app.tenant_id` fijado). **Top.**
- R-91 (huérfanos): test de fallo inyectado → rollback total.
- R-93 (colisión sin manejo tipado): tests de slug/email → 409/422, nunca 500.
- R-94 (regresión #1–#6): suites existentes verdes sin modificar asserts.
- R-95 (secreto en claro): test de que respuesta/logs no exponen password/hash.

## Checkpoints aplicables
- C2 (borrado lógico respetado en tests/runbook). C3 (sin secretos/PII; passwords hasheados verificados). C4 (criterios verificables). C6 (cierre de cambio sensible → notificación Telegram en deploy). C8 (origen PLAN-009 / `prompt-lab/prompts/PROMPT-009-ONBOARDING-MULTITENANT.md`).
