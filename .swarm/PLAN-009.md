# PLAN-009 — Alta administrativa interna de un tenant nuevo (sede) + su primer usuario administrador, atómica, sobre la RLS efectiva ya existente — "admin de plataforma" como concepto separado (fuera del modelo tenant-scoped), sin autoregistro público, sin canal WhatsApp, activación inmediata, binario sin planes/billing

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Fecha: 2026-09-29 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo` presente) — el alta crea la **raíz de aislamiento** (`tenants`) de los datos personales de una sede/cliente nuevo; un fallo aquí es una **fuga cross-tenant**. Esta fase **NO introduce egress nuevo**: no llama a IA externa ni a servicios de terceros. El único transporte externo del proyecto sigue siendo `graph.facebook.com` (ADR-006), que **esta fase no toca** (el tenant se crea SIN canal, §2 OUT).
> Origen: `prompt-lab/prompts/PROMPT-009-ONBOARDING-MULTITENANT.md` (🧠 XAVIER) — decisiones del Lead a §7 ya **VINCULANTES** (§7.1, 2026-09-29): Q1→(i) grupo de clínicas multi-sede + **Opción B alta administrativa interna**; Q2→**A tenant SIN canal**; Q3→**A activación inmediata**; Q4→**A binario, sin límites/billing**. **No se reabren.**
> Regla de oro: este PLAN **NO genera SPECs ni código**. Las SPEC se redactan como PROPUESTA y solo pasan a implementación tras la aprobación explícita del Lead ("APROBADO PLAN-009" y luego "APROBADO SPEC-XXX"). **Dos puertas obligatorias:** primero PLAN, luego SPEC.
> **APROBADO por el Lead — 2026-09-30**, con los 3 puntos de §12 resueltos por defecto (recomendaciones aceptadas, sin veto): (1) `platform_admins` separado confirmado; (2) sin UI en la SPA (endpoint+CLI); (3) el seed/SQL queda solo para demo/pruebas, el alta de producción real pasa por este flujo nuevo. F3 se mantiene fusionada (4 SPECs, no 5).
> Base que se CONSUME (no se rediseña): **ADR-004** (RLS pool-model), **ADR-008** (roles BD: rol app `omnicore_app` NOSUPERUSER NOBYPASSRLS + SECURITY DEFINER), `backend/app/db/rls.py` (`TENANT_SCOPED_TABLES`), **SPEC-012** (modelo + RLS), **SPEC-013** (login `tenant_slug`+email+password, hashing de password, resolución de tenant pre-JWT). El aislamiento de datos **ya funciona y está probado** (`tests/test_rls_isolation.py`); esta fase construye el **flujo de alta que hoy no existe** encima de él.
> Contadores vigentes (`.swarm/specs.json`): `next_plan: 8` (⚠️ **DESACTUALIZADO** — PLAN-008 ya existe/APROBADO; **este plan lo corrige a 10**), `next_spec: 73`, `next_adr: 15`. Este plan es **PLAN-009** (número correcto, no colisiona) y **recomienda ADR-015**. `next_spec`/`next_adr` **NO se reclaman aquí**: se consumirán al crear las SPEC tras "APROBADO PLAN-009".

---

## 1. Objetivo y contexto

### Objetivo

Reemplazar el **alta manual actual de un tenant** (hoy 100% vía `backend/app/db/seed.py` / SQL con rol owner) por un **flujo de provisioning administrativo interno**: un **admin de plataforma** (concepto que HOY NO EXISTE) da de alta una **sede/tenant nueva** (nombre + slug único) junto con su **primer usuario administrador** (email único por-tenant, password hasheado, `rol="admin"`) en una **única operación atómica** — de modo que ese admin pueda **loguearse de inmediato** con el flujo existente (`tenant_slug`+email+password, SPEC-013) y que el tenant quede **aislado por RLS desde el primer commit**, reutilizando ADR-004/ADR-008 sin rediseñarlos.

Es el caso de uso confirmado por el Lead (§7.1 Q1): **un grupo de clínicas multi-sede** (Clínica Campbell y sus sedes), **NO** un SaaS vendido a terceros. Por eso el alta es **administrativa interna** (no hay formulario público de autoregistro), **activación inmediata** (quien crea el tenant ya es de confianza), el tenant se crea **sin canal WhatsApp** (se conecta después, fase separada) y es **binario** (existe/no existe, sin planes/cuotas/billing).

Todo es **aditivo**: no se rompe `GET /tenants/me`, ni el login (SPEC-013), ni el seed, ni las fases #1–#6. La migración de los tenants ya existentes está **fuera de alcance** (siguen como están).

### Decisiones del Lead ya VINCULANTES (del prompt §7.1 — NO se reabren)

| # | Pregunta | Decisión vinculante | Consecuencia de alcance |
|---|----------|---------------------|-------------------------|
| **Q1 — Quién crea el tenant / caso de uso** | **(i) Grupo de clínicas multi-sede** + **Opción B: alta administrativa interna.** Introduce el concepto de **"admin de plataforma"** (hoy inexistente). Sin autoregistro público. | El alta es un endpoint **protegido para admin de plataforma**, no un formulario abierto. Mínima superficie de abuso. El **mecanismo exacto** del admin de plataforma lo decide este PLAN (§3.2 + ADR-015), ya que XAVIER lo dejó explícitamente a DOCTOR STRANGE. |
| **Q2 — Canal WhatsApp en el alta** | **Opción A: el tenant se crea SIN canal.** Registrar `phone_number_id` en `whatsapp_accounts` es un paso/fase posterior. | Alcance limpio: no se arrastra la complejidad de credenciales de Meta. El tenant queda aislado en DATOS de inmediato; conectar WhatsApp es OUT (§2). |
| **Q3 — Verificación/activación** | **Opción A: activación inmediata.** Sin verificación de email ni aprobación adicional. | El primer admin puede loguearse en cuanto termina el alta. **Sin dependencia de SMTP** → sin egress nuevo por correo. |
| **Q4 — Planes/límites** | **Opción A: binario, sin límites.** Sin planes/cuotas ni billing. | No hay modelo de datos de plan ni enforcement de cuotas. Billing sigue OUT por defecto (§2). |

### Contexto verificado en código (fuente de verdad, no asunciones)

- **`tenants` es la raíz del aislamiento, SIN `tenant_id`** (`backend/app/models/tenant.py`): columnas `id` (uuid `gen_random_uuid()`), `nombre` (255), `slug` (100, **UNIQUE**, index) + `TimestampMixin` + `SoftDeleteMixin` (`activo`, C2). **NO está en `TENANT_SCOPED_TABLES`** (`rls.py:43-56`) → no lleva política RLS por fila. Gestionar qué tenants existen es **operación de plataforma**, explícitamente fuera del mecanismo RLS (`rls.py:37-40`).
- **`users` es tabla scoped con RLS ENABLE+FORCE** (`rls.py:44`, `backend/app/models/user.py`): `id`, `email` (255, index), `nombre`, `password_hash` (nullable, lo llena SPEC-013), `rol` (str 50, **default `"agente"`** — HOY **no hay rol `"admin"` reservado**), + `TenantMixin`/`TimestampMixin`/`SoftDeleteMixin`. Constraint **`uq_users_tenant_email`** (email único POR tenant, no global) — **ya existe, se consume tal cual**.
- **El provisioning de plataforma YA es un patrón vigente** (`backend/app/db/seed.py:49-62`): inserta en `tenants` con el **engine directo (rol owner) SIN fijar `app.tenant_id`** — intencional y correcto para la fila raíz `tenants` (no scoped). Este plan **formaliza y hace seguro** ese patrón, no lo inventa.
- **La resolución de tenant ANTES del JWT ya existe** (`backend/app/services/auth_service.py:75-98`): `authenticate()` descubre el tenant por `slug` con la sesión "de plataforma" (`get_db`, sin tenant fijado) y **luego fija `set_tenant_session(db, tenant.id)` para leer `users` bajo RLS**. Es exactamente el patrón que reutilizará el provisioning para **crear el primer admin bajo RLS** (fijar `app.tenant_id` del tenant recién creado antes de insertar en `users`).
- **`set_tenant_session` + RLS efectiva** (`app/db/session.py`, `app/api/deps.py:60-70`): el rol `omnicore_app` es **NOSUPERUSER NOBYPASSRLS** (ADR-008); fijar `app.tenant_id` es lo que activa el aislamiento (ADR-004). **PROHIBIDO bypass genérico con rol owner** para crear el `user` admin (bug recurrente ya documentado en `retention_service`/`call_retention_service`).
- **`GET /tenants/me` es la ÚNICA lectura de tenant hoy** (`backend/app/api/tenants.py`): no hay endpoint de creación ni listado global de tenants (comentario explícito: un listado global sería "una fuga cross-tenant/administrativa fuera de alcance"). Este plan **añade la creación**, no toca `GET /tenants/me`.
- **JWT lleva `tenant_id` + `rol`** (`auth_service.py:116`, `create_access_token`): el rol viaja firmado en el token. Hoy la autorización por rol dentro de un tenant existe conceptualmente pero **no hay un guard `require_role`**; el admin de plataforma **NO** se modela como un rol de JWT de tenant (ver §3.2).

---

## 2. Alcance IN / OUT

### IN — entra en el Entregable de alta de tenant

1. **Decisión y modelo del "admin de plataforma" (F0/F1 + ADR-015):** definir el mecanismo exacto por el que un actor interno queda autorizado a crear tenants. **Decisión de este plan (§3.2): tabla separada `platform_admins` FUERA del modelo tenant-scoped** (sin `tenant_id`, NO en `TENANT_SCOPED_TABLES`, análoga a `tenants`), con su propio password hasheado (reutiliza SPEC-013) y su propia autenticación acotada. Migración Alembic **aditiva**.
2. **Servicio de provisioning transaccional (F2):** un `tenant_provisioning_service` que, en **una sola unidad atómica (todo o nada)**: (a) crea la fila raíz `tenants` (nombre + slug único, `activo=True`) con el patrón de plataforma (rol owner, sin `app.tenant_id`, como el seed); (b) fija `app.tenant_id` del tenant recién creado y crea el **primer usuario `users`** (email normalizado único por-tenant, `password_hash` vía SPEC-013, `rol="admin"`) **respetando RLS** (patrón de `auth_service`), **sin bypass genérico**. Si cualquier paso falla → **rollback total** (nunca un tenant huérfano sin admin, ni un admin sin tenant).
3. **Endpoint de alta protegido para admin de plataforma (F2):** `POST` de provisioning que **solo** un admin de plataforma autenticado puede invocar (autenticación/autorización propia, §3.2), con validación tipada de entrada, respuestas de error **tipadas** (409/422, no 500) para colisión de slug (global) y email, y unicidad de slug (derivación/validación/reservados).
4. **Introducción del `rol="admin"` explícito para el primer usuario (F1):** el primer usuario del tenant nace con `rol="admin"` (hoy el default es `"agente"`). Es un valor de texto en la columna `rol` existente (no cambia el esquema de `users`); se documenta su semántica. La **gestión posterior de más usuarios/roles finos** del tenant es OUT (§2).
5. **Reutilización del login existente (F2/F3):** tras el alta, el primer admin se autentica con el flujo **sin cambios** (`tenant_slug`+email+password, SPEC-013). No se toca `auth_service`/`deps` salvo, si acaso, un guard de autorización reutilizable (`require_platform_admin`) que **no altera** el login de tenant.
6. **Pruebas + seguridad + no-regresión (F3):** **aislamiento cross-tenant obligatorio** (el tenant recién creado no ve ni es visto por otros — test que fija `app.tenant_id` cruzado, patrón `tests/test_rls_isolation.py`); **atomicidad** (fallo inyectado a mitad del alta → 0 filas, sin huérfanos); **unicidad** (slug duplicado → error tipado; email duplicado por-tenant → error tipado; **no 500**); **cero bypass RLS** (el `user` admin se crea con `app.tenant_id` fijado, no con owner); **protección del endpoint** (sin credenciales de admin de plataforma → 401/403; superficie de abuso acotada — test negativo); **password hasheado** + cero secretos en logs (C3); **cero regresión** de login, `GET /tenants/me`, seed y fases #1–#6.
7. **Docs/runbook (F3, fusionado):** runbook del nuevo flujo de alta (cómo un admin de plataforma da de alta una sede vía API/CLI interno), cómo se crea/gestiona un admin de plataforma (bootstrap del primer admin de plataforma), y **nota explícita** sobre deprecar (o no) el alta por seed/SQL para tenants de producción reales (el seed **permanece** para datos de demo/pruebas; el alta de producción pasa a ser el nuevo flujo).

### OUT — NO entra en este slice (fase futura / decisión aparte)

- **Autoregistro público / formulario abierto** (Q1-A): descartado por Q1→B. No hay alta self-service para el cliente final; la hace el equipo interno.
- **Verificación de email / SMTP / anti-bot / rate-limit de alta pública** (Q3-B/C): descartado por Q3→A (activación inmediata) y por no haber alta pública. **Sin dependencia de correo → sin egress nuevo.**
- **Conectar el canal WhatsApp en el alta** (Q2-B/C): el tenant se crea SIN canal. Registrar `phone_number_id` en `whatsapp_accounts` y, más aún, WABA/credenciales propias por-tenant (Embedded Signup, tokens cifrados) son fases futuras propias.
- **Planes / cuotas / límites / billing** (Q4-B, §8 del prompt): binario sin límites. Sin modelo de plan ni enforcement.
- **Gestión avanzada de usuarios del tenant** (invitar/eliminar más usuarios, roles finos más allá del primer admin): esta fase crea SOLO el primer admin del tenant.
- **Baja/offboarding de tenants** y exportación de datos: esta fase es el ALTA, no la baja. (El borrado lógico C2 = `activo=False` ya existe en el modelo; su uso operativo es otra fase.)
- **Migración de tenants existentes** creados por seed/SQL: siguen como están.
- **UI/pantalla de alta en la SPA:** ver §3.5 — **por defecto OUT** (el valor se entrega con un endpoint API + CLI interno para el equipo; una pantalla admin es fase futura opcional, no indispensable para el entregable). Se anota como candidata futura, no se da por sentada.
- **SSO / login federado** para el admin de plataforma: usa autenticación por password propia (reutiliza el hashing de SPEC-013).

---

## 3. Arquitectura de referencia

### 3.1 Flujo end-to-end (alta administrativa interna, atómica)

```
admin de plataforma (autenticado por su propio mecanismo, §3.2)
      |
      v
