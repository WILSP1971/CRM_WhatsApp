# SPEC-004 — Bandeja omnicanal unificada

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, WOLVERINE, HAWKEYE · Prioridad: ALTA · Tipo: MÓDULO · Fase: F3
- Deriva de: PLAN-001 (F3) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Construir la bandeja omnicanal: lista de conversaciones multicanal (WhatsApp/Instagram/
Messenger/WebChat) con iconos de canal, hilo de conversación unificado, etiquetas de
sentimiento (mock) y estados de mensaje, con panel de contacto 360°.

## Contexto

Módulo A del PLAN. Es el ancla visual del panel RAG (SPEC-005), que se acopla a su costado.
Conviene entregarse antes o junto con SPEC-005.

## Alcance

### IN

- Lista de conversaciones: canal (icono), sentimiento (positivo/neutral/negativo mock), último mensaje, no-leídos, estado.
- Hilo unificado al abrir una conversación (mensajes entrantes/salientes, estados de mensaje).
- Etiquetas de sentimiento presentadas como resultado de IA (representación, no cálculo real).
- Panel de contacto 360° (datos ficticios: historial, canales, etiquetas).
- Fixtures JSON de conversaciones y contactos.

### OUT

- Envío real de mensajes, integraciones reales, panel RAG (SPEC-005).

## Dependencias

- Depende de SPEC-003 (layout/router) y SPEC-002 (tokens/primitivas).

## Requisitos funcionales

- RF-04 Por conversación se ve canal, sentimiento, último mensaje, no-leídos y estado.
- RF-04 Al abrir una conversación se muestra el hilo + panel 360° del contacto.
- RF-10 Todos los datos provienen de fixtures locales ficticios.

## Requisitos no funcionales

- Estilos desde tokens (RNF-04). Densidad de datos legible a 1920x1080.
- Lista virtualizable/eficiente si el fixture crece; interacciones <100 ms.

## Criterios de aceptación (verificables)

- [ ] La lista muestra ≥8 conversaciones con los 4 canales representados y sus iconos.
- [ ] Cada conversación muestra sentimiento, no-leídos y estado de mensaje.
- [ ] Al seleccionar una conversación se abre el hilo unificado y el panel 360°.
- [ ] Datos provienen de fixtures JSON ficticios (verificable en `src/mocks/`).
- [ ] Cero errores de consola en ambos temas.

## Accesibilidad (WCAG 2.2 AAA)

- Lista navegable por teclado; selección con Enter/Space; foco visible.
- Iconos de canal con texto alternativo/`aria-label`; sentimiento no solo por color (icono/etiqueta).
- Contraste AAA ≥7:1 en textos de la lista, hilo y panel 360° en ambos temas.

## Restricción SENSIBLE

- Cero llamadas externas: sentimiento y mensajes son datos pre-grabados locales.
- Cero PII real: nombres, teléfonos y textos explícitamente ficticios (R-05).

## Riesgos

- R-05 (mock que parezca PII): fixtures marcados como ficticios; barrido BLACK WIDOW.
- R-04 (performance de lista): virtualización si es necesario.

## Checkpoints aplicables

- C4 (criterios verificables). C8 (origen registrado).
