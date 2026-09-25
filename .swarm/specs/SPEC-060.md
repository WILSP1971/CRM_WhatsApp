# SPEC-060 — Pruebas + seguridad + observabilidad del slice de notas de voz (cero regresión #1–#4) 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: HAWKEYE · Colaboran: THOR, BLACK PANTHER, BLACK WIDOW, WOLVERINE, CAPTAIN AMERICA · Prioridad: ALTA · Tipo: QA/PRUEBAS · Fase: F7
- Deriva de: PLAN-006 (F7, CE-61..CE-65) · Clasificación: SENSIBLE (`.no-externo`) · ADR-009/ADR-013
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Verificar el slice completo de notas de voz de WhatsApp con pruebas objetivas: **e2e** (descarga → transcripción → `Message.contenido` → enriquecimiento, cero STT/inferencia a terceros), **idempotencia por `wamid`** (no re-descarga/re-transcribe/duplica), **límite de duración** (nota > 10 min → auto-respuesta, no error silencioso, no job STT), **cross-tenant que DEBE fallar por RLS** (rol app no-superusuario, ADR-008), **prueba de egress vacío** desde `stt_worker`/IA, **allowlist de descarga** (solo `graph.facebook.com` desde el módulo WhatsApp) y **cero regresión de #1–#4** (jobs `call` de #4 intactos, WhatsApp de texto de #3 intacto). Cobertura del código nuevo **≥80%**.

## Contexto

Cierra la validación técnica del Entregable #5 usando el **simulador de nota de voz** (SPEC-061) cuando no haya WhatsApp real. Reutiliza la infra de pruebas de #2/#3/#4 (pytest, Locust, guardarraíles de egress `check-externos-backend.sh`, `test_egress_topology_guardrail.py`). Es la evidencia objetiva de CE-61..CE-65. El audio es-CO de prueba es **ficticio** (sin datos reales/PHI). El criterio de **no-regresión del sink `call`** (R-62) es el más crítico: la suite de SPEC-038 debe pasar **sin modificar sus asserts**.

## Alcance

### IN
- **e2e del slice (CE-61):** una nota de voz ficticia por WhatsApp se descarga (solo `graph.facebook.com`), se almacena cifrada, se transcribe con `faster-whisper` local (sink `message`, SPEC-056) y aparece como `Message.contenido` en la conversación real; **cero** STT de terceros.
- **Enriquecimiento reutilizado (CE-62):** la transcripción recibe sentimiento + borrador RAG **≥3 citas**; respuesta **en texto** con human-in-the-loop; **sin** TTS de salida (verificación de ausencia de audio de respuesta, ADR-013).
- **Idempotencia por `wamid` (CE-63):** reentrega del mismo `wamid` no re-descarga, no re-transcribe, no duplica `Message`/enriquecimiento; **sin `call_id`** (ADR-013).
- **Límite de duración (CE-64):** nota > 10 min → **auto-respuesta clara** (SPEC-029), **no** se encola job STT, descarte auditado (`transcripcion_estado="descartada_por_duracion"`).
- **Cross-tenant (CE-63):** una sesión de tenant A no lee el `Message`/`audio_ref` de audio de tenant B → **falla por RLS** con el rol app no-superusuario (ADR-008).
- **Egress (CE-61/CE-62):** prueba de egress **vacío** desde `stt_worker`/`ia`/workers de IA (salida pública **falla**); la función de descarga (SPEC-054) sale **solo** a `graph.facebook.com` y **no** se importa desde `stt_worker`/IA (guardarraíl de egress).
- **No-regresión de #1–#4 (CE-65):** (a) un job `call` de #4 (o sin `destino`) sigue escribiendo `CallTranscript` + `Message` de voz + pipeline IA **igual** que antes (la suite de SPEC-038 corre **sin modificar asserts**); (b) un WhatsApp de **texto** de #3 sigue igual; suites #1–#4 verdes.
- **Observabilidad:** métricas de descargas de media, transcripciones de mensajería (sink `message`), descartes por límite, RTF reutilizado, tasa de error — por tenant.
- **Cobertura** del código nuevo **≥80%**.

### OUT
- Implementación del simulador en sí (SPEC-061); implementación de controles (SPEC-053..059).

## Dependencias
- Depende de SPEC-053..059 (slice completo) y del simulador (SPEC-061). Se ancla en ADR-009 y ADR-013.

## Requisitos funcionales
- RF-01 Existe suite de tests del slice de notas de voz (e2e, idempotencia `wamid`, límite, cross-tenant, egress, no-regresión).
- RF-02 La suite verifica el sink `message` (transcripción en `Message.contenido`) y la **no-regresión** del sink `call`.
- RF-03 El e2e cubre el ciclo hasta el human-in-the-loop (nada se envía autónomamente; respuesta solo texto).

## Requisitos no funcionales
- RNF-62 **Cero regresión** del sink `call`: la suite de SPEC-038 pasa **sin modificar sus asserts** (evidencia dura de R-62).
- RNF-41 Evidencia de cero audio/inferencia a terceros (prueba de egress vacío desde `stt_worker`/IA); descarga solo a `graph.facebook.com` desde el módulo WhatsApp.
- RNF-07 Cobertura backend del código nuevo ≥ 80%; suites #1–#4 verdes; `docker compose up` reproducible sin internet de inferencia.

## Criterios de aceptación (verificables)
- [ ] e2e: una nota de voz ficticia se descarga (solo `graph.facebook.com`), transcribe local y aparece como `Message.contenido`; **cero** STT de terceros (CE-61).
- [ ] La transcripción recibe sentimiento + borrador RAG **≥3 citas**; respuesta **en texto** con human-in-the-loop; **sin** TTS (CE-62/ADR-013).
- [ ] Reentrega por `wamid` no re-descarga/re-transcribe/duplica; **sin `call_id`** (CE-63).
- [ ] Nota > 10 min → **auto-respuesta**, sin job STT, descarte auditado (CE-64).
- [ ] Test cross-tenant **falla** por RLS con el rol app no-superusuario (verde = aislamiento cumplido) sobre `Message`/`audio_ref` (CE-63).
- [ ] Prueba de egress: salida desde `stt_worker`/`ia` **falla**; descarga solo a `graph.facebook.com` y no importada desde STT/IA (CE-61/CE-62).
- [ ] **No-regresión:** la suite de SPEC-038 pasa **sin modificar asserts** (job `call` escribe `CallTranscript` igual); WhatsApp de texto de #3 igual; suites #1–#4 verdes (CE-65).
- [ ] Cobertura del código nuevo ≥ 80%; métricas de descargas/transcripciones-mensajería/descartes/RTF por tenant expuestas.
- [ ] `check-externos-backend.sh` en verde.

## Notas de seguridad (C2/C3)
- C3: tests no exponen secretos; usan simulador/audios ficticios/placeholders.
- C2: tests verifican borrado lógico y purga por retención (SPEC-058) donde aplica.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (verifica egress): esta SPEC PRUEBA el invariante del slice (ADR-009/ADR-013): STT/IA sin salida; audio nunca a terceros; descarga solo a `graph.facebook.com` desde el módulo WhatsApp (sin egress nuevo); respuesta solo texto (sin TTS). La prueba de egress vacío es evidencia obligatoria del DoD.

## Riesgos
- R-61/R-62/R-63/R-64/R-65/R-66/R-67/R-70: cada uno cubierto por su test (egress/allowlist, no-regresión sink `call`, cifrado/cross-tenant, retención, idempotencia `wamid`, límite de duración, URL expirada, regresión canal texto).

## Checkpoints aplicables
- C2 (borrado lógico/purga). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-006).
