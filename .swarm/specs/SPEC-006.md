# SPEC-006 — VoiceBot + telefonía VoIP (representación)

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, WOLVERINE, HAWKEYE, BLACK WIDOW · Prioridad: MEDIA · Tipo: MÓDULO · Fase: F5
- Deriva de: PLAN-001 (F5) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Construir el centro de llamadas VoiceBot/VoIP: webphone/marcador, visualizador de onda de
audio animado (mock), transcripción voz-a-texto en vivo (mock), controles de grabación,
detección de intención IA (mock) e historial de llamadas. Todo es representación visual.

## Contexto

Módulo C del PLAN. No hay VoIP ni audio real; la onda, la transcripción y la intención son
simuladas con datos pre-grabados (SUP-03).

## Alcance

### IN

- Webphone/marcador con estados (en llamada / en espera / colgado).
- Visualizador de onda de audio animado (mock, sin captura real de micrófono).
- Transcripción voz-a-texto incremental simulada (aparece progresivamente).
- Controles/indicador de grabación (representación, sin grabar audio real).
- Chip de intención detectada por IA (mock).
- Historial de llamadas (fixtures).

### OUT

- IP-PBX/VoIP real, captura o grabación de audio real, transcripción/STT real.

## Dependencias

- Depende de SPEC-003 (layout/router) y SPEC-002 (tokens/primitivas).

## Requisitos funcionales

- RF-06 El webphone muestra estados, onda animada, transcripción incremental simulada y chip de intención.
- RF Controles de grabación con indicador visual (sin grabar audio real).
- RF-10 Historial y transcripción desde fixtures ficticios.

## Requisitos no funcionales

- Onda y transcripción a 60 fps, GPU-friendly (R-04). Estilos desde tokens (RNF-04).
- Sin solicitar permisos de micrófono del navegador.

## Criterios de aceptación (verificables)

- [ ] El webphone transita entre estados (en llamada/espera/colgado) visualmente.
- [ ] La onda de audio se anima sin capturar micrófono (sin prompt de permisos).
- [ ] La transcripción aparece incrementalmente desde fixtures.
- [ ] Se muestra el chip de intención y el historial de llamadas (fixtures).
- [ ] DevTools Network sin peticiones a VoIP/STT/terceros. Cero errores de consola en ambos temas.

## Accesibilidad (WCAG 2.2 AAA)

- Todos los controles operables por teclado con foco visible.
- Onda con alternativa textual/estado; animación respeta `prefers-reduced-motion`.
- Transcripción en región `aria-live` para lectores de pantalla.
- Contraste AAA ≥7:1 en textos y controles en ambos temas.

## Restricción SENSIBLE

- Cero llamadas externas: audio, STT e intención son pre-grabados locales.
- Cero PII real: transcripciones e historial explícitamente ficticios.

## Riesgos

- R-01 (fuga a STT/VoIP externo): sin clientes de red; verificación DevTools.
- R-04 (performance de onda/animación): GPU-friendly, medir en F7.

## Checkpoints aplicables

- C4 (criterios verificables). C6 (representa grabación/datos de voz). C8 (origen registrado).
