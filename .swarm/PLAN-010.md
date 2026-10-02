# PLAN-010 — Observabilidad real (operación on-prem): levantar un stack self-hosted Prometheus + Grafana + Alertmanager que efectivamente scrapee/visualice/alerte sobre el `/metrics` que el backend YA emite, dashboards y reglas as-code, alertas visibles sin push externo, invariante intocable de que NINGUNA métrica lleva `tenant_id` como label, sin egress nuevo y sin ADR de egress — con BACKUPS DIFERIDOS a fase posterior

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Fecha: 2026-10-02 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo`) — el stack toca datos operativos con PHI potencial (transcripciones médicas, ADR-009) bajo RLS multi-tenant; un exporter con labels de tenant sería una **regresión de aislamiento/confidencialidad**.
> Origen: `prompt-lab/prompts/PROMPT-010-OBSERVABILIDAD-BACKUPS.md` (🧠 XAVIER, C.R.A.F.T.) — decisiones del Lead a §7 ya **VINCULANTES** (§7.1, 2026-10-02). **NO se reabren** (ver §1 tabla).
> ⚠️ **CAMBIO DE ALCANCE (instrucción directa del Lead, 2026-10-02, posterior a §7.1):** *"Deja pendiente el backup automatizado."* → **PLAN-010 cubre AHORA solo el bloque A (Observabilidad).** El bloque B (Backups automatizados) queda **EXPLÍCITAMENTE DIFERIDO** a una fase posterior (p. ej. PLAN-011) — ver **§13**. Las 4 decisiones vinculantes del Lead que aplican a backups (Q2/Q3) ya están respondidas y quedan registradas en §13 para no reabrirlas cuando se retome.
> Posición en la secuencia ordenada por el Lead: **Fase B de 4** (1. Onboarding multi-tenant ✅ PLAN-009 · **2. Observabilidad real ← ESTA (backups diferidos)** · 3. Hardening de producción · 4. Instagram DM).
> Regla de oro: este PLAN **NO genera SPECs ni código**. Las SPEC se redactan como PROPUESTA y solo pasan a implementación tras aprobación explícita del Lead ("APROBADO PLAN-010" y luego "APROBADO SPEC-XXX"). **Dos puertas obligatorias:** primero PLAN, luego SPEC.
> Base que se CONSUME (no se rediseña): **`backend/app/core/metrics.py`** (SPEC-022, registro Prometheus dedicado, invariante "sin `tenant_id` como label" — verificada en el docstring del módulo); **`backend/app/main.py:265`** (`/metrics`), `:37` (`structlog` JSON); healthchecks de `docker-compose.yml` (`/healthz`, `/readyz`, `pg_isready`, `redis`, `ollama`); `backend/check-externos-backend.sh` (auditoría de egress CI); **ADR-005/006/009/010** (aislamiento IA, egress acotado, PHI/audio cifrado, PBX). El endpoint `/metrics` ya es rico y multi-vector (HTTP/IA/STT/WhatsApp). Esta fase **cierra el hueco operativo de observabilidad**, no instrumenta métricas nuevas ni rediseña retención de datos.
> Contadores vigentes (`.swarm/specs.json`, verificados 2026-10-02): `next_plan: 10` (este plan; al cerrarse PLAN-010 pasa a **11**), `next_spec: 77`, `next_adr: 16`. **`next_spec`/`next_adr` NO se reclaman aquí**: se consumen al crear las SPEC tras "APROBADO PLAN-010". **DECISIÓN de este plan: NO se requiere ADR nuevo** (ver §11) → `next_adr` permanece en **16**.

---

## 1. Objetivo y contexto

### Objetivo

Convertir la **observabilidad** de **"documentada pero inexistente en la práctica"** a **"real y operativa"**, sobre la infraestructura `docker-compose` actual del proyecto y sin introducir egress nuevo: levantar un stack self-hosted **Prometheus + Grafana + Alertmanager** (as-code, versionado en el repo, integrado en `docker-compose.yml` dentro de `ia_internal` sin egress) que efectivamente **scrapee** el `/metrics` que el backend YA expone, lo **visualice** en dashboards versionados y **alerte** sobre umbrales de salud/rendimiento — con las alertas **solo visibles en Grafana/Alertmanager** (sin notificación push externa, sin Loki/logs agregados en esta fase).

Es puramente **aditivo y operativo**: no rompe `/metrics`, ni el logging `structlog`, ni los healthchecks, ni el aislamiento IA/egress, ni las fases #1–#8. **No instrumenta métricas de negocio nuevas** (ya existe el dashboard de analítica, SPEC-062..066) ni **rediseña la retención de DATOS de negocio** (ciclo de vida del dato bajo HABEAS DATA, no observabilidad).

**Los BACKUPS automatizados quedan DIFERIDOS** por instrucción directa del Lead (§13): no entran en el alcance IN de PLAN-010 ni generan SPECs ahora. El hallazgo de XAVIER de que `backup-crm.sh` **no existe como archivo real** pese a estar en `RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md` **sigue siendo un hueco operativo real y prioritario** — solo se **aborda después**, como fase separada, con las decisiones del Lead ya tomadas (§13).

### Decisiones del Lead ya VINCULANTES que aplican a ESTA fase (prompt §7.1 — NO se reabren)

| # | Pregunta | Decisión vinculante | Consecuencia de alcance (observabilidad) |
|---|----------|---------------------|-------------------------------------------|
| **Q1 — Profundidad del stack** | **Opción A: Prometheus + Grafana + Alertmanager.** Sin Loki/promtail/logs agregados en esta fase. | Métricas + dashboards + alertas. Los `structlog` JSON se quedan como están (stdout/driver de logs de Docker). La agregación de logs por `tenant_id`/`trace_id` queda OUT (§2) — candidata a fase futura. |
| **Q1-sub — Canal de alertas** | **Alertas solo visibles en Grafana/Alertmanager.** Sin notificación push externa; el "bridge de Telegram" de la memoria del orquestador NO se reutiliza (es un mecanismo de sesión, no un canal operativo del repo). | **Cero integración de notificación externa** → cero egress por alertas, cero credenciales de terceros. El criterio "la alerta dispara" se verifica en el estado del Alertmanager/Grafana, no en un push recibido. |

> Las decisiones **Q2** (alcance del backup) y **Q3** (destino LAN/NAS) también están respondidas y vinculantes, pero aplican al **bloque B (backups), DIFERIDO** → se registran en **§13** para cuando se retome, no reabrirlas.

### Contexto verificado en código (fuente de verdad, no asunciones)

- **`/metrics` REAL y rico, pero nadie lo scrapea** (`backend/app/main.py:265` → `backend/app/core/metrics.py`, SPEC-022): formato Prometheus (`prometheus_client==0.19.0` ya en `requirements.txt`), `CollectorRegistry` dedicado. Series HOY: `http_requests_total{method,path,status_code}`, `http_request_duration_seconds{method,path}`; `ai_request_duration_seconds{operation,model}` (buckets hasta 60s, degradación CPU), `ai_request_errors_total{operation,error_type}`; `stt_rtf{model,device}`, `stt_queue_latency_seconds`, `stt_jobs_total{resultado}`; `whatsapp_media_downloads_total{resultado}`, `whatsapp_audio_discarded_by_duration_total`. **NO existe ningún Prometheus/Grafana/Alertmanager/Loki en el repo** (`find` sobre esos configs → vacío): el endpoint "cae en un bosque sin oídos".
- **INVARIANTE DE DISEÑO YA FIJADA (verificada en `metrics.py`, líneas 7/45/50/177/189):** **NINGUNA métrica lleva `tenant_id` como label** (cardinalidad no acotada + fuga cross-tenant en un backend de métricas compartido). La desagregación por tenant se obtiene de los **logs estructurados** (`structlog`, que SÍ llevan `tenant_id`), **no** de Prometheus. **Esta invariante es intocable: NINGUNA SPEC de esta fase puede relajarla** (ni añadir `tenant_id`/PII como label, ni crear recording rules/exporters/relabeling que lo reintroduzcan). Ver §3.3.
- **Logging `structlog` a JSON a stdout/stderr** (`main.py:37`, `JSONRenderer`, `TimeStamper` ISO; `audit_log` dedicado en `app/core/audit_log.py`, logger `audit.personal_data`): **sin agregación centralizada** (ni Loki/ELK ni rotación gestionada — depende del driver de logs del host). Por Q1-A **esto se queda como está** en esta fase.
- **Healthchecks SÍ existen** (`docker-compose.yml`): `db` (`pg_isready`), `redis` (`redis-cli ping`), `ia`/`ollama` (`/api/tags`), `api` (`/healthz`), Caddy. El backend expone `/healthz` y `/readyz`. **Base aprovechable** para reglas de alerta de disponibilidad (target down / `readyz` caído), NO el objetivo en sí.
- **Topología de redes/volúmenes (verificada en `docker-compose.yml:960–1026`):** red `app` (bridge, egress acotado a `graph.facebook.com`), red **`ia_internal` (bridge, `internal: true` — bloquea egress a internet)**; volúmenes `db_data`, `redis_data`, `ollama_models`, `audio_store` (cifrado), `whisper_models`, `caddy_data/config`, voces TTS. El `api` escucha en `ia_internal` (y en `app`): el scrape de `/metrics` se hace **contra `api` desde dentro de `ia_internal`**, sin salir a internet.
- **CI sin CD, un solo `docker-compose.yml`** (sin staging): lo que se entregue debe **operarse sobre el stack `docker-compose` actual**. Montar un entorno de producción dedicado es la **Fase C (Hardening)**, fuera de alcance (§2).
- **Hueco de backups (verificado por XAVIER, DIFERIDO — §13):** `RUNBOOK.md:168–256` documenta un `cat > backup-crm.sh` manual + restore + rsync, pero **ese script NO existe como archivo del repo** (`find . -name "backup*.sh"` → vacío) y `DEPLOYMENT_CHECKLIST.md:100–104` lo **asume** en cron + "test de restauración completado". Es un hueco operativo real; se **difiere**, no se ignora (§13).

---

## 2. Alcance IN / OUT

### IN — entra en el Entregable de observabilidad (bloque A)

1. **Servicios de observabilidad en `docker-compose.yml`:** Prometheus, Grafana y Alertmanager como servicios nuevos en la red **`ia_internal` (`internal: true`, sin egress nuevo)**, con healthchecks, `restart: unless-stopped` y **volúmenes de persistencia dedicados** (TSDB de Prometheus, estado de Grafana, estado de Alertmanager). Acceso a los UIs protegido/no expuesto sin auth al exterior (C3: credenciales de Grafana por env).
2. **Scrape config versionado** que apunta a `api:8000/metrics` (y a los healthchecks/targets aprovechables): el target debe aparecer **UP** y las series HTTP/IA/STT/WhatsApp consultables.
3. **Dashboards-as-code** (provisioning de Grafana versionado en el repo): al menos un dashboard que muestre **latencia/errores HTTP**, **latencia IA** (`ai_request_duration_seconds` p95 vs RNF-04) y **RTF STT** (`stt_rtf` vs RNF-42). Candidatos de umbral los aporta THOR (consumidor natural de esas series).
4. **Reglas de alerta-as-code** sobre las métricas/healthchecks YA existentes: al menos **target down**, **tasa de error HTTP 5xx > umbral** y **`readyz`/salud caída**; enrutadas a Alertmanager, **visibles en Grafana/Alertmanager sin push externo** (Q1-sub). Al menos **una regla dispara en una prueba controlada** (HAWKEYE).
5. **Pruebas + seguridad + no-regresión** (HAWKEYE/BLACK WIDOW/WOLVERINE): **alerta que dispara**; **CERO regresión de aislamiento** (ninguna serie/label/recording rule/dashboard expone `tenant_id` ni PII — auditoría de la config as-code); **`check-externos-backend.sh` verde** (sin egress nuevo; el stack vive en `ia_internal`; Alertmanager sin receivers externos); **cero secretos hardcodeados** (admin de Grafana por env, nunca en repo ni logs, C3); **cero regresión** de `/metrics`, logging, healthchecks y fases #1–#8.
6. **Actualización puntual de `RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md`** para la parte de observabilidad (cómo levantar/operar el stack, cómo acceder a dashboards/alertas). **La parte de backups del RUNBOOK/CHECKLIST NO se toca en esta fase** (se abordará al retomar backups, §13).

### OUT — NO entra en este slice (fase futura / decisión aparte)

- **Backups automatizados (bloque B completo):** servicio/script de backup, cifrado, retención, scheduling, rsync a LAN/NAS, prueba de restauración → **DIFERIDO por instrucción del Lead** (§13). No genera SPECs en PLAN-010.
- **Agregación de logs self-hosted (Loki/promtail/ELK)** y consulta de `structlog` por `tenant_id`/`trace_id`: descartado por Q1-A. Los logs se quedan en stdout/driver de Docker. Candidato a fase futura.
- **Notificación push externa de alertas** (Telegram/Slack/email/PagerDuty): descartado por Q1-sub (alertas solo visibles en Grafana/Alertmanager). Cero integración de notificación externa → cero egress nuevo.
- **Métricas/dashboards de NEGOCIO nuevos** (conversaciones, conversión, tiempos de respuesta): ya existen (SPEC-062..066, AnalyticsPage). No se duplican. Esta fase es observabilidad **técnica/operativa**.
- **Instrumentar métricas nuevas en el backend:** se consume `/metrics` tal cual; esta fase **observa** lo que ya se emite, no añade contadores/histogramas nuevos.
- **CD / pipeline de deploy / entorno de staging / servidor de producción dedicado:** es la **Fase C (Hardening)**, siguiente en la secuencia. Esta fase opera sobre el `docker-compose` actual.
- **Añadir `tenant_id` (o cualquier PII) como label de Prometheus / recording rule que lo reintroduzca:** PROHIBIDO por diseño ya fijado en `metrics.py` (§3.3). Invariante dura.
- **Exponer públicamente los UIs de Prometheus/Grafana/Alertmanager sin auth:** fuera de alcance; el acceso queda protegido/interno (C3).

---

## 3. Arquitectura de referencia

### 3.1 Topología del stack de observabilidad (sin egress nuevo)

```
                 red ia_internal (internal: true — SIN egress a internet)
   +---------------------------------------------------------------------+
   |  api:8000/metrics  <--- scrape --- prometheus (TSDB, vol dedicado)   |
   |  (series HTTP/IA/STT/WhatsApp,          |                            |
   |   SIN tenant_id como label)             | evalúa reglas-as-code      |
   |                                         v                            |
   |  healthchecks (db/redis/ia/api)   alertmanager (estado, vol ded.)    |
   |                                         ^                            |
   |  grafana (dashboards-as-code,           | consulta + visualiza       |
   |   datasource=prometheus, auth por env) -+                            |
   +---------------------------------------------------------------------+
         acceso a los UIs: protegido/no expuesto sin auth al exterior (C3)
         Alertas: VISIBLES en Grafana/Alertmanager — SIN push externo (Q1-sub)
