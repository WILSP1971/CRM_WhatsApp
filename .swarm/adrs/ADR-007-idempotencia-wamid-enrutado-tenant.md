# ADR-007 — Idempotencia por `wamid` + enrutado `phone_number_id → tenant_id`

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-003.md` (F1/F3/F5, riesgos R-33/R-34, CE-31/CE-32), `SPEC-025`, `SPEC-027`, `SPEC-030`

- **Estado:** Aceptada
- **Fecha:** 2026-09-18

---

## Contexto

WhatsApp/Meta **reentrega webhooks** (recepción y statuses) cuando no recibe un ACK a tiempo o ante fallos
transitorios. Sin una clave de deduplicación robusta, esos reintentos crearían **mensajes/borradores/envíos
duplicados** (R-33), degradando datos y UX. Además, el sistema es **multi-tenant** y cada número de WhatsApp
pertenece a un tenant distinto: un enrutado incorrecto sería una **fuga cross-tenant** (R-34, HABEAS DATA).

Se necesita decidir (a) la **clave de idempotencia** de los eventos de WhatsApp y (b) el **mecanismo de
resolución de tenant** y fijado de RLS para el webhook, de forma verificable.

---

## Decisión

1. **Idempotencia por `wamid`:** el `wamid` (id de mensaje de WhatsApp que emite Meta) es la clave de
   deduplicación. Se aplica **restricción de unicidad a nivel de BD** sobre `messages.wamid` (SPEC-025) más
   una **guarda en el `wa_inbound_worker`** (SPEC-027). Un evento reentregado con el mismo `wamid` no crea un
   segundo mensaje/borrador/envío. Los **statuses** se concilian por el `wamid` del mensaje enviado (SPEC-030),
   con actualización idempotente.
2. **Enrutado `phone_number_id → tenant_id`:** una tabla explícita `whatsapp_accounts (phone_number_id UNIQUE,
   tenant_id, ...)` bajo RLS (SPEC-025) resuelve el tenant del **número receptor**. El worker **fija el
   `tenant_id` de sesión (RLS FORCE, ADR-004) ANTES de cualquier escritura**; nunca cruza tenants.
3. **Descarte auditado sin mapeo:** un `phone_number_id` sin fila en `whatsapp_accounts` produce **descarte
   con registro de auditoría** y **cero** persistencia de contenido.

---

## Alternativas consideradas

| Alternativa | Por qué se descartó |
| ----------- | ------------------- |
| **Dedup por hash del payload** | **Frágil:** cambios menores/no significativos del payload (orden, campos opcionales) generan hashes distintos y no deduplican; el `wamid` es el identificador estable y oficial de Meta. |
| **Tenant por cabecera HTTP** | **No fiable/spoofable:** una cabecera puede falsificarse; el enrutado debe basarse en el `phone_number_id` del payload firmado (HMAC) contra una tabla controlada. |
| **Dedup solo en el worker (sin unicidad en BD)** | Sin la restricción de BD, una condición de carrera entre workers podría insertar duplicados; la unicidad en BD es la garantía dura. |
| **Un tenant global / sin RLS para el webhook** | Rompe el aislamiento multi-tenant; inaceptable por HABEAS DATA. |

---

## Consecuencias

**Pros**
- Reintentos de Meta **no duplican** datos (idempotencia garantizada por BD + worker).
- Enrutado multi-tenant **explícito y auditable**; RLS fijada antes de escribir evita fugas cross-tenant.
- Descarte auditado da trazabilidad de eventos sin mapeo, sin persistir contenido indebido.

**Cons / mitigaciones**
- La unicidad de `wamid` exige manejar el conflicto (upsert/ignore) con cuidado → definido en SPEC-027/030.
- La tabla de routing debe mantenerse al alta de cada número → seed + runbook (SPEC-025/034).
- Statuses fuera de orden → actualización idempotente (última-gana/monotónica) definida en SPEC-030.

**Criterio de verificación (objetivo y verificable)**
- **Idempotencia:** un webhook reentregado con el mismo `wamid` **no** crea un segundo mensaje/borrador/
  envío (test de duplicado, SPEC-033).
- **Cross-tenant:** un evento con `phone_number_id`/`wamid` de otro tenant **falla** por RLS/enrutado (test
  cross-tenant que debe fallar, SPEC-033); sin mapeo → descarte auditado sin persistir contenido.
- El fijado de `tenant_id` de sesión ocurre **antes** de cualquier `INSERT` (verificable en código/tests).

---

## Referencias

- `PLAN-003.md` — F1/F3/F5, riesgos **R-33** (idempotencia), **R-34** (cross-tenant), **CE-31**/**CE-32**, DoD §3/§4.
- `SPEC-025` — Datos: `whatsapp_accounts` + `wamid` único + RLS.
- `SPEC-027` — Ingesta idempotente + enrutado tenant + fijado RLS.
- `SPEC-030` — Statuses conciliados por `wamid`.
- Relacionado: **ADR-004** (RLS multi-tenant pool-model), **ADR-006** (excepción de egress transporte).
