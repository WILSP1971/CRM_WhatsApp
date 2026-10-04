# SPEC-089 — Envío saliente por la Graph API de Instagram (`graph_client.py` + `instagram_send_worker`): ventana de mensajería PROPIA de IG (message tags, NO HSM) + conciliación de statuses → `estado_entrega` (F4) 🔴 SENSIBLE

- Estado: APROBADA · Responsable: BLACK PANTHER · Colaboran/revisan: BLACK WIDOW (token/egress), HAWKEYE (human-in-the-loop/statuses), WOLVERINE (no-regresión), DOCTOR STRANGE/BLACK PANTHER (confirmación de message tags contra doc de Meta) · Prioridad: ALTA · Tipo: BACKEND/TRANSPORTE/SEGURIDAD · Fase: F4
- Deriva de: PLAN-012 (F4, §2.IN.1.c/4, §3.1, §3.2 N-5, §3.5, §4 tabla F4, §5, §6 R-116, §7 CE-119) · Clasificación: SENSIBLE (`.no-externo`) · **Depende de SPEC-087** (mensaje persistido) **y de SPEC-019** (borrador aprobado por humano, YA EXISTENTE) **y SPEC-085** (secreto `INSTAGRAM_PAGE_ACCESS_TOKEN`, allowlist/ADR-006 ampliado) · Espeja `backend/app/integrations/whatsapp/graph_client.py` (SPEC-029) y `wa_send_worker` (SPEC-029/030), `backend/app/models/message.py` (`estado_entrega`) · ADR-006/007

## Objetivo

Enviar la **respuesta ya aprobada por un humano** (SPEC-019, borrador `propuesto` → aprobado) por la **Graph API de Instagram**, espejando el envío de WhatsApp pero respetando la **ventana de mensajería PROPIA de Instagram** (message tags, NO plantillas HSM): (1) `app/integrations/instagram/graph_client.py` — ÚNICO módulo autorizado a enviar por la Graph API de IG a `graph.facebook.com`, con **allowlist de host por código** (patrón `_validate_graph_host`), backoff ante 429/5xx, token Bearer nunca en logs; (2) `app/workers/instagram_send_worker.py` — envía el borrador aprobado respetando la ventana de IG (24h estándar, extensible bajo el tag `HUMAN_AGENT` en las condiciones que fije Meta), **NO reutiliza el módulo de plantillas HSM de WhatsApp**; (3) conciliación de los statuses de entrega de IG → `estado_entrega` (monotónica, idempotente, `failed` terminal). **Cero autoenvío:** nada se envía sin aprobación humana previa.

## Contexto

Verificado en el repo (fuente de verdad — 2026-10-03):
- **`graph_client.py` de WhatsApp es la plantilla EXACTA** (SPEC-029): `_ALLOWED_GRAPH_HOST = "graph.facebook.com"` fijo; `_validate_graph_host` valida host EXACTO por `hostname`, `https`, rechaza userinfo/subdominios (líneas 77–112); `_post_with_retries` reintenta 429/5xx con backoff, 4xx no reintentable es `GraphApiError`, transitorio agotado es `GraphApiTransientError` (líneas 177–261); `_headers()` es el ÚNICO punto que materializa el `Authorization: Bearer <token>` y su retorno nunca se loguea (líneas 168–175, C3); `_extract_wamid` lee `messages[0].id` de la respuesta. El envío solo tras aprobación humana del borrador (`wa_send_worker`).
- **La ventana de IG es DISTINTA de WhatsApp (N-5, §3.5):** Instagram tiene su **propia** "standard messaging window" (24h), extensible a 7 días bajo el tag `HUMAN_AGENT` en ciertas condiciones, y **NO usa plantillas HSM** — usa **message tags**. El `instagram_send_worker` implementa la ventana propia de IG; **NO reutiliza** `send_template_message`/`whatsapp_template_*`/`whatsapp_session_window_hours` de WhatsApp (esa es una decisión de arquitecto fijada en el plan: copiar la lógica HSM rompería el envío de IG, R-116). **DOCTOR STRANGE/BLACK PANTHER confirman los message tags soportados (p. ej. `HUMAN_AGENT`) y las condiciones de ventana contra la documentación vigente de Meta ANTES de fijar el comportamiento** (PLAN-012 §12.2, confirmable al implementar).
- **Human-in-the-loop (SPEC-019, Q3=A):** el borrador queda `propuesto`; un agente lo aprueba (`POST .../drafts/{id}/approve`) y recién entonces se encola el envío. El worker de IG consume el borrador **ya aprobado**, igual que `wa_send_worker`; NUNCA decide aprobación.
- **Statuses:** WhatsApp mapea `sent/delivered/read/failed` → `estado_entrega` (`enviado/entregado/leido`/`failed`), monotónico e idempotente, `failed` terminal (`whatsapp_inbound_worker._process_status_event`, SPEC-030). IG expone sus propios callbacks de entrega; el worker de IG los concilia con el MISMO vocabulario `estado_entrega`, conciliados por el id de mensaje de IG (guardado en `messages.wamid`, §3.4).
- **Secreto/allowlist:** `INSTAGRAM_PAGE_ACCESS_TOKEN` (SPEC-085, fail-fast); el host `graph.facebook.com` cubierto por ADR-006 ampliado (SPEC-085); `graph_client.py` de IG vive en `app/integrations/instagram/` (allowlist por ruta).
- **BLOQUEO DE META APP REVIEW (R-110):** el envío se verifica con cuentas de prueba (modo desarrollo de la app de Meta, intercambio real limitado a testers) + simulador; NO con usuarios reales hasta que Meta apruebe `instagram_manage_messages` (Q1=B, DIFERIDO al Lead).

