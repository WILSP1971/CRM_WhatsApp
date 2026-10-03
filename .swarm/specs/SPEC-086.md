# SPEC-086 — Webhook de recepción de Instagram (challenge GET + firma HMAC sobre RAW body + ACK 200 ≤500ms + encolado `ig:inbound`) + parser puro `object:"instagram"`/`entry[].messaging[]` (F1) 🔴 SENSIBLE

- Estado: APROBADA · Responsable: BLACK PANTHER · Colaboran/revisan: BLACK WIDOW (firma HMAC), HAWKEYE (simulador firmado), WOLVERINE (robustez del parser) · Prioridad: ALTA · Tipo: BACKEND/TRANSPORTE/SEGURIDAD · Fase: F1
- Deriva de: PLAN-012 (F1, §2.IN.1.a/b, §3.1, §3.2 N-1, §4 tabla F1, §5, §6 R-112, §7 CE-115) · Clasificación: SENSIBLE (`.no-externo`) · **Depende de SPEC-085** (cola `ig:inbound` + allowlist por ruta + secretos `INSTAGRAM_*`) · Espeja `backend/app/integrations/whatsapp/webhook.py` (SPEC-026) y `inbound_parser.py` (SPEC-027), `backend/app/core/whatsapp_queue.py`, `backend/app/core/rate_limit_general.py` (SPEC-081) · ADR-006/007

## Objetivo

Construir la **puerta de recepción firmada** del canal Instagram, espejo exacto del webhook de WhatsApp, sin IA ni SQL en el request: (1) `GET /api/v1/instagram/webhook` resuelve el challenge de Meta (`hub.mode=subscribe` + `hub.verify_token == INSTAGRAM_VERIFY_TOKEN` en **tiempo constante** con `hmac.compare_digest` → `hub.challenge` en texto plano; si no, **403**); (2) `POST /api/v1/instagram/webhook` valida la firma `X-Hub-Signature-256` (**HMAC-SHA256 sobre el RAW body** con `INSTAGRAM_APP_SECRET`, `hmac.compare_digest`) **ANTES de parsear**, y si falta/es inválida responde **401 sin encolar**; con firma válida **encola el RAW body** en `ig:inbound` y hace **ACK 200 inmediato** (p95 ≤ 500 ms, sin IA/SQL); **503** si Redis cae (señal de reintento a Meta); rate-limit por IP vía `Depends()` (SPEC-081) ANTES de validar la firma; (3) `inbound_parser.py`, parser **puro sin I/O** del formato `object:"instagram"`/`entry[].messaging[]`, robusto ante malformados.

## Contexto

Verificado en el repo (fuente de verdad — 2026-10-03):
- **`integrations/whatsapp/webhook.py` es la plantilla EXACTA** (SPEC-026): el challenge GET valida token en tiempo constante (`hmac.compare_digest(hub_verify_token, settings.whatsapp_verify_token)`, líneas 71–80) y responde `PlainTextResponse` con 200/403; el POST lee `await request.body()` (bytes EXACTOS) ANTES de parsear, valida con `_is_valid_signature` (HMAC-SHA256 del RAW body, `compare_digest`, sin rama de timing distinta para header ausente vs incorrecto, líneas 83–106), devuelve **401 sin encolar** si la firma falla (líneas 141–151), encola el RAW body con `enqueue_inbound_webhook_event` y responde **200** (líneas 162–178), y **503** si el encolado lanza (Redis caído, líneas 162–174). El rate-limit es `_rate_limit: None = Depends(whatsapp_webhook_rate_limiter)` (SPEC-081), aplicado ANTES del cuerpo del endpoint. El módulo **NO ejecuta IA ni SQL**.
- **`inbound_parser.py` es la plantilla de parser puro** (SPEC-027): sin I/O, `json.loads` + validación de forma, `InboundEventParseError` ante malformados (líneas 119–141), `@dataclass(frozen=True)` para eventos normalizados, robusto (descarta mensajes incompletos sin reventar). El worker captura `InboundEventParseError` y descarta el evento.
- **Formato de Instagram (N-1, distinto de WhatsApp):** `object: "instagram"`, estructura `entry[].messaging[]` con objetos `{sender:{id}, recipient:{id}, timestamp, message:{mid, text, attachments:[{type, payload:{url, ...}}]}}` — **NO** `entry[].changes[].value.messages[]`. La clave de routing es `recipient.id` (el `instagram_business_account_id` receptor). El id de mensaje es `message.mid`. El challenge GET y la firma `X-Hub-Signature-256` (HMAC sobre RAW body) son **el mismo mecanismo** que WhatsApp.
- **La cola `ig:inbound`, los secretos `INSTAGRAM_*` y la allowlist** los deja SPEC-085. El parser vive en `app/integrations/instagram/` (allowlist por ruta); el webhook también vive ahí por la organización del módulo de transporte (no porque llame a Meta — recibe, egress cero), mismo criterio que `whatsapp/webhook.py`.
- **BLOQUEO DE META APP REVIEW (R-110):** esta SPEC se verifica con el **simulador de webhook firmado** (SPEC-091, espejo de SPEC-034) y cuentas de prueba; **NO** con tráfico de usuarios reales hasta que Meta apruebe (Q1=B, DIFERIDO al Lead).

