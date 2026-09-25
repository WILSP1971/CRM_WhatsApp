# SPEC-048 — Bucle de diálogo (NLU→respuesta de catálogo RAG/pregrabada→TTS) + barge-in 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, THOR, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: CRÍTICA · Tipo: BACKEND/ORQUESTACIÓN · Fase: F4
- Deriva de: PLAN-005 (F4, §3.1/§3.4/§3.6.4, ruta crítica dura) · Clasificación: SENSIBLE (`.no-externo`) · ADR-011/ADR-012 (reutiliza SPEC-017/045/047)
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Implementar el **orquestador del turno de voz en vivo**: toma la transcripción parcial (`voice_stt`, SPEC-047), clasifica el intent contra el catálogo cerrado (SPEC-045), **rellena la plantilla de respuesta anclada a RAG con citas** (SPEC-017) **o selecciona el audio pregrabado** correspondiente, y la **sintetiza con Piper** (`voice_tts`) **o** con el **modo bajo-cómputo pregrabado** a través de una **interfaz de TTS conmutable** (ADR-012, §3.6.4); con **barge-in** (la interrupción del usuario **cancela la síntesis en curso** y devuelve el turno a STT) e **instrumentación del presupuesto de latencia por turno**. Es el segundo eslabón de la ruta crítica dura (F3+F4+F6).

## Contexto

Aquí se cierra el bucle conversacional. El invariante P1 es duro: la respuesta **solo** puede provenir del catálogo cerrado (plantilla anclada a RAG con citas o audio pregrabado); **ningún LLM generativo** produce texto libre en vivo (SPEC-045). El TTS se implementa **detrás de una interfaz conmutable** (Piper generativo ↔ banco de audios pregrabados) por env/feature-flag, para que el **modo bajo-cómputo** (coste de GPU ~0, clave para la viabilidad de latencia sobre GPU compartida, ADR-011/ADR-012) **no** requiera rediseño. El **barge-in** exige STT/TTS en el mismo host de baja latencia y **cancelación de la síntesis en curso**: cuando el usuario habla mientras el bot sintetiza (detectado por VAD), el audio-out se corta y el turno vuelve a STT de inmediato. Cualquier `SIN_INTENT` / baja confianza / sentimiento negativo / petición de humano → no se responde: se **escala** (contrato en SPEC-049).

## Alcance

### IN
- **Orquestador de turno:** consume hipótesis parciales de `voice_stt`, invoca el clasificador de intent (SPEC-045) y decide: (a) responder desde el catálogo, (b) consultar dato/agendar (acción del intent), o (c) **escalar** (delegado a SPEC-049 ante `SIN_INTENT`/baja confianza).
- **Respuesta anclada a catálogo:** rellena la plantilla del intent con datos consultados (estado de cita/pedido, etc.), **anclada a RAG con citas** (SPEC-017) cuando aplique; para FAQ, respuesta citada del RAG existente; **nunca** genera texto libre con LLM.
- **Interfaz de TTS conmutable** (ADR-012): `voice_tts` Piper generativo **o** banco de audios pregrabados/concatenados (modo bajo-cómputo), seleccionable por env/feature-flag sin cambiar el orquestador; el audio-out se entrega al `voice_gateway` por la red interna.
- **Barge-in:** detección de habla del usuario durante la síntesis (VAD), **cancelación de la síntesis TTS en curso**, descarte del audio-out pendiente y retorno del turno a STT; medición del tiempo de corte.
- **Instrumentación del presupuesto de latencia por turno:** medición end-to-end parcial audio-in → intent → TTS listo → audio-out (contribución al ≤700 ms; agregación en SPEC-050).
- Selección automática de estrategia de respuesta: datos variables no pregrabables → Piper; respuestas fijas del catálogo → audio pregrabado (cuando el modo bajo-cómputo está activo).

### OUT
- Contrato exacto de la transferencia a humano y monitor SPA (SPEC-049); clasificación de intent en sí (SPEC-045); STT streaming (SPEC-047); medición/fijación de `C` y verificación de latencia bajo carga (SPEC-050); persistencia/retención (SPEC-051).

