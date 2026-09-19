# SPEC-032 — Seguridad del canal + política de egress: auditoría "cero inferencia externa + transporte acotado" 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: BLACK WIDOW · Colaboran: BLACK PANTHER, CAPTAIN AMERICA, HAWKEYE, WOLVERINE · Prioridad: CRÍTICA · Tipo: SEGURIDAD · Fase: F7
- Deriva de: PLAN-003 (F7) · Clasificación: SENSIBLE (`.no-externo`) · ADR-006

## Objetivo

Consolidar y auditar la seguridad del canal: **firma HMAC obligatoria**, **tokens fuera de repo/logs (C3)**, **TLS del webhook**, **aislamiento cross-tenant**, **rate limits de Meta**, y la verificación de la **excepción de egress** (la IA no tiene salida; `api`/`wa_send_worker` solo alcanzan `graph.facebook.com`). Es la puerta de seguridad transversal antes del cierre.

## Contexto

Transversal desde F0/F2, se cierra auditando el conjunto. Consolida las garantías de SPEC-024 (egress/allowlist), SPEC-026 (firma), SPEC-029 (envío/tokens) y SPEC-027/030 (aislamiento cross-tenant), reafirmando ADR-005 para la IA y ADR-006 para el transporte.

## Alcance

### IN
- Auditoría de que la IA (`ia`/`rag_worker`/`sentiment_worker`) NO tiene egress (reafirma ADR-005).
- Verificación de la excepción de egress: `api`/`wa_send_worker` solo a `graph.facebook.com` (allowlist por ruta, ADR-006).
- Barrido de secretos: `WHATSAPP_TOKEN`/`WHATSAPP_APP_SECRET`/`WHATSAPP_VERIFY_TOKEN`/`WHATSAPP_PHONE_NUMBER_ID` ausentes de repo/logs/docs.
- Verificación de firma HMAC obligatoria (401 sin firma) y TLS activo en el webhook.
- Verificación de aislamiento cross-tenant (enrutado + RLS) y de rate limits hacia Meta.

### OUT
- Ejecución de tests de carga/e2e (SPEC-033); implementación de los controles (SPEC-024/026/029).

## Dependencias
- Depende de SPEC-024, SPEC-026, SPEC-027, SPEC-029, SPEC-030. Se ancla en ADR-005 y ADR-006.

## Requisitos funcionales
- RF-01 La auditoría demuestra que la IA no tiene salida a internet.
- RF-02 La auditoría demuestra que el único egress es transporte a `graph.facebook.com`.
- RF-03 La auditoría demuestra secretos fuera de repo/logs, firma HMAC obligatoria y TLS activo.

## Requisitos no funcionales
- RNF-01 Cero inferencia externa (evidencia auditable).
- RNF-03 HABEAS DATA/GDPR-like: TLS, secretos C3, borrado lógico C2.

## Criterios de aceptación (verificables)
- [ ] Prueba de egress: intento de salida desde `ia`/`rag_worker`/`sentiment_worker` **falla** (evidencia registrada).
- [ ] `api`/`wa_send_worker` alcanzan `graph.facebook.com` y **ningún** otro dominio público (evidencia de captura de red).
- [ ] `check-externos-backend.sh` en verde con allowlist por ruta; test negativo (transporte fuera del conector) **falla** la build.
- [ ] Barrido de secretos: ninguno de los 4 tokens aparece en repo/logs/docs (grep/escáner en verde).
- [ ] Webhook rechaza (401) peticiones sin firma HMAC válida; TLS activo verificado.
- [ ] Test cross-tenant demuestra aislamiento (falla por RLS/enrutado); rate limit hacia Meta configurado.

## Notas de seguridad (C2/C3)
- C3: barrido explícito de secretos WhatsApp; fail-fast en env.
- C2: borrado lógico verificado en entidades del canal.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: esta SPEC es la garante de la EXCEPCIÓN de egress (ADR-006): IA sin salida, transporte solo a Meta. Requiere aprobación explícita del Lead + notificación Telegram (C6); barrido BLACK WIDOW obligatorio antes del cierre.

## Riesgos
- R-31 (fuga de egress hacia la IA): prueba de egress vacío + captura de red; allowlist por ruta.
- R-32 (firma HMAC): verificación 401 sin firma.
- R-34 (fuga cross-tenant): test que falla por RLS/enrutado.
- R-37 (tokens expuestos): barrido de secretos en verde.

## Checkpoints aplicables
- C3 (secretos). C4 (criterios verificables). C6 (cambio sensible: seguridad del borde con Meta). C8 (origen PLAN-003).
