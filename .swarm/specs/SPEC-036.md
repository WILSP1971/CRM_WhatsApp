# SPEC-036 — Datos de voz: `call` / `call_transcript` + RLS efectiva + idempotencia por `call_id`

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, WOLVERINE · Prioridad: ALTA · Tipo: DATOS/BACKEND · Fase: F1
- Deriva de: PLAN-004 (F1) · Clasificación: SENSIBLE (`.no-externo`) · ADR-008/ADR-009
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Extender el modelo de datos para soportar el canal de voz: crear las entidades `call` (metadatos de la llamada, `call_id`, enlace a conversación/contacto) y `call_transcript` (segmentos con timestamps y hablante) bajo **multi-tenant RLS FORCE efectiva** (ADR-008), con **unicidad por `call_id`** (base de idempotencia, ADR-007) y **borrado lógico** (C2), mediante **migración Alembic aditiva** con head único desde el head actual.

## Contexto

El dominio ya es agnóstico de canal (`conversations.canal` es `String(50)`; añadir `voz`/`telefonia` no rediseña el dominio). El Entregable #2 fijó el esquema multi-tenant con RLS (SPEC-012) y el Entregable #3 consolidó la **RLS efectiva** con rol app no-superusuario + `SECURITY DEFINER` (ADR-008) y el patrón de idempotencia por identificador estable (ADR-007, `wamid`). Esta SPEC replica ese patrón para la voz, aplicando la clave de idempotencia por `call_id` y enlazando la llamada al mismo bus de conversación que un mensaje de texto.

## Alcance

### IN
- Tabla `call (id, call_id UNIQUE, tenant_id, numero, direccion, duracion, estado, conversation_id?, contact_id?, audio_ref?, activo, timestamps, ...)` con RLS FORCE por `tenant_id`.
- Tabla `call_transcript (id, call_id/call_ref, tenant_id, segmentos[] {inicio, fin, texto, hablante}, idioma, modelo_stt, wer?, activo, timestamps)` con RLS FORCE por `tenant_id`.
- Restricción de **unicidad sobre `call.call_id`** (por tenant) como base de idempotencia; guarda referencial de `call_transcript` a `call`.
- Enlace opcional a `conversations` (`canal="voz"/"telefonia"`) y a `contacts`, reutilizando el contrato existente.
- Migración Alembic versionada con **head único** derivado del head actual (no ramas divergentes); seed ficticio de una llamada + transcripción.
- Borrado lógico (C2) en `call` y `call_transcript`.

### OUT
- Conector de ingesta y almacenamiento del audio (SPEC-037); worker STT que puebla los segmentos (SPEC-038).
- Política de retención/purga del audio y de la transcripción (SPEC-041).

## Dependencias
- Depende de SPEC-035 (infra) y SPEC-012 (esquema/RLS/pgvector). Prerequisito duro de SPEC-037/038/039. Se ancla en ADR-008 (RLS efectiva) y ADR-007 (idempotencia por identificador estable) y ADR-009.

## Requisitos funcionales
- RF-01 Existen `call` y `call_transcript` con `tenant_id` bajo RLS FORCE efectiva.
- RF-02 `call.call_id` es único por tenant (base de idempotencia); `call_transcript` referencia a `call`.
- RF-03 La migración aplica y revierte limpio, con head único desde el head actual.
- RF-04 `call` enlaza opcionalmente a `conversations`/`contacts` sin romper contratos existentes.

## Requisitos no funcionales
- RNF-47 Aislamiento multi-tenant: ningún tenant lee `call`/`call_transcript` de otro (RLS efectiva con rol app no-superusuario, ADR-008).
- RNF-07 Migración aditiva no destructiva; suites #1/#2/#3 verdes tras aplicarla.

## Criterios de aceptación (verificables)
- [ ] `alembic upgrade head` aplica la migración sin error; `downgrade` la revierte.
- [ ] `alembic heads` devuelve **un único head** (sin ramas divergentes).
- [ ] `call.call_id` tiene restricción de unicidad (base de idempotencia); `call_transcript` referencia a `call`.
- [ ] RLS efectiva: con el **rol app no-superusuario** (ADR-008), una sesión de tenant A no lee `call`/`call_transcript` de tenant B (test cross-tenant que **falla** por RLS).
- [ ] `call_transcript` almacena segmentos con `inicio/fin/texto/hablante` e idioma/modelo STT.
- [ ] `call`/`call_transcript` soportan borrado lógico (Activo/Inactivo); las consultas excluyen inactivos.
- [ ] Seed ficticio disponible; sin datos reales/secretos; suites #1/#2/#3 verdes.

## Notas de seguridad (C2/C3)
- C2: `call`/`call_transcript` con borrado lógico; sin DELETE físico (la purga por retención se define en SPEC-041).
- C3: sin secretos en la migración/seed; solo placeholders de prueba.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): esta SPEC es solo de datos; no introduce salidas externas. El `tenant_id` + RLS FORCE efectiva es la base del aislamiento cross-tenant del audio/transcripción (posible PHI, ADR-008/ADR-009).

## Riesgos
- R-46 (idempotencia insuficiente): unicidad de `call_id` a nivel BD (ADR-007).
- R-47 (fuga cross-tenant): RLS FORCE efectiva con rol app no-superusuario (ADR-008); test cross-tenant (SPEC-042).
- R-49 (regresión #1/#2/#3): migración aditiva, head único, suites verdes.

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-004).
