# SPEC-084 — Pruebas + seguridad + no-regresión + docs que CIERRA PLAN-011 (DoD): verificación de 429 (HAWKEYE), contenedor no-root confirmado, headers coherentes emitidos (HSTS 1 año + CSP estricta salvo excepción `/docs`), escaneo que FALLA ante una dependencia vulnerable sembrada deliberadamente, auditoría de que NINGÚN endurecimiento relajó una invariante (RLS/egress/secretos/PHI — BLACK WIDOW), CERO regresión de las suites #1–#10 y de `check-externos-backend.sh`, y `DEPLOYMENT_CHECKLIST.md` con los checkboxes abordados convertidos en artefactos reales referenciados (sin tocar el RUNBOOK operativo, Q2=A) 🔴 SENSIBLE

- Estado: APROBADA (bloque SPEC-080..084, 2026-10-02) · Responsable: HAWKEYE (pruebas: 429, no-root, headers, escaneo que falla ante vuln sembrada) · Colaboran/revisan: BLACK WIDOW (**auditoría de que ningún endurecimiento relajó una invariante** — RLS/egress/secretos/PHI), WOLVERINE (no-regresión/calidad), QUICKSILVER (`DEPLOYMENT_CHECKLIST.md`/`docker-compose`), BLACK PANTHER, THOR · Prioridad: ALTA · Tipo: PRUEBAS/SEGURIDAD/DOCS/NO-REGRESIÓN · Fase: F4
- Deriva de: PLAN-011 (F4, §2.IN.6, §3.1, §4, §5, §6 R-103..R-109, §7 CE-112/CE-113, §9, §10 · cierra R-103..R-109 · CE-112/CE-113) · Clasificación: SENSIBLE (`.no-externo`) · **Depende de SPEC-080, SPEC-081, SPEC-082 y SPEC-083** (prueba/audita/documenta el conjunto) · Consume `backend/check-externos-backend.sh`, `tests/test_rls_isolation.py`/`test_auth_cross_tenant_rls.py`/`test_config_and_cors.py`, `DEPLOYMENT_CHECKLIST.md`, `backend/app/core/security_headers.py`, ADR-005/006/009/010/016 · **Cierra el slice** (DoD PLAN-011 §10)

## Objetivo

