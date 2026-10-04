# SPEC-091 — Pruebas + simulador de webhook de Instagram FIRMADO + runbook del canal (con el bloqueo de Meta App Review EXPLÍCITO) + deploy on-prem — CIERRA PLAN-012 (F6) 🔴 SENSIBLE

- Estado: CERRADA · Responsable: HAWKEYE · Colaboran/revisan: BLACK PANTHER, BLACK WIDOW, WOLVERINE, QUICKSILVER (deploy) · Prioridad: ALTA · Tipo: PRUEBAS/DOCS/DEVOPS/NO-REGRESIÓN · Fase: F6
- Deriva de: PLAN-012 (F6, §2.IN.8, §4 tabla F6, §5, §6 R-110..R-117 (cierre), §7 CE-114/CE-120, §9, §10, §1.5/§1 bloqueo de Meta App Review) · Clasificación: SENSIBLE (`.no-externo`) · **Depende de SPEC-085..090** (prueba el conjunto completo y cierra el plan) · Espeja el simulador de webhook firmado de WhatsApp (SPEC-034) y las suites de WhatsApp (SPEC-033); `RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md`, `docker-compose.yml` · ADR-006/007/009/016/017(si aplica) · **CIERRA PLAN-012**

## Objetivo

**Cerrar PLAN-012** con la tanda de pruebas, el simulador firmado, el runbook y el deploy, documentando explícitamente el límite externo de Meta App Review sin edulcorarlo: (1) HAWKEYE escribe el **simulador de webhook de Instagram FIRMADO** (HMAC-SHA256, espejo del de WhatsApp, SPEC-034) — challenge GET, mensaje, duplicado por `mid`, status; (2) tests de **idempotencia por `mid`**, **test cross-tenant que DEBE fallar**, tests del **parser ante payloads reales/malformados**, tests de media (attachments) con el simulador, y verificación e2e con **cuentas de prueba de Meta** dentro de lo posible sin App Review aprobado; (3) **documenta explícitamente el límite E2E por el bloqueo de Meta App Review (R-110)** en el runbook, sin ocultarlo; (4) **runbook del canal Instagram** (sección nueva o archivo nuevo) con alta de la app de Meta, webhook/verify-token, secret manager de `INSTAGRAM_*`, ventana de mensajería de IG, rotación de token, y el bloqueo de App Review explícito; (5) **deploy on-prem** de los servicios Docker de IG (QUICKSILVER, con **aprobación explícita del Lead antes de desplegar**, secretos reales DIFERIDOS, mismo patrón que deploys anteriores).

## Contexto

Verificado en el repo (fuente de verdad — 2026-10-03):
- **El simulador de webhook firmado de WhatsApp es la plantilla** (SPEC-034): emite POST con firma HMAC-SHA256 válida (webhook acepta 200) e inválida (401), un duplicado por `wamid` (idempotencia) y un callback de status (conciliación), todo en local sin secretos reales (placeholders). El simulador de IG lo espeja con el formato `object:"instagram"`/`entry[].messaging[]` y la clave `mid`.
- **Suites de WhatsApp como plantilla** (SPEC-033): idempotencia, cross-tenant que falla, parser ante payloads reales/malformados. Las de IG las espejan con el formato/claves de Instagram.
- **🔴 BLOQUEO DE META APP REVIEW (R-110, riesgo TOP del plan, §1.5):** la Instagram Messaging API exige App Review de Meta (`instagram_manage_messages`, `instagram_basic`, `pages_messaging`) + cuenta IG Business vinculada + tokens reales. Sin App Review, la app **solo intercambia mensajes con cuentas de rol de prueba** (admins/testers/developers), NO con usuarios reales. Prerequisitos que SOLO el Lead/negocio aporta (app de Meta, cuenta IG Business, App Review aprobado, tokens reales). **Q1=B (vinculante):** el equipo construye y verifica TODO con **payloads firmados simulados + cuentas de prueba**; la activación con usuarios reales queda **DIFERIDA al Lead** cuando Meta apruebe. HAWKEYE **documenta el límite E2E explícitamente, no lo oculta ni lo fuerza** — es puerta externa C6.
- **Deploy sensible (C6):** habilitar el canal real + secretos reales + App Review = cambio sensible → **aprobación explícita del Lead + notificación** antes de desplegar a usuarios reales (mismo patrón que deploys anteriores con secretos reales diferidos).