## Dependencias
- Depende de SPEC-045 (catálogo/NLU), SPEC-047 (transcripción parcial) y SPEC-017 (RAG con citas). Prerequisito de SPEC-049 (escalación consume el estado del turno) y de SPEC-050 (mide este bucle). Se ancla en ADR-011 (modo bajo-cómputo) y ADR-012 (TTS local + interfaz conmutable). Reutiliza `voice_tts`/banco pregrabado de SPEC-044.

## Requisitos funcionales
- RF-01 El orquestador clasifica el intent y responde SOLO desde el catálogo (plantilla RAG citada o audio pregrabado); nunca texto libre de LLM.
- RF-02 El TTS es conmutable Piper↔pregrabado por env/feature-flag sin cambiar el orquestador.
- RF-03 El barge-in corta la síntesis en curso y devuelve el turno a STT de forma medible.
- RF-04 El bucle instrumenta la latencia por turno (audio-in → audio-out).
- RF-05 `SIN_INTENT`/baja confianza no produce respuesta del bot: delega la escalación (SPEC-049).

## Requisitos no funcionales
- RNF-56 Contribución del turno al presupuesto ≤700 ms p95 (valor final fijado por THOR, SPEC-050).
- RNF-51 TTS/NLU/orquestación 100% local, sin egress (ADR-011/ADR-012).
- RNF-54 La respuesta anclada a RAG conserva las citas trazables de SPEC-017; ningún LLM generativo en el camino.

## Criterios de aceptación (verificables)
- [ ] Con el simulador (SPEC-052), un intent dentro de catálogo produce la respuesta de plantilla (RAG citada o audio pregrabado) sintetizada y devuelta como audio-out; **ningún LLM generativo** interviene (verificado en CI, SPEC-045).
- [ ] Conmutar TTS Piper↔pregrabado por env NO requiere cambios en el orquestador (test de interfaz conmutable).
- [ ] **Barge-in:** un audio simulado que interrumpe a mitad de síntesis **corta** el audio-out y devuelve el turno a STT; el tiempo de corte se mide y queda por debajo del umbral definido (CE-54, valor medido en SPEC-050).
- [ ] Una respuesta de FAQ está anclada a RAG con citas trazables (SPEC-017); una respuesta de dato variable (estado de cita) usa la plantilla del intent rellenada.
- [ ] El bucle expone métricas de latencia por turno (audio-in → intent → TTS → audio-out).
- [ ] Un intento de egress desde `voice_tts`/orquestador/NLU a IP/dominio público **falla** (timeout/deny).
- [ ] `SIN_INTENT`/baja confianza en el turno NO genera respuesta del bot; marca escalación (verificado contra SPEC-049).

## Notas de seguridad (C2/C3)
- C3: sin secretos en el orquestador; flags/umbrales por env.
- C2: el turno no persiste datos aquí; la transcripción/persistencia es SPEC-051.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: orquestación/NLU/TTS 100% local en `ia_internal`, sin egress (ADR-011/ADR-012). Invariante P1: la respuesta del bot proviene SOLO del catálogo cerrado; ningún LLM generativo habla en vivo. Prueba de egress vacío (SPEC-051).

## Riesgos
- R-51 (latencia ≤700 ms): modo bajo-cómputo pregrabado (coste ~0) por interfaz conmutable; instrumentación y degradación en SPEC-050.
- R-53 (bot fuera de catálogo): respuesta solo desde plantillas/RAG citado; ningún LLM generativo (CI, SPEC-045); fuera de catálogo → escalación (SPEC-049).
- R-56 (barge-in no funciona): VAD + cancelación de síntesis en curso; STT/TTS en el mismo host de baja latencia; test de barge-in medible (CE-54).
- R-54 (TTS a terceros): `voice_tts` local en `ia_internal`, TTS de terceros prohibido en CI (ADR-012); egress vacío.

## Checkpoints aplicables
- C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-005).