Verificar y **cerrar** PLAN-011 con una tanda de **pruebas + seguridad + no-regresión** y la **actualización del `DEPLOYMENT_CHECKLIST.md`**. Debe demostrar, de forma objetiva y auditable: (1) que el **rate-limit general dispara 429** y el tráfico legítimo NO (HAWKEYE, CE-106); (2) que el **contenedor corre como no-root** (CE-104/CE-105); (3) que los **headers coherentes se emiten** (HSTS 1 año + CSP estricta sin `'unsafe-inline'` salvo excepción acotada `/docs`/`/redoc`, CE-110); (4) que el **escaneo FALLA ante una dependencia vulnerable sembrada** deliberadamente (CE-107); (5) **auditoría de BLACK WIDOW** de que **NINGÚN endurecimiento relajó una invariante** (RLS, egress, secretos, PHI — el criterio de seguridad top de esta SPEC); (6) **CERO regresión** de las suites existentes (#1–#10) y de `check-externos-backend.sh` (CE-112); y (7) la **actualización de `DEPLOYMENT_CHECKLIST.md`** convirtiendo los checkboxes abordados (firewall, puertos, TLS, headers, escaneo) en **artefactos reales referenciados** (CE-113), **sin tocar el RUNBOOK operativo** (Q2=A). No implementa hardening nuevo: **prueba/audita/documenta el conjunto** y cierra el DoD.

## Contexto

Verificado en PLAN-011 §4/§5/§7/§10 y en el repo (fuente de verdad, no asunciones — 2026-10-02):
- **Patrón de cierre (SPEC-079 de PLAN-010):** esta SPEC es la **puerta de evidencia** de todo PLAN-011. Reúne las verificaciones dispersas en las SPEC-080..083 y añade la auditoría de no-relajación de invariantes + la no-regresión global + la actualización del checklist.
- **Auditoría de no-relajación de invariantes (BLACK WIDOW — criterio top de esta SPEC):** ningún endurecimiento (no-root, límites, rate-limit, firewall, puertos, HSTS/CSP, TLS, escaneo) puede haber **relajado** una invariante: fail-fast de secretos (`config.py:609–672`), RLS multi-tenant (`omnicore_app` NOSUPERUSER NOBYPASSRLS, ADR-004/008), CORS endurecido, egress acotado (`check-externos-backend.sh`, `ia_internal internal:true`), cifrado de audio (ADR-009, PHI). Se audita explícitamente que el escaneo **no** relajó la allowlist de egress (R-106, invariante central de SPEC-082) y que el firewall **reforzó** (no relajó) `ia_internal`.
- **Cero regresión (#1–#10):** las suites de las fases #1–#10 (incluye observabilidad de PLAN-010) deben pasar **sin modificar asserts**; en particular `test_rls_isolation`/`test_auth_cross_tenant_rls`/`test_config_and_cors` verdes; `check-externos-backend.sh` verde **sin relajar allowlist**. Esta fase no re-instrumenta nada ni toca la lógica de aplicación.
- **Prueba de dependencia vulnerable sembrada (CE-107):** un PR con una dependencia vulnerable deliberada debe poner el **CI en rojo** (gate HIGH/CRITICAL de SPEC-082), y luego revertirse — evidencia de que el gate funciona.
- **Docs (Q2=A):** se actualiza **solo** el `DEPLOYMENT_CHECKLIST.md` convirtiendo los `[ ]` fantasma (firewall, puertos, TLS, headers, escaneo) en **artefactos reales referenciados** (apuntando a `scripts/ops/`, `security_headers.py`, los workflows, `dependabot.yml`, ADR-016). **El `RUNBOOK.md` NO se reescribe** (Q2=A); como mucho se referencian los artefactos nuevos, sin extender procedimientos operativos. **Backups DIFERIDOS** (Q6=A) no se tocan ni se mencionan como entregable (ver PLAN-011 §2 OUT / PLAN-010 §13).

## Alcance

### IN
- **Verificación del 429** (HAWKEYE, CE-106): prueba controlada de exceso por IP/endpoint → 429; prueba de ráfaga legítima (webhooks WhatsApp/PBX) → **sin** 429; coexistencia con `LoginRateLimiter` confirmada.
- **Verificación no-root** (CE-104/CE-105): `docker exec ... whoami` ≠ root en `api`/workers; sin `--reload`; escrituras legítimas (`audio_store` cifrado/modelos/`tmp`) intactas; suites #4/#5/#6 verdes.
- **Verificación de headers coherentes** (CE-110): HSTS `max-age=31536000` + CSP estricta sin `'unsafe-inline'` emitidos en `/api/*`/`/metrics`; `/docs` usable (excepción acotada) o Swagger OFF en prod; `security_headers.py` = `DEPLOYMENT_CHECKLIST.md`.
- **Verificación del escaneo que FALLA** (CE-107): dependencia vulnerable **sembrada** → CI rojo (gate HIGH/CRITICAL); Dependabot presente; `requirements.txt` 100% `==`; `check-externos-backend.sh` verde sin relajar allowlist.
- **Auditoría de no-relajación de invariantes** (BLACK WIDOW, criterio top): ningún endurecimiento relajó RLS/egress/secretos/PHI; el escaneo no relajó la allowlist (R-106); el firewall reforzó `ia_internal`; cero secretos en el repo/logs (C3).
- **No-regresión (#1–#10, CE-112):** suites #1–#10 verdes **sin modificar asserts**; `test_rls_isolation`/`test_auth_cross_tenant_rls`/`test_config_and_cors` verdes; `check-externos-backend.sh` verde.
- **Actualización de `DEPLOYMENT_CHECKLIST.md`** (CE-113): checkboxes abordados (firewall, puertos, TLS, headers, escaneo) → **artefactos reales referenciados** (`scripts/ops/`, `security_headers.py`, workflows, `dependabot.yml`, ADR-016); **sin tocar el RUNBOOK operativo** (Q2=A).

### OUT
- **Implementar** contenedores/Dockerfile (SPEC-080), rate-limiting (SPEC-081), escaneo/Dependabot (SPEC-082), firewall/puertos/TLS/headers (SPEC-083) → aquí se **prueban/auditan/documentan**, no se implementan.
- **Reescribir el `RUNBOOK.md`** (Q2=A) → PROHIBIDO; solo se referencian los artefactos nuevos en el checklist.
- **Retomar/mencionar backups** (Q6=A, DIFERIDOS) → fuera de alcance (ver PLAN-011 §2 OUT / PLAN-010 §13); no se tocan ni se mencionan como entregable.
- **CD/staging/servidor de producción dedicado** (Q3=A) → fuera de alcance.
- **Relajar cualquier invariante** (RLS/egress/secretos/PHI) para "hacer pasar" una prueba → PROHIBIDO; se consume todo intacto.
- **Mapear a un marco de compliance formal** (SOC2/ISO/HIPAA/PCI) → fuera de alcance (Q5-sub=A).

## Dependencias
- **Depende de SPEC-080, SPEC-081, SPEC-082 y SPEC-083** (prueba, audita y documenta el conjunto completo). Reutiliza `check-externos-backend.sh` (egress), `test_rls_isolation`/`test_auth_cross_tenant_rls`/`test_config_and_cors` (no-regresión), `security_headers.py` (headers), los workflows (escaneo) y `DEPLOYMENT_CHECKLIST.md` (docs). Consume ADR-005/006/009/010/016 sin rediseño. **Cierra el slice** (DoD PLAN-011 §10). Ruta crítica: F0 (SPEC-080) → F3 (SPEC-083) → **F4 (SPEC-084)**; F1 (SPEC-081) y F2 (SPEC-082) convergen aquí.

## Requisitos funcionales
- RF-01 Prueba de que el rate-limit general dispara **429** por IP/endpoint y la **ráfaga legítima** de webhooks NO recibe 429; coexiste con `LoginRateLimiter` (CE-106).
- RF-02 Verificación de **contenedor no-root** (`whoami` ≠ root), sin `--reload`, con escrituras legítimas (`audio_store`/modelos/`tmp`) intactas; suites #4/#5/#6 verdes (CE-104/CE-105).
- RF-03 Verificación de **headers coherentes**: HSTS `max-age=31536000` + CSP estricta sin `'unsafe-inline'` en `/api/*`/`/metrics`; `/docs` usable (excepción acotada) o Swagger OFF en prod; `security_headers.py` = `DEPLOYMENT_CHECKLIST.md` (CE-110).
- RF-04 Verificación de que una **dependencia vulnerable sembrada** hace **fallar** el CI (gate HIGH/CRITICAL); Dependabot presente; `requirements.txt` 100% `==`; `check-externos-backend.sh` verde sin relajar allowlist (CE-107).
- RF-05 **Auditoría de no-relajación** (BLACK WIDOW): ningún endurecimiento relajó RLS/egress/secretos/PHI; el escaneo no relajó la allowlist (R-106); el firewall reforzó `ia_internal`; cero secretos en el repo/logs (CE-112).
- RF-06 **No-regresión:** suites #1–#10 verdes sin modificar asserts; `test_rls_isolation`/`test_auth_cross_tenant_rls`/`test_config_and_cors` verdes; `check-externos-backend.sh` verde (CE-112).
- RF-07 `DEPLOYMENT_CHECKLIST.md` con los checkboxes abordados (firewall/puertos/TLS/headers/escaneo) → **artefactos reales referenciados**; `RUNBOOK.md` NO se reescribe (Q2=A) (CE-113).

## Requisitos no funcionales
- RNF-NO-RELAJA-INVARIANTE (criterio top) Ningún endurecimiento de la fase relajó fail-fast de secretos, RLS, CORS, egress (`check-externos-backend.sh`/`ia_internal`) ni cifrado de audio (PHI, ADR-009); el firewall **refuerza** el aislamiento; el escaneo vive en el plano CI sin tocar el guardarraíl de runtime (R-106).
- RNF-NO-REGRESION Cero regresión de #1–#10; suites verdes sin modificar asserts; `/metrics`/logging/healthchecks/RLS/CORS intactos.
- RNF-REPRO Las pruebas (429, no-root, headers, escaneo que falla) y las auditorías son **reproducibles y documentadas** (evidencia auditable).
- RNF-C3 Ningún secreto en tests/fixtures/checklist; credenciales de prueba ficticias; grep de ausencia de secretos en el repo/logs; el agente no genera credenciales.
- RNF-DOCS-ACOTADO Solo se actualiza `DEPLOYMENT_CHECKLIST.md` (checkboxes → artefactos reales); el `RUNBOOK.md` operativo no se reescribe (Q2=A); backups DIFERIDOS no se mencionan (Q6=A).

## Criterios de aceptación (verificables)
- [ ] Exceso por IP/endpoint → **429**; ráfaga legítima de webhooks → **sin** 429; coexiste con `LoginRateLimiter` (CE-106).
- [ ] `docker exec <api>/<worker> whoami` ≠ root; sin `--reload`; escrituras a `audio_store` cifrado/modelos/`tmp` intactas; suites #4/#5/#6 verdes (CE-104/CE-105).
- [ ] HSTS `max-age=31536000` + CSP estricta sin `'unsafe-inline'` emitidos; `/docs` usable (excepción acotada) o Swagger OFF en prod; `security_headers.py` = `DEPLOYMENT_CHECKLIST.md` (CE-110).
- [ ] Una **dependencia vulnerable sembrada** pone el CI en **rojo** (gate HIGH/CRITICAL); Dependabot presente; `requirements.txt` 100% `==`; `check-externos-backend.sh` verde sin relajar allowlist (CE-107).
- [ ] **Auditoría BLACK WIDOW:** ningún endurecimiento relajó RLS/egress/secretos/PHI; el escaneo no relajó la allowlist (R-106); el firewall reforzó `ia_internal`; cero secretos en el repo/logs (CE-112).
- [ ] Suites #1–#10 verdes **sin modificar asserts**; `test_rls_isolation`/`test_auth_cross_tenant_rls`/`test_config_and_cors` verdes; `check-externos-backend.sh` verde (CE-112).
- [ ] `DEPLOYMENT_CHECKLIST.md`: cada ítem abordado (firewall/puertos/TLS/headers/escaneo) apunta a un **artefacto real** del repo; `RUNBOOK.md` NO reescrito; backups no mencionados (CE-113).

## Notas de seguridad (C3/C6)
- C3: ningún secreto/PHI real en tests/fixtures/checklist; credenciales de prueba ficticias; grep de ausencia de secretos en el repo/logs verificado; el agente no genera credenciales.
- C6: esta SPEC **cierra el DoD**; aplicar los endurecimientos (límites, rate-limit, firewall, puertos, TLS) en el entorno real sigue siendo un **cambio sensible** → aprobación del Lead + notificación antes de desplegar (reafirmado desde SPEC-080/081/083).

## Restricción SENSIBLE / egress
- 🔴 SENSIBLE (sin egress nuevo): esta SPEC es la **puerta de evidencia** de todo PLAN-011. La auditoría de **no-relajación de invariantes** (RLS/egress/secretos/PHI, BLACK WIDOW) es el criterio de seguridad top de la SPEC: un endurecimiento que relajara la allowlist de egress (R-106), rompiera el aislamiento `ia_internal`, debilitara el fail-fast de secretos o el cifrado de audio (PHI, ADR-009) sería una **REGRESIÓN de seguridad** disfrazada de mejora. `check-externos-backend.sh` verde sin relajar allowlist; el firewall (ADR-016) **refuerza** `ia_internal`; `graph.facebook.com` (ADR-006) no se toca; ningún dominio/IP nuevo. **Sin ADR nuevo en esta SPEC** (el único ADR de la fase es ADR-016, de SPEC-083).

## Riesgos
- R-103..R-109 (**cierre**): esta SPEC **cierra** todos los riesgos del plan verificando sus mitigaciones — R-103 (límites no asfixian STT/IA: informe de THOR de SPEC-080 presente), R-104 (escrituras legítimas intactas), R-105 (ráfaga legítima sin 429), R-106 (escaneo en plano CI, allowlist no relajada — **auditado explícitamente**), R-107 (excepción de CVE auditable presente), R-108 (puertos cerrados sin romper operación), R-109 (`/docs` usable con CSP estricta). La auditoría de no-relajación de invariantes y la no-regresión #1–#10 son la evidencia final (CE-112/CE-113).

## Checkpoints aplicables
- C3 (secretos: cero en tests/fixtures/checklist/logs; credenciales de prueba ficticias; el agente no genera credenciales — crítico). C4 (criterios verificables — 429, no-root, headers, gate rojo ante vuln sembrada, no-regresión). C6 (aplicar los endurecimientos en el entorno real = cambio sensible → aprobación del Lead + notificación; esta SPEC cierra el DoD). C8 (origen `prompt-lab/prompts/PROMPT-011-HARDENING-PRODUCCION.md`).