## Alcance

### IN
- **Simulador de webhook de IG firmado** (espejo de SPEC-034): emite `GET` challenge (token válido/ inválido), `POST` firmado (HMAC-SHA256 válido → 200 encola; inválido/ausente → 401 sin encolar), un **duplicado por `mid`** (idempotencia), un payload con **attachments** (media, SPEC-088) y — según el mecanismo de statuses de IG (SPEC-089) — un callback de status; todo en local, con **placeholders, sin secretos reales**.
- **Tests** (HAWKEYE, espejo de SPEC-033):
  - Idempotencia por `mid`: webhook reentregado con el mismo `mid` → un solo `Message`/borrador (CE-117, verifica SPEC-087).
  - **Cross-tenant que DEBE fallar:** evento con `instagram_account_id`/`mid` de otro tenant NO cruza tenants (RLS/enrutado, CE-116); sin mapeo → descarte auditado sin escritura.
  - Parser ante payloads `object:"instagram"` reales/malformados (no revienta, CE-115).
  - Media: payload con attachments → descarga a almacén cifrado (verifica SPEC-088, con el host confirmado).
  - Firma: válida/inválida/ausente (verifica SPEC-086/R-112).
  - e2e con cuentas de prueba de Meta **dentro de lo posible** sin App Review aprobado (modo desarrollo); el alcance alcanzado vs diferido queda en un informe de HAWKEYE.
- **Runbook del canal Instagram** (sección nueva en `RUNBOOK.md` o archivo nuevo): alta de la app de Meta, cuenta IG Business/Página vinculada, configuración del webhook + `INSTAGRAM_VERIFY_TOKEN`, secret manager de los `INSTAGRAM_*`, **ventana de mensajería de IG** (message tags, NO HSM, SPEC-089), rotación de token, y **el bloqueo de Meta App Review documentado EXPLÍCITAMENTE** (qué permisos faltan, qué se puede verificar con cuentas de prueba, qué queda diferido al Lead) — sin edulcorarlo. `DEPLOYMENT_CHECKLIST.md` actualizado con los artefactos del canal IG si aplica.
- **Deploy on-prem** de los servicios Docker de IG (`instagram_inbound_worker`, `instagram_send_worker`), endurecidos (PLAN-011), con `docker compose up` reproducible y SOLO el path del webhook expuesto por HTTPS; **con aprobación explícita del Lead antes de desplegar** (C6), secretos reales DIFERIDOS.

### OUT
- Implementar datos/webhook/worker/media/envío/seguridad (SPEC-085..090) → aquí se **prueban/documentan/despliegan**, no se implementan.
- **Gestionar/acelerar Meta App Review** (trámite externo del Lead/negocio con Meta).
- Verificación E2E con **usuarios reales** (BLOQUEADA tras App Review, R-110; responsabilidad del Lead).
- Reescribir procedimientos operativos no relacionados con el canal IG.

## Dependencias
- **Depende de SPEC-085..090** (prueba el slice completo y cierra el plan). Reutiliza el simulador/suites de WhatsApp (SPEC-033/034), `check-externos-backend.sh`, `RUNBOOK.md`/`DEPLOYMENT_CHECKLIST.md`, `docker-compose.yml`. **Cierra el DoD de PLAN-012** (§10). Ruta crítica: F0 → F1 → F2 → {F3 ‖ F4} → F5 → **F6 (esta)**.

## Requisitos funcionales
- RF-01 El simulador emite webhooks de IG firmados (challenge, mensaje, duplicado por `mid`, attachments, status) verificables en local con placeholders (CE-114).
- RF-02 Tests verdes: idempotencia por `mid` (CE-117), cross-tenant que **falla** (CE-116), parser real/malformado (CE-115), firma válida/inválida/ausente (R-112), media a almacén cifrado (SPEC-088).
- RF-03 Verificación e2e con cuentas de prueba de Meta dentro de lo posible; informe de HAWKEYE del alcance E2E alcanzado vs **DIFERIDO** por R-110 (CE-114).
- RF-04 Runbook del canal IG con alta/webhook/secret manager/ventana/rotación y el **bloqueo de Meta App Review EXPLÍCITO** (no oculto, no edulcorado) (CE-114).
- RF-05 Deploy on-prem reproducible (`docker compose up`), solo el webhook por HTTPS, servicios endurecidos; **aprobación explícita del Lead antes de desplegar** (C6), secretos reales DIFERIDOS.
- RF-06 CERO regresión: suites de WhatsApp/RLS/CORS/egress/secretos + `check-externos-backend.sh` verdes (CE-120).

