# SPEC-073 — ADR-015: mecanismo del "admin de plataforma" (`platform_admins` separado, fuera del modelo tenant-scoped) + frontera de privilegio + atomicidad tenant+admin + bootstrap + semántica `rol="admin"` — PUERTA DE DISEÑO 🔴 SENSIBLE

- Estado: CERRADA — ADR-015 aceptada por el Lead (bloque PLAN-009, 2026-09-30); puerta de diseño satisfecha, F1 (SPEC-074) puede arrancar. · Responsable: DOCTOR STRANGE · Colaboran/revisan: BLACK PANTHER, BLACK WIDOW, CAPTAIN AMERICA, WOLVERINE, HAWKEYE · Prioridad: ALTA · Tipo: ADR/DISEÑO · Fase: F0
- Deriva de: PLAN-009 (F0, §2.IN.1, §3.2, §3.3, §3.4, §4, §11, R-89/R-90/R-91/R-92/R-96, CE-88/CE-89/CE-91/CE-92/CE-93) · Clasificación: SENSIBLE (`.no-externo`) · Consume ADR-004/ADR-008 · Produce ADR-015

## Objetivo

Formalizar, en **ADR-015**, la decisión arquitectónica estructural que XAVIER dejó explícitamente a DOCTOR STRANGE: cómo se introduce el concepto de **"admin de plataforma"** (hoy inexistente) y cómo el provisioning de un tenant nuevo + su primer admin respeta la **RLS efectiva ya existente** (ADR-004/ADR-008) **sin rediseñarla**. Es una **puerta de diseño dura**: sin ADR-015 aceptado, no arranca F2 (SPEC-075). Esta SPEC **no produce código de producción**; produce la decisión auditable que gobierna F1–F3.

## Contexto

El alta de un tenant es hoy 100% manual vía `backend/app/db/seed.py`/SQL con rol owner sin `app.tenant_id` (patrón correcto para la fila raíz `tenants`, no scoped: `rls.py:37-40`). No existe flujo administrativo de alta ni concepto de "admin de plataforma". PLAN-009 (grupo de clínicas multi-sede, NO SaaS externo) requiere alta administrativa interna atómica (tenant + primer admin) con aislamiento desde el primer commit, reutilizando ADR-004/ADR-008. Las 4 decisiones del Lead (Q1-B alta interna, Q2-A sin canal, Q3-A activación inmediata, Q4-A binario) son **vinculantes** (PLAN-009 §1). El punto de diseño abierto —mecanismo del admin de plataforma— lo resuelve esta SPEC/ADR-015. Contexto de código verificado en PLAN-009 §1.33 y en la lectura de `tenant.py`/`user.py`/`rls.py`/`seed.py`/`session.py`/`auth_service.py`/`deps.py`/`passwords.py`.

**Naturaleza de puerta de diseño (importante):** esta SPEC entrega una **decisión y su justificación** (ADR-015), no implementación. La decisión debe ser auditable (alternativas evaluadas, invariantes de seguridad explícitos) para que F1–F3 se construyan sobre una base fijada, no sobre supuestos.

## Alcance

### IN
- **Redacción y aceptación de ADR-015** (`.swarm/adrs/ADR-015-admin-plataforma-separado-provisioning-atomico-tenant-rls.md`) que decide, con justificación basada en el código real:
  - **(a) `platform_admins` como concepto separado FUERA del modelo tenant-scoped:** tabla sin `tenant_id`, **NO** en `TENANT_SCOPED_TABLES`, sin política RLS por fila, análoga a `tenants`; con autenticación propia acotada (guard `require_platform_admin` independiente del login de tenant SPEC-013). Se descarta la Opción A (rol especial dentro de `users`) por mezclar planos y forzar bypass/ampliación de RLS.
  - **(b) Frontera de privilegio (invariante que no se relaja):** la fila raíz `tenants` se crea con **privilegio elevado acotado** (patrón seed, sin `app.tenant_id`); el primer `user` admin del tenant se crea **BAJO RLS con `app.tenant_id` fijado** (patrón `auth_service`), **nunca** con bypass genérico owner.
  - **(c) Atomicidad tenant+admin:** ambas filas en una sola transacción; cualquier fallo → rollback total (sin huérfanos).
  - **(d) Bootstrap del primer admin de plataforma:** por seed/CLI de plataforma (mismo plano que el seed de `tenants`), credenciales iniciales fuera del código (C3), sin autoregistro.
  - **(e) Semántica de `rol="admin"`:** valor de texto en la columna `rol` existente de `users` (sin cambio de esquema) para el primer usuario del tenant.
- **Registro explícito de alternativas descartadas** con motivo: Opción A (rol en `users`), bypass owner para `users`, autoregistro público (Q1-B), verificación de email (Q3-A), planes/billing (Q4-A), canal en el alta (Q2-A).
- **Consumo declarado de ADR-004/ADR-008** (no se rediseñan): esta ADR se apoya en la RLS efectiva ya probada.

### OUT
- Migración/modelo de `platform_admins` y semántica implementada de `rol="admin"` (SPEC-074).
- `tenant_provisioning_service`, guard `require_platform_admin`, endpoint `POST /platform/tenants`, CLI (SPEC-075).
- Pruebas + seguridad + docs/runbook + no-regresión (SPEC-076).
- Cualquier egress nuevo (esta fase no lo introduce; §Restricción).

