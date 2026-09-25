# SPEC-055 — `inbound_parser` extendido a `type=="audio"` + límite de duración + encolado en `stt:jobs` 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, WOLVERINE · Prioridad: ALTA · Tipo: BACKEND/INTEGRACIÓN · Fase: F2
- Deriva de: PLAN-006 (F2, §2.1/§2.8, R-66/R-70) · Clasificación: SENSIBLE (`.no-externo`) · ADR-007/ADR-013
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Extender la ingesta del canal WhatsApp para que **reconozca las notas de voz** (`type=="audio"`) en lugar de tratarlas como marcador: extraer `media_id`, `mime_type`, duración (si Meta la provee) y `wamid`; crear el `Message(tipo="audio")` **idempotente por `wamid`** (SPEC-027/ADR-007) en la `Conversation` real; disparar la descarga cifrada (SPEC-054); aplicar el **límite de duración configurable (10 min, P1)** con **descarte amable + auto-respuesta** (SPEC-029) cuando se excede; y **encolar en `stt:jobs`** con el `destino="message:{id}"` que gobierna el sink del `stt_worker` (SPEC-056). Es la **puerta de ingesta** de audio de este slice.

## Contexto

Hoy `parse_inbound_message_events` (`inbound_parser.py`) es un parser **puro**: extrae `wamid/phone_number_id/wa_id/tipo/texto`; para tipos no-texto `texto` es `None` y el worker de ingesta (`wa_inbound_worker`, SPEC-027) persiste un marcador sin descartar el mensaje. El parser **ya expone `tipo`** (`message.get("type")`), por lo que reconocer `audio` es **aditivo**: se enriquece `InboundMessageEvent` con los campos de media (`media_id`, `mime_type`, `duracion`) leyendo `message["audio"]` cuando `tipo=="audio"`. El worker de ingesta ya es idempotente por `wamid` (ADR-007, UNIQUE `uq_messages_wamid`) y ya sabe crear `Message` en la conversación real. El envío saliente con reintentos y ventana de 24h/plantilla ya existe (SPEC-029, `graph_client`), reutilizado para la auto-respuesta de descarte.

## Alcance

### IN
- **Parser extendido (aditivo):** cuando `tipo=="audio"`, `parse_inbound_message_events` extrae `media_id` (`message["audio"]["id"]`), `mime_type` y, si Meta la envía, la duración; `InboundMessageEvent` gana campos opcionales de media (`media_id`, `mime_type`, `audio_duracion_seg`). Los tipos texto/otros **no cambian** (RNF-64).
- **Worker de ingesta extendido (rama `audio`):** crea el `Message(tipo="audio", contenido=NULL)` idempotente por `wamid` (SPEC-027/ADR-007, UNIQUE) en la `Conversation` real; llama a la descarga cifrada (SPEC-054) que puebla `audio_ref`.
- **Límite de duración configurable** (por env, **default 10 min**, P1): si la duración conocida (de Meta o tras descarga/decodificación) **excede** el límite → **descarte amable**: se marca `transcripcion_estado="descartada_por_duracion"`, se envía una **auto-respuesta clara** por `graph_client` (SPEC-029: "tu nota de voz es muy larga, por favor resúmela o escríbenos tu consulta"), **NO** se encola en `stt:jobs`, y el descarte queda **auditado** (log + métrica). No es error silencioso (CE-64).
- **Encolado en `stt:jobs`** (solo si dentro del límite y con `audio_ref` presente): el job lleva `destino="message:{id}"` (contrato extendido de SPEC-056), `audio_ref`, `tenant_id` y trazabilidad. La transcripción escribirá en `Message.contenido` (SPEC-056).
- **Idempotencia (ADR-007, sin nada nuevo):** reentrega del mismo `wamid` no crea segundo `Message`, no re-descarga (guarda de SPEC-054), no re-encola si `transcripcion_estado` ya es `ok`/`descartada_por_duracion`. **Sin `call_id`** (ADR-013).

### OUT
- Descarga/almacenamiento del binario en sí (SPEC-054, invocada aquí).
- Transcripción y sink de escritura (SPEC-056); enriquecimiento (SPEC-057).
- Media de WhatsApp que no sea audio (imágenes/documentos/vídeo): siguen como marcador, sin cambio.

