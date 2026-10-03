# PLAN-012 — Canal Instagram Direct Message (Fase D, la ÚLTIMA de 4): segundo canal de mensajería real — Instagram Messaging API de Meta — ESPEJANDO la arquitectura del canal WhatsApp ya en producción (webhook firmado → cola → worker de ingesta idempotente → routing multi-tenant → pipeline IA local human-in-the-loop → envío aprobado), reutilizando al máximo el dominio/pipeline IA/infra YA construidos y aislando SOLO lo genuinamente distinto de Instagram (formato de webhook, clave de routing, secretos/permisos, ventana de mensajería, descarga de media) — con el bloqueo externo de **Meta App Review** como riesgo TOP y puerta externa, SIN reconstruir el dominio, SIN tocar el frontend, SIN notas de voz, SIN autoenvío

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Fecha: 2026-10-03 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo`) — canal de mensajería nuevo que recibe/envía datos personales de contactos sobre un backend multi-tenant (RLS, ADR-004/008) con egress acotado (ADR-005/006/010). Un canal mal aislado (routing cross-tenant, egress nuevo no auditado, secretos en logs, firma de webhook no validada) sería una **REGRESIÓN de seguridad y de HABEAS DATA**, no una funcionalidad nueva.
> Origen: `prompt-lab/prompts/PROMPT-012-INSTAGRAM-DM.md` (🧠 XAVIER, C.R.A.F.T.) — decisiones del Lead a §7 ya **VINCULANTES** (§7.1, 2026-10-03). **NO se reabren** (ver §1, tabla de decisiones).
> Posición en la secuencia ordenada por el Lead: **Fase D de 4, la ÚLTIMA** (1. Onboarding multi-tenant ✅ PLAN-009 · 2. Observabilidad real ✅ PLAN-010 — backups DIFERIDOS · 3. Hardening de producción ✅ PLAN-011 · **4. Instagram Direct Message ← ESTA**).
> Regla de oro: este PLAN **NO genera SPECs ni código**. Las SPEC se redactan como PROPUESTA y solo pasan a implementación tras aprobación explícita del Lead ("APROBADO PLAN-012" y luego "APROBADO SPEC-XXX"). **Dos puertas obligatorias:** primero PLAN, luego SPEC.
> Base que se CONSUME y se REUTILIZA (jamás se rediseña ni se relaja): el canal WhatsApp real (`app/integrations/whatsapp/{webhook,inbound_parser,graph_client,media_client}.py`, `app/workers/whatsapp_inbound_worker.py`, `models/whatsapp_account.py`), el dominio agnóstico de canal (`Conversation.canal` String(50); `app/schemas/conversation.py:15` `CANALES_VALIDOS` YA incluye `"instagram"`), la idempotencia por `messages.wamid` (UNIQUE nullable), el pipeline IA local (RAG SPEC-017/019 + sentimiento SPEC-018), el human-in-the-loop (SPEC-019, borrador `propuesto` + aprobación), el routing `identificador→tenant` con función `SECURITY DEFINER` (ADR-008), la infra de egress acotado (ADR-006, `check-externos-backend.sh`), el fail-fast de secretos (`config.py`, PLAN-011/SPEC-021), la observabilidad (PLAN-010), el rate-limiting general (PLAN-011/SPEC-081) y los contenedores endurecidos (PLAN-011). Estas son **invariantes a reutilizar y, si acaso, reforzar — nunca a tocar**.
> Contadores vigentes (`.swarm/specs.json`, verificados 2026-10-03): `next_plan: 12` (este plan; al cerrarse PLAN-012 pasa a **13**), `next_spec: 85`, `next_adr: 17`. **`next_spec`/`next_adr` NO se reclaman aquí**: se consumen al crear las SPEC/ADR tras "APROBADO PLAN-012". **DECISIÓN de este plan sobre ADR de egress: ver §11** (se amplía ADR-006 para el envío sobre `graph.facebook.com`; se condiciona la creación de **ADR-017** a que la SPEC de media confirme un host de CDN distinto).

---

## 1. Objetivo y contexto

### Objetivo

Añadir un **segundo canal de mensajería real — Instagram Direct Message** vía la **Instagram Messaging API de Meta** (webhook entrante firmado + envío saliente por Graph API) — **espejando la arquitectura del canal WhatsApp ya en producción** end-to-end: recibir DMs por webhook firmado y verificado (challenge GET + HMAC-SHA256 sobre RAW body), encolar + ACK 200 rápido, resolver el **tenant** correcto bajo **RLS**, persistir con el contrato de dominio existente (`Conversation`/`Message`/`Contact`, `canal="instagram"`), disparar el **pipeline IA 100% local** (sentimiento SPEC-018 + borrador RAG con ≥3 citas SPEC-019), someterlo a **human-in-the-loop** (borrador `propuesto` → aprobación del agente, cero autoenvío) y **enviar** la respuesta aprobada por la **Graph API de Instagram** respetando su **ventana de mensajería propia** (message tags, NO plantillas HSM). El alcance V1 cubre **texto + imágenes/adjuntos** (descarga de media a almacén cifrado); **notas de voz quedan fuera**.

Es un trabajo **aditivo y de reutilización masiva**: NO reconstruye el dominio, el pipeline IA ni la infra endurecida. Aísla en módulos nuevos (`app/integrations/instagram/`, `instagram_accounts`, `instagram_inbound_worker.py`, worker de envío) **SOLO lo genuinamente distinto de Instagram**: formato de webhook (`object:"instagram"`/`entry[].messaging[]`), clave de routing (`instagram_business_account_id`/`recipient.id`), secretos/permisos (`INSTAGRAM_*`), ventana de mensajería (message tags), y descarga de media desde el CDN de Meta para Instagram.

### Hallazgo central (refinado por XAVIER, confirmado en código)

El tamaño real es **MENOR** que "reconstruir el Entregable #3 completo". Cuando se construyó WhatsApp (PLAN-003) **no existía** el pipeline IA local disparable sobre un canal, ni el patrón de descarga de media, ni la observabilidad, ni el rate-limiting general, ni el patrón de routing `identificador→tenant` con función `SECURITY DEFINER`. **Hoy todo eso ya existe y se hereda casi intacto.** Lo verdaderamente nuevo de Instagram es un **conjunto acotado de diferencias de transporte + un bloqueo externo de Meta** — no un rediseño del dominio. Por eso el set de SPECs es **más pequeño** que las 11 de WhatsApp (recomendación firme: **7 SPECs**, §8).

### Decisiones del Lead ya VINCULANTES (prompt §7.1, 2026-10-03 — NO se reabren)

| # | Pregunta | Decisión vinculante | Consecuencia de alcance (Instagram DM) |
|---|----------|---------------------|----------------------------------------|
| **Q1 — 🔴 Meta App Review** | **Opción B:** NO resuelto / en trámite. | El equipo **construye y verifica TODO con payloads firmados simulados + cuentas de prueba** (modo desarrollo de la app de Meta). La **activación con usuarios reales queda DIFERIDA al Lead** cuando Meta apruebe. Es el **riesgo TOP (R-110)** y una **puerta externa (C6)**, NO un detalle menor. HAWKEYE documenta explícitamente el límite E2E, no lo oculta ni lo fuerza. |
| **Q2 — Contenido V1** | **Opción B:** Texto + imágenes/adjuntos. | Entra la descarga de media a almacén cifrado (patrón `media_client.py`). **Consecuencia directa:** si el CDN de media de Instagram usa un host distinto de `graph.facebook.com`, es un borde de egress NUEVO que exige su propio ADR acotado (candidato **ADR-017**). Notas de voz (Q2-C) quedan **OUT** de esta V1. |
| **Q3 — Human-in-the-loop** | **Opción A:** reutilizar idéntico. | Borrador RAG en estado `propuesto`, **cero autoenvío**, aprobación humana obligatoria antes de cualquier envío real. No se abre ninguna discusión de política de autoenvío. Invariante de producto. |
| **Q4 — Idempotencia** | **Opción A:** reutilizar `messages.wamid`. | El `mid` de Instagram se guarda en la columna `messages.wamid` existente como "id de mensaje del canal externo" **genérico** (UNIQUE ya existe). La SPEC de datos **documenta** que la columna conserva su nombre pero amplía su significado conceptual (mismo nombre, distinto canal de origen), sin colisión semántica con WhatsApp. |
| **Q5 — Frontend** | **Opción A:** headless/mínimo. | Solo backend + API; a lo sumo un badge/filtro de canal en la Bandeja ya omnicanal (la API ya acepta `canal="instagram"` sin cambios). **Sin trabajo de UI dedicado.** |

### Contexto verificado en código (fuente de verdad, no asunciones — 2026-10-03)

> Hallazgo: el **dominio y la API ya contemplan "instagram"**; lo que falta es **exclusivamente el transporte real** (webhook/parser/worker/clientes de envío y media), de lo cual **no existe nada hoy**.

- **CERO transporte de Instagram.** `app/integrations/` solo tiene `whatsapp/` y `pbx/`. No existe `instagram/`, ni worker, ni tabla, ni secretos `INSTAGRAM_*`.
- **El dominio ya admite `canal="instagram"` SIN migración de datos.** `Conversation.canal` es `String(50)` libre (default `"webchat"`); `app/schemas/conversation.py:15` ya declara `CANALES_VALIDOS = {"whatsapp", "instagram", "messenger", "webchat"}` y `app/api/conversations.py` ya lo documenta (heredado de la maqueta, SPEC-004/008). `Message.wamid` es `String(128)` UNIQUE nullable — clave de idempotencia reutilizable (Q4=A).
- **El canal WhatsApp es el PATRÓN EXACTO a espejar** (código real, verificado): `integrations/whatsapp/webhook.py` (challenge GET en tiempo constante + firma `X-Hub-Signature-256` HMAC-SHA256 sobre RAW body con `hmac.compare_digest` ANTES de parsear + encolado en `wa:inbound` + ACK 200 p95 ≤ 500 ms, 401 sin firma, 503 si Redis cae; rate-limit por IP vía `Depends()` SPEC-081; NO ejecuta IA ni SQL); `inbound_parser.py` (parser puro sin I/O, `object:"whatsapp_business_account"`, robusto ante malformados vía `InboundEventParseError`); `graph_client.py` (ÚNICO módulo autorizado a `POST graph.facebook.com/...`, `_validate_graph_host` host EXACTO, backoff ante 429/5xx, token Bearer nunca en logs); `media_client.py` (dos GETs a `graph.facebook.com` → almacén cifrado `audio_store`, ADR-009, misma allowlist por host); `workers/whatsapp_inbound_worker.py` (resuelve tenant por `resolve_tenant_by_phone_number_id` `SECURITY DEFINER` ADR-008 pre-RLS, descarte auditado sin mapeo, fija RLS, idempotencia por `wamid` guarda+UNIQUE, get-or-create `Contact`/`Conversation(canal="whatsapp")`/`Message`, dispara sentimiento SPEC-018 + borrador RAG SPEC-019 sin autoenvío, modo degradado si el LLM local cae sin revertir la ingesta); statuses `sent/delivered/read/failed` → `estado_entrega`, conciliados por `wamid`, monotónicos e idempotentes (SPEC-030).
- **Pipeline IA local reutilizable TAL CUAL:** `generate_rag_draft` + `draft_review_service.create_draft` (SPEC-017/019) + `schedule_sentiment_analysis` (SPEC-018) ya se invocan desde el worker de WhatsApp sin acoplarse al canal — operan sobre `Conversation`/`Message`. El worker de Instagram los dispara **igual**, sin crear IA nueva.
- **Routing `identificador→tenant` con `SECURITY DEFINER` (ADR-008):** `resolve_tenant_by_phone_number_id` es la plantilla EXACTA para `resolve_tenant_by_instagram_account_id` (resolución pre-RLS de solo lectura, acotada, `search_path` fijo). `models/whatsapp_account.py` es la plantilla de `instagram_accounts`.
- **Egress acotado (ADR-006, `check-externos-backend.sh` sección 7):** la allowlist por ruta YA permite `graph.facebook.com` **SOLO dentro de `app/integrations/whatsapp/`**. Un módulo nuevo `app/integrations/instagram/` necesita **extender esa allowlist por ruta**; secciones 8-9 verifican que el módulo de transporte NO importe IA ni la IA el httpx de transporte — mismo criterio a aplicar a Instagram.
- **Infra heredada endurecida:** fail-fast de secretos (`config.py`, PLAN-011/SPEC-021), observabilidad sin label de tenant (PLAN-010), rate-limiting por `Depends()` (SPEC-081), contenedores no-root con límites (PLAN-011), `docker-compose.yml` con servicios endurecidos de WhatsApp a espejar.

### 🔴 BLOQUEO EXTERNO DURO — Meta App Review (riesgo TOP de todo el plan, §1.5 del prompt)

> Esto NO se edulcora. Es el equivalente, en esta fase, a "los deploys con secretos reales se difieren al Lead" de fases anteriores — pero **más fuerte**, porque depende de un **tercero (Meta) con plazos de días a semanas** fuera del control del equipo.

- La Instagram Messaging API **exige App Review de Meta** con permisos específicos (`instagram_manage_messages`, `instagram_basic`, `pages_messaging`, función "Instagram messaging" habilitada). Sin esa aprobación, la app **solo puede intercambiar mensajes con cuentas de rol de prueba** (admins/testers/developers de la app) — **no con usuarios reales**.
- Prerequisitos que **SOLO el Lead/negocio puede aportar** (no el agente): (a) app de Meta Business creada; (b) cuenta IG Business/Creator vinculada a una Página de Facebook; (c) App Review aprobado para los permisos de mensajería; (d) tokens/secretos reales.
- **Consecuencia (Q1=B):** el equipo **construye y verifica TODO el camino** con (1) tests unitarios/integración con **payloads firmados simulados** (espejo del simulador de WhatsApp, SPEC-034) y (2) **cuentas de prueba/tester** del modo desarrollo de la app de Meta. La verificación con **tráfico de usuarios reales queda BLOQUEADA tras la aprobación de Meta**, responsabilidad del Lead. Esto es **R-110 (riesgo top)** + puerta externa **C6**, documentado explícitamente en el runbook del canal, **no oculto**.

### Invariantes que rigen esta fase (intocables)

- **100% self-hosted / on-premise, CPU-only, sin SaaS/BSP de pago** (ADR-005): transporte **directo a Meta**, sin Twilio/360dialog/ManyChat (un BSP vería el contenido de los DMs → contradice SENSIBLE, mismo criterio que descartó los BSP en ADR-006).
- **La IA sigue sin egress** (`ia_internal internal:true`, ADR-005): el transporte de Instagram vive SOLO en `app`/su worker de envío; el módulo `instagram/` **NUNCA** importa Ollama/IA/`app.workers` (verificado por `check-externos-backend.sh` secciones 7-9). El aislamiento se **refuerza**, nunca se relaja.
- **RLS / PHI / cifrado de media / fail-fast de secretos:** el routing de Instagram fija `tenant_id` ANTES de escribir (nunca bypass del rol `omnicore_app`), la media se cifra en reposo (ADR-009), los `INSTAGRAM_*` usan el fail-fast existente.
- **Human-in-the-loop (Q3=A):** cero autoenvío; el borrador queda `propuesto` hasta la aprobación del agente.
- **CERO regresión del canal WhatsApp** ni del resto del backend: todo cambio es aditivo; las suites de WhatsApp, RLS, egress y secretos siguen verdes sin modificar asserts.

---

## 2. Alcance IN / OUT

### IN — entra en el Entregable de Instagram DM (Fase D)

1. **A · Módulo de transporte `app/integrations/instagram/`** (espejo de `whatsapp/`):
   - `webhook.py`: challenge GET de Meta (token en tiempo constante → `hub.challenge`) + firma `X-Hub-Signature-256` HMAC-SHA256 sobre **RAW body** (`hmac.compare_digest`) ANTES de parsear + encolado del RAW body en `ig:inbound` + **ACK 200** sin IA/SQL (p95 ≤ 500 ms); 401/403 sin firma/token válido, 503 si Redis cae; rate-limit por IP vía `Depends()` (SPEC-081).
   - `inbound_parser.py`: parser **puro sin I/O** del formato `object:"instagram"`/`entry[].messaging[]` (`sender.id`/`recipient.id`/`message.mid`/`message.text`/`message.attachments[]`), normaliza a eventos de dominio; robusto ante malformados (descarta sin reventar).
   - `graph_client.py`: ÚNICO módulo autorizado a enviar por la Graph API de Instagram a `graph.facebook.com`; allowlist de host por código (patrón `_validate_graph_host`), backoff ante 429/5xx, token Bearer nunca en logs (C3), respeto de la ventana de mensajería de Instagram (message tags).
   - `media_client.py`: descarga de adjuntos/imágenes a almacén cifrado (patrón ADR-009), con allowlist de host por código al CDN de media de Meta para Instagram (host a confirmar en la SPEC, §11.2).
2. **B · Routing multi-tenant nuevo:** tabla `instagram_accounts` (espejo de `whatsapp_accounts`, bajo RLS, borrado lógico `activo=False`) + función SQL `resolve_tenant_by_instagram_account_id` (`SECURITY DEFINER`, patrón ADR-008) + migración Alembic aditiva.
3. **C · Worker de ingesta `instagram_inbound_worker.py`** (cola `ig:inbound`, espejo de `whatsapp_inbound_worker.py`): `BLPOP` → resuelve tenant (descarte auditado sin mapeo, cero escritura) → fija RLS → **idempotencia por `mid`** guardado en `messages.wamid` (guarda de worker + UNIQUE de BD) → get-or-create `Contact`/`Conversation(canal="instagram")`/`Message` → encola descarga de media si hay adjuntos → dispara **sentimiento (SPEC-018)** + **borrador RAG ≥3 citas en `propuesto` (SPEC-019)** sin autoenvío → modo degradado si el LLM local cae sin revertir la ingesta → conciliación de statuses de entrega de Instagram.
4. **D · Worker/servicio de envío saliente** (espejo de `wa_send_worker`): envía el borrador **ya aprobado por un humano** (SPEC-019) por la Graph API de Instagram, respetando la **ventana de mensajería de Instagram** (message tags, NO plantillas HSM), con reintentos backoff; concilia `estado_entrega` por el id de mensaje de Instagram.
5. **E · Egress acotado extendido:** ampliar la allowlist por ruta de `check-externos-backend.sh` a `app/integrations/instagram/` para `graph.facebook.com` (envío/media bajo el mismo host); **ampliación de ADR-006** para el envío; **ADR-017 condicional** si la SPEC de media confirma que el CDN de media de Instagram usa un host distinto (§11).
6. **F · Secretos nuevos `INSTAGRAM_*`** (app secret, page access token, verify token, business account id) con el **mismo fail-fast** de `config.py` (PLAN-011/SPEC-021); `.env.example` con placeholders; nunca en repo/logs (C3).
7. **G · Frontend headless/mínimo (Q5=A):** la API ya acepta `canal="instagram"`; a lo sumo un badge/filtro de canal en la Bandeja omnicanal. Sin vista nueva.
8. **H · Pruebas + seguridad + no-regresión + docs:** simulador de webhook de Instagram **firmado** (espejo SPEC-034), idempotencia por `mid`, cross-tenant que **debe fallar**, parser ante payloads reales/malformados, **CERO regresión del canal WhatsApp**; runbook del canal con el **bloqueo de Meta App Review documentado explícitamente** (R-110, C6) + límite E2E; servicio(s) Docker del worker de IG endurecidos (PLAN-011).

### OUT — NO entra en este slice (ya decidido por el Lead o fase futura)

- **Notas de voz entrantes de Instagram** (Q2=B solo texto+imágenes/adjuntos, no audio): **OUT**. No se toca el pipeline STT (`stt:jobs`/`stt_worker`, PLAN-006).
- **Trabajo de frontend/SPA dedicado** (Q5=A): sin vista ni experiencia propia; la Bandeja ya es omnicanal.
- **Autoenvío sin aprobación humana** (Q3=A): rompería el invariante de producto.
- **Gestionar/acelerar el proceso de Meta App Review**: es un trámite externo del Lead/negocio con Meta; el equipo entrega el canal verificable con simuladores + cuentas de prueba (R-110/C6).
- **Facebook Messenger como canal separado** (aunque comparte Graph API): el Lead pidió **Instagram DM**; Messenger sería otra fase (el enum ya lo contempla, pero no está en este encargo).
- **SaaS/BSP intermediario** (Twilio/360dialog/ManyChat): transporte directo a Meta, mismo criterio que WhatsApp.
- **Reconstruir el dominio o la infra ya endurecida:** `Conversation`/`Message`/`Contact`, RAG/sentimiento (SPEC-017/018/019), human-in-the-loop, egress acotado (ADR-006), observabilidad (PLAN-010), rate-limiting (PLAN-011/SPEC-081), contenedores (PLAN-011), fail-fast de secretos (SPEC-021) — se **heredan y extienden**, no se rediseñan.
- **Relajar cualquier invariante** (RLS, `omnicore_app`, aislamiento `ia_internal`, `check-externos-backend.sh`, PHI, fail-fast de secretos): el canal solo REFUERZA.

---

## 3. Arquitectura de referencia

### 3.1 Flujo end-to-end (espejo exacto del de WhatsApp)

```
recepción:  Meta (graph.facebook.com) --POST firmado HMAC X-Hub-Signature-256--> [Webhook FastAPI IG]
            --ACK 200 ≤500ms + encola RAW body--> [Redis cola ig:inbound] --> [instagram_inbound_worker]
            --> resuelve instagram_account_id→tenant (SECURITY DEFINER, pre-RLS) [descarte auditado sin mapeo]
            --> fija RLS --> dedup por mid (guardado en messages.wamid) --> get-or-create
                Contact / Conversation(canal="instagram") / Message
            --> [si adjuntos] encola descarga de media --> media_client --> almacén cifrado (ADR-009)
            --> dispara sentimiento (SPEC-018) + borrador RAG ≥3 citas en 'propuesto' (SPEC-019)
                [TODO on-prem, SIN egress de inferencia]