## Dependencias
- **Consume** ADR-004 (RLS pool-model) y ADR-008 (rol `omnicore_app` NOSUPERUSER NOBYPASSRLS + SECURITY DEFINER) — no los rediseña. Se ancla en SPEC-012 (modelo + RLS) y SPEC-013 (login + hashing). **Puerta previa dura** de SPEC-074/075/076: F1 materializa la decisión (a), F2 la (b)/(c)/(d)/(e), F3 la verifica.

## Requisitos funcionales
- RF-01 ADR-015 decide `platform_admins` separado (Opción B), con justificación explícita frente a la Opción A (rol en `users`).
- RF-02 ADR-015 fija la frontera de privilegio: privilegio elevado acotado solo para la fila raíz `tenants`; `users` siempre bajo RLS con `app.tenant_id` fijado; bypass owner PROHIBIDO para tablas scoped.
- RF-03 ADR-015 fija la atomicidad tenant+admin (una transacción, rollback total ante fallo, sin huérfanos).
- RF-04 ADR-015 fija el bootstrap del primer admin de plataforma por seed/CLI (credenciales fuera del código, sin autoregistro).
- RF-05 ADR-015 fija la semántica de `rol="admin"` (valor de texto en la columna `rol` existente, sin cambio de esquema).
- RF-06 ADR-015 lista las alternativas descartadas con motivo y declara el consumo (no rediseño) de ADR-004/ADR-008.

## Requisitos no funcionales
- RNF-DECISION La salida es una decisión arquitectónica auditable (alternativas, invariantes, consecuencias verificables), no una preferencia.
- RNF-NO-EGRESS La decisión no introduce egress nuevo: sin IA externa, sin SMTP (Q3-A), sin Meta (Q2-A); `graph.facebook.com` (ADR-006) no se toca.
- RNF-CONSISTENCIA ADR-015 es coherente con el código verificado (`tenant.py`/`user.py`/`rls.py`/`seed.py`/`session.py`/`auth_service.py`/`passwords.py`); no contradice ADR-004/ADR-008.

## Criterios de aceptación (verificables)
- [ ] Existe `.swarm/adrs/ADR-015-...md` en estado "Propuesta/Aceptada" con Contexto, Decisión, Alternativas consideradas, Consecuencias y Referencias.
- [ ] ADR-015 decide `platform_admins` separado (sin `tenant_id`, NO en `TENANT_SCOPED_TABLES`, sin RLS) y descarta explícitamente la Opción A (rol en `users`) con motivo.
- [ ] ADR-015 fija la frontera de privilegio (privilegio elevado solo para `tenants`; `users` bajo RLS con `app.tenant_id`; bypass owner prohibido).
- [ ] ADR-015 fija la atomicidad tenant+admin (una transacción, rollback total, sin huérfanos).
- [ ] ADR-015 fija el bootstrap por seed/CLI (credenciales fuera del código, sin autoregistro) y la semántica de `rol="admin"` (sin cambio de esquema en `users`).
- [ ] ADR-015 lista alternativas descartadas (rol en `users`, bypass owner, autoregistro, verificación email, planes, canal) y declara consumo de ADR-004/ADR-008 sin rediseño.
- [ ] La decisión no introduce egress nuevo; es coherente con el código verificado.

## Notas de seguridad (C2/C3)
- C2: `platform_admins` y el `user` admin nacen con borrado lógico (`activo`) previsto (materializado en SPEC-074/075); ADR-015 lo declara.
- C3: ADR-015 exige passwords hasheados (SPEC-013, bcrypt) para `platform_admins` y el `user` admin, y credenciales de bootstrap fuera del código; cero secretos en logs.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (sin egress nuevo): el alta crea la **raíz de aislamiento** (`tenants`) de una sede nueva; un fallo aquí es una fuga cross-tenant. Esta fase **NO** llama a IA externa, SMTP ni Meta; `graph.facebook.com` (ADR-006) no se toca; `check-externos-backend.sh` debe seguir verde. Ningún dominio/IP nuevo se introduce.

## Riesgos
- R-89 (**fuga cross-tenant en el alta**): ADR-015 fija que el `user` admin se crea bajo RLS con `app.tenant_id` fijado (patrón `auth_service`), no se rediseña RLS; verificado por test cross-tenant en SPEC-076. **Riesgo top.**
- R-90 (**bypass owner para `users`**): ADR-015 prohíbe explícitamente el bypass genérico; privilegio elevado solo para la fila raíz `tenants`. **Riesgo top.**
- R-92 (**superficie de abuso del endpoint**): ADR-015 fija la auth propia del admin de plataforma (independiente de SPEC-013) como control de abuso; sin credenciales → rechazo. **Riesgo top.**
- R-91 (huérfanos): ADR-015 fija atomicidad todo-o-nada.
- R-96 (bootstrap huevo-gallina): ADR-015 lo resuelve por seed/CLI, credenciales fuera del código.

## Checkpoints aplicables
- C3 (passwords hasheados + credenciales de bootstrap fuera del código). C4 (criterios verificables). C6 (cambio sensible → notificación Telegram al implementar F1–F3). C8 (origen PLAN-009 / `prompt-lab/prompts/PROMPT-009-ONBOARDING-MULTITENANT.md`). C2 declarado (borrado lógico previsto). Aprobación explícita del Lead requerida (ADR-015 aceptada al aprobar esta SPEC).
