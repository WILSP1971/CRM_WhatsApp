# SPEC-067 — Prueba de viabilidad de TTS local en CPU (THOR): Piper vs Coqui (fallback ligero), voz es-CO, calidad + latencia real vs techo ≤5–10 s, decisión de motor documentada 🔴 SENSIBLE

- Estado: CERRADA — decisión de motor: **Piper TTS 1.8.0, voz `es_ES-davefx-medium`** (única combinación que cumple el techo ≤10s en las 8 categorías de guion probadas; confirmada por el Lead sobre la alternativa `es_MX-ald-medium`, que falla por poco el techo en el guion más largo). `es_CO-pablo-medium` de `config.py` no existe (404). Hallazgos para SPEC-069: normalización previa de cifras/siglas requerida; concurrencia inicial `tts:jobs`=1 (no medida con workers reales, sin Docker en este sandbox); `ffmpeg` no está en `Dockerfile` (gap a cerrar). Ninguna vía dura de contingencia (R-83) se activó; se aplica preventivamente "acotar longitud" (~650-800 caracteres). Fix colateral: `check-externos-backend.sh` excluía `tests/` pero no `.venv/`, causando falsos positivos con `huggingface_hub` (dependencia transitiva de Piper) — corregido. · Responsable: THOR · Colaboran: BLACK PANTHER, CAPTAIN AMERICA, HAWKEYE, BLACK WIDOW, WOLVERINE · Prioridad: ALTA · Tipo: SPIKE/PERFORMANCE · Fase: F0
- Deriva de: PLAN-008 (F0, §2.IN.1, §4, §5, §6 R-83/R-84, CE-84/CE-86) · Clasificación: SENSIBLE (`.no-externo`) · ADR-005/ADR-009/ADR-012

## Objetivo

Ejecutar una **prueba de viabilidad reproducible** de síntesis de voz (TTS) **100% local, CPU-only, on-prem** en español **es-CO/LatAm**, para **decidir el motor** que usará el Entregable #6 antes de comprometer implementación. Se comparan **Piper TTS** (candidato principal, Q3) y **Coqui TTS** (comparativa de naturalidad), y —**solo si ambos incumplen** el techo con calidad aceptable— un **fallback ligero tipo eSpeak-NG** como último recurso. Se mide, sobre guiones representativos (cortos/medios/largos), la **calidad subjetiva** (inteligibilidad, naturalidad, pronunciación correcta de nombres propios, cifras y siglas) y la **latencia real** contra el techo **≤5–10 s** (Q4-b), además del **coste de CPU** con los demás workers concurrentes (STT batch/RAG/sentimiento). Entregable: **decisión de motor final documentada + evidencia reproducible + plan de contingencia** si ningún motor cumple. Es **puerta previa dura**: sin esta SPEC cerrada con una decisión de motor, **F2 (SPEC-069) no puede arrancar**.

## Contexto

No existe hoy código TTS funcional en el repo (verificado: `find backend/app -iname "*tts*"` → solo `stt_worker.py`, no TTS). La fase archivada PLAN-005/ADR-011/ADR-012 evaluó Piper/Coqui **para GPU compartida + tiempo real (barge-in, ≤700 ms)** que **YA NO APLICA**: sirve solo como punto de partida de librerías candidatas, no como decisión firme ni código reutilizable. La máquina objetivo corre **sin GPU** y ya soporta STT batch (`faster-whisper`, SPEC-038), RAG (SPEC-017) y sentimiento (SPEC-018) en la misma CPU; `ffmpeg` ya está presente en el stack STT de #5 (útil para transcodificar a OGG/Opus, R-88). La voz `PIPER_VOICE=es_CO-pablo-medium` de `config.py` (residuo GPU) es una **base candidata a re-validar en CPU**, no un dato firme. El techo ≤5–10 s (Q4-b) es un techo **de background** (el agente no queda bloqueado, Q1-C).

**Naturaleza de spike (importante):** esta SPEC produce **evidencia y una decisión**, no código de producción. Cualquier prototipo se mantiene aislado (scripts de benchmark/notebook), no se integra al flujo hasta F2. La medición debe ser **reproducible** (guiones fijos, versiones de motor/voz fijadas, hardware documentado) para que la decisión sea auditable.

