# SPEC-082 — Escaneo de vulnerabilidades en CI con gate BLOQUEANTE en HIGH/CRITICAL: `pip-audit` + `bandit` (SAST Python) en `backend-ci.yml`, `npm audit`/equivalente en `ci.yml`, `.github/dependabot.yml` nuevo, sin romper los gates existentes (lint/test/cobertura/egress); INVARIANTE CENTRAL: el escaneo corre SOLO en el runner de CI (plano CI, con egress), JAMÁS se confunde con el runtime on-prem aislado, y `check-externos-backend.sh` sigue auditando el código/runtime sin relajarse (R-106); excepción de CVE auditable (allowlist versionada con justificación + fecha, decisión del Lead, nunca desactivación global del gate) 🔴 SENSIBLE

- Estado: APROBADA (bloque SPEC-080..084, 2026-10-02) · Responsable: WOLVERINE (CI/calidad: integra `pip-audit`/`bandit`/`npm audit`/Dependabot sin romper gates existentes) · Colaboran/revisan: BLACK WIDOW (**criterio de severidad y política de excepciones de CVE**), HAWKEYE (prueba de que una dependencia vulnerable sembrada hace fallar el gate), BLACK PANTHER · Prioridad: ALTA · Tipo: CI/CALIDAD/SEGURIDAD-SUPPLY-CHAIN · Fase: F2
- Deriva de: PLAN-011 (F2, §1 H-3, §2.IN.3, §3.1 (dos planos), §3.5, §4, §5, §6 R-106/R-107, §7 CE-107/CE-108, §9, §10 · R-106/R-107 · CE-107/CE-108) · Clasificación: SENSIBLE (`.no-externo`) · Consume `.github/workflows/backend-ci.yml`, `.github/workflows/ci.yml`, `backend/requirements.txt` (100% `==`), `backend/check-externos-backend.sh` (NO se toca ni se relaja) · Crea `.github/dependabot.yml` · Independiente de SPEC-080/081 (toca solo workflows + `dependabot.yml`) · Prerequisito conceptual de SPEC-084

## Objetivo

Añadir **escaneo de vulnerabilidades en CI** con **gate BLOQUEANTE en severidad HIGH/CRITICAL** (Q5=A): `pip-audit` (dependencias backend) + `bandit` (SAST Python) integrados en `backend-ci.yml`, `npm audit`/equivalente en `ci.yml`, y un `.github/dependabot.yml` nuevo — **sin romper** los gates existentes (lint/test/cobertura≥80%/egress). **INVARIANTE CENTRAL de esta SPEC (R-106):** el escaneo vive **SOLO en el runner de CI** (plano CI, que SÍ tiene egress a internet para consultar bases de CVEs online); **JAMÁS se confunde con el runtime on-prem aislado**, y `check-externos-backend.sh` **sigue auditando el código/runtime, no el CI** — no se toca ni se relaja su allowlist. Incluye un **mecanismo de excepción de CVE auditable** (allowlist versionada con justificación + fecha de revisión, **nunca** desactivación global del gate), cuya decisión es **siempre del Lead, nunca del agente**. `requirements.txt` sigue 100% `==`. Es trabajo **aditivo** sobre los workflows; no toca el runtime, el egress ni la seguridad de aplicación.

## Contexto

Verificado en PLAN-011 §1.4/§3.1/§3.5 y en el repo (fuente de verdad, no asunciones — 2026-10-02):
- **Escaneo de vulnerabilidades AUSENTE.** `backend-ci.yml` corre `black`/`flake8`/`mypy`/`check-externos-backend.sh`/`pytest`+cobertura≥80% + smoke de carga, pero **NO** `pip-audit`/`safety`/`bandit`/`trivy`. `ci.yml` (frontend) corre lint/build/test/Lighthouse pero **NO** `npm audit`. **NO existe `.github/dependabot.yml`.** Base sólida: `requirements.txt` 100% pinneado con `==` (sin rangos abiertos) → escaneo **reproducible**.
- **Los dos planos NUNCA se confunden (§3.1 — el eje de toda la fase, invariante central de esta SPEC, R-106):**
  - **PLANO CI** (runner de GitHub, **CON egress a internet**): `pip-audit`/`bandit`/`npm audit` consultan bases de CVEs **online** → requieren egress (lo tienen, es el runner). Dependabot abre PRs. Gate BLOQUEANTE HIGH/CRITICAL.
  - **PLANO RUNTIME on-prem** (host CPU-only, **aislado**): NUNCA consulta CVEs online; el host no tiene egress de IA (`ia_internal internal:true` + firewall `nftables` de SPEC-083). `check-externos-backend.sh` sigue auditando el **código/runtime**, NO el CI.
  - **El error más peligroso de la fase** sería interpretar el egress del escáner como egress del host, o "ajustar" `check-externos-backend.sh` para tolerar el egress del escáner → **regresión del guardarraíl**. Esta SPEC lo prohíbe explícitamente: Dependabot/pip-audit viven en `.github/`, nunca en el runtime; `check-externos-backend.sh` **no se toca**.
