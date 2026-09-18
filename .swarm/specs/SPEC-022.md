# SPEC-022 — Pruebas (unit/integración/e2e) + carga (THOR) + observabilidad

- Estado: PROPUESTA · Responsable: HAWKEYE · Colaboran: THOR, BLACK PANTHER, BLACK WIDOW, WOLVERINE · Prioridad: ALTA · Tipo: QA/PERFORMANCE/OBSERVABILIDAD · Fase: F8
- Deriva de: PLAN-002 (F8) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Probar el slice completo con tests **unit/integración/e2e** (auth/RLS/RAG/WebChat), incluir **prueba de carga/latencia** (THOR) y **observabilidad**, con dos verificaciones críticas: un **test cross-tenant que DEBE fallar por RLS** y la **verificación auditable de cero inferencia externa**.

## Contexto

Fase F8: depende de que F2–F6 estén completas; prueba el slice de extremo a extremo. Consolida CE-22 (aislamiento multi-tenant probado), CE-23 (p95 RAG), CE-24 (WebChat persistido) y CE-27 (cobertura ≥ 80%). THOR mide latencias (RAG p95, API no-IA p95). La observabilidad usa logs estructurados (`tenant_id`/`trace_id`), `/healthz` y métricas Prometheus.

## Alcance

### IN
- Tests unitarios de dominio (auth, RLS, RAG, WebChat, sentimiento, borrador).
- Tests de integración (API↔BD↔IA local↔Redis) y e2e del slice (auth → WebChat → RAG → borrador).
- **Test cross-tenant automatizado que DEBE fallar por RLS** (acceso de A a datos de B rechazado).
- **Verificación de cero inferencia externa**: prueba de egress vacío + captura de red + `check-externos-backend.sh` en CI.
- Carga/latencia (THOR): p95 RAG (GPU/CPU) y p95 API no-IA; degradación documentada.
- Observabilidad: logs estructurados (`tenant_id`/`trace_id`), `/healthz`, métricas Prometheus (latencia RAG/IA).
- Reporte de cobertura backend ≥ 80%.

### OUT
- Implementación de features (SPEC-011..021).
- Deploy on-prem/runbook (SPEC-023).

## Dependencias
- Depende de SPEC-013 (auth/RLS), SPEC-015 (WebChat), SPEC-016/017 (IA/RAG), SPEC-018 (sentimiento), SPEC-019 (borrador) y SPEC-021 (seguridad). Prerequisito de cierre (SPEC-023).

## Requisitos funcionales
- RF Un test cross-tenant intenta leer datos de otro tenant y **falla** por RLS.
- RF La verificación de egress confirma cero conexiones salientes de inferencia del contenedor IA.
- RF La suite e2e cubre auth → WebChat → RAG → borrador human-in-the-loop.

## Requisitos no funcionales
- RNF-04 p95 RAG ≤ 6 s (GPU) / degradación CPU documentada; p95 API no-IA ≤ 200 ms.
- RNF-03 Cobertura de tests backend ≥ 80%.
- RNF-06 Observabilidad: logs estructurados, `/healthz`, métricas Prometheus.

## Criterios de aceptación (verificables)
- [ ] **Test cross-tenant** presente y **falla** (acceso de A a datos de B rechazado por RLS) — CE-22.
- [ ] Prueba de egress vacío: `curl` del contenedor IA a dominios externos **falla**; captura de red sin IPs públicas — CE-21.
- [ ] `check-externos-backend.sh` corre en CI y falla ante cualquier URL/SDK/endpoint externo de inferencia.
- [ ] e2e WebChat: mensaje del visitante persiste y aparece en la Bandeja; respuesta llega — CE-24.
- [ ] e2e RAG: borrador con ≥3 citas trazables; **p95 ≤ 6 s** (GPU) o degradación CPU documentada — CE-23.
- [ ] Reporte de cobertura backend **≥ 80%** — CE-27.
- [ ] Métricas Prometheus + `/healthz` verdes; logs con `tenant_id`/`trace_id`.

## Notas de seguridad (C2/C3)
- C3: los tests no exponen secretos; usan env/fixtures.
- C2: los tests validan borrado lógico (registros inactivos excluidos).

## Restricción SENSIBLE aplicable
- La suite verifica de forma AUDITABLE la política SENSIBLE: cero inferencia externa (CE-21) y aislamiento multi-tenant (CE-22).

## Riesgos
- R-23 (RLS mal configurado): test cross-tenant obligatorio que debe fallar.
- R-22 (fuga de egress IA): prueba de egress vacío + captura de red.
- R-24 (latencia RAG): medición p95 THOR; degradación CPU documentada.

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-002).
