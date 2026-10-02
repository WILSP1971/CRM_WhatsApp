# SPEC-078 — Reglas de alerta-as-code + configuración de Alertmanager (sin receiver externo, Q1-sub): target down, tasa de error HTTP 5xx > umbral, `/readyz`/salud caída; umbrales candidatos de THOR referenciando RNF-04/RNF-42; alertas visibles SOLO en Grafana/Alertmanager; al menos una alerta que dispara en prueba controlada (HAWKEYE) 🔴 SENSIBLE

- Estado: APROBADA (bloque SPEC-077..079, 2026-10-02) · Responsable: CAPTAIN AMERICA · Colaboran/revisan: BLACK PANTHER / THOR (reglas + umbrales), HAWKEYE (prueba de disparo), QUICKSILVER (Alertmanager en `docker-compose`), BLACK WIDOW · Prioridad: ALTA · Tipo: OBSERVABILIDAD/ALERTAS-AS-CODE · Fase: F1
- Deriva de: PLAN-010 (F1, §2.IN.4, §3.1, §3.4, §4, §6, §7, §9, §10 · R-99 (top) · CE-97) · Clasificación: SENSIBLE (`.no-externo`) · Depende de SPEC-077 · Consume healthchecks de `docker-compose.yml`, `backend/app/core/metrics.py` (SPEC-022), `/healthz`/`/readyz` · Prerequisito de SPEC-079

## Objetivo

Sobre el stack ya levantado por SPEC-077, definir **reglas de alerta-as-code** (versionadas en el repo) sobre las **métricas y healthchecks que YA existen** — al menos **target down**, **tasa de error HTTP 5xx > umbral** y **`/readyz`/salud caída** — enrutarlas a **Alertmanager** mediante una configuración de Alertmanager **sin ningún receiver de notificación externa** (decisión vinculante Q1-sub de PLAN-010), de modo que las alertas sean **visibles únicamente en Grafana/Alertmanager**, y demostrar que **al menos una regla dispara en una prueba controlada** (bajar el target / inyectar 5xx) y queda *firing* y visible. Los umbrales son **candidatos aportados por THOR** referenciando **RNF-04** (p95 RAG) y **RNF-42** (RTF STT) más umbrales de disponibilidad (target down, 5xx), con valores **configurables** y revisables por el Lead en la aprobación.

## Contexto

Verificado en PLAN-010 y en el repo:
- **Base aprovechable:** healthchecks existentes (`db` `pg_isready`, `redis` `redis-cli ping`, `ia`/`ollama` `/api/tags`, `api` `/healthz`), `/healthz` y `/readyz` del backend, y las series de `/metrics` (`http_requests_total{method,path,status_code}` para 5xx, el `up` del scrape para target down). Esta SPEC **observa** lo que ya se emite; **no instrumenta métricas nuevas**.
- **Decisión vinculante Q1-sub (PLAN-010 §1):** alertas **solo visibles en Grafana/Alertmanager**, **sin notificación push externa**. El "bridge de Telegram" de la memoria del orquestador **no** se reutiliza (es un mecanismo de sesión, no un canal operativo del repo). Consecuencia dura: **cero receiver externo en Alertmanager** → cero egress por alertas, cero credenciales de terceros. El criterio "la alerta dispara" se verifica en el **estado del Alertmanager/Grafana** (*firing*), no en un push recibido.
- **Riesgo top de la fase F1 (R-99):** reglas mal definidas o Alertmanager mal enrutado → "alertas" que nunca se activan = falsa sensación de cobertura. La contramedida es una **prueba controlada de disparo** (HAWKEYE), que es el núcleo de CE-97.
- **Invariante de aislamiento (§3.3):** las reglas/recording rules **no** pueden introducir `tenant_id` ni PII como label (R-98). Esta SPEC respeta la invariante; su auditoría formal se consolida en SPEC-079 junto con scrape/dashboards.

## Alcance

### IN
- **Reglas de alerta-as-code** (p. ej. `observability/prometheus/rules/*.yml` o ruta equivalente, versionadas en el repo y cargadas por Prometheus) que cubran al menos:
  - **Target down** (el target `api`/scrape `up==0` durante X tiempo).
  - **Tasa de error HTTP 5xx > umbral** (sobre `http_requests_total{status_code=~"5.."}`).
  - **`/readyz` / salud caída** (readiness del backend o healthcheck degradado).
  - Umbrales **candidatos de THOR** referenciando RNF-04 (p95 RAG, `ai_request_duration_seconds`) y RNF-42 (RTF STT, `stt_rtf`) donde aplique como alerta de rendimiento; valores **configurables/revisables**.