human-in-the-loop:  [Bandeja SPA omnicanal] <-- borrador citado -- agente revisa/edita/APRUEBA (SPEC-019)

envío:      aprobación --> [instagram_send_worker] --httpx allowlist--> graph.facebook.com (Graph API IG)
            respeta ventana de mensajería de IG (message tags, NO HSM)
            <-- statuses de entrega --> actualiza estado_entrega (conciliado por el id de mensaje IG)
```

### 3.2 Qué es NUEVO vs qué se REUTILIZA (el eje anti-scope de la fase)

```
GENUINAMENTE NUEVO (se construye, aislado en instagram/)   SE REUTILIZA CASI INTACTO (no se toca)
--------------------------------------------------------   ------------------------------------------
N-1 parser object:"instagram"/entry[].messaging[]          dominio Conversation/Message/Contact
N-2 routing por instagram_account_id (tabla + SECURITY     pipeline IA local (RAG/sentimiento SPEC-017/18/19)
    DEFINER resolve_tenant_by_instagram_account_id)        human-in-the-loop (borrador propuesto + aprobación)
N-3 idempotencia por mid → GUARDADO en messages.wamid      columna messages.wamid (UNIQUE, Q4=A)
    (reutiliza la columna, Q4=A)                           challenge GET + firma HMAC sobre RAW body (mecanismo)
