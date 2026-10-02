# SPEC-080 — Contenedores + Dockerfile de producción: imagen no-root sin `--reload`/tests/`.env`/bind-mount (multi-stage o target separado, conservando la imagen de desarrollo) + `mem_limit`/`cpus`/`pids_limit`/`no-new-privileges`/`cap_drop`/`read_only` en `docker-compose.yml`, con la PUERTA DURA de THOR (R-103) como criterio BLOQUEANTE antes de fijar cualquier límite de recursos a `api`/`stt_worker`/`ia` (no asfixiar STT faster-whisper, RTF vs RNF-42, ni IA Ollama, p95 RAG vs RNF-04) 🔴 SENSIBLE

- Estado: CERRADA — implementado por CAPTAIN AMERICA: Dockerfile multi-stage (`development`/`production`), usuario no-root `appuser`, sin `--reload`/tests/`.env` en producción (`.dockerignore` + copia selectiva), `docker-compose.prod.yml` como overlay versionado. En `docker-compose.yml`: `mem_limit`/`cpus`/`pids_limit` holgados en 16 de 19 servicios, `no-new-privileges`+`cap_drop: [ALL]` en los 19, `read_only`+`tmpfs` donde no rompe escritura legítima. **Puerta dura de THOR (R-103) satisfecha por diseño:** `api`/`stt_worker`/`ia` quedaron explícitamente SIN `mem_limit`/`cpus` (opción "ausente" que la propia SPEC permite cuando no hay informe de THOR) — ningún límite se fijó sin ese informe, confirmado por BLACK WIDOW. Auditoría de BLACK WIDOW: cero relajación de RLS/secretos/egress; `init_audio_store.sh` fail-closed (no degrada permisos ante error de ownership). Suite completa re-verificada por el orquestador contra Postgres real: 778 passed, cero regresión nueva. · Responsable: CAPTAIN AMERICA · Colaboran/revisan: QUICKSILVER, BLACK WIDOW, HAWKEYE, WOLVERINE, THOR (puerta de recursos, satisfecha por ausencia de límite) · Prioridad: ALTA · Tipo: INFRA/CONTENEDORES/DOCKERFILE/DOCKER-COMPOSE · Fase: F0
- Deriva de: PLAN-011 (F0, §1 H-1/H-6, §2.IN.1, §3.2, §3.3, §4, §5, §6 R-103/R-104, §7 CE-104/CE-105, §9, §10 · R-103 (top crítico — puerta de THOR)/R-104 · CE-104/CE-105) · Clasificación: SENSIBLE (`.no-externo`) · Consume `backend/Dockerfile`, `docker-compose.yml`, `backend/app/workers/stt_worker.py`, `backend/scripts/init_audio_store.sh` (o equivalente), volúmenes `audio_store` (cifrado, ADR-009), `whisper_models`, `ollama_models`, ADR-005/ADR-009 (sin rediseño) · Coordina edición de `docker-compose.yml` con SPEC-083 (§5 PLAN-011) · Prerequisito conceptual de SPEC-084 (prueba el conjunto)

## Objetivo

Convertir los contenedores de "desarrollo corriendo en producción" a **imagen de producción endurecida**, sin reimplementar nada de la seguridad de aplicación ya madura. Debe producir: (1) una **imagen de producción** (multi-stage o target separado del `Dockerfile`) con **usuario no-root**, **sin `--reload`**, **sin código de test ni `.env`**, **sin bind-mount de desarrollo**, **conservando la imagen de desarrollo** actual intacta para el flujo local; (2) en `docker-compose.yml`, por servicio: `mem_limit`/`cpus`/`pids_limit`, `security_opt: no-new-privileges`, `cap_drop` donde sea viable, y `read_only` donde **no** rompa una escritura legítima (dejando `rw` `audio_store`, modelos y `tmp`). **PUERTA DURA (R-103, criterio de aceptación BLOQUEANTE):** ningún `mem_limit`/`cpus` se fija a `api`, `stt_worker` o `ia` (Ollama) **sin el visto bueno explícito y documentado de THOR** (RTF de faster-whisper vs RNF-42; p95 RAG vs RNF-04) — con la opción explícita de dejar esos servicios **generosos o sin límite** si el riesgo de asfixia supera el beneficio de hardening. Es trabajo **aditivo/endurecedor**: no toca el código de aplicación, el aislamiento `ia_internal`, el egress ni los secretos.