## Requisitos no funcionales
- RNF-LIMITE-E2E-EXPLICITO El límite de verificación E2E con usuarios reales por Meta App Review (R-110) se documenta de forma explícita y auditable (runbook + informe de HAWKEYE); NO se oculta ni se presenta como "completado".
- RNF-SIN-SECRETOS Simulador/tests/runbook/checklist con placeholders; cero secretos reales; credenciales de prueba ficticias; el agente no genera credenciales (C3).
- RNF-REPRO Simulador y tests reproducibles en local (sin egress); deploy reproducible con `docker compose up`.
- RNF-NO-REGRESION Cero regresión del canal WhatsApp ni del resto del backend; suites verdes sin modificar asserts.

## Criterios de aceptación (verificables)
- [ ] El simulador genera un POST con firma HMAC válida que el webhook acepta (200) y uno inválido/ausente que rechaza (401 sin encolar); emite un duplicado por `mid` y un payload con attachments (CE-114/CE-115).
- [ ] Tests verdes: idempotencia por `mid` (un solo `Message`), cross-tenant que **falla**, parser real/malformado, media a almacén cifrado (CE-115/CE-116/CE-117).
- [ ] Informe de HAWKEYE del alcance E2E alcanzado (cuentas de prueba) vs **DIFERIDO** por Meta App Review (R-110) (CE-114).
- [ ] Runbook con alta de la app de Meta, webhook+verify-token, secret manager de `INSTAGRAM_*`, ventana de IG (tags, NO HSM), rotación de token y el **bloqueo de Meta App Review EXPLÍCITO**; placeholders, sin secretos (CE-114).
- [ ] Deploy on-prem reproducible (`docker compose up`), solo webhook por HTTPS, servicios IG endurecidos; registro de la **aprobación explícita del Lead** antes de desplegar (C6).
- [ ] Suites de WhatsApp/RLS/CORS/egress/secretos + `check-externos-backend.sh` verdes sin modificar asserts (CE-120).
- [ ] Barrido: ningún secreto real en simulador/tests/runbook/checklist (C3).

## Notas de seguridad (C2/C3/C6)
- C2: simulador/tests sin PII real; logs de descarte solo con metadatos.
- C3: 🔴 placeholders en todo; secretos reales solo en env del operador; el agente no genera credenciales.
- C6: 🔴 el deploy del canal real + secretos reales + el paso por Meta App Review es cambio sensible → **aprobación explícita del Lead + notificación** antes de desplegar a usuarios reales; la activación con usuarios reales queda DIFERIDA al Lead.

## Restricción SENSIBLE / egress
- 🔴 SENSIBLE: el simulador corre en local (sin egress); los tests no abren egress a Meta; el deploy respeta la excepción de egress (ADR-006 ampliado + ADR-017 si aplica): IA sin salida, transporte solo a `graph.facebook.com` (+ CDN de media si aplica) desde `instagram/`. **Bloqueo de Meta App Review (R-110):** TODO se verifica con payloads firmados simulados + cuentas de prueba; la activación con usuarios reales queda DIFERIDA al Lead, documentada explícitamente (no oculta). Deploy = C6 (aprobación + notificación).

## Riesgos
- R-110 (**top del plan** — bloqueo de Meta App Review): documentado explícitamente en el runbook + informe de HAWKEYE; el desarrollo/pruebas no esperan a Meta; la activación real es puerta externa del Lead (C6).
- R-111..R-117 (**cierre**): esta SPEC verifica sus mitigaciones — cross-tenant que falla (R-111), firma HMAC (R-112), idempotencia por `mid` (R-113), egress acotado/allowlist verde (R-114), host de media confirmado (R-115), ventana de IG documentada (R-116), cero regresión de WhatsApp (R-117).

## Checkpoints aplicables
- C2 (minimización, sin PII en simulador/tests). C3 (placeholders, cero secretos reales, 🔴 crítico). C4 (criterios verificables, con la salvedad E2E explícita de R-110). C6 (🔴 deploy sensible: aprobación del Lead + notificación; activación con usuarios reales diferida). C8 (origen PLAN-012 / `prompt-lab/prompts/PROMPT-012-INSTAGRAM-DM.md`).
