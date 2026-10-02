# PLAN-011 — Hardening de producción (Fase C): endurecer la frontera entre el código y el host sobre la infra `docker-compose` actual — contenedores no-root + límites de recursos, rate-limiting GENERAL de API, escaneo de vulnerabilidades BLOQUEANTE en CI, firewall de host + restricción de puertos, coherencia HSTS/CSP, TLS de producción y Dockerfile de producción — SIN reimplementar la seguridad de aplicación ya madura, SIN CD/staging, SIN tocar el runbook operativo, SIN retomar backups

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Fecha: 2026-10-02 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo`) — endurecer la superficie de un backend multi-tenant (RLS, ADR-004/008) con PHI potencial (audio/transcripciones, ADR-009) y egress acotado (ADR-005/006/010). Un endurecimiento mal hecho (romper el aislamiento `ia_internal`, abrir un puerto, relajar un fail-fast de secreto, estrangular STT/IA, o un header TLS inconsistente) sería una **REGRESIÓN de seguridad o de servicio**, no una mejora.
> Origen: `prompt-lab/prompts/PROMPT-011-HARDENING-PRODUCCION.md` (🧠 XAVIER, C.R.A.F.T.) — decisiones del Lead a §7 ya **VINCULANTES** (§7.1, 2026-10-02). **NO se reabren** (ver §1, tabla de decisiones).
> Posición en la secuencia ordenada por el Lead: **Fase C de 4** (1. Onboarding multi-tenant ✅ PLAN-009 · 2. Observabilidad real ✅ PLAN-010 — backups DIFERIDOS · **3. Hardening de producción ← ESTA** · 4. Instagram DM).
> Regla de oro: este PLAN **NO genera SPECs ni código**. Las SPEC se redactan como PROPUESTA y solo pasan a implementación tras aprobación explícita del Lead ("APROBADO PLAN-011" y luego "APROBADO SPEC-XXX"). **Dos puertas obligatorias:** primero PLAN, luego SPEC.
> Base que se CONSUME y se REFUERZA (jamás se rediseña ni se relaja): fail-fast de secretos (`backend/app/core/config.py:609–672`, `_require_strong_secret`/`_require_internal_ai_host`), RLS efectiva (ADR-004/008, rol `omnicore_app` NOSUPERUSER NOBYPASSRLS), CORS endurecido (`main.py:109–116`), security headers (`security_headers.py`, montado en `main.py:122`), cifrado de audio en reposo (ADR-009, `AUDIO_ENCRYPTION_KEY` Fernet), egress acotado y auditado (`check-externos-backend.sh`, ADR-005/006/010), rate-limiting de LOGIN (`security/rate_limit.py`, `LoginRateLimiter`, SPEC-013), stack de observabilidad en `ia_internal` (PLAN-010). Estas son **invariantes a reforzar**, nunca a tocar.
> Contadores vigentes (`.swarm/specs.json`, verificados 2026-10-02): `next_plan: 11` (este plan; al cerrarse PLAN-011 pasa a **12**), `next_spec: 80`, `next_adr: 16`. **`next_spec`/`next_adr` NO se reclaman aquí**: se consumen al crear las SPEC/ADR tras "APROBADO PLAN-011". **DECISIÓN de este plan sobre ADR: ver §11** (se recomienda **un** ADR acotado para la política de firewall de host como contrato de seguridad → `next_adr` pasaría a 17 al crearlo).

---

## 1. Objetivo y contexto

### Objetivo

Pasar el despliegue on-prem de **"funcionalmente completo y razonablemente seguro a NIVEL DE APLICACIÓN"** a **"endurecido a NIVEL DE OPERACIÓN E INFRAESTRUCTURA"**: cerrar los huecos de hardening que viven en la **frontera entre el código y el host**, sobre la infraestructura `docker-compose` actual (sin CD/staging, sin servidor de producción dedicado confirmado), sin introducir egress nuevo y sin relajar ninguna invariante ya fijada:

1. **Contenedores:** imagen de producción con **usuario no-root**, sin `--reload`, sin código de test ni bind-mount de desarrollo; **límites de recursos** (`mem_limit`/`cpus`/`pids_limit`), `security_opt: no-new-privileges`, `cap_drop` donde sea viable.
2. **Rate-limiting GENERAL de API** por IP/endpoint (hoy solo existe para login), reutilizando el Redis ya presente, protegiendo webhooks públicos (WhatsApp/PBX) y endpoints REST, sin degradar tráfico legítimo.
3. **Escaneo de vulnerabilidades en CI**, gate **BLOQUEANTE en HIGH/CRITICAL** (`pip-audit` backend, `npm audit` frontend, `bandit` SAST Python) + `.github/dependabot.yml`.
4. **Firewall de host** (`nftables`) versionado con DROP de egress de IA + **restricción de puertos**: `db`/`redis`/`api` dejan de publicarse a `0.0.0.0`.
5. **Coherencia HSTS/CSP** (D-1) entre `security_headers.py` y `DEPLOYMENT_CHECKLIST.md`, y **TLS de producción** (ACME/Let's Encrypt en Caddy para cuando haya dominio real).

Es un trabajo **endurecedor y aditivo** sobre lo existente: **NO reimplementa la seguridad de aplicación que YA está hecha** (fail-fast de secretos, RLS, CORS, security headers salvo la coherencia D-1, cifrado de audio, egress acotado — todo verificado en §1.4). Consume lo existente y endurece la capa operativa/infra que lo rodea.

### Decisiones del Lead ya VINCULANTES (prompt §7.1, 2026-10-02 — NO se reabren)

| # | Pregunta | Decisión vinculante | Consecuencia de alcance (hardening) |
|---|----------|---------------------|--------------------------------------|
| **Q1 — Alcance de "hardening"** | **Opción A:** solo endurecimiento TÉCNICO de infra/contenedores/CI/firewall/TLS (H-1, H-3, H-4/D-2, D-1, H-5/H-6). | IN: contenedores, rate-limiting, escaneo CI, firewall/puertos, coherencia headers, TLS/Dockerfile de producción. OUT: runbook operativo, CD/staging. |
| **Q2 — Overhead operativo** | **Opción A:** se deja `RUNBOOK.md` como está; esta fase se concentra en lo técnico. | NO se extiende/reescribe el runbook de incidentes/rotación. Solo se **referencian** los artefactos nuevos (firewall, escaneo, TLS) en `DEPLOYMENT_CHECKLIST.md` convirtiendo `[ ]` fantasma en artefactos reales. |
| **Q3 — Entorno objetivo y CD/staging** | **Opción A:** se diseña sobre la infra `docker-compose` actual de desarrollo/demo; no hay servidor de producción dedicado confirmado; el deploy sigue manual. | Todo sobre `docker-compose.yml`. CD/pipeline/staging/servidor de producción dedicado = **OUT** (fase posterior propia si el Lead la pide). TLS de producción se **materializa como config parametrizada por dominio/env**, lista para activarse cuando exista dominio real. |
| **Q4 — Rate-limiting general** | **Opción A: ALTA prioridad, entra en esta fase.** Reutiliza el Redis existente; cubre webhooks públicos (WhatsApp/PBX) y REST. | H-2 es IN y de alta prioridad. Defensa anti-abuso/DoS por IP/endpoint, sin degradar tráfico legítimo (validación de latencia por THOR). |
| **Q5 — Escaneo de vulnerabilidades** | **Opción A: gate BLOQUEANTE en HIGH/CRITICAL** (`pip-audit`/`npm audit`/`bandit`). Sub-pregunta compliance: **sin marco regulatorio formal** (SOC2/ISO/HIPAA/PCI) — "buenas prácticas de seguridad". | El CI **falla** ante HIGH/CRITICAL. No se mapea a ningún framework de compliance (no inventar SOC2/HIPAA). Dependabot activo. El escaneo de CVEs online corre en el **runner de CI** (con egress), nunca desde el host on-prem aislado. |
| **Q6 — Backups diferidos (PLAN-010 §13)** | **Opción A: SIGUEN DIFERIDOS.** Esta fase C NO los retoma. | Backups **fuera de alcance** (ni IN, ni OUT discutible). Las decisiones Q2/Q3 de PLAN-010 §13 ya están tomadas para su fase posterior. **Esta fase no los menciona como entregable.** |

### Contexto verificado en código (fuente de verdad, no asunciones — 2026-10-02)

> Hallazgo central (patrón idéntico al de backups en PLAN-010): **la seguridad de APLICACIÓN está notablemente madura y bien testeada; el hueco real está en la capa INFRA/OPERACIÓN** (host, contenedores, pipeline, y checkboxes del checklist que asumen artefactos que no existen).

- **H-1 · Hardening de contenedores AUSENTE.** `grep` sobre `docker-compose.yml` → CERO `mem_limit`/`cpus`/`deploy.resources`/`read_only`/`user:`/`cap_drop`/`security_opt`/`no-new-privileges`/`pids_limit`/`ulimits`. El `backend/Dockerfile` (verificado) corre como **root** (sin `USER`; `pip install` y `CMD uvicorn` como root), arranca con **`--reload`** (flag de desarrollo) y hace `COPY . .` (incluye tests y cualquier `.env` presente); además `docker-compose.yml` monta bind-mount de desarrollo del código.
- **H-2 · Rate-limiting GENERAL AUSENTE.** El único rate-limiting es el de login (`LoginRateLimiter`). NO hay `slowapi`/`fastapi-limiter` en `requirements.txt` (verificado: 0 coincidencias) ni límite por IP/endpoint para el resto de la API (webhooks WhatsApp/PBX, endpoints REST, `/rag/draft`). Caddy tampoco aplica rate-limiting.
- **H-3 · Escaneo de vulnerabilidades AUSENTE.** El CI backend (`backend-ci.yml`) corre `black`/`flake8`/`mypy`/`check-externos-backend.sh`/`pytest`+cobertura≥80% + smoke de carga, pero **NO** `pip-audit`/`safety`/`bandit`/`trivy`. El CI frontend (`ci.yml`) corre lint/build/test/Lighthouse pero **NO** `npm audit`. **NO existe `.github/dependabot.yml`.** Base sólida: `requirements.txt` 100% pinneado con `==` (sin rangos abiertos) → escaneo reproducible.
- **H-4/D-2 · Firewall de host / restricción de puertos documentado pero SIN artefacto.** `DEPLOYMENT_CHECKLIST.md` (Fase 2, líneas 46–52) pide reglas `iptables`/`nftables` DROP de egress de Ollama y restricción de `8000/5432/6379/11434`, pero **NO existe script de firewall/hardening versionado**. En `docker-compose.yml` (verificado): `db` publica `"${DB_PORT:-5432}:5432"`, `redis` `"${REDIS_PORT:-6379}:6379"` y `api` `"${API_PORT:-8000}:8000"` al host (`0.0.0.0`, todas las interfaces), mientras `ia` sí restringe a `"127.0.0.1:11434:11434"`. Los servicios de observabilidad de PLAN-010 (Prometheus/Grafana/Alertmanager) ya nacen **sin `ports:` publicado** (patrón correcto a imitar).
- **D-1 · HSTS/CSP divergen entre doc y código (verificado).** `security_headers.py:42` usa `max-age=15552000` (180 días) + CSP con `'unsafe-inline'` en `style-src`/`script-src` (para no romper Swagger `/docs`, según su propio docstring). `DEPLOYMENT_CHECKLIST.md:71,74` pide `max-age=31536000` (1 año) + CSP `default-src 'self'` **sin `unsafe-inline'`. Incoherencia doc↔código que esta fase debe resolver (decisión de arquitecto en §11.2).
- **H-5 · TLS de producción solo como comentario.** `Caddyfile` (verificado) expone solo `/webhooks/pbx/recordings` y `/voice/ws`; TLS de producción es un comentario ("usar cert válido Let's Encrypt"), sin bloque ACME configurado ni parametrización de dominio más allá de `{$CADDY_DOMAIN:localhost}`. El tráfico de `/api/*` NO pasa por Caddy hoy.
- **H-6 · Dockerfile de producción inexistente.** Un solo `Dockerfile` con `--reload` + `COPY . .` + bind-mount en runtime. No hay separación imagen de producción vs desarrollo.

