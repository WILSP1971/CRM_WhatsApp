# SPEC-050 — Latencia/GPU compartida (THOR) + fijación de `C` + política de degradación/bajo-cómputo 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: THOR · Colaboran: HAWKEYE, BLACK PANTHER, WOLVERINE, BLACK WIDOW, CAPTAIN AMERICA · Prioridad: CRÍTICA · Tipo: PERFORMANCE/QA · Fase: F6
- Deriva de: PLAN-005 (F6, §3.3/§3.6, puerta de viabilidad, CE-51/CE-52) · Clasificación: SENSIBLE (`.no-externo`) · ADR-011/ADR-012
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Ejecutar la **puerta de viabilidad** de la fase: medir la **latencia end-to-end p95 del turno de voz en vivo** bajo concurrencia **compartiendo GPU con el `stt_worker` batch de #4**, **fijar empíricamente el límite duro `C`** (1-3, P-K), **verificar la prioridad de GPU** (la voz gana; el batch se despriorza/pausa y **reanuda**; **backlog del batch inducido cuantificado**, P-D), y —si **≤700 ms p95** no se cumple bajo `C`— **documentar la degradación** y **activar el modo bajo-cómputo pregrabado** (interfaz conmutable de SPEC-048/ADR-012). Aquí se confirma si el VoiceBot en vivo es viable sobre GPU compartida o si el alcance se recorta a IVR de comandos cortos (decisión del Lead).

## Contexto

R-51/R-52 son el **Top-1** de riesgo de toda la fase: el presupuesto ≤700 ms sobre **GPU compartida** (sin GPU dedicada, P3) es el mayor riesgo técnico. Esta SPEC es análoga a la validación "RTF ≤1.0 GPU o degradación CPU documentada" de #4 (SPEC-042), aplicada a **latencia conversacional** y **contención de dos cargas en la misma GPU**. Reutiliza la infra de carga de #2/#3/#4 (Locust) y el simulador de llamada en vivo (SPEC-052). Sin PBX real, la medición usa audios es-CO ficticios inyectados por el simulador. El valor de `C` y la política de degradación que resulten aquí **retroalimentan** SPEC-044 (config), SPEC-047 (STT), SPEC-048 (bucle) y SPEC-049 (escalación por latencia sostenida).

## Alcance

### IN
- **Medición end-to-end p95** del turno (audio-in → STT parcial → NLU → TTS → audio-out) bajo concurrencia, con el `stt_worker` batch de #4 corriendo en paralelo (contención real).
- **Fijación empírica de `C`** (arranque 1-3): el mayor número de llamadas en vivo simultáneas que mantiene p95 ≤700 ms (o el mejor alcanzable); documentado con evidencia.
- **Verificación de la prioridad de GPU** (CE-52, ADR-011): con ≥1 llamada en vivo activa, la voz mantiene latencia estable y el `stt_worker` batch se despriorza/pausa; al liberarse la voz, el batch **reanuda**; **backlog del batch inducido cuantificado** (tiempo de recuperación, tamaño de cola acumulada).
- **Barge-in medible** (CE-54): tiempo de corte de la síntesis al interrumpir, bajo carga.
- **Política de degradación:** si p95 ≤700 ms no se cumple bajo `C`, se **documenta la degradación medida** y se **activa el modo bajo-cómputo** (audios pregrabados, coste GPU ~0); se re-mide. Si ni con modo bajo-cómputo y `C=1` es aceptable → recomendación de recorte a **IVR de comandos cortos** (decisión del Lead), documentada.
- **Comparativa de modelos** (THOR): STT liviano candidatos (`distil-whisper` vs `faster-whisper small/medium` cuantizado) y TTS (Piper vs pregrabado vs Coqui) por latencia/VRAM; recomendación parametrizada por env.
- **Observabilidad de latencia y contención:** p50/p95 por etapa del turno, tasa de barge-in, tasa de escalación por latencia, contención de GPU (espera de la voz, backlog del batch), alertas al superar el presupuesto o el límite `C`.