```

- Los tres servicios viven en **`ia_internal` (`internal: true`)**: pueden hablar con `api` (scrape de `/metrics`) y entre sí, **sin ninguna ruta a internet**. Cero egress nuevo → `check-externos-backend.sh` sigue verde.
- Prometheus, Grafana y Alertmanager usan **imágenes oficiales** con config/dashboards/reglas **montadas desde el repo** (provisioning as-code) y **volúmenes de persistencia dedicados** para TSDB/estado.
- Las alertas se **enrutan a Alertmanager** y se consultan en su UI / en Grafana; **no se configura ningún receiver de notificación externa** (Q1-sub).

### 3.2 Separación observabilidad vs retención de datos vs backups (NO confundir)

```
OBSERVABILIDAD (esta fase, IN)          |  CICLO DE VIDA DEL DATO (OUT)      |  BACKUPS (DIFERIDO, §13)
----------------------------------------|-----------------------------------|---------------------------
Prometheus/Grafana/Alertmanager         |  retention_service / call_reten.  |  pg_dump + audio_store cifrado
mide salud/rendimiento del sistema      |  DATA/AUDIO_RETENTION_DAYS         |  retención + rsync a NAS LAN
dashboards/reglas as-code               |  anonimiza/purga por HABEAS DATA   |  restauración probada
```

Esta fase **no toca** ni la retención de datos de negocio ni los backups.

### 3.3 Invariante intocable: cero `tenant_id`/PII en el plano de métricas (NO se relaja)

```
PLANO DE MÉTRICAS (Prometheus — compartido entre tenants):
   - NINGUNA serie/label lleva tenant_id ni PII  (fijado en metrics.py, SPEC-022)
   - la desagregación por tenant se obtiene de los LOGS structlog (fuera de Prometheus)
   - PROHIBIDO: nuevas recording rules, relabeling o exporters que reintroduzcan tenant_id/PII