- **Configuración de Alertmanager as-code** (p. ej. `observability/alertmanager/alertmanager.yml`): enrutado de las reglas a Alertmanager **sin ningún receiver de notificación externa** (Q1-sub). Un receiver "nulo"/interno o la ausencia deliberada de integración externa; cero webhooks/SMTP/Slack/Telegram/PagerDuty/email salientes.
- **Visibilidad de las alertas** en el UI de Alertmanager y/o en Grafana (panel de alertas / estado de reglas), sin push externo.
- **Prueba controlada de disparo** (coordinada con HAWKEYE, verificación formal en SPEC-079): al menos una regla pasa a estado *firing* al provocar la condición (bajar el target / inyectar 5xx) y es **visible** en Alertmanager/Grafana; **ningún receiver externo** configurado.
- **Reglas revisables y versionadas** (as-code), con umbrales documentados como candidatos de THOR.

### OUT
- **Levantar los servicios Prometheus/Grafana/Alertmanager, scrape config y dashboards** → SPEC-077 (F0); esta SPEC asume el stack ya levantado.
- **Prueba formal de disparo + auditoría de aislamiento + no-regresión + docs de operación** → SPEC-079 (F2) consolida la verificación y la documentación; esta SPEC define las reglas y su enrutado.
- **Cualquier receiver de notificación externa** (Telegram/Slack/email/PagerDuty/webhook) → PROHIBIDO por Q1-sub; cero egress por alertas.
- **Agregación de logs (Loki/promtail)**, **métricas de negocio nuevas**, **instrumentar métricas nuevas en el backend** → OUT del plan.
- **Añadir `tenant_id`/PII como label en reglas o recording rules** → PROHIBIDO por diseño (`metrics.py`, §3.3).
- **Backups automatizados** → fuera de alcance de PLAN-010 (DIFERIDO, ver PLAN-010 §13); esta SPEC no los menciona ni los insinúa.

## Dependencias
- **Depende de SPEC-077** (necesita Prometheus evaluando reglas, Alertmanager levantado y Grafana para visualizar). Consume los healthchecks de `docker-compose.yml`, `/healthz`/`/readyz` y las series de `metrics.py` (SPEC-022) sin rediseñarlos. Consume RNF-04/RNF-42 como referencia de umbral. **Prerequisito de SPEC-079** (que verifica formalmente el disparo, audita aislamiento y documenta la operación). Ruta crítica: F0 (SPEC-077) → **F1 (SPEC-078)** → F2 (SPEC-079).

## Requisitos funcionales
- RF-01 Existen reglas de alerta-as-code versionadas en el repo, cargadas por Prometheus, que cubren al menos **target down**, **5xx > umbral** y **`/readyz`/salud caída**.
- RF-02 Los umbrales son **candidatos de THOR** (referenciando RNF-04 p95 RAG y RNF-42 RTF donde aplique) y son **configurables/revisables**; se documentan en la propia config as-code.
- RF-03 La configuración de Alertmanager enruta las reglas **sin ningún receiver de notificación externa** (Q1-sub): cero webhooks/SMTP/Slack/Telegram/PagerDuty/email salientes.
- RF-04 Las alertas son **visibles en Grafana/Alertmanager** (UI de Alertmanager y/o panel/estado de reglas en Grafana), sin push externo.
- RF-05 Al menos **una regla dispara en una prueba controlada** (bajar el target / inyectar 5xx), pasa a estado *firing* y es **visible** en Alertmanager/Grafana; ningún receiver externo configurado (CE-97; prueba formal verificada en SPEC-079).
- RF-06 Las reglas/recording rules **no** introducen `tenant_id` ni PII como label (se respeta la invariante §3.3; auditoría consolidada en SPEC-079).

