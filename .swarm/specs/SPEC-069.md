# SPEC-069 — Servicio TTS local en `ia_internal` (sin egress) + cola `tts:jobs`/throttling CPU + enganche híbrido al human-in-the-loop + subida del clip por el módulo WhatsApp (sin egress nuevo) + retención por defecto no-persistir 🔴 SENSIBLE

- Estado: APROBADA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, THOR, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: BACKEND/WORKER · Fase: F2
- Deriva de: PLAN-008 (F2, §2.IN.4/5/6/8/9, §3.1/§3.2/§3.4, §4, §6 R-81/R-84/R-86/R-88, CE-81/CE-82/CE-85/CE-86) · Clasificación: SENSIBLE (`.no-externo`) · ADR-014/ADR-005/ADR-006/ADR-009/ADR-012
- APROBADO SPEC-069 por el Lead (bloque PLAN-008) — 2026-09-28.

## Objetivo

Construir el **núcleo técnico** del Entregable #6: un **servicio/worker TTS 100% local, CPU-only**, aislado en `ia_internal` (`internal: true`, sin ruta a internet), que —con el **motor validado por SPEC-067**— toma el **guion textual aprobado** (`rag_drafts`, human-in-the-loop) y produce un **clip de audio compatible con nota de voz de WhatsApp** (OGG/Opus, transcodificado con `ffmpeg` si hace falta) **en background** dentro del techo ≤5–10 s. El servicio **no sube nada** él mismo: deja el clip en el almacén/cola local; la **subida al cliente** la realiza **solo** `app/integrations/whatsapp/` a `graph.facebook.com` (ADR-006, **sin egress nuevo**). Se encola con `tts:jobs` (Redis, patrón `stt:jobs`) con **throttling/concurrencia limitada** (dimensionado por SPEC-067) para no degradar STT batch/RAG/sentimiento. Se engancha al human-in-the-loop de forma **híbrida** (Q1-C, ADR-014): ruta por defecto = generar tras aprobar el guion; ruta opcional "escuchar antes de enviar" = generar bajo demanda para que el agente apruebe el clip. **Ningún audio se envía sin aprobación humana.** Por defecto **no se persiste** el clip.

## Contexto

Dependencia dura de **SPEC-067**: sin la decisión de motor viable en CPU cerrada, **esta SPEC no puede arrancar** (puerta previa del plan, §5). Estado y modelo de datos vienen de **SPEC-068/ADR-014** (`respuesta_modo`, `tts_estado`, `audio_salida_ref`). Patrones reutilizables verificados: `stt_worker.py` + cola `stt:jobs` (contrato con `destino`, ADR-013) como plantilla de worker aislado; `audio_store.py` cifrado (SPEC-035) para el caso de persistencia por auditoría; `app/integrations/whatsapp/` como **único** módulo con egress a `graph.facebook.com` (ADR-006/SPEC-024/054), que ya descarga media y envía saliente con human-in-the-loop (SPEC-029); `ffmpeg` presente en el stack STT para transcodificar a OGG/Opus (R-88). El invariante de aprobación se ancla al **guion** (`rag_drafts.sent_message_id` se completa solo al aprobar, SPEC-019): el TTS es una consecuencia **post-aprobación** en la ruta por defecto, y una **pre-aprobación bajo demanda** en la ruta de escucha.

**Invariante de egress (NO se toca):** el servicio TTS vive **solo** en `ia_internal internal:true`, jamás alcanza `graph.facebook.com` ni internet (simétrico al `stt_worker`); la subida del clip vive **solo** en `app/integrations/whatsapp/`. Verificación negativa en CI: el servicio TTS **no** importa ni ejecuta el cliente de subida, y ningún dominio TTS de terceros aparece.

## Alcance