PLANO DE LOGS (structlog JSON — SÍ lleva tenant_id):
   - se queda como está (stdout/Docker), sin Loki en esta fase (Q1-A)
```

Toda la config as-code (scrape, reglas, dashboards) de esta fase **debe auditarse** para garantizar que no introduce `tenant_id`/PII como label (CE-98). Es la invariante de aislamiento más importante de esta fase.

### 3.4 Decisiones de arquitecto dentro de las decisiones vinculantes (resueltas aquí, no se preguntan)

Dentro de las decisiones del Lead quedan detalles de implementación que **resuelvo yo** (como se hizo con `platform_admins` en ADR-015), sin generar preguntas nuevas:

- **Acceso a los UIs:** Grafana con auth (admin por env, C3); Prometheus/Alertmanager no expuestos al exterior sin protección. Sin SSO en esta fase.
- **Umbrales de alerta:** candidatos de THOR (RNF-04 p95 RAG, RNF-42 RTF) + umbrales de disponibilidad (target down, 5xx); valores concretos configurables, revisables en SPEC.
- **Retención de la TSDB de Prometheus:** parametrizada por env (default conservador acorde al tamaño del host); es retención de **series de métricas**, no de datos de negocio (sin tensión HABEAS DATA).
- **Provisioning as-code:** datasource + dashboards + reglas versionados en el repo (no creados a mano en la UI), para que el entregable sea reproducible y auditable.

### 3.5 Por qué NO hay egress nuevo (y por tanto NO hay ADR de egress)

Los tres servicios de observabilidad viven en `ia_internal` (`internal: true`) y solo scrapean `api:8000/metrics` por red interna — **sin salida a internet**. Las alertas **no** notifican a ningún servicio externo (Q1-sub). El único transporte externo del proyecto (`graph.facebook.com`, ADR-006) **no se toca**. `check-externos-backend.sh` debe seguir **verde sin relajar su allowlist**. Por eso esta fase **no requiere un ADR de egress** (a diferencia de ADR-006/ADR-010) — ver §11.

---

## 4. Fases y entregables

| Fase | Nombre | Entregables clave | SPEC (propuesta) |
|------|--------|-------------------|------------------|
| **F0** | **Stack de observabilidad as-code (Prometheus + Grafana + Alertmanager) + dashboards** | Servicios nuevos en `docker-compose.yml` (red `ia_internal` sin egress, healthchecks, `restart`, volúmenes de persistencia dedicados); scrape config que deja `api:8000/metrics` **UP**; **dashboards-as-code** (HTTP latencia/errores, IA p95 vs RNF-04, STT RTF vs RNF-42); acceso a UIs protegido (Grafana admin por env, C3). **Invariante:** ninguna config reintroduce `tenant_id`/PII (§3.3). | **SPEC-077** |
| **F1** | **Reglas de alerta-as-code + Alertmanager (sin push externo)** | Reglas-as-code sobre métricas/healthchecks existentes (target down, 5xx > umbral, `readyz`/salud caída; umbrales candidatos de THOR); enrutado a Alertmanager; **alertas visibles en Grafana/Alertmanager sin notificación push externa** (Q1-sub); al menos **una alerta que dispara en prueba controlada**. | **SPEC-078** |
| **F2** | **Pruebas + seguridad + no-regresión + docs de observabilidad** | Alerta que dispara (HAWKEYE); **auditoría de aislamiento** (cero `tenant_id`/PII en scrape/reglas/dashboards, §3.3); `check-externos-backend.sh` **verde** (stack en `ia_internal`, Alertmanager sin receivers externos, sin egress nuevo); **cero secretos hardcodeados** (admin Grafana → env, no en repo ni logs, C3); **cero regresión** de `/metrics`/logging/healthchecks/#1–#8; actualización de `RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md` (operación del stack de observabilidad); cobertura/validación de la config as-code. | **SPEC-079** |

> **Nota de división (criterio de arquitecto):** F0 (infra + scrape + dashboards) / F1 (alertas) / F2 (pruebas+seguridad+no-regresión+docs). Si el Lead prefiere **fusionar F0+F1** en una sola SPEC de observabilidad (2 SPECs) o **separar docs** de F2 en fase propia, el recuento se ajusta (§8). Recomendación firme = **3 SPECs**. *(La anterior numeración de 5 SPECs —que incluía backups— queda obsoleta tras el cambio de alcance; backups ya no genera SPECs en este PLAN, §13.)*

---

## 5. Dependencias entre fases y ruta crítica

- **F0 (SPEC-077)** no depende de ninguna fase previa de este plan (consume `/metrics` existente); es la base.
- **F1 (SPEC-078)** depende de F0 (necesita Prometheus/Alertmanager levantados para evaluar reglas y Grafana para visualizarlas).
- **F2 (SPEC-079)** depende de F0/F1 (prueba el conjunto: alerta que dispara, aislamiento, egress verde, secretos, cero regresión; y documenta la operación).

**Ruta crítica:** `F0 → F1 → F2`. El mayor riesgo de aislamiento se concentra en **F0/F2** (cero `tenant_id`/PII en métricas) y el de operación en **F1** (que la alerta realmente dispare y sea visible sin push externo).

---

## 6. Riesgos y mitigaciones (R-98..R-102 — continúan tras R-97 de PLAN-009)

| # | Riesgo | Impacto | Mitigación |
|---|--------|---------|------------|
| **R-98** | **Regresión de aislamiento en el plano de métricas:** una scrape config, recording rule, relabeling o dashboard reintroduce `tenant_id`/PII como label (fuga cross-tenant + cardinalidad no acotada). | **Crítico** (fuga cross-tenant) | Invariante dura (§3.3): **ninguna config as-code** añade `tenant_id`/PII; se consume `metrics.py` tal cual (ya sin `tenant_id`). **Auditoría obligatoria** de scrape/reglas/dashboards (CE-98). La desagregación por tenant se obtiene de logs, no de Prometheus. |
| **R-99** | **La alerta no dispara / no es verificable** (reglas mal definidas, Alertmanager mal enrutado → "alertas" que nunca se activan = falsa sensación de cobertura). | **Alto** (observabilidad ciega) | Al menos **una regla que dispara en una prueba controlada** (bajar el target / inyectar 5xx) y es **visible en Alertmanager/Grafana** (CE-97, HAWKEYE); reglas as-code revisables. |
| **R-100** | **Secretos de observabilidad hardcodeados o filtrados** (admin de Grafana, cualquier token de datasource en el repo o en logs). | **Alto** (C3) | Admin de Grafana y cualquier credencial por **env**, nunca en el repo ni en logs, nunca generados por el agente (test que verifica ausencia de secretos en config/logs, CE-101). |
| **R-101** | **Egress nuevo accidental:** un servicio de observabilidad fuera de `ia_internal` o un receiver de Alertmanager externo rompen el aislamiento (`check-externos-backend.sh` rojo). | **Alto** (viola ADR-005/006, aislamiento) | Los tres servicios en `ia_internal` (`internal: true`); **cero receivers externos** en Alertmanager (Q1-sub). `check-externos-backend.sh` **verde sin relajar allowlist** (CE-102). |
| **R-102** | **Regresión de `/metrics`/logging/healthchecks/#1–#8** al añadir servicios/volúmenes nuevos. | **Alto** (rompe lo existente) | Todo **aditivo**: servicios nuevos en `ia_internal`, volúmenes nuevos; `/metrics`, `structlog` y healthchecks **intactos** (no se re-instrumenta nada); suites #1–#8 verdes sin modificar asserts; `check-externos-backend.sh` verde (CE-103). |

**Top-3:** **R-98 (regresión de aislamiento en métricas / `tenant_id` como label)**, **R-99 (alerta que no dispara / no verificable)**, **R-100 (secretos de observabilidad, C3)**. R-101 (egress accidental) inmediatamente detrás.

> *Los riesgos específicos de backups (artefacto en claro, restore no probado, secretos del NAS, peso del artefacto, tensión C2) quedan registrados para la fase diferida en **§13**; no se numeran aquí porque no entran en el alcance IN de PLAN-010.*

---

## 7. Criterios de éxito verificables (CE-95..CE-103 — continúan tras CE-94 de PLAN-009)

| ID | Criterio | Cómo se verifica | Fase |
|----|----------|------------------|------|
| **CE-95** | **Scrape UP + series consultables:** Prometheus scrapea `api:8000/metrics`, el target aparece **UP** y las series HTTP/IA/STT/WhatsApp son consultables. | Query a Prometheus: target `up==1`; `http_requests_total`, `ai_request_duration_seconds`, `stt_rtf` devuelven series. | F0 |
| **CE-96** | **Dashboard versionado (as-code):** al menos un dashboard provisionado desde el repo muestra latencia/errores HTTP, IA p95 (vs RNF-04) y RTF STT (vs RNF-42). | El dashboard carga desde el provisioning del repo (no creado a mano); paneles muestran datos. | F0 |
| **CE-97** | **Alerta que dispara (sin push externo):** al menos una regla-as-code (target down / 5xx > umbral / `readyz` caído) pasa a estado *firing* en una prueba controlada y es **visible en Grafana/Alertmanager**, sin notificación externa. | Prueba controlada (bajar el target / inyectar 5xx); la alerta aparece *firing* en Alertmanager/Grafana; **ningún receiver externo configurado**. | F1 |
| **CE-98** | **Cero `tenant_id`/PII en el plano de métricas:** ninguna serie/label/recording rule/dashboard expone `tenant_id` ni PII. | Auditoría de scrape config, reglas y dashboards; inspección de labels de todas las series expuestas (§3.3). | F0/F2 |
| **CE-99** | **Stack persistente y resiliente:** Prometheus/Grafana/Alertmanager con volúmenes de persistencia dedicados, healthchecks y `restart: unless-stopped`; sobreviven a un reinicio del stack. | Reinicio del stack: los servicios vuelven *healthy*, dashboards/series persisten. | F0 |
| **CE-100** | **UIs protegidos:** acceso a Grafana con auth (admin por env); Prometheus/Alertmanager no expuestos sin protección al exterior. | Intento de acceso sin credenciales → rechazado; config de auth por env, no hardcodeada. | F0/F2 |
| **CE-101** | **Secretos seguros (C3):** admin de Grafana y cualquier credencial → **por env**, cero hardcodeados, cero en logs. | Inspección: config/compose sin secretos literales; grep de logs sin secretos. | F0/F2 |
| **CE-102** | **Sin egress nuevo:** el stack vive en `ia_internal`; Alertmanager sin receivers externos; **`check-externos-backend.sh` verde sin relajar allowlist**. | `check-externos-backend.sh` verde; inspección de redes del compose (observabilidad en `ia_internal`). | F0/F2 |
| **CE-103** | **Cero regresión + docs reales:** `/metrics`, logging, healthchecks y suites #1–#8 intactos; `RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md` documentan la operación del stack de observabilidad. | Suites #1–#8 verdes sin modificar asserts; RUNBOOK/CHECKLIST con sección de observabilidad. | F2 |

> Transversales heredados: **aprobación explícita del Lead**; CHECKPOINTS **C3** (secretos: admin de Grafana por env — crítico aquí) / **C4** (criterios verificables, §5 del prompt) / **C6** (levantar el stack en producción on-prem = cambio sensible → aprobación del Lead + notificación antes de desplegar) / **C8** (origen `prompt-lab/prompts/PROMPT-010-OBSERVABILIDAD-BACKUPS.md`). **No existe C9** (verificado por XAVIER). *(C2 —tensión backup↔HABEAS DATA— se traslada a la fase de backups diferida, §13, pues ya no hay backup en esta fase.)*

---

## 8. Mapa de SPECs propuestas (SOLO el mapa — se redactan como PROPUESTA, se implementan tras "APROBADO PLAN-010")

> Continúa desde `specs.json` (`next_spec: 77`). Se crearán únicamente tras "APROBADO PLAN-010". Cada SPEC llevará criterios verificables (C4), clasificación SENSIBLE, dependencias y checkpoints citados.

- **SPEC-077** — Stack de observabilidad as-code: Prometheus + Grafana + Alertmanager en `docker-compose` (`ia_internal`, healthchecks, volúmenes de persistencia); scrape de `api:8000/metrics` (target UP); dashboards-as-code (HTTP/IA p95/STT RTF); acceso a UIs protegido (C3); invariante cero `tenant_id`/PII (F0).
- **SPEC-078** — Reglas de alerta-as-code sobre métricas/healthchecks existentes (target down, 5xx > umbral, `readyz` caído; umbrales candidatos de THOR) + Alertmanager; alertas visibles en Grafana/Alertmanager **sin push externo** (Q1-sub); al menos una alerta que dispara en prueba controlada (F1).
- **SPEC-079** — Pruebas + seguridad + no-regresión + docs de observabilidad: alerta que dispara, auditoría de aislamiento (cero `tenant_id`/PII), `check-externos-backend.sh` verde, cero secretos hardcodeados (C3), cero regresión #1–#8, docs de operación del stack (F2).

> Total: **3 SPECs (SPEC-077..SPEC-079)** → `next_spec` pasaría a **80** al crearlas (no ahora). **Sin ADR nuevo** → `next_adr` permanece en **16** (§11). Opciones de ajuste si el Lead lo prefiere: (a) **fusionar F0+F1** → 2 SPECs; (b) **separar docs** de F2 → 4 SPECs. Recomendación firme = **3 SPECs**.

---

## 9. Entregables finales de la fase

- **Stack de observabilidad self-hosted** (Prometheus + Grafana + Alertmanager) en `ia_internal` (sin egress), con scrape de `/metrics`, **dashboards-as-code** y **reglas de alerta-as-code**, alertas visibles sin push externo, UIs protegidos (C3), volúmenes de persistencia dedicados.
- **Suite de pruebas** (alerta que dispara, auditoría de aislamiento cero `tenant_id`/PII, egress verde, secretos por env, cero regresión #1–#8).
- **`RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md`** con la operación del stack de observabilidad.
- **Evidencia auditable:** target `/metrics` UP, dashboard/alerta funcionando, cero `tenant_id`/PII en métricas, `check-externos-backend.sh` verde, cero secretos en repo/logs.

## 10. Definition of Done (fase de observabilidad)

1. CE-95..CE-103 cumplidos y evidenciados.
2. **Observabilidad real:** Prometheus scrapea `/metrics` (target UP); dashboard-as-code muestra HTTP/IA/STT; al menos una alerta dispara en prueba controlada, visible en Grafana/Alertmanager **sin push externo**.
3. **Cero `tenant_id`/PII** en scrape/reglas/dashboards (auditoría); la invariante de `metrics.py` **no se relaja**.
4. **Stack persistente/resiliente:** volúmenes dedicados, healthchecks, `restart`; sobrevive a reinicio.
5. **UIs protegidos** (Grafana auth por env); Prometheus/Alertmanager no expuestos sin protección.
6. **Secretos seguros (C3):** admin de Grafana por env; cero hardcodeados; cero en logs.
7. **Sin egress nuevo:** stack en `ia_internal`; Alertmanager sin receivers externos; `check-externos-backend.sh` verde sin relajar allowlist.
8. **Cero regresión:** `/metrics`, logging, healthchecks y suites #1–#8 intactos sin modificar asserts.
9. **Docs reales:** `RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md` con la operación del stack de observabilidad.
10. **Sin ADR nuevo** (§11); **backups DIFERIDOS** (§13, no implementados en esta fase).
11. **Aprobación explícita del Lead**; levantar el stack en producción on-prem = cambio sensible → **aprobación del Lead + notificación** (C6); ninguna SPEC se cierra sin cumplir los CHECKPOINTS aplicables (C3/C4/C6/C8).

---

## 11. ADRs: NO se requiere ADR nuevo en esta fase (decisión explícita)

> **DECISIÓN: esta fase NO produce ningún ADR.** `next_adr` permanece en **16** (no se reclama).

Justificación, consistente con las decisiones vinculantes del Lead (§1):

- **No hay egress nuevo** (la única causa que exigiría un ADR acotado tipo ADR-006/ADR-010): el stack de observabilidad vive en `ia_internal` (`internal: true`, sin salida a internet); las alertas no notifican a ningún servicio externo (Q1-sub).
- **No hay una decisión arquitectónica estructural nueva** que fijar: se **consumen** ADR-005 (aislamiento IA), ADR-006 (egress WhatsApp acotado), ADR-009 (audio cifrado/PHI) y ADR-010 (PBX) **sin rediseñarlos**. La invariante "cero `tenant_id` en métricas" ya está fijada en `metrics.py` (SPEC-022); esta fase la **refuerza**, no la introduce.
- *(La valoración de ADR para backups —confirmada innecesaria porque el destino es LAN interna, no externo— queda registrada en §13 para la fase diferida.)*

---

## 12. PREGUNTAS ABIERTAS AL LEAD

**Ninguna de alcance.** Las decisiones Q1/Q1-sub están resueltas y adoptadas como vinculantes (prompt §7.1). Puntos que se fijan en la SPEC con supuesto por defecto (no requieren decisión previa del Lead), confirmables en la aprobación:

1. **Umbrales de alerta:** candidatos de THOR (RNF-04 p95 RAG, RNF-42 RTF) + disponibilidad (target down, 5xx); valores configurables. *El Lead puede ajustar umbrales al aprobar.*
2. **Retención de la TSDB de Prometheus:** por env (default conservador). *El Lead puede fijar otro valor.*
3. **Número de SPECs:** recomendación = **3** (SPEC-077..079). *Opcional: fusionar F0+F1 → 2, o separar docs → 4.*

---

## 13. DIFERIDO / Fuera de alcance de PLAN-010 (pendiente) — Backups automatizados

> **Instrucción directa del Lead (2026-10-02, posterior a §7.1):** *"Deja pendiente el backup automatizado."* El bloque B del PROMPT-010 **no se implementa en PLAN-010 ni genera SPECs ahora.** Esta sección preserva el trabajo de investigación/decisión ya hecho para que, cuando se retome como **fase separada** (p. ej. **PLAN-011** o una extensión futura de PLAN-010), **no haya que volver a preguntarle al Lead** — las decisiones ya están tomadas, solo **diferidas en el tiempo**.

### 13.1 El hueco sigue siendo real y prioritario (no se le quita urgencia)

Hallazgo de XAVIER, confirmado en el repo: **`backup-crm.sh` NO existe como archivo versionado** (`find . -name "backup*.sh"` → vacío) pese a que:
- `RUNBOOK.md:168–256` documenta el procedimiento completo como un `cat > /usr/local/bin/backup-crm.sh << 'EOF'` que el operador debe copiar a mano (cron diario 2 AM, retención 7 días, restore paso a paso, `gzip` + `rsync`).
- `DEPLOYMENT_CHECKLIST.md:100–104` **asume** ese script en cron + "test de restauración completado" como ítem a verificar en producción.

Es decir: el checklist exige un backup que el repo **no entrega**, el `pg_dump` actual sale **en claro**, **no cubre el `audio_store` cifrado**, y la **restauración nunca se ha probado automáticamente**. Es un hueco operativo real; se **aborda después**, no se ignora.

### 13.2 Decisiones del Lead YA TOMADAS que aplicarán a la fase de backups (vinculantes, no reabrir)

| # | Decisión vinculante (prompt §7.1) | Consecuencia para la fase futura |
|---|------------------------------------|----------------------------------|
| **Q2 — Alcance del backup** | **Opción C: PostgreSQL + `audio_store` cifrado + nota de que los modelos NO se respaldan** (`whisper_models`/`ollama_models`/voces Piper son re-descargables; se documenta la re-provisión). | El artefacto cubre datos relacionales/PHI estructurado **y** audio cifrado. `AUDIO_ENCRYPTION_KEY` se preserva pero **nunca** junto al backup (C3). Modelos → procedimiento de re-descarga documentado, no bytes respaldados. |
| **Q3 — Destino + entorno** | **Opción B: offsite dentro de la LAN/on-prem (rsync a NAS/servidor interno).** Sin egress a internet, **sin ADR-016**. Entorno: la infra `docker-compose` actual (no un servidor de producción dedicado distinto). | Protege contra fallo del host **sin** cruzar un borde de egress a internet → **NO requiere ADR de egress**. Host/credenciales del NAS **por env** (C3). Reconfigurable por env si aparece un host de producción futuro. |

### 13.3 Alcance esbozado para la fase diferida (NO se implementa ahora — referencia para el PLAN futuro)

Cuando el Lead lo retome, la fase de backups cubriría (todo aditivo, sobre el `docker-compose` actual):
- **Scripts de backup/restore versionados** (en `scripts/ops/` o `backend/scripts/`), parametrizados por env, que reemplazan el `cat > backup-crm.sh` del RUNBOOK: `pg_dump` (rol owner, bypassa RLS → captura TODOS los tenants) + **`audio_store` cifrado** → **artefacto cifrado en reposo** (nunca `.sql` plano), con **retención configurable**.
- **Dos claves distintas, ambas por env, nunca junto al backup:** `AUDIO_ENCRYPTION_KEY` (existente) y `BACKUP_ENCRYPTION_KEY` (nueva). El agente nunca las genera ni fija (C3).
- **Automatización/scheduling** (servicio compose por defecto, o cron/systemd del host documentado) + **`rsync` a NAS/host LAN interna** (host/credenciales por env, sin egress a internet).
- **Prueba de restauración reproducible** (criterio central): restore → BD consultable + `/readyz` verde + audio descifrable.
- **Actualización de `RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md`** para referenciar los scripts reales (reemplazando el manual) + re-provisión de modelos.

### 13.4 Checkpoints/riesgos que trasladan a la fase de backups (registrados, no activos en PLAN-010)

- **C2** (tensión backup "eterno" vs retención HABEAS DATA): documentar que el régimen de retención del backup es por env y su relación con la política de anonimización/purga — sin rediseñar HABEAS DATA.
- **C3** (crítico): clave de cifrado del backup + host/credenciales del NAS por env, nunca en repo ni logs, nunca junto al artefacto.
- **Riesgos específicos a retomar:** artefacto de backup en claro (regresión al `.sql` plano con PHI/todos los tenants), backup sin restauración verificada, secretos del NAS hardcodeados, peso del artefacto con `audio_store`, egress accidental del rsync. **Sin ADR de egress** (destino LAN interna).

---

> **Siguiente paso:** IRON MAN presenta este PLAN-010 (solo observabilidad) al Lead. El Lead debe responder **"APROBADO PLAN-010"** (o "Ajusta PLAN-010: …") antes de que DOCTOR STRANGE redacte las SPEC-077..SPEC-079. **No se crea ningún ADR** (§11). **Backups diferidos** (§13) — se retomarán como fase separada con las decisiones Q2/Q3 ya tomadas. Cumple CHECKPOINT C8 (origen `prompt-lab/prompts/PROMPT-010-OBSERVABILIDAD-BACKUPS.md`). `.swarm/specs.json` **NO se actualiza** hasta la aprobación del Lead.