### OUT
- Implementación del simulador (SPEC-052); implementación de los servicios medidos (SPEC-044..049); barrido de seguridad/persistencia/retención (SPEC-051).

## Dependencias
- Depende de SPEC-044 (prioridad GPU/VRAM), SPEC-047 (STT), SPEC-048 (bucle/barge-in), SPEC-049 (escalación por latencia) y del simulador SPEC-052. Se ancla en ADR-011 (GPU compartida priorizada) y ADR-012 (interfaz conmutable). Retroalimenta la config de SPEC-044/047/048/049.

## Requisitos funcionales
- RF-01 Existe la medición end-to-end p95 del turno bajo concurrencia con el batch en paralelo.
- RF-02 `C` se fija empíricamente y se documenta con evidencia.
- RF-03 La prioridad de GPU se verifica: voz estable + batch despriorizado/reanudado + backlog cuantificado.
- RF-04 La política de degradación (modo bajo-cómputo) se activa y re-mide si ≤700 ms no se cumple.

## Requisitos no funcionales
- RNF-56 Presupuesto **p95 ≤ 700 ms** end-to-end bajo `C` compartiendo GPU, **o** degradación documentada + modo bajo-cómputo activado (nunca una experiencia rota).
- RNF-52 Prioridad de GPU verificada; impacto en el SLA del batch de #4 cuantificado y aceptado (P-D).
- RNF-07 Suites #1-#4 verdes; el batch de #4 sigue funcional (reanuda tras la voz).

## Criterios de aceptación (verificables)
- [ ] Informe THOR de latencia end-to-end: **p95 ≤ 700 ms** bajo `C` con el batch en paralelo, **o** degradación documentada + modo bajo-cómputo activado y re-medido (CE-51).
- [ ] `C` fijado empíricamente (valor + evidencia); la llamada C+1 recibe IVR mínimo + escalación sin degradar activas (verificado).
- [ ] Prioridad de GPU verificada (CE-52): con ≥1 llamada en vivo, la voz mantiene p95; el `stt_worker` batch se despriorza/pausa y **reanuda** al liberarse; **backlog inducido cuantificado** (cola acumulada + tiempo de recuperación).
- [ ] Barge-in medible bajo carga: tiempo de corte de la síntesis por debajo del umbral definido (CE-54).
- [ ] Comparativa de modelos STT/TTS documentada (latencia/VRAM); recomendación parametrizada por env.
- [ ] Métricas de latencia por etapa, contención de GPU y backlog del batch expuestas; alertas al superar presupuesto/`C`.
- [ ] Suites #1-#4 verdes; el batch de #4 sigue transcribiendo tras la voz (sin regresión funcional).

## Notas de seguridad (C2/C3)
- C3: la carga usa audios ficticios/placeholders; sin secretos ni datos reales/PHI.
- C2: no aplica creación de entidades; el batch de #4 conserva su comportamiento.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: la medición corre 100% local con audios ficticios; ningún servicio de voz/IA sale del host durante la carga (se verifica en SPEC-051). El impacto de la prioridad sobre el batch de #4 se documenta como coste aceptado de la GPU compartida (P-D).

## Riesgos
- R-51 (≤700 ms no alcanzable): esta SPEC es la puerta de viabilidad; modo bajo-cómputo pregrabado + recorte a IVR de comandos cortos como último recurso documentado.
- R-52 (contención de GPU): verificación de prioridad + fracción de VRAM reservada; backlog del batch cuantificado (impacto aceptado, P-D).
- R-56 (barge-in): medición del tiempo de corte bajo carga (CE-54).
- R-61 (regresión #4): el batch reanuda tras la voz; suites #1-#4 verdes; backlog documentado como impacto aceptado.

## Checkpoints aplicables
- C3 (sin secretos, audios ficticios). C4 (criterios verificables). C8 (origen PLAN-005).
