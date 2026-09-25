# SPEC-047 — STT streaming liviano en vivo sobre GPU compartida 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, THOR, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: CRÍTICA · Tipo: BACKEND/IA/STT · Fase: F3
- Deriva de: PLAN-005 (F3, §3.1/§3.3/§3.6.1/§3.6.3, ruta crítica dura) · Clasificación: SENSIBLE (`.no-externo`) · ADR-009/ADR-011
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Implementar el **`voice_stt`**: transcripción en vivo de baja latencia sobre el audio-in del `voice_gateway`, con un modelo **liviano** (`distil-whisper` o `faster-whisper` `small`/`medium` **cuantizado** int8/int8_float16) en **streaming de ventana deslizante**, produciendo **transcripción parcial** para el NLU de intent; con la **prioridad de GPU** frente al `stt_worker` batch de #4 **activa** (ADR-011) e **instrumentación de la latencia parcial**; **sin egress**. Es el primer eslabón de la **ruta crítica dura** (F3+F4+F6): sostiene el presupuesto ≤700 ms p95 sobre GPU compartida.

## Contexto

El `stt_worker` batch de #4 (SPEC-038) usa `large-v3` optimizado para **calidad** (transcripción legal de la ficha), no para latencia. La voz en vivo tiene la restricción inversa: latencia dura, calidad suficiente. Por la GPU compartida (P3, §3.6.1), el STT en vivo usa un modelo **mucho más liviano**, aceptando **mayor WER** porque el camino de voz solo **clasifica intent contra un catálogo cerrado** (SPEC-045) — tolera transcripción imperfecta mejor que un resumen; la transcripción "de calidad" se **recomputa en batch** con `large-v3` de #4 al colgar, sin coste en vivo (SPEC-051). Este servicio activa la **prioridad de GPU** de ADR-011 (marca "llamada en vivo activa" para despriorizar el batch) y expone las métricas de latencia parcial que THOR usará en F6 para fijar `C`. Vive en `ia_internal internal:true`; recibe el audio del `voice_gateway` por la red interna, nunca del PBX ni de internet.

## Alcance

### IN
- `voice_stt` en `ia_internal internal:true`: consume frames de audio-in del `voice_gateway` por la red interna; **sin egress**.
- Modelo STT liviano **parametrizable por env** (`distil-whisper` / `faster-whisper` `small`/`medium`, cuantización int8/int8_float16); pesos montados por volumen (SPEC-044).
- **Streaming de ventana deslizante:** transcripción **parcial** incremental de baja latencia (no espera al fin de la locución); emite hipótesis parciales al orquestador de diálogo (SPEC-048) para clasificar intent lo antes posible.
- **Activación de la prioridad de GPU** (ADR-011): al iniciar una llamada en vivo, marca la señal (lock/flag Redis) que despriorza/pausa el `stt_worker` batch; la libera al terminar todas las llamadas activas.
- **Uso de la fracción de VRAM reservada** para la voz (SPEC-044), evitando competir por asignación bajo carga.
- **Instrumentación de latencia parcial:** tiempo audio-in → primera hipótesis parcial y → hipótesis estabilizada, por turno y agregado (p50/p95), expuesto en `/metrics` interno.
- Respeto del **límite de concurrencia `C`** (SPEC-044/SPEC-050): no arranca STT en vivo por encima de `C` (la llamada C+1 la maneja el gateway con IVR mínimo, SPEC-046/049).

### OUT
- Clasificación de intent sobre la transcripción parcial (SPEC-045); orquestación del turno, TTS y barge-in (SPEC-048); fijación empírica de `C` y verificación de la prioridad bajo carga (SPEC-050); recomputo batch de la transcripción de calidad al colgar (SPEC-051).

## Dependencias
- Depende de SPEC-044 (infra `voice_stt`/prioridad GPU/VRAM reservada) y SPEC-046 (audio-in en vivo por la red interna). Prerequisito de SPEC-048 (bucle de diálogo). Se ancla en ADR-009 (STT local) y ADR-011 (GPU compartida priorizada). Reutiliza el motor `faster-whisper` de SPEC-038 (configuración liviana distinta).

## Requisitos funcionales
- RF-01 `voice_stt` transcribe el audio-in en vivo en modo streaming de ventana deslizante, emitiendo hipótesis parciales.
- RF-02 El modelo y su cuantización son parametrizables por env; los pesos se montan por volumen (sin `pull` en runtime).
- RF-03 Al haber ≥1 llamada en vivo activa, `voice_stt` marca la prioridad de GPU (despriorza el batch); la libera al terminar.
- RF-04 Expone métricas de latencia parcial (audio-in → parcial) por turno y agregadas.
- RF-05 No arranca STT en vivo por encima del límite `C`.

## Requisitos no funcionales
- RNF-51 STT en vivo 100% local, sin egress (ADR-009/ADR-011).
- RNF-56 Presupuesto de latencia parcial acotado (contribución del STT al presupuesto ≤700 ms p95; valor final fijado por THOR en SPEC-050).
- RNF-58 WER del modelo liviano documentado; se acepta mayor que `large-v3` porque solo alimenta la clasificación de intent contra catálogo cerrado.

## Criterios de aceptación (verificables)
- [ ] Con el simulador (SPEC-052), un audio es-CO ficticio en vivo produce transcripción parcial incremental de baja latencia (no espera al fin de la locución).
- [ ] El modelo/cuantización se cambia por env sin tocar código; pesos por volumen (sin `pull` en runtime).
- [ ] Al iniciar una llamada en vivo se marca la prioridad de GPU y el `stt_worker` batch reduce/suspende consumo; al terminar todas las llamadas, se libera y el batch reanuda (verificación funcional; la medición bajo carga es SPEC-050).
- [ ] Un intento de egress desde `voice_stt` a IP/dominio público **falla** (timeout/deny).
- [ ] `/metrics` expone latencia parcial (p50/p95) por turno; WER del modelo liviano documentado sobre el set ficticio.
- [ ] Con `C` llamadas activas, una nueva no arranca STT en vivo (la maneja el gateway); no se degradan las activas.

## Notas de seguridad (C2/C3)
- C3: sin secretos; el modelo/cuantización/VRAM no son secretos; audio en tránsito solo por red interna.
- C2: el audio en vivo no se persiste aquí; la persistencia/retención es SPEC-051 (borrado lógico + retención de #4).

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el `voice_stt` vive en `ia_internal internal:true`, recibe audio solo por red interna y **nunca** sale (ADR-009/ADR-011). Prueba de egress vacío obligatoria (SPEC-051).

## Riesgos
- R-51 (latencia ≤700 ms no alcanzable): modelo liviano cuantizado + ventana deslizante; prioridad de GPU + VRAM reservada; medición y fijación de `C`/degradación en SPEC-050.
- R-52 (contención de GPU): activa la prioridad de la voz (despriorza el batch) + fracción de VRAM reservada (ADR-011); instrumentación en SPEC-050.
- R-58 (WER alto degrada la clasificación): tolerado por el catálogo cerrado; umbral + escalación (SPEC-045/049); transcripción de calidad recomputada en batch (SPEC-051).
- R-54 (audio a terceros): aislamiento en `ia_internal`; prueba de egress vacío.

## Checkpoints aplicables
- C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-005).