N-4 secretos INSTAGRAM_* (fail-fast existente)             fail-fast de config.py (SPEC-021)
N-5 ventana de mensajería IG (message tags, NO HSM)        allowlist de host por código (_validate_graph_host)
N-6 descarga de media desde CDN de IG (host a confirmar)   patrón media_client + almacén cifrado (ADR-009)
    cola ig:inbound + 2 workers nuevos                     observabilidad, rate-limiting, contenedores (PLAN-010/11)
```

### 3.3 Límite de egress (invariante de topología, idéntico a WhatsApp)

- El **conector/worker que habla con Meta** (webhook de IG en `api` + `instagram_send_worker` + descarga de media) vive en la red **`app`** (con egress) y su salida se **restringe por allowlist** a `graph.facebook.com` (envío/Graph API) y — si aplica, §11.2 — al host del CDN de media de Instagram.
- El **contenedor `ia` y los workers de IA** siguen SOLO en `ia_internal` (`internal:true`): **NUNCA** se les añade `app` ni ruta a internet. El módulo `instagram/` **NUNCA** importa Ollama/IA/`app.workers`; los módulos de IA **NUNCA** importan el httpx de transporte de IG (secciones 7-9 de `check-externos-backend.sh`, espejo de WhatsApp).
- **El dato que va a Meta** es solo el **texto/media de la respuesta ya aprobada por el agente** (transporte del canal), nunca una llamada de inferencia.

### 3.4 Idempotencia reutilizando `messages.wamid` (Q4=A) — nota de diseño

La columna `messages.wamid` (`String(128)` UNIQUE nullable) pasa a representar el **"id de mensaje del canal externo" genérico**: para WhatsApp guarda el `wamid`, para Instagram guarda el `mid`. **No colisiona semánticamente** porque: (a) la unicidad es global pero los espacios de id de WhatsApp (`wamid.*`) e Instagram (`mid`) no se solapan en la práctica; (b) la SPEC de datos documenta el nombre conservado + significado ampliado; (c) BLACK PANTHER valida en la SPEC que ningún código asume formato de WhatsApp al leer la columna. Se evita así una migración de esquema y una segunda clave de idempotencia. (Decisión de arquitecto: no se renombra la columna — el coste de una migración de renombrado + actualización de todo el código de WhatsApp supera el beneficio cosmético; se documenta el significado genérico.)

### 3.5 Ventana de mensajería de Instagram (N-5) — por qué NO se copia la lógica HSM de WhatsApp

Instagram tiene su **propia** "standard messaging window" (24h, extensible a 7 días bajo el tag `HUMAN_AGENT` en ciertas condiciones) y **NO usa plantillas HSM** como WhatsApp; usa **message tags**. El `instagram_send_worker` implementa la lógica de ventana propia de Instagram (no reutiliza el módulo de plantillas HSM de WhatsApp). DOCTOR STRANGE/BLACK PANTHER confirman contra la documentación vigente de Meta, en la SPEC de envío, los tags soportados y las condiciones de ventana antes de fijar el comportamiento.

---

## 4. Fases y entregables

| Fase | Nombre | Entregables clave | SPEC (propuesta) |
|------|--------|-------------------|------------------|
| **F0** | **Datos + egress acotado + secretos (B/E/F)** | Tabla `instagram_accounts` (espejo `whatsapp_accounts`, RLS, borrado lógico) + función `resolve_tenant_by_instagram_account_id` (`SECURITY DEFINER`, ADR-008) + migración Alembic aditiva; nota de idempotencia por `mid` en `messages.wamid` (Q4=A, §3.4); allowlist por ruta de IG en `check-externos-backend.sh`; secretos `INSTAGRAM_*` con fail-fast (`config.py`) + `.env.example` placeholders; **ampliación de ADR-006** para el envío. | **SPEC-085** |
| **F1** | **Webhook de recepción (A, parte 1)** | `integrations/instagram/webhook.py`: challenge GET en tiempo constante + firma HMAC-SHA256 sobre RAW body (`compare_digest`) ANTES de parsear + encolado en `ig:inbound` + ACK 200 (p95 ≤ 500 ms) sin IA/SQL; 401/403/503; rate-limit por IP (SPEC-081). `inbound_parser.py`: parser puro `object:"instagram"`/`entry[].messaging[]`, robusto ante malformados. | **SPEC-086** |
| **F2** | **Ingesta idempotente + routing + pipeline IA (C)** | `workers/instagram_inbound_worker.py` (cola `ig:inbound`): resuelve tenant (descarte auditado sin mapeo), fija RLS, idempotencia por `mid`→`wamid`, get-or-create `Contact`/`Conversation(canal="instagram")`/`Message`, dispara sentimiento (SPEC-018) + borrador RAG ≥3 citas `propuesto` (SPEC-019) SIN autoenvío, modo degradado; servicio Docker endurecido (PLAN-011). | **SPEC-087** |
| **F3** | **Descarga de media de Instagram (A, `media_client.py`)** | `integrations/instagram/media_client.py`: descarga de adjuntos/imágenes a almacén cifrado (patrón ADR-009), allowlist de host por código; **confirmación del host real del CDN de media de Meta para Instagram contra la documentación vigente** ANTES de fijar la allowlist; **crea ADR-017 si el host resulta distinto** de `graph.facebook.com` (§11.2); enganche desde el worker de ingesta (F2). | **SPEC-088** |
| **F4** | **Envío saliente + ventana de Instagram + statuses (D)** | `integrations/instagram/graph_client.py` + `workers/instagram_send_worker.py`: envío del borrador **aprobado** (SPEC-019) por la Graph API de IG, allowlist de host, backoff ante 429/5xx, token Bearer nunca en logs; **ventana de mensajería de IG** (message tags, NO HSM, N-5/§3.5); conciliación de statuses → `estado_entrega`; servicio Docker endurecido. | **SPEC-089** |
| **F5** | **Seguridad del canal + no-regresión + frontend mínimo (E/F/G, cierre de seguridad)** | Auditoría BLACK WIDOW: firma HMAC obligatoria, aislamiento/allowlist de egress (ADR-006↔ADR-017), fail-fast `INSTAGRAM_*`, cero fuga cross-tenant (RLS antes de escribir), cero PII/secretos en logs, el módulo IG no importa IA; `check-externos-backend.sh` verde con la allowlist extendida; **CERO regresión** del canal WhatsApp y del resto del backend; badge/filtro de canal "instagram" en la Bandeja (Q5=A, mínimo). | **SPEC-090** |
| **F6** | **Pruebas + simulador firmado + runbook + deploy (H, cierra PLAN-012)** | HAWKEYE: simulador de webhook de Instagram **firmado** (espejo SPEC-034), idempotencia por `mid`, cross-tenant que **debe fallar**, parser ante payloads reales/malformados, e2e con cuentas de prueba; **límite E2E documentado** (R-110); runbook del canal con el **bloqueo de Meta App Review explícito** (C6); deploy on-prem de los servicios IG (QUICKSILVER, con aprobación del Lead). | **SPEC-091** |

> **Nota de división (criterio de arquitecto):** la división sigue las fronteras naturales del transporte y comprime las 10 fases de WhatsApp (F0–F9) a **7** gracias a la reutilización: se **fusiona** datos+egress+secretos en F0 (todas tocan la infra de arranque del canal y comparten la ampliación de ADR-006); el **pipeline IA** NO tiene SPEC propia (como en WhatsApp SPEC-028) porque se dispara **desde el worker de ingesta** reutilizando SPEC-017/018/019 sin componentes nuevos → se integra en F2; la **media** tiene SPEC propia (F3) por su borde de egress con posible ADR-017; **frontend** NO tiene SPEC propia (Q5=A, mínimo) → se integra en F5; **seguridad** (F5) y **pruebas/docs/deploy** (F6) siguen el patrón de WhatsApp (SPEC-032/033/034). Recomendación firme = **7 SPECs**. Ajuste posible (§12): si el Lead prefiere, separar el envío (F4) en graph_client (SPEC) + send_worker/ventana/statuses (SPEC) → 8 SPECs; o fusionar F3 (media) en F2 si el host de media resulta ser `graph.facebook.com` y no requiere ADR → 6 SPECs.

---

## 5. Dependencias entre fases y ruta crítica

- **F0 (SPEC-085 — datos/egress/secretos)** habilita todo: sin tabla de routing, función `SECURITY DEFINER`, allowlist de egress y secretos no hay canal. No depende de fases previas de este plan. Toca migración Alembic, `check-externos-backend.sh`, `config.py`, `.env.example` y amplía ADR-006.
- **F1 (SPEC-086 — webhook/parser)** depende de F0 (necesita la cola `ig:inbound` definida y la allowlist); es la puerta de recepción.
- **F2 (SPEC-087 — ingesta/routing/IA)** depende de F1 (evento encolado) y de F0 (función de routing + idempotencia); reutiliza SPEC-017/018/019. Habilita el borrador para el human-in-the-loop.
- **F3 (SPEC-088 — media)** depende de F2 (el worker encola la descarga) y de F0 (allowlist); es la fase de **mayor incertidumbre** (host del CDN → posible ADR-017).
- **F4 (SPEC-089 — envío/ventana/statuses)** depende de F2 (mensaje persistido) y de SPEC-019 (aprobación); puede avanzar en paralelo a F3 una vez definido el contrato de statuses.
- **F5 (SPEC-090 — seguridad/no-regresión/frontend)** transversal: se diseña desde F0/F1 (firma, egress, secretos) y se **cierra** auditando el conjunto; depende de F1–F4.
- **F6 (SPEC-091 — pruebas/simulador/runbook/deploy)** depende de F1–F5 (prueba el slice completo y cierra el plan).

**Ruta crítica:** `F0 → F1 → F2 → {F3 ‖ F4} → F5 → F6`. F3 y F4 corren parcialmente en paralelo tras F2. El mayor riesgo se concentra en **el bloqueo externo (R-110, transversal a F6/deploy)**, en **F2** (fuga cross-tenant / idempotencia) y en **F3** (host de media no confirmado → ADR-017).

---

## 6. Riesgos y mitigaciones (R-110..R-117 — continúan tras R-109 de PLAN-011)

| # | Riesgo | Impacto | Mitigación |
|---|--------|---------|------------|
| **R-110** | 🔴 **TOP · Bloqueo externo de Meta App Review:** sin `instagram_manage_messages` aprobado + cuenta IG Business vinculada + tokens reales, NO hay mensajería con usuarios reales (solo cuentas de prueba). Depende de un tercero (Meta) con plazos de días a semanas fuera del control del equipo. | **Crítico** (impide la activación real; NO el desarrollo) | **Construir y verificar TODO con payloads firmados simulados + cuentas de prueba** (modo desarrollo de la app de Meta); la **activación con usuarios reales queda DIFERIDA al Lead** cuando Meta apruebe (Q1=B, análogo a deploys con secretos reales diferidos). HAWKEYE documenta el límite E2E explícitamente (no lo oculta). Es puerta externa **C6** (CE-114). |
| **R-111** | **Fuga cross-tenant:** un DM se enruta/persiste en el tenant equivocado (routing por `instagram_account_id` mal resuelto o RLS no fijada antes de escribir). | **Alto** (privacidad, HABEAS DATA) | Función `resolve_tenant_by_instagram_account_id` `SECURITY DEFINER` (ADR-008) pre-RLS de solo lectura; sin mapeo → descarte auditado sin escritura; RLS (`set_tenant_session`) fijada ANTES de cualquier escritura; **test cross-tenant que DEBE fallar** (HAWKEYE); barrido BLACK WIDOW (CE-116). |
| **R-112** | **Firma HMAC mal validada:** aceptar tráfico no firmado o con firma inválida, o validar sobre el body ya parseado (no el RAW). | **Alto** (seguridad del canal) | HMAC-SHA256 `X-Hub-Signature-256` sobre el **RAW body** con `hmac.compare_digest` ANTES de parsear (espejo exacto de WhatsApp); sin firma válida → 401 **sin encolar**; test con firma válida/inválida/ausente (BLACK WIDOW/HAWKEYE) (CE-115). |
| **R-113** | **Idempotencia insuficiente al reutilizar `messages.wamid` (Q4=A):** reentrega del mismo `mid` crea `Message`/borrador duplicado, o colisión semántica con el `wamid` de WhatsApp. | **Alto** (datos/UX) | Idempotencia por `mid` guardado en `messages.wamid` (guarda de worker + UNIQUE de BD, ADR-007); SPEC de datos documenta el significado genérico de la columna (§3.4); BLACK PANTHER valida que ningún código asume formato WhatsApp; test de webhook duplicado que NO crea doble mensaje (CE-117). |
| **R-114** | **Egress no auditado / allowlist mal extendida:** `graph.facebook.com` aparece fuera de `instagram/`, o el host del CDN de media se añade sin ADR, o el módulo IG importa IA. | **Alto** (viola ADR-005/006, falsea el guardarraíl) | Allowlist por ruta extendida SOLO a `app/integrations/instagram/`; secciones 8-9 verifican que IG no importa IA ni la IA el httpx; **host de media confirmado contra doc de Meta antes de fijar la allowlist** y ADR-017 si es host nuevo (§11.2); test negativo (transporte fuera del conector) FALLA la build (CE-118). |
| **R-115** | **Host del CDN de media de Instagram no confirmado / cambia:** la V1 incluye media (Q2=B); si el CDN usa un host distinto de `graph.facebook.com` y se asume el equivocado, la descarga falla o abre un egress no cubierto por ADR. | **Medio-Alto** (rompe media / egress no cubierto) | SPEC-088 **confirma el hostname real del CDN de media de Meta para Instagram contra la documentación vigente ANTES de fijar la allowlist**; si es distinto, SPEC-088 crea **ADR-017** (egress acotado del CDN de media de IG) con allowlist de host por código + entrada en `check-externos-backend.sh`. DOCTOR STRANGE NO fija el host ahora sin esa confirmación (§11.2) (CE-118). |
| **R-116** | **Ventana de mensajería de IG mal manejada:** copiar la lógica de plantillas HSM de WhatsApp (que IG NO usa) → mensajes rechazados por Meta fuera de ventana. | **Medio** (entrega/negocio) | `instagram_send_worker` implementa la ventana propia de IG (message tags, `HUMAN_AGENT`), confirmada contra doc de Meta en SPEC-089 (N-5/§3.5); NO reutiliza el módulo HSM de WhatsApp; estados `failed` reflejados; documentado en runbook (CE-119). |
| **R-117** | **Regresión del canal WhatsApp** al reutilizar la columna `wamid`, la cola/patrón de workers o `check-externos-backend.sh`. | **Medio** (R-39 heredado) | Todo cambio aditivo; cola `ig:inbound` separada de `wa:inbound`; suites de WhatsApp/RLS/egress/secretos verdes sin modificar asserts; migración Alembic no destructiva; `check-externos-backend.sh` verde (CE-120). |

**Top-3:** **R-110 (bloqueo de Meta App Review — crítico, puerta externa, condiciona la verificación E2E real pero NO el desarrollo)**, **R-111 (fuga cross-tenant)**, **R-114 (egress no auditado / allowlist mal extendida)**. R-112 (firma HMAC) y R-113 (idempotencia por `mid` en `wamid`) inmediatamente detrás.

---

## 7. Criterios de éxito verificables (CE-114..CE-120 — continúan tras CE-113 de PLAN-011)

| ID | Criterio | Cómo se verifica | Fase |
|----|----------|------------------|------|
| **CE-114** | **Límite E2E por Meta App Review documentado y respetado (Q1=B):** el equipo verifica TODO lo verificable con payloads firmados simulados + cuentas de prueba; la activación con usuarios reales queda explícitamente marcada como DIFERIDA al Lead (puerta externa C6). | Simulador de webhook firmado verde; runbook con el bloqueo de App Review explícito; informe de HAWKEYE del alcance E2E alcanzado vs diferido. | F6 |
| **CE-115** | **Recepción firmada:** `GET` resuelve el challenge (token en tiempo constante, 403 si no coincide); `POST` rechaza (401) payload sin firma o con HMAC inválida **sin encolar**; con firma válida encola el RAW body en `ig:inbound` y hace **ACK 200** sin IA/SQL (p95 ≤ 500 ms). | Simulador de webhook IG firmado (válido/inválido/ausente); medición de latencia; inspección de que no hay IA/SQL en el request. | F1 |
| **CE-116** | **Enrutado multi-tenant sin fugas:** evento con `instagram_account_id` sin fila → descarte auditado, cero escritura; evento de otro tenant NO cruza tenants (RLS fijada antes de escribir). | Test cross-tenant (HAWKEYE) que **falla**; prueba de descarte sin mapeo auditado; barrido BLACK WIDOW. | F2 |
| **CE-117** | **Idempotencia por `mid` (Q4=A):** webhook reentregado con el mismo `mid` NO crea segundo `Message`/borrador; sin colisión semántica con el `wamid` de WhatsApp. | Test de duplicado → un solo `Message`; inspección de la columna `messages.wamid` con `mid` de IG; nota de diseño §3.4 verificada. | F2 |
| **CE-118** | **Egress acotado extendido sin relajar el guardarraíl:** `check-externos-backend.sh` verde con la allowlist por ruta de `app/integrations/instagram/`; `graph.facebook.com`/CDN de IG NO aparece fuera de ese módulo; el módulo IG NO importa Ollama/IA; host de media confirmado + ADR (006 ampliado / 017 nuevo) presente. | `check-externos-backend.sh` verde; test negativo (transporte fuera del conector) FALLA; inspección del/los ADR; grep de host de media. | F0/F3/F5 |
| **CE-119** | **Envío + ventana + statuses:** un borrador aprobado se envía por la Graph API de IG respetando la ventana de IG (message tags, NO HSM); el estado de entrega se concilia por el id de mensaje de IG; NADA se envía sin aprobación humana. | e2e con cuenta de prueba/simulador; inspección de `estado_entrega`; prueba de que sin aprobación no hay envío (human-in-the-loop intacto). | F4 |
| **CE-120** | **CERO regresión + fail-fast de secretos:** suite de WhatsApp, RLS cross-tenant, CORS, egress, cifrado de media y fases #1–#11 verdes sin modificar asserts; `INSTAGRAM_*` con fail-fast fuera de development; ningún secreto ni PII de contacto en logs. | Suite completa + `test_rls_isolation`/egress/secretos verdes; `check-externos-backend.sh` verde; arranque sin `INSTAGRAM_*` fuera de dev falla; inspección de logs. | F5/F6 |

> Transversales heredados: **aprobación explícita del Lead**; CHECKPOINTS **C2** (minimización: descartes/errores de enrutado loguean solo metadatos `instagram_account_id`/`mid`/`event_id`, NUNCA el contenido del DM ni datos del contacto; borrado lógico `activo=False` en `instagram_accounts`) / **C3** (secretos 🔴 crítico: `INSTAGRAM_*` por env/secret manager con fail-fast; token Bearer solo en el header `Authorization`, jamás en logs) / **C4** (criterios verificables, con la salvedad E2E de R-110) / **C6** (habilitar el canal real + secretos reales + App Review de Meta = cambio sensible → **aprobación explícita del Lead + notificación** antes de desplegar a usuarios reales) / **C8** (origen `prompt-lab/prompts/PROMPT-012-INSTAGRAM-DM.md`). **No existe C9.**

---

## 8. Mapa de SPECs propuestas (SOLO el mapa — se redactan como PROPUESTA, se implementan tras "APROBADO PLAN-012")

> Continúa desde `specs.json` (`next_spec: 85`). Se crearán únicamente tras "APROBADO PLAN-012". Cada SPEC llevará criterios verificables (C4), clasificación SENSIBLE, dependencias y checkpoints citados, con la cabecera/estilo de las SPEC de WhatsApp (SPEC-024..034) y las últimas (SPEC-080..084).

- **SPEC-085** — Datos del canal Instagram + egress acotado + secretos: tabla `instagram_accounts` (RLS, borrado lógico) + función `resolve_tenant_by_instagram_account_id` (`SECURITY DEFINER`, ADR-008) + migración Alembic; idempotencia por `mid` en `messages.wamid` (Q4=A, §3.4); allowlist por ruta de IG en `check-externos-backend.sh`; `INSTAGRAM_*` con fail-fast + `.env.example`; ampliación de ADR-006 (F0).
- **SPEC-086** — Webhook de recepción Instagram: challenge GET + firma HMAC-SHA256 sobre RAW body + ACK 200 ≤ 500 ms + encolado en `ig:inbound`; parser puro `object:"instagram"`/`entry[].messaging[]` robusto ante malformados (F1).
- **SPEC-087** — Ingesta idempotente + enrutado multi-tenant + disparo del pipeline IA local (`instagram_inbound_worker`): dedup por `mid`, resolución de tenant, fijado RLS, persistencia `canal="instagram"`, sentimiento (SPEC-018) + borrador RAG ≥3 citas `propuesto` (SPEC-019) sin autoenvío; servicio Docker endurecido (F2).
- **SPEC-088** — Descarga de media de Instagram (`media_client.py`): adjuntos/imágenes a almacén cifrado (ADR-009), allowlist de host por código; **confirma el host del CDN de media contra doc de Meta y crea ADR-017 si es host nuevo** (§11.2) (F3).
- **SPEC-089** — Envío saliente por la Graph API de Instagram (`graph_client.py` + `instagram_send_worker`): envío del borrador aprobado, ventana de mensajería de IG (message tags, NO HSM), backoff, conciliación de statuses → `estado_entrega`; servicio Docker endurecido (F4).
- **SPEC-090** — Seguridad del canal + no-regresión + frontend mínimo: firma HMAC obligatoria, aislamiento/allowlist de egress (ADR-006↔017), fail-fast `INSTAGRAM_*`, cero fuga cross-tenant, cero PII/secretos en logs, IG no importa IA; cero regresión de WhatsApp; badge/filtro "instagram" en la Bandeja (Q5=A) (F5).
- **SPEC-091** — Pruebas + simulador de webhook firmado + runbook + deploy: idempotencia por `mid`, cross-tenant que falla, parser, e2e con cuentas de prueba; **límite E2E documentado (R-110)**; runbook con el bloqueo de Meta App Review explícito (C6); deploy on-prem de los servicios IG (F6).

> Total: **7 SPECs (SPEC-085..SPEC-091)** → `next_spec` pasaría a **92** al crearlas (no ahora). **ADR: ADR-006 se amplía** (no consume `next_adr`); **ADR-017 se crea SOLO si** la SPEC-088 confirma un host de CDN distinto → `next_adr` pasaría a **18** en ese caso (§11). Opciones de ajuste (§12): (a) separar SPEC-089 en graph_client + send_worker/ventana/statuses → 8 SPECs; (b) fusionar SPEC-088 en SPEC-087 si el host de media resulta ser `graph.facebook.com` → 6 SPECs. Recomendación firme = **7 SPECs**.

---

## 9. Entregables finales de la fase

- Módulo de transporte `app/integrations/instagram/{webhook,inbound_parser,graph_client,media_client}.py`, integrado al backend existente, ejecutable con `docker compose up`.
- `app/models/instagram_account.py` + migración Alembic (tabla + función `SECURITY DEFINER` + RLS + borrado lógico).
- `app/workers/instagram_inbound_worker.py` + `instagram_send_worker` + cola Redis `ig:inbound`.
- Servicio(s) Docker del worker de ingesta/envío de IG, endurecidos como los de PLAN-011.
- Secretos `INSTAGRAM_*` con fail-fast en `config.py` + `.env.example` (placeholders) + `check-externos-backend.sh` con la allowlist por ruta de IG.
- **ADR-006 ampliado** (envío de IG sobre `graph.facebook.com`) + **ADR-017** (CDN de media de IG) **solo si** SPEC-088 confirma host distinto.
- Suite de pruebas (simulador de webhook IG firmado, idempotencia por `mid`, cross-tenant que falla, parser, cero regresión de WhatsApp) + runbook del canal con el **bloqueo de Meta App Review explícito** (R-110, C6).
- **Evidencia auditable:** firma HMAC verificada, routing cross-tenant que falla, egress público SOLO a `graph.facebook.com` (+ CDN de media si aplica) desde `instagram/`, IA sin egress, cero secretos/PII en logs, límite E2E documentado.

## 10. Definition of Done (fase Instagram DM)

1. CE-114..CE-120 cumplidos y evidenciados.
2. **Webhook firmado** (challenge GET + HMAC-SHA256 sobre RAW body, 401 sin firma válida sin encolar) + **ACK 200 p95 ≤ 500 ms** sin IA/SQL.
3. **Idempotencia por `mid`** probada (reentrega no crea doble `Message`/borrador), reutilizando `messages.wamid` sin colisión semántica (§3.4).
4. **Enrutado multi-tenant** probado: test cross-tenant que **falla** por RLS/enrutado; sin mapeo → descarte auditado.
5. Pipeline IA **100% local** sobre Instagram (sentimiento + borrador RAG ≥3 citas, sin IA nueva); `check-externos-backend.sh` verde con la allowlist por ruta de IG extendida.
6. **Egress público únicamente** desde el conector/workers de IG y **solo** a `graph.facebook.com` (+ CDN de media si aplica, cubierto por ADR); IA sin ruta a internet; módulo IG no importa IA.
7. **Human-in-the-loop intacto** (Q3=A): nada se envía sin aprobación humana; el borrador queda `propuesto`.
8. **Envío por la Graph API de IG** respetando la ventana de IG (message tags, NO HSM); statuses conciliados en `estado_entrega`.
9. **Media de Instagram** (Q2=B): adjuntos/imágenes descargados a almacén cifrado (ADR-009); host de CDN confirmado + ADR (006 ampliado / 017 nuevo). **Notas de voz OUT.**
10. **Secretos seguros (C3):** `INSTAGRAM_*` por env con fail-fast, cero hardcodeadas, cero en logs; token Bearer solo en el header.
11. **CERO regresión:** suite de WhatsApp, RLS cross-tenant, CORS, egress, cifrado de media y fases #1–#11 verdes sin modificar asserts; **frontend headless/mínimo** (Q5=A), sin vista nueva.
12. **Bloqueo de Meta App Review documentado** (R-110): verificado con simuladores + cuentas de prueba; **activación con usuarios reales DIFERIDA al Lead** (C6, cambio sensible → aprobación + notificación). **Aprobación explícita del Lead**; ninguna SPEC se cierra sin cumplir los CHECKPOINTS aplicables (C2/C3/C4/C6/C8).

---

## 11. ADRs: ampliar ADR-006 (envío) + ADR-017 condicional (CDN de media) — decisión de arquitecto justificada

### 11.1 Envío de Instagram sobre `graph.facebook.com` → AMPLIAR ADR-006 (no un ADR nuevo)

> **DECISIÓN:** el envío/API de Instagram va al **mismo host `graph.facebook.com`** que ADR-006 ya autoriza para WhatsApp. **No es una decisión de egress nueva**: es la **misma excepción acotada de transporte a Meta**, extendida a un segundo módulo de conector. Por tanto se **AMPLÍA ADR-006** (se añade `app/integrations/instagram/` a la allowlist por ruta de `check-externos-backend.sh` y se nota en el ADR que el egress de transporte a `graph.facebook.com` abarca ahora WhatsApp **e** Instagram), **sin consumir `next_adr`**.

Justificación: crear un ADR separado para "egress de IG sobre `graph.facebook.com`" duplicaría la misma decisión arquitectónica (transporte a Meta, no inferencia, allowlist por ruta, IA sin egress) ya fijada en ADR-006. El criterio del repo es NO forzar ADRs sin una decisión arquitectónica genuinamente nueva. La única diferencia material (la ruta de módulo en el guardarraíl) es un detalle de implementación de SPEC-085, cubierto por la ampliación de ADR-006.

### 11.2 CDN de media de Instagram → ADR-017 CONDICIONAL, decisión diferida a SPEC-088

> **DECISIÓN:** la V1 incluye media (Q2=B). El CDN de media de Meta para Instagram **normalmente usa hosts distintos** de `graph.facebook.com` (dominios tipo `*.cdninstagram.com` / `scontent.*` servidos por Meta). **Pero NO puedo confirmar el hostname exacto con certeza en este momento** (no tengo acceso verificable a la documentación vigente de Meta desde aquí, y la API de Meta evoluciona). Por tanto, como arquitecto, **fijo la regla de decisión** en vez de adivinar el host:
>
> 1. **SPEC-088** (la que implementa `media_client.py` de Instagram) **DEBE confirmar el hostname real del CDN de media de Meta para Instagram contra la documentación vigente de Meta ANTES de fijar la allowlist** de egress.
> 2. **Si el host resulta ser `graph.facebook.com`** (p. ej. porque la descarga pasa por un endpoint de la Graph API) → queda cubierto por la **ampliación de ADR-006** (§11.1), **sin ADR nuevo**.
> 3. **Si el host resulta ser distinto** (CDN propio de Meta para IG) → es un **borde de egress NUEVO no cubierto por ADR-006** → **SPEC-088 crea ADR-017** ("egress acotado del CDN de media de Instagram") con allowlist de host **por código** (patrón `_validate_graph_host`) + entrada nueva en `check-externos-backend.sh`, `next_adr` pasa a 18.

Por qué diferir y no decidir ahora: fijar una allowlist de egress sobre un hostname no confirmado sería un riesgo de seguridad (R-114/R-115) — o rompe la descarga (host equivocado) o abre un egress a un host incorrecto. La decisión correcta de arquitecto, dentro de las decisiones vinculantes del Lead, es **fijar el procedimiento de confirmación + el gatillo del ADR**, no el host. Esto respeta Q2=B (media IN), no reabre ninguna decisión del Lead, y mantiene el guardarraíl de egress intacto. La media **siempre** se cifra en reposo (ADR-009) y se descarga SOLO desde el módulo `instagram/` autorizado, con cualquiera de los dos hosts.

> Invariante reafirmado por ambas decisiones: la IA (`ia_internal internal:true`) sigue sin egress; el transporte de IG vive SOLO en `app`/sus workers; el aislamiento se **refuerza**, nunca se relaja (ADR-005 intacto).

---

## 12. PREGUNTAS ABIERTAS AL LEAD

**Ninguna de alcance.** Las cinco decisiones Q1–Q5 están resueltas y adoptadas como vinculantes (prompt §7.1). La ambigüedad interna genuina (el hostname del CDN de media, Q-ADR) la he resuelto yo como arquitecto **fijando el procedimiento de confirmación + el gatillo condicional de ADR-017** (§11.2), sin generar una pregunta nueva para el Lead. Puntos que se fijan en la SPEC con supuesto por defecto, confirmables al aprobar (NO bloquean el PLAN):

1. **Host del CDN de media de Instagram:** lo confirma SPEC-088 contra la doc vigente de Meta; de ello depende si se amplía ADR-006 o se crea ADR-017 (§11.2). *El Lead no necesita decidir nada aquí; es una verificación técnica de la SPEC.*
2. **Message tags / condiciones de la ventana de IG:** DOCTOR STRANGE/BLACK PANTHER confirman los tags soportados (p. ej. `HUMAN_AGENT`) contra la doc de Meta en SPEC-089 (N-5/§3.5). *Confirmable al aprobar.*
3. **Número de SPECs:** recomendación = **7** (SPEC-085..091). *Opcional: separar el envío → 8, o fusionar la media si el host es `graph.facebook.com` → 6.*
4. **🔴 Meta App Review (recordatorio, NO pregunta):** Q1=B ya vinculante — el desarrollo NO espera a Meta; la activación con usuarios reales es puerta externa del Lead (R-110/C6). *Se re-confirma en el deploy, no bloquea el PLAN.*

---

> **Siguiente paso:** IRON MAN presenta este PLAN-012 al Lead. El Lead debe responder **"APROBADO PLAN-012"** (o "Ajusta PLAN-012: …") antes de que DOCTOR STRANGE redacte las SPEC-085..SPEC-091, amplíe ADR-006 y (condicionalmente) cree ADR-017. Dos puertas obligatorias: primero PLAN, luego SPEC. El **bloqueo de Meta App Review** (R-110) condiciona la verificación E2E con usuarios reales pero **NO** bloquea el desarrollo/pruebas con simuladores + cuentas de prueba. Cumple CHECKPOINT C8 (origen `prompt-lab/prompts/PROMPT-012-INSTAGRAM-DM.md`). `.swarm/specs.json` **NO se actualiza** hasta la aprobación del Lead.
