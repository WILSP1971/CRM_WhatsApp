# SPEC-079 — Pruebas + seguridad + no-regresión + docs del stack de observabilidad (cierre de PLAN-010, DoD): verificación de la alerta que dispara (HAWKEYE), auditoría de que NINGUNA serie/label/recording-rule/dashboard expone `tenant_id`/PII (CE-98, criterio de seguridad top del plan), `check-externos-backend.sh` verde sin relajar allowlist (BLACK WIDOW/WOLVERINE), cero secretos hardcodeados (admin Grafana por env, C3), cero regresión de `/metrics`/logging/healthchecks/#1–#8, y `RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md` con la operación del stack 🔴 SENSIBLE

- Estado: CERRADA — CIERRA PLAN-010 completo. HAWKEYE auditó aislamiento (CE-98, el criterio de seguridad más importante del plan: leyó `metrics.py` y los 6 archivos de `observability/` uno por uno, cero `tenant_id`/PII en ningún label/regla/dashboard), egress (CE-102: `check-externos-backend.sh` APROBADO, los 3 servicios solo en `ia_internal`, sin `ports:`, Alertmanager sin `*_configs` externos), secretos (CE-101: `GF_SECURITY_ADMIN_PASSWORD` sin default débil, consistente con la convención del proyecto) y UIs protegidos (CE-100). Añadió la sección "Observabilidad (PLAN-010)" a `RUNBOOK.md` y un bloque a `DEPLOYMENT_CHECKLIST.md`, con nota explícita de que los backups del stack quedan DIFERIDOS (PLAN-010 §13). Suite completa re-verificada por el orquestador contra Postgres real (HAWKEYE no tenía acceso en su sandbox): 778 passed, 11 failed (únicamente los dos casos ya documentados y aceptados: el caveat de `test_rag_tts_api.py` y el flake de `test_privacy_api.py`), cero regresión nueva — confirma que ningún archivo de `backend/app/` fue tocado por SPEC-077/078 (solo `docker-compose.yml`/`.env.example`/`observability/`). Las 3 pruebas de `test_check_externos_pbx_allowlist_guardrail.py` (aislamiento del guardarraíl de egress) verificadas aparte en ejecución directa: las 3 pasan (2 parametrizadas en 12.6s + la de árbol real en 96s, APROBADO) — el "colgado" reportado al correrlas dentro de la suite larga es un artefacto conocido del harness con subprocesos anidados, no una regresión de código (mismo patrón ya documentado en SPEC-075/076). CE-97 (alerta dispara) ya había sido confirmado en vivo por el orquestador durante el cierre de SPEC-078. · Responsable: HAWKEYE · Colaboran/revisan: BLACK WIDOW (aislamiento/egress/secretos), WOLVERINE (no-regresión/calidad), QUICKSILVER (docs operativos/`docker-compose`), BLACK PANTHER, THOR · Prioridad: ALTA · Tipo: PRUEBAS/SEGURIDAD/DOCS/NO-REGRESIÓN · Fase: F2
- Deriva de: PLAN-010 (F2, §2.IN.5/6, §3.1–§3.5, §4, §5, §9, §10 · R-98/R-99/R-100/R-101/R-102 · CE-97/CE-98/CE-100/CE-101/CE-102/CE-103) · Clasificación: SENSIBLE (`.no-externo`) · Depende de SPEC-077 y SPEC-078 · Consume `backend/app/core/metrics.py` (SPEC-022), `backend/check-externos-backend.sh`, `RUNBOOK.md`, `DEPLOYMENT_CHECKLIST.md`, ADR-005/ADR-006/ADR-009/ADR-010 · **Cierra el slice** (DoD PLAN-010 §10)

## Objetivo

