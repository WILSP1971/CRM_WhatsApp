# SPEC-027 — Ingesta idempotente + enrutado multi-tenant (`wa_inbound_worker`)

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, WOLVERINE · Prioridad: CRÍTICA · Tipo: BACKEND · Fase: F3
- Deriva de: PLAN-003 (F3) · Clasificación: SENSIBLE (`.no-externo`) · ADR-007

## Objetivo

Implementar el `wa_inbound_worker` que consume la cola `wa:inbound`, **deduplica por `wamid`**, resuelve `phone_number_id → tenant_id`, **fija el `tenant_id` de sesión (RLS)** antes de escribir, y persiste contacto/conversación/mensaje con `canal="whatsapp"`; sin mapeo → **descarte auditado**. Nunca cruza tenants.

## Contexto

Reutiliza el patrón cola Redis + worker del Entregable #2 (`rag_ingest_worker`, `sentiment_worker`). El evento crudo lo encola SPEC-026. La resolución de tenant usa `whatsapp_accounts` (SPEC-025). El fijado RLS ocurre **antes** de cualquier escritura para garantizar aislamiento (ADR-004/ADR-007).

## Alcance

### IN
- Consumidor de `wa:inbound` con reintentos idempotentes.
- Dedup por `wamid`: guarda en worker + restricción única de BD (SPEC-025); un evento reentregado no crea mensaje/borrador/envío duplicado.
- Resolución `phone_number_id → tenant_id` vía `whatsapp_accounts`; fijado RLS de sesión antes de escribir.
- Persistencia de contacto/conversación/mensaje con `canal="whatsapp"`, `wamid`, estado de transporte; borrado lógico (C2).
- Sin mapeo `phone_number_id` → **descarte auditado** (log/registro), sin persistir contenido.

### OUT
- Disparo del pipeline IA (SPEC-028; el worker lo encola pero la lógica de sentimiento/RAG es de esa SPEC).
- Envío saliente (SPEC-029) y statuses (SPEC-030).

## Dependencias
- Depende de SPEC-026 (evento encolado) y SPEC-025 (routing/`wamid`). Prerequisito de SPEC-028. Se ancla en ADR-007.

## Requisitos funcionales
- RF-01 Un evento con `wamid` nuevo se persiste una sola vez como mensaje `canal="whatsapp"`.
- RF-02 Un evento reentregado con el mismo `wamid` NO crea mensaje duplicado (idempotencia).
- RF-03 El mensaje se asigna al `tenant_id` del `phone_number_id` receptor bajo RLS.
- RF-04 Un `phone_number_id` sin mapeo se descarta y se audita, sin persistir contenido.

## Requisitos no funcionales
- RNF-04 Aislamiento multi-tenant: fijado RLS antes de escribir; ningún dato cruza tenants.
- RNF-05 Reintentos idempotentes; procesamiento asíncrono no bloqueante.

## Criterios de aceptación (verificables)
- [ ] Un evento con `wamid` nuevo crea exactamente un mensaje `canal="whatsapp"` en el tenant correcto.
- [ ] Reprocesar el mismo `wamid` (duplicado) NO crea un segundo mensaje (idempotencia verificada).
- [ ] El mensaje queda bajo el `tenant_id` resuelto por `phone_number_id`; una consulta cross-tenant NO lo ve (RLS).
- [ ] Un `phone_number_id` no mapeado produce descarte con registro de auditoría y **cero** persistencia de contenido.
- [ ] El fijado de `tenant_id` de sesión ocurre antes de cualquier `INSERT` (verificable en el código/tests).
- [ ] Un fallo transitorio del worker se reintenta sin duplicar (idempotencia end-to-end).

## Notas de seguridad (C2/C3)
- C2: mensajes/conversaciones con borrado lógico; descarte sin mapeo no persiste contenido.
- C3: config de cola/DB SOLO en env.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): el worker de ingesta procesa on-prem; no habla con Meta ni con IA externa. El enrutado por número + RLS es la barrera cross-tenant (ADR-007).

## Riesgos
- R-33 (idempotencia insuficiente): dedup por `wamid` (BD + guarda worker); test de duplicado (SPEC-033).
- R-34 (fuga cross-tenant): fijado RLS antes de escribir; descarte auditado sin mapeo; test cross-tenant (SPEC-033).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-003).