### IN
- **Servicio/worker TTS local** en `ia_internal` (`internal: true`, sin egress) con el motor de SPEC-067: recibe un job, sintetiza el guion aprobado a audio es-CO y lo transcodifica a **OGG/Opus** (formato de nota de voz de WhatsApp) con `ffmpeg` si el motor no lo produce directamente. **No importa ni ejecuta** el cliente de subida a Graph API.
- **Cola `tts:jobs`** (Redis, patrón `stt:jobs`) con **throttling/concurrencia limitada** dimensionada según la medición de SPEC-067 (CE-86, R-84); generación **en background** (no bloquea al agente); job idempotente (no re-sintetizar si ya hay clip listo para el mismo guion aprobado).
- **Enganche híbrido al human-in-the-loop** (Q1-C, ADR-014), reutilizando SPEC-019/029:
  - **Ruta por defecto (aprobar el guion):** al aprobar el `rag_draft` con `respuesta_modo="audio"`, se encola la síntesis; generado el clip, se envía por el módulo WhatsApp. `tts_estado` transiciona `no_solicitado → generando → listo`/`error`.
  - **Ruta opcional "escuchar antes de enviar":** se genera el clip **bajo demanda** (sin enviar); el agente lo reproduce (SPA, SPEC-070) y aprueba/rechaza el **audio concreto**; solo tras aprobar se envía.
  - En **ambas** rutas: **ningún audio se envía sin aprobación humana** (del guion o del clip escuchado).
- **Subida del clip por el módulo WhatsApp ya autorizado** (`app/integrations/whatsapp/` → `graph.facebook.com`, ADR-006), extendiendo el envío saliente con human-in-the-loop de SPEC-029 a **media de audio** (mismo host/módulo/token) — **cero egress nuevo**.
- **Retención por defecto = no persistir** el clip (ADR-012 §5/ADR-014): el clip se genera, se sube y no queda persistido; basta el guion aprobado en `rag_drafts`/`Message`. Si por auditoría se persiste (`audio_salida_ref`), se rige por `audio_store.py` cifrado + política SPEC-041 (un solo régimen).
- **Manejo de errores/degradación:** fallo de síntesis → `tts_estado="error"`, sin bloquear el guion ya aprobado (el agente puede caer a texto); timeout > techo → política definida (según contingencia de SPEC-067/ADR-014), sin envío de audio a medias.
- **Transcodificación a OGG/Opus** con `ffmpeg` local (R-88), verificada con el simulador (SPEC-072) sin egress.

### OUT
- Prueba/decisión de motor (SPEC-067) y ADR-014/modelo de datos/config (SPEC-068) — se consumen aquí.
- SPA/UX, reproductor, feature-flag y disclaimer (SPEC-070 — esta SPEC expone el estado/clip que la SPA consume).
- Pruebas e2e/seguridad/no-regresión (SPEC-071) y docs/runbook/deploy (SPEC-072).
- Respuesta en audio a mensajes de **texto** entrantes (OUT del plan): solo cuando el entrante fue nota de voz.
- Cualquier TTS de terceros / egress nuevo (PROHIBIDO).

## Dependencias
- Depende de **SPEC-067** (motor + dimensionado de throttling; **puerta previa dura**) y **SPEC-068/ADR-014** (modelo de datos + decisión de aprobación/opt-in/no-persistencia/disclaimer). Reutiliza SPEC-019/029 (human-in-the-loop + envío saliente), SPEC-035 (`audio_store.py` cifrado, solo si se persiste), SPEC-024/054 (módulo WhatsApp/`graph.facebook.com`) y el patrón `stt:jobs`/`stt_worker`. Se ancla en ADR-005 (egress IA), ADR-006 (transporte WhatsApp), ADR-009 (audio PHI) y ADR-012 (TTS local). **Prerequisito de SPEC-070/071/072.**

## Requisitos funcionales
- RF-01 El servicio TTS local sintetiza el guion aprobado a un clip OGG/Opus es-CO en background dentro del techo (SPEC-067), corriendo en `ia_internal` sin egress.
- RF-02 La cola `tts:jobs` aplica throttling/concurrencia limitada (SPEC-067) y el job es idempotente (no re-sintetiza un clip ya listo).
- RF-03 Ruta por defecto: aprobar el guion con `respuesta_modo="audio"` encola la síntesis y, generado el clip, dispara el envío; `tts_estado` refleja el ciclo `no_solicitado→generando→listo/error`.
- RF-04 Ruta "escuchar antes de enviar": genera el clip bajo demanda sin enviar; el envío ocurre solo tras aprobación explícita del audio.
- RF-05 El clip se sube **solo** por `app/integrations/whatsapp/` a `graph.facebook.com`; el servicio TTS no importa ni ejecuta el cliente de subida.
- RF-06 Por defecto el clip no se persiste; si se persiste por auditoría, usa `audio_store.py` cifrado + SPEC-041 (`audio_salida_ref`).
- RF-07 Fallo/timeout de síntesis → `tts_estado="error"` sin enviar audio incompleto y sin bloquear el guion aprobado (fallback a texto disponible).