## Alcance

### IN
- **Banco de guiones representativos** en es-CO: al menos respuestas **cortas** (1 frase), **medias** (2–4 frases) y **largas** (párrafo), incluyendo casos con **nombres propios, cifras (fechas/horas/precios/teléfonos) y siglas** (los casos donde la pronunciación importa, §ADR-014). Sin datos reales de clientes (C3): guiones ficticios representativos del dominio (agendamiento, confirmaciones, precios).
- **Comparativa de motores en CPU:** Piper (voz es-CO/es_419) y Coqui (voz es más cercana), ejecutados **local, sin egress**, con versiones/voces **fijadas y documentadas**. Fallback eSpeak-NG **solo si** Piper y Coqui incumplen.
- **Métricas de calidad subjetiva** por guión y motor: inteligibilidad, naturalidad y pronunciación de nombres/cifras/siglas, con una **rúbrica simple y documentada** (p. ej. escala 1–5 + notas), evaluada por ≥1 revisor humano (protocolo repetible).
- **Métricas de latencia real** por guión y motor en CPU: tiempo de síntesis de extremo a extremo (incluida transcodificación a OGG/Opus si aplica), reportando media/mediana/p95 y comparándolas con el techo ≤5–10 s; identificación del punto en el que la longitud del guión rompe el techo (insumo para "acotar longitud", R-83).
- **Coste de CPU concurrente:** medición del impacto del TTS ejecutándose junto a STT batch/RAG/sentimiento (degradación observada), para **dimensionar el throttling/concurrencia** de `tts:jobs` en SPEC-069 (CE-86, R-84).
- **Decisión de motor documentada:** motor elegido + voz + parámetros + versiones, con justificación basada en la evidencia; recomendación del **techo de latencia exacto** dentro de 5–10 s (p. ej. objetivo 5 s / aceptable 10 s) y del **dimensionado de concurrencia** inicial para SPEC-069.
- **Plan de contingencia (R-83) escalonado y explícito**, para decisión del Lead con la evidencia: (1) **relajar el techo** a best-effort si la calidad es buena y la latencia solo algo mayor (audio asíncrono, Q1-C lo permite); (2) **degradar a motor más ligero** (eSpeak-NG) aceptando menor naturalidad; (3) **acotar la longitud** sintetizable (cortas sí, largas caen a texto); (4) último recurso **degradar a "solo texto"** (el pipeline de #5 es el fallback natural) y aplazar. El plan **prioriza (1)/(3) sobre abortar**; la decisión final es del Lead con datos.
- **Evidencia reproducible archivada:** scripts/comandos de benchmark, guiones, versiones fijadas, hardware, tablas de resultados y muestras de audio generadas localmente (sin egress), de modo que la medición se pueda repetir.

### OUT
- Servicio/worker TTS de producción, cola `tts:jobs`, enganche al human-in-the-loop y subida por WhatsApp (SPEC-069).
- ADR-014, modelo de datos aditivo y limpieza de residuos `TTS_*` de config (SPEC-068).
- SPA/UX, feature-flag y disclaimer (SPEC-070).
- Suite de pruebas de no-regresión/seguridad e2e (SPEC-071) y docs/runbook/deploy (SPEC-072).
- Cualquier TTS de terceros / en la nube (PROHIBIDO, ADR-012).

## Dependencias
- Depende del stack CPU-only ya operativo (STT batch SPEC-038, RAG SPEC-017, sentimiento SPEC-018) para medir contención concurrente, y de `ffmpeg` presente en el stack STT (SPEC-035/054). Se ancla en ADR-005 (bloqueo de egress de IA), ADR-009 (audio como PHI) y ADR-012 (TTS local, motores candidatos). **Prerequisito duro y puerta previa de SPEC-069** (F2 no arranca sin la decisión de motor de esta SPEC) y de SPEC-068 (ADR-014 registra el motor elegido). Informa el dimensionado de throttling que verifica SPEC-071.

## Requisitos funcionales
- RF-01 Existe un banco de guiones es-CO cortos/medios/largos con nombres/cifras/siglas, ficticios (sin PII real), versionado y reutilizable.
- RF-02 Se ejecuta Piper y Coqui en CPU sin egress, con versiones/voces fijadas; si ambos incumplen, se evalúa eSpeak-NG.
- RF-03 Se registra, por guión y motor, calidad subjetiva (rúbrica documentada) y latencia real (media/mediana/p95) frente al techo ≤5–10 s.
- RF-04 Se mide el impacto de CPU del TTS junto a STT batch/RAG/sentimiento y se propone un dimensionado inicial de concurrencia/throttling para SPEC-069.
- RF-05 Se entrega una decisión de motor documentada (motor+voz+parámetros+versiones) con recomendación de techo exacto y plan de contingencia escalonado (R-83).

## Requisitos no funcionales
- RNF-01 **Cero egress:** toda la síntesis corre local; ningún guión ni audio sale a un dominio/IP público; TTS de terceros PROHIBIDO. La medición se ejecuta en un contexto sin ruta a internet de inferencia (simétrico a `ia_internal`).
- RNF-REPRO **Reproducibilidad:** guiones, versiones de motor/voz, comandos y hardware documentados; los resultados se pueden regenerar.
- RNF-C3 Sin secretos ni PII real en guiones, scripts o muestras de audio; solo datos ficticios.
- RNF-DECISION La salida es una decisión auditable, no una preferencia; queda evidencia que la sustenta.

## Criterios de aceptación (verificables)
- [ ] Existe el banco de guiones es-CO (cortos/medios/largos con nombres/cifras/siglas), ficticio y versionado.
- [ ] Hay evidencia reproducible (scripts + versiones fijadas + hardware) de Piper y Coqui ejecutados en CPU **sin egress**; eSpeak-NG evaluado solo si ambos incumplen.
- [ ] Existe tabla de resultados con calidad subjetiva (rúbrica documentada) y latencia (media/mediana/p95) por guión y motor, comparada con el techo ≤5–10 s.
- [ ] Existe medición del impacto de CPU concurrente (TTS + STT batch/RAG/sentimiento) y una propuesta de concurrencia/throttling inicial para SPEC-069.
- [ ] Existe una **decisión de motor documentada** (motor+voz+parámetros+versiones) con recomendación de techo exacto dentro de 5–10 s.
- [ ] Existe el **plan de contingencia escalonado (R-83)** por si ningún motor cumple, con la vía priorizada y marcado como decisión del Lead con la evidencia.
- [ ] Ningún guión/audio de prueba contiene PII real ni secretos; ningún artefacto sale a un tercero.

## Notas de seguridad (C2/C3)
- C2: la prueba no persiste datos de negocio; las muestras de audio son ficticias y borrables (no entran en el régimen de retención de producción).
- C3: sin secretos en scripts/guiones/config del benchmark; solo datos ficticios; configuración por env si la hubiera.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (sin egress): TTS **100% local, CPU-only**; ningún motor de terceros ni dominio externo. La medición se hace en un entorno sin ruta a internet de inferencia (equivalente a `ia_internal internal:true`). No introduce egress; no reutiliza `graph.facebook.com` (esta SPEC no sube nada).

## Riesgos
- R-83 (**viabilidad calidad/latencia en CPU**): riesgo de que **ningún motor** cumpla el techo ≤5–10 s con calidad es-CO aceptable → esta SPEC **es la puerta** que lo detecta antes de invertir en F2–F5; plan de contingencia escalonado (relajar techo / degradar motor / acotar longitud / fallback a solo texto), decisión final del Lead con datos. **Riesgo top del plan.**
- R-84 (coste de CPU compartido): se mide el impacto concurrente para dimensionar el throttling de SPEC-069 (CE-86).
- R-87 (residuos de config GPU): `PIPER_VOICE` se re-valida en CPU aquí; `TTS_VRAM_FRACTION`/`TTS_MODE` no aplican (se limpian en SPEC-068).
- R-88 (formato incompatible): la latencia medida incluye la transcodificación a OGG/Opus con `ffmpeg` para reflejar el coste real.

## Checkpoints aplicables
- C3 (sin secretos/PII en guiones y scripts). C4 (criterios verificables). C8 (origen PLAN-008 / `prompt-lab/prompts/PROMPT-008-TTS-NOTAS-VOZ.md`). C6 no aplica (spike sin cambio en producción).