## Contexto

Verificado en PLAN-011 §1.4/§3.2 y en el repo (fuente de verdad, no asunciones — 2026-10-02):
- **Hardening de contenedores AUSENTE por completo.** `grep` sobre `docker-compose.yml` → CERO `mem_limit`/`cpus`/`deploy.resources`/`read_only`/`user:`/`cap_drop`/`security_opt`/`no-new-privileges`/`pids_limit`/`ulimits`.
- **`backend/Dockerfile` corre como root y en modo desarrollo:** sin `USER` no-root (`pip install` y `CMD uvicorn` como root), arranca con **`--reload`** (flag de desarrollo), hace `COPY . .` (incluye tests y cualquier `.env` presente); además `docker-compose.yml` monta **bind-mount de desarrollo** del código (`./backend:/app`). No existe separación imagen de producción vs desarrollo (H-6).
- **Máquina CPU-only compartida (invariante dura, §1.4 PLAN-011):** los límites de recursos **NO pueden estrangular STT** (faster-whisper, `stt_worker`) **ni IA** (Ollama, `ia`). Es el riesgo real y crítico de esta fase (R-103). Los histogramas de latencia que fijan el baseline ya existen (`ai_request_duration_seconds` vs RNF-04; `stt_rtf` vs RNF-42 — observabilidad de PLAN-010, SPEC-077/078), de modo que THOR dispone de evidencia medible para dimensionar o descartar límites.
- **Escrituras legítimas a preservar (R-104):** `audio_store` (cifrado en reposo, ADR-009) debe quedar **`rw`**; los volúmenes de modelos (`whisper_models`, `ollama_models`) y `tmp` necesitan escritura; cualquier `init_audio_store.sh`/`chmod` de arranque que asuma root debe adaptarse al usuario no-root con ownership correcto. Un `read_only`/`cap_drop`/no-root mal aplicado rompería las fases #4/#5/#6 (audio/STT/IA).
- **Patrón a imitar:** los servicios de observabilidad de PLAN-010 (Prometheus/Grafana/Alertmanager) ya nacen correctos; `ia` ya restringe su puerto a loopback. Esta SPEC toca **recursos/capabilities**, no `ports:` (eso es SPEC-083) — por eso la **edición de `docker-compose.yml` se coordina con SPEC-083** (§5 PLAN-011) para evitar conflicto.

## Alcance

### IN
- **Imagen de producción** (multi-stage o target `production` separado en el `Dockerfile`): usuario **no-root** con ownership correcto de los paths de escritura; **sin `--reload`**; **sin código de test ni `.env`** (ni `COPY . .` que los arrastre); **sin bind-mount** de desarrollo en el servicio de producción. **La imagen/flujo de desarrollo se conserva** intacta (target `development` o `Dockerfile` actual) para el trabajo local.
- **Límites de recursos en `docker-compose.yml`** por servicio: `mem_limit`/`cpus`/`pids_limit`. Los servicios **ligeros** (`api` stateless, `redis`, `caddy`, observabilidad) se acotan con holgura. Para `api`, `stt_worker` e `ia` los valores los fija **THOR con evidencia** (R-103, puerta dura) o se dejan **generosos/ausentes** si la asfixia supera el beneficio.
- **Capabilities / privilegios:** `security_opt: no-new-privileges` donde viable; `cap_drop` (mínimo necesario) donde no rompa funcionalidad; `read_only: true` **solo** donde no haya escritura legítima, dejando `rw` `audio_store`/modelos/`tmp` (`tmpfs` o volumen donde corresponda).
- **Ownership/arranque no-root:** adaptar cualquier script de init (`init_audio_store.sh` o equivalente) y los permisos de los volúmenes para que el usuario no-root pueda escribir audio cifrado, modelos y temporales.