## Alcance

### IN
- **`app/integrations/instagram/graph_client.py`** (espejo de `whatsapp/graph_client.py`): ÚNICO módulo autorizado a enviar por la Graph API de IG; allowlist de host por código (`_validate_graph_host`, host EXACTO `graph.facebook.com`, `https`, sin userinfo/subdominios); `send_message` (texto a `recipient.id`, con el/los message tag(s) de IG cuando aplique); `_post_with_retries` (backoff 429/5xx), `GraphApiError`/`GraphApiTransientError`; token Bearer (`INSTAGRAM_PAGE_ACCESS_TOKEN`) solo en header, nunca en logs; extrae el id de mensaje de IG de la respuesta.
- **Ventana de mensajería de IG (N-5/§3.5):** lógica propia de IG (24h estándar + `HUMAN_AGENT`/tags confirmados contra la doc de Meta); **NO reutiliza el módulo HSM de WhatsApp**. Fuera de ventana sin tag aplicable → el envío se bloquea con motivo explícito (no se arriesga a un rechazo de Meta), `estado_entrega` refleja el bloqueo/`failed` según corresponda.
- **`app/workers/instagram_send_worker.py`** (espejo de `wa_send_worker`): consume el borrador **ya aprobado** (SPEC-019), resuelve el `instagram_business_account_id` emisor (de la conversación / `instagram_accounts`), envía vía `graph_client` respetando la ventana, persiste el id de mensaje de IG en `messages.wamid`, reintentos idempotentes (no reencola un envío ya `enviado`/con id persistido). Servicio Docker endurecido (PLAN-011).
- **Conciliación de statuses de IG → `estado_entrega`** (espejo de SPEC-030): mapeo al vocabulario interno (`enviado/entregado/leido`/`failed`), monotónico e idempotente, `failed` terminal; conciliados por el id de mensaje de IG; motivos de error solo como metadatos (`title`/`code`), nunca contenido ni PII (C2).

### OUT
- Reutilizar el módulo de plantillas HSM de WhatsApp (PROHIBIDO, N-5: IG usa message tags).
- Autoenvío sin aprobación humana (Q3=A, invariante de producto).
- Descarga de media entrante (SPEC-088); recepción/ingesta (SPEC-086/087).

## Dependencias
- **Depende de SPEC-087** (mensaje persistido + conversación), **SPEC-019** (borrador aprobado por humano, ya existente) y **SPEC-085** (secreto `INSTAGRAM_PAGE_ACCESS_TOKEN`, ADR-006 ampliado). Reutiliza el patrón `_validate_graph_host`/backoff y el vocabulario `estado_entrega`. Puede correr en paralelo a SPEC-088 tras SPEC-087.

## Requisitos funcionales
- RF-01 `graph_client.py` de IG envía SOLO a `graph.facebook.com` (allowlist de host por código); un host distinto aborta antes de conectar.
- RF-02 El envío ocurre SOLO sobre un borrador **ya aprobado** por un humano (SPEC-019); **nada se envía automáticamente** (human-in-the-loop intacto).
- RF-03 El envío respeta la **ventana de mensajería de IG** (message tags confirmados contra la doc de Meta, NO HSM); fuera de ventana sin tag aplicable → bloqueo con motivo explícito.
- RF-04 Backoff ante 429/5xx; 4xx no reintentable → `failed`; token Bearer solo en header, nunca en logs (C3).
- RF-05 El id de mensaje de IG se persiste en `messages.wamid` (§3.4); conciliación de statuses → `estado_entrega` monotónica e idempotente; `failed` terminal; motivos solo como metadatos.
- RF-06 Reintentos idempotentes: un envío ya `enviado`/con id persistido no se reencola (no duplica).
- RF-07 Servicio Docker `instagram_send_worker` endurecido (no-root, límites, `no-new-privileges`, `cap_drop`).

## Requisitos no funcionales
- RNF-VENTANA-PROPIA La ventana de IG se implementa con su mecanismo propio (tags), confirmado contra la doc de Meta; NO se copia la lógica HSM de WhatsApp (R-116).
- RNF-C3 `INSTAGRAM_PAGE_ACCESS_TOKEN` solo desde `Settings`, solo en header `Authorization`, nunca en logs ni excepciones.
- RNF-EGRESS-ACOTADO El envío vive SOLO en `app/integrations/instagram/graph_client.py` (+ el worker que lo invoca), SOLO a `graph.facebook.com` (ADR-006 ampliado); la IA sigue sin egress (ADR-005); `check-externos-backend.sh` verde.
- RNF-NO-REGRESION Cola/worker de envío de IG separados de los de WhatsApp; cero regresión del envío de WhatsApp (R-117).
- RNF-STATUS-IDEMPOTENTE La conciliación de statuses es monotónica (no retrocede) e idempotente ante reentregas/desorden; `failed` no revive.