### Invariantes que rigen esta fase (intocables — §1.4)

- **100% self-hosted / on-premise, CPU-only**, sin SaaS de pago (ADR-005): todo el hardening es self-hosted (`pip-audit`/`bandit`/`npm audit` en el runner de CI gratuito; firewall con `nftables` del host; no WAF/secret-manager/escáner SaaS de pago).
- **Egress acotado y auditado** (`check-externos-backend.sh`): ningún endurecimiento introduce egress nuevo en runtime ni rompe el guardarraíl. Endurecer el firewall **REFUERZA** (no relaja) el aislamiento `ia_internal`. El escaneo de CVEs online corre **en el CI** (runner con egress), **nunca** desde el host on-prem aislado — distinguir plano CI vs plano runtime.
- **RLS / PHI / cifrado de audio / fail-fast de secretos:** ningún cambio de hardening debilita el rol `omnicore_app`, la inyección de `tenant_id`, el cifrado de audio en reposo ni los `_require_strong_secret`.
- **CPU-only compartida:** los límites de recursos **NO** pueden estrangular STT (faster-whisper) ni IA (Ollama) — riesgo real y crítico de esta fase (R-103), validado por THOR.

---

## 2. Alcance IN / OUT

### IN — entra en el Entregable de hardening (Fase C)

