# SPEC-053 — Modelo de datos: extensión aditiva de `Message` para nota de voz de WhatsApp (tipo `audio` + `audio_ref`) 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, WOLVERINE · Prioridad: ALTA · Tipo: DATOS/BACKEND · Fase: F0
- Deriva de: PLAN-006 (F0, §3.5) · Clasificación: SENSIBLE (`.no-externo`) · ADR-008/ADR-009/ADR-013
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Extender el modelo `messages` (SPEC-012/015/018/025) de forma **aditiva y mínima** para que una **nota de voz de WhatsApp** se modele como un `Message` real dentro de su `Conversation` (Entregable #3), **NO** como una entidad `call`/`call_transcript` (ADR-013): añadir un discriminador de tipo que admita `audio`, una referencia opaca `audio_ref` al almacén cifrado (SPEC-035), y campos opcionales de estado de transcripción/duración; y hacer `messages.contenido` **nullable** para poder crear el `Message` de audio antes de que exista su transcripción. Migración Alembic **aditiva** con head único, RLS heredada intacta, borrado lógico (C2), seed ficticio.

## Contexto

El modelo `Message` actual (`app/models/message.py`) tiene `contenido: Text NOT NULL`, `wamid` UNIQUE (idempotencia ADR-007), `remitente`, `sentimiento`/`sentimiento_score` (SPEC-018), `estado_entrega` y RLS FORCE por `tenant_id` (TenantMixin/SoftDeleteMixin, ADR-008). **No existe hoy una columna de tipo/`kind`** (R-68 del plan): el discriminador debe **añadirse**. Un `Message(tipo="audio")` nace **sin contenido** (la transcripción llega después, SPEC-056), por lo que `contenido` debe pasar a **nullable** — cambio aditivo/relajante que no afecta a los mensajes de texto existentes (siguen poblando `contenido`). El Entregable #4 modeló la voz telefónica como `call`/`call_transcript`; **esta SPEC no las crea ni las reutiliza** (ADR-013): la nota de voz vive en `messages`.

## Alcance

### IN
- Nueva columna `messages.tipo` (`String`, nullable, default lógico `"texto"`): admite al menos `"texto"` y `"audio"`. Se documenta el conjunto de valores válidos en el modelo (constante análoga a `SENTIMIENTOS_VALIDOS`/`ESTADOS_ENTREGA_VALIDOS`). Los mensajes de texto existentes quedan como `"texto"` (o `NULL` interpretado como `"texto"` por la capa de servicio — a fijar en la migración; se prefiere backfill lógico a `"texto"` sin reescritura destructiva).
- `messages.contenido` pasa a **nullable** (relajación de constraint): un `Message(tipo="audio")` se crea con `contenido = NULL` hasta que SPEC-056 escribe la transcripción. Los mensajes de texto siguen poblando `contenido`.
- Nueva columna `messages.audio_ref` (`String`, nullable): referencia **opaca** al almacén cifrado on-prem (`audio_store.py`, SPEC-035), mismo patrón que `calls.audio_ref`. `NULL` para mensajes de texto.
- Nuevas columnas opcionales de observabilidad (nullable): `messages.transcripcion_estado` (`"pendiente"` | `"ok"` | `"descartada_por_duracion"` | `"error"`) y `messages.audio_duracion_seg` (entero/numérico). Constantes de valores válidos documentadas en el modelo.
- **Migración Alembic aditiva** versionada con **head único** derivado del head actual (sin ramas divergentes); columnas nullable; sin backfill destructivo; RLS/`TenantMixin`/`SoftDeleteMixin` heredados sin cambio.
- Seed ficticio de una nota de voz (un `Message(tipo="audio", contenido=NULL, audio_ref="<placeholder>", transcripcion_estado="pendiente")`) en una conversación de WhatsApp de prueba, sin datos reales ni secretos.
- Borrado lógico (C2) heredado de `SoftDeleteMixin` sobre el `Message` de audio (sin columna nueva).

### OUT
- Descarga/almacenamiento del binario (SPEC-054); parser/encolado (SPEC-055); worker STT/sink (SPEC-056); enriquecimiento (SPEC-057); retención (SPEC-058); SPA (SPEC-059).
- **Cualquier tabla `call`/`call_transcript`**: NO se crean ni se tocan (ADR-013).
- Media de WhatsApp que no sea `audio` (imágenes/documentos/vídeo): fuera; el discriminador admite el valor pero solo `audio` se activa aguas abajo.

## Dependencias
- Depende de SPEC-012 (esquema/RLS/pgvector) y SPEC-025 (contrato `messages`/`wamid`). Prerequisito duro de SPEC-054..058. Se ancla en ADR-008 (RLS efectiva), ADR-007 (idempotencia por `wamid`) y ADR-013.

## Requisitos funcionales
- RF-01 `messages` admite `tipo="audio"` con `audio_ref` opcional y `contenido` nullable, bajo RLS FORCE por `tenant_id`.
- RF-02 La migración aplica (`upgrade`) y revierte (`downgrade`) limpio, con **head único** desde el head actual.
- RF-03 Los mensajes de texto existentes quedan intactos (`tipo="texto"`, `contenido` poblado, `audio_ref=NULL`); ninguna suite de #1–#4 rompe.
- RF-04 `transcripcion_estado`/`audio_duracion_seg` quedan disponibles como estado opcional del ciclo de vida de la transcripción.

## Requisitos no funcionales
- RNF-64 Migración **aditiva no destructiva**; los mensajes de texto (#3) siguen exactamente igual; suites #1–#4 verdes tras aplicarla.
- RNF-47 Aislamiento multi-tenant: el `Message` de audio y su `audio_ref` viven bajo la misma RLS efectiva que cualquier `Message` (rol app no-superusuario, ADR-008); ningún tenant lee el `audio_ref`/transcripción de otro.
- RNF-07 `alembic heads` devuelve un único head; sin ramas divergentes.

## Criterios de aceptación (verificables)
- [ ] `alembic upgrade head` aplica la migración sin error; `downgrade` la revierte; `alembic heads` devuelve **un único head**.
- [ ] `messages.contenido` es **nullable** tras la migración; un `Message(tipo="audio", contenido=NULL)` se inserta sin violar constraint.
- [ ] `messages.tipo` admite `"texto"`/`"audio"`; los mensajes preexistentes quedan como `"texto"` (o NULL tratado como texto por la capa de servicio, documentado).
- [ ] `messages.audio_ref`, `messages.transcripcion_estado`, `messages.audio_duracion_seg` existen como columnas **nullable**.
- [ ] RLS efectiva: con el **rol app no-superusuario** (ADR-008), una sesión de tenant A no lee el `Message`/`audio_ref` de audio de tenant B (test cross-tenant que **falla** por RLS).
- [ ] El `Message` de audio soporta borrado lógico (Activo/Inactivo); las consultas excluyen inactivos.
- [ ] Seed ficticio de nota de voz disponible; sin datos reales/secretos; **NO** se crean tablas `call`/`call_transcript`.
- [ ] Suites #1/#2/#3/#4 verdes tras aplicar la migración (sin regresión, RNF-64).

## Notas de seguridad (C2/C3)
- C2: el `Message` de audio y su `audio_ref` respetan borrado lógico; sin DELETE físico (la purga por retención se define en SPEC-058, extiende SPEC-041).
- C3: sin secretos en la migración/seed; solo placeholders de prueba; el `audio_ref` es una referencia opaca, nunca un binario ni una URL externa.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): esta SPEC es solo de datos; no introduce salidas externas. El `tenant_id` + RLS FORCE efectiva es la base del aislamiento cross-tenant del audio/transcripción de mensajería (posible PHI, ADR-008/ADR-009). El `audio_ref` referencia el almacén cifrado on-prem (SPEC-035), jamás un tercero.

## Riesgos
- R-68 (`Message` sin campo de tipo previo): se **añade** columna `tipo` nullable con default lógico `"texto"`; migración aditiva; sin reescritura destructiva.
- R-70 (regresión canal texto #3): `contenido` pasa a nullable (relajación, no rompe texto); columnas nuevas nullable; test de no-regresión de un WhatsApp de texto.
- R-47 (fuga cross-tenant): RLS FORCE efectiva con rol app no-superusuario (ADR-008); test cross-tenant (SPEC-060).
- R-49 (regresión #1–#4): migración aditiva, head único, suites verdes.

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-006).