## Alcance

### IN
- **`app/integrations/instagram/webhook.py`** (espejo de `whatsapp/webhook.py`): `APIRouter(prefix="/instagram", tags=["Instagram"])`.
  - `GET /webhook`: `hub.mode=subscribe` + `hub.verify_token == settings.instagram_verify_token` en tiempo constante (`hmac.compare_digest`) + `hub.challenge` presente → `PlainTextResponse(challenge, 200)`; si no, **403** (`PlainTextResponse("Forbidden", 403)`), sin filtrar detalle.
  - `POST /webhook`: `_rate_limit: None = Depends(instagram_webhook_rate_limiter)` (nuevo limitador por IP con umbral holgado en `rate_limit_general.py`, espejo del de WhatsApp) ANTES del cuerpo; `raw_body = await request.body()` (bytes EXACTOS) ANTES de parsear; `_is_valid_signature(raw_body, X-Hub-Signature-256, settings.instagram_app_secret)` con HMAC-SHA256 + `compare_digest` y la MISMA defensa de timing (no distinguir header ausente de incorrecto); sin firma válida → **401 sin encolar**; con firma válida → `enqueue_inbound_instagram_event(redis, raw_body=...)` en `ig:inbound` + **200**; excepción de encolado (Redis caído) → **503**. El endpoint **NO ejecuta IA ni SQL**.
- **`app/core/instagram_queue.py`** (espejo de `whatsapp_queue.py`): `INBOUND_QUEUE_KEY = "ig:inbound"` (cola SEPARADA de `wa:inbound`, R-117), `InboundInstagramJob` (con `event_id`/`raw_body`), `enqueue_inbound_instagram_event`/`dequeue_inbound_instagram_event`.
- **`app/integrations/instagram/inbound_parser.py`** (parser PURO sin I/O, espejo de WhatsApp): `InboundEventParseError` (reutilizable o propio del módulo); `@dataclass(frozen=True) InstagramMessageEvent(mid, instagram_account_id, sender_id, tipo, texto, attachments)` donde `instagram_account_id = recipient.id`, `sender_id = sender.id`, `mid = message.mid`, `texto = message.text` (None si no-texto), `attachments` = lista normalizada de `{type, url}` de `message.attachments[]` (insumo de SPEC-088). `parse_inbound_instagram_events(raw_body)`: `json.loads` + validación `object == "instagram"`/`entry` presente; recorre `entry[].messaging[]`; descarta eventos sin `mid`/`sender.id`/`recipient.id` sin reventar; malformado → `InboundEventParseError`. (Echo-backs/statuses propios de IG que no sean mensajes entrantes se ignoran sin error; la conciliación de statuses salientes se trata en SPEC-089.)
- **Registro del router** en la app FastAPI (mismo punto que el de WhatsApp).

### OUT
- Resolución de tenant, RLS, idempotencia, persistencia, disparo de IA, descarga de media (SPEC-087/088).
- Envío saliente/statuses (SPEC-089).
- Los tests que consumen el simulador firmado (SPEC-091).

## Dependencias
- **Depende de SPEC-085** (cola `ig:inbound`, allowlist por ruta de `app/integrations/instagram/`, secretos `INSTAGRAM_APP_SECRET`/`INSTAGRAM_VERIFY_TOKEN`). Es la puerta de recepción; **habilita SPEC-087** (el worker consume `ig:inbound`). Reutiliza el rate-limiting por `Depends()` (SPEC-081) y el patrón de cola/ACK de WhatsApp.

