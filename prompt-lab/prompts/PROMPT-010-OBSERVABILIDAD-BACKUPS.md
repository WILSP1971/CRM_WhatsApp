# PROMPT-010 — Observabilidad real + backups automatizados (operación on-prem)

> Autor: 🧠 XAVIER (Professor X) — Estratega de Prompts (Nivel 1) · skill `optimizar-prompt`
> Fecha: 2026-10-02 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo`) — el stack toca datos operativos con PHI potencial (transcripciones médicas, ADR-009) bajo RLS multi-tenant; un exporter con labels de tenant o un backup sin cifrar serían una regresión de aislamiento/confidencialidad.
> Marco aplicado: **C.R.A.F.T.** (Contexto · Rol · Acción · Formato · Tests)
> Destino: este prompt alimenta a 🔮 **DOCTOR STRANGE** para **PLAN-010** (NO genera SPECs por sí mismo).
> Contadores REALES (`.swarm/specs.json`): `next_plan: 10`, `next_spec: 77`, `next_adr: 16`. DOCTOR STRANGE avanza `next_plan` a 11 al cerrar PLAN-010.
> Posición en la secuencia ordenada por el Lead: **Fase B de 4** (1. Onboarding multi-tenant ✅ CERRADO/PLAN-009 · **2. Observabilidad real + backups automatizados ← ESTA** · 3. Hardening de producción · 4. Instagram DM).
> ⚠️ **Puerta obligatoria:** este prompt NO es aprobación. Requiere PLAN-010 aprobado por el Lead y luego SPECs aprobadas antes de escribir código (CLAUDE.md del enjambre). Además hay **preguntas abiertas VINCULANTES (§7)** que el Lead debe responder antes de que DOCTOR STRANGE fije alcance.

---

## 0. Resumen del encargo (una frase)

Convertir la observabilidad y los backups de **"documentados pero manuales"** a **"reales y automatizados"**: levantar un stack de observabilidad self-hosted que efectivamente **scrapee, visualice y alerte** sobre el `/metrics` y los logs que el backend YA emite, y materializar un **servicio de backup versionado, cifrado, con retención y restauración probada** que hoy solo existe como instrucciones manuales en el RUNBOOK.

Esta fase **NO instrumenta nuevas métricas de negocio** (ya hay un dashboard de analítica, Entregable #7/SPEC-062..066) ni **rediseña la retención de DATOS de negocio** (`retention_service`/`call_retention_service`, `AUDIO_RETENTION_DAYS` — eso es ciclo de vida del dato, NO backup de infraestructura). Consume lo existente y cierra el hueco operativo.

---

## 1. Contexto (verificado en el repo, no asumido)

### 1.1 Observabilidad: el endpoint existe, el stack NO
- **`/metrics` REAL y rico** (`backend/app/main.py:265`, implementado en `backend/app/core/metrics.py`, SPEC-022): formato Prometheus vía `prometheus_client==0.19.0` (ya en `requirements.txt`), registro dedicado `CollectorRegistry`. Métricas expuestas HOY:
  - **Técnicas HTTP:** `http_requests_total{method,path,status_code}`, `http_request_duration_seconds{method,path}` (buckets hasta 10s).
  - **IA local:** `ai_request_duration_seconds{operation,model}` (buckets alineados a RNF-04 p95 RAG; cubre degradación CPU hasta 60s), `ai_request_errors_total{operation,error_type}`.
  - **STT (SPEC-038, ADR-009):** `stt_rtf{model,device}`, `stt_queue_latency_seconds`, `stt_jobs_total{resultado}`.
  - **WhatsApp notas de voz (SPEC-060):** `whatsapp_media_downloads_total{resultado}`, `whatsapp_audio_discarded_by_duration_total`.
  - **INVARIANTE DE DISEÑO YA FIJADO (no tocar):** NINGUNA métrica lleva `tenant_id` como label — decisión explícita y documentada en el docstring de `metrics.py` (cardinalidad no acotada + fuga cross-tenant en un backend de métricas compartido). La desagregación por tenant se obtiene de los **logs estructurados** (`structlog`, que SÍ llevan `tenant_id`), no de Prometheus. **Cualquier stack de observabilidad de esta fase DEBE respetar esto.**
- **NADIE scrapea `/metrics`:** NO hay Prometheus, Grafana, Alertmanager, Loki ni ningún config file de observabilidad en el repo (`find` sobre `prometheus.y*ml`/`grafana*`/`loki*`/`alertmanager*` → vacío). El endpoint es un árbol que cae en un bosque sin oídos.
- **Logging:** `structlog` configurado en `backend/app/main.py:37` con pipeline a **JSON** (`JSONRenderer`, `TimeStamper` ISO, `add_log_level`, `add_logger_name`). Hay un `audit_log` dedicado (`app/core/audit_log.py`, logger `audit.personal_data`) para accesos a datos personales (HABEAS DATA). **Todo va a stdout/stderr del proceso: NO hay agregación centralizada** (ni Loki/ELK ni rotación gestionada — depende del driver de logs de Docker del host).
- **Healthchecks SÍ existen** en `docker-compose.yml` para `db` (`pg_isready`), `redis`, `ollama`, `api` (`/readyz`) y demás servicios. El backend expone `/healthz` y `/readyz`. Esto es base aprovechable, NO el objetivo.

### 1.2 Backups: documentados en el RUNBOOK, pero 100% manuales y NO versionados
- **El RUNBOOK YA describe el procedimiento completo** (`RUNBOOK.md` §"Backups de PostgreSQL", líneas 168–256): `pg_dump` full plano, un script `backup-crm.sh` para `cron` (diario 2 AM, retención 7 días vía `find -mtime +7 -delete`), restauración paso a paso (incluye borrar el volumen `crm_whatsapp_db_data` y re-restaurar), y una nota de `gzip` + `rsync` a un "servidor remoto seguro".
- **PERO ese `backup-crm.sh` NO existe como archivo versionado** (`find . -name "backup*.sh"` → vacío; no está en `backend/scripts/` ni en `scripts/`, que solo contienen `verify_stt_rtf.py` y `check-externos.sh`). Es un `cat > ... << EOF` que el operador debe copiar a mano al host. **El `DEPLOYMENT_CHECKLIST.md` (líneas 100–104) lo lista como ítem a verificar en producción** ("Script `backup-crm.sh` está en cron", "test de restauración completado") — es decir: el checklist ASUME un backup que el repo NO entrega. Ese es exactamente el hueco de esta fase.
- **Limitaciones del enfoque manual actual que esta fase debe resolver:** (a) solo cubre **Postgres** — ignora el **audio cifrado en reposo** (`audio_store`, SPEC-035/ADR-009, con `AUDIO_ENCRYPTION_KEY`) y los **pesos de modelos** (`whisper_models`, `ollama_models`, voces Piper — aunque estos son re-descargables/reproducibles, no datos); (b) el `pg_dump` sale **en claro** (`.sql` plano) — un backup de PHI sin cifrar en reposo contradice el cifrado del `audio_store`; (c) el offsite (`rsync` a "servidor-backup") requiere **credenciales/host que el repo NO tiene y el agente NUNCA debe inventar** (C3); (d) **la restauración nunca se ha probado automáticamente** — un backup sin restore verificado no es un backup.
- **NO confundir con retención de datos de NEGOCIO:** `DATA_RETENTION_DAYS=90` (anonimización de contactos inactivos), `AUDIO_RETENTION_DAYS=30` y el job `run_call_retention_job` (`config.py:134/278`) son **ciclo de vida del dato bajo HABEAS DATA**, NO backups de infraestructura. Están fuera de alcance de esta fase (solo se citan como vecinos para no pisarlos).

### 1.3 Topología e invariantes del proyecto que rigen esta fase
- **100% self-hosted / on-premise, CPU-only**, sin presupuesto de SaaS externo. El proyecto ha evitado consistentemente dependencias externas de pago en todas las fases (patrón de ADR-005 "bloqueo de egress del contenedor IA"; el espíritu "preferir self-hosted" aplica aquí aunque ese ADR sea específico de inferencia).
- **Egress acotado y auditado:** `backend/check-externos-backend.sh` falla el CI ante cualquier dominio/IP de inferencia externa o `graph.facebook.com` fuera del módulo WhatsApp. El único patrón aprobado para egress legítimo-pero-externo es un **ADR acotado** (ADR-006 WhatsApp, ADR-010 PBX). **Un backup offsite a un servicio/host externo sería un borde de egress nuevo y por tanto un caso SENSIBLE que requiere su propio ADR** (análogo a ADR-010), no una decisión del agente.
- **RLS multi-tenant (ADR-004/ADR-008):** rol de aplicación `omnicore_app` NOSUPERUSER NOBYPASSRLS. **Un `pg_dump` se hace con el rol owner (`postgres`), que SÍ bypassa RLS** — correcto para un backup full (debe capturar TODOS los tenants), pero implica que **el fichero de backup contiene datos de TODOS los tenants sin fronteras de RLS** → refuerza por qué debe ir cifrado y con acceso mínimo.
- **PHI potencial (ADR-009):** transcripciones de llamadas/notas de voz médicas. Confidencialidad en reposo es un requisito duro, no un nice-to-have.
- **CI sin CD:** existe `.github/workflows/` pero el deploy es manual (`docker-compose up`, migraciones manuales). NO hay staging (un solo `docker-compose.yml`). Esto NO es el objetivo de esta fase (es la Fase C "Hardening"), pero condiciona el alcance: lo que se entregue debe operarse en el stack `docker-compose` actual.

---

## 2. Rol (quién resuelve)

- **🔮 DOCTOR STRANGE** — PLAN-010 + SPECs (dos puertas de aprobación).
- **🛡️ CAPTAIN AMERICA** — orquestación de la implementación / decisiones de integración en `docker-compose`.
- **🐾 BLACK PANTHER** — backend/infra: servicio(s) de observabilidad y backup, config de scrape, scripts versionados, healthchecks.
- **🕷️ BLACK WIDOW** — seguridad: que el exporter no filtre datos de tenant/PHI, que los backups vayan cifrados, que los secretos del destino offsite estén por env (C3), y el ADR de egress si hay offsite externo.
- **🦅 HAWKEYE** — pruebas: **la prueba de restauración** (el criterio de éxito más importante de los backups) y validación de que las alertas disparan.
- **⚡ THOR** — consultor de performance: es el consumidor natural de `ai_request_duration_seconds`/`stt_rtf`; sus umbrales (RNF-04 p95 RAG, RNF-42 RTF) son candidatos directos a reglas de alerta.
- **🩹 WOLVERINE** — calidad: que los nuevos servicios/scripts queden en CI (lint de config, `check-externos-backend.sh` verde, dashboards/reglas versionados como código).

---

## 3. Acción (verbo único y medible por sub-objetivo)

### A. Observabilidad real
- **DESPLEGAR** un stack de observabilidad **self-hosted** que **scrapee** `/metrics`, **visualice** en dashboards y **alerte** sobre umbrales — todo como **configuración versionada en el repo** (dashboards-as-code, reglas-as-code), integrado en `docker-compose.yml`, en la red interna `ia_internal` sin egress nuevo.
- **DEFINIR** un conjunto mínimo de **reglas de alerta** sobre las métricas/healthchecks YA existentes (ver §5 criterios), con un **canal de notificación** (ver §7 Q1).
- **(Opcional, según §7 Q1)** **AGREGAR** los logs `structlog` JSON en un store consultable self-hosted (Loki) — o dejarlo fuera de alcance si el Lead lo difiere.

### B. Backups automatizados
- **MATERIALIZAR** `backup-crm.sh` (y su equivalente de restore) como **scripts versionados en el repo** (p. ej. `backend/scripts/` o `scripts/ops/`), parametrizados por env, que hoy solo viven como texto en el RUNBOOK.
- **AUTOMATIZAR** su ejecución (servicio de backup en `docker-compose` con scheduler, o unidad documentada para `cron`/systemd del host — ver §7 Q3), con **retención configurable** y **cifrado en reposo** del artefacto.
- **PROBAR la restauración** de forma automatizable/repetible (el criterio de aceptación central).
- **DECIDIR el alcance del artefacto** (Postgres solo vs Postgres + `audio_store` cifrado) y el **destino** (local vs offsite) — ambos dependen de §7 Q2/Q3; el offsite externo exige ADR de egress.

---

## 4. Formato (estructura exacta de la salida esperada de DOCTOR STRANGE / implementación)

1. **PLAN-010.md** (`.swarm/PLAN-010.md`): alcance, fases (A observabilidad / B backups), entregables, riesgos, criterios de éxito, matriz de preguntas→decisiones (resolviendo §7), y clasificación SENSIBLE.
2. **SPECs** (`.swarm/specs/SPEC-077..0NN.md`) desde `next_spec:77`, con la cabecera/estilo de SPEC-075/076 (deriva de PLAN-010, clasificación, dependencias, checkpoints citados).
3. **ADR(s)** desde `next_adr:16` **SOLO si** la decisión del Lead introduce egress offsite externo (análogo a ADR-010) o una excepción de confidencialidad.
4. **Artefactos de implementación esperados:**
   - Config de observabilidad versionada (scrape config, reglas de alerta, dashboards-as-code) + servicios en `docker-compose.yml` (red `ia_internal`, healthchecks, restart policy, volúmenes de persistencia dedicados).
   - Scripts de backup/restore versionados (parametrizados por env, cifrado, retención) + servicio/scheduler o unidad de cron documentada.
   - Actualización del `RUNBOOK.md` (reemplazar el `cat > backup-crm.sh` manual por "usar el script versionado `X`") y del `DEPLOYMENT_CHECKLIST.md` (ítems que ahora SÍ tienen entregable).
   - Pruebas (HAWKEYE): restore verificado + alerta que dispara.

---

## 5. Tests / criterios de éxito (verificables — C4)

### Observabilidad
- [ ] Prometheus (o equivalente self-hosted) **scrapea `/metrics`** y el target aparece **UP**; las series HTTP/IA/STT/WhatsApp son consultables.
- [ ] Existe **al menos un dashboard versionado** (as-code) que muestra latencia/errores HTTP, latencia IA (`ai_request_duration_seconds` p95 vs RNF-04), y RTF STT (`stt_rtf` vs RNF-42).
- [ ] Existe **al menos una regla de alerta** que **dispara en una prueba controlada** (p. ej. target `down`, tasa de error HTTP 5xx > umbral, o `readyz` caído) y **notifica por el canal elegido** (§7 Q1).
- [ ] **CERO regresión de aislamiento:** ninguna serie/label expone `tenant_id` ni PII; `check-externos-backend.sh` sigue **verde** (sin egress nuevo); el stack vive en `ia_internal`.
- [ ] El acceso a dashboards/alertas está protegido (no expuesto sin auth al exterior).

### Backups
- [ ] Un **backup se genera automáticamente** sin intervención manual, **cifrado en reposo**, con **retención configurable** aplicada.
- [ ] **La restauración se prueba y se verifica** (criterio central): restaurar un backup en un entorno limpio produce una BD consultable y `/readyz` verde. HAWKEYE automatiza o documenta reproduciblemente este test.
- [ ] Los scripts están **versionados en el repo** y parametrizados por **env (C3)** — **cero secretos hardcodeados**, **cero credenciales del destino offsite en el repo o en logs**.
- [ ] El `RUNBOOK.md` y el `DEPLOYMENT_CHECKLIST.md` referencian los artefactos reales (no instrucciones de copiar/pegar).

---

## 6. Checkpoints aplicables (C1–C8 del proyecto — NO existe C9)

> Nota de XAVIER: se verificó que **NO existe un checkpoint C9** en el repo (`grep C9` → vacío). Los checkpoints citados en specs recientes (SPEC-072/076) son **C1–C8**. El caso "egress offsite" NO es un checkpoint numerado: se gobierna por el **patrón de ADR de egress acotado** (ADR-006/ADR-010) + `check-externos-backend.sh`.

- **C2 (borrado lógico / retención):** el backup/observabilidad NO debe subvertir la retención HABEAS DATA — un backup "eterno" de datos que la política anonimiza a los 90 días es una tensión a documentar (¿los backups caducan acorde a la política de retención?). A resolver en el PLAN.
- **C3 (secretos):** 🔴 **crítico aquí.** Credenciales de cualquier destino offsite, clave de cifrado de backups, y credenciales de acceso a dashboards → **SIEMPRE por env/secreto del operador, NUNCA hardcodeadas, NUNCA generadas por el agente, NUNCA en logs.** Mismo trato que `DB_APP_PASSWORD`/`AUDIO_ENCRYPTION_KEY`.
- **C4 (criterios verificables):** todos los criterios de §5 son objetivos y demostrables.
- **C6 (deploy sensible):** levantar el stack / activar backups en producción on-prem es cambio sensible → **aprobación explícita del Lead + notificación** antes de desplegar.
- **C8 (trazabilidad):** origen = PLAN-010 / `prompt-lab/prompts/PROMPT-010-OBSERVABILIDAD-BACKUPS.md`.
- **Egress (patrón ADR, no checkpoint):** si el Lead elige **offsite externo** (S3/host remoto fuera de la LAN), se requiere un **ADR-016 acotado** análogo a ADR-010, y `check-externos-backend.sh` debe contemplar explícitamente ese borde. Si el offsite es un **host dentro de la LAN/on-prem** (rsync a un NAS interno), NO es egress a internet y NO requiere ADR de egress.

---

## 7. Preguntas abiertas para el Lead (VINCULANTES — DOCTOR STRANGE las necesita para fijar alcance)

> Formato con opciones (como en PROMPT-009). El Lead responde; la respuesta se anexará como sección "Respuestas del Lead — VINCULANTES" antes de PLAN-010.

**Q1 — Stack de observabilidad y alertas: ¿profundidad y canal?**
El candidato natural (100% self-hosted, sin SaaS, respeta ADR-005) es **Prometheus + Grafana + Alertmanager** en `docker-compose`. La pregunta es el ALCANCE:
- **(A) Métricas + dashboards + alertas (Prometheus+Grafana+Alertmanager)**, logs se quedan como están (stdout/Docker). — *lo más acotado y entregable en esta fase.*
- **(B) Opción A + agregación de logs self-hosted (Loki + promtail)** para consultar los `structlog` JSON por `tenant_id`/`trace_id`. — *más completo, más superficie operativa.*
- **(C) Otro stack self-hosted que prefieras** (p. ej. VictoriaMetrics, Netdata).
- **Sub-pregunta canal de alerta:** ¿a dónde notifican las alertas? Existe en la memoria del orquestador un "bridge de Telegram" para notificaciones de deploy/checkpoints (C6) — **¿es un canal real reutilizable para alertas operativas, o es solo un mecanismo de la sesión del orquestador NO conectado a este repo?** Si no hay canal real, el default seguro es **alertas visibles en Grafana/Alertmanager (sin notificación push externa)** para no inventar integraciones.

**Q2 — Backups: ¿qué se respalda, exactamente?**
- **(A) Solo PostgreSQL** (`db_data` vía `pg_dump` cifrado). Audio y modelos quedan fuera. — *cubre los datos relacionales/PHI estructurado; el audio quedaría sin backup.*
- **(B) PostgreSQL + `audio_store`** (audio cifrado en reposo, SPEC-035/ADR-009). — *cubre también las notas de voz/grabaciones; el artefacto crece y debe preservar/gestionar `AUDIO_ENCRYPTION_KEY` con cuidado (la clave NO se guarda junto al backup, C3).*
- **(C) B + nota explícita de que los modelos (`whisper_models`/`ollama_models`/voces Piper) NO se respaldan** por ser reproducibles/re-descargables (se documenta el procedimiento de re-provisión en vez de backup). — *recomendación de XAVIER por defecto si no indicas otra cosa.*

**Q3 — Destino del backup y entorno objetivo: ¿local, LAN interna, u offsite externo? ¿Y esta fase opera sobre un servidor de producción real o sobre la infra de desarrollo/demo?**
Esto decide si hay egress (→ ADR) y cuánta protección contra fallo de hardware se exige:
- **(A) Local al mismo host** (directorio del host). Simple, pero NO protege contra fallo de disco/host. — *mínimo viable.*
- **(B) Offsite dentro de la LAN/on-prem** (rsync a un NAS/servidor interno). Protege contra fallo del host, **sin egress a internet, sin ADR nuevo.** — *recomendación de XAVIER si existe ese destino interno.*
- **(C) Offsite externo** (S3 compatible / host remoto fuera de la LAN). Máxima protección, pero **introduce egress → requiere ADR-016 acotado + credenciales que TÚ (Lead) debes proveer** (el agente no las inventa). ¿Tienes un endpoint/bucket y credenciales, o lo dejamos como contingencia documentada (como hizo ADR-010 con el PBX externo)?
- **Entorno:** ¿esta Fase B se diseña para un **servidor de producción ya corriendo**, o sigue siendo sobre la **infra de desarrollo/demo** actual (dimensiona la urgencia del offsite y el realismo de la prueba de restore)?

---

## 8. Fuera de alcance (anti-scope explícito)

- NUEVAS métricas de negocio o dashboards de analítica de negocio (ya existe Entregable #7, SPEC-062..066 — no duplicar).
- Rediseño de la retención de datos de negocio (`retention_service`, `AUDIO_RETENTION_DAYS`, HABEAS DATA) — es ciclo de vida del dato, no backup.
- CD / pipeline de deploy / entorno de staging — es la **Fase C (Hardening)**, siguiente en la secuencia.
- Añadir `tenant_id` como label de Prometheus — prohibido por diseño ya fijado en `metrics.py`.
- Inventar servicios SaaS de pago, URLs o credenciales externas.

---

## 7.1 Respuestas del Lead — VINCULANTES (2026-10-02)

- **Q1 (profundidad del stack):** **Opción A** — Prometheus + Grafana + Alertmanager. Logs se quedan como están (stdout/Docker, sin Loki/promtail en esta fase).
- **Q1-sub (canal de alertas):** **Alertas solo visibles en Grafana/Alertmanager**, sin notificación push externa. El bridge de Telegram de la memoria del orquestador NO se reutiliza para esto — es un mecanismo de sesión, no un canal operativo de este repo.
- **Q2 (alcance del backup):** **Opción C** — PostgreSQL + `audio_store` cifrado + nota explícita documentando que los modelos (`whisper_models`/`ollama_models`/voces Piper) NO se respaldan por ser re-descargables/reproducibles (se documenta el procedimiento de re-provisión en vez de backup).
- **Q3 (destino + entorno):** **Opción B** — offsite dentro de la LAN/on-prem (rsync a un NAS/servidor interno). Sin egress a internet, **sin ADR-016 necesario**. Entorno objetivo: se diseña sobre la infraestructura `docker-compose` actual del proyecto (no se asume un servidor de producción dedicado ya corriendo, consistente con el resto de fases de este proyecto) — si en el futuro aparece un host de producción distinto, el destino LAN se reconfigura por env, no por cambio de diseño.

**Consecuencia directa para DOCTOR STRANGE:** no se requiere ADR de egress para esta fase (el destino es LAN interna, no externo); SÍ aplica C3 estrictamente para la clave de cifrado del backup y cualquier credencial/host del NAS interno (por env, nunca hardcodeado); el alcance de PLAN-010 cubre Prometheus+Grafana+Alertmanager (sin Loki) + backup Postgres+audio_store con restauración probada.

---

## 9. Trazabilidad

- **Origen:** objetivo verbatim del Lead "Fase B: Observabilidad real + backups automatizados" (2ª de 4 fases ordenadas).
- **Evidencia del estado real** (verificada por XAVIER en esta sesión): `backend/app/core/metrics.py`, `backend/app/main.py:37/265`, `backend/app/core/audit_log.py`, `docker-compose.yml` (sin servicios de observabilidad; healthchecks presentes; volúmenes `db_data`/`audio_store`/`whisper_models`/`ollama_models`), `RUNBOOK.md:168–256` (backup manual documentado), `DEPLOYMENT_CHECKLIST.md:100–104`, `backend/scripts/` (sin `backup-crm.sh`), `backend/check-externos-backend.sh`, ADR-005/006/009/010, `backend/app/core/config.py:134/272/278`.
- **Siguiente paso:** el Lead responde §7 → se anexan respuestas VINCULANTES → 🔮 DOCTOR STRANGE redacta PLAN-010 → aprobación del Lead → SPECs → aprobación → implementación.