## Requisitos no funcionales
- RNF-01 **Cero egress de voz:** el servicio TTS no alcanza internet ni `graph.facebook.com`; TTS de terceros PROHIBIDO; `check-externos-backend.sh` en verde; test de egress vacío desde el servicio en `ia_internal` (verificado en SPEC-071).
- RNF-84 **Coste de CPU acotado:** throttling/concurrencia dimensionados por SPEC-067; la ejecución no degrada de forma inaceptable STT batch/RAG/sentimiento (umbral THOR, verificado en SPEC-071).
- RNF-47 Aislamiento multi-tenant: el guion/clip/estado viven bajo RLS efectiva (rol app no-superusuario, ADR-008); ningún tenant genera/envía audio de otro.
- RNF-88 El clip es OGG/Opus compatible con nota de voz de WhatsApp (transcodificación local con `ffmpeg`, sin egress).
- RNF-HITL **Ningún audio se envía sin aprobación humana** (guion o clip escuchado) — invariante verificable.

## Criterios de aceptación (verificables)
- [ ] El servicio TTS genera un clip OGG/Opus es-CO local en background, en `ia_internal`, con el motor de SPEC-067, dentro del techo fijado.
- [ ] Un intento de egress desde el servicio TTS a cualquier IP/dominio público **falla**; el servicio **no** importa/ejecuta el cliente de subida; ningún dominio TTS de terceros aparece; `check-externos-backend.sh` en verde.
- [ ] `tts:jobs` aplica throttling/concurrencia limitada; el job es idempotente (reintento no genera dos clips ni dos envíos).
- [ ] Ruta por defecto: aprobar el guion (`respuesta_modo="audio"`) genera y envía el clip; sin guion aprobado no se genera ni se envía nada.
- [ ] Ruta "escuchar antes de enviar": el clip se genera bajo demanda sin enviarse; el envío ocurre **solo** tras aprobación explícita del audio.
- [ ] El clip se sube **solo** por `app/integrations/whatsapp/` a `graph.facebook.com` (sin egress nuevo); no hay ruta de subida en el servicio TTS.
- [ ] Por defecto no queda clip persistido tras el envío; con persistencia por auditoría, el clip queda cifrado (`audio_store.py`) bajo SPEC-041.
- [ ] Fallo/timeout de síntesis marca `tts_estado="error"` sin enviar audio incompleto y sin bloquear el guion aprobado.

## Notas de seguridad (C2/C3)
- C2: si el clip se persiste, respeta borrado lógico/purga física de SPEC-041/058 (`audio_purged_at`); por defecto no hay clip que purgar.
- C3: sin secretos en el servicio/worker; token de Graph API solo en el módulo WhatsApp existente (no en el servicio TTS); el `audio_salida_ref` es referencia opaca, nunca binario ni URL externa.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el servicio TTS corre **solo** en `ia_internal internal:true` (sin ruta a internet); genera el clip y lo deja en almacén/cola local. La **única** salida es la subida del clip por `app/integrations/whatsapp/` a `graph.facebook.com` (ADR-006) — **transporte ya autorizado, no egress nuevo**. TTS de terceros PROHIBIDO (ADR-012).

## Riesgos
- R-81 (**fuga de egress de voz**): TTS 100% local en `ia_internal internal:true`; servicio no importa el cliente de subida; subida solo desde el módulo WhatsApp; test de egress vacío + `check-externos-backend.sh` verde. **Riesgo crítico (top-1).**
- R-84 (coste de CPU compartido): `tts:jobs` con throttling/concurrencia (SPEC-067); background; opt-in (solo se genera cuando se pide).
- R-86 (retención/PHI del clip): por defecto no persistir; si se persiste → cifrado + SPEC-041.
- R-88 (formato incompatible): transcodificación a OGG/Opus con `ffmpeg` local; verificado con el simulador (SPEC-072).
- R-82 (regresión de #4/#5/texto): todo aditivo/opt-in; el `stt_worker`/sink `message` de #5 y el envío de texto de SPEC-029 no se rompen (verificado en SPEC-071).

## Checkpoints aplicables
- C2 (borrado lógico/purga si se persiste). C3 (sin secretos). C4 (criterios verificables). C6 (servicio de voz sensible → notificación en deploy). C8 (origen PLAN-008 / `prompt-lab/prompts/PROMPT-008-TTS-NOTAS-VOZ.md`).