## Requisitos no funcionales
- RNF-SIN-PUSH-EXTERNO (Q1-sub) Cero receiver de notificación externa en Alertmanager; las alertas se consultan en el estado del Alertmanager/Grafana, no en un push recibido.
- RNF-NO-EGRESS (R-101) Las reglas y el enrutado no introducen egress; Alertmanager sin receivers externos; stack en `ia_internal`; `check-externos-backend.sh` verde sin relajar allowlist (verificación formal en SPEC-079).
- RNF-AISLAMIENTO-METRICAS (R-98, §3.3) Ninguna regla/recording-rule lleva `tenant_id` ni PII como label.
- RNF-VERIFICABLE (R-99) La cobertura de alertas es **real, no aparente**: se demuestra con al menos una alerta que dispara en prueba controlada; reglas as-code revisables (no "alertas" que nunca se activan).
- RNF-ADITIVO (R-102) Define reglas/config de Alertmanager; no re-instrumenta `/metrics` ni toca `structlog`/healthchecks; sin modificar asserts de suites #1–#8.

## Criterios de aceptación (verificables)
- [ ] Existen reglas-as-code versionadas (target down, 5xx > umbral, `/readyz`/salud caída) cargadas por Prometheus, con umbrales configurables (candidatos de THOR, RNF-04/RNF-42 referenciados).
- [ ] La configuración de Alertmanager enruta las alertas **sin ningún receiver externo** (Q1-sub): inspección confirma cero webhooks/SMTP/Slack/Telegram/PagerDuty/email salientes.
- [ ] Al menos una regla pasa a estado *firing* en una **prueba controlada** (bajar el target / inyectar 5xx) y es **visible en Grafana/Alertmanager**, sin notificación externa (CE-97; prueba formal en SPEC-079).
- [ ] Ninguna regla/recording-rule expone `tenant_id` ni PII (§3.3; auditoría en SPEC-079).
- [ ] Las alertas son visibles en Grafana/Alertmanager; no existe ningún canal de push externo.

## Notas de seguridad (C2/C3)
- C2: no aplica (sin datos de negocio ni retención en esta SPEC; solo reglas sobre series de métricas sin PII).
- C3: la config de Alertmanager/reglas **no contiene secretos** (no hay receivers externos que requieran tokens/credenciales); cualquier credencial del stack (Grafana admin) se gestiona en SPEC-077 por env, nunca en reglas/config de alerta ni en logs.

## Restricción SENSIBLE / egress
- 🔴 SENSIBLE (sin egress nuevo): el núcleo de la restricción es **cero receiver externo en Alertmanager** (Q1-sub) → cero egress por alertas, cero credenciales de terceros. El stack sigue en `ia_internal`; `graph.facebook.com` (ADR-006) no se toca; ningún dominio/IP nuevo; `check-externos-backend.sh` verde sin relajar allowlist (verificación formal en SPEC-079). **Sin ADR nuevo** (PLAN-010 §11): no hay egress nuevo ni decisión arquitectónica estructural que fijar.

## Riesgos
- R-99 (**la alerta no dispara / no es verificable**): reglas mal definidas o Alertmanager mal enrutado → "alertas" que nunca se activan = falsa sensación de cobertura. Mitigación: al menos **una regla que dispara en prueba controlada** y es **visible en Alertmanager/Grafana** (CE-97, HAWKEYE); reglas as-code revisables. **Top de F1.**
- R-101 (**egress nuevo accidental por receiver externo**): un receiver de Alertmanager externo rompería el aislamiento. Mitigación: cero receivers externos (Q1-sub); `check-externos-backend.sh` verde (verificación en SPEC-079).
- R-98 (**`tenant_id`/PII en reglas/recording rules**): mitigación: invariante dura (§3.3); ninguna regla añade `tenant_id`/PII (auditoría en SPEC-079).
- R-102 (**regresión al añadir reglas/config**): todo aditivo; `/metrics`/logging/healthchecks intactos; suites #1–#8 sin cambios de asserts (verificación en SPEC-079).

## Checkpoints aplicables
- C3 (la config de alerta sin secretos; cero credenciales de terceros al no haber receiver externo). C4 (criterios verificables — la alerta que dispara es el criterio central). C6 (operar el stack en producción on-prem = cambio sensible → aprobación del Lead + notificación antes de desplegar). C8 (origen `prompt-lab/prompts/PROMPT-010-OBSERVABILIDAD-BACKUPS.md`).
