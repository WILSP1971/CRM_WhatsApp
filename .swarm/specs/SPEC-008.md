# SPEC-008 — Sectores de referencia + analítica multisectorial

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, WOLVERINE, HAWKEYE · Prioridad: MEDIA · Tipo: MÓDULO · Fase: F6
- Deriva de: PLAN-001 (F6) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Construir las vistas de referencia de alta fidelidad para Servicios/Consultoría (hitos de
proyecto, horas facturables, SLA, reservas) y Manufactura (órdenes de trabajo, alertas de
inventario, sync ERP cadena de suministro), más la analítica multisectorial con gráficos (Recharts).

## Contexto

Módulo D del PLAN; Servicios y Manufactura son referencia navegable (SUP-04, R-06), no
completos como Comercial (SPEC-007). Incluye el dashboard de analítica multisectorial.

## Alcance

### IN

- Vista Servicios/Consultoría (referencia): hitos de proyecto, horas facturables, SLA, reservas.
- Vista Manufactura (referencia): órdenes de trabajo, alertas de inventario, sync ERP cadena de suministro (visual).
- Analítica multisectorial: KPIs y gráficos con Recharts (mock, densidad nítida).
- Fixtures JSON para ambos sectores y para la analítica.

### OUT

- Sector Comercial completo (SPEC-007), integración ERP real, backend.

## Dependencias

- Depende de SPEC-003 (layout/router) y SPEC-002 (tokens). Coordina con SPEC-007 (mismo módulo por sector).

## Requisitos funcionales

- RF Vista Servicios muestra hitos, horas facturables, SLA y reservas (referencia).
- RF Vista Manufactura muestra órdenes de trabajo, alertas de inventario y sync ERP (referencia visual).
- RF Analítica multisectorial con ≥3 gráficos Recharts y KPIs.
- RF-10 Datos desde fixtures locales ficticios.

## Requisitos no funcionales

- Estilos desde tokens (RNF-04). Gráficos con lazy-load para performance (R-04).
- Densidad de datos legible a 1920x1080 sin scroll horizontal (RNF-03).

## Criterios de aceptación (verificables)

- [ ] Vista Servicios muestra hitos, horas facturables, SLA y reservas (fixtures).
- [ ] Vista Manufactura muestra órdenes de trabajo, alertas de inventario y sync ERP (fixtures).
- [ ] Analítica multisectorial renderiza ≥3 gráficos Recharts + KPIs sin errores.
- [ ] Sin scroll horizontal 1280–1920; cero errores de consola en ambos temas.
- [ ] DevTools Network sin peticiones a ERP/terceros.

## Accesibilidad (WCAG 2.2 AAA)

- Gráficos con alternativa textual/tabla o `aria-label` describiendo la tendencia.
- Vistas navegables por teclado con foco visible; datos no solo por color.
- Contraste AAA ≥7:1 en textos, ejes y leyendas en ambos temas.

## Restricción SENSIBLE

- Cero llamadas externas: sectores, ERP y analítica son fixtures locales.
- Cero PII real: proyectos, órdenes e inventario explícitamente ficticios.

## Riesgos

- R-06 (expansión de alcance): Servicios/Manufactura solo como referencia.
- R-04 (performance de gráficos): lazy-load; medir en F7.

## Checkpoints aplicables

- C4 (criterios verificables). C8 (origen registrado).
