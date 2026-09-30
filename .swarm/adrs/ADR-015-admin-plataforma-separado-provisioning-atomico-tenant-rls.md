# ADR-015 — Mecanismo del "admin de plataforma" y provisioning atómico de tenant + primer admin respetando la RLS efectiva

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-009.md` (§1, §2 IN/OUT, §3.2, §3.3, §3.4, §4 F0, §11, Q1–Q4 §1.24, R-89/R-90/R-91/R-92/R-95/R-96, CE-88/CE-89/CE-91/CE-92/CE-93), `SPEC-073`, `SPEC-074`, `SPEC-075`, `SPEC-076`

- **Estado:** Aceptada — APROBADA por el Lead (bloque PLAN-009, 2026-09-30).
- **Fecha:** 2026-09-30
- **Plan:** PLAN-009

---

## Contexto

El alta de un tenant nuevo (sede) es hoy 100% manual: se ejecuta `backend/app/db/seed.py` (o SQL equivalente) con el **rol owner** de la BD, sin `app.tenant_id` fijado (`seed.py:49-62`) — patrón correcto para la fila raíz `tenants`, que **no** es tenant-scoped (no lleva `tenant_id`, no está en `TENANT_SCOPED_TABLES`, `rls.py:37-40,43-56`). No existe ningún flujo administrativo que dé de alta una sede + su primer usuario administrador de forma controlada, atómica y auditable; tampoco existe el concepto de "admin de plataforma".

PLAN-009 (caso de uso confirmado por el Lead, §7.1: **grupo de clínicas multi-sede**, NO SaaS externo) requiere: (a) que un actor interno de confianza cree un tenant nuevo (nombre + slug único) junto con su **primer usuario admin** (email único por-tenant, password hasheado, `rol="admin"`) en **una sola operación atómica**; (b) que ese admin pueda loguearse de inmediato con el flujo existente (SPEC-013); (c) que el tenant quede **aislado por RLS desde el primer commit**, reutilizando ADR-004 (RLS pool-model) y ADR-008 (rol `omnicore_app` NOSUPERUSER NOBYPASSRLS + SECURITY DEFINER) **sin rediseñarlos**.

Decisiones del Lead ya **VINCULANTES** (PLAN-009 §1, Q1–Q4, no se reabren): alta **administrativa interna** (sin autoregistro público, Q1-B); tenant **sin canal WhatsApp** en el alta (Q2-A); **activación inmediata** sin verificación de email/SMTP (Q3-A → sin egress nuevo); **binario sin planes/cuotas/billing** (Q4-A). XAVIER dejó **explícitamente a DOCTOR STRANGE** el punto de diseño central: cómo se introduce el "admin de plataforma" (hoy inexistente) y cómo el provisioning respeta la RLS efectiva. Esta ADR lo resuelve.

Contexto de código verificado (fuente de verdad, no asunciones):
- `tenants` (`app/models/tenant.py`): `id` (uuid `gen_random_uuid()`), `nombre` (255), `slug` (100, **UNIQUE**, index) + `TimestampMixin`/`SoftDeleteMixin` (`activo`, C2). Raíz del aislamiento, **sin `tenant_id`**, **NO** en `TENANT_SCOPED_TABLES`.
- `users` (`app/models/user.py`): tabla scoped con RLS ENABLE+FORCE (`rls.py:44`); `email` (255), `nombre`, `password_hash` (nullable, lo llena SPEC-013), `rol` (str 50, **default `"agente"`**), constraint **`uq_users_tenant_email`** (email único **por-tenant**, ya existe).
- `auth_service.authenticate()` (`auth_service.py:75-98`) ya usa el patrón que reutilizará el provisioning: resuelve el tenant por slug con la sesión de plataforma (sin tenant fijado) y **luego fija `set_tenant_session(db, tenant.id)`** para leer/escribir `users` **bajo RLS efectiva**.
- `set_tenant_session` (`app/db/session.py:32-60`) usa `set_config(:var, :valor, true)` (equivalente a `SET LOCAL`, scoped a la transacción) — permite fijar `app.tenant_id` sobre la **misma** conexión/transacción tras el INSERT de `tenants`.
- El bug recurrente de bypass genérico con rol owner (documentado en `retention_service`/`call_retention_service`) está **PROHIBIDO** para insertar en tablas scoped.

Esta fase **NO introduce egress nuevo**: no llama a IA externa, ni a SMTP (Q3-A), ni a Meta (tenant sin canal, Q2-A). El único transporte externo del proyecto (`graph.facebook.com`, ADR-006) **no se toca**; `check-externos-backend.sh` debe seguir verde. Por eso esta ADR **no** es un ADR de egress (a diferencia de ADR-006/ADR-010).

---

## Decisión

1. **El "admin de plataforma" es un concepto SEPARADO, fuera del modelo tenant-scoped: tabla `platform_admins`.** Se crea una tabla nueva `platform_admins` **sin `tenant_id`**, **NO** incluida en `TENANT_SCOPED_TABLES`, **sin política RLS por fila** — análoga a `tenants` (plano-plataforma). Tiene su propio `email` (único global), `password_hash` (reutiliza el hashing de SPEC-013, `app/security/passwords.py` bcrypt), `nombre`, `activo` (C2) + timestamps. Su autenticación/autorización es **independiente** del login de tenant (SPEC-013): un guard `require_platform_admin` distinto del JWT de tenant. Se **descarta** la Opción A (rol especial dentro de `users`, ver §Alternativas).

2. **Frontera de privilegio explícita e invariante (NO se relaja).** Existen dos planos, ya mantenidos deliberadamente separados por el proyecto:
   - **Plano de plataforma** (sin `app.tenant_id`, como el seed hoy): la fila raíz `tenants` y la tabla `platform_admins` (ambas no scoped). El `INSERT` en `tenants` es la **única** operación con **privilegio elevado acotado** (patrón seed, `seed.py:49-62`).
   - **Plano de tenant** (RLS efectiva, `app.tenant_id` fijado, rol `omnicore_app` NOSUPERUSER NOBYPASSRLS, ADR-008): el **primer `user` admin** del tenant se crea **AQUÍ**, bajo RLS, con `set_tenant_session(db, nuevo_tenant.id)` fijado (patrón `auth_service`). **PROHIBIDO** el bypass genérico con rol owner para insertar en `users` (restricción dura, R-90).

3. **Atomicidad tenant + admin en una sola transacción (todo o nada, nunca huérfanos).** El alta es **una única unidad atómica** sobre la misma sesión/conexión de BD: (a) `INSERT tenants` (plano-plataforma, sin `app.tenant_id`); (b) `set_tenant_session(db, nuevo_tenant.id)` sobre la MISMA transacción; (c) `INSERT users` (bajo RLS, `rol="admin"`, `password_hash` vía SPEC-013). El `commit`/`rollback` cubre **ambas** filas. Cualquier fallo (p. ej. violación de `uq_users_tenant_email` o de `unique(slug)`) → **rollback total**: ni tenant ni admin quedan persistidos. Nunca un tenant sin admin ni un admin sin tenant.

4. **Bootstrap del primer admin de plataforma por seed/CLI (no por autoregistro).** El "huevo-gallina" (¿quién crea al primer admin de plataforma?) se resuelve por **seed/CLI de plataforma** — mismo plano que el seed de `tenants` hoy —, con credenciales iniciales **fuera del código** (env/secreto, C3). No hay autoregistro de admin de plataforma (coherente con Q1-B: sin autoregistro público). Se documenta en el runbook (SPEC-076).

5. **Semántica de `rol="admin"` para el primer usuario del tenant.** El primer usuario del tenant nace con `rol="admin"` (hoy el default de `users.rol` es `"agente"`). Es un **valor de texto en la columna `rol` existente**, **sin cambio de esquema** en `users`. Denota al administrador inicial de la sede (quien podrá, en fases futuras OUT, gestionar más usuarios/roles finos). La gestión posterior de usuarios/roles finos del tenant es **OUT** de esta fase.

**Esta ADR consume, no rediseña, ADR-004 (RLS pool-model) y ADR-008 (roles BD + RLS efectiva).** El aislamiento de datos ya funciona y está probado (`tests/test_rls_isolation.py`); esta fase construye el flujo de alta encima de él.

---

## Alternativas consideradas

| Alternativa | Por qué se descartó |
| ----------- | ------------------- |
| **Opción A — Rol especial `rol="platform_admin"` dentro de `users`** (en un usuario de un "tenant de control") | `users` es tenant-scoped con RLS ENABLE+FORCE: un actor que debe operar **por encima de todos los tenants** encaja mal en una tabla cuya invariante es "solo ves tu tenant". Autorizar el alta requeriría **saltarse o ampliar RLS** para ese rol (justo el bypass PROHIBIDO, R-90) o inventar un "tenant de control" artificial. **Mezcla dos planos** que el proyecto mantiene separados a propósito (`tenants`/`platform_admins` fuera de `TENANT_SCOPED_TABLES`; `rls.py:37-40`). Aumenta la superficie de error de aislamiento. Descartada a favor de `platform_admins` separado (Opción B). |
| **Bypass genérico con rol owner para crear el `user` admin** | Rompe la invariante dura de aislamiento (ADR-004/ADR-008); es el bug recurrente ya documentado (`retention_service`/`call_retention_service`). El privilegio elevado se limita a la fila raíz `tenants` (no scoped); `users` se inserta **siempre** con `app.tenant_id` fijado. Descartada (R-90, restricción dura). |
| **Autoregistro público / formulario abierto de alta de tenant** (Q1-A) | Descartada por decisión vinculante del Lead (Q1-B): el alta es **administrativa interna**, no self-service. Un endpoint abierto sería una superficie de abuso (creación no autorizada de tenants, R-92). |
| **Verificación de email / activación diferida del primer admin** (Q3-B/C) | Descartada por decisión vinculante del Lead (Q3-A, activación inmediata): quien crea el tenant es de confianza. Añadiría dependencia de SMTP → **egress nuevo** por correo, contrario al alcance sin egress de esta fase. |
| **Persistir/gestionar planes, cuotas o límites en el alta** (Q4-B) | Descartada por Q4-A (binario, sin límites): no hay modelo de datos de plan ni enforcement. Fuera de alcance. |
| **Conectar el canal WhatsApp en el alta** (Q2-B/C) | Descartada por Q2-A: el tenant se crea SIN canal (`whatsapp_accounts` es fase posterior). Mantiene el alcance limpio y sin arrastrar credenciales de Meta. |

---

## Consecuencias

**Pros**
- Respeta la **separación ya vigente** plano-plataforma (gestiona `tenants`) / plano-tenant (RLS): `platform_admins` sin RLS es coherente con `tenants` sin RLS; el `user` admin bajo RLS es coherente con el resto de `users`.
- **Cero bypass RLS:** el privilegio elevado se limita a la fila raíz `tenants` (como el seed); todo lo scoped (`users`) respeta RLS. No se toca ni amplía la RLS de `users`.
- La autenticación de plataforma es **independiente** del login de tenant → **cero regresión** de SPEC-013; superficie de abuso mínima (solo credenciales de plataforma pueden crear tenants, R-92).
- **Atomicidad todo-o-nada** → nunca tenant/admin huérfanos (R-91).
- Todo es **aditivo**: `platform_admins` es tabla nueva; migración nullable/aditiva; `GET /tenants/me`, seed y fases #1–#6 intactos (R-94). **Sin egress nuevo** (Q2-A/Q3-A).
- El tenant queda **aislado desde el primer commit** reutilizando ADR-004/ADR-008 sin rediseño (R-89).

**Cons / mitigaciones**
- Introduce una tabla y un pequeño camino de auth propios (bootstrap del primer admin de plataforma) → esfuerzo acotado y aislado; bootstrap por seed/CLI documentado en runbook (R-96).
- El paso `set_tenant_session` sobre la misma transacción tras insertar `tenants` es sutil → se fija explícitamente en SPEC-075 y se verifica con test de cero bypass (el `user` NO se crea con sesión owner) y test cross-tenant (R-89/R-90).
- Colisión de slug (global) o email (por-tenant) debe traducirse a **error tipado 409/422, nunca 500** → validación previa + captura tipada de la violación de unicidad (R-93), verificada en SPEC-076.
- Secretos: passwords del `user` admin y de `platform_admins` **hasheados** (SPEC-013, bcrypt), cero secretos en logs/respuesta (C3, R-95).

**Criterio de verificación (objetivo y verificable)**
- **Aislamiento (CE-89):** test cross-tenant (fija `app.tenant_id` de otro tenant → 0 filas del nuevo, patrón `tests/test_rls_isolation.py`).
- **Cero bypass RLS (CE-91):** test que verifica que `users` NO se inserta con sesión owner; el `user` admin se crea con `app.tenant_id` fijado; passwords hasheados; cero secretos en logs.
- **Atomicidad + unicidad (CE-93):** fallo inyectado a mitad del alta → 0 filas (sin huérfanos); colisión de slug/email → 409/422, nunca 500.
- **Protección del endpoint (CE-92):** sin credenciales de plataforma → 401; con JWT de tenant normal → 403; solo admin de plataforma → 201.
- **Login inmediato (CE-90):** el primer admin se autentica por el flujo existente (SPEC-013) tras el alta → 200 con JWT (`tenant_id` correcto, `rol="admin"`).
- **Cero regresión (CE-94):** login, `GET /tenants/me`, seed y fases #1–#6 verdes sin modificar asserts.

---

## Referencias

- `PLAN-009.md` — §1 (objetivo, Q1–Q4 vinculantes), §2 IN/OUT, §3.2 (mecanismo del admin de plataforma, Opción A vs B), §3.3 (frontera de privilegio), §3.4 (atomicidad), §4 F0 (puerta de diseño), §11 (ADR-015 recomendado), R-89/R-90/R-91/R-92/R-95/R-96, CE-88..CE-94, DoD §10.
- `SPEC-073` — Esta ADR (puerta de diseño F0).
- `SPEC-074` — Modelo de datos aditivo: migración Alembic de `platform_admins` (sin `tenant_id`, NO scoped) + semántica de `rol="admin"`.
- `SPEC-075` — `tenant_provisioning_service` transaccional + auth/guard `require_platform_admin` + endpoint `POST /platform/tenants` + CLI interno.
- `SPEC-076` — Pruebas + seguridad + docs/runbook + no-regresión.
- **Consume (no rediseña):** `ADR-004` (RLS pool-model), `ADR-008` (rol `omnicore_app` NOSUPERUSER NOBYPASSRLS + RLS efectiva).
- Código: `app/models/tenant.py`, `app/models/user.py`, `app/db/rls.py`, `app/db/seed.py`, `app/db/session.py::set_tenant_session`, `app/services/auth_service.py`, `app/api/deps.py`, `app/security/passwords.py`, `app/api/tenants.py`, `tests/test_rls_isolation.py`.
- `backend/check-externos-backend.sh` — debe seguir en verde (sin egress nuevo).
