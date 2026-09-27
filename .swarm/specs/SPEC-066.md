# SPEC-066 — Documentación, runbook, notas OpenAPI, guía de feature-flag y deploy on-prem del dashboard de métricas de negocio

- Estado: PROPUESTA · Responsable: QUICKSILVER · Colaboran: BLACK PANTHER, BLACK WIDOW, WOLVERINE, HAWKEYE, DAREDEVIL · Prioridad: MEDIA · Tipo: DOCS/DEPLOY · Fase: F4
- Deriva de: PLAN-007 (F4) · Clasificación: SENSIBLE (`.no-externo`) · ADR-004/ADR-008
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Cerrar PLAN-007 con la **documentación** del dashboard de métricas de negocio (definición precisa de cada métrica, incluida **"conversión = conversaciones cerradas / totales"**, Q1(a), sin dominio nuevo), las **notas OpenAPI** del endpoint (SPEC-063), la **guía de la feature-flag** (`VITE_USE_REAL_API` para `AnalyticsPage`), la actualización del **runbook operativo** y el **deploy on-prem** (Docker Compose) con **aprobación explícita del Lead** (cambio sensible → notificación Telegram, C6).

## Contexto

El proyecto ya tiene runbook operativo (SPEC-023/034/043/061) y documentación de features previas. Esta SPEC documenta el nuevo dashboard **sin secretos** (solo placeholders): cómo se define cada métrica (para que un supervisor/operador entienda las cifras y su semántica), cómo activar/desactivar la vista real por feature-flag, y cómo desplegar el cambio on-prem. La definición de "conversión" se documenta aquí y en SPEC-062 (no requiere ADR de dominio, Q1(a)).

## Alcance

### IN
- **Documentación de métricas:** definición precisa de conversaciones (total/canal/estado/serie), tiempos de respuesta (TPR + promedio, con el tratamiento de casos límite), y **conversión = cerradas/totales** (Q1(a), explícitamente "sin dominio nuevo / sin ADR de dominio"); semántica del rango (ventana sobre `created_at`), del modo on-demand (Q2) y de los presets de fecha (Q4).
- **Notas OpenAPI** del endpoint (SPEC-063): params, schema de respuesta, ejemplos **sin datos reales**.
- **Guía de la feature-flag** `VITE_USE_REAL_API` para `AnalyticsPage`: cómo se pasa de mock (OFF) a datos reales (ON) y viceversa; comportamiento reversible.
- **Actualización del runbook operativo:** operación del dashboard, límites de rango configurables (env), consideraciones de performance (índices, latencia p95 THOR), verificación de RLS efectiva.
- **Deploy on-prem** (Docker Compose) del cambio, con **aprobación explícita del Lead** (C6, notificación Telegram por cambio sensible).

### OUT
- Implementación de servicio/endpoint/SPA/pruebas (SPEC-062..065).
- Cualquier ADR de dominio de "conversión" (no aplica, Q1(a)).

## Dependencias
- Depende de SPEC-062..065 (slice implementado y probado). Se ancla en ADR-004/ADR-008 (RLS efectiva, a documentar en el runbook) y hereda ADR-003/005 (IA local — solo lectura de columnas persistidas).

## Requisitos funcionales
- RF-01 Existe documentación de las métricas (con la definición de conversión Q1(a)) y de la semántica de rango/on-demand/presets.
- RF-02 El endpoint está documentado en OpenAPI con ejemplos sin datos reales.
- RF-03 Existe guía de la feature-flag `VITE_USE_REAL_API` para `AnalyticsPage`.
- RF-04 El runbook se actualiza; el deploy on-prem se realiza con aprobación del Lead.

## Requisitos no funcionales
- RNF-C3 Documentación y runbook **sin secretos** (solo placeholders).
- RNF-07 El deploy no rompe #1–#6 ni `/metrics`; reversible por feature-flag.

## Criterios de aceptación (verificables)
- [ ] Documentación de métricas publicada, incluida "conversión = cerradas/totales" (Q1(a), sin dominio nuevo/sin ADR de dominio).
- [ ] OpenAPI del endpoint con ejemplos sin datos reales.
- [ ] Guía de feature-flag `VITE_USE_REAL_API` para `AnalyticsPage` (mock ↔ real, reversible).
- [ ] Runbook actualizado (operación, límites de rango, performance, RLS efectiva).
- [ ] Deploy on-prem realizado con **aprobación explícita del Lead** (C6, notificación Telegram); `/metrics` y #1–#6 intactos tras el deploy.
- [ ] Sin secretos en docs/runbook (C3).

## Notas de seguridad (C2/C3)
- C2: la documentación refleja que los agregados excluyen inactivos/anonimizados.
- C3: sin secretos en docs/runbook; solo placeholders.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): el dashboard no introduce egress; el deploy no abre salidas nuevas. La doc enfatiza la RLS efectiva (ADR-004/008) y la ausencia de IA/inferencia nueva.

## Riesgos
- R-74 (regresión al desplegar): deploy reversible por feature-flag; verificación de #1–#6 y `/metrics` tras el deploy.
- (Docs) definición ambigua de métricas: la doc fija la semántica exacta (rango, casos límite, conversión) alineada con SPEC-062.

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C6 (cambio sensible → notificación Telegram en el deploy). C8 (origen PLAN-007 / `prompt-lab/prompts/PROMPT-007-CRM-ANALYTICS.md`).
