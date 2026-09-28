# ADR-014 — Cómo se aprueba y envía una respuesta de audio (TTS local) manteniendo el human-in-the-loop

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-008.md` (§1, §2 IN/OUT, §3.4, §3.5, §11, Q1–Q4 §1, R-81/R-83/R-85/R-86, CE-81/CE-82/CE-84/CE-85/CE-87), `SPEC-067`, `SPEC-068`, `SPEC-069`, `SPEC-070`, `SPEC-071`, `SPEC-072`

- **Estado:** Aceptada — APROBADA por el Lead (bloque PLAN-008) — 2026-09-28.
- **Fecha:** 2026-09-28
- **Plan:** PLAN-008

---

## Contexto

El Entregable #6 cierra el bucle de la voz asíncrona en WhatsApp: cuando un cliente envía una **nota de voz**
(ya descargada y transcrita por STT **100% local** en el Entregable #5, SPEC-053..061), el agente podrá **responder
con una nota de voz generada por TTS 100% local, CPU-only** en español es-CO. El Entregable #5 respondía **solo con
texto** y **ADR-013 §4** aplazó explícitamente el "TTS de salida" ("posible Entregable #6") por una **pregunta de
diseño no resuelta**: *¿cómo aprueba un agente humano un artefacto de audio antes de enviarlo — escucha el clip
generado, o aprueba solo el guion textual de lo que diría?* Esta ADR resuelve esa pregunta y desbloquea el vector.

Concurren decisiones vinculantes del Lead (PLAN-008 §1, Q1–Q4, adoptadas del prompt §7.1, **no se reabren**):
- **Q1 (aprobación) = Opción C (híbrida):** aprobar el **guion textual** por defecto (reutiliza SPEC-019/029);
  botón opcional **"escuchar antes de enviar"** que genera y reproduce el clip bajo demanda.
- **Q2 (activación) = Opción A (opt-in):** por defecto la respuesta sigue siendo **texto**; el agente elige
  explícitamente "responder con audio". No automático.
- **Q3 (motor) = Piper** candidato principal (CPU-friendly, pre-evaluado en ADR-012) vs **Coqui** comparativa;
  **elección final sujeta a la prueba de viabilidad de THOR (SPEC-067)**.
- **Q4 (latencia) = ≤5–10 s** con generación **en background** sin bloquear al agente.

La clasificación SENSIBLE (`.no-externo`) obliga a que la voz de salida (dato personal / posible PHI, como la de
entrada) y **toda** la síntesis permanezcan on-prem (ADR-005/ADR-009/ADR-012). El TTS de terceros (ElevenLabs,
AWS Polly, Google/Azure/OpenAI TTS, Deepgram, PlayHT, Coqui-cloud) está **PROHIBIDO** y ya bloqueado en
`check-externos-backend.sh`. La subida del clip usa **solo** el host/módulo ya autorizado para WhatsApp
(`graph.facebook.com`, ADR-006/SPEC-024/054) — **no hay egress nuevo**, a diferencia de ADR-010. Además, una voz
sintética que habla en nombre de la empresa plantea un riesgo legal/reputacional (Ley 1581, herencia ADR-012 §4):
el Lead ya decidió, al aprobar PLAN-008, **incluir un disclaimer de voz sintética (marca ligera)**.

Contexto de código verificado: `rag_drafts` (SPEC-019) es la máquina de estados del guion human-in-the-loop
(`propuesto→editado→aprobado→descartado`, `sent_message_id` se completa **solo al aprobar**); `messages` ya tiene
las columnas del audio **entrante** (SPEC-053/054/058); `config.py` líneas 420–439 contienen residuos GPU
(`TTS_MODE`/`PIPER_VOICE`/`TTS_VRAM_FRACTION`, fase archivada PLAN-005/ADR-011/ADR-012) a limpiar en CPU-only.

---

## Decisión

1. **El invariante de aprobación se ancla al GUION textual, con ruta opcional de escucha (Q1-C).** El humano
   aprueba el **guion** (`rag_drafts`, exactamente como hoy en SPEC-019/029). El motor TTS es **determinista
   respecto al guion aprobado**, de modo que aprobar el guion ≈ aprobar lo que se dirá. La generación del audio es
   una consecuencia **post-aprobación** en la ruta por defecto (background, no bloquea). Adicionalmente existe una
   ruta **"escuchar antes de enviar"** que genera el clip **bajo demanda** para que el agente lo reproduzca y
   apruebe/rechace el **audio concreto** (cubre los casos donde la pronunciación importa: nombres, cifras, siglas).
   **En ambos casos, ningún audio se envía sin una aprobación humana explícita** (la del guion o la del clip
   escuchado).

2. **Activación opt-in (Q2-A).** Por defecto la respuesta es **texto** (comportamiento actual idéntico). El agente
   elige explícitamente "responder con audio". Se modela con un campo aditivo `respuesta_modo`
   (`"texto"` por defecto / `"audio"`) sobre `rag_drafts`, y un `tts_estado` opcional
   (`no_solicitado`/`generando`/`listo`/`error`) para la ruta de escucha (SPEC-068). El audio **solo se genera
   cuando se pide** (ahorra CPU).

3. **Generación en background, CPU-only, aislada sin egress (Q4-b).** La síntesis corre en un servicio/worker
   **100% local** en `ia_internal internal:true` (sin ruta a internet, simétrico al `stt_worker`), encolado en
   `tts:jobs` (Redis, patrón `stt:jobs`) con **throttling/concurrencia limitada** dimensionada por THOR
   (SPEC-067/R-84), dentro del techo **≤5–10 s**. El servicio **no sube nada**: deja el clip en almacén/cola
   local. La **subida** la realiza **solo** `app/integrations/whatsapp/` a `graph.facebook.com` (ADR-006) —
   **cero egress nuevo**. TTS de terceros **PROHIBIDO** (extiende ADR-009/ADR-012).

4. **Motor decidido (Q3, evidencia de SPEC-067): Piper TTS 1.8.0, voz `es_ES-davefx-medium`.** Única combinación
   motor+voz de las evaluadas (4 voces Piper + Coqui `es/css10/vits`) que cumple el techo ≤10s en las 8 categorías
   de guion probadas (peor caso p95 = 7.19s); cumple ≤5s en 6 de 8. Coqui excede el techo en ambos guiones largos
   y su vocabulario **no incluye dígitos** (descarta cifras silenciosamente) — un modo de fallo más peligroso que
   el de Piper (que las pronuncia, aunque mal, si no se normalizan antes). El Lead confirmó `es_ES-davefx-medium`
   (mejor rendimiento medido) sobre la alternativa `es_MX-ald-medium` (acento más cercano a LatAm, pero falla por
   poco el techo de 10s en el guion más largo probado, 10.137s). **`PIPER_VOICE=es_CO-pablo-medium` de `config.py`
   no existe en el catálogo real de Piper (404) — no hay ninguna voz colombiana auténtica disponible hoy en
   ninguna librería evaluada; se documenta como trade-off de acento aceptado, no como error a corregir.**
   Requisito nuevo descubierto (SPEC-067): el guion debe **normalizarse** (cifras/siglas expandidas a palabras)
   antes de sintetizar — ninguna voz las pronuncia bien en crudo; se incorpora al alcance de SPEC-069.
   El **plan de contingencia (R-83)** no se activó de forma dura (Piper sí es viable); se aplica preventivamente
   la vía "acotar longitud sintetizable" (~650–800 caracteres, el rango probado) y se deja preparada la vía
   "relajar el techo a best-effort" como salvaguarda si la concurrencia real (no medida aquí por falta de acceso
   a Docker en el sandbox del spike) resulta peor que la estimada — a re-validar en SPEC-071.

5. **No persistir el clip por defecto (herencia ADR-012 §5).** Basta el guion aprobado (que ya vive en
   `rag_drafts`/`Message`). Si por auditoría se decide persistir, se rige por el **mismo `audio_store.py` cifrado
   + política SPEC-041** (un solo régimen, herencia ADR-009), mediante un `audio_salida_ref` opcional (nullable,
   por defecto NULL).

6. **Disclaimer de voz sintética SÍ, marca ligera (decisión vinculante del Lead, herencia ADR-012 §4).** Toda
   respuesta de audio se acompaña de una **marca ligera** (p. ej. etiqueta/prefijo "🔊 respuesta de voz asistida")
   para que el cliente sepa que la voz es asistida (Ley 1581 / buena práctica anti-deepfake). Es un requisito
   **firme** (no desactivable por defecto), implementado en SPEC-070 y verificado en SPEC-071 (CE-87). En chat
   asíncrono con aprobación humana el riesgo es menor que en un bot en vivo, pero se aplica igual.

**Esta ADR desbloquea/supersede la parte "TTS de salida aplazado" de ADR-013 §4.** El resto de ADR-013 (nota de
voz modelada como `Message`, no como `call`; sink parametrizado por `destino`; idempotencia por `wamid`; sin egress
nuevo) permanece **vigente e intacto**.

---

## Alternativas consideradas

| Alternativa | Por qué se descartó |
| ----------- | ------------------- |
| **Aprobar SIEMPRE el clip escuchado (Opción B pura de Q1)** | Obliga a generar audio para *cada* respuesta antes de aprobar, aun cuando el guion basta: más fricción para el agente y más consumo de CPU sin GPU (R-84). El invariante de aprobación puede anclarse al guion (el TTS es determinista respecto a él) dejando la escucha como ruta **opcional**. Descartada por Q1-C (híbrida). |
| **Activación automática voz→voz (Opción B de Q2)** | Generaría audio sin decisión explícita del agente: rompe el opt-in, consume CPU innecesaria y elimina el control humano sobre cuándo la empresa "habla". Descartada por Q2-A (opt-in); posible slice futuro si el Lead lo valida. |
| **TTS en la nube / de terceros** (ElevenLabs, AWS Polly, Google/Azure/OpenAI TTS, Deepgram, PlayHT, Coqui-cloud) | Enviaría a un tercero **el contenido que la empresa dice al cliente** (posible PHI) y crearía dependencia externa en el camino de voz: rompe SENSIBLE/`.no-externo` (igual que STT de terceros, ADR-009/ADR-012). Prohibido y bloqueado en `check-externos-backend.sh`. |
| **Persistir el clip TTS por defecto** | Aumenta la superficie SENSIBLE (retención de PHI de voz de salida) sin necesidad: basta el guion aprobado. Por defecto no se persiste (herencia ADR-012 §5); si se persiste por auditoría, aplica cifrado + SPEC-041. Descartada como comportamiento por defecto. |
| **No declarar que la voz es sintética** | Riesgo legal/reputacional (deepfake, engaño, Ley 1581; herencia ADR-012 §4, R-85). El Lead decidió incluir una marca ligera. Descartada. |
| **Servicio TTS en la red `app` (con egress) por comodidad** | Superficie de salida innecesaria: el TTS no necesita internet (deja el clip en almacén/cola local y lo sube el módulo WhatsApp). Aumenta R-81. Descartada a favor de `ia_internal internal:true` (simétrico a `stt_worker`/ADR-005). |
| **Fijar el motor sin la prueba de viabilidad de THOR** | Sin evidencia de calidad/latencia en CPU (Q4-b), comprometer un motor arriesga invalidar el entregable (R-83). SPEC-067 es **puerta previa dura**; el motor se decide con datos. Descartada. |

---

## Consecuencias

**Pros**
- El human-in-the-loop se conserva **sin fricción nueva** en el caso común (aprobar el guion, como hoy), con una
  ruta de escucha disponible cuando la pronunciación importa: control humano garantizado en ambas rutas.
- Cero egress nuevo (subida por el canal WhatsApp ya autorizado, ADR-006) y cero dependencia externa de voz:
  cumple SENSIBLE sin excepción; extiende ADR-009/ADR-012 al vector TTS de salida asíncrono CPU-only.
- Opt-in + generación en background + throttling: coste de CPU acotado sobre una máquina sin GPU compartida con
  STT batch/RAG/sentimiento (R-84).
- No persistir por defecto minimiza la superficie SENSIBLE del clip; el disclaimer mitiga el riesgo legal (R-85).
- ADR-013 queda desbloqueada en su punto abierto sin tocar el resto de su decisión (mínima superficie de cambio).

**Cons / mitigaciones**
- Aprobar el guion (no el clip) asume que el TTS es determinista respecto al texto → la ruta opcional "escuchar
  antes de enviar" cubre los casos de pronunciación (nombres/cifras/siglas); ambas rutas se prueban (CE-81/SPEC-071).
- La viabilidad calidad/latencia en CPU es incierta → SPEC-067 es puerta previa + plan de contingencia escalonado
  (R-83), decisión del Lead con datos; el plan prioriza relajar techo / acotar longitud sobre abortar.
- El campo `respuesta_modo`/`tts_estado` añade estado al borrador → migración **aditiva/nullable**, default
  `"texto"` = comportamiento actual idéntico (SPEC-068, R-82); suites de texto/#5/#4 verdes.
- Residuos de config GPU podrían reutilizarse por error en CPU → SPEC-068 los limpia/reemplaza (R-87), documentado
  en el runbook (SPEC-072).
- Si se decide persistir el clip → cambio sensible: aplica retención de #4 (SPEC-041) + aprobación del Lead (C6).

**Criterio de verificación (objetivo y verificable)**
- **Aprobación humana (CE-81):** un envío de audio sin guion/clip aprobado **falla**; ambas rutas verificadas
  (SPEC-069/071).
- **Cero egress de voz (CE-82):** intento de salida de voz/inferencia TTS a cualquier dominio/IP público **falla**;
  `check-externos-backend.sh` en verde con TTS de terceros prohibido; egress vacío desde el servicio TTS en
  `ia_internal`; el servicio no importa/ejecuta el cliente de subida (SPEC-069/071).
- **Opt-in + aditivo (CE-85):** default texto; migración aditiva/nullable; clip subido **solo** por el módulo
  WhatsApp; no-persistencia por defecto (SPEC-068/069/071).
- **Viabilidad CPU (CE-84):** evidencia de THOR (SPEC-067) del motor elegido dentro del techo ≤5–10 s, o plan de
  contingencia aplicado con decisión del Lead.
- **Voz sintética/legal (CE-87):** disclaimer/marca ligera presente e implementado (SPEC-070) y verificado
  (SPEC-071).
- **Cero regresión (CE-83):** texto (SPEC-029), pipeline #5 (SPEC-053..061) y jobs `call` (#4) intactos; suites
  verdes sin modificar asserts (SPEC-071).

---

## Referencias

- `PLAN-008.md` — §1 (objetivo, Q1–Q4 vinculantes, disclaimer decidido), §2 IN/OUT, §3.4 (enganche al
  human-in-the-loop), §3.5 (modelo de datos aditivo), §11 (ADR-014 recomendado), R-81/R-83/R-84/R-85/R-86/R-87,
  CE-81..CE-87, DoD §9/§12.
- `SPEC-067` — Prueba de viabilidad de motor TTS en CPU (Piper vs Coqui, fallback ligero); decisión de motor +
  plan de contingencia (puerta previa dura).
- `SPEC-068` — Esta ADR + modelo de datos aditivo (`respuesta_modo`/`tts_estado`/`audio_salida_ref`) + limpieza de
  residuos `TTS_*` de config (CPU-only).
- `SPEC-069` — Servicio TTS local en `ia_internal` (sin egress) + `tts:jobs`/throttling + enganche híbrido +
  subida por el módulo WhatsApp (sin egress nuevo) + no-persistencia por defecto.
- `SPEC-070` — SPA/UX opt-in "responder con audio" + "escuchar antes de enviar" + estados AAA + feature-flag +
  disclaimer (marca ligera, firme).
- `SPEC-071` — Pruebas + seguridad + no-regresión (e2e opt-in, cero egress de voz, ningún audio sin aprobación,
  cero regresión #4/#5/texto, latencia/coste CPU, cobertura ≥80%).
- `SPEC-072` — Documentación, runbook (motor/latencia/throttling/retención/disclaimer), limpieza documentada,
  simulador local sin egress, deploy on-prem (C6).
- **Supersede:** `ADR-013` §4 (parte "TTS de salida aplazado"); el resto de ADR-013 permanece vigente.
- Relacionado: **ADR-012** (TTS local + declaración de voz sintética — se re-evalúa §4/§5 en contexto CPU-only
  asíncrono), **ADR-009** (audio como PHI: cifrado/retención si se persiste), **ADR-006** (transporte WhatsApp —
  la subida del clip no es egress nuevo), **ADR-005** (bloqueo de egress de IA, reafirmado), **ADR-007**
  (idempotencia por `wamid`), **ADR-008** (RLS efectiva).
- `backend/check-externos-backend.sh` — auditoría "cero audio/inferencia/TTS a terceros" (debe seguir en verde).