POST /platform/tenants  { nombre, slug, admin_email, admin_password, admin_nombre }
      |
      v  [tenant_provisioning_service — UNA transacción atómica]
      |
      +-- (1) INSERT tenants (nombre, slug UNIQUE, activo=true)      <- patrón de plataforma
      |        rol owner, SIN app.tenant_id  (tenants NO es scoped, como el seed hoy)
      |        colision de slug -> 409 tipado (no 500)
      |
      +-- (2) set_tenant_session(db, nuevo_tenant.id)               <- FIJA app.tenant_id
      |        INSERT users (email norm., password_hash SPEC-013, rol="admin")
      |        BAJO RLS efectiva (patron auth_service) — SIN bypass owner
      |        colision uq_users_tenant_email -> 409/422 tipado (no 500)
      |
      +-- commit (todo)  |  cualquier fallo -> ROLLBACK total (0 filas, sin huerfanos)
      |
      v
201 { tenant_id, slug }  ->  el primer admin ya puede loguearse (SPEC-013, sin cambios)
                             tenant AISLADO por RLS desde el primer commit
```

### 3.2 El punto de diseño central: mecanismo del "admin de plataforma" (ADR-015)

XAVIER dejó explícitamente a DOCTOR STRANGE elegir entre dos opciones. Las evalúo y decido:

- **Opción A — Rol especial reservado dentro de `users`** (p. ej. un `rol="platform_admin"` en un usuario de un tenant "de control"), con privilegio elevado para crear otros tenants.
  - *Contras (decisivos):* `users` es **tenant-scoped con RLS ENABLE+FORCE**; un actor que debe **operar por encima de todos los tenants** encaja mal en una tabla cuya invariante es "solo ves tu tenant". Autorizar el alta requeriría **saltarse o ampliar RLS** para ese rol (justo el bypass que las restricciones duras PROHÍBEN), o inventar un "tenant de control" artificial. Mezcla dos planos (operación de tenant vs operación de plataforma) que el proyecto ya mantiene deliberadamente separados (`tenants` fuera de `TENANT_SCOPED_TABLES`; comentario de `rls.py:37-40`). Aumenta la superficie de error de aislamiento.
- **Opción B — Concepto separado FUERA del modelo tenant-scoped: tabla `platform_admins` sin `tenant_id`** (análoga a `tenants`, NO en `TENANT_SCOPED_TABLES`, sin política RLS por fila), con su propio `email`/`password_hash` (reutiliza el hashing de SPEC-013) y su propia autenticación acotada (JWT/credencial de plataforma distinto del JWT de tenant, o un login de plataforma dedicado).
  - *Pros (decisivos):* respeta la **separación ya existente** entre "plano de plataforma" (gestiona `tenants`) y "plano de tenant" (RLS). No toca ni amplía RLS de `users`. El admin de plataforma **no pertenece a ningún tenant** (correcto conceptualmente: gestiona todos). La fila raíz `tenants` ya se crea con el patrón de plataforma (rol owner, sin `app.tenant_id`); un `platform_admins` sin RLS es **coherente** con ese mismo plano. La autenticación de plataforma es **independiente** del login de tenant (no lo contamina, cero regresión de SPEC-013). Superficie de abuso mínima (solo credenciales de plataforma pueden crear tenants).
  - *Contra (gestionable):* introduce una tabla y un pequeño camino de auth propios (bootstrap del primer admin de plataforma vía seed/CLI, análogo a como hoy nace el primer tenant). Es esfuerzo acotado y aislado.

> **DECISIÓN (ADR-015): Opción B — `platform_admins` como concepto separado, fuera del modelo tenant-scoped.** Es la que mejor respeta las restricciones duras (cero bypass RLS, no rediseñar el aislamiento) y la arquitectura ya vigente (separación plano-plataforma / plano-tenant). El **bootstrap del primer admin de plataforma** se hace por seed/CLI de plataforma (mismo plano que el seed de `tenants` hoy), no por autoregistro. La autenticación del admin de plataforma es **independiente** del login de tenant (SPEC-013 intacto). La creación del **primer usuario admin del tenant** (fila `users`, scoped) **sí** se hace **bajo RLS con `app.tenant_id` fijado** (patrón `auth_service`), nunca con bypass owner — la fila raíz `tenants` es la única que usa el privilegio elevado acotado (como el seed).

### 3.3 Dónde vive la frontera de privilegio (invariante de seguridad — NO se relaja)

```
PLANO DE PLATAFORMA  (sin app.tenant_id — como el seed hoy):
   - tabla `tenants`          (raiz, NO scoped)  -> INSERT con patron de plataforma
   - tabla `platform_admins`  (NUEVA, NO scoped) -> gestiona su propia auth
   - crea la fila raiz `tenants` con privilegio elevado ACOTADO (analogo al seed)