### OUT
- **Rate-limiting general** → SPEC-081 (F1). **Escaneo CI/Dependabot** → SPEC-082 (F2). **Firewall de host, `ports:` restringidos, HSTS/CSP/TLS** → SPEC-083 (F3). **Pruebas consolidadas + docs del checklist** → SPEC-084 (F4).
- **Reimplementar la seguridad de aplicación YA hecha** (fail-fast de secretos, RLS, CORS, security headers, cifrado de audio, egress acotado): se **consume/refuerza**, no se rediseña.
- **CD/pipeline de deploy/staging/servidor de producción dedicado** → fuera de alcance (Q3=A, PLAN-011 §2 OUT).
- **Backups automatizados** → fuera de alcance (Q6=A, DIFERIDOS; ver PLAN-011 §2 OUT / PLAN-010 §13). No se mencionan como entregable.
- **Runbook operativo** → no se reescribe (Q2=A); la actualización del `DEPLOYMENT_CHECKLIST.md` es SPEC-084.

## Dependencias
- Consume `backend/Dockerfile`, `docker-compose.yml`, `backend/app/workers/stt_worker.py`, el init del `audio_store` y los volúmenes de modelos **sin rediseñar la lógica de aplicación**. **Coordina la edición de `docker-compose.yml` con SPEC-083** (ambas tocan el mismo archivo: SPEC-080 recursos/capabilities, SPEC-083 `ports:`/redes — §5 PLAN-011, ruta crítica F0 → F3). Es la **base física** del endurecimiento (no depende de fases previas de PLAN-011). **Prerequisito conceptual de SPEC-084** (que prueba el conjunto). La puerta de THOR (R-103) se comparte a nivel de validación con SPEC-081 (latencia).

## Requisitos funcionales
- RF-01 Existe una **imagen de producción** (multi-stage/target separado) que corre como **usuario no-root**, **sin `--reload`**, **sin código de test ni `.env`**, **sin bind-mount** de desarrollo; la imagen/flujo de desarrollo se **conserva** para uso local (CE-104).
- RF-02 En `docker-compose.yml`, los servicios **ligeros** (`api` stateless, `redis`, `caddy`, observabilidad) tienen `mem_limit`/`cpus`/`pids_limit` con holgura, sin degradar su operación (CE-104).
- RF-03 **(Puerta dura R-103)** Los `mem_limit`/`cpus` de `api`, `stt_worker` e `ia` **solo se fijan con el visto bueno explícito y documentado de THOR** (informe de RTF vs RNF-42 y p95 RAG vs RNF-04 bajo los límites propuestos); donde el riesgo de asfixia supere el beneficio, el límite queda **generoso o ausente**, decisión registrada en la SPEC (CE-104).
- RF-04 `security_opt: no-new-privileges` y `cap_drop` aplicados donde es viable; `read_only: true` solo donde no haya escritura legítima; `audio_store`/modelos/`tmp` quedan `rw` (CE-105).
- RF-05 El arranque como usuario no-root escribe correctamente el **audio cifrado** (ADR-009), los **modelos** y los **temporales**; cualquier script de init se adapta al no-root con ownership correcto (CE-105).

## Requisitos no funcionales
- RNF-NO-ASFIXIA (R-103, top crítico) Los límites de recursos de STT (`stt_worker`, faster-whisper, RTF vs RNF-42) e IA (`ia`, Ollama, p95 RAG vs RNF-04) **no degradan el servicio** en la máquina CPU-only compartida; THOR valida con evidencia **antes** de fijarlos; sin su visto bueno no se fijan límites a esos servicios.
- RNF-NO-ROMPE-ESCRITURA (R-104) El usuario no-root / `read_only` / `cap_drop` **no rompe** ninguna escritura legítima (`audio_store` cifrado, modelos, `tmp`, logs); suites #4/#5/#6 verdes (verificación formal en SPEC-084).
- RNF-ADITIVO Todo aditivo/endurecedor: no se modifica el código de aplicación, el aislamiento `ia_internal`, el egress ni `/metrics`/healthchecks; la imagen de desarrollo se conserva.
- RNF-C3 Ningún secreto en el `Dockerfile`/compose; la imagen de producción **no** incluye `.env` ni secretos; credenciales por env en runtime, nunca hardcodeadas ni generadas por el agente.
- RNF-REPRO La imagen de producción es reproducible (base pinneada, `requirements.txt` 100% `==` ya vigente); el build no requiere egress nuevo en runtime.

