# SPEC-065 — Pruebas + seguridad + performance + no-regresión del dashboard de métricas de negocio (exactitud, RLS cross-tenant, latencia THOR, cero regresión #1–#6 y `/metrics`) 🔴 SENSIBLE

- Estado: CERRADA — CE-71/72/73/75/76/77 verificados por HAWKEYE (98% cobertura, 88 tests nuevos/reforzados, no-regresión #1–#6 y `/metrics` intactos); CE-74 medido por el orquestador contra Postgres real (p95=1025.7ms, objetivo ≤1500ms, sin disk spill) tras corregir el benchmark de THOR (bug `SET LOCAL`/sintaxis LATERAL) y aplicar el fix de N+1 hallado por THOR (`get_conversion_rate` ya no reconsulta `get_conversation_metrics`) · Responsable: HAWKEYE · Colaboran: THOR, BLACK PANTHER, BLACK WIDOW, WOLVERINE, DAREDEVIL, CAPTAIN AMERICA · Prioridad: ALTA · Tipo: QA/PRUEBAS · Fase: F3
- Deriva de: PLAN-007 (F3, CE-71..CE-77) · Clasificación: SENSIBLE (`.no-externo`) · ADR-004/ADR-008
- APROBADO SPEC-065 por el Lead (bloque PLAN-007) — 2026-09-28.

## Objetivo

Verificar el dashboard de métricas de negocio con pruebas objetivas: **exactitud** de cada métrica con **fixtures deterministas** (conversaciones, tiempos de respuesta incl. casos límite, conversión), **aislamiento cross-tenant que DEBE fallar por RLS** (rol app no-superusuario, ADR-008), **latencia p95** del endpoint (THOR) sobre volumen representativo, y **cero regresión** de los Entregables #1–#6 y de `/metrics` (Prometheus). Cobertura del código nuevo **≥80%**. Es la evidencia objetiva de CE-71..CE-77.

## Contexto

Cierra la validación técnica de PLAN-007 reutilizando la infra de pruebas de #2–#6 (pytest, fixtures de tenant/RLS `tests/test_rls_isolation.py`, Locust para carga, `check-externos-backend.sh`). Las métricas se verifican contra datos **sembrados de forma determinista** (fixtures) para poder afirmar que las cifras coinciden con la BD. El criterio más crítico es **R-71 (fuga cross-tenant)**: el test cross-tenant debe demostrar que una sesión de tenant A, con el rol app no-superusuario, **no** agrega filas de tenant B (falla por RLS = aislamiento cumplido). El segundo, **R-72**: los tiempos de respuesta en casos límite.

## Alcance

### IN
- **Exactitud (CE-71):** fixtures deterministas por tenant; los agregados del servicio/endpoint (conversaciones total/canal/estado/serie, TPR, respuesta promedio, conversión) **igualan** el conteo esperado calculado a mano sobre el fixture.
- **Tiempos de respuesta / casos límite (CE-73):** fixtures por caso: conversación sin respuesta (excluida del promedio, no cuenta como 0), respuesta de IA vs agente (ambas salientes), múltiples entrantes seguidos (primer entrante del bloque), conversación con solo salientes (excluida), múltiples idas y vueltas (promedio correcto).
- **Conversión (CE-76):** test de la fórmula `cerradas/totales`; caso `totales=0` → sin división por cero (0/`null` documentado).
- **Cross-tenant RLS (CE-72):** una sesión de tenant A no agrega datos de tenant B → **falla por RLS** con el rol app no-superusuario (ADR-008); se verifica que el servicio/endpoint **no** usa rol owner ni sesión sin tenant. Test análogo a `test_session_without_tenant_sees_zero_rows`.
- **Latencia p95 (CE-74):** medición del endpoint sobre un **volumen representativo** de conversaciones/mensajes; se fija y verifica el objetivo p95 acordado con THOR.
- **PII / privacidad (R-75):** verificación de que la respuesta contiene **solo agregados** (sin PII individual) y que soft-deleted/`anonymized_at` se excluyen de los conteos.
- **No-regresión (CE-77):** `/metrics` (Prometheus) intacto; suites de #1–#6 verdes; la maqueta de `AnalyticsPage` con flag OFF idéntica (test/visual).
- **Cobertura** del código nuevo (servicio + endpoint) **≥80%**.

### OUT
- Implementación de servicio/endpoint/SPA (SPEC-062/063/064); docs/deploy (SPEC-066).

## Dependencias
- Depende de SPEC-062 (servicio), SPEC-063 (endpoint) y SPEC-064 (SPA). Se ancla en ADR-004/ADR-008 (RLS efectiva). Reutiliza la infra de pruebas de #2–#6.

## Requisitos funcionales
- RF-01 Existe suite de tests del dashboard: exactitud, tiempos de respuesta (casos límite), conversión, cross-tenant RLS, latencia, PII, no-regresión.
- RF-02 Los tests de exactitud comparan los agregados contra valores esperados de fixtures deterministas.
- RF-03 El test cross-tenant demuestra el aislamiento por RLS (falla por RLS = verde).

## Requisitos no funcionales
- RNF-47 Evidencia dura de RLS efectiva: cross-tenant falla; sin rol owner/superusuario ni sesión sin tenant.
- RNF-73 Latencia p95 del endpoint dentro del objetivo THOR sobre volumen representativo.
- RNF-07 Cobertura del código nuevo ≥80%; suites #1–#6 verdes; `/metrics` intacto; `docker compose up` reproducible.

## Criterios de aceptación (verificables)
- [ ] Exactitud: los agregados (conversaciones total/canal/estado/serie, TPR, respuesta promedio, conversión) igualan los valores esperados de fixtures deterministas (CE-71).
- [ ] Tiempos de respuesta correctos en casos límite: sin respuesta (excluida), IA vs agente (salientes), múltiples entrantes seguidos, solo salientes (excluida), múltiples idas/vueltas (CE-73).
- [ ] Conversión = `cerradas/totales`; `totales=0` sin división por cero (CE-76).
- [ ] **Cross-tenant falla por RLS** con el rol app no-superusuario (ADR-008); servicio/endpoint sin rol owner ni sesión sin tenant (CE-72).
- [ ] Latencia p95 del endpoint dentro del objetivo THOR sobre volumen representativo (CE-74).
- [ ] La respuesta contiene solo agregados (sin PII); soft-deleted/`anonymized_at` excluidos de los conteos (R-75).
- [ ] **No-regresión:** `/metrics` (Prometheus) intacto; suites #1–#6 verdes; `AnalyticsPage` con flag OFF idéntica (CE-77).
- [ ] Cobertura del código nuevo ≥80%; `check-externos-backend.sh` en verde.

## Notas de seguridad (C2/C3)
- C2: tests verifican exclusión de inactivos y respeto de `anonymized_at` en los conteos.
- C3: tests no exponen secretos; usan fixtures/placeholders.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (verifica aislamiento): esta SPEC PRUEBA el invariante de RLS (ADR-004/008): ningún agregado cruza tenants; sin bypass; sin egress (solo SQL local + lectura de columnas persistidas). El test cross-tenant es evidencia obligatoria del DoD.

## Riesgos
- R-71/R-72/R-73/R-74/R-75/R-76/R-77: cada uno cubierto por su test (cross-tenant RLS, tiempos límite, latencia THOR, regresión maqueta con flag OFF, PII/soft-delete, `/metrics` intacto, rango vacío/división por cero).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-007 / `prompt-lab/prompts/PROMPT-007-CRM-ANALYTICS.md`).