PLANO DE TENANT  (RLS efectiva, app.tenant_id fijado — rol omnicore_app NOSUPERUSER NOBYPASSRLS):
   - tabla `users` (scoped)   -> el PRIMER ADMIN del tenant se crea AQUI, bajo RLS
   - jamas se usa bypass owner para insertar en `users` (restriccion dura)
```

- La **única** operación con privilegio elevado es el `INSERT` en `tenants` (fila raíz no scoped) — exactamente lo que ya hace el seed y lo que ADR-004/`rls.py` describen como operación de plataforma. **Todo lo scoped (`users`) respeta RLS.**
- El endpoint de alta **solo** es alcanzable por un admin de plataforma autenticado; ese es el control de abuso (no hay alta pública que proteger con captcha/rate-limit).

### 3.4 Atomicidad tenant + admin (invariante — nunca huérfanos)

El alta es **una sola transacción**. El reto técnico: (1) crear `tenants` es plano-plataforma (sin `app.tenant_id`) y (2) crear `users` es plano-tenant (con `app.tenant_id` fijado), pero **ambos deben vivir en la misma unidad atómica**. El diseño (a fijar en SPEC): una única transacción de BD donde, tras insertar `tenants`, se ejecuta `set_tenant_session` sobre **la misma sesión/conexión** y se inserta `users`; el `commit`/`rollback` cubre ambas filas. Si el segundo `INSERT` viola `uq_users_tenant_email` (o cualquier fallo), **rollback total** → ni tenant ni admin quedan persistidos. Se verifica con un test de fallo inyectado (CE-93).

### 3.5 ¿Hace falta UI/frontend? (evaluación, no se da por sentado)

Q1→B es **alta administrativa interna** para un grupo de clínicas con pocas sedes (no un SaaS con miles de altas). El valor del entregable —formalizar y hacer seguro el alta que hoy es SQL manual— se entrega **por completo con un endpoint API protegido + un pequeño CLI interno** (invocable por el equipo vía Postman/script, mejora directa del seed actual). Una **pantalla en la SPA no es indispensable** para el valor y añadiría superficie (routing admin, guard de UI, diseño AAA) sin necesidad clara dado el volumen. **Decisión: la UI queda OUT de este slice** (§2), anotada como **fase futura opcional** si el Lead prioriza un panel admin. Si el Lead la quiere dentro del alcance, se añade una fase F-UI (SPIDER-MAN/DAREDEVIL) — pero el plan **no la asume**.

### 3.6 Por qué NO hay egress nuevo

El alta no llama a IA, ni a SMTP (activación inmediata, Q3-A → sin verificación por correo), ni a Meta (tenant sin canal, Q2-A). Es 100% interna a la BD. El único transporte externo del proyecto (`graph.facebook.com`, ADR-006) **no se toca**. `backend/check-externos-backend.sh` debe seguir **verde sin cambios**. Por eso este plan **no requiere un ADR de egress** (a diferencia de ADR-006/ADR-010).

---

## 4. Fases y entregables

| Fase | Nombre | Entregables clave | SPEC (propuesta) |
|------|--------|-------------------|------------------|
| **F0** | **Decisión del mecanismo de "admin de plataforma" + ADR-015 — PUERTA DE DISEÑO** | ADR-015 formaliza: (a) `platform_admins` como concepto separado fuera del modelo tenant-scoped (Opción B, §3.2); (b) la fila raíz `tenants` se crea con privilegio elevado acotado (patrón seed), el `user` admin bajo RLS con `app.tenant_id` fijado (sin bypass); (c) atomicidad tenant+admin; (d) bootstrap del primer admin de plataforma por seed/CLI; (e) alcance del `rol="admin"`. **Gate:** sin ADR-015 aceptado no se implementa F2. | **SPEC-073** |
| **F1** | Modelo de datos aditivo + `rol="admin"` | Migración Alembic **aditiva**: tabla `platform_admins` (id, email único, password_hash, nombre, activo/timestamps; **sin `tenant_id`**, **NO** en `TENANT_SCOPED_TABLES`); semántica de `rol="admin"` para el primer usuario del tenant (usa la columna `rol` existente, sin cambio de esquema en `users`). Sin backfill destructivo; cero impacto en tenants/usuarios existentes. | **SPEC-074** |
| **F2** | Servicio de provisioning + endpoint protegido + auth de admin de plataforma | `tenant_provisioning_service` transaccional (tenant plano-plataforma + primer admin bajo RLS, atómico); autenticación/guard del admin de plataforma (`require_platform_admin`, independiente de SPEC-013); endpoint `POST /platform/tenants` con validación tipada, unicidad de slug/email → 409/422 (no 500); reutiliza hashing SPEC-013; CLI interno de alta (mejora del seed). | **SPEC-075** |
| **F3** | Pruebas + seguridad + docs/runbook + no-regresión (fusiona pruebas y docs) | Aislamiento cross-tenant del tenant nuevo (test que fija `app.tenant_id` cruzado); atomicidad (fallo inyectado → 0 filas); unicidad slug/email → error tipado; cero bypass RLS (admin creado con `app.tenant_id`); protección del endpoint (sin credenciales → 401/403; superficie de abuso acotada); password hasheado + cero secretos en logs (C3); **cero regresión** login/`GET /tenants/me`/seed/#1–#6; runbook del alta + bootstrap del admin de plataforma + nota de deprecación (o no) del alta por seed/SQL para producción; cobertura ≥80%. | **SPEC-076** |

> **F3 fusiona pruebas+seguridad+docs** (a diferencia de planes previos que separaban docs en fase propia): el alcance es acotado (un servicio + un endpoint + una tabla), el grueso es de seguridad/pruebas y el runbook es breve (no hay deploy de infra nueva ni motor a documentar). Si el Lead prefiere separar docs/runbook en una F4 propia (patrón SPEC-061/066/072), serían **5 SPECs**; el plan lo deja como opción explícita.

---

## 5. Dependencias entre fases y ruta crítica

- **F0 (SPEC-073, ADR-015)** es **puerta de diseño dura**: fija el mecanismo del admin de plataforma y el modelo de privilegio/atomicidad. Sin ADR-015 aceptado no se implementa F2.
- **F1 (SPEC-074)** depende de F0 (el modelo `platform_admins` materializa la decisión de ADR-015). El `rol="admin"` puede documentarse en paralelo.
- **F2 (SPEC-075)** depende de F0 (ADR-015) y F1 (tabla `platform_admins` + `rol`). Es el **núcleo técnico** (provisioning atómico + endpoint protegido + auth de plataforma).
- **F3 (SPEC-076)** depende de F0/F1/F2 (prueba el slice completo: aislamiento, atomicidad, unicidad, cero bypass, protección, cero regresión) y cierra con docs/runbook.

**Ruta crítica:** `F0 → F1 → F2 → F3`. El mayor riesgo de diseño se concentra en **F0** (mecanismo del admin de plataforma) y el mayor riesgo de seguridad en **F2/F3** (aislamiento del tenant nuevo + protección del endpoint de alta).

---

## 6. Riesgos y mitigaciones

| # | Riesgo | Impacto | Mitigación |
|---|--------|---------|------------|
| **R-89** | **Fuga cross-tenant en el alta** (el tenant recién creado ve o es visto por otros, o el primer admin se crea sin aislamiento efectivo). | **Crítico** (fuga de datos personales) | El `user` admin se crea **bajo RLS con `app.tenant_id` fijado** (patrón `auth_service`), rol `omnicore_app` NOSUPERUSER NOBYPASSRLS (ADR-008); **test cross-tenant obligatorio** (fija `app.tenant_id` de otro tenant → 0 filas del nuevo, patrón `tests/test_rls_isolation.py`). No se rediseña RLS: se consume tal cual. |
| **R-90** | **Bypass genérico de RLS con rol owner para crear el `user` admin** (bug recurrente documentado en `retention_service`/`call_retention_service`). | **Crítico** (rompe la invariante de aislamiento) | **Prohibido por diseño:** el privilegio elevado se limita a la fila raíz `tenants` (no scoped, como el seed); `users` se inserta **siempre** con `app.tenant_id` fijado. Test que verifica que el alta NO usa una sesión owner para `users`. ADR-015 fija esta frontera explícitamente (§3.3). |
| **R-91** | **Tenant huérfano** (tenant creado sin admin, o admin sin tenant) por fallo a mitad del alta. | **Alto** (estado inconsistente) | **Atomicidad todo-o-nada:** ambas filas en una sola transacción/`commit`; fallo → **rollback total**. Test de fallo inyectado (violar `uq_users_tenant_email` a propósito) verifica 0 filas persistidas (§3.4). |
| **R-92** | **Superficie de abuso del endpoint de alta** (¿quién puede llamarlo? si el guard es débil, cualquiera crea tenants) — el riesgo de seguridad más importante del plan. | **Alto** (creación no autorizada de tenants) | El alta **solo** es alcanzable por un **admin de plataforma autenticado** (mecanismo propio, §3.2, independiente del login de tenant); sin credenciales de plataforma → 401/403. Al ser **alta interna** (no pública, Q1-B) la superficie es mínima por diseño; test negativo (sin credenciales / con JWT de tenant normal → rechazado). Bootstrap del primer admin de plataforma por seed/CLI, no por autoregistro. |
| **R-93** | **Colisión de slug/email sin manejo tipado** → 500 en vez de 409/422 (mala UX + posible filtración de detalle interno). | **Medio** | Validación previa + captura tipada de la violación de `unique(slug)` global y `uq_users_tenant_email` → **409/422 tipado**; test de colisión de slug y de email. Nunca 500. |
| **R-94** | **Regresión de login / `GET /tenants/me` / seed / fases #1–#6** al introducir la nueva tabla/endpoint/auth. | **Alto** (rompe lo existente) | Todo **aditivo**: `platform_admins` es tabla nueva no scoped; el login de tenant (SPEC-013) **no se toca**; migración nullable/aditiva; `GET /tenants/me` intacto; seed intacto (permanece para demo). Suites #1–#6 verdes sin modificar asserts. |
| **R-95** | **Secreto en claro** (password del admin del tenant o del admin de plataforma en logs/DB). | **Medio** (C3) | Password hasheado con el hashing de **SPEC-013** (mismo mecanismo) tanto para el `user` admin como para `platform_admins`; ningún secreto en logs; test que verifica que la respuesta/logs no exponen el password. |
| **R-96** | **Bootstrap del admin de plataforma mal resuelto** (huevo-gallina: ¿quién crea al primer admin de plataforma?). | **Medio** | Bootstrap por **seed/CLI de plataforma** (mismo plano que el seed de `tenants` hoy), documentado en el runbook (F3); no hay autoregistro de admin de plataforma. Credenciales iniciales fuera del código (C3). |
| **R-97** | **Slug inválido/reservado o colisión con seed** (`clinica-demo-norte/sur` ya existen). | **Bajo/Medio** | Validación de formato de slug + lista de reservados + unicidad global; el alta convive con los slugs del seed (ON CONFLICT ya es el patrón); test de slug reservado/duplicado → error tipado. |

**Top-3:** **R-89 (fuga cross-tenant en el alta)**, **R-92 (superficie de abuso del endpoint / quién puede llamarlo)**, **R-90 (bypass RLS con owner)**. R-91 (huérfanos/atomicidad) inmediatamente detrás.

---

## 7. Criterios de éxito verificables (CE-88..CE-94 — continúan tras CE-87 de PLAN-008)

> Base: CE-1..CE-7 del prompt §6, renumerados correlativamente para no colisionar con PLAN-008 (último CE = CE-87).

| ID | Criterio | Cómo se verifica | Fase |
|----|----------|------------------|------|
| **CE-88** | **Alta funcional sin desarrollador tocando SQL:** un admin de plataforma da de alta una sede/tenant + su primer admin vía endpoint/CLI, sin ejecutar SQL/seed manual. | Test e2e del alta feliz: `POST /platform/tenants` → 201 con `tenant_id`/`slug`; tenant + primer admin persistidos. | F2/F3 |
| **CE-89** | **Aislamiento desde el primer commit:** el tenant recién creado está aislado por RLS; no ve ni es visto por otros tenants. | Test cross-tenant que fija `app.tenant_id` de otro tenant y verifica 0 filas del nuevo (patrón `tests/test_rls_isolation.py`). | F2/F3 |
| **CE-90** | **Login inmediato (activación inmediata, Q3-A):** el primer admin se autentica con el flujo existente (`tenant_slug`+email+password) inmediatamente tras el alta, sin verificación adicional. | Test e2e: alta → login del primer admin → 200 con JWT (`tenant_id` correcto, `rol="admin"`). | F2/F3 |
| **CE-91** | **Cero bypass RLS + secretos seguros:** el primer admin (`users`) se crea con `app.tenant_id` fijado (no con owner); el privilegio elevado se limita a la fila raíz `tenants`; passwords hasheados; cero secretos en logs. | Test que verifica que `users` NO se inserta con sesión owner; inspección de logs/respuesta sin password; `password_hash` presente y hasheado. | F2/F3 |
| **CE-92** | **Protección del endpoint (superficie de abuso acotada):** solo un admin de plataforma autenticado puede crear tenants; sin credenciales de plataforma (o con un JWT de tenant normal) → 401/403. | Test negativo: llamada sin credenciales → 401; con JWT de agente/admin de un tenant → 403; solo admin de plataforma → 201. | F2/F3 |
| **CE-93** | **Atomicidad + unicidad:** colisión de slug (global) o email (por-tenant) → error tipado (409/422, **no 500**); un fallo a mitad del alta no deja tenant huérfano ni admin huérfano. | Test de colisión de slug, de email, y de fallo inyectado → rollback total verificado (0 filas). | F2/F3 |
| **CE-94** | **Cero regresión + alcance acotado:** login, `GET /tenants/me`, seed y fases #1–#6 pasan sus suites sin modificar asserts; lo listado como OUT (§2: WhatsApp en el alta, verificación email, planes/billing, UI, autoregistro) NO aparece implementado. | Suites #1–#6 verdes; inspección de que no se añadió canal/plan/UI/autoregistro. | F3 |

> Transversales heredados: **aprobación explícita del Lead**; CHECKPOINTS C2 (borrado lógico `activo`) / C3 (secretos: passwords hasheados) / C4 (criterios verificables) / C6 (cambio sensible → notificación Telegram) / C8 (prompt registrado en `prompt-lab/prompts/PROMPT-009-ONBOARDING-MULTITENANT.md`).

---

## 8. Mapa de SPECs propuestas (SOLO el mapa — se redactan como PROPUESTA, se implementan tras "APROBADO PLAN-009")

> Continúa la numeración desde `specs.json` (`next_spec: 73`). Se crearán únicamente tras "APROBADO PLAN-009". Cada SPEC llevará criterios verificables (C4).

- **SPEC-073** — ADR-015 (mecanismo del admin de plataforma = `platform_admins` separado, fuera del modelo tenant-scoped; frontera de privilegio tenant/plano-plataforma; atomicidad tenant+admin; bootstrap del admin de plataforma; alcance de `rol="admin"`). **Puerta de diseño** (F0).
- **SPEC-074** — Modelo de datos aditivo: migración Alembic de la tabla `platform_admins` (sin `tenant_id`, NO scoped) + semántica de `rol="admin"` del primer usuario del tenant; sin backfill destructivo, cero impacto en existentes (F1).
- **SPEC-075** — `tenant_provisioning_service` transaccional (tenant plano-plataforma + primer admin bajo RLS, atómico) + auth/guard del admin de plataforma (`require_platform_admin`, independiente de SPEC-013) + endpoint `POST /platform/tenants` con unicidad slug/email tipada (409/422) + CLI interno de alta (F2).
- **SPEC-076** — Pruebas + seguridad + docs/runbook + no-regresión: aislamiento cross-tenant, atomicidad, unicidad tipada, cero bypass RLS, protección del endpoint, passwords hasheados, cero regresión #1–#6, runbook del alta + bootstrap del admin de plataforma + nota de deprecación del alta por SQL, cobertura ≥80% (F3).

> Total: **4 SPECs (SPEC-073..SPEC-076)** → `next_spec` pasaría a **77** al crearlas (no ahora). **ADR-015** recomendado → `next_adr` pasaría a **16** al crearlo. Si el Lead separa docs/runbook en una F4 propia (§4), serían 5 SPECs (SPEC-073..077).

---

## 9. Entregables finales de la fase de alta de tenant

- **Tabla `platform_admins`** (concepto separado, fuera del modelo tenant-scoped) con su propia autenticación acotada, y bootstrap del primer admin de plataforma por seed/CLI.
- **ADR-015** que formaliza el mecanismo del admin de plataforma, la frontera de privilegio (plano-plataforma para `tenants`, RLS para `users`) y la atomicidad tenant+admin; sin rediseñar RLS.
- **`tenant_provisioning_service`** transaccional que crea tenant + primer admin en una sola unidad atómica, con el `user` admin **bajo RLS** (sin bypass owner).
- **Endpoint `POST /platform/tenants`** protegido para admin de plataforma, con unicidad de slug/email tipada (409/422) + **CLI interno** de alta (mejora segura del seed manual).
- Primer usuario del tenant con **`rol="admin"`** y **login inmediato** por el flujo existente (SPEC-013, sin cambios).
- Suite de pruebas (aislamiento cross-tenant, atomicidad, unicidad, cero bypass RLS, protección del endpoint, cero regresión #1–#6) + cobertura ≥80%.
- **Evidencia auditable:** tenant nuevo aislado por RLS, `user` admin creado sin bypass owner, atomicidad sin huérfanos, endpoint no alcanzable sin credenciales de plataforma, passwords hasheados, cero regresión.
- Runbook del nuevo flujo de alta + bootstrap del admin de plataforma + nota explícita de deprecación (o no) del alta por seed/SQL para tenants de producción reales.

## 10. Definition of Done (fase de alta de tenant)

1. CE-88..CE-94 cumplidos y evidenciados.
2. Un **admin de plataforma interno** da de alta una **sede/tenant + su primer admin** en una **operación atómica**, sin SQL/seed manual, vía endpoint/CLI.
3. **Aislamiento desde el primer commit:** test cross-tenant verifica que el tenant nuevo no ve ni es visto por otros.
4. **Cero bypass RLS:** el `user` admin se crea con `app.tenant_id` fijado; el privilegio elevado se limita a la fila raíz `tenants` (como el seed); test lo verifica.
5. **Atomicidad:** fallo a mitad del alta → rollback total, sin tenant/admin huérfanos; test de fallo inyectado.
6. **Unicidad tipada:** colisión de slug (global) / email (por-tenant) → 409/422, nunca 500.
7. **Protección del endpoint:** solo admin de plataforma autenticado crea tenants; sin credenciales / con JWT de tenant → 401/403; test negativo.
8. **Login inmediato** del primer admin (Q3-A) por el flujo existente (SPEC-013), `rol="admin"`.
9. **Secretos seguros (C3):** passwords hasheados (SPEC-013), cero secretos en logs.
10. **Cero regresión:** login, `GET /tenants/me`, seed y fases #1–#6 intactos; suites verdes sin modificar asserts.
11. **Alcance acotado:** WhatsApp en el alta, verificación de email, planes/billing, UI y autoregistro público NO implementados (OUT, §2).
12. **ADR-015 aceptado**; cobertura código nuevo ≥80%; borrado lógico C2 (`activo`) respetado.
13. **Aprobación explícita del Lead**; cambio sensible → notificación Telegram (C6); ninguna SPEC se cierra sin cumplir los CHECKPOINTS aplicables (C2/C3/C4/C6/C8).

---

## 11. ADRs recomendados

> **Se recomienda un ADR nuevo (ADR-015).** Hay una **decisión arquitectónica estructural** que XAVIER dejó explícitamente a DOCTOR STRANGE: cómo se introduce el concepto de "admin de plataforma" (hoy inexistente) y cómo el provisioning respeta la RLS efectiva. Se **heredan/consumen** ADR-004 (RLS pool-model), ADR-008 (roles BD + RLS efectiva) — **no se rediseñan**.

- **ADR-015 — Mecanismo del "admin de plataforma" y provisioning atómico de tenant + primer admin respetando RLS efectiva.**
  Decide: (a) el admin de plataforma es un **concepto separado fuera del modelo tenant-scoped** (tabla `platform_admins` sin `tenant_id`, NO en `TENANT_SCOPED_TABLES`, análoga a `tenants`), con autenticación propia acotada — **descartada** la Opción A (rol especial dentro de `users`) por mezclar el plano-plataforma con el plano-tenant y forzar ampliación/bypass de RLS; (b) la **frontera de privilegio**: la fila raíz `tenants` se crea con privilegio elevado acotado (patrón seed, sin `app.tenant_id`), el primer `user` admin se crea **bajo RLS con `app.tenant_id` fijado** (patrón `auth_service`), **prohibido bypass genérico owner** para `users`; (c) **atomicidad** tenant+admin en una sola transacción (todo o nada, sin huérfanos); (d) **bootstrap** del primer admin de plataforma por seed/CLI (mismo plano que el seed de `tenants`), no por autoregistro; (e) semántica del **`rol="admin"`** para el primer usuario del tenant (usa la columna `rol` existente). **No rediseña** ADR-004/ADR-008 (los consume). Alternativas descartadas: rol especial en `users` (Opción A, §3.2); bypass owner para crear el admin (rompe restricción dura); autoregistro público (descartado por Q1-B); verificación de email (descartada por Q3-A).

---

## 12. PREGUNTAS ABIERTAS AL LEAD

**Ninguna de alcance.** Las 4 decisiones (Q1–Q4) están resueltas y adoptadas como vinculantes (prompt §7.1). Puntos que se fijan en la SPEC/ADR-015 (con supuesto por defecto, no requieren decisión previa del Lead) salvo dos que conviene confirmar en la aprobación:

1. **Mecanismo del admin de plataforma:** decidido por DOCTOR STRANGE = **tabla `platform_admins` separada** (Opción B, §3.2/ADR-015). *El Lead puede vetar en la aprobación si prefiere la Opción A; recomendación firme = B.*
2. **UI de alta en la SPA:** por defecto **OUT** (endpoint API + CLI interno bastan para el valor, §3.5). *Si el Lead prioriza un panel admin, se añade una fase F-UI; el plan no la asume.*
3. **¿Fusionar o separar docs/runbook?** F3 fusiona pruebas+seguridad+docs (4 SPECs). *Si el Lead prefiere docs en fase propia (patrón SPEC-061/066/072), serían 5 SPECs.*
4. **Deprecar el alta por seed/SQL para producción:** recomendación = el seed **permanece** solo para demo/pruebas; el alta de producción pasa al nuevo flujo. *Se documenta en el runbook (F3); el Lead confirma la política.*

---

> **Siguiente paso:** IRON MAN presenta este PLAN-009 al Lead. El Lead debe responder **"APROBADO PLAN-009"** (o "Ajusta PLAN-009: …") antes de que DOCTOR STRANGE redacte las SPEC-073..SPEC-076 y el ADR-015. Cumple CHECKPOINT C8 (prompt registrado en `prompt-lab/prompts/PROMPT-009-ONBOARDING-MULTITENANT.md`).