## Requisitos funcionales
- RF-01 `GET /api/v1/instagram/webhook` resuelve el challenge con token en tiempo constante → `hub.challenge` (200); token/mode inválido → **403** sin filtrar detalle.
- RF-02 `POST` valida `X-Hub-Signature-256` (HMAC-SHA256 sobre el RAW body con `INSTAGRAM_APP_SECRET`, `compare_digest`) ANTES de parsear; sin firma o firma inválida → **401 sin encolar**.
- RF-03 Con firma válida, encola el RAW body en `ig:inbound` y responde **200** (sin IA/SQL); si el encolado falla (Redis) → **503**.
- RF-04 El parser extrae `mid`/`instagram_account_id`(=`recipient.id`)/`sender_id`/texto/attachments de un payload `object:"instagram"` real y **no revienta** ante uno malformado (lanza `InboundEventParseError`).
- RF-05 Rate-limit por IP (umbral holgado, espejo de WhatsApp) aplicado vía `Depends()` ANTES de validar la firma; exceso → 429 sin tocar el cuerpo.

## Requisitos no funcionales
- RNF-ACK ACK 200 p95 ≤ 500 ms; el endpoint NO ejecuta IA ni SQL (solo valida + encola).
- RNF-TIMING La validación de firma usa `hmac.compare_digest` y no introduce una rama de timing distinta entre "header ausente" y "firma incorrecta" (espejo de `whatsapp/webhook.py:83–106`).
- RNF-PARSER-PURO `inbound_parser.py` sin I/O (sin Postgres/Redis/httpx), NO importa `app.workers`/IA/`app.services.rag` (verificado por `check-externos-backend.sh` 8-9, SPEC-085).
- RNF-C3 `INSTAGRAM_APP_SECRET`/`INSTAGRAM_VERIFY_TOKEN` solo desde `Settings`; ni los secretos ni el header de firma recibido se escriben jamás en logs; los logs llevan solo metadatos (`event_id`, `has_signature_header`, `body_length`).
- RNF-COLA-SEPARADA `ig:inbound` es una cola distinta de `wa:inbound` (R-117, cero regresión de WhatsApp).

## Criterios de aceptación (verificables)
- [ ] `GET` con token válido → `hub.challenge` (200); token inválido → **403** (CE-115).
- [ ] `POST` sin firma → **401 sin encolar**; con firma inválida → **401 sin encolar**; con firma válida → encola en `ig:inbound` + **200** (CE-115).
- [ ] Medición: ACK 200 p95 ≤ 500 ms; inspección de que no hay IA/SQL en el request (CE-115).
- [ ] Redis caído en el encolado → **503** (no 500), sin filtrar el secreto ni detalle del error.
- [ ] El parser extrae correctamente `mid`/`recipient.id`/`sender.id`/texto/attachments de un payload `object:"instagram"` real; ante malformado lanza `InboundEventParseError` sin reventar (CE-115).
- [ ] Exceso de peticiones por IP → 429 (rate-limit por `Depends()`), ráfaga legítima sin 429.
- [ ] `check-externos-backend.sh` verde: el módulo `instagram/` no importa IA; `ig:inbound` distinto de `wa:inbound`.
- [ ] Grep de logs: ni `INSTAGRAM_APP_SECRET`/`INSTAGRAM_VERIFY_TOKEN` ni el header de firma aparecen en ningún log (C3).

## Notas de seguridad (C2/C3)
- C2: logs de recepción/descarte solo con metadatos (`event_id`/`body_length`/`has_signature_header`), nunca el contenido del DM.
- C3: 🔴 crítico — secretos solo desde `Settings`; firma recibida jamás logueada.

## Restricción SENSIBLE / egress
- 🔵 SENSIBLE: el webhook RECIBE (egress cero); no llama a `graph.facebook.com`. Vive en `app/integrations/instagram/` por la organización del módulo (allowlist por ruta), no por llamar a Meta. La IA sigue sin egress (ADR-005). **Bloqueo de Meta App Review (R-110):** la recepción se verifica con el simulador firmado (SPEC-091) + cuentas de prueba, NO con tráfico de usuarios reales hasta que Meta apruebe (Q1=B, DIFERIDO al Lead).

## Riesgos
- R-112 (**top de esta SPEC** — firma HMAC mal validada): HMAC-SHA256 sobre el **RAW body** con `compare_digest` ANTES de parsear; 401 sin encolar; defensa de timing uniforme; test firma válida/inválida/ausente (BLACK WIDOW/HAWKEYE).
- R-117 (regresión de WhatsApp): cola `ig:inbound` separada; webhook/parser nuevos, no tocan los de WhatsApp.
- R-110 (bloqueo de Meta App Review): verificación con simulador + cuentas de prueba; activación real diferida al Lead (C6).

## Checkpoints aplicables
- C2 (minimización en logs). C3 (secretos/firma fuera de logs, 🔴 crítico). C4 (criterios verificables). C8 (origen PLAN-012 / `prompt-lab/prompts/PROMPT-012-INSTAGRAM-DM.md`).