- **Gate bloqueante manejable (R-107):** una CVE HIGH/CRITICAL sin fix disponible no debe volver el gate inmanejable. Se incluye un mecanismo **auditable y acotado** de excepción: **allowlist de CVE versionada** con justificación + fecha de revisión, **NUNCA** desactivación global del gate. La decisión de añadir una excepción es **del Lead, no del agente** (C3/gobernanza). Ninguna CVE se silencia sin registro.

## Alcance

### IN
- **`pip-audit` en `backend-ci.yml`** (dependencias del backend) con **gate BLOQUEANTE en HIGH/CRITICAL** (el job falla), sin romper los gates existentes (lint/test/cobertura/egress).
- **`bandit` (SAST Python) en `backend-ci.yml`** con gate BLOQUEANTE en HIGH/CRITICAL (findings de seguridad en el código).
- **`npm audit`/equivalente en `ci.yml`** (frontend) con gate BLOQUEANTE en HIGH/CRITICAL.
- **`.github/dependabot.yml` nuevo** (actualizaciones de dependencias de backend/frontend y, si aplica, GitHub Actions).
- **Mecanismo de excepción de CVE auditable:** allowlist versionada (archivo en el repo) con **justificación + fecha de revisión** por cada CVE excepcionada; **nunca** desactivación global del gate; la decisión de excepción es **del Lead**. Se documenta el procedimiento.
- **Invariante de los dos planos explícita:** el escaneo corre **solo en el runner de CI**; `check-externos-backend.sh` **no se toca ni se relaja**; `requirements.txt` sigue 100% `==`.

### OUT
- **Contenedores/Dockerfile** → SPEC-080 (F0). **Rate-limiting** → SPEC-081 (F1). **Firewall/puertos/TLS/headers** → SPEC-083 (F3). **Pruebas consolidadas (incl. la prueba de dependencia sembrada que FALLA el gate) + docs** → se **verifican/consolidan** en SPEC-084 (F4); esta SPEC implementa el gate.
- **Relajar `check-externos-backend.sh`** para tolerar el egress del escáner → PROHIBIDO (R-106, invariante central). El guardarraíl audita el runtime/código, no el CI.
- **Escáner SaaS de pago** (Snyk comercial, etc.) → fuera de alcance (ADR-005, self-hosted/CI gratuito). `trivy` de imagen es opcional/futuro, no exigido aquí.
- **Correr el escaneo desde el host on-prem aislado** → PROHIBIDO (confusión de planos, R-106): el host no tiene egress de CVEs online; el escaneo es del runner de CI.
- **Mapear a un marco de compliance formal** (SOC2/ISO/HIPAA/PCI) → fuera de alcance (Q5-sub=A: buenas prácticas, sin certificación).
- **Desactivar el gate globalmente** ante una CVE → PROHIBIDO (R-107): solo allowlist acotada, versionada, justificada, decidida por el Lead.
- **CD/staging** (Q3=A) y **backups** (Q6=A, DIFERIDOS) → fuera de alcance (ver PLAN-011 §2 OUT / PLAN-010 §13).

## Dependencias
- Consume `.github/workflows/backend-ci.yml`, `.github/workflows/ci.yml`, `backend/requirements.txt` (100% `==`) y **no toca** `backend/check-externos-backend.sh`. Crea `.github/dependabot.yml` y el archivo de allowlist de excepciones. **Independiente de SPEC-080/081** (toca solo workflows + `dependabot.yml`); puede correr en paralelo. Único acople: si SPEC-081 añade `slowapi` (pinneado `==`), el escaneo de esta SPEC lo cubrirá. **Prerequisito conceptual de SPEC-084** (que verifica el gate con una dependencia vulnerable sembrada).

## Requisitos funcionales
- RF-01 `backend-ci.yml` ejecuta `pip-audit` (dependencias) y `bandit` (SAST) con **gate BLOQUEANTE en HIGH/CRITICAL** (el job falla), sin romper los gates existentes (CE-107).
- RF-02 `ci.yml` ejecuta `npm audit`/equivalente con **gate BLOQUEANTE en HIGH/CRITICAL** sin romper lint/build/test/Lighthouse (CE-107).
- RF-03 Existe `.github/dependabot.yml` que mantiene las dependencias de backend/frontend (y, si aplica, Actions) (CE-107).
- RF-04 El escaneo corre **solo en el runner de CI** (plano CI); `check-externos-backend.sh` sigue verde **sin relajar su allowlist** (sigue auditando código/runtime, no el CI); `requirements.txt` sigue 100% `==` (CE-107, R-106).
- RF-05 Existe un **mecanismo de excepción de CVE auditable**: allowlist versionada con justificación + fecha de revisión por CVE; **nunca** desactivación global; la decisión de excepción es **del Lead** (CE-108).