## Criterios de aceptación (verificables)
- [ ] `docker exec <api>/<worker> whoami` ≠ `root`; el `CMD` de producción **no** usa `--reload`; la imagen de producción **no** contiene tests ni `.env`; el servicio de producción **no** monta bind-mount de desarrollo; la imagen de desarrollo sigue disponible (CE-104).
- [ ] **(BLOQUEANTE, R-103)** Existe **informe de THOR** que documenta el visto bueno de los `mem_limit`/`cpus` de `api`/`stt_worker`/`ia` (RTF vs RNF-42, p95 RAG vs RNF-04), o la decisión explícita de dejarlos generosos/sin límite; **ningún límite a esos tres servicios se fija sin ese informe** (CE-104).
- [ ] `no-new-privileges` y `cap_drop` aplicados donde viable; `read_only` solo donde no haya escritura; inspección de compose coherente (CE-105).
- [ ] Arranque OK como no-root: escritura de **audio cifrado** (ADR-009), modelos y temporales funciona; suites #4/#5/#6 verdes (consolidado en SPEC-084) (CE-105).
- [ ] `check-externos-backend.sh` sigue verde sin relajar allowlist; sin egress nuevo en runtime; sin secretos en imagen/compose/logs.

## Notas de seguridad (C3/C6)
- C3: la imagen de producción **no** empaqueta `.env` ni secretos; toda credencial por env en runtime, nunca hardcodeada, nunca en logs, nunca generada por el agente implementador.
- C6: **aplicar los límites de recursos y la imagen de producción endurecida en un entorno real de producción es un cambio sensible** → requiere **aprobación explícita del Lead + notificación** antes de desplegar (ajustar `mem_limit`/`cpus` en caliente puede afectar STT/IA). Esta SPEC entrega los artefactos versionados; no los aplica en producción.

## Restricción SENSIBLE / egress
- 🔴 SENSIBLE (sin egress nuevo): el hardening de contenedores toca la superficie de un backend multi-tenant (RLS) con PHI potencial (audio/transcripciones, ADR-009). Un límite que **asfixie STT/IA** sería una **REGRESIÓN de servicio** (R-103); un `read_only`/no-root que rompa la escritura del `audio_store` cifrado sería una **REGRESIÓN de funcionalidad/PHI** (R-104). No se introduce egress nuevo; `ia_internal` no se toca; `check-externos-backend.sh` verde sin relajar allowlist. **Sin ADR nuevo en esta SPEC** (el único ADR de la fase, firewall de host, es de SPEC-083/ADR-016).

## Riesgos
- R-103 (**los límites de recursos estrangulan STT/IA en CPU-only**): mitigación: **THOR es puerta previa dura** (criterio BLOQUEANTE RF-03/CE-104); límites generosos o ausentes donde la asfixia supere el beneficio; el hardening de recursos prioriza servicios ligeros. **TOP CRÍTICO del plan — sin visto bueno de THOR no se fijan límites a `api`/`stt_worker`/`ia`.**
- R-104 (**no-root / `read_only` / `cap_drop` rompe una escritura legítima**): mitigación: mapear escrituras (`audio_store` cifrado, modelos, `tmp`), mantenerlas `rw`, ownership correcto del no-root, `read_only` solo donde no haya escritura; suites #4/#5/#6 verdes (CE-105).

## Checkpoints aplicables
- C3 (secretos: imagen sin `.env`/secretos, credenciales por env, cero generadas por el agente, cero en logs). C4 (criterios verificables — no-root, informe de THOR, escrituras intactas). C6 (aplicar límites/imagen de producción endurecida en el entorno real = cambio sensible → aprobación del Lead + notificación antes de desplegar). C8 (origen `prompt-lab/prompts/PROMPT-011-HARDENING-PRODUCCION.md`).