Verificar y **cerrar** el slice de observabilidad de PLAN-010 con una tanda de **pruebas + seguridad + no-regresión** y la **documentación operativa**. Debe demostrar, de forma objetiva y auditable: (1) que **al menos una alerta dispara** en una prueba controlada y es visible en Grafana/Alertmanager **sin push externo** (HAWKEYE, CE-97); (2) **auditoría de aislamiento** — que **NINGUNA serie/label/recording-rule/dashboard expone `tenant_id` ni PII** (invariante intocable de `metrics.py`, CE-98 — **el criterio de seguridad MÁS importante de todo PLAN-010**); (3) que **`check-externos-backend.sh` sigue verde sin relajar su allowlist** (stack en `ia_internal`, Alertmanager sin receivers externos — BLACK WIDOW/WOLVERINE, CE-102); (4) **cero secretos hardcodeados** (admin de Grafana por env, cero en el repo, cero en logs — C3, CE-101); (5) **cero regresión** de `/metrics`, logging `structlog`, healthchecks y suites #1–#8 (CE-103); y (6) actualización de **`RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md`** documentando cómo operar el stack de observabilidad (CE-103).

## Contexto

Verificado en PLAN-010 y en el repo:
- **Patrón de auditoría de aislamiento:** la invariante "cero `tenant_id`/PII en el plano de métricas" está fijada en `backend/app/core/metrics.py` (SPEC-022, líneas 7/45/50/177/189). La auditoría de esta SPEC debe cubrir **toda la config as-code de SPEC-077/078**: scrape config, relabeling, recording rules, reglas de alerta y dashboards JSON — más la inspección de los **labels de todas las series expuestas** por `/metrics` tal como las ve Prometheus. Ninguna puede llevar `tenant_id` ni PII. Es el criterio de seguridad top del plan (R-98/CE-98).
- **Patrón de egress CI:** `backend/check-externos-backend.sh` es la auditoría de egress del proyecto; debe seguir **verde sin relajar la allowlist** (el stack vive en `ia_internal` `internal: true`; Alertmanager sin receivers externos; `graph.facebook.com`/ADR-006 intacto). Es la evidencia de R-101/CE-102.
- **Cero regresión (#1–#8):** las suites existentes de las fases #1–#8 deben pasar **sin modificar asserts**; `/metrics`, `structlog` JSON y los healthchecks (`db`/`redis`/`ia`/`api`, `/healthz`/`/readyz`) quedan **intactos** (esta fase no re-instrumenta nada). Es la evidencia de R-102/CE-103.
- **Secretos (C3):** admin de Grafana y cualquier credencial del stack van por **env** (gestionado en SPEC-077); esta SPEC verifica por grep/inspección que no hay secretos literales en config/compose ni en logs (R-100/CE-101).
- **Docs:** el runbook sigue el patrón de SPEC-061/072/076 (flujo + operación + troubleshooting). **La parte de backups del RUNBOOK/CHECKLIST NO se toca en esta fase** (se abordará al retomar backups, PLAN-010 §13). El hallazgo de que `backup-crm.sh` no existe como archivo real sigue siendo un hueco operativo real, pero **está fuera de alcance de PLAN-010** y de esta SPEC.

## Alcance

### IN
- **Verificación de la alerta que dispara** (HAWKEYE, CE-97/R-99): prueba controlada (bajar el target / inyectar 5xx) que lleva al menos una regla a estado *firing*, visible en Alertmanager/Grafana, con **ningún receiver externo** configurado; reproducible/documentada.
- **Auditoría de aislamiento (CE-98/R-98 — criterio de seguridad top del plan):** verificación de que **NINGUNA** serie/label/recording-rule/dashboard (scrape config, relabeling, reglas de SPEC-078, dashboards JSON de SPEC-077, y labels de todas las series expuestas por `/metrics`) contiene `tenant_id` ni PII; la invariante de `metrics.py` **no se relaja**; la desagregación por tenant sigue siendo de logs, no de Prometheus.
- **Auditoría de egress (CE-102/R-101):** `check-externos-backend.sh` **verde sin relajar la allowlist**; inspección de las redes del compose (observabilidad en `ia_internal` `internal: true`, nada en `app`); Alertmanager sin receivers externos; ningún dominio/IP nuevo.
- **Auditoría de secretos (CE-101/R-100, C3):** inspección (grep) de que config/compose **no** contienen secretos literales (admin de Grafana por env); grep de logs sin secretos; el agente no generó ni fijó credenciales.
- **No-regresión (CE-103/R-102):** suites #1–#8 verdes **sin modificar asserts**; `/metrics`, `structlog` y healthchecks intactos; verificación de que no se instrumentaron métricas nuevas ni se tocó el logging.
- **UIs protegidos (CE-100):** verificación de que Grafana exige auth (admin por env) y Prometheus/Alertmanager no están expuestos sin protección al exterior.
- **Docs de operación** (`RUNBOOK.md` + `DEPLOYMENT_CHECKLIST.md`, parte de observabilidad): cómo levantar/operar el stack, cómo acceder a dashboards/alertas, cómo verificar que el target está UP y que la alerta dispara, retención de la TSDB por env, y nota de que la parte de backups del runbook/checklist **no se toca en esta fase** (DIFERIDA, PLAN-010 §13).

### OUT
- **Levantar el stack / scrape / dashboards** → SPEC-077 (F0); **reglas de alerta / Alertmanager** → SPEC-078 (F1). Aquí se **prueban/auditan/documentan**, no se implementan.
- **Agregación de logs (Loki/promtail)**, **métricas de negocio nuevas**, **instrumentar métricas nuevas en el backend**, **CD/staging/producción dedicada** → OUT del plan.
- **Receiver de notificación externa** → PROHIBIDO por Q1-sub (se verifica su ausencia, no se añade).
- **Rediseño de RLS, de `metrics.py`, del login o de HABEAS DATA** → se consumen intactos; la invariante cero `tenant_id` no se relaja.
- **Backups automatizados y su documentación** → fuera de alcance de PLAN-010 (DIFERIDO, PLAN-010 §13); esta SPEC **no toca** la parte de backups del RUNBOOK/CHECKLIST ni la genera.

## Dependencias
- **Depende de SPEC-077 y SPEC-078** (prueba, audita y documenta el conjunto completo). Reutiliza `backend/check-externos-backend.sh` (egress), el registro/labels de `metrics.py` (auditoría de aislamiento), los patrones de runbook de SPEC-061/072/076. Consume ADR-005/ADR-006/ADR-009/ADR-010 sin rediseño. **Cierra el slice** (DoD PLAN-010 §10). Ruta crítica: F0 (SPEC-077) → F1 (SPEC-078) → **F2 (SPEC-079)**.

## Requisitos funcionales
- RF-01 Verificación de que al menos una alerta dispara en prueba controlada, visible en Grafana/Alertmanager, con cero receiver externo (CE-97).
- RF-02 Auditoría de aislamiento: **ninguna** serie/label/recording-rule/dashboard (scrape, relabeling, reglas, dashboards JSON, labels de `/metrics`) expone `tenant_id` ni PII; la invariante de `metrics.py` no se relaja (CE-98).
- RF-03 Auditoría de egress: `check-externos-backend.sh` **verde sin relajar allowlist**; observabilidad en `ia_internal` (`internal: true`), nada en `app`; Alertmanager sin receivers externos; ningún dominio/IP nuevo (CE-102).
- RF-04 Auditoría de secretos: config/compose sin secretos literales (admin de Grafana por env); logs sin secretos; el agente no generó credenciales (CE-101, C3).
- RF-05 No-regresión: suites #1–#8 verdes sin modificar asserts; `/metrics`/`structlog`/healthchecks intactos; sin métricas nuevas instrumentadas (CE-103).
- RF-06 UIs protegidos: Grafana con auth (admin por env); Prometheus/Alertmanager no expuestos sin protección (CE-100).
- RF-07 `RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md` documentan la operación del stack de observabilidad (levantar/operar, acceder a dashboards/alertas, target UP, alerta que dispara, retención TSDB); la parte de backups **no se toca** (DIFERIDA, PLAN-010 §13) (CE-103).

## Requisitos no funcionales
- RNF-AISLAMIENTO-METRICAS (R-98 — top) La auditoría cubre toda la config as-code y los labels de las series; cero `tenant_id`/PII; la invariante de `metrics.py` no se relaja en ningún punto.
- RNF-NO-EGRESS (R-101) `check-externos-backend.sh` verde sin relajar allowlist; stack en `ia_internal`; Alertmanager sin receivers externos; `graph.facebook.com` (ADR-006) intacto.
- RNF-C3 (R-100) Ningún secreto en config/compose/logs; admin de Grafana por env; ningún test/fixture/runbook contiene secretos ni PII real; credenciales de prueba ficticias.
- RNF-ADITIVO (R-102) Cero regresión: `/metrics`, `structlog` y healthchecks intactos; suites #1–#8 sin modificar asserts.
- RNF-REPRO La prueba de disparo de la alerta y las auditorías son reproducibles y documentadas (evidencia auditable).

## Criterios de aceptación (verificables)
- [ ] Al menos una alerta pasa a *firing* en prueba controlada, visible en Grafana/Alertmanager, con cero receiver externo (CE-97).
- [ ] Auditoría: ninguna serie/label/recording-rule/dashboard expone `tenant_id` ni PII; invariante de `metrics.py` intacta (CE-98 — criterio de seguridad top del plan).
- [ ] `check-externos-backend.sh` verde **sin relajar allowlist**; observabilidad en `ia_internal` (`internal: true`), nada en `app`; Alertmanager sin receivers externos (CE-102).
- [ ] Config/compose sin secretos literales; admin de Grafana por env; grep de logs sin secretos; el agente no generó credenciales (CE-101).
- [ ] Suites #1–#8 verdes **sin modificar asserts**; `/metrics`/`structlog`/healthchecks intactos; sin métricas nuevas (CE-103).
- [ ] Grafana exige auth (admin por env); Prometheus/Alertmanager no expuestos sin protección (CE-100).
- [ ] `RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md` con sección de operación del stack de observabilidad; la parte de backups NO se toca (DIFERIDA, PLAN-010 §13) (CE-103).

## Notas de seguridad (C2/C3)
- C2: no aplica retención de datos de negocio; la TSDB guarda series de métricas sin PII. (La tensión backup↔HABEAS DATA pertenece a la fase de backups, DIFERIDA, PLAN-010 §13 — fuera de alcance.)
- C3: ningún secreto/PII real en tests/fixtures/runbook; admin de Grafana por env verificado por grep; logs sin secretos; credenciales de prueba ficticias.

## Restricción SENSIBLE / egress
- 🔴 SENSIBLE (sin egress nuevo): esta SPEC es la **puerta de evidencia** de todo PLAN-010. La auditoría de aislamiento (cero `tenant_id`/PII en métricas, CE-98) es el criterio de seguridad más importante del plan: un exporter/label/recording-rule/dashboard con `tenant_id` sería una **regresión de aislamiento/confidencialidad** (PHI potencial, ADR-009, bajo RLS multi-tenant). `check-externos-backend.sh` verde sin relajar allowlist; stack en `ia_internal`; Alertmanager sin receivers externos; `graph.facebook.com` (ADR-006) no se toca; ningún dominio/IP nuevo. **Sin ADR nuevo** (PLAN-010 §11).

## Riesgos
- R-98 (**regresión de aislamiento en el plano de métricas / `tenant_id` como label**): mitigación: **auditoría obligatoria** de scrape/reglas/dashboards + labels de todas las series; cero `tenant_id`/PII; invariante de `metrics.py` no relajada (CE-98). **Top — criterio de seguridad más importante del plan.**
- R-99 (**la alerta no dispara / no es verificable**): mitigación: prueba controlada que lleva al menos una regla a *firing*, visible en Alertmanager/Grafana (CE-97, HAWKEYE). **Top.**
- R-100 (**secretos de observabilidad, C3**): mitigación: auditoría de ausencia de secretos en config/compose/logs; admin de Grafana por env (CE-101). **Top.**
- R-101 (**egress nuevo accidental**): mitigación: `check-externos-backend.sh` verde sin relajar allowlist; stack en `ia_internal`; Alertmanager sin receivers externos (CE-102).
- R-102 (**regresión de `/metrics`/logging/healthchecks/#1–#8**): mitigación: suites #1–#8 verdes sin modificar asserts; `/metrics`/`structlog`/healthchecks intactos (CE-103).

## Checkpoints aplicables
- C3 (secretos: admin de Grafana por env verificado; cero en repo/logs — crítico). C4 (criterios verificables — alerta que dispara + auditorías). C6 (operar/levantar el stack en producción on-prem = cambio sensible → aprobación del Lead + notificación antes de desplegar; esta SPEC cierra el DoD). C8 (origen `prompt-lab/prompts/PROMPT-010-OBSERVABILIDAD-BACKUPS.md`).
