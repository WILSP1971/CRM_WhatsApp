# SPEC-005 — Panel lateral RAG en vivo (representación)

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, WOLVERINE, HAWKEYE, BLACK WIDOW · Prioridad: MEDIA · Tipo: MÓDULO · Fase: F4
- Deriva de: PLAN-001 (F4) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Construir el panel lateral RAG que acompaña la bandeja: asistente contextual con fragmentos
de citas (mock de base vectorial), borradores de respuesta autogenerados (mock) y sugerencias
de producto/servicio. Toda la IA es representación visual, sin invocar ningún modelo.

## Contexto

Módulo B del PLAN. Se integra visualmente junto a la bandeja (SPEC-004). Es donde el riesgo
de "IA real" es mayor: aquí todo es pre-grabado (R-01/SUP-03).

## Alcance

### IN

- Asistente contextual con ≥3 citas/fuentes (fragmentos con nombre de fuente, mock vectorial).
- Borrador de respuesta autogenerado (mock) con acción visual "Insertar borrador".
- ≥2 sugerencias de producto/servicio (mock).
- Se integra como panel lateral acoplado a la bandeja.
- Fixtures JSON RAG (citas, borradores, sugerencias).

### OUT

- Llamadas a LLM/embeddings/base vectorial reales; envío real del borrador.

## Dependencias

- Depende de SPEC-004 (bandeja) y SPEC-002/003 (tokens/layout).

## Requisitos funcionales

- RF-05 Muestra ≥3 citas con fuente, un borrador sugerido y ≥2 sugerencias de producto (mock).
- RF-05 Acción visual "Insertar borrador" que coloca el texto en el compositor (mock, sin envío).
- RF-10 Datos desde fixtures locales ficticios.

## Requisitos no funcionales

- Estilos desde tokens (RNF-04). Estados de "generando…" simulados con animación GPU-friendly.
- Interacciones <100 ms.

## Criterios de aceptación (verificables)

- [ ] El panel muestra ≥3 citas, cada una con su fuente identificable.
- [ ] Muestra un borrador sugerido y ≥2 sugerencias de producto.
- [ ] "Insertar borrador" coloca el texto en el compositor sin realizar envío real.
- [ ] DevTools Network sin peticiones a servicios de IA/terceros durante el uso.
- [ ] Cero errores de consola en ambos temas.

## Accesibilidad (WCAG 2.2 AAA)

- Panel y acciones operables por teclado con foco visible.
- Citas y sugerencias con estructura semántica (listas/regiones con `aria-label`).
- Estado "generando…" anunciado con `aria-live` (no solo animación).
- Contraste AAA ≥7:1 en textos del panel en ambos temas.

## Restricción SENSIBLE

- Cero llamadas externas: RAG, sentimiento y borradores son datos pre-grabados locales.
- Cero PII real: citas y sugerencias explícitamente ficticias.

## Riesgos

- R-01 (fuga a IA externa): verificación de red; sin ningún cliente de LLM.
- R-05 (mock que parezca PII): fixtures marcados; barrido BLACK WIDOW.

## Checkpoints aplicables

- C4 (criterios verificables). C6 (representa IA/datos personales: revisión Lead). C8 (origen registrado).
