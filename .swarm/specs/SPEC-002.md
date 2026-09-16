# SPEC-002 — Design system: tokens, temas y primitivas UI

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, WOLVERINE, HAWKEYE · Prioridad: ALTA · Tipo: FUNDACIONAL · Fase: F1
- Deriva de: PLAN-001 (F1) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Definir el sistema de diseño de OmniCore AI: design tokens (color, tipografía Inter
self-hosted, espaciado, radios 12–16px, sombras, blur glassmorphism), tema claro/oscuro
con toggle persistente y primitivas UI accesibles (Button, Card, Badge, Input, Tabs, Tooltip).

## Contexto

Prerrequisito duro de SPEC-003 a SPEC-008: todo componente usa tokens; sin ellos no hay
consistencia (RNF-04) ni contraste AAA (RNF-01). Glassmorphism debe convivir con AAA (R-02).

## Alcance

### IN

- Design tokens como CSS variables: paleta (azul pizarra/marino, índigo eléctrico, cian IA, gris neutro; estados esmeralda/ámbar/coral), escala tipográfica, spacing, radios 12–16px, sombras, blur.
- Tipografía Inter self-hosted (`@fontsource/inter`), sin fuentes remotas.
- Tema oscuro (default) + claro compartiendo tokens; toggle persistente (localStorage) sin parpadeo.
- Primitivas UI accesibles: Button, Card, Badge, Input, Tabs, Tooltip (base Radix/shadcn).
- Documento/catálogo de tokens y componentes.

### OUT

- Layout global (SPEC-003), módulos funcionales, gráficos (SPEC-008).

## Dependencias

- Depende de SPEC-001. Prerrequisito duro de SPEC-003 a SPEC-008.

## Requisitos funcionales

- RF Toggle de tema aplica tokens en toda la UI sin parpadeo (RF-03).
- RF El tema seleccionado persiste entre recargas de la sesión.
- RF Cada primitiva expone variantes (estados hover/active/disabled/focus) basadas en tokens.

## Requisitos no funcionales

- 100% de color/spacing/radio/tipografía desde tokens (RNF-04, cero hardcode).
- Contraste de texto ≥7:1 (normal) y ≥4.5:1 (grande) en ambos temas, incluido sobre glassmorphism.
- Glassmorphism con capa de fondo sólida mínima para garantizar contraste (R-02).

## Criterios de aceptación (verificables)

- [ ] Tokens definidos como CSS variables; grep confirma cero colores/spacing/radios hardcodeados en primitivas.
- [ ] Inter cargada self-hosted; DevTools Network sin peticiones de fuentes externas.
- [ ] Toggle claro/oscuro cambia todos los primitivos sin parpadeo y persiste tras recargar.
- [ ] axe/checker: contraste ≥7:1 en las 6 primitivas en ambos temas.
- [ ] Las 6 primitivas renderizan en un catálogo/preview navegable.

## Accesibilidad (WCAG 2.2 AAA)

- Contraste AAA ≥7:1 verificado por token de color de texto sobre cada fondo (incluye vidrio).
- Todas las primitivas con roles/labels ARIA, foco visible y operables por teclado.
- Tooltip accesible (aparece con foco de teclado, `aria-describedby`).

## Restricción SENSIBLE

- Cero llamadas externas: Inter y iconos self-hosted; sin CDNs.
- Cero PII real: los ejemplos del catálogo son ficticios.

## Riesgos

- R-02 (glass vs AAA): capa sólida mínima y auditoría por tema.
- R-03 (licencias): Inter OFL self-hosted, prohibido SF Pro.
- R-07 (deriva): lint de tokens, revisión WOLVERINE.

## Checkpoints aplicables

- C4 (criterios verificables). C3 (sin secretos). C8 (origen registrado).