## Criterios de aceptación (verificables)
- [ ] Un borrador aprobado se envía por la Graph API de IG; sin aprobación, **no hay envío** (human-in-the-loop intacto, CE-119).
- [ ] El envío respeta la ventana de IG (message tags confirmados, NO HSM); fuera de ventana sin tag → bloqueo con motivo, no un intento que Meta rechace (CE-119).
- [ ] El estado de entrega se concilia por el id de mensaje de IG → `estado_entrega`; monotónico/idempotente; `failed` terminal (CE-119).
- [ ] Un host distinto de `graph.facebook.com` / userinfo / `http` aborta antes de conectar; `check-externos-backend.sh` verde con el envío SOLO en `instagram/` (CE-118/CE-119).
- [ ] Reintento de un envío ya `enviado` no duplica el mensaje.
- [ ] `docker exec <instagram_send_worker> whoami` ≠ root; `no-new-privileges`/`cap_drop` presentes.
- [ ] Grep de logs: el token Bearer no aparece en ningún log ni excepción (C3); motivos de `failed` solo como metadatos (`title`/`code`), sin contenido/PII (C2).

## Notas de seguridad (C2/C3)
- C2: motivos de error de Meta solo como metadatos (`title`/`code`), nunca contenido del mensaje ni datos del contacto en logs.
- C3: 🔴 token Bearer solo en header, nunca en logs; secreto solo desde `Settings`.

## Restricción SENSIBLE / egress
- 🔴 SENSIBLE: el dato que va a Meta es SOLO el texto de la respuesta ya aprobada por el agente (transporte del canal, no inferencia). Egress SOLO desde `app/integrations/instagram/graph_client.py` (+ el worker), SOLO a `graph.facebook.com` (ADR-006 ampliado, SPEC-085). La IA sigue sin egress (ADR-005). **Bloqueo de Meta App Review (R-110):** el envío se verifica con cuentas de prueba (testers del modo desarrollo) + simulador, NO con usuarios reales hasta que Meta apruebe `instagram_manage_messages` (Q1=B, DIFERIDO al Lead; C6).

## Riesgos
- R-116 (**top** — ventana de IG mal manejada): mecanismo propio de IG (tags) confirmado contra la doc de Meta; NO se copia HSM; `failed`/bloqueo reflejados; documentado en runbook (SPEC-091).
- R-117 (regresión de WhatsApp): cliente/worker de envío de IG separados; no tocan los de WhatsApp.
- R-110 (bloqueo de Meta App Review): verificación con cuentas de prueba + simulador; activación real diferida al Lead (C6).

> **⚠️ NOTA DE REVISIÓN POST-IMPLEMENTACIÓN (2026-10-04, trazabilidad C8):** al implementar RF-05 (conciliación de statuses → `estado_entrega`), se construyó `parse_delivery_events`/`_process_delivery_event` esperando el callback `delivery` (`{"mids": [...], "watermark": ...}`) documentado para el Messenger Platform. **Investigación posterior confirmó (múltiples fuentes consistentes de documentación/soporte de Meta) que el campo de suscripción de webhook `message_deliveries` NO está disponible para Instagram, SOLO para Messenger/Facebook** — los campos que sí soporta Instagram son `messages`/`message_reactions`/`messaging_postbacks`/`messaging_seen`/`messaging_optins`/`messaging_referrals`. En consecuencia, `parse_delivery_events`/`_process_delivery_event` son código **inofensivo pero efectivamente MUERTO**: Meta nunca envía ese callback a este canal, por lo que nunca se ejecutan en producción. **Decisión del Lead (AskUserQuestion, no se reabre):** dejarlo documentado sin tocar el código (no representa un riesgo de seguridad, solo deja RF-05 sin cumplir en la práctica). **Limitación conocida y aceptada:** `estado_entrega` de los mensajes salientes de Instagram queda en `enviado` (confirmado de forma síncrona por el 200 OK de la Graph API, correcto y funcional) y **NO progresa automáticamente a `entregado`/`leido`** — a diferencia de WhatsApp. Una extensión futura podría explorar `messaging_seen` (que sí soporta IG) y su `watermark` para aproximar "leído" de forma agregada (todos los mensajes anteriores a esa marca de tiempo), pero eso es alcance de una SPEC nueva, no de esta. **SPEC-091 debe reflejar esta limitación explícitamente en el runbook del canal**, igual que documenta R-110.

## Checkpoints aplicables
- C2 (minimización en logs). C3 (token fuera de logs, 🔴 crítico). C4 (criterios verificables, con la salvedad E2E de R-110). C6 (envío real con token real a usuarios reales = cambio sensible → aprobación del Lead + notificación). C8 (origen PLAN-012 §3.5 / `prompt-lab/prompts/PROMPT-012-INSTAGRAM-DM.md`).
