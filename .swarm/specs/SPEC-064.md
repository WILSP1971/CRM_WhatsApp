# SPEC-064 — SPA: `AnalyticsPage` a datos REALES por feature-flag (reemplaza el mock, Q3) — KPIs, series temporales, desglose por canal, selector de rango (hoy/7d/30d + custom)

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, BLACK PANTHER, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: FRONTEND · Fase: F2
- Deriva de: PLAN-007 (F2, Q3/Q4) · Clasificación: SENSIBLE (`.no-externo`) · ADR-004
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Conectar la página `AnalyticsPage.tsx` a los datos **reales** del endpoint de métricas de negocio (SPEC-063) por **feature-flag** (`VITE_USE_REAL_API`, patrón SPEC-020/031), **reemplazando** el contenido mock (Q3): con el flag **ON** la página muestra KPIs numéricos, series temporales y desglose por canal calculados sobre la BD del tenant, con un **selector de rango de fechas** (presets **hoy / 7 días / 30 días + rango custom**, Q4) y estados **carga / vacío / error accesibles (AAA)**. Con el flag **OFF**, la maqueta de #1 (`kpis.json`/`analytics.json`/`sales.json`, SPEC-008) permanece **intacta** (sin regresión). Misma ruta/página; no convive maqueta paralela ni se crea página separada.

## Contexto

`AnalyticsPage.tsx` (`src/pages/`) es hoy el dashboard "Analítica multisectorial" (SPEC-008) **100% mock** (`kpis.json`, `analytics.json`, `sales.json`), con `KpiCard`, `RevenueBySectorChart`, `CsatTrendChart`, `PipelineDonutChart`. La SPA ya consume APIs reales por feature-flag `VITE_USE_REAL_API` (SPEC-020) y el canal WhatsApp/otros módulos ya se integraron bajo ese patrón (SPEC-031/040). El design system del Entregable #1 (WCAG AAA) provee los componentes de KPI/gráficos; **no se duplican** componentes de gráfico si los existentes sirven. La decisión del Lead (Q3) es **reemplazar** el contenido mock por datos reales bajo el flag, no crear una página nueva ni conservar la maqueta en paralelo.

## Alcance

### IN
- **Cliente de datos** para el endpoint SPEC-063 (fetch parametrizado por `desde`/`hasta`/`canal`), gobernado por `VITE_USE_REAL_API`: ON → API real; OFF → mock existente (sin cambios).
- **Reemplazo del contenido de `AnalyticsPage`** (con flag ON) para mostrar métricas de negocio reales: KPIs (conversaciones total/abiertas/cerradas, tasa de conversión, TPR, respuesta promedio), **serie temporal** (conversaciones por día) y **desglose por canal**. Reutiliza componentes de KPI/gráfico del design system existente donde apliquen; adapta los tipos.
- **Selector de rango de fechas:** presets **hoy / 7 días / 30 días** + **rango custom** (Q4). Al cambiar el rango/canal, re-consulta el endpoint (on-demand).
- **Estados accesibles (AAA):** carga (skeleton/spinner con aria), **vacío** (rango sin datos → mensaje claro, no error), **error** (fallo de red/servidor → mensaje accesible + reintento). Contraste/aria conforme SPEC-009.
- **Contrato de tipos** (`src/lib/types.ts`) extendido de forma aditiva para la respuesta de métricas de negocio, sin romper tipos existentes.
- Flag **OFF = maqueta de #1 intacta** (sin regresión visual/funcional).

### OUT
- Backend/servicio/endpoint (SPEC-062/063).
- Exportación PDF/CSV, alertas/umbrales, tiempo real/WebSocket (fuera de PLAN-007).
- Nuevos gráficos de negocio que requieran datos inexistentes (CSAT real, ingresos) — no hay fuente.
- Cambios en Prometheus/observabilidad técnica.

## Dependencias
- Depende de SPEC-063 (endpoint) y reutiliza SPEC-020 (feature-flag `VITE_USE_REAL_API`), SPEC-031 (patrón de integración SPA↔API real) y el design system de SPEC-002/008/009. Se ancla en ADR-004 (la SPA hereda el aislamiento por tenant de la API).

## Requisitos funcionales
- RF-01 Con `VITE_USE_REAL_API=ON`, `AnalyticsPage` muestra KPIs, serie temporal y desglose por canal reales del tenant, para el rango elegido.
- RF-02 El selector de rango ofrece hoy/7d/30d + custom (Q4); al cambiarlo re-consulta el endpoint.
- RF-03 La página muestra estados carga/vacío/error accesibles (AAA).
- RF-04 Con `VITE_USE_REAL_API=OFF`, la maqueta de #1 (SPEC-008) queda intacta.

## Requisitos no funcionales
- RNF-07 Sin romper #1–#6; feature-flag reversible; contrato de tipos aditivo (`src/lib/types.ts`).
- RNF-47 La SPA solo muestra datos del tenant autenticado (hereda RLS de la API; sin cambio).
- A11y: estados y componentes cumplen el estándar de accesibilidad/contraste del Entregable #1 (SPEC-009, AAA).

## Criterios de aceptación (verificables)
- [ ] Con `VITE_USE_REAL_API=ON`, `AnalyticsPage` muestra KPIs (conversaciones, conversión, TPR, respuesta promedio), serie temporal y desglose por canal reales, coincidentes con la BD del tenant.
- [ ] El selector de rango ofrece hoy/7d/30d + custom (Q4) y re-consulta al cambiar rango/canal.
- [ ] Estados carga/vacío/error son accesibles (aria/contraste conforme SPEC-009); rango vacío muestra mensaje claro (no error).
- [ ] Con `VITE_USE_REAL_API=OFF`, la maqueta de #1 (SPEC-008) se ve idéntica (sin regresión visual/funcional).
- [ ] El contrato de tipos se extiende de forma aditiva sin romper `src/lib/types.ts`.
- [ ] Suites de #1–#6 verdes tras el cambio.

## Notas de seguridad (C2/C3)
- C2: la SPA solo muestra agregados del tenant (los soft-deleted ya se excluyen en backend).
- C3: sin secretos en el frontend; el endpoint es on-prem, autenticado por JWT.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): la SPA consume solo la API on-prem; no habla con terceros ni IA externa. Los datos mostrados son agregados sin PII individual.

## Riesgos
- R-74 (regresión de la maqueta #1): feature-flag reversible; OFF = mock intacto; suites verdes (SPEC-065).
- R-75 (PII en pantalla): la API devuelve solo agregados; la SPA no reconstruye PII.
- (A11y) estados vacío/error mal etiquetados: revisión DAREDEVIL + a11y (SPEC-065).

## Checkpoints aplicables
- C2 (borrado lógico respetado en backend). C3 (sin secretos en front). C4 (criterios verificables). C8 (origen PLAN-007 / `prompt-lab/prompts/PROMPT-007-CRM-ANALYTICS.md`).
