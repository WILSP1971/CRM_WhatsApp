# PROMPT-011 — Hardening de producción (endurecer el despliegue on-prem existente)

> Autor: 🧠 XAVIER (Professor X) — Estratega de Prompts (Nivel 1) · skill `optimizar-prompt`
> Fecha: 2026-10-02 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo`) — endurecer la superficie de un backend multi-tenant (RLS) con PHI potencial (ADR-009) y egress acotado (ADR-005/006/010). Un endurecimiento mal hecho (romper el aislamiento `ia_internal`, abrir un puerto, relajar un fail-fast de secreto, o un header TLS inconsistente) sería una REGRESIÓN de seguridad, no una mejora.
> Marco aplicado: **C.R.A.F.T.** (Contexto · Rol · Acción · Formato · Tests)
> Destino: este prompt alimenta a 🔮 **DOCTOR STRANGE** para **PLAN-011** (NO genera SPECs por sí mismo).
> Contadores REALES (`.swarm/specs.json`, verificados 2026-10-02): `next_plan: 11`, `next_spec: 80`, `next_adr: 16`. DOCTOR STRANGE reclama `next_plan:11→12` al cerrar PLAN-011; `next_spec`/`next_adr` solo se consumen al crear SPECs/ADRs tras "APROBADO PLAN-011".
> Posición en la secuencia ordenada por el Lead: **Fase C de 4** (1. Onboarding multi-tenant ✅ PLAN-009 · 2. Observabilidad real ✅ PLAN-010 (backups DIFERIDOS) · **3. Hardening de producción ← ESTA** · 4. Instagram DM).
> ⚠️ **Puerta obligatoria:** este prompt NO es aprobación. Requiere PLAN-011 aprobado por el Lead y luego SPECs aprobadas antes de escribir código (CLAUDE.md del enjambre). Además hay **preguntas abiertas VINCULANTES (§7)** que el Lead debe responder antes de que DOCTOR STRANGE fije alcance.

---

## 0. Resumen del encargo (una frase)

Pasar el despliegue on-prem de **"funcionalmente completo y razonablemente seguro a nivel de aplicación"** a **"endurecido a nivel de operación e infraestructura"**: cerrar los huecos de hardening que viven en la **frontera entre el código y el host** — hardening de contenedores (usuario no-root, límites de recursos, capabilities), rate-limiting general de API (hoy solo existe en login), escaneo de vulnerabilidades de dependencias en CI (hoy inexistente), coherencia de los headers TLS/CSP entre lo documentado y lo implementado, y materializar como **entregables reales** los ítems de `DEPLOYMENT_CHECKLIST.md` que hoy son checkboxes `[ ]` sin artefacto (firewall de host, restricción de puertos, TLS de producción).

Esta fase **NO reimplementa la seguridad de aplicación que YA está hecha** (fail-fast de secretos, RLS, CORS endurecido, security headers, cifrado de audio, egress acotado — todo verificado en §1). **Consume lo existente y endurece la capa operativa/infra que lo rodea**, sin romper ninguna invariante ya fijada.

---

## 1. Contexto (verificado en el repo, NO asumido — qué YA está duro vs qué falta)

> Hallazgo central de XAVIER (patrón idéntico al de backups en PLAN-010): **la seguridad de APLICACIÓN está notablemente madura y bien testeada; el hueco real está en la capa INFRA/OPERACIÓN** (host, contenedores, pipeline, y checkboxes del checklist que asumen artefactos que no existen).

### 1.1 Lo que YA está endurecido (NO rehacer — anti-scope duro)

- **Fail-fast de secretos en producción — EXHAUSTIVO** (`backend/app/core/config.py`): `_require_strong_secret()` (líneas 634–672) aborta el arranque fuera de `development` si cualquier secreto falta, está en la **lista negra** de valores débiles/genéricos (`_WEAK_SECRET_VALUES`), o mide `< _MIN_SECRET_LENGTH` (32). Aplica a `JWT_SECRET_KEY`, `DB_PASSWORD`, `DB_APP_PASSWORD`, `AUDIO_ENCRYPTION_KEY`, `WEBHOOK_VERIFY_TOKEN`/`WEBHOOK_SECRET`, `WHATSAPP_*` (condicional). Cubierto por los tests `test_settings_production_*` en `test_config_and_cors.py`. **Esta área está CERRADA — no duplicar.**
- **Defensa en profundidad de egress de IA en la propia app:** `_require_internal_ai_host()` (líneas 609–632) rechaza arrancar si `OLLAMA_BASE_URL` no resuelve a un host interno permitido (`ia`/loopback). Suma al aislamiento de red + `check-externos-backend.sh`.
- **CORS endurecido** (`backend/app/main.py:109–116`): allowlist explícita, nunca `*` + credenciales; fuera de development sin orígenes → CORS deshabilitado (no comodín). Cubierto por tests `test_cors_*`.
- **Security headers — YA IMPLEMENTADOS** (`backend/app/core/security_headers.py`, `SecurityHeadersMiddleware` montado en `main.py:122`): HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CSP (`default-src 'self'`), `Permissions-Policy`. **PERO hay una DIVERGENCIA real vs `DEPLOYMENT_CHECKLIST.md` (§1.3, D-1).**
- **RLS multi-tenant endurecido** (ADR-004/008): rol runtime `omnicore_app` NOSUPERUSER NOBYPASSRLS; migraciones con rol owner separado. **Fuera de alcance (ya hecho).**
- **Aislamiento de red:** `ia_internal` (`internal: true`, sin egress), `app` solo con egress acotado a `graph.facebook.com`; workers de IA/STT sin red `app`. `check-externos-backend.sh` audita egress en CI y es el guardarraíl intocable.
- **Cifrado de audio en reposo** (ADR-009, `AUDIO_ENCRYPTION_KEY` + `cryptography==41.0.7` Fernet). **Fuera de alcance.**
- **Rate-limiting DE LOGIN** (`backend/app/security/rate_limit.py`, `LoginRateLimiter`, SPEC-013): por intentos fallidos, con modo estricto Redis fuera de dev. **Existe SOLO para login/platform-login — ver hueco en §1.2.**

### 1.2 Lo que FALTA (huecos reales de hardming — candidatos de esta fase)

- **H-1 · Hardening de contenedores: AUSENTE por completo.** `grep` sobre `docker-compose.yml` → **CERO** `mem_limit`/`cpus`/`deploy.resources`/`read_only`/`user:`/`cap_drop`/`security_opt`/`no-new-privileges`/`pids_limit`/`ulimits` (ninguno existe). El `backend/Dockerfile` corre como **root** (no hay `USER` no-root; `pip install` y `CMD uvicorn` como root) y arranca con `--reload` (flag de desarrollo). Ningún servicio tiene límites de recursos ni capabilities recortadas. Terreno clásico de hardening, hoy sin tocar.
- **H-2 · Rate-limiting GENERAL de API: AUSENTE.** El único rate-limiting es el de **login** (`LoginRateLimiter`). NO hay `slowapi`/`fastapi-limiter` en `requirements.txt` ni un límite por IP/endpoint para el resto de la API (webhooks, endpoints REST, `/rag/draft`, etc.). Caddy tampoco tiene rate-limiting (su config solo expone `/webhooks/pbx/recordings` y `/voice/ws`).
- **H-3 · Escaneo de vulnerabilidades de dependencias: AUSENTE.** El CI backend (`backend-ci.yml`) corre `black`, `flake8`, `mypy`, `check-externos-backend.sh`, `pytest` + cobertura ≥80%, y smoke de carga — pero **NO** `pip-audit`/`safety`/`bandit`/`trivy`. El CI frontend (`ci.yml`) corre lint/build/test/Lighthouse pero **NO** `npm audit`/`snyk`. **NO existe `.github/dependabot.yml`.** Lado positivo: `requirements.txt` está **100% pinneado con `==`** (39 pins, 0 rangos abiertos) — base sólida para un escaneo reproducible.
- **H-4 · Firewall de host / restricción de puertos: documentado pero SIN artefacto.** `DEPLOYMENT_CHECKLIST.md` (Fase 2, líneas 40–58) pide reglas `iptables`/`nftables` DROP de egress desde Ollama y restricción de puertos `8000/5432/6379/11434`, pero **NO existe ningún script de firewall/hardening de host versionado** (`find` sobre `*firewall*`/`*nftables*`/`*iptables*`/`*hardening*` → vacío). Además, en `docker-compose.yml` `db` publica `5432:5432`, `redis` `6379:6379` y `api` `8000:8000` al host (no restringidos a loopback como sí hace `ia` con `127.0.0.1:11434`). El checklist **asume** un endurecimiento de red que el repo no entrega — mismo patrón que el `backup-crm.sh` fantasma de PLAN-010.
- **H-5 · TLS de producción: solo reverse-proxy, sin automatización de cert.** Caddy (`Caddyfile`) expone solo el webhook del PBX y `/voice/ws`; en producción pide "usar cert válido (Let's Encrypt)" como comentario, pero **no hay bloque `tls`/ACME configurado ni documentación de dominio real**. El tráfico de la API (`/api/*`) NO pasa por Caddy hoy (Caddy solo proxya webhooks) — el checklist (Fase 3) asume que un reverse-proxy termina TLS para la API en :443, lo cual **no está materializado**.
- **H-6 · Dockerfile de producción: inexistente.** Un solo `Dockerfile` con `--reload` y `COPY . .` (incluye tests/`.env` si existiera) + volumen `./backend:/app` montado en runtime (bind-mount de desarrollo). No hay separación de imagen de producción (sin `--reload`, sin código de test, sin bind-mount).

### 1.3 Divergencias/inconsistencias detectadas (candidatas a "coherencia", no solo "añadir")

- **D-1 · HSTS y CSP divergen entre documentación y código.** `DEPLOYMENT_CHECKLIST.md:71,74` pide `Strict-Transport-Security: max-age=31536000` (1 año) y `Content-Security-Policy: default-src 'self'` **sin `unsafe-inline`**. El middleware REAL (`security_headers.py`) usa `max-age=15552000` (180 días) y CSP **con** `'unsafe-inline'` en `style-src`/`script-src` (para no romper Swagger `/docs`). No es un bug de seguridad grave, pero es una incoherencia doc↔código que una fase de hardening debe resolver (¿se endurece el header, o se corrige el checklist? — decisión de alcance).
- **D-2 · Puertos de infra publicados al host sin restricción de interfaz.** `db`/`redis`/`api` publican a `0.0.0.0` (todas las interfaces) mientras el checklist pide que `5432`/`6379` NO se expongan a internet y `8000` solo tras el proxy. Hoy dependen enteramente de que el firewall del host (inexistente como artefacto, H-4) los proteja.

### 1.4 Lo que YA existe de "overhead operativo" (para no duplicar)

- **`RUNBOOK.md` YA tiene** secciones de "Rotación y renovación de secretos", "Respuesta a incidentes comunes" y "Procedimiento de rollback" (texto/procedimientos). Son prosa operativa existente — una fase de hardening podría **extenderlos/endurecerlos** (p. ej. runbook de incidente de seguridad específico, rotación documentada con pasos reproducibles), pero no partir de cero. Esto condiciona Q2.
- **`DEPLOYMENT_CHECKLIST.md` YA es exhaustivo** (7 fases): es el mejor inventario de "lo que debería estar duro en producción". Varios de sus checkboxes son exactamente los huecos H-1..H-5. El entregable natural de esta fase es **convertir esos `[ ]` en artefactos reales + marcarlos**.

### 1.5 Topología e invariantes que rigen esta fase (intocables)

- **100% self-hosted / on-premise, CPU-only**, sin SaaS externo de pago (patrón ADR-005). Todo el hardening debe ser self-hosted (p. ej. `pip-audit`/`trivy` corren en el runner de CI, no un SaaS de pago; firewall con `nftables` del host, no un WAF de pago).
- **Egress acotado y auditado** (`check-externos-backend.sh`): cualquier endurecimiento NO puede introducir egress nuevo ni romper el guardarraíl. Endurecer el firewall debe REFORZAR (no relajar) el aislamiento `ia_internal`. Un escáner de vulnerabilidades que consulte una base de datos de CVEs online corre **en el CI** (runner de GitHub, no en el host on-prem sin egress) — distinguir plano CI vs plano runtime on-prem.
- **RLS / PHI / cifrado de audio:** ningún cambio de hardening puede debilitar el rol `omnicore_app`, la inyección de `tenant_id`, ni el cifrado en reposo.
- **CI sin CD, un solo `docker-compose.yml`, sin staging:** sigue siendo el entorno objetivo (ver Q3). Montar CD/staging es un objetivo potencialmente DENTRO de "hardening" pero de alcance grande — a decidir en Q3, no asumir.

---

## 2. Rol (quién resuelve)

- **🔮 DOCTOR STRANGE** — PLAN-011 + SPECs (dos puertas de aprobación); decide qué huecos entran y en qué fases.
- **🛡️ CAPTAIN AMERICA** — orquestación de la implementación / decisiones de integración en `docker-compose`/`Dockerfile`.
- **🕷️ BLACK WIDOW** — **líder natural de esta fase**: hardening de contenedores/capabilities, rate-limiting como control anti-abuso, coherencia de headers TLS/CSP, firewall de host, revisión de que ningún endurecimiento relaje una invariante (RLS/egress/secretos/PHI).
- **🐾 BLACK PANTHER** — backend/infra: rate-limiting general (middleware/dependencia), Dockerfile de producción (usuario no-root, multi-stage), límites de recursos en compose, script de firewall del host.
- **🩹 WOLVERINE** — calidad/CI: integrar `pip-audit`/`bandit`/`npm audit`/Dependabot en los workflows sin romper los gates existentes (lint/test/cobertura/egress); que todo quede como código versionado.
- **🦅 HAWKEYE** — pruebas: que el rate-limiting dispara (429 controlado), que los headers nuevos se emiten, que el contenedor arranca como no-root, que el escaneo de vulns falla ante una dependencia vulnerable sembrada.
- **⚡ THOR** — consultor de performance: que los `mem_limit`/`cpus` no estrangulen STT/IA en la máquina CPU-only de 4 vCPU compartida (R-84); que el rate-limiting no degrade latencia legítima.
- **⚡ QUICKSILVER** — deploy/operación: runbook de incidentes/rotación (si entra, Q2), materializar el `DEPLOYMENT_CHECKLIST` con artefactos, y (si entra, Q3) CD/staging.

---

## 3. Acción (verbo único y medible por sub-objetivo candidato — alcance final lo fija el Lead en §7)

- **A. ENDURECER contenedores:** Dockerfile de producción con **usuario no-root**, sin `--reload`, sin código de test; `security_opt: no-new-privileges`, `cap_drop`, `read_only` donde sea viable; `mem_limit`/`cpus`/`pids_limit` por servicio (validados por THOR para no asfixiar STT/IA en CPU-only).
- **B. AÑADIR rate-limiting GENERAL de API** (por IP/endpoint) como defensa anti-abuso/DoS, self-hosted (p. ej. `slowapi` + Redis ya presente, o límites en Caddy), sin degradar tráfico legítimo — **prioridad sujeta a Q4.**
- **C. INTEGRAR escaneo de vulnerabilidades en CI:** `pip-audit` (backend), `npm audit`/equivalente (frontend), opcionalmente `bandit` (SAST Python) y/o `trivy` (imagen), + `Dependabot`/renovate — como gates de CI (bloqueantes o informativos, a decidir).
- **D. MATERIALIZAR el hardening de host del `DEPLOYMENT_CHECKLIST`:** script versionado de firewall (`nftables`) con DROP de egress de IA + restricción de puertos, restringir los `ports:` de `db`/`redis`/`api` a loopback/interfaz interna, y convertir los `[ ]` en artefactos reales + marcarlos.
- **E. RESOLVER la coherencia TLS/headers (D-1/D-2):** alinear HSTS/CSP entre `security_headers.py` y el checklist (endurecer el código o corregir la doc, con criterio de seguridad), y documentar/materializar el TLS de producción (ACME en Caddy o proxy que termina TLS para la API).
- **F. (Condicional Q2) EXTENDER el overhead operativo:** runbook de incidente de **seguridad**, procedimiento de **rotación de secretos** reproducible, sobre lo que ya existe en `RUNBOOK.md`.
- **G. (Condicional Q3) MONTAR CD/staging** si el Lead lo mete en alcance — es un objetivo grande, probablemente su propia fase.

---

## 4. Formato (estructura exacta de la salida esperada de DOCTOR STRANGE / implementación)

1. **PLAN-011.md** (`.swarm/PLAN-011.md`): alcance IN/OUT, fases, entregables, riesgos, criterios de éxito, matriz preguntas→decisiones (resolviendo §7), clasificación SENSIBLE, y **priorización explícita de los huecos H-1..H-6 + D-1/D-2** (qué entra ahora, qué se difiere).
2. **SPECs** (`.swarm/specs/SPEC-080..0NN.md`) desde `next_spec:80`, con la cabecera/estilo de SPEC-077/078/079 (deriva de PLAN-011, clasificación, dependencias, checkpoints citados).
3. **ADR(s)** desde `next_adr:16` **SOLO si** una decisión introduce una excepción de arquitectura (p. ej. política de firewall del host como contrato de seguridad, o una elección de herramienta de escaneo con implicaciones de egress en CI). **No forzar un ADR si no hay una decisión arquitectónica genuina.**
4. **Artefactos de implementación esperados (según alcance aprobado):**
   - `Dockerfile` de producción (usuario no-root, multi-stage) + ajustes de `docker-compose.yml` (recursos, capabilities, `ports:` restringidos).
   - Middleware/config de rate-limiting general + dependencia pinneada (si B entra).
   - Steps de CI nuevos (`pip-audit`/`bandit`/`npm audit`/`trivy`) + `.github/dependabot.yml` (si C entra).
   - Script versionado de firewall de host (`nftables`) + doc de aplicación (si D entra).
   - Ajuste de `security_headers.py` y/o `DEPLOYMENT_CHECKLIST.md` para D-1/D-2; config TLS de producción de Caddy (si E entra).
   - Actualización de `RUNBOOK.md` (incidentes/rotación, si F) y de `DEPLOYMENT_CHECKLIST.md` (checkboxes → artefactos reales).
   - Pruebas (HAWKEYE): rate-limit 429, no-root, headers, escaneo que falla ante vuln sembrada.

---

## 5. Tests / criterios de éxito (verificables — C4)

> El set final depende del alcance aprobado (§7). Candidatos por hueco:

### Contenedores (A)
- [ ] El contenedor de `api`/workers corre como **usuario no-root** (`docker exec ... whoami` ≠ root) y **sin `--reload`** en producción.
- [ ] Cada servicio tiene **límites de recursos** (`mem_limit`/`cpus`) que THOR valida que NO estrangulan STT/IA en CPU-only; `no-new-privileges` y `cap_drop` aplicados donde es viable.

### Rate-limiting general (B)
- [ ] Un cliente que excede el límite por IP/endpoint recibe **429** (prueba controlada), y el tráfico legítimo NO se ve afectado (THOR verifica latencia).

### Escaneo de vulnerabilidades (C)
- [ ] El CI ejecuta `pip-audit` (backend) y `npm audit`/equivalente (frontend); una **dependencia vulnerable sembrada** hace **fallar** el gate (o reportar, según decisión). `Dependabot` activo.
- [ ] `requirements.txt` sigue 100% pinneado con `==` (sin regresión a rangos abiertos).

### Firewall/puertos (D)
- [ ] Existe un **script de firewall versionado** que aplica DROP de egress de IA y restringe puertos; `db`/`redis` dejan de publicarse a `0.0.0.0` (solo red interna/loopback).
- [ ] `check-externos-backend.sh` sigue **verde**; el aislamiento `ia_internal` se **refuerza**, nunca se relaja.

### Coherencia TLS/headers (E)
- [ ] HSTS/CSP coherentes entre `security_headers.py` y `DEPLOYMENT_CHECKLIST.md` (una sola fuente de verdad); TLS de producción documentado/materializado sin exponer secretos en el repo (C3).

### Transversal
- [ ] **CERO regresión:** fail-fast de secretos, RLS cross-tenant, CORS, egress, cifrado de audio y fases #1–#10 siguen verdes (suite completa + `test_rls_isolation`/`test_auth_cross_tenant_rls`).
- [ ] `DEPLOYMENT_CHECKLIST.md`: los checkboxes abordados ahora tienen **artefacto real** referenciado (no instrucciones de copiar/pegar).

---

## 6. Checkpoints aplicables (C1–C8 del proyecto — NO existe C9)

- **C3 (secretos):** 🔴 crítico. Cualquier credencial nueva (TLS, firewall, escaneo) por env/secret manager, nunca hardcodeada ni en logs. NO relajar los fail-fast ya existentes.
- **C4 (criterios verificables):** todos los de §5 son objetivos y demostrables.
- **C6 (deploy sensible):** aplicar firewall de host, cambiar `ports:`, o endurecer contenedores en el entorno real es cambio sensible → **aprobación explícita del Lead + notificación** antes de desplegar.
- **C8 (trazabilidad):** origen = PLAN-011 / `prompt-lab/prompts/PROMPT-011-HARDENING-PRODUCCION.md`.
- **Egress (patrón ADR, no checkpoint):** el escaneo de CVEs online corre en el **CI** (runner con egress), NUNCA desde el host on-prem aislado. Si alguna herramienta de hardening implicara un borde de egress nuevo en runtime, requeriría ADR acotado — pero el diseño por defecto NO lo introduce.

---

## 7. Preguntas abiertas para el Lead (VINCULANTES — DOCTOR STRANGE las necesita para fijar alcance)

> Formato con opciones (como en PROMPT-009/010). El Lead responde; la respuesta se anexará como "§7.1 Respuestas del Lead — VINCULANTES" antes de PLAN-011.

**Q1 — ¿Alcance de "hardening"? (la pregunta madre: qué huecos entran)**
Verificado que la seguridad de APLICACIÓN ya está madura; los huecos reales son de INFRA/OPERACIÓN (H-1..H-6, D-1/D-2). ¿Qué cubre esta fase?
- **(A) Solo endurecimiento TÉCNICO de infra/contenedores/CI:** H-1 (contenedores no-root + recursos), H-3 (escaneo de vulns en CI), H-4/D-2 (firewall + puertos), D-1 (coherencia headers), H-5/H-6 (TLS prod + Dockerfile prod). Rate-limiting general (H-2) según Q4. — *lo más acotado y entregable; recomendación de XAVIER por defecto.*
- **(B) Opción A + overhead OPERATIVO** (runbook de incidente de seguridad + rotación de secretos reproducible, extendiendo lo que ya existe en `RUNBOOK.md`). — *más completo; ver Q2.*
- **(C) Opción B + CD/staging** (pipeline de deploy automatizado + entorno de staging). — *el más ambicioso; probablemente merece su propia fase, ver Q3.*

**Q2 — Overhead operativo: ¿se extiende el runbook de incidentes/rotación en esta fase, o se deja para después?**
`RUNBOOK.md` YA tiene secciones de rotación de secretos, respuesta a incidentes y rollback (prosa). ¿Esta fase las **endurece/convierte en procedimientos reproducibles y probados** (runbook de incidente de seguridad específico, rotación paso a paso verificable), o las deja como están y se concentra en lo técnico?
- **(A) Dejar el runbook como está** (solo hardening técnico). — *si Q1=A.*
- **(B) Extender/endurecer runbook de incidentes de seguridad + rotación de secretos** (sobre lo existente, sin empezar de cero). — *si Q1=B/C.*

**Q3 — Entorno objetivo y CD/staging: ¿esta fase opera sobre el `docker-compose` actual, o monta un pipeline de deploy / servidor de producción real?**
Pregunta recurrente del proyecto (sigue sin haber servidor de producción dedicado confirmado ni staging; CI sin CD).
- **(A) Hardening SOBRE el `docker-compose` actual** (sin CD/staging nuevo): se endurece lo que hay, el deploy sigue manual. — *recomendación de XAVIER; mantiene la fase acotada.*
- **(B) Incluir CD/staging en esta fase** (pipeline de deploy automatizado + entorno de staging). — *objetivo grande; XAVIER sugiere que, si se quiere, sea una fase propia posterior para no diluir el hardening.*
- **Sub-pregunta:** ¿hay ya un **servidor de producción real** en algún sitio (para dimensionar firewall/TLS/recursos con realismo), o seguimos diseñando sobre la infra de desarrollo/demo como en fases anteriores?

**Q4 — Rate-limiting general de API (H-2): ¿prioridad ALTA ahora, o se difiere?**
Hoy solo hay rate-limiting de login. Añadir uno general (por IP/endpoint, p. ej. `slowapi` + Redis ya presente) protege webhooks y endpoints REST contra abuso/DoS, pero es superficie nueva.
- **(A) Alta prioridad — entra en esta fase.** — *recomendación de XAVIER: la API expone webhooks públicos (WhatsApp/PBX) y endpoints REST sin tope general; es un hueco de abuso real.*
- **(B) Diferir** a una fase posterior (se documenta como hueco conocido, como se hizo con backups en PLAN-010 §13).

**Q5 — Escaneo de vulnerabilidades (H-3): ¿gate BLOQUEANTE o informativo, y qué severidad?**
Integrar `pip-audit`/`npm audit`/`bandit`/`trivy` + Dependabot. ¿Cómo de estricto?
- **(A) Bloqueante en severidad HIGH/CRITICAL** (el CI falla; fuerza atención inmediata). — *recomendación de XAVIER para un proyecto con PHI.*
- **(B) Informativo** (reporta en el job summary, no bloquea) al principio, endurecer después.
- **Sub-pregunta compliance:** este es un CRM clínico (PHI potencial, ADR-009) pero **NO se ha mencionado ningún marco regulatorio formal** (SOC2/ISO27001/HIPAA/PCI). ¿El hardening debe mapearse a algún marco concreto (lo cual cambia sustancialmente el alcance), o es "buenas prácticas de seguridad" sin certificación formal? *(XAVIER por defecto asume lo segundo — buenas prácticas, sin inventar un marco regulatorio.)*

> **Nota sobre backups (PLAN-010 §13, DIFERIDOS):** las decisiones Q2/Q3 del Lead sobre backups (Postgres + `audio_store` cifrado, destino LAN/NAS interna) ya están tomadas y registradas. "Hardening de producción" y "backups" están relacionados (un backup cifrado offsite ES parte de la postura de seguridad). **¿Se retoman los backups diferidos COMO PARTE de esta fase, o siguen diferidos a un PLAN posterior?** — esta es, de hecho, una 6ª decisión del Lead:
>
> **Q6 — Backups diferidos (PLAN-010 §13): ¿se retoman en esta fase C, o siguen diferidos?**
> - **(A) Siguen diferidos** — esta fase es solo hardening de la superficie viva; los backups entran en su propia fase posterior con las decisiones ya tomadas. — *mantiene el foco.*
> - **(B) Se retoman AQUÍ** — dado que backup cifrado + restauración probada es parte de la postura de seguridad de producción, se materializan en esta fase (Postgres + `audio_store` cifrado, rsync a NAS LAN, restore probado — Q2/Q3 de PLAN-010 ya respondidas). — *consolida toda la "producción endurecida" en un solo esfuerzo.*

---

## 7.1 Respuestas del Lead — VINCULANTES (2026-10-02)

- **Q1 (alcance):** **Opción A** — solo hardening TÉCNICO de infra/contenedores/CI/firewall/TLS (H-1, H-3, H-4/D-2, D-1, H-5/H-6). El runbook operativo (Q2) NO se toca; el deploy sigue manual sin CD/staging.
- **Q2 (overhead operativo — derivada de Q1=A):** se deja el `RUNBOOK.md` como está; esta fase se concentra en lo técnico.
- **Q3 (entorno objetivo):** **Opción A** — se diseña sobre la infraestructura `docker-compose` actual de desarrollo/demo; no hay un servidor de producción dedicado confirmado todavía. CD/staging (Q1-C) queda fuera, como una fase posterior propia si el Lead la pide en el futuro.
- **Q4 (rate-limiting general):** **Opción A** — alta prioridad, entra en esta fase. Reutiliza el Redis ya existente; cubre webhooks públicos (WhatsApp/PBX) y endpoints REST sin tope general hoy.
- **Q5 (escaneo de vulnerabilidades):** **Opción A** — gate BLOQUEANTE en severidad HIGH/CRITICAL (`pip-audit`/`npm audit`/`bandit`). Sub-pregunta de compliance: sin marco regulatorio formal (SOC2/ISO/HIPAA/PCI) — "buenas prácticas de seguridad", confirmado el default de XAVIER.
- **Q6 (backups diferidos de PLAN-010):** **Opción A** — siguen DIFERIDOS. Esta fase C NO los retoma; quedan para una fase posterior con las decisiones Q2/Q3 de PLAN-010 §13 ya tomadas (Postgres + `audio_store` cifrado, destino LAN/NAS interna, sin ADR de egress).

**Consecuencia directa para DOCTOR STRANGE:** PLAN-011 cubre únicamente H-1 (contenedores no-root + límites de recursos), H-2 (rate-limiting general, prioridad alta), H-3 (escaneo de vulnerabilidades bloqueante HIGH/CRITICAL + Dependabot), H-4/D-2 (firewall de host + restricción de puertos), D-1 (coherencia HSTS/CSP), H-5/H-6 (TLS de producción + Dockerfile de producción) — todo sobre el `docker-compose` actual, sin CD/staging, sin tocar el runbook operativo más allá de referenciar los artefactos nuevos, y sin retomar backups. No se fuerza ningún ADR salvo que una decisión técnica concreta lo exija genuinamente (p. ej. política de firewall como contrato de seguridad).

---

## 8. Fuera de alcance (anti-scope explícito)

- **Reimplementar la seguridad de aplicación YA hecha:** fail-fast de secretos, RLS, CORS, security headers (salvo la coherencia D-1), cifrado de audio, egress acotado. Verificados en §1.1 — no duplicar.
- **Nuevas funcionalidades de negocio / canales** (Instagram DM es la Fase 4, siguiente).
- **Relajar cualquier invariante** (RLS, `omnicore_app`, aislamiento `ia_internal`, `check-externos-backend.sh`, PHI). El hardening solo REFUERZA.
- **Inventar un marco de compliance formal** (SOC2/ISO/HIPAA/PCI) que el Lead no ha pedido (a confirmar en Q5-sub).
- **SaaS externo de pago** (WAF cloud, secret manager SaaS, escáner SaaS de pago) — todo self-hosted / herramientas de CI gratuitas, patrón ADR-005.
- **Backups** (DIFERIDOS, PLAN-010 §13) salvo que el Lead los retome aquí explícitamente (Q6-B).
- **CD/staging** salvo que el Lead lo meta en alcance (Q3-B).

---

## 9. Trazabilidad

- **Origen:** objetivo verbatim del Lead "Fase C: Hardening de producción" (3ª de 4 fases ordenadas; 1 y 2 cerradas, PLAN-009/PLAN-010).
- **Evidencia del estado real** (verificada por XAVIER en esta sesión, 2026-10-02): `backend/app/core/config.py:609–672` (fail-fast secretos/host IA), `backend/app/core/security_headers.py` (headers implementados, HSTS 15552000 + CSP con unsafe-inline), `backend/app/main.py:109–123` (CORS + middlewares), `backend/app/security/rate_limit.py` (rate-limit SOLO login), `docker-compose.yml` (CERO límites de recursos/capabilities/no-root; `db`/`redis`/`api` publican a `0.0.0.0`; `ia` sí a `127.0.0.1`), `backend/Dockerfile` (root + `--reload` + `COPY . .`), `backend/requirements.txt` (39 pins `==`, 0 rangos; sin `slowapi`/`pip-audit`), `.github/workflows/backend-ci.yml` (black/flake8/mypy/check-externos/pytest/cobertura≥80, SIN pip-audit/bandit/trivy), `.github/workflows/ci.yml` (lint/build/test/Lighthouse, SIN npm audit), sin `.github/dependabot.yml`, sin script de firewall/hardening de host versionado, `Caddyfile` (solo webhook PBX + `/voice/ws`, TLS prod como comentario), `DEPLOYMENT_CHECKLIST.md` (Fases 1–7; checkboxes `[ ]` de firewall/puertos/TLS/backup sin artefacto; HSTS/CSP divergen del código), `RUNBOOK.md` (rotación de secretos/incidentes/rollback ya documentados), `.swarm/PLAN-010.md §13` (backups diferidos, Q2/Q3 resueltas), `.swarm/specs.json` (`next_plan:11`, `next_spec:80`, `next_adr:16`).
- **Siguiente paso:** el Lead responde §7 (Q1–Q6) → se anexan respuestas VINCULANTES (§7.1) → 🔮 DOCTOR STRANGE redacta PLAN-011 → aprobación del Lead → SPECs → aprobación → implementación.