## Dependencias
- Depende de SPEC-053 (`Message` tipo `audio`), SPEC-054 (descarga cifrada → `audio_ref`) y reutiliza SPEC-027 (ingesta idempotente por `wamid`) y SPEC-029 (auto-respuesta). Produce el job que consume SPEC-056. Se ancla en ADR-007 (idempotencia `wamid`) y ADR-013 (modela `Message`, no `call`).

## Requisitos funcionales
- RF-01 El parser reconoce `type=="audio"` y extrae `media_id`/`mime_type`/duración; los tipos texto/otros no cambian.
- RF-02 Se crea un `Message(tipo="audio")` idempotente por `wamid` en la conversación real; una reentrega del mismo `wamid` no crea un segundo mensaje.
- RF-03 Una nota dentro del límite se **encola** en `stt:jobs` con `destino="message:{id}"` y `audio_ref`.
- RF-04 Una nota que **excede** el límite (10 min, env) dispara **auto-respuesta** (SPEC-029), **no** se encola STT, y el descarte queda auditado (`transcripcion_estado="descartada_por_duracion"`).
- RF-05 El límite de duración es **configurable por env** con default 10 min.

## Requisitos no funcionales
- RNF-64 La rama `audio` es **aditiva**; los WhatsApp de texto (#3) siguen el camino actual sin cambio; suites #3 verdes.
- RNF-65 El descarte por duración es **amable y auditado** (auto-respuesta + log/métrica), nunca un error silencioso ni un job STT desproporcionado.
- RNF-41 Ninguna salida externa nueva desde el parser/worker de ingesta salvo la auto-respuesta por el transporte ya autorizado (`graph.facebook.com`, SPEC-029/ADR-006).

## Criterios de aceptación (verificables)
- [ ] Un webhook con `type=="audio"` crea un `Message(tipo="audio", contenido=NULL)` idempotente por `wamid` y dispara la descarga (SPEC-054).
- [ ] Una nota dentro del límite se **encola** en `stt:jobs` con `destino="message:{id}"` (inspección del job encolado).
- [ ] Una nota que **excede** 10 min genera **auto-respuesta** (SPEC-029), **no** encola job STT, y marca `transcripcion_estado="descartada_por_duracion"` con registro auditado (CE-64).
- [ ] Reentrega del mismo `wamid` no crea segundo `Message` ni segundo job STT (test de idempotencia, ADR-007).
- [ ] El límite es configurable por env (test con límite reducido que dispara el descarte).
- [ ] Un WhatsApp de **texto** sigue exactamente el camino actual (test de no-regresión, RNF-64); suites #3 verdes.
- [ ] **No** se crea `call`/`call_transcript` ni se usa `call_id` (ADR-013).

## Notas de seguridad (C2/C3)
- C2: el `Message` de audio y el descarte respetan borrado lógico; el descarte por duración no persiste contenido de audio más allá del `audio_ref` sujeto a retención (SPEC-058).
- C3: el límite y la config de cola SOLO desde env; la auto-respuesta reutiliza el manejo de token de `graph_client` (token nunca en logs).

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: la única salida externa es la **auto-respuesta** por el transporte ya autorizado (`graph.facebook.com`, SPEC-029/ADR-006) — sin egress nuevo. El audio nunca sale a un tercero; el encolado transporta solo `audio_ref` (referencia al almacén cifrado), nunca el binario.

## Riesgos
- R-66 (nota muy larga): límite configurable 10 min (P1); descarte amable + auto-respuesta; no se encola STT (chequeo antes de encolar).
- R-65 (idempotencia `wamid`): reutiliza ADR-007/SPEC-027 sin nada nuevo; guardas de reentrega; test que no duplica.
- R-70 (regresión canal texto): rama `audio` aditiva; texto sin cambio; test de no-regresión.
- R-68 (duración desconocida): si Meta no envía la duración, el chequeo se hace tras descarga/decodificación (SPEC-054); si no se puede determinar, se transcribe y el límite se aplica sobre la duración real medida por el motor (documentado).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (secretos en env). C4 (criterios verificables). C8 (origen PLAN-006).
