# PLAN-008 — Entregable #6: responder con NOTA DE VOZ generada por TTS 100% LOCAL (CPU-only) a una nota de voz entrante de WhatsApp — opt-in, con aprobación humana híbrida (texto por defecto + "escuchar antes de enviar"), sin egress nuevo ni regresión del pipeline #5/texto

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Fecha: 2026-09-28 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo` presente) — el audio de salida (la voz que la empresa "dice" al cliente) es **dato personal / posible PHI**, exactamente como la nota de voz entrante de #5. Toda síntesis de voz (TTS) es **100% LOCAL, CPU-only, on-prem**: el texto de respuesta y el audio generado **NUNCA** salen a APIs externas de voz (ElevenLabs, AWS Polly, Google/Azure/OpenAI TTS, Deepgram, PlayHT y equivalentes **PROHIBIDOS**). El servicio TTS corre **SIN egress** en `ia_internal` (`internal: true`). La subida del audio a WhatsApp es **transporte acotado** ya autorizado (`graph.facebook.com`, ADR-006) desde el módulo `app/integrations/whatsapp/` — **NO hay egress nuevo**.
> Origen: `prompt-lab/prompts/PROMPT-008-TTS-NOTAS-VOZ.md` (🧠 XAVIER) · Estado: **APROBADO** por el Lead — 2026-09-28. **Disclaimer de voz sintética: SÍ, marca ligera** (p. ej. "🔊 respuesta de voz asistida") — decisión vinculante del Lead, se formaliza en ADR-014/SPEC-068 y se implementa en SPEC-070 (R-85/CE-87 ya resueltos, no reabrir).
> Regla de oro: este PLAN **NO genera SPECs**. Las SPEC se redactan como PROPUESTA y solo pasan a implementación tras la aprobación explícita del Lead ("APROBADO PLAN-008" y luego "APROBADO SPEC-XXX"). **Dos puertas obligatorias:** primero PLAN, luego SPEC.
> Precedente directo reutilizable: **PLAN-006 / SPEC-053..061 (CERRADAS)** — nota de voz entrante descargada + transcrita con STT 100% local, respondida con texto (human-in-the-loop). Este plan **cierra el bucle** añadiendo la respuesta en audio, sin tocar el flujo entrante ni el de texto. **ADR-013 §4** aplazó explícitamente el TTS de salida ("posible Entregable #6"): este plan lo **desbloquea**.
> Referencia de fase ARCHIVADA (NO código reusable): **PLAN-005 / ADR-011 / ADR-012** evaluaron Piper/Coqui, pero para un contexto **GPU compartida + tiempo real (barge-in, ≤700 ms)** que **YA NO APLICA**. Sirve solo como punto de partida de librerías candidatas, no como decisión firme ni código existente. **Residuos a limpiar/reemplazar:** `backend/app/core/config.py` líneas 420–439 (`TTS_MODE`, `PIPER_VOICE`, `TTS_VRAM_FRACTION`) asumen GPU/VRAM y **no aplican en CPU-only**.
> Contadores vigentes (`.swarm/specs.json`): `next_plan: 8`, `next_spec: 67`, `next_adr: 14`. Este plan será **PLAN-008** (número correcto, no colisiona) y **recomienda ADR-014**. `next_spec`/`next_adr` **NO se reclaman aquí**: se consumirán al crear las SPECs tras "APROBADO PLAN-008".

---

## 1. Objetivo y contexto

### Objetivo

Construir el **Entregable #6** como un **vertical slice de máximo valor / mínimo riesgo**: cuando un cliente envía una **nota de voz** por WhatsApp (ya descargada y transcrita por #5), permitir que el agente **responda con una nota de voz generada por TTS 100% local (CPU-only)** en español es-CO, de forma **opt-in** (por defecto sigue respondiendo en texto, como hoy), **conservando intacto el human-in-the-loop**: el agente **aprueba el texto/guion por defecto** y dispone de un botón opcional **"escuchar antes de enviar"** que genera y reproduce el clip bajo demanda (modelo **híbrido**). El audio se genera **en background** (techo ≤5–10 s) sin bloquear al agente, y solo se **sube al cliente por el módulo WhatsApp ya autorizado** (`graph.facebook.com`, ADR-006) — **sin egress nuevo**. Por defecto **no se persiste** el audio TTS (basta el texto/guion aprobado, que ya vive en el `Message`), salvo requisito de auditoría.

Todo es **aditivo**: no se rompe el pipeline de #5 (SPEC-053..061, CERRADAS: descarga + STT local + enriquecimiento + human-in-the-loop), ni el flujo de respuesta en texto (SPEC-029), ni los jobs `call` del Entregable #4 (ADR-013 R-62). **Antes de comprometer un motor** se ejecuta una **prueba de viabilidad en CPU (THOR)** — puerta previa dura del plan.

### Decisiones del Lead ya VINCULANTES (del prompt §7.1 — NO se reabren)

| # | Pregunta | Decisión vinculante | Consecuencia de alcance |
|---|----------|---------------------|-------------------------|
| **Q1 — Aprobación del audio** | **Opción C (híbrida):** el agente **aprueba el TEXTO/guion por defecto** (reutiliza SPEC-029); botón opcional **"escuchar antes de enviar"** que genera y reproduce el clip bajo demanda. | El human-in-the-loop se conserva sobre el **guion**; la escucha del clip es una ruta opcional. Desbloquea ADR-013 §4 → se formaliza en **ADR-014**. Dos rutas de UX a probar. |
| **Q2 — Activación** | **Opción A (opt-in):** por defecto la respuesta sigue siendo **texto** (como hoy); el agente elige explícitamente "responder con audio". **No automático.** | El audio solo se genera cuando se pide (ahorra CPU). Se añade una **acción explícita** en la UI de respuesta; el camino de texto por defecto es idéntico al actual. |
| **Q3 — Motor** | **Piper TTS** como candidato principal a validar (CPU-friendly, pre-evaluado en ADR-012), con **Coqui TTS** como comparativa de naturalidad. **Elección final sujeta a la prueba de viabilidad de THOR** (calidad es-CO + latencia real en CPU). | La SPEC del servicio TTS **no fija el motor** hasta que F0 (THOR) entregue evidencia y decisión documentada. |
| **Q4 — Techo de latencia** | **Opción (b): ≤5–10 s**, con generación **en background** sin bloquear al agente. | Coherente con Q1-C (el agente sigue trabajando mientras se genera y escucha cuando decide). El techo real se **mide** en F0 y se fija en la SPEC. |

### Contexto verificado en código (fuente de verdad, no asunciones)

- **Pipeline de #5 CERRADO (SPEC-053..061):** la nota de voz entrante se descarga desde `graph.facebook.com` (SPEC-054), se cifra en `audio_store.py` (SPEC-035), se transcribe con `stt_engine.py`/`faster-whisper` es-CO en `ia_internal` (SPEC-056, sink `message` parametrizado por `destino`), y su transcripción vive en `Message.contenido`. A partir de ahí es indistinguible de un texto y entra al pipeline IA (sentimiento SPEC-018, RAG SPEC-017, human-in-the-loop SPEC-019).
- **Respuesta hoy = solo texto (SPEC-029):** el agente aprueba un borrador (`rag_draft`, máquina de estados SPEC-019) y se envía por Graph API. **No hay audio de salida en ningún punto** (ADR-013 §4).
- **Barrera de egress ya activa y en verde:** `backend/check-externos-backend.sh` **ya bloquea TTS de terceros** por dominio (líneas 65–77: ElevenLabs, Polly, Google/Azure TTS, PlayHT, Deepgram, Coqui-cloud, etc.) y por SDK (líneas 117–121). Está verde **hoy sin código TTS** y **debe seguir verde** cuando se añada TTS local (que es on-prem, sin dominio externo). El caso peligroso acotado (`boto3.*polly`, `mutagen.*tts`) sigue vigilado por patrón de texto libre.
- **Residuos de la fase archivada (a limpiar/decidir en F1):** `config.py` líneas 420–439 tienen `TTS_MODE` (`piper`/`prerecorded`), `PIPER_VOICE` (`es_CO-pablo-medium`) y `TTS_VRAM_FRACTION` (0.3) — **asumen GPU/VRAM**. `TTS_VRAM_FRACTION` **carece de sentido en CPU-only** y debe eliminarse/reemplazarse; `PIPER_VOICE` puede reutilizarse como base pero re-validado en CPU. **NO existe código TTS funcional** en el repo (verificado en #5: `find backend/app -iname "*tts*"` → solo el `stt_worker.py` no TTS).
- **Aislamiento vigente (ADR-005/006/009):** los servicios de inferencia viven en `ia_internal internal:true` (sin ruta a internet); la descarga/subida de media de WhatsApp es exclusiva de `app/integrations/whatsapp/`. El STT no descarga ni sube; el TTS **tampoco** subirá — genera el audio y lo deja en el almacén/cola para que el módulo WhatsApp lo suba.

---

## 2. Alcance IN / OUT

### IN — entra en el Entregable #6

1. **Prueba de viabilidad de motor TTS en CPU (THOR) — puerta previa (F0):** Piper vs Coqui (y, si ambos incumplen el techo, un fallback ligero tipo eSpeak-NG como último recurso) en CPU, con voz es-CO/LatAm, sobre guiones representativos (respuestas cortas/medias/largas). Se mide **calidad subjetiva** (inteligibilidad, naturalidad, pronunciación de nombres/cifras/siglas) y **latencia real** contra el techo ≤5–10 s (Q4-b). Entregable: **decisión de motor final documentada** + evidencia reproducible + **plan de contingencia** si ningún motor cumple (ver §6 R-83).
2. **ADR-014 (F1):** "Cómo se aprueba y envía una respuesta de audio (TTS) manteniendo el human-in-the-loop" — formaliza el modelo híbrido (Q1-C: aprobar el guion por defecto, escuchar bajo demanda), el opt-in (Q2-A), la ausencia de persistencia por defecto (herencia ADR-012 §5), la decisión sobre disclaimer de voz sintética (herencia ADR-012 §4, ver §7), el motor elegido (salida de F0) y **desbloquea/supersede la parte "TTS de salida aplazado" de ADR-013 §4**.
3. **Modelo de datos aditivo (F1, si hace falta):** extensión **aditiva/nullable** para el guion/estado de generación del audio de respuesta (p. ej. `respuesta_modo` = `texto`/`audio` sobre `rag_draft`, y un `tts_estado` opcional = `no_solicitado`/`generando`/`listo`/`error` para la ruta "escuchar antes de enviar"). Sin rediseñar `Message`/`Conversation`/`rag_draft`; se lee el modelo real antes de decidir el campo exacto. Migración Alembic aditiva, sin backfill destructivo.
4. **Servicio de generación TTS local (F2):** servicio/worker aislado en `ia_internal` (`internal: true`, sin ruta a internet) que toma el texto/guion aprobado y produce un clip de audio (formato compatible con nota de voz de WhatsApp — OGG/Opus, o transcodificado localmente con ffmpeg ya presente en el stack STT) en background, con el motor elegido en F0, dentro del techo de latencia. **No sube nada** él mismo.
5. **Integración con el flujo de aprobación (F2):** enganche del TTS al human-in-the-loop existente (SPEC-019/029) **de forma híbrida** (Q1-C): (a) ruta por defecto = aprobar el guion textual, luego generar el audio en background y enviarlo; (b) ruta opcional "escuchar antes de enviar" = generar el clip bajo demanda, el agente lo reproduce y aprueba/rechaza el audio concreto antes del envío. **Ningún audio se envía sin aprobación humana.**
6. **Envío del audio por el módulo WhatsApp ya autorizado (F2):** el clip generado se sube a `graph.facebook.com` **solo** por `app/integrations/whatsapp/` (mismo host/módulo/token que ya envía texto y descarga media, ADR-006/SPEC-024/SPEC-054) — **cero egress nuevo**. Reutiliza el envío saliente con human-in-the-loop de SPEC-029 (extendido a media de audio).
7. **Frontend/UX del flujo (F3):** acción explícita **"responder con audio"** (opt-in) en la UI de respuesta; botón **"escuchar antes de enviar"** con reproductor del clip generado; estados carga/generando/listo/error **accesibles (AAA)**; por feature-flag (patrón SPEC-020/031); flag OFF = flujo de texto intacto. Marca/disclaimer de voz sintética si F1/ADR-014 lo decide.
8. **Retención mínima por defecto (F2/F4):** por defecto **no persistir** el audio TTS de salida (basta el guion aprobado en el `Message`/`rag_draft`); si por auditoría se persiste, se rige por el **mismo `audio_store.py` cifrado + política SPEC-041** (un solo régimen, herencia ADR-009/ADR-012 §5).
9. **Cola/throttling de CPU (F2, a dimensionar por THOR):** dado que la misma máquina sin GPU ya corre STT batch + RAG + sentimiento y ahora TTS, el servicio TTS se **encola** (Redis, patrón `stt:jobs`) con throttling/concurrencia limitada para no degradar el resto. La forma exacta (cola dedicada `tts:jobs` vs reutilizar el patrón existente) se fija en la SPEC según la medición de F0.
10. **Pruebas + seguridad + no-regresión (F4):** e2e opt-in (guion aprobado → audio generado local → subido por WhatsApp); **cero egress de voz** (test negativo: TTS de terceros prohibido, `check-externos-backend.sh` verde, prueba de egress vacío desde el servicio TTS en `ia_internal`); **ningún audio enviado sin aprobación** (test verificable); **cero regresión** del flujo de texto (SPEC-029), del pipeline #5 (SPEC-053..061) y de los jobs `call` de #4; cobertura del código nuevo ≥80%.
11. **Docs/runbook (F4/F5):** actualización del runbook (motor TTS elegido, techo de latencia, throttling, retención por defecto, disclaimer si aplica), limpieza documentada de los residuos de config, simulador local verificable sin internet de inferencia.

### OUT — NO entra en este slice (fase futura / decisión aparte)

- **Respuesta en audio a mensajes de TEXTO entrantes:** este Entregable #6 aplica **solo cuando el mensaje entrante fue una nota de voz** (§8 del prompt). Extender a texto entrante es decisión aparte.
- **Activación automática voz→voz (Q2-B):** fuera por decisión Q2-A (opt-in). Migrar a automático más adelante sería un slice posterior si el Lead lo valida.
- **Clonación / personalización de voz de una persona real** (riesgo de suplantación; ya OUT en ADR-012 §6).
- **Multi-idioma** más allá de español es-CO/LatAm.
- **VoiceBot conversacional en vivo / barge-in / streaming** (PLAN-005 archivado por falta de GPU — no se reabre).
- **Instagram u otros canales** (SUP-66): solo WhatsApp.
- **Persistir el audio TTS por defecto** (ADR-012 §5): no se persiste salvo requisito de auditoría explícito del Lead.

---

## 3. Arquitectura de referencia

### 3.1 Flujo end-to-end (opt-in, híbrido)

```
entrada (YA existe, #5):  nota de voz --descarga graph.facebook.com--> audio_store cifrado --STT local (ia_internal)--> Message.contenido (texto)
                          --> pipeline IA local (sentimiento SPEC-018 + RAG SPEC-017) --> borrador (rag_draft, SPEC-019)

respuesta (NUEVO, #6, OPT-IN):
  el agente ve el borrador de texto (como hoy) y ELIGE "responder con audio" (Q2-A opt-in)
      |
      +-- ruta por defecto (Q1-C, aprobar el GUION):
      |     agente aprueba el texto/guion (human-in-the-loop, SPEC-019/029)
      |     --> encola tts:jobs (Redis, throttling CPU) --> [servicio TTS LOCAL en ia_internal, sin egress]
      |     --> genera clip OGG/Opus es-CO en background (techo <=5-10s, Q4-b)  [NO sube nada]
      |     --> [app/integrations/whatsapp] sube el clip a graph.facebook.com (ADR-006, sin egress nuevo)
      |
      +-- ruta opcional "escuchar antes de enviar" (Q1-C):
            agente pulsa "escuchar" --> genera el clip BAJO DEMANDA --> reproductor en la SPA
            --> agente aprueba/rechaza el AUDIO concreto --> si aprueba, mismo envío por el módulo WhatsApp

retención: por defecto NO se persiste el clip (basta el guion aprobado). Si auditoria => audio_store cifrado + SPEC-041.
```

### 3.2 Dónde está el límite de egress (invariante de seguridad — NO se toca)

```
  red `ia_internal` (internal:true, SIN egress):
     [servicio TTS LOCAL: Piper/Coqui/... (motor de F0)]  ⛔ jamás alcanza internet — genera el clip y lo deja en almacén/cola
     [stt_worker + faster-whisper] [ia = Ollama] [rag_worker] [sentiment_worker]  ⛔ (ya vigente)

  red `app` (egress SOLO a graph.facebook.com, ADR-006):
     [app/integrations/whatsapp] --sube el clip de audio--> Meta Graph API   ►► ÚNICO egress (transporte ya autorizado)
```

- El **servicio TTS** vive **SOLO** en `ia_internal internal:true`: genera el audio y lo entrega al almacén/cola local; **NUNCA** alcanza `graph.facebook.com` ni internet. Simétrico al `stt_worker` de #5 (que recibe del almacén, no descarga).
- La **subida del clip** vive **solo** en `app/integrations/whatsapp/`, a `graph.facebook.com`. **No es egress nuevo:** mismo host/módulo/token que ya envía texto y descarga media. La verificación de CI es negativa: que el servicio TTS **no** importe/ejecute el cliente de subida, y que ningún dominio TTS de terceros aparezca.

### 3.3 Por qué NO hay egress nuevo

Igual que en #5: el clip se sube por el canal WhatsApp que **ya** tiene autorizado `graph.facebook.com` (ADR-006/SPEC-024). Subir media de audio es el **mismo host, mismo módulo, mismo token** — un verbo adicional sobre el envío que ya existe (SPEC-029/054). Por eso este plan **no requiere un ADR de egress nuevo** (a diferencia de ADR-010). La síntesis (TTS) es 100% local y on-prem, sin dominio externo.

### 3.4 El enganche al human-in-the-loop (punto de diseño central — ADR-014)

**Problema:** ¿cómo aprueba un humano un artefacto de audio antes de enviarlo? (la pregunta que ADR-013 §4 dejó abierta). **Decisión (Q1-C, ADR-014):** el invariante de aprobación se ancla al **guion textual** (que ya se aprueba hoy en SPEC-019/029), no obligatoriamente al clip. La generación del audio es una consecuencia **post-aprobación del guion** en la ruta por defecto (background, no bloquea), y una **pre-aprobación bajo demanda** en la ruta "escuchar antes de enviar". En ambos casos **ningún audio se envía sin una aprobación humana explícita**: la del guion (ruta por defecto) o la del clip escuchado (ruta opcional). El motor TTS es determinista respecto al guion aprobado, de modo que aprobar el guion ≈ aprobar lo que se dirá; la ruta de escucha cubre los casos donde la pronunciación importa (nombres, cifras, siglas).

### 3.5 Modelo de datos: extensión aditiva mínima (NO entidad nueva)

- **NO se crea entidad nueva.** El guion es el `rag_draft`/`Message` que ya se aprueba hoy.
- **Campos aditivos/nullable candidatos** (nombre exacto a fijar leyendo el modelo real en F1): `respuesta_modo` (`texto` por defecto / `audio` cuando el agente elige opt-in), y opcional `tts_estado` (`no_solicitado`/`generando`/`listo`/`error`) para la ruta "escuchar antes de enviar". Opcional `audio_salida_ref` **solo si** se persiste el clip por auditoría (por defecto NULL/ausente).
- **Migración Alembic aditiva** (nullable, sin backfill destructivo): mensajes de texto y el pipeline de #5 siguen exactamente igual (cero regresión).

---

## 4. Fases y entregables

| Fase | Nombre | Entregables clave | SPEC (propuesta) |
|------|--------|-------------------|------------------|
| **F0** | **Prueba de viabilidad de TTS local en CPU (THOR) — PUERTA PREVIA** | Piper vs Coqui (fallback ligero si ambos fallan) en CPU, voz es-CO/LatAm, sobre guiones cortos/medios/largos representativos; medición de **calidad subjetiva** (inteligibilidad/naturalidad/pronunciación) y **latencia real** vs techo ≤5–10 s (Q4-b); **decisión de motor final documentada** + evidencia reproducible + **plan de contingencia** (§6 R-83). **Gate:** sin esta decisión no arranca F2. | **SPEC-067** |
| **F1** | ADR-014 + modelo de datos aditivo | **ADR-014** (aprobación híbrida del audio + opt-in + no-persistencia por defecto + disclaimer sí/no + motor de F0; desbloquea/supersede ADR-013 §4); migración Alembic aditiva (`respuesta_modo`, `tts_estado` opcional, `audio_salida_ref` opcional); limpieza/reemplazo documentado de residuos `TTS_MODE`/`TTS_VRAM_FRACTION`/`PIPER_VOICE` en `config.py` (CPU-only). | **SPEC-068** |
| **F2** | Servicio TTS local + integración con el flujo de aprobación + envío por WhatsApp | Servicio/worker TTS en `ia_internal` (sin egress) con el motor de F0, generación en background (cola `tts:jobs` + throttling CPU); enganche híbrido al human-in-the-loop (ruta guion por defecto + ruta "escuchar antes de enviar" bajo demanda, SPEC-019/029); subida del clip **solo** por `app/integrations/whatsapp/` a `graph.facebook.com` (sin egress nuevo); retención por defecto = no persistir. | **SPEC-069** |
| **F3** | Frontend/UX del flujo opt-in "responder con audio" + "escuchar antes de enviar" | Acción explícita "responder con audio" (opt-in); botón "escuchar antes de enviar" con reproductor; estados carga/generando/listo/error **AAA**; feature-flag (SPEC-020/031), flag OFF = flujo de texto intacto; disclaimer/marca de voz sintética si ADR-014 lo decide. (SPIDER-MAN/DAREDEVIL) | **SPEC-070** |
| **F4** | Pruebas + seguridad + no-regresión | e2e opt-in (guion→audio local→subida WhatsApp); **cero egress de voz** (TTS de terceros prohibido, `check-externos-backend.sh` verde, egress vacío desde TTS en `ia_internal`); **ningún audio sin aprobación** (test); **cero regresión** de texto (SPEC-029), pipeline #5 (SPEC-053..061), jobs `call` #4; latencia dentro del techo (THOR); cobertura ≥80%. (HAWKEYE/BLACK WIDOW/WOLVERINE) | **SPEC-071** |
| **F5** | Documentación + runbook + deploy on-prem | Runbook (motor elegido, techo de latencia, throttling, retención por defecto, disclaimer si aplica), limpieza de residuos documentada, simulador local sin internet de inferencia, deploy on-prem (QUICKSILVER, con aprobación del Lead). | **SPEC-072** |

> **F5 se mantiene como fase propia** (no se absorbe en F4): la limpieza de residuos de config + runbook del motor elegido + simulador tienen entidad suficiente y son el patrón habitual del proyecto (cf. SPEC-061/066). Si el Lead prefiere compactar, F5 puede fusionarse con F4 (quedarían 5 SPECs).

---

## 5. Dependencias entre fases y ruta crítica

- **F0 (SPEC-067)** es **puerta previa dura**: sin la decisión de motor + evidencia de viabilidad en CPU no se compromete la implementación (F2). Es el mayor punto de incertidumbre del plan.
- **F1 (SPEC-068)** depende de F0 (ADR-014 registra el motor elegido) — el resto de F1 (modelo de datos, limpieza de residuos) puede adelantarse en paralelo a F0.
- **F2 (SPEC-069)** depende de F0 (motor) y F1 (ADR-014 + modelo de datos). Es el **núcleo técnico** (servicio TTS + enganche híbrido + subida sin egress nuevo).
- **F3 (SPEC-070)** depende de F2 (consume el servicio y los estados del guion/clip).
- **F4 (SPEC-071)** depende de F0/F1/F2/F3 (prueba el slice completo: aprobación, cero egress, cero regresión, latencia).
- **F5 (SPEC-072)** cierra: runbook/limpieza/simulador/deploy tras F4.

**Ruta crítica:** `F0 → F1 → F2 → F3 → F4 → F5`. La **ruta crítica dura** es **F0 (viabilidad de motor en CPU)**: si ningún motor cumple el techo con calidad aceptable, se activa el plan de contingencia (R-83) **antes** de invertir en F2–F5.

---

## 6. Riesgos y mitigaciones

| # | Riesgo | Impacto | Mitigación |
|---|--------|---------|------------|
| **R-81** | **Fuga de egress de voz** (TTS de terceros, o que el servicio TTS o el audio generado alcancen internet → rompe SENSIBLE, expone PHI de voz de salida). | **Crítico** (rompe política, PHI) | TTS **100% local** en `ia_internal internal:true` (sin ruta a internet); TTS de terceros **PROHIBIDOS** — `check-externos-backend.sh` ya los bloquea (dominios/SDK) y debe seguir verde; el servicio TTS **no importa ni ejecuta** el cliente de subida; subida **solo** desde `app/integrations/whatsapp/` a `graph.facebook.com` (ADR-006); test de egress vacío desde el servicio TTS. Hereda ADR-005/006/009/012. |
| **R-82** | **Regresión del flujo de texto (SPEC-029), del pipeline #5 (SPEC-053..061) o de los jobs `call` de #4** al añadir la ruta de audio. | Alto (rompe #4/#5/texto) | Todo es **aditivo/opt-in**: `respuesta_modo` por defecto `texto` = comportamiento actual idéntico; migración nullable; el `stt_worker`/sink `message` de #5 no se toca; test de no-regresión de respuesta en texto, de nota de voz entrante e2e (#5) y de un job `call` (#4). |
| **R-83** | **Viabilidad real de calidad/latencia en CPU** — riesgo de que **ningún motor** cumpla el techo ≤5–10 s con calidad es-CO aceptable. | Alto (podría invalidar el entregable) | F0 (THOR) es **puerta previa**. **Plan de contingencia explícito y escalonado, decisión del Lead con la evidencia de F0:** (1) **relajar el techo** a best-effort si la calidad es buena y la latencia solo algo mayor (audio asíncrono, el agente no queda bloqueado — Q1-C lo permite); (2) **degradar a un motor más ligero** (eSpeak-NG) aceptando menor naturalidad; (3) **acotar la longitud** del guion sintetizable (respuestas cortas sí, largas caen a texto); (4) como último recurso, **degradar a "solo texto"** (el pipeline de #5 sigue siendo el fallback natural) y **aplazar** el entregable. El plan NO asume que se aborta: prioriza (1)/(3) sobre abortar, pero la decisión final es del Lead con datos. |
| **R-84** | **Coste de CPU compartido** (STT batch + RAG + sentimiento + ahora TTS en la misma máquina sin GPU → contención/latencia degradada del resto). | Medio/Alto | TTS **encolado** (`tts:jobs`) con **throttling/concurrencia limitada** dimensionada por THOR (F0); generación en background (no bloquea); opt-in (solo se genera cuando se pide, ahorra CPU); prioridad de cola y límite de concurrencia fijados en SPEC-069 tras medir el impacto en el resto de workers. |
| **R-85** | **Aspectos legales de voz sintética** (Ley 1581 / herencia ADR-012 §4: una voz sintética hablando en nombre de la empresa puede requerir que el cliente sepa que es un asistente). | Medio (cumplimiento) | **El plan decide explícitamente en F1/ADR-014** (no se deja abierto): **recomendación DOCTOR STRANGE = incluir una declaración/marca ligera** (p. ej. prefijo textual o etiqueta "🔊 respuesta de voz asistida" acompañando el envío, o disclaimer configurable), **pero la decisión firme es del Lead en la aprobación de ADR-014**. En chat asíncrono con aprobación humana el riesgo es menor que en un bot en vivo, pero se documenta y se aplica lo que el Lead confirme. |
| **R-86** | **Retención/PHI del audio de salida** (si se persiste el clip, audio de voz de la empresa retenido sin cifrar/sin política). | Medio (cumplimiento) | Por defecto **no persistir** (ADR-012 §5); si por auditoría se persiste → **mismo `audio_store.py` cifrado + política SPEC-041** (un solo régimen, herencia ADR-009). Test que verifica que por defecto no queda clip persistido. |
| **R-87** | **Residuos de config de la fase archivada** (`TTS_VRAM_FRACTION`, `TTS_MODE` GPU) reutilizados por error en CPU-only. | Bajo/Medio | F1 **limpia/reemplaza** explícitamente los residuos (líneas 420–439 de `config.py`); `TTS_VRAM_FRACTION` se elimina (sin sentido en CPU); `PIPER_VOICE` re-validado en CPU por F0; documentado en el runbook (F5). |
| **R-88** | **Formato del clip incompatible** con nota de voz de WhatsApp (Meta espera OGG/Opus para voz). | Bajo | Generar/transcodificar localmente a OGG/Opus con ffmpeg (ya presente en el stack STT de #5); verificado en F2 con el simulador. Sin egress. |

**Top-3:** **R-81 (fuga de egress de voz — PROHIBIDO)**, **R-83 (viabilidad calidad/latencia en CPU — con plan de contingencia)**, **R-82 (regresión de #4/#5/texto)**. R-84 (CPU compartido) y R-85 (voz sintética/legal) inmediatamente detrás.

---

## 7. Criterios de éxito verificables (CE-81..CE-87 — continúan tras CE-77 de PLAN-007)

> Base: CE-1..CE-6 del prompt §6, renumerados correlativamente para no colisionar con PLAN-007 (último CE = CE-77).

| ID | Criterio | Cómo se verifica | Fase |
|----|----------|------------------|------|
| **CE-81** | **Aprobación humana del audio (híbrida):** ningún audio llega al cliente sin la aprobación humana definida en ADR-014 (guion por defecto, o clip escuchado en la ruta "escuchar antes de enviar"). | Test e2e: un envío de audio sin guion/clip aprobado **falla**; se verifican ambas rutas (guion y escucha). | F2/F4 |
| **CE-82** | **100% local, cero egress de voz:** un intento de salida de voz/inferencia TTS a cualquier dominio/IP público **falla**; `check-externos-backend.sh` en verde con TTS de terceros prohibido; egress vacío desde el servicio TTS en `ia_internal`. | Test negativo + captura de red + script verde. | F2/F4 |
| **CE-83** | **Cero regresión:** la respuesta en texto (SPEC-029), el pipeline de nota de voz entrante (#5, SPEC-053..061) y los jobs `call` (#4) siguen funcionando sin cambio de comportamiento; suites existentes pasan sin modificar asserts. | Suites #4/#5/texto verdes; no-regresión e2e. | F4 |
| **CE-84** | **Viabilidad CPU:** existe evidencia (THOR) de que el motor elegido genera voz es-CO inteligible dentro del techo ≤5–10 s (Q4-b) en CPU, sobre guiones representativos; o, si no se cumple, el plan de contingencia (R-83) se aplicó con decisión del Lead. | Informe de F0 con métricas de calidad + latencia + decisión de motor/contingencia. | F0 |
| **CE-85** | **Opt-in + aditivo:** por defecto la respuesta sigue siendo texto (Q2-A); el audio solo se genera al elegir "responder con audio"; la migración es aditiva/nullable; el clip se sube **solo** por el módulo WhatsApp; retención por defecto = no persistir. | Test de opt-in (default texto), test de migración aditiva, inspección de la subida y de la no-persistencia por defecto. | F1/F2/F4 |
| **CE-86** | **Coste de CPU acotado:** el TTS corre encolado con throttling/concurrencia limitada; su ejecución no degrada de forma inaceptable el STT batch/RAG del resto (umbral fijado por THOR). | Medición de impacto en workers concurrentes (THOR, SPEC-071). | F2/F4 |
| **CE-87** | **Voz sintética / legal resuelto (no abierto):** ADR-014 decide explícitamente si aplica declaración/disclaimer (herencia ADR-012 §4, Ley 1581) y, si aplica, está implementado y verificado. | ADR-014 aceptado con la decisión del Lead + test/inspección del disclaimer si aplica. | F1/F3/F4 |

> Transversales heredados: **aprobación explícita del Lead**; CHECKPOINTS C2 (borrado lógico) / C3 (secretos) / C4 (criterios verificables) / C6 (cambio sensible → notificación Telegram) / C8 (prompt registrado en `prompt-lab/prompts/PROMPT-008-TTS-NOTAS-VOZ.md`).

---

## 8. Mapa de SPECs propuestas (SOLO el mapa — se redactan como PROPUESTA, se implementan tras "APROBADO PLAN-008")

> Continúa la numeración desde `specs.json` (`next_spec: 67`). Se crearán únicamente tras "APROBADO PLAN-008". Cada SPEC llevará criterios verificables (C4).

- **SPEC-067** — Prueba de viabilidad de TTS local en CPU (THOR): Piper vs Coqui (fallback ligero), voz es-CO, calidad subjetiva + latencia real vs techo ≤5–10 s, decisión de motor documentada + plan de contingencia. **Puerta previa** (F0).
- **SPEC-068** — ADR-014 (aprobación híbrida del audio + opt-in + no-persistencia + disclaimer + motor de F0; desbloquea ADR-013 §4) + modelo de datos aditivo (`respuesta_modo`, `tts_estado`, `audio_salida_ref` opcional) + limpieza de residuos `TTS_*` de config CPU-only (F1).
- **SPEC-069** — Servicio TTS local en `ia_internal` (sin egress) + cola `tts:jobs`/throttling CPU + enganche híbrido al human-in-the-loop (guion por defecto + "escuchar antes de enviar") + subida del clip por el módulo WhatsApp a `graph.facebook.com` (sin egress nuevo) + retención por defecto no-persistir (F2).
- **SPEC-070** — SPA/UX: acción opt-in "responder con audio" + botón "escuchar antes de enviar" + reproductor + estados AAA + feature-flag (flag OFF = texto intacto) + disclaimer si ADR-014 lo decide (F3).
- **SPEC-071** — Pruebas + seguridad + no-regresión: e2e opt-in, cero egress de voz, ningún audio sin aprobación, cero regresión #4/#5/texto, latencia/coste CPU (THOR), cobertura ≥80% (F4).
- **SPEC-072** — Documentación, runbook (motor/latencia/throttling/retención/disclaimer), limpieza de residuos, simulador local y deploy on-prem (F5).

> Total: **6 SPECs (SPEC-067..SPEC-072)** → `next_spec` pasaría a **73** al crearlas (no ahora). **ADR-014** recomendado → `next_adr` pasaría a **15** al crearlo. Si F5 se fusiona con F4 (§4), serían 5 SPECs.

---

## 9. Entregables finales del Entregable #6

- Servicio de **generación TTS 100% local (CPU-only)** en `ia_internal` (sin egress), con el motor validado por THOR (F0).
- **ADR-014** que formaliza la aprobación híbrida del audio (guion por defecto + escuchar bajo demanda), el opt-in, la no-persistencia por defecto y la decisión sobre disclaimer; **desbloquea/supersede** el TTS de salida aplazado en ADR-013 §4.
- Integración con el **human-in-the-loop existente** (SPEC-019/029): ningún audio se envía sin aprobación.
- **Subida del clip por el módulo WhatsApp ya autorizado** (`graph.facebook.com`, ADR-006) — **cero egress nuevo**.
- **SPA/UX opt-in** "responder con audio" + "escuchar antes de enviar" con estados AAA por feature-flag; flag OFF = flujo de texto intacto.
- **Cola/throttling** de TTS dimensionada para no degradar el resto del sistema CPU-only.
- Limpieza documentada de los **residuos `TTS_MODE`/`TTS_VRAM_FRACTION`/`PIPER_VOICE`** de la fase GPU archivada.
- Suite de pruebas (e2e opt-in, cero egress de voz, ningún audio sin aprobación, cero regresión #4/#5/texto, latencia/coste CPU) + cobertura ≥80%.
- **Evidencia auditable:** cero egress de voz, `check-externos-backend.sh` verde, aislamiento del servicio TTS, no-persistencia del clip por defecto, no-regresión de #4/#5/texto.
- Runbook + simulador local; deploy on-prem con aprobación del Lead.

## 10. Definition of Done (Entregable #6)

1. CE-81..CE-87 cumplidos y evidenciados.
2. Respuesta en **nota de voz TTS 100% local (CPU-only)** a una nota de voz entrante, **opt-in** (default texto), con voz es-CO.
3. **Human-in-the-loop intacto:** ningún audio se envía sin aprobación humana (guion por defecto o clip escuchado); test verificable.
4. **Cero egress de voz:** TTS de terceros prohibido, `check-externos-backend.sh` verde, egress vacío desde el servicio TTS en `ia_internal`; subida **solo** a `graph.facebook.com` desde el módulo WhatsApp (sin egress nuevo).
5. **Viabilidad CPU probada** (THOR): motor elegido dentro del techo ≤5–10 s con calidad es-CO aceptable; o plan de contingencia (R-83) aplicado con decisión del Lead.
6. **Cero regresión:** flujo de texto (SPEC-029), pipeline #5 (SPEC-053..061) y jobs `call` (#4) intactos; suites verdes.
7. **Coste de CPU acotado:** TTS encolado con throttling; no degrada de forma inaceptable el resto (umbral THOR).
8. **Retención por defecto = no persistir** el clip; si se persiste por auditoría → cifrado + SPEC-041.
9. **Voz sintética/legal resuelto en ADR-014** (disclaimer sí/no decidido por el Lead e implementado si aplica).
10. Residuos `TTS_*` de config limpiados/reemplazados (CPU-only); cobertura código nuevo ≥80%.
11. Secretos fuera del código/logs (C3); borrado lógico (C2); runbook + simulador entregados.
12. **ADR-014 aceptado**; deploy on-prem con **aprobación del Lead** (cambio sensible → notificación Telegram, C6).
13. **Aprobación explícita del Lead**. Ninguna SPEC se cierra sin cumplir los CHECKPOINTS aplicables (C2/C3/C4/C6/C8).

---

## 11. ADRs recomendados

> **Se recomienda un ADR nuevo (ADR-014).** A diferencia de #5 (que no requirió ADR de egress porque reutilizaba `graph.facebook.com`), aquí hay una **decisión arquitectónica de dominio no resuelta** que ADR-013 §4 dejó explícitamente abierta: cómo se aprueba y envía un artefacto de audio manteniendo el human-in-the-loop. Se **hereda** ADR-005 (aislamiento IA), ADR-006 (transporte WhatsApp — la subida del clip no es egress nuevo), ADR-009 (audio como PHI: cifrado/retención si se persiste), ADR-012 (TTS local + declaración de voz sintética — se **re-evalúa** su §4/§5 en contexto CPU-only asíncrono).

- **ADR-014 — Cómo se aprueba y envía una respuesta de audio (TTS local) manteniendo el human-in-the-loop.**
  Decide: (a) el invariante de aprobación se ancla al **guion textual** (Q1-C), con ruta opcional "escuchar antes de enviar" el clip bajo demanda; **ningún audio se envía sin aprobación humana** (del guion o del clip); (b) activación **opt-in** (Q2-A: default texto); (c) generación **en background, techo ≤5–10 s** (Q4-b), **CPU-only**, servicio aislado en `ia_internal` sin egress; (d) **motor** = el validado por la prueba de viabilidad de THOR (F0), con Piper como candidato principal y Coqui como comparativa (Q3); (e) **no persistir** el clip por defecto (herencia ADR-012 §5); si se persiste por auditoría, cifrado + SPEC-041; (f) **decisión explícita sobre declaración/disclaimer de voz sintética** (herencia ADR-012 §4, Ley 1581) — recomendación DOCTOR STRANGE = marca ligera, decisión firme del Lead. **Desbloquea/supersede** la parte "TTS de salida aplazado" de **ADR-013 §4**. Alternativas descartadas: aprobar siempre el clip escuchado (Opción B pura — más fricción/CPU, descartada por Q1-C); activación automática voz→voz (Opción B de Q2 — descartada por Q2-A opt-in); TTS de terceros (rompe SENSIBLE); persistir el clip por defecto (retención innecesaria de PHI de voz).

---

## 12. PREGUNTAS ABIERTAS AL LEAD

**Ninguna de alcance.** Las 4 decisiones (Q1–Q4) están resueltas y adoptadas como vinculantes (prompt §7.1). Puntos que se **fijan con la evidencia de F0/en la SPEC** (no requieren decisión previa del Lead, con supuesto por defecto), salvo dos que sí conviene confirmar en la aprobación:

1. **Motor TTS final:** se decide en F0/ADR-014 con la evidencia de THOR (Piper candidato principal, Coqui comparativa). *No requiere decisión previa; el Lead confirma al aprobar ADR-014.*
2. **Plan de contingencia si ningún motor cumple (R-83):** el plan prioriza relajar el techo / acotar longitud sobre abortar. *El Lead decide la vía concreta cuando F0 entregue datos — no antes.*
3. ~~Disclaimer de voz sintética (R-85/CE-87)~~ — **RESUELTO al aprobar PLAN-008: SÍ, marca ligera** (p. ej. "🔊 respuesta de voz asistida"). No se reabre; ADR-014/SPEC-068 lo formaliza, SPEC-070 lo implementa.
4. **Techo de latencia exacto dentro del rango 5–10 s:** se fija en la SPEC tras medir en F0 (p. ej. objetivo 5 s, aceptable hasta 10 s). *Supuesto por defecto; ajustable con datos.*

---

> **Siguiente paso:** IRON MAN presenta este PLAN-008 al Lead. El Lead debe responder **"APROBADO PLAN-008"** (o "Ajusta PLAN-008: …") antes de que DOCTOR STRANGE redacte las SPEC-067..SPEC-072 y el ADR-014. Cumple CHECKPOINT C8 (prompt registrado en `prompt-lab/prompts/PROMPT-008-TTS-NOTAS-VOZ.md`).
