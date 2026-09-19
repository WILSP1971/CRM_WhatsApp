# SPEC-026 — Webhook de recepción WhatsApp: challenge GET + firma HMAC-SHA256 + ACK rápido 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, THOR, WOLVERINE · Prioridad: CRÍTICA · Tipo: BACKEND/SEGURIDAD · Fase: F2
- Deriva de: PLAN-003 (F2) · Clasificación: SENSIBLE (`.no-externo`) · ADR-006

## Objetivo

Implementar el endpoint del webhook de WhatsApp con (a) verificación del **challenge GET** de Meta (`hub.mode`/`hub.verify_token`/`hub.challenge`), (b) validación de **firma HMAC-SHA256** `X-Hub-Signature-256` sobre el **raw body** con `WHATSAPP_APP_SECRET` (comparación en tiempo constante), y (c) **ACK 200 rápido (p95 ≤ 500 ms)** encolando el evento de forma asíncrona; sin firma válida → **401**.

## Contexto

Meta requiere un endpoint HTTPS público (detrás del reverse proxy TLS de SPEC-024). El GET verifica el `verify_token` en el alta del webhook; cada POST debe validarse por firma para rechazar tráfico no firmado o falsificado. El proceso pesado (dedup, RLS, persistencia, IA) va en un worker (SPEC-027), no en el request, para evitar reintentos de Meta.

## Alcance

### IN
- `GET` del webhook: valida `hub.mode=subscribe` y `hub.verify_token` contra `WHATSAPP_VERIFY_TOKEN`; devuelve `hub.challenge` en texto plano; token inválido → rechazo.
- `POST` del webhook: calcula HMAC-SHA256 del **raw body** con `WHATSAPP_APP_SECRET`, compara con `X-Hub-Signature-256` en **tiempo constante**; firma ausente/ inválida → **401**.
- ACK 200 inmediato tras validar firma; **encola** el evento crudo en la cola Redis (`wa:inbound`) sin procesamiento pesado.
- Logs estructurados con `trace_id`/`wamid` (sin secretos); métricas de latencia del webhook.

### OUT
- Dedup/enrutado/persistencia (SPEC-027); pipeline IA (SPEC-028); envío (SPEC-029); statuses (SPEC-030).
- Configuración TLS/reverse proxy y allowlist de egress (SPEC-024).

## Dependencias
- Depende de SPEC-024 (TLS/proxy, secretos) y SPEC-025 (persistencia posterior). Prerequisito de SPEC-027. Se ancla en ADR-006.

## Requisitos funcionales
- RF-01 GET con `verify_token` correcto devuelve `hub.challenge`; incorrecto → rechazo.
- RF-02 POST con firma HMAC válida → ACK 200 + evento encolado.
- RF-03 POST sin firma o con firma inválida → **401**, sin encolar.

## Requisitos no funcionales
- RNF-02 Latencia del webhook: **ACK 200 p95 ≤ 500 ms** (medición formal en SPEC-033, THOR).
- RNF-03 Firma obligatoria; comparación en tiempo constante; tokens jamás en logs.

## Criterios de aceptación (verificables)
- [ ] GET con `hub.verify_token` == `WHATSAPP_VERIFY_TOKEN` devuelve `hub.challenge`; token distinto → rechazo.
- [ ] POST con firma HMAC-SHA256 válida sobre el raw body → 200 y evento encolado en `wa:inbound`.
- [ ] POST sin cabecera `X-Hub-Signature-256` → **401**; POST con firma inválida → **401**; ninguno encola.
- [ ] La comparación de firma es en tiempo constante (no early-return por diferencia de bytes).
- [ ] El request del webhook NO ejecuta IA/SQL pesado (solo valida + encola).
- [ ] Los logs no contienen `WHATSAPP_APP_SECRET`/`WHATSAPP_VERIFY_TOKEN` ni el token de firma.
- [ ] p95 del ACK ≤ 500 ms bajo carga (verificado en SPEC-033).

## Notas de seguridad (C2/C3)
- C3: `WHATSAPP_APP_SECRET`/`WHATSAPP_VERIFY_TOKEN` SOLO en env con fail-fast; nunca en repo/logs.
- C2: no crea entidades transaccionales en el request (se hace en el worker).

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el webhook **recibe** de Meta (entrante) tras el proxy TLS; no genera egress de inferencia. Ninguna llamada a IA en el request. Requiere aprobación explícita del Lead + notificación Telegram (C6) por ser componente de borde con Meta.

## Riesgos
- R-32 (firma HMAC mal validada): HMAC-SHA256 sobre raw body, tiempo constante, 401 sin firma; tests válida/ inválida/ ausente (SPEC-033).
- R-38 (latencia > 500 ms): ACK inmediato + proceso 100% asíncrono; medición THOR.
- R-37 (tokens expuestos): secretos en env; redacción de logs.

## Checkpoints aplicables
- C3 (secretos en env). C4 (criterios verificables). C6 (cambio sensible: borde con Meta). C8 (origen PLAN-003).
