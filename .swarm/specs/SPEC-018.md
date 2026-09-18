# SPEC-018 — Análisis de sentimiento del mensaje entrante con LLM local

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: MEDIA · Tipo: IA/BACKEND · Fase: F5
- Deriva de: PLAN-002 (F5) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Clasificar el **sentimiento** de cada mensaje entrante (positivo / neutral / negativo + `score`) usando el **LLM local** de SPEC-016, y **persistir** el resultado asociado al mensaje bajo RLS.

## Contexto

Fase F5: sobre los mensajes reales del WebChat (SPEC-015) se ejecuta una clasificación de sentimiento con el LLM local (cero externos). El resultado se persiste junto al mensaje para que la Bandeja/analítica lo consuma (render real en SPEC-020). Detección de intención avanzada queda OUT (Fase 3).

## Alcance

### IN
- Clasificación de sentimiento del mensaje entrante: etiqueta {positivo, neutral, negativo} + `score` (0..1).
- Prompt/few-shots afinados para español (es-CO) con el LLM local.
- Persistencia del sentimiento (etiqueta + score) asociado al mensaje, bajo RLS por tenant.
- Ejecución asíncrona (cola Redis) para no bloquear la recepción del mensaje.

### OUT
- Detección de intención avanzada / enrutamiento automático (Fase 3).
- Borrador RAG y human-in-the-loop (SPEC-019).
- Visualización del sentimiento en la SPA (SPEC-020).

## Dependencias
- Depende de SPEC-016 (LLM local) y SPEC-015 (mensajes del WebChat) / SPEC-014 (modelo de mensajes). Prerequisito parcial de SPEC-020 (render).

## Requisitos funcionales
- RF-07 Un mensaje entrante recibe una etiqueta de sentimiento + score del LLM local.
- RF El sentimiento se persiste asociado al mensaje del tenant correcto.
- RF La clasificación no bloquea la recepción/persistencia del mensaje (asíncrona).

## Requisitos no funcionales
- RNF-01 Clasificación 100% local (cero externos).
- RNF-02 Aislamiento por tenant en la persistencia del sentimiento.
- RNF-04 Latencia de clasificación medida (formal en SPEC-022, THOR).

## Criterios de aceptación (verificables)
- [ ] Un mensaje entrante genera una etiqueta {positivo|neutral|negativo} + `score` en [0,1].
- [ ] El sentimiento queda persistido y asociado al mensaje correcto del tenant correcto.
- [ ] La clasificación se ejecuta de forma asíncrona sin bloquear la recepción del mensaje.
- [ ] La clasificación usa el LLM local (sin llamadas externas; verificado por egress vacío/captura de red).
- [ ] Un mensaje de otro tenant no queda accesible al consultar el sentimiento (RLS).

## Notas de seguridad (C2/C3)
- C2: el sentimiento sigue el ciclo de vida del mensaje (borrado lógico).
- C3: config del modelo/cola SOLO en env.

## Restricción SENSIBLE aplicable
- Clasificación on-prem con LLM local; ningún tercero ve el contenido del mensaje. Cero inferencia externa (CE-21).

## Riesgos
- R-27 (calidad del modelo en es-CO): prompts/few-shots afinados; modelo cambiable por env.
- R-22 (fuga de egress IA): egress bloqueado + verificación (SPEC-016/022).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-002).
