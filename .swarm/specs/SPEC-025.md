# SPEC-025 — Datos del canal WhatsApp: routing `phone_number_id→tenant_id` + `wamid`/estado en `messages`

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, WOLVERINE · Prioridad: ALTA · Tipo: DATOS/BACKEND · Fase: F1
- Deriva de: PLAN-003 (F1) · Clasificación: SENSIBLE (`.no-externo`) · ADR-007

## Objetivo

Extender el modelo de datos para soportar el canal WhatsApp: crear la tabla de routing `whatsapp_accounts (phone_number_id, tenant_id, ...)` con RLS y añadir `wamid` + estado de transporte a `messages`, mediante **migración Alembic aditiva** con **head único** desde el head actual, respetando borrado lógico (C2).

## Contexto

El dominio ya es agnóstico de canal (`conversations.canal` es `String(50)`; añadir `whatsapp` no rediseña el dominio). `messages` ya modela `remitente`, `sentimiento`/`sentimiento_score` (SPEC-018) y `estado_entrega` (SPEC-015). Esta SPEC **extiende** ese contrato con la identidad del mensaje de WhatsApp (`wamid`) y el enrutado multi-tenant por número receptor, sin romper lo existente.

## Alcance

### IN
- Tabla `whatsapp_accounts (id, phone_number_id UNIQUE, tenant_id, activo, timestamps, ...)` con RLS FORCE por `tenant_id`.
- Campos nuevos en `messages`: `wamid` (identidad del mensaje de WhatsApp, con restricción de unicidad para idempotencia) y estado de transporte (mapeado a `estado_entrega`).
- Migración Alembic versionada con **head único** derivado del head actual (no ramas divergentes).
- Seed de routing ficticio (phone_number_id de prueba → tenant de prueba) para el simulador.
- Borrado lógico (C2) en `whatsapp_accounts`.

### OUT
- Lógica del webhook (SPEC-026), ingesta/dedup runtime (SPEC-027), envío (SPEC-029).
- Auditoría del descarte sin mapeo (SPEC-027).

## Dependencias
- Depende de SPEC-024 (infra) y SPEC-012 (esquema/RLS/pgvector). Prerequisito duro de SPEC-026/027/029/030. Se ancla en ADR-007.

## Requisitos funcionales
- RF-01 Existe `whatsapp_accounts` con mapeo único `phone_number_id → tenant_id` bajo RLS.
- RF-02 `messages` admite `wamid` único y estado de transporte sin romper el contrato existente.
- RF-03 La migración aplica y revierte limpio, con head único desde el head actual.

## Requisitos no funcionales
- RNF-04 Aislamiento multi-tenant: `whatsapp_accounts` bajo RLS; ningún tenant ve el mapeo de otro.
- RNF-07 Migración aditiva no destructiva; suites #1/#2 verdes tras aplicarla.

## Criterios de aceptación (verificables)
- [ ] `alembic upgrade head` aplica la migración sin error; `downgrade` la revierte.
- [ ] `alembic heads` devuelve **un único head** (sin ramas divergentes).
- [ ] `whatsapp_accounts.phone_number_id` tiene restricción de unicidad; `messages.wamid` tiene restricción de unicidad (base de idempotencia).
- [ ] RLS activa en `whatsapp_accounts`: una sesión de tenant A no lee filas de tenant B.
- [ ] `messages` conserva `remitente`/`sentimiento`/`estado_entrega`; no hay regresión en el contrato existente.
- [ ] Seed de routing ficticio disponible para el simulador; sin datos reales/secretos.
- [ ] `whatsapp_accounts` soporta borrado lógico (Activo/Inactivo); las consultas excluyen inactivos.

## Notas de seguridad (C2/C3)
- C2: `whatsapp_accounts` con borrado lógico; sin DELETE físico.
- C3: sin secretos en la migración/seed; solo placeholders de prueba.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): esta SPEC es solo de datos; no introduce salidas externas. El mapeo `phone_number_id→tenant_id` es la base del aislamiento cross-tenant (ADR-007).

## Riesgos
- R-33 (idempotencia insuficiente): unicidad de `wamid` a nivel BD (ADR-007).
- R-34 (fuga cross-tenant): RLS FORCE en `whatsapp_accounts`; test cross-tenant (SPEC-033).
- R-39 (regresión #1/#2): migración aditiva, head único, suites verdes.

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-003).