## Requisitos no funcionales
- RNF-DOS-PLANOS (R-106, invariante central) El escaneo de CVEs online vive **solo en el runner de CI** (con egress); NUNCA en el host on-prem aislado; `check-externos-backend.sh` audita el **código/runtime**, no el CI, y **no se relaja**; Dependabot/pip-audit viven en `.github/`, nunca en el runtime.
- RNF-GATE-MANEJABLE (R-107) El gate bloqueante HIGH/CRITICAL es manejable: excepción **auditable y acotada** (allowlist versionada, justificación + fecha), nunca desactivación global; decisión del Lead, nunca del agente; ninguna CVE silenciada sin registro.
- RNF-NO-ROMPE-GATES Los gates existentes (lint/test/cobertura≥80%/egress) siguen verdes; el escaneo se añade sin romperlos.
- RNF-REPRO `requirements.txt` sigue 100% `==` → escaneo reproducible; sin regresión a rangos abiertos.
- RNF-C3 Ningún token/credencial del escáner hardcodeado; si alguna herramienta requiere token, va por secret de CI (env), nunca en el repo ni en logs; el agente no genera credenciales.

## Criterios de aceptación (verificables)
- [ ] `pip-audit`+`bandit` corren en `backend-ci.yml` y `npm audit`/equivalente en `ci.yml`, con gate BLOQUEANTE HIGH/CRITICAL; los gates existentes siguen verdes (CE-107).
- [ ] Una **dependencia vulnerable sembrada** deliberadamente hace **fallar** el CI (gate rojo) — verificación consolidada en SPEC-084 (CE-107).
- [ ] `.github/dependabot.yml` presente y activo (CE-107).
- [ ] `check-externos-backend.sh` sigue **verde sin relajar su allowlist** (audita código/runtime, no el CI); `requirements.txt` 100% `==` (grep de `==`) (CE-107, R-106).
- [ ] Existe allowlist de excepción de CVE **versionada con justificación + fecha**; no hay desactivación global del gate; la excepción (si existe) está justificada y es del Lead (CE-108).
- [ ] El escaneo corre **solo en el runner de CI**; no hay ningún paso de escaneo de CVEs online en el runtime on-prem; sin secretos en el repo/logs.

## Notas de seguridad (C3/C6)
- C3: cualquier token del escáner por secret de CI (env), nunca hardcodeado ni en logs; el agente no genera credenciales. La allowlist de CVE contiene solo IDs de CVE + justificación + fecha, nunca secretos.
- C6: no aplica despliegue a infraestructura (esta SPEC vive en `.github/`, plano CI). La decisión de **excepcionar una CVE** es del **Lead** (gobernanza), no del agente; se registra de forma auditable.

## Restricción SENSIBLE / egress
- 🔴 SENSIBLE (sin egress nuevo EN RUNTIME): la **invariante central** de esta SPEC es la **separación de los dos planos (R-106)**. El escaneo consulta bases de CVEs online **solo en el runner de CI** (que ya tiene egress); el **host on-prem sigue aislado** (`ia_internal internal:true` + firewall de SPEC-083). `check-externos-backend.sh` **audita el código/runtime, no el CI**, y **no se relaja** su allowlist: confundir el egress del escáner con egress del host, o ajustar el guardarraíl para tolerarlo, sería la **regresión más peligrosa de la fase**. No se introduce egress nuevo en el runtime; `graph.facebook.com` (ADR-006) no se toca. **Sin ADR nuevo** (el único ADR de la fase es el de firewall de host, SPEC-083/ADR-016); el escaneo en CI no es una decisión de egress de runtime (PLAN-011 §3.5).

## Riesgos
- R-106 (**confusión plano CI ↔ plano runtime / relajar el guardarraíl de egress**): el escaneo de CVEs online se interpreta como egress del host, o `check-externos-backend.sh` se "ajusta" para tolerarlo. Mitigación: §3.1 explícita — escaneo SOLO en el runner de CI; `check-externos-backend.sh` audita código/runtime, NO el CI, y NO se relaja; Dependabot/pip-audit en `.github/`, nunca en el runtime (CE-107). **TOP del plan (invariante central de esta SPEC).**
- R-107 (**el gate bloqueante se vuelve inmanejable**): una CVE HIGH/CRITICAL sin fix bloquea el CI → presión para desactivarlo. Mitigación: gate bloqueante HIGH/CRITICAL (Q5=A) con excepción **auditable y acotada** (allowlist versionada, justificación + fecha, NO desactivación global); decisión del Lead; ninguna CVE silenciada sin registro (CE-108).

## Checkpoints aplicables
- C3 (secretos: tokens del escáner por secret de CI; cero hardcodeados, cero en logs; allowlist sin secretos). C4 (criterios verificables — gate rojo ante dep sembrada, Dependabot presente, allowlist auditable). C6 (no aplica deploy de infra; la excepción de CVE es decisión del Lead, no del agente). C8 (origen `prompt-lab/prompts/PROMPT-011-HARDENING-PRODUCCION.md`).