1. **H-1/H-6 · Contenedores + Dockerfile de producción:** imagen de producción (usuario no-root, sin `--reload`, sin código de test ni bind-mount de desarrollo — multi-stage o target separado); en `docker-compose.yml`: `mem_limit`/`cpus`/`pids_limit` por servicio (validados por THOR), `security_opt: no-new-privileges`, `cap_drop` donde sea viable, `read_only` donde no rompa escritura legítima (p. ej. `audio_store`).
2. **H-2 · Rate-limiting GENERAL de API** por IP/endpoint, self-hosted sobre el Redis ya presente (p. ej. `slowapi` + backend Redis o equivalente), cubriendo webhooks públicos (WhatsApp/PBX) y endpoints REST; respuesta **429** controlada; sin degradar tráfico legítimo (latencia validada por THOR). **No sustituye** al `LoginRateLimiter` existente: lo complementa.
3. **H-3 · Escaneo de vulnerabilidades en CI (gate BLOQUEANTE HIGH/CRITICAL):** `pip-audit` (backend), `npm audit`/equivalente (frontend), `bandit` (SAST Python), integrados en los workflows **sin romper** los gates existentes (lint/test/cobertura/egress); `.github/dependabot.yml` nuevo. `requirements.txt` sigue 100% pinneado con `==`.
4. **H-4/D-2 · Firewall de host + restricción de puertos:** script versionado (`scripts/ops/` o similar) de firewall `nftables` con DROP de egress de IA + restricción de puertos; en `docker-compose.yml`, `db`/`redis`/`api` dejan de publicarse a `0.0.0.0` (loopback/interfaz interna, patrón `ia`/observabilidad). `check-externos-backend.sh` sigue verde; `ia_internal` se **refuerza**.
5. **D-1 · Coherencia HSTS/CSP + H-5 · TLS de producción:** resolver la divergencia HSTS/CSP con criterio de seguridad (§11.2) estableciendo una única fuente de verdad; config TLS de producción de Caddy parametrizada por dominio/env (ACME/Let's Encrypt), lista para activarse cuando haya dominio real, sin secretos en el repo (C3).
6. **Pruebas + seguridad + no-regresión + docs** (HAWKEYE/BLACK WIDOW/WOLVERINE/QUICKSILVER): rate-limit 429, contenedor no-root, headers coherentes emitidos, escaneo que **falla** ante una dependencia vulnerable sembrada; **CERO regresión** de fail-fast de secretos, RLS cross-tenant, CORS, egress, cifrado de audio y fases #1–#10; `DEPLOYMENT_CHECKLIST.md` con los checkboxes abordados convertidos en artefactos reales referenciados.

### OUT — NO entra en este slice (ya decidido por el Lead o fase futura)

- **Runbook operativo / rotación de secretos reproducible** (Q2=A): `RUNBOOK.md` se deja como está; solo se **referencian** los artefactos nuevos en `DEPLOYMENT_CHECKLIST.md`.
- **CD / pipeline de deploy automatizado / entorno de staging / servidor de producción dedicado** (Q3=A): el deploy sigue manual sobre el `docker-compose` actual.
- **Backups automatizados** (Q6=A, PLAN-010 §13): **DIFERIDOS**, no se retoman ni se mencionan como entregable.
- **Reimplementar la seguridad de aplicación YA hecha** (§1.4): fail-fast de secretos, RLS, CORS, security headers (salvo la coherencia D-1), cifrado de audio, egress acotado. Se **refuerzan**, no se rediseñan.
- **Inventar un marco de compliance formal** (SOC2/ISO/HIPAA/PCI) (Q5-sub): "buenas prácticas de seguridad", sin certificación.
- **SaaS externo de pago** (WAF cloud, secret manager SaaS, escáner SaaS de pago): todo self-hosted / herramientas de CI gratuitas (ADR-005).
- **Nuevas funcionalidades de negocio / canales** (Instagram DM = Fase 4, siguiente).
- **Relajar cualquier invariante** (RLS, `omnicore_app`, aislamiento `ia_internal`, `check-externos-backend.sh`, PHI, fail-fast de secretos): el hardening solo REFUERZA.

---

## 3. Arquitectura de referencia

### 3.1 Dos planos distintos (NO confundir) — el eje de toda la fase

```
PLANO CI (runner de GitHub, CON egress a internet)        PLANO RUNTIME on-prem (host CPU-only, aislado)
---------------------------------------------------        -----------------------------------------------
pip-audit / bandit / npm audit consultan bases de           NUNCA consultan CVEs online; el host NO tiene
datos de CVEs ONLINE  → requieren egress (lo tienen)        egress de IA (ia_internal internal:true + firewall
Dependabot abre PRs                                        nftables DROP). check-externos-backend.sh sigue
gate BLOQUEANTE HIGH/CRITICAL                              siendo sobre el CÓDIGO/RUNTIME, no sobre el CI.
```

**Confundir estos planos es el error más peligroso de la fase:** el escaneo de vulnerabilidades (H-3) vive **solo** en el CI; el firewall/aislamiento (H-4) vive **solo** en el runtime. Ninguno cruza al otro. `check-externos-backend.sh` audita el runtime/código, no el runner de CI.

### 3.2 Contenedores: imagen de producción vs desarrollo (H-1/H-6)

```
DESARROLLO (hoy, se conserva para dev local)     PRODUCCIÓN (nuevo, objetivo de la fase)
--------------------------------------------      --------------------------------------
Dockerfile con --reload, COPY . ., bind-mount     usuario NO-root; sin --reload; sin código de
root; sin límites de recursos                     test ni .env; sin bind-mount; multi-stage/target
                                                  mem_limit/cpus/pids_limit (THOR valida que NO
                                                  asfixian STT/IA); no-new-privileges; cap_drop;
                                                  read_only donde no rompa escritura (audio_store rw)
```

> **Guardarraíl de THOR (R-103, crítico):** los `mem_limit`/`cpus` del servicio `api`, `stt_worker` e `ia` (Ollama) deben dimensionarse para **NO** degradar STT (faster-whisper, RTF vs RNF-42) ni IA (latencia RAG p95 vs RNF-04) en la máquina CPU-only compartida. Los límites de los workers de IA/STT serán **generosos o ausentes** donde el riesgo de asfixia supere el beneficio de hardening; los servicios ligeros (api stateless, redis, caddy, observabilidad) se acotan con holgura. THOR fija los valores concretos en la SPEC; sin su visto bueno no se fijan límites a STT/IA.

### 3.3 Red y puertos: restringir la exposición al host (H-4/D-2)

```
HOY                                      OBJETIVO
db   : "5432:5432"  (0.0.0.0)            db   : solo red Docker interna (sin ports: al host, o 127.0.0.1)
redis: "6379:6379"  (0.0.0.0)            redis: solo red Docker interna (sin ports: al host, o 127.0.0.1)
api  : "8000:8000"  (0.0.0.0)            api  : 127.0.0.1:8000 (solo tras reverse-proxy/loopback)
ia   : "127.0.0.1:11434:11434"  ✓        ia   : se mantiene (ya correcto) — patrón a imitar
obs. : sin ports: (PLAN-010)   ✓         obs. : se mantiene
```

Complementado por un **script de firewall `nftables` del host** (versionado) que: (a) DROP de egress de IA a internet (refuerza `ia_internal`), (b) restringe los puertos expuestos. El script **no se aplica automáticamente** en el repo (C6: aplicarlo en un entorno real es cambio sensible → aprobación + notificación); se entrega versionado + documentado.

### 3.4 Rate-limiting: dos capas, no una (H-2)

```
CAPA 1 (existente, se conserva): LoginRateLimiter — por intentos fallidos de login (SPEC-013)
CAPA 2 (nueva, esta fase):        rate-limit GENERAL por IP/endpoint sobre Redis ya presente
                                  → webhooks públicos (WhatsApp/PBX), endpoints REST, /rag/draft
                                  → 429 controlado; tráfico legítimo intacto (THOR valida latencia)
```

**Cuidado con los webhooks:** WhatsApp/PBX pueden emitir ráfagas legítimas; el límite debe ser por IP/endpoint con umbrales que no descarten entregas válidas (R-105). El rate-limit NUNCA rechaza antes de la validación de firma HMAC de forma que rompa la idempotencia (ADR-007); se coordina con el ACK rápido del webhook.

### 3.5 Por qué NO hay egress nuevo en runtime (y qué ADR sí se justifica)

- El escaneo de vulnerabilidades (H-3) corre **en el CI** (runner con egress), no en el runtime → no introduce egress en el host on-prem. No requiere ADR de egress.
- El firewall de host (H-4) **reduce** egress (DROP de IA), no lo amplía → refuerza ADR-005, no lo contradice. **Pero** la política de firewall de host es un **contrato de seguridad estructural nuevo** (qué se bloquea/permite a nivel de host, por encima del aislamiento de red de Docker) → se recomienda **un ADR acotado** que lo fije como invariante auditable (§11.1).
- El TLS de producción (H-5) no cambia la topología de egress (Caddy ya es el borde entrante); ACME requiere egress a Let's Encrypt **solo cuando se active con dominio real** — se documenta como borde entrante/validación ACME acotado, no un egress de datos; no exige ADR de egress de datos (se nota en el ADR de firewall si procede).

---

## 4. Fases y entregables

| Fase | Nombre | Entregables clave | SPEC (propuesta) |
|------|--------|-------------------|------------------|
| **F0** | **Contenedores + Dockerfile de producción (H-1/H-6)** | Imagen de producción (usuario no-root, sin `--reload`, sin tests/`.env`, sin bind-mount — multi-stage/target); en `docker-compose.yml`: `mem_limit`/`cpus`/`pids_limit` (THOR valida STT/IA, R-103), `no-new-privileges`, `cap_drop`, `read_only` donde no rompa escritura; imagen de desarrollo conservada. | **SPEC-080** |
| **F1** | **Rate-limiting GENERAL de API (H-2)** | Middleware/dependencia de rate-limit por IP/endpoint sobre Redis existente (`slowapi` o equivalente, pinneado `==`); cobertura de webhooks públicos (WhatsApp/PBX) + REST + `/rag/draft`; **429** controlado; coexiste con `LoginRateLimiter`; umbrales que no descartan ráfagas legítimas; latencia validada por THOR. | **SPEC-081** |
| **F2** | **Escaneo de vulnerabilidades en CI + Dependabot (H-3)** | `pip-audit` (backend) + `bandit` (SAST) en `backend-ci.yml`, `npm audit`/equivalente en `ci.yml`, **gate BLOQUEANTE HIGH/CRITICAL** sin romper gates existentes; `.github/dependabot.yml` nuevo; `requirements.txt` sigue 100% `==`; escaneo corre en el **runner de CI** (plano CI, §3.1). | **SPEC-082** |
| **F3** | **Firewall de host + puertos + coherencia TLS/headers (H-4/D-2/D-1/H-5)** | Script `nftables` versionado (DROP egress IA + restricción de puertos) + doc de aplicación; `db`/`redis`/`api` dejan de publicarse a `0.0.0.0`; resolución D-1 (HSTS/CSP, §11.2) con fuente de verdad única; config TLS de producción de Caddy (ACME/dominio por env, sin secretos en repo); **ADR de política de firewall** (§11.1). | **SPEC-083** |
| **F4** | **Pruebas + seguridad + no-regresión + docs (cierra PLAN-011)** | Pruebas: 429, no-root, headers coherentes, escaneo que falla ante vuln sembrada (HAWKEYE); auditoría de que ningún endurecimiento relaja una invariante (BLACK WIDOW); **CERO regresión** de fail-fast secretos/RLS cross-tenant/CORS/egress/cifrado audio/#1–#10 (`check-externos-backend.sh` verde); `DEPLOYMENT_CHECKLIST.md` con checkboxes → artefactos reales referenciados. | **SPEC-084** |

> **Nota de división (criterio de arquitecto):** la división sigue las fronteras naturales que el prompt sugirió — (F0) contenedores+Dockerfile de producción, (F1) rate-limiting general, (F2) escaneo de vulnerabilidades en CI, (F3) firewall+puertos+coherencia TLS/headers (agrupadas porque todas tocan la frontera host/red/transporte y comparten el ADR de firewall), (F4) pruebas+seguridad+no-regresión+docs (patrón SPEC-079). Recomendación firme = **5 SPECs**. Ajustes posibles si el Lead lo prefiere (§8): separar D-1/TLS de F3 en SPEC propia → 6 SPECs; o fusionar F0+F1 → 4 SPECs.

---

## 5. Dependencias entre fases y ruta crítica

- **F0 (SPEC-080 — contenedores/Dockerfile prod)** es la base física del endurecimiento; no depende de fases previas de este plan. Toca `Dockerfile` y `docker-compose.yml` (recursos/capabilities).
- **F1 (SPEC-081 — rate-limiting)** es independiente de F0 a nivel de código de app, pero comparte la validación de latencia de THOR; puede correr en paralelo. Depende del Redis existente, no de F0.
- **F2 (SPEC-082 — escaneo CI)** es independiente de F0/F1 (toca solo workflows + `dependabot.yml`); puede correr en paralelo. Único acople: si F1 añade `slowapi`, el escaneo de F2 lo cubrirá.
- **F3 (SPEC-083 — firewall/puertos/TLS/headers)** toca `docker-compose.yml` (`ports:`) igual que F0 (recursos) → **coordinar la edición de `docker-compose.yml`** para evitar conflicto; produce el ADR de firewall. Depende conceptualmente de F0 (misma superficie de infra).
- **F4 (SPEC-084 — pruebas/seguridad/no-regresión/docs)** depende de F0/F1/F2/F3 (prueba el conjunto y cierra el plan).

**Ruta crítica:** `F0 → F3 → F4` (ambas tocan `docker-compose.yml`; F3 cierra la superficie de infra). `F1` y `F2` corren en paralelo y convergen en `F4`. El mayor riesgo se concentra en **F0/F3** (asfixia de STT/IA por límites; abrir/cerrar puertos; relajar aislamiento) y en **F1** (romper webhooks legítimos).

---

## 6. Riesgos y mitigaciones (R-103..R-109 — continúan tras R-102 de PLAN-010)

| # | Riesgo | Impacto | Mitigación |
|---|--------|---------|------------|
| **R-103** | **Los límites de recursos (`mem_limit`/`cpus`) estrangulan STT (faster-whisper) o IA (Ollama)** en la máquina CPU-only compartida → RTF/latencia degradados, timeouts, cola STT creciente. | **Crítico** (rompe el servicio) | **THOR es puerta previa dura** para los límites de `api`/`stt_worker`/`ia`: se dimensionan con evidencia (RTF vs RNF-42, p95 RAG vs RNF-04); límites **generosos o ausentes** donde la asfixia supere el beneficio; el hardening de recursos prioriza servicios ligeros (redis/caddy/api stateless). Sin visto bueno de THOR no se fijan límites a STT/IA (CE-104). |
| **R-104** | **Un contenedor no-root / `read_only` / `cap_drop` rompe una escritura legítima** (p. ej. `audio_store` cifrado, modelos, `/tmp`, logs) o un `chmod`/`init_audio_store.sh` que asume root. | **Alto** (rompe #4/#5/#6) | Mapear escrituras legítimas (volúmenes `audio_store`, modelos, tmpfs) y mantenerlas `rw`; usuario no-root con ownership correcto de esos paths; `read_only` solo donde no haya escritura; suites #4/#5/#6 verdes (CE-105). |
| **R-105** | **El rate-limiting general descarta tráfico legítimo** (ráfaga de webhooks WhatsApp/PBX válidos, o un agente humano activo) → mensajes perdidos, 429 a Meta/PBX, pérdida de idempotencia. | **Alto** (pérdida de datos/entregas) | Umbrales por IP/endpoint calibrados para ráfagas legítimas; el límite no rompe el ACK rápido ni la validación de firma HMAC/idempotencia (ADR-007); exenciones/holgura para webhooks; prueba de que tráfico legítimo NO recibe 429 (THOR latencia + HAWKEYE) (CE-106). |
| **R-106** | **Confusión plano CI ↔ plano runtime:** el escaneo de CVEs online se interpreta como egress del host, o `check-externos-backend.sh` se "ajusta" para tolerar el egress del escáner → regresión del guardarraíl. | **Alto** (viola ADR-005, falsea el guardarraíl) | §3.1 explícita: escaneo SOLO en el runner de CI (con egress); `check-externos-backend.sh` sigue auditando el **código/runtime**, NO el CI, y NO se relaja su allowlist; Dependabot/pip-audit viven en `.github/`, nunca en el runtime (CE-107). |
| **R-107** | **El gate de escaneo BLOQUEANTE se vuelve inmanejable** (una CVE HIGH/CRITICAL sin fix disponible bloquea todo el CI, incluidas ramas no relacionadas) → presión para desactivarlo. | **Medio** (fricción operativa → riesgo de relajar) | Gate bloqueante en HIGH/CRITICAL (Q5=A) con mecanismo **auditable y acotado** de excepción temporal documentada (allowlist de CVE con justificación + fecha de revisión, NO desactivación global); nunca se silencia una CVE sin registro. Decisión de excepción = del Lead, no del agente (CE-108). |
| **R-108** | **Restringir `ports:` de `db`/`redis`/`api` rompe el acceso legítimo** (healthchecks, migraciones, herramientas de operación que hoy asumen `localhost:5432`/`:6379`/`:8000`). | **Alto** (rompe operación/CI) | Verificar que healthchecks (ya por red Docker interna) y migraciones siguen funcionando; `api` tras loopback/reverse-proxy; documentar el nuevo modo de acceso en `DEPLOYMENT_CHECKLIST.md`; suites/healthchecks verdes (CE-109). |
| **R-109** | **Endurecer HSTS/CSP (D-1) rompe Swagger `/docs`** (quitar `'unsafe-inline'` deja la UI de Swagger sin estilos/JS) o aplica HSTS de 1 año sobre HTTP de desarrollo. | **Medio** (rompe `/docs` / fuerza HTTPS indebido) | Resolución D-1 (§11.2): CSP estricta global + excepción acotada SOLO para `/docs`/`/redoc` (o deshabilitar Swagger en producción); HSTS `max-age=31536000` como valor de producción, inocuo en dev (el navegador solo lo respeta sobre HTTPS). Prueba de que `/docs` sigue usable y el resto va estricto (CE-110). |

**Top-3:** **R-103 (asfixia de STT/IA por límites de recursos — crítico, puerta de THOR)**, **R-105 (rate-limiting descarta webhooks legítimos)**, **R-106 (confusión plano CI ↔ runtime / relajar el guardarraíl de egress)**. R-104 (escritura rota por no-root/read_only) inmediatamente detrás.

---

## 7. Criterios de éxito verificables (CE-104..CE-113 — continúan tras CE-103 de PLAN-010)

| ID | Criterio | Cómo se verifica | Fase |
|----|----------|------------------|------|
| **CE-104** | **Contenedor no-root + sin `--reload` + límites que NO asfixian STT/IA:** `api`/workers corren como usuario no-root; sin `--reload` en producción; `mem_limit`/`cpus` con visto bueno de THOR (RTF vs RNF-42, p95 RAG vs RNF-04). | `docker exec ... whoami` ≠ root; inspección del `CMD`/compose; informe de THOR de RTF/latencia bajo límites. | F0 |
| **CE-105** | **Capabilities/read-only sin romper escrituras legítimas:** `no-new-privileges` y `cap_drop` aplicados donde viable; escrituras a `audio_store`/modelos/tmp intactas. | Inspección de compose; suites #4/#5/#6 verdes; arranque y escritura de audio cifrado OK. | F0 |
| **CE-106** | **Rate-limit general dispara 429 sin dañar tráfico legítimo:** exceder el límite por IP/endpoint → 429; ráfaga de webhooks/REST legítimos NO recibe 429; latencia legítima intacta (THOR). | Prueba controlada de exceso → 429; prueba de ráfaga legítima → sin 429; coexiste con `LoginRateLimiter`. | F1 |
| **CE-107** | **Escaneo BLOQUEANTE en CI (plano CI) sin tocar el guardarraíl de runtime:** `pip-audit`+`bandit`+`npm audit` corren en el runner; una dependencia vulnerable **sembrada** hace **fallar** el gate; Dependabot activo; `check-externos-backend.sh` sigue verde sin relajar allowlist; `requirements.txt` 100% `==`. | PR con dep vulnerable → CI rojo; `.github/dependabot.yml` presente; `check-externos-backend.sh` verde; grep de `==` en requirements. | F2 |
| **CE-108** | **Excepción de CVE auditable (no desactivación global):** si una CVE HIGH/CRITICAL sin fix bloquea, existe un mecanismo documentado de allowlist acotada con justificación y fecha, nunca silenciado sin registro. | Inspección del config del escáner; la excepción (si existe) está versionada y justificada. | F2 |
| **CE-109** | **Puertos restringidos sin romper operación:** `db`/`redis` sin `ports:` a `0.0.0.0` (solo red Docker/loopback); `api` tras loopback/reverse-proxy; healthchecks y migraciones verdes. | Inspección de `docker-compose.yml`; healthchecks healthy; migraciones OK; nmap/ss del host sin `5432`/`6379` en `0.0.0.0`. | F3 |
| **CE-110** | **Coherencia HSTS/CSP (D-1) con fuente de verdad única:** `security_headers.py` y `DEPLOYMENT_CHECKLIST.md` coinciden; CSP estricta global con excepción acotada para `/docs` (o Swagger off en prod); HSTS de producción documentado. | Inspección de ambos artefactos; `/docs` sigue usable; el resto va estricto; sin secretos en repo. | F3 |
| **CE-111** | **Firewall de host versionado + TLS de producción parametrizado:** script `nftables` (DROP egress IA + restricción de puertos) versionado + doc; config TLS/ACME de Caddy por dominio/env, sin secretos en el repo (C3); `ia_internal` reforzado. | Script presente y documentado; Caddyfile con ACME/dominio por env; `check-externos-backend.sh` verde; ADR de firewall presente. | F3 |
| **CE-112** | **CERO regresión de la seguridad de aplicación:** fail-fast de secretos, RLS cross-tenant, CORS, egress, cifrado de audio y fases #1–#10 verdes sin modificar asserts. | Suite completa + `test_rls_isolation`/`test_auth_cross_tenant_rls`/`test_config_and_cors` verdes; `check-externos-backend.sh` verde. | F4 |
| **CE-113** | **Checkboxes del checklist → artefactos reales:** los ítems de `DEPLOYMENT_CHECKLIST.md` abordados (firewall, puertos, TLS, headers, escaneo) referencian un artefacto real versionado, no instrucciones de copiar/pegar. | Inspección de `DEPLOYMENT_CHECKLIST.md`: cada ítem abordado apunta a un archivo real del repo. | F4 |

> Transversales heredados: **aprobación explícita del Lead**; CHECKPOINTS **C3** (secretos: credenciales de TLS/firewall/escaneo por env, nunca hardcodeadas ni generadas por el agente, nunca en logs — crítico aquí) / **C4** (criterios verificables, §5 del prompt) / **C6** (aplicar firewall de host, cambiar `ports:`, o endurecer contenedores en el entorno real = cambio sensible → **aprobación del Lead + notificación** antes de desplegar) / **C8** (origen `prompt-lab/prompts/PROMPT-011-HARDENING-PRODUCCION.md`). **No existe C9.**

---

## 8. Mapa de SPECs propuestas (SOLO el mapa — se redactan como PROPUESTA, se implementan tras "APROBADO PLAN-011")

> Continúa desde `specs.json` (`next_spec: 80`). Se crearán únicamente tras "APROBADO PLAN-011". Cada SPEC llevará criterios verificables (C4), clasificación SENSIBLE, dependencias y checkpoints citados.

- **SPEC-080** — Contenedores + Dockerfile de producción: imagen no-root sin `--reload`/tests/bind-mount (multi-stage/target); `mem_limit`/`cpus`/`pids_limit` (THOR valida que NO asfixian STT/IA, R-103), `no-new-privileges`, `cap_drop`, `read_only` donde no rompa escritura; imagen de desarrollo conservada (F0).
- **SPEC-081** — Rate-limiting GENERAL de API por IP/endpoint sobre Redis existente (`slowapi` o equivalente, pinneado): webhooks públicos (WhatsApp/PBX) + REST + `/rag/draft`, 429 controlado, coexiste con `LoginRateLimiter`, sin descartar ráfagas legítimas (latencia THOR) (F1).
- **SPEC-082** — Escaneo de vulnerabilidades en CI (gate BLOQUEANTE HIGH/CRITICAL): `pip-audit`+`bandit` en `backend-ci.yml`, `npm audit` en `ci.yml`, `.github/dependabot.yml`, excepción de CVE auditable; corre en el runner de CI (plano CI); `requirements.txt` 100% `==` (F2).
- **SPEC-083** — Firewall de host `nftables` versionado (DROP egress IA + restricción de puertos) + `db`/`redis`/`api` sin `ports:` a `0.0.0.0`; coherencia HSTS/CSP (D-1, §11.2) con fuente única; TLS de producción de Caddy (ACME/dominio por env); ADR de política de firewall (F3).
- **SPEC-084** — Pruebas + seguridad + no-regresión + docs (cierra PLAN-011): 429, no-root, headers coherentes, escaneo que falla ante vuln sembrada; auditoría de no-relajación de invariantes; cero regresión #1–#10 + `check-externos-backend.sh` verde; `DEPLOYMENT_CHECKLIST.md` con checkboxes → artefactos reales (F4).

> Total: **5 SPECs (SPEC-080..SPEC-084)** → `next_spec` pasaría a **85** al crearlas (no ahora). **Un ADR recomendado** (§11.1) → `next_adr` pasaría a **17** al crearlo. Opciones de ajuste si el Lead lo prefiere: (a) separar D-1/TLS de SPEC-083 en SPEC propia → 6 SPECs; (b) fusionar F0+F1 → 4 SPECs. Recomendación firme = **5 SPECs + 1 ADR**.

---

## 9. Entregables finales de la fase

- **Imagen de producción** (no-root, sin `--reload`/tests/bind-mount) + `docker-compose.yml` endurecido (recursos validados por THOR, `no-new-privileges`, `cap_drop`, `ports:` restringidos).
- **Rate-limiting general** por IP/endpoint sobre Redis existente, 429 controlado, coexistiendo con el de login.
- **CI con escaneo de vulnerabilidades BLOQUEANTE** (`pip-audit`/`bandit`/`npm audit`) + `.github/dependabot.yml`.
- **Script de firewall `nftables` versionado** (DROP egress IA + puertos) + doc + **ADR de política de firewall**.
- **Coherencia HSTS/CSP** resuelta (fuente única) + **config TLS de producción** de Caddy parametrizada por dominio/env (sin secretos en repo).
- **Suite de pruebas** (429, no-root, headers, escaneo que falla, cero regresión #1–#10) + `DEPLOYMENT_CHECKLIST.md` con checkboxes → artefactos reales.
- **Evidencia auditable:** contenedor no-root, 429 funcional, CI rojo ante vuln sembrada, puertos cerrados en el host, `check-externos-backend.sh` verde, cero secretos en repo/logs.

## 10. Definition of Done (fase de hardening)

1. CE-104..CE-113 cumplidos y evidenciados.
2. **Contenedores endurecidos:** imagen de producción no-root, sin `--reload`; límites de recursos con visto bueno de THOR que NO degradan STT/IA (R-103); `no-new-privileges`/`cap_drop` sin romper escrituras legítimas.
3. **Rate-limiting general operativo:** 429 por IP/endpoint; tráfico legítimo (webhooks/REST) intacto; coexiste con `LoginRateLimiter`.
4. **Escaneo BLOQUEANTE en CI:** `pip-audit`/`bandit`/`npm audit` fallan ante HIGH/CRITICAL; Dependabot activo; excepción de CVE auditable; escaneo en plano CI, nunca en runtime.
5. **Puertos/firewall endurecidos:** `db`/`redis`/`api` sin exposición a `0.0.0.0`; script `nftables` versionado + documentado; `ia_internal` reforzado; `check-externos-backend.sh` verde sin relajar allowlist.
6. **Coherencia TLS/headers:** HSTS/CSP con fuente de verdad única; `/docs` usable con CSP estricta (o Swagger off en prod); TLS de producción de Caddy parametrizado por env, sin secretos en repo (C3).
7. **Secretos seguros (C3):** toda credencial de TLS/firewall/escaneo por env, cero hardcodeadas, cero generadas por el agente, cero en logs.
8. **CERO regresión:** fail-fast de secretos, RLS cross-tenant, CORS, egress, cifrado de audio y fases #1–#10 verdes sin modificar asserts.
9. **Checkboxes → artefactos reales** en `DEPLOYMENT_CHECKLIST.md`; `RUNBOOK.md` NO se reescribe (Q2=A), solo se referencian los artefactos nuevos.
10. **Backups DIFERIDOS** (Q6=A) no retomados; CD/staging (Q3=A) fuera; runbook operativo (Q2=A) sin tocar.
11. **ADR de política de firewall** creado (§11.1); **aprobación explícita del Lead**; aplicar firewall/puertos/contenedores endurecidos en el entorno real = cambio sensible → **aprobación del Lead + notificación** (C6); ninguna SPEC se cierra sin cumplir los CHECKPOINTS aplicables (C3/C4/C6/C8).

---

## 11. ADRs: un ADR recomendado (política de firewall de host) + resolución de D-1

### 11.1 ADR recomendado: política de firewall de host como contrato de seguridad (candidato ADR-016)

> **DECISIÓN: esta fase recomienda crear UN ADR acotado** para la **política de firewall de host** (candidato `ADR-016`). `next_adr` pasaría de 16 a 17 **al crearlo tras "APROBADO PLAN-011"** (no ahora).

Justificación (criterio de arquitecto, consistente con el prompt "SOLO si una decisión introduce una excepción de arquitectura genuina"):

- **Sí merece ADR** porque el firewall de host introduce un **segundo plano de control de egress/exposición** que vive **por encima** del aislamiento de red de Docker (`ia_internal internal:true`, ADR-005). Hasta ahora la garantía de "cero externos" se apoyaba en la red de Docker + `check-externos-backend.sh`; añadir un firewall de host (`nftables` DROP de egress de IA + restricción de puertos del host) crea un **contrato de seguridad estructural y duradero** —qué se bloquea/permite a nivel de kernel del host, independiente de Docker— que futuros cambios no deben erosionar. Es exactamente el tipo de decisión que ADR-005/006/010 fijan para el egress: merece su propio registro auditable, trazable y referenciable.
- **No es "solo un detalle de implementación de una SPEC"** porque su alcance trasciende la SPEC-083: define una invariante (el host NO permite egress de IA ni expone `db`/`redis` a internet) que condiciona todo despliegue futuro y que BLACK WIDOW debe poder citar como contrato. Un script sin ADR sería un artefacto frágil sin la fuerza normativa del resto de decisiones de egress.
- **Lo que el ADR fija:** relación firewall de host ↔ `ia_internal` (defensa en profundidad, no sustitución), puertos permitidos/denegados, que el script NO se aplica automáticamente (C6), y que ACME/TLS entrante (validación Let's Encrypt cuando haya dominio) es un borde entrante acotado, no un egress de datos. **No** es un ADR de egress nuevo (el firewall REDUCE egress); es un ADR de **contrato de hardening de host**.

> Los demás huecos (contenedores no-root, rate-limiting, escaneo CI, coherencia D-1) son **detalles de implementación dentro de decisiones ya fijadas** (hardening estándar, buenas prácticas) y **NO** justifican ADR propio. Se recomienda **un solo ADR** (firewall de host), no más.

### 11.2 Resolución de D-1 (coherencia HSTS/CSP) — decisión de arquitecto, NO se pregunta al Lead

> **Ambigüedad genuina dentro de una decisión ya vinculante (Q1=A incluye D-1).** La resuelvo yo como arquitecto, con criterio de seguridad, documentando la justificación (como se hizo con `platform_admins` en ADR-015 y la invariante de métricas en PLAN-010 §3.3). **No genero una pregunta nueva para el Lead.**

**Fuente de verdad correcta: el `DEPLOYMENT_CHECKLIST.md` (el valor MÁS ESTRICTO), no el código actual.** Se **endurece `security_headers.py`** para igualar el checklist, resolviendo el conflicto con Swagger mediante excepción acotada:

1. **HSTS → `max-age=31536000; includeSubDomains`** (1 año, el valor del checklist). El valor de 180 días del código es conservador sin razón de seguridad; 1 año es el estándar recomendado y es **inocuo en desarrollo** (el navegador solo respeta HSTS sobre respuestas HTTPS; en HTTP plano de dev no tiene efecto). No se añade `preload` (requiere registro manual en navegadores, fuera de alcance; se nota como endurecimiento futuro).
2. **CSP → estricta global (`default-src 'self'` sin `'unsafe-inline'`)**, con **excepción acotada únicamente para `/docs`/`/redoc`**. El `'unsafe-inline'` existe hoy SOLO para que Swagger UI (que inyecta estilos/JS inline) funcione. La solución correcta es **no relajar la CSP de toda la API por culpa de dos rutas de documentación**: se aplica CSP estricta a todas las respuestas y, para `/docs`/`/redoc`, o bien (a) se sirve una CSP específica que permita lo mínimo que Swagger necesita (idealmente con `nonce`/`hash` en vez de `'unsafe-inline'` global), o bien (b) **se deshabilita Swagger en producción** (`docs_url=None`/`redoc_url=None` fuera de `development`), que es además una buena práctica de reducción de superficie para un backend con PHI. **Recomendación: ambas** — Swagger OFF en producción (reduce superficie) y, mientras esté ON en dev, CSP relajada acotada solo a esas rutas. Así el resto de la API (incluido `/api/*`, `/metrics`) va con CSP estricta sin `'unsafe-inline'`.
3. **Actualización de la coherencia:** tras endurecer el código, `DEPLOYMENT_CHECKLIST.md` y `security_headers.py` quedan alineados; el docstring de `security_headers.py` se actualiza para reflejar la excepción acotada de `/docs`. Una única fuente de verdad: **el código endurecido = el checklist**.

**Por qué esta dirección y no "relajar el checklist":** en una fase de *hardening* para un backend con PHI, la resolución correcta de una divergencia doc↔código es **subir el código al nivel más estricto**, no bajar la documentación. Relajar el checklist sería una regresión de postura de seguridad disfrazada de "coherencia". El coste (Swagger) se absorbe con una excepción quirúrgica o deshabilitándolo en producción, sin sacrificar la CSP del resto de la API.

> Validación asociada: **R-109/CE-110** — prueba de que `/docs` sigue usable (en dev) y el resto de rutas emiten CSP estricta sin `'unsafe-inline'`, con HSTS de 1 año.

---

## 12. PREGUNTAS ABIERTAS AL LEAD

**Ninguna de alcance.** Las seis decisiones Q1–Q6 están resueltas y adoptadas como vinculantes (prompt §7.1). Las ambigüedades internas (D-1, división de SPECs, necesidad de ADR) las he resuelto yo como arquitecto (§11). Puntos que se fijan en la SPEC con supuesto por defecto, confirmables en la aprobación (NO bloquean el PLAN):

1. **Valores concretos de `mem_limit`/`cpus`:** los dimensiona THOR con evidencia en SPEC-080 (puerta dura R-103). *El Lead puede ajustar el techo de hardening de recursos de STT/IA al aprobar.*
2. **Umbrales del rate-limit general** (req/min por IP/endpoint, holgura de webhooks): candidatos en SPEC-081, calibrados para ráfagas legítimas. *El Lead puede ajustar umbrales.*
3. **Swagger en producción ON/OFF** (parte de la resolución D-1, §11.2): recomendación = OFF en producción + CSP estricta. *Confirmable al aprobar; no cambia el alcance.*
4. **Número de SPECs:** recomendación = **5** (SPEC-080..084) + **1 ADR** (firewall). *Opcional: separar D-1/TLS → 6, o fusionar F0+F1 → 4.*

---

> **Siguiente paso:** IRON MAN presenta este PLAN-011 al Lead. El Lead debe responder **"APROBADO PLAN-011"** (o "Ajusta PLAN-011: …") antes de que DOCTOR STRANGE redacte las SPEC-080..SPEC-084 y el ADR de firewall. Dos puertas obligatorias: primero PLAN, luego SPEC. **Backups siguen DIFERIDOS** (Q6=A); **CD/staging** y **runbook operativo** fuera (Q3=A/Q2=A). Cumple CHECKPOINT C8 (origen `prompt-lab/prompts/PROMPT-011-HARDENING-PRODUCCION.md`). `.swarm/specs.json` **NO se actualiza** hasta la aprobación del Lead.
