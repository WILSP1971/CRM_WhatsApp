# SPEC-007 — Sector Comercial / E-Commerce (PRIORITARIO)

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, WOLVERINE, HAWKEYE · Prioridad: ALTA · Tipo: MÓDULO · Fase: F6
- Deriva de: PLAN-001 (F6) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Construir el sector prioritario Comercial/E-Commerce completo: embudo de ventas Kanban con
drag & drop (dnd-kit), seguimiento de pedidos, indicadores de venta cruzada y KPIs.

## Contexto

Módulo D del PLAN, sector completo por SUP-04. Es la vista más rica del panel por sector;
Servicios y Manufactura (SPEC-008) quedan como referencia.

## Alcance

### IN

- Embudo de ventas Kanban con columnas de etapa y tarjetas arrastrables (dnd-kit).
- Seguimiento de pedidos (estados/timeline, fixtures).
- Indicadores de venta cruzada (sugerencias/oportunidades mock).
- KPIs comerciales (tarjetas de métricas).

### OUT

- Sectores Servicios/Manufactura (SPEC-008), gráficos analíticos multisectoriales (SPEC-008), backend/pedidos reales.

## Dependencias

- Depende de SPEC-003 (layout/router) y SPEC-002 (tokens/primitivas).

## Requisitos funcionales

- RF-07 Kanban de embudo con tarjetas arrastrables entre etapas (o estados visuales equivalentes).
- RF-07 Módulo de seguimiento de pedidos y de venta cruzada.
- RF KPIs comerciales visibles con densidad de datos nítida.
- RF-10 Datos desde fixtures locales ficticios.

## Requisitos no funcionales

- Estilos desde tokens (RNF-04). Drag & drop fluido; interacciones <100 ms.
- Densidad de datos legible a 1920x1080 sin scroll horizontal (RNF-03).

## Criterios de aceptación (verificables)

- [ ] Kanban con ≥3 etapas y tarjetas que se mueven entre columnas por drag & drop.
- [ ] Existe fallback de teclado para mover tarjetas (dnd-kit accesible).
- [ ] Seguimiento de pedidos muestra estados por pedido (fixtures).
- [ ] Se muestran indicadores de venta cruzada y ≥3 KPIs comerciales.
- [ ] Sin scroll horizontal 1280–1920; cero errores de consola en ambos temas.

## Accesibilidad (WCAG 2.2 AAA)

- Kanban operable por teclado (mover tarjetas sin ratón) con anuncios `aria-live`.
- Foco visible en tarjetas, columnas y controles; roles ARIA de lista/opción.
- Estados no dependen solo del color (etiqueta/icono). Contraste AAA ≥7:1 en ambos temas.

## Restricción SENSIBLE

- Cero llamadas externas: embudo, pedidos y KPIs son fixtures locales.
- Cero PII real: clientes/pedidos explícitamente ficticios.

## Riesgos

- R-08 (accesibilidad de drag & drop): dnd-kit accesible + fallback teclado; prueba HAWKEYE.
- R-06 (expansión de alcance): solo Comercial completo aquí.

## Checkpoints aplicables

- C4 (criterios verificables). C8 (origen registrado).
