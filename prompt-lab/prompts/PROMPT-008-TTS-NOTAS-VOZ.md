# PROMPT-008 — TTS de respuesta en notas de voz de WhatsApp (Entregable #6)

> Autor: 🧠 XAVIER (Professor X) — Estratega de Prompts (Nivel 1) · skill `optimizar-prompt`
> Fecha: 2026-09-28 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo`) — el audio (voz que la empresa "dice" al cliente) es dato personal / posible PHI.
> Marco aplicado: **C.R.A.F.T.** (Contexto · Rol · Acción · Formato · Tests)
> Destino: este prompt alimenta a 🔮 **DOCTOR STRANGE** para **PLAN-008** (NO genera SPECs por sí mismo).
> Contadores vigentes (`.swarm/specs.json`): `next_plan: 8`, `next_spec: 67`, `next_adr: 14`.
> ⚠️ **Puerta obligatoria:** este prompt NO es aprobación. Requiere PLAN-008 aprobado por el Lead y luego SPECs aprobadas antes de escribir código (CLAUDE.md del enjambre).

---

## 0. Resumen del encargo (una frase)

Habilitar que, cuando un cliente envía una **nota de voz** por WhatsApp, el agente pueda **responder con una nota de voz generada por TTS 100% local (CPU-only)**, **sin romper el human-in-the-loop** (nunca se envía nada sin aprobación humana explícita) ni el resto del pipeline ya construido (STT → sentimiento → RAG → borrador → aprobación → envío).

Este es el **P2 aplazado** en PLAN-006/ADR-013, cuyo desbloqueo depende de resolver **una pregunta de diseño concreta** (cómo aprueba un humano un artefacto de audio) — recogida en §7.

---

## 1. Contexto (verificado en el repo, no asumido)

### 1.1 Lo que YA existe (base sobre la que se construye)
- **PLAN-006 / SPEC-053..061 (CERRADAS):** una nota de voz entrante de WhatsApp se descarga (solo desde `graph.facebook.com`, ADR-006), se transcribe con **STT 100% local** (`stt_engine.py` = `faster-whisper`, invocado por `stt_worker` con sink parametrizado por `destino`, ADR-013 §2) y su transcripción se escribe en `messages.contenido` del `Message(tipo="audio")`. A partir de ahí es **indistinguible de un WhatsApp de texto** y entra al mismo pipeline (sentimiento + RAG + human-in-the-loop).
- **Respuesta HOY = solo texto (SPEC-029):** el agente ve un borrador generado por IA (RAG), lo **aprueba explícitamente** y se envía como mensaje de texto normal por Graph API — **incluso cuando el mensaje entrante fue una nota de voz** (ADR-013 §4, §2 OUT de PLAN-006). No hay audio de salida en ningún punto.
- **Human-in-the-loop (SPEC-019/029):** invariante duro — nunca se envía nada al contacto sin aprobación humana. El Lead confirmó (P2, PLAN-006) que este principio se mantiene; lo pendiente es **cómo aplicarlo a un artefacto de audio**.
- **Barrera de egress ya activa:** `backend/check-externos-backend.sh` ya **bloquea TTS de terceros** (ElevenLabs, AWS Polly, Google TTS, Azure Speech, Deepgram, etc.) por SDK y por dominio — verificado en el script (líneas 62–121, refs SPEC-044/ADR-012). Está en verde **hoy sin código TTS**, y debe seguir en verde cuando se añada TTS local.

### 1.2 Restricciones de plataforma que ya rigen TODO el proyecto
- **Máquina sin GPU (CPU-only)**, confirmado por el Lead (memoria del proyecto: `project_no_gpu_voicebot_pivot.md`). El VoiceBot en vivo (PLAN-005) fue **archivado** por esto.
- **Clasificación SENSIBLE (`.no-externo`):** toda inferencia (incluido TTS) debe ser **100% local/on-prem**. Ningún audio ni contenido de respuesta sale a APIs externas de voz. Mismo patrón que STT (ADR-009) e IA de texto (ADR-003/005).
- **Aislamiento:** los servicios de inferencia viven en `ia_internal internal:true` (sin ruta a internet); la descarga/subida de media de WhatsApp es exclusiva del módulo `app/integrations/whatsapp/` (ADR-006).

### 1.3 Referencia de una fase ARCHIVADA (NO código reusable — leer con cautela)
- **⚠️ ADR-012 / ADR-011 / PLAN-005** ya evaluaron TTS local: **Piper** (voz es-CO, o la más cercana disponible) como motor por defecto y **Coqui** como alternativa. **PERO** ese análisis se hizo para un contexto **GPU compartida + tiempo real (presupuesto ≤700 ms, barge-in)** que **YA NO APLICA**: esta fase es **CPU-only y asíncrona**. Sirve como **punto de partida de librerías candidatas** (evita repetir la investigación desde cero), **no** como decisión firme ni como código existente.
- **⚠️ `backend/app/core/config.py` (líneas 420–439)** contiene `TTS_MODE` (`piper`/`prerecorded`) y `TTS_VRAM_FRACTION` **residuales de la fase archivada** (asumen GPU/VRAM). **NO se reutilizan tal cual** — `TTS_VRAM_FRACTION` carece de sentido en CPU-only. Se citan solo para que PLAN-008 decida si limpiarlos/reemplazarlos.
- **NO existe ningún código de TTS funcional en el repo** (verificado: `find backend/app -iname "*tts*"` → vacío; PLAN-005 llegó solo a F0/infra y quedó archivado).

### 1.4 Herencia relevante de ADR-012 que probablemente siga aplicando (a confirmar en PLAN-008)
- **Declaración de voz sintética / anti-deepfake (ADR-012 §4, Ley 1581):** una voz sintética hablando en nombre de la empresa puede requerir que el cliente sepa que es un asistente virtual. En chat asíncrono con aprobación humana el riesgo es menor que en un bot en vivo, pero **PLAN-008 debe decidir explícitamente** si aplica alguna declaración/etiqueta (p. ej. marca textual "🔊 respuesta de voz asistida" o disclaimer). No se asume por XAVIER.
- **Retención del audio de salida (ADR-012 §5, P-N):** por defecto **no persistir** el audio TTS generado (basta el texto/guion aprobado, que ya vive en el `Message`), salvo requisito de auditoría. Si se persiste, aplica la retención/cifrado de SPEC-041/ADR-009.

---

## 2. Rol (quién debería resolverlo)

- 🔮 **DOCTOR STRANGE** — dueño de PLAN-008 y SPECs (traduce este prompt en plan/specs + ADR de desbloqueo del P2 aplazado).
- ⚫ **BLACK PANTHER** — backend: worker/servicio TTS local, integración con el sink de respuesta y la subida de media a WhatsApp.
- ⚡ **THOR** — **prueba de viabilidad** de motor TTS en CPU (calidad de voz es-CO + latencia por longitud de guion), decisiva antes de comprometer un motor.
- 🕷️ **SPIDER-MAN** / 🔴 **DAREDEVIL** — UX/frontend del flujo de aprobación del artefacto de audio (según la opción elegida en §7 Q1).
- 🕶️ **BLACK WIDOW** — verificar que `check-externos-backend.sh` sigue en verde con TTS local y cero egress de voz.

---

## 3. Acción (verbo único y medible)

**Diseñar** (PLAN-008 + SPECs, NO implementar aún) la capacidad de **responder con nota de voz generada por TTS 100% local** a una nota de voz entrante de WhatsApp, integrada de forma **aditiva** al pipeline existente y **conservando la aprobación humana explícita** antes de todo envío.

Sub-acciones esperadas del plan (orientativas para DOCTOR STRANGE, sujetas a §7):
1. Resolver la pregunta de aprobación humana del artefacto de audio (§7 Q1) → registrarla en un **ADR nuevo (candidato ADR-014)** que desbloquea/supersede la parte "TTS aplazado" de ADR-013.
2. Definir el punto de enganche del TTS en el flujo de respuesta (tras la aprobación humana, reutilizando el envío de media de WhatsApp ya autorizado — sin egress nuevo).
3. Prueba de viabilidad de motor (THOR): candidato(s) de §7 Q3 en CPU con voz es-CO, midiendo calidad subjetiva y latencia contra el techo de §7 Q4.
4. Extender `check-externos-backend.sh`/tests para probar **cero egress de voz de salida** (además del bloqueo ya existente de TTS de terceros).

---

## 4. Restricciones (invariantes duros — no negociables)

- **TTS 100% local, CPU-only.** Prohibido cualquier TTS de terceros (ElevenLabs, AWS Polly, Google/Azure/OpenAI TTS, Deepgram, PlayHT, etc.). `check-externos-backend.sh` debe seguir en verde.
- **Human-in-the-loop intacto.** Ningún audio se envía al cliente sin aprobación humana explícita. La forma exacta de esa aprobación es lo que resuelve §7 Q1 — pero la existencia de la aprobación NO es negociable.
- **Aditivo / cero regresión.** No romper el flujo de respuesta en texto (SPEC-029) ni los jobs `call` del Entregable #4 (ADR-013 R-62). El modelo `Message`/`Conversation` (ADR-013) se extiende de forma aditiva y nullable si hace falta (p. ej. `audio_ref` de salida), no se rediseña.
- **Sin egress nuevo.** El audio generado se sube a WhatsApp **solo** por el módulo `app/integrations/whatsapp/` (`graph.facebook.com`, ADR-006). El servicio TTS vive aislado (`ia_internal`), sin ruta a internet.
- **Idioma es-CO** por consistencia con el STT del proyecto (PLAN-004: `faster-whisper` es-CO). La voz de salida debe ser español (Colombia/LatAm), coherente con la voz del proyecto.
- **Retención mínima por defecto** (ADR-012 §5, P-N): no persistir el audio TTS salvo requisito de auditoría; si se persiste, cifrado/retención de SPEC-041/ADR-009.

---

## 5. Formato de salida esperado (lo que DOCTOR STRANGE debe producir con este prompt)

1. **`.swarm/PLAN-008.md`** — plan profesional: objetivo, alcance IN/OUT, fases (incluida la prueba de viabilidad de motor THOR como puerta previa), entregables, riesgos, criterios de éxito (CE), DoD. Debe **incorporar las respuestas del Lead a §7** antes de cerrarse.
2. **ADR candidato (ADR-014)** — "Cómo se aprueba y envía una respuesta de audio (TTS) manteniendo el human-in-the-loop", que desbloquea explícitamente el P2 aplazado en ADR-013 §4.
3. **Set de SPECs** (a partir de `next_spec: 67`) derivadas del plan aprobado — NO en este paso.
4. Todo redactado en español, clasificación SENSIBLE en el encabezado, coherente con el estilo de PLAN-004/006 y ADR-009/012/013.

---

## 6. Criterios de éxito (cómo se sabrá que el resultado es correcto)

- **CE-1 (aprobación humana de audio):** ningún audio llega al cliente sin la aprobación humana definida en §7 Q1; test verificable end-to-end.
- **CE-2 (100% local, cero egress de voz):** un intento de salida de voz/inferencia TTS a cualquier dominio/IP público **falla**; `check-externos-backend.sh` en verde con TTS de terceros prohibido (test negativo).
- **CE-3 (cero regresión):** la respuesta en texto (SPEC-029) y los jobs `call` (#4) siguen funcionando sin cambios de comportamiento; suites existentes pasan sin modificar asserts.
- **CE-4 (viabilidad CPU):** existe evidencia (THOR) de que el motor elegido genera voz es-CO inteligible dentro del techo de latencia acordado (§7 Q4) en CPU, sobre guiones representativos.
- **CE-5 (aditivo):** la migración de datos (si la hay) es aditiva/nullable; el audio de salida solo se sube por el módulo WhatsApp autorizado; retención por defecto = no persistir (o política de #4 si se persiste).
- **CE-6 (alcance acotado):** lo listado como OUT (§8) no aparece implementado salvo que el Lead lo pida.

---

## 7. Preguntas abiertas para el Lead (máx. 4 — con opciones concretas y trade-offs)

> ⚠️ **Q1 es la que desbloquea el Entregable #6** (la pregunta de diseño no resuelta de ADR-013). Sin decisión del Lead aquí, PLAN-008 no puede cerrarse.

### Q1 — ¿Cómo aprueba el agente humano la respuesta de audio? (LA pregunta de ADR-013)
- **Opción A — Aprobar el TEXTO/guion; el audio se genera y envía automáticamente tras la aprobación textual.**
  - *Pros:* mínima fricción; reutiliza casi tal cual el flujo de aprobación de texto actual (SPEC-029); latencia de generación fuera de la línea de espera del agente (puede generarse post-aprobación).
  - *Contras:* el humano **no escucha** lo que realmente sonará (pronunciación de nombres, cifras, siglas, entonación); menor control sobre el artefacto final que llega al cliente.
- **Opción B — Aprobar escuchando el CLIP de audio ya generado** (se genera el audio, el agente lo reproduce y aprueba/rechaza el audio concreto).
  - *Pros:* máximo control humano — el agente aprueba exactamente lo que oirá el cliente.
  - *Contras:* añade latencia (generar audio ANTES de la aprobación) y fricción (el agente debe escuchar cada clip); coste de CPU por cada borrador, incluso los rechazados.
- **Opción C — Híbrida:** aprobar el texto por defecto (Opción A), con un botón opcional **"escuchar antes de enviar"** que genera y reproduce el clip bajo demanda (Opción B a voluntad).
  - *Pros:* equilibrio control/fricción; el agente decide cuándo vale la pena escuchar.
  - *Contras:* más superficie de UX/estados; dos rutas a probar.
- *Recomendación XAVIER (no vinculante):* **Opción C** encaja mejor con un canal asíncrono CPU-only (baja fricción por defecto, control total cuando importa). **Decisión del Lead.**

### Q2 — ¿Opt-in explícito o automático por tipo de mensaje entrante?
- **Opción A — Opt-in:** el agente elige "responder con audio" como acción explícita (por defecto responde en texto, como hoy).
  - *Pros:* cambio mínimo, el agente controla; el audio solo se genera cuando se pide (ahorra CPU).
  - *Contras:* requiere una acción extra; el "responder en voz a quien te habló en voz" no es el comportamiento por defecto.
- **Opción B — Automático:** si el mensaje entrante fue una nota de voz, la respuesta se propone en audio por defecto, con opción de cambiar a texto.
  - *Pros:* simetría natural de canal (voz → voz); UX fluida para el cliente.
  - *Contras:* genera audio por defecto (más CPU); puede no ser deseado en todos los casos; interactúa con Q1 (más clips a aprobar).
- *Recomendación XAVIER (no vinculante):* **Opción A (opt-in)** para el primer slice — menor riesgo/coste y menor superficie; migrar a automático más adelante si el Lead lo valida. **Decisión del Lead.**

### Q3 — ¿Qué motor de TTS local se prioriza para la prueba de viabilidad? (CPU-only, es-CO)
- **Candidatas reales a evaluar (2–3):**
  - **Piper TTS** — ligero, diseñado para CPU, voces es-CO/es-ES disponibles; ya era el default evaluado en ADR-012 (contexto GPU/vivo). Buen punto de partida para CPU asíncrono.
  - **Coqui TTS (XTTS/VITS)** — mayor naturalidad potencial, pero más pesado en CPU; era la "alternativa" en ADR-012.
  - **(Opcional) eSpeak-NG / otro ligero** — como fallback de mínimo cómputo si la latencia CPU de los anteriores no cumple el techo (§7 Q4), a costa de naturalidad.
- ⚠️ **Nota honesta:** la elección final **NO se asume aquí**. Requiere una **prueba de viabilidad (THOR): calidad subjetiva de voz es-CO + latencia real en CPU** por longitud de guion, antes de comprometer un motor en las SPECs.
- *Pregunta al Lead:* ¿priorizamos **Piper** como candidato principal a validar (recomendación XAVIER por ser CPU-friendly y ya pre-evaluado), con Coqui como comparativa de naturalidad? ¿O el Lead tiene una preferencia/exclusión?

### Q4 — ¿Cuál es el techo de latencia/experiencia aceptable? (NO es VoiceBot en vivo)
- Contexto: esto es **asíncrono** como el resto del sistema — **NO** hay presupuesto duro de <700 ms (eso era el VoiceBot en vivo archivado). Pero sí importa que no se sienta "lento" para el agente al aprobar/enviar.
- *Pregunta al Lead:* ¿qué techo de tiempo de **generación del audio** es aceptable antes de sentirse lento? Opciones de referencia:
  - **(a) ≤ 2–3 s** por respuesta típica (percibido como "casi inmediato" tras aprobar).
  - **(b) ≤ 5–10 s** aceptable si el audio se genera en background y el agente no queda bloqueado (compatible con Opción A de Q1).
  - **(c) sin techo estricto** (best-effort), priorizando calidad de voz sobre velocidad.
- *Recomendación XAVIER (no vinculante):* fijar **(b)** con generación en background como objetivo, midiendo el real en la prueba THOR. **Decisión del Lead.**

---

## 7.1 Respuestas del Lead (2026-09-28) — VINCULANTES

- **Q1 → Opción C (híbrida):** el agente aprueba el texto/guion por defecto; botón opcional "escuchar antes de enviar" para revisar el clip bajo demanda. Desbloquea el P2 de ADR-013 — candidato a registrar como ADR-014.
- **Q2 → Opción A (opt-in):** por defecto la respuesta sigue siendo texto (como hoy); el agente elige explícitamente "responder con audio". No automático en este slice.
- **Q3 → Piper TTS como candidato principal** a validar (CPU-friendly, ya pre-evaluado en ADR-012), con Coqui TTS como comparativa de naturalidad. La elección final sigue sujeta a la prueba de viabilidad de THOR (calidad es-CO + latencia real en CPU).
- **Q4 → Opción (b):** techo de ≤5–10s, con generación del audio en background sin bloquear al agente (coherente con Q1 Opción C: el agente sigue trabajando mientras se genera, y revisa/escucha cuando decide).

Estas 4 decisiones son vinculantes para PLAN-008 — DOCTOR STRANGE las incorpora directamente, sin volver a preguntarlas.

---

## 8. Fuera de alcance por defecto (OUT — salvo que el Lead lo pida en §7)

- **Clonación / personalización de voz** de una persona real (riesgo de suplantación; ya OUT en ADR-012 §6).
- **Multi-idioma** más allá de español es-CO/LatAm.
- **Respuesta en audio a mensajes de TEXTO entrantes.** Este Entregable #6 aplica **solo cuando el mensaje entrante fue una nota de voz**, salvo que el Lead indique lo contrario (Q2 puede matizar esto).
- **Instagram u otros canales** (sigue fuera, como en PLAN-006 / SUP-66). Solo WhatsApp.
- **VoiceBot conversacional en vivo / barge-in / streaming** (PLAN-005, archivado por falta de GPU — no se reabre).
- **Persistir el audio TTS por defecto** (ADR-012 §5, P-N): no se persiste salvo requisito de auditoría explícito del Lead.

---

## 9. Trazabilidad

- Origen del aplazamiento: **PLAN-006 §2 OUT + §12 P2**, **ADR-013 §4 / Decisión 4** ("TTS de salida aplazado").
- Referencias TTS local (fase archivada, NO reusable como código): **ADR-012**, **ADR-011**, **PLAN-005** (Piper es-CO / Coqui).
- Idioma es-CO: **PLAN-004** (STT `faster-whisper` es-CO).
- Invariantes SENSIBLE: **ADR-005** (egress IA), **ADR-009** (STT local + retención audio), **ADR-006** (transporte WhatsApp).
- Barrera de egress: `backend/check-externos-backend.sh` (TTS de terceros ya bloqueado).
- Residuos a limpiar/decidir: `backend/app/core/config.py` líneas 420–439 (`TTS_MODE`, `TTS_VRAM_FRACTION`).
- Siguiente paso: 🔮 DOCTOR STRANGE → **PLAN-008** (con las respuestas del Lead a §7) → aprobación del Lead → SPECs (desde `next_spec: 67`).
