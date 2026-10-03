# PROMPT-012 — Canal Instagram Direct Message (Instagram Messaging API de Meta)

> Autor: 🧠 XAVIER (Professor X) — Estratega de Prompts (Nivel 1) · skill `optimizar-prompt`
> Fecha: 2026-10-03 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo`) — canal de mensajería nuevo que recibe/envía datos personales de contactos sobre un backend multi-tenant (RLS) con egress acotado (ADR-005/006). Un canal mal aislado (routing cross-tenant, egress nuevo no auditado, secretos en logs, firma de webhook no validada) sería una REGRESIÓN de seguridad y de HABEAS DATA, no una funcionalidad nueva.
> Marco aplicado: **C.R.A.F.T.** (Contexto · Rol · Acción · Formato · Tests)
> Destino: este prompt alimenta a 🔮 **DOCTOR STRANGE** para **PLAN-012** (NO genera SPECs por sí mismo).
> Contadores REALES (`.swarm/specs.json`, verificados 2026-10-03): `next_plan: 12`, `next_spec: 85`, `next_adr: 17`. DOCTOR STRANGE reclama `next_plan:12→13` al abrir PLAN-012; `next_spec`/`next_adr` solo se consumen al crear SPECs/ADRs tras "APROBADO PLAN-012".
> Posición en la secuencia ordenada por el Lead: **Fase D de 4, la ÚLTIMA** (1. Onboarding multi-tenant ✅ PLAN-009 · 2. Observabilidad real ✅ PLAN-010 · 3. Hardening de producción ✅ PLAN-011 · **4. Instagram Direct Message ← ESTA**).
> ⚠️ **Puerta obligatoria:** este prompt NO es aprobación. Requiere PLAN-012 aprobado por el Lead y luego SPECs aprobadas antes de escribir código (CLAUDE.md del enjambre). Además hay un **BLOQUEO EXTERNO DURO de Meta App Review (§1.5)** y **preguntas abiertas VINCULANTES (§7)** que el Lead debe resolver antes de que DOCTOR STRANGE fije alcance.

---

## 0. Resumen del encargo (una frase)

Añadir un **segundo canal de mensajería real** — **Instagram Direct Message** vía la **Instagram Messaging API de Meta** (webhook entrante firmado + envío saliente por Graph API) — **espejando la arquitectura del canal WhatsApp ya en producción** (webhook → cola → worker de ingesta idempotente → routing multi-tenant → pipeline IA local human-in-the-loop → envío aprobado), reutilizando al máximo el dominio (`Conversation`/`Message`/`Contact`), el pipeline RAG+sentimiento y la infra de egress acotado YA construidos, y aislando en módulos nuevos SOLO lo que es genuinamente distinto de Instagram (formato de webhook, clave de routing, secretos/permisos, ventana de mensajería).

> **Hallazgo central de XAVIER:** el tamaño real es **MENOR** que "reconstruir el Entregable #3 completo" (la estimación de PLAN-006). Cuando se construyó WhatsApp (PLAN-003) **no existía** el pipeline IA local disparable sobre un canal, ni el patrón de descarga de media, ni la observabilidad, ni el rate-limiting general, ni el patrón de routing `identificador→tenant` con función `SECURITY DEFINER`. Hoy **todo eso ya existe y es reutilizable casi intacto** (§1.2). Lo verdaderamente nuevo de Instagram es un **conjunto acotado de diferencias de transporte + un bloqueo externo de Meta** (§1.3/§1.5), no un rediseño del dominio.

---

## 1. Contexto (verificado en el repo, NO asumido — qué se reutiliza vs qué es nuevo)

### 1.1 El canal WhatsApp real es el PATRÓN EXACTO a espejar (leído a fondo)

Arquitectura verificada en `backend/app/integrations/whatsapp/` + `backend/app/workers/` (código real, no doc):

- **Webhook entrante** (`integrations/whatsapp/webhook.py`, SPEC-026): `GET /api/v1/whatsapp/webhook` resuelve el **challenge** de Meta (`hub.mode`/`hub.verify_token` en tiempo constante → `hub.challenge`); `POST` valida la **firma `X-Hub-Signature-256` (HMAC-SHA256 sobre el RAW body** con `WHATSAPP_APP_SECRET`, `hmac.compare_digest`) ANTES de parsear, **encola el payload crudo** en Redis (`wa:inbound`) y hace **ACK 200 inmediato** (p95 ≤ 500 ms); 401 sin firma, 503 si Redis cae (señal de reintento a Meta). Rate-limit general por IP aplicado vía `Depends()` (SPEC-081). **No ejecuta IA ni SQL** — solo valida + encola.
- **Parser puro** (`integrations/whatsapp/inbound_parser.py`, SPEC-027): sin I/O, interpreta el JSON de Meta (`object:"whatsapp_business_account"` → `entry[].changes[].value.messages[]` y `.statuses[]`), normaliza a `InboundMessageEvent`/`StatusEvent`. Robusto ante payloads malformados (lanza `InboundEventParseError`, el worker lo descarta sin reventar).
- **Worker de ingesta** (`workers/whatsapp_inbound_worker.py`, SPEC-027/028/030): `BLPOP wa:inbound` → (1) resuelve tenant por `phone_number_id` con **función SQL `resolve_tenant_by_phone_number_id` (`SECURITY DEFINER`, ADR-008)**, sin fijar RLS aún; (2) descarte auditado sin mapeo, cero escritura; (3) fija RLS (`set_tenant_session`); (4) **idempotencia por `wamid`** (guarda de worker + UNIQUE de BD); (5) get-or-create `Contact` (por `telefono==wa_id`) + `Conversation` (`canal="whatsapp"`) + `Message`; (6) dispara **sentimiento (SPEC-018)** + genera y persiste **borrador RAG con ≥3 citas en estado `propuesto` (SPEC-019)** — NADA se envía automáticamente; (7) modo degradado si el LLM local no está (nunca revierte la ingesta).
- **Envío saliente** (`integrations/whatsapp/graph_client.py`, SPEC-029): ÚNICO módulo autorizado a `POST graph.facebook.com/<ver>/<phone_number_id>/messages`; `send_text_message`/`send_template_message`/`send_audio_message`+`upload_media`; **allowlist de host por código** (`_validate_graph_host`, host EXACTO `graph.facebook.com`, rechaza userinfo/subdominios), reintentos backoff ante 429/5xx, token Bearer nunca en logs (C3). Envío solo tras **aprobación humana** del borrador (`wa_send_worker`, no leído en detalle pero referenciado en todo el flujo).
- **Descarga de media entrante** (`integrations/whatsapp/media_client.py`, SPEC-054): dos GETs a `graph.facebook.com` (resolver URL temporal + descargar binario), almacena cifrado (`audio_store`, ADR-009), misma allowlist por host. El STT **nunca** descarga (lee del almacén ya poblado, ADR-009).
- **Statuses de entrega** (SPEC-030): `sent/delivered/read/failed` → `estado_entrega` (`enviado/entregado/leido`/`failed`), conciliados por `wamid`, monotónicos e idempotentes.

### 1.2 Lo que YA EXISTE y Instagram REUTILIZA casi intacto (anti-scope — no rehacer)

- **Modelo de dominio YA admite el canal "instagram" SIN migración de datos:**
  - `Conversation.canal` es `String(50)` libre con default `"webchat"` (`models/conversation.py`) — un `canal="instagram"` es aditivo, sin tocar el esquema.
  - **HALLAZGO:** `app/schemas/conversation.py:15` ya declara `CANALES_VALIDOS = {"whatsapp", "instagram", "messenger", "webchat"}` y `app/api/conversations.py` ya documenta "whatsapp/instagram/..." — **"instagram" es un valor de canal VÁLIDO heredado de la maqueta original (SPEC-004/008)**; el dominio y la API de lectura ya lo contemplan. Lo único que falta es el **transporte real** (webhook/worker/cliente de envío), CERO de lo cual existe hoy.
  - `Message` (`models/message.py`): `remitente` (contacto/agente/ia), `contenido`, `tipo` (texto/audio), `estado_entrega`, `sentimiento`, y `wamid` (UNIQUE cuando no-None) como clave de idempotencia. El `wamid` es un `String(128)` nullable — Instagram necesita su propia clave de idempotencia (el `mid` de Instagram); **a decidir en Q4** si se reutiliza la columna `wamid` como "id de mensaje del canal" genérico o se añade una columna/tabla propia.
- **Pipeline IA local reutilizable TAL CUAL:** `generate_rag_draft` + `draft_review_service.create_draft` (SPEC-017/019) + `schedule_sentiment_analysis` (SPEC-018) ya se invocan desde el worker de WhatsApp sin acoplarse al canal — operan sobre `Conversation`/`Message` del dominio. El worker de Instagram los dispararía **igual**, sin crear componentes de IA nuevos.
- **Human-in-the-loop (SPEC-019):** el borrador RAG queda en `propuesto`; un agente lo aprueba vía `POST .../drafts/{id}/approve` y recién entonces se envía. **Reutilizable sin cambios de concepto** — solo el transporte de envío cambia (Graph API de Instagram en vez de WhatsApp).
- **Infra de egress acotado (ADR-006, `check-externos-backend.sh`):** la allowlist por ruta YA permite `graph.facebook.com` dentro de `app/integrations/whatsapp/`. Instagram Messaging usa **el mismo host `graph.facebook.com`** (y el subdominio de media/CDN) — ver §1.4 y Q-ADR.
- **Observabilidad (PLAN-010), rate-limiting general (PLAN-011/SPEC-081), contenedores endurecidos (PLAN-011):** todo heredado; un worker/endpoint de Instagram se suma al patrón existente (métricas sin label de tenant, rate-limit por `Depends()`, contenedor no-root con límites) sin rediseñarlo.
- **Patrón de routing `identificador→tenant` con `SECURITY DEFINER` (ADR-008):** `resolve_tenant_by_phone_number_id` es la plantilla EXACTA para una futura `resolve_tenant_by_instagram_account_id` (resolución pre-RLS de solo lectura, acotada, `search_path` fijo).

### 1.3 Lo que es GENUINAMENTE NUEVO de Instagram (el verdadero alcance a construir)

> Estas diferencias son reales y verificadas contra el formato de Meta documentado en el propio código de WhatsApp + conocimiento de la Instagram Messaging API. DOCTOR STRANGE debe confirmarlas contra la documentación vigente de Meta al redactar las SPECs (la API de Meta evoluciona).

- **N-1 · Formato del webhook distinto.** El payload de Instagram usa `object: "instagram"` y la estructura `entry[].messaging[]` (objetos `sender.id`/`recipient.id`/`message.mid`/`message.text`/`message.attachments[]`) — **NO** la estructura `entry[].changes[].value.messages[]` de WhatsApp. Requiere un **parser nuevo** (`instagram/inbound_parser.py`), espejo del de WhatsApp pero con el mapeo propio de Instagram. El challenge GET y la firma `X-Hub-Signature-256` (HMAC sobre RAW body) son **el mismo mecanismo** que WhatsApp (mismo app secret de Meta por app) — reutilizable en concepto.
- **N-2 · Clave de routing multi-tenant distinta.** WhatsApp enruta por `phone_number_id` (número receptor). Instagram enruta por el **`instagram_business_account_id`** (o el ID de la página de Facebook vinculada / `recipient.id` del evento) — es un **routing y tabla NUEVOS** (`instagram_accounts`, espejo de `whatsapp_accounts`), con su propia función `SECURITY DEFINER`. No reutilizable directamente de `whatsapp_accounts`.
- **N-3 · Clave de idempotencia distinta.** Instagram identifica cada mensaje con un **`mid`** (message id), no un `wamid`. Idempotencia por `mid` (misma estrategia que ADR-007: guarda de worker + UNIQUE de BD). **A decidir (Q4):** reutilizar la columna `messages.wamid` como "id de mensaje del canal" genérico (renombrar conceptualmente) vs añadir columna propia.
- **N-4 · Autenticación/permisos y tipos de token distintos.** Instagram Messaging requiere un **Page Access Token** (o token de usuario del sistema) con permisos específicos de Instagram, distinto del token de WhatsApp. Secretos nuevos (`INSTAGRAM_*`: app secret compartido o propio, page access token, verify token, business account id) con el **mismo fail-fast de secretos** de `config.py` (PLAN-011/SPEC-021). **Ver el bloqueo de App Review en §1.5.**
- **N-5 · Ventana de mensajería y políticas distintas.** Instagram tiene su **propia ventana de respuesta** (la "standard messaging window" de 24h de Messenger/Instagram, con etiquetas como `HUMAN_AGENT` que la extienden a 7 días bajo ciertas condiciones) — **similar pero NO idéntica** a la ventana de 24h de WhatsApp y a su mecanismo de plantillas HSM (Instagram NO usa plantillas HSM; usa message tags). El envío saliente debe respetar la ventana de Instagram, no copiar literalmente la lógica de plantillas de WhatsApp.
- **N-6 · Tipos de contenido y media.** Instagram DM soporta texto y adjuntos (imágenes, audio, stickers, reacciones, respuestas a historias). **A verificar por DOCTOR STRANGE:** si Instagram entrega notas de voz entrantes de forma reutilizable por el pipeline STT ya existente (`stt:jobs` + `stt_worker`, sink parametrizado por destino, PLAN-006) o si el manejo de media difiere lo suficiente como para dejar audio fuera de la V1 (ver Q2). El patrón de `media_client.py` (descarga a almacén cifrado) es reutilizable en forma.

### 1.4 Egress y ADR (decisión de arquitectura para DOCTOR STRANGE)

- **Instagram Messaging API usa `graph.facebook.com`** (el mismo host que WhatsApp) para el envío, y el CDN de media (`*.cdninstagram.com` / `scontent.*` / subdominios servidos por Meta) para la descarga de adjuntos. **Punto a resolver (candidato ADR-017):**
  - El **envío/API** cae bajo el **mismo host `graph.facebook.com`** que ADR-006 ya autoriza — pero la allowlist por ruta de `check-externos-backend.sh` (sección 7) hoy permite `graph.facebook.com` **SOLO dentro de `app/integrations/whatsapp/`**. Un módulo nuevo `app/integrations/instagram/` necesitará **extender esa allowlist por ruta** (añadir `app/integrations/instagram` a `GRAPH_ALLOWED_MODULES`). Esto es un cambio al guardarraíl de egress → **requiere decisión explícita y probablemente un ADR acotado** (¿se amplía ADR-006, o se crea ADR-017 "egress acotado del transporte Instagram"?).
  - La **descarga de media** de Instagram, si entra en V1 (Q2), puede requerir un **dominio de CDN distinto de `graph.facebook.com`** (los adjuntos de IG se sirven desde CDNs de Meta con otros hostnames). Si es así, es un **borde de egress NUEVO** (no cubierto por ADR-006) → **ADR acotado obligatorio** con allowlist de host por código (mismo patrón `_validate_graph_host`) + entrada nueva en `check-externos-backend.sh`. DOCTOR STRANGE debe confirmar los hostnames reales del CDN de media de IG antes de fijar esto.
- **Invariante intocable:** la IA (`ia_internal internal:true`) sigue sin egress; el transporte de Instagram vive SOLO en `app`/su worker de envío; el módulo `instagram/` NUNCA importa Ollama/IA/`app.workers` (mismo criterio que WhatsApp, verificado por `check-externos-backend.sh` secciones 7-9).

### 1.5 🔴 BLOQUEO EXTERNO DURO — Meta App Review (NO es algo que el equipo pueda resolver con código)

> Esto NO se edulcora. Es el equivalente, en esta fase, a "los deploys con secretos reales se difieren al Lead" de fases anteriores — pero más fuerte, porque depende de un **tercero (Meta) con plazos de días a semanas** fuera del control del equipo.

- La **Instagram Messaging API exige App Review de Meta** con permisos específicos (**`instagram_manage_messages`**, `instagram_basic`, `pages_messaging`, y la función "Instagram messaging" habilitada en la app de Meta). Sin esa aprobación, la app **solo puede intercambiar mensajes con cuentas de rol de prueba** (admins/testers/developers de la app) — **no con usuarios reales**.
- Prerequisitos que **SOLO el Lead/negocio puede aportar** (no el agente): (a) una **app de Meta** (Business) ya creada; (b) una **cuenta de Instagram Business o Creator** vinculada a una **Página de Facebook**; (c) el proceso de **App Review aprobado** para los permisos de mensajería; (d) los **tokens/secretos reales** de esa app.
- **Consecuencia para HAWKEYE (pruebas E2E) y QUICKSILVER (deploy):** **sin App Review aprobado, NO se puede verificar nada end-to-end con un usuario real de Instagram.** El equipo PUEDE construir y probar TODO el camino con: (1) **tests unitarios/integración con payloads firmados simulados** (igual que el `simulador de webhook firmado` de WhatsApp, SPEC-034), (2) **cuentas de prueba/tester** dentro del modo desarrollo de la app de Meta (intercambio real pero limitado a testers). La verificación con tráfico de **usuarios reales queda BLOQUEADA tras la aprobación de Meta**, que es responsabilidad del Lead gestionar. Esto debe quedar **explícito en PLAN-012 como riesgo top + puerta externa**, no como un detalle menor.

---

## 2. Rol (quién resuelve)

- **🔮 DOCTOR STRANGE** — PLAN-012 + SPECs (dos puertas de aprobación); confirma el formato/permisos/hostnames vigentes de la Instagram Messaging API contra la documentación de Meta; decide alcance V1 (Q1–Q5) y si el egress de Instagram amplía ADR-006 o crea ADR-017.
- **🛡️ CAPTAIN AMERICA** — orquestación de la implementación; integración del nuevo módulo/worker/servicio de Docker espejando el de WhatsApp.
- **🐾 BLACK PANTHER** — **líder natural del backend de esta fase:** módulo `integrations/instagram/` (webhook, parser, graph/media client), worker de ingesta, tabla `instagram_accounts` + función `SECURITY DEFINER` de routing, cola Redis `ig:inbound`, worker de envío.
- **🕷️ BLACK WIDOW** — seguridad: validación de firma del webhook, aislamiento/allowlist de egress (ADR-006↔ADR-017), fail-fast de secretos `INSTAGRAM_*`, cero fuga cross-tenant (RLS fijada antes de escribir), cero PII/secretos en logs, barrido de que el módulo IG no importe IA.
- **🩹 WOLVERINE** — calidad: que `check-externos-backend.sh` se extienda correctamente (allowlist por ruta de IG), cobertura, no-regresión del canal WhatsApp.
- **🦅 HAWKEYE** — pruebas: simulador de webhook de Instagram **firmado** (espejo del de WhatsApp), tests de idempotencia por `mid`, cross-tenant (debe fallar), parser ante payloads IG reales/malformados; documenta el límite de verificación E2E por el bloqueo de App Review (§1.5).
- **🦸 DAREDEVIL / SPIDER-MAN** — frontend (si entra, Q5): la Bandeja ya es omnicanal (SPEC-004) y la API de conversaciones ya acepta `canal="instagram"` — probablemente solo un badge/filtro de canal, no una vista nueva.
- **⚡ QUICKSILVER** — deploy: servicio Docker del worker de IG, runbook del canal, y **gestión del bloqueo de App Review con el Lead** (no desplegable a usuarios reales sin aprobación de Meta).
- **⚡ THOR** — performance: que el worker de IG no compita de forma dañina con STT/IA en la máquina CPU-only (reutiliza límites de PLAN-011).

---

## 3. Acción (verbo único y medible por sub-objetivo candidato — alcance final lo fija el Lead en §7)

- **A. CREAR el módulo de transporte `app/integrations/instagram/`** espejando `whatsapp/`: `webhook.py` (challenge GET + firma HMAC sobre RAW body + encolado + ACK 200), `inbound_parser.py` (parser puro del formato `object:"instagram"`/`entry[].messaging[]`), `graph_client.py` (envío por Graph API de IG), y — **condicional Q2** — `media_client.py` (descarga de adjuntos).
- **B. AÑADIR el routing multi-tenant de Instagram:** tabla `instagram_accounts` (espejo de `whatsapp_accounts`, bajo RLS) + función SQL `resolve_tenant_by_instagram_account_id` (`SECURITY DEFINER`, patrón ADR-008) + migración Alembic.
- **C. CREAR el worker de ingesta `instagram_inbound_worker.py`** (cola `ig:inbound`) espejando `whatsapp_inbound_worker.py`: resuelve tenant, fija RLS, **idempotencia por `mid`**, get-or-create `Contact`/`Conversation(canal="instagram")`/`Message`, **dispara el pipeline IA local existente** (sentimiento SPEC-018 + borrador RAG SPEC-019, sin crear IA nueva) + conciliación de statuses de entrega de IG.
- **D. CREAR el worker/servicio de envío saliente** (espejo de `wa_send_worker`): envía el borrador **ya aprobado por un humano** (SPEC-019) por la Graph API de IG, respetando la **ventana de mensajería de Instagram** (N-5, message tags en vez de plantillas HSM).
- **E. EXTENDER el egress acotado:** ampliar la allowlist por ruta de `check-externos-backend.sh` a `app/integrations/instagram/`, y **decidir ADR** (ampliar ADR-006 para el envío sobre `graph.facebook.com` y/o crear **ADR-017** para el CDN de media de IG si es un host nuevo — Q-ADR).
- **F. GESTIONAR secretos nuevos `INSTAGRAM_*`** con el fail-fast de secretos existente (`config.py`, PLAN-011), nunca en repo/logs (C3).
- **G. (Condicional Q5) FRONTEND:** badge/filtro de canal "instagram" en la Bandeja omnicanal (la API ya lo acepta) — probablemente mínimo.
- **H. PRUEBAS + simulador de webhook firmado de IG + documentación/runbook del canal**, con el límite de verificación E2E explícito (§1.5).

---

## 4. Formato (estructura exacta de la salida esperada de DOCTOR STRANGE / implementación)

1. **PLAN-012.md** (`.swarm/PLAN-012.md`): alcance IN/OUT, fases (espejo de las F0–F9 de PLAN-003 pero MÁS CORTO por la reutilización de §1.2), entregables, **riesgos con R-top = bloqueo de Meta App Review (§1.5)**, criterios de éxito, matriz preguntas→decisiones (resolviendo §7), clasificación SENSIBLE, y la **decisión de ADR de egress (ampliar ADR-006 vs crear ADR-017)**.
2. **SPECs** (`.swarm/specs/SPEC-085..0NN.md`) desde `next_spec:85`, con la cabecera/estilo de las SPEC de WhatsApp (SPEC-024..034) y las últimas (SPEC-080..084): deriva de PLAN-012, clasificación, dependencias, checkpoints citados. Se espera un set **más pequeño** que las 11 de WhatsApp gracias a la reutilización.
3. **ADR(s)** desde `next_adr:17` **SOLO** para la(s) decisión(es) de egress genuinas (allowlist por ruta de IG + CDN de media si aplica). No forzar ADRs sin decisión arquitectónica real.
4. **Artefactos de implementación esperados (según alcance aprobado):**
   - `app/integrations/instagram/{webhook,inbound_parser,graph_client[,media_client]}.py`.
   - `app/models/instagram_account.py` + migración Alembic (tabla + función `SECURITY DEFINER` + RLS).
   - `app/workers/instagram_inbound_worker.py` + worker/servicio de envío + colas Redis (`ig:inbound`).
   - Servicio(s) nuevo(s) en `docker-compose.yml` (worker de ingesta/envío de IG, endurecidos como los de PLAN-011).
   - Secretos `INSTAGRAM_*` en `config.py` (fail-fast) + `.env.example` + `check-externos-backend.sh` actualizado (allowlist por ruta de IG).
   - Pruebas (HAWKEYE): simulador de webhook IG firmado, idempotencia por `mid`, cross-tenant que falla, parser, no-regresión de WhatsApp.
   - Runbook del canal Instagram + nota explícita del bloqueo de App Review.

---

## 5. Tests / criterios de éxito (verificables — C4)

> El set final depende del alcance aprobado (§7). Candidatos:

### Webhook + parser (A)
- [ ] `GET /api/v1/instagram/webhook` resuelve el challenge de Meta (token en tiempo constante) y responde 403 si no coincide.
- [ ] `POST` rechaza (401) un payload sin firma o con firma HMAC inválida **sin encolar**; con firma válida encola el RAW body en `ig:inbound` y hace **ACK 200** sin ejecutar IA/SQL (p95 ≤ 500 ms).
- [ ] El parser extrae correctamente `mid`/`sender.id`/`recipient.id`/texto de un payload `object:"instagram"` real y **no revienta** ante uno malformado.

### Routing + idempotencia (B/C)
- [ ] Un evento con `instagram_account_id` sin fila en `instagram_accounts` → **descarte auditado, cero escritura** (RF espejo de ADR-007).
- [ ] Un webhook **reentregado con el mismo `mid`** NO crea un segundo `Message`/borrador (idempotencia por `mid`, guarda + UNIQUE de BD).
- [ ] Un evento cuyo `instagram_account_id`/`mid` pertenece a **otro tenant** NO cruza tenants (RLS fijada antes de escribir; test cross-tenant que **debe fallar**).

### Pipeline IA + human-in-the-loop (C)
- [ ] Tras persistir un DM entrante se dispara sentimiento (SPEC-018) y se **propone** un borrador RAG con ≥3 citas (SPEC-019) — **NADA se envía automáticamente**; el envío real solo ocurre tras aprobación humana (reutiliza el flujo existente, sin IA nueva).

### Envío + ventana (D)
- [ ] Un borrador aprobado se envía por la Graph API de IG; el envío respeta la **ventana de mensajería de Instagram** (N-5) y concilia el estado de entrega por el id de mensaje de IG.

### Egress / seguridad (E/F)
- [ ] `check-externos-backend.sh` sigue **verde** con la allowlist por ruta extendida a `app/integrations/instagram/`; `graph.facebook.com`/CDN de IG NO aparece fuera de ese módulo; el módulo IG NO importa Ollama/IA (secciones 7-9 del script, espejo de WhatsApp).
- [ ] Fail-fast de `INSTAGRAM_*` fuera de development; ningún secreto ni PII de contacto en logs (C2/C3).
- [ ] La IA (`ia_internal`) sigue sin egress; el aislamiento se **refuerza**, nunca se relaja.

### Transversal
- [ ] **CERO regresión del canal WhatsApp** ni del resto del backend (suite completa + `test_rls_isolation`/egress/secretos verdes).
- [ ] **Límite E2E documentado (§1.5):** las pruebas E2E con usuario real de IG quedan explícitamente marcadas como bloqueadas tras Meta App Review (responsabilidad del Lead); el equipo verifica todo lo verificable con payloads firmados simulados + cuentas de prueba.

---

## 6. Checkpoints aplicables (C1–C8 del proyecto — NO existe C9)

- **C2 (minimización de datos):** descartes/errores de enrutado loguean solo metadatos (`instagram_account_id`/`mid`/`event_id`), NUNCA el contenido del DM ni datos del contacto. Borrado lógico (`activo=False`) en `instagram_accounts`.
- **C3 (secretos):** 🔴 crítico. `INSTAGRAM_*` (app secret, page access token, verify token, business account id) por env/secret manager con fail-fast; token Bearer solo en el header `Authorization`, jamás en logs.
- **C4 (criterios verificables):** todos los de §5 son objetivos y demostrables (con la salvedad E2E de §1.5).
- **C6 (deploy sensible):** habilitar el canal real + aplicar secretos reales + el paso por Meta App Review es cambio sensible → **aprobación explícita del Lead + notificación** antes de desplegar a usuarios reales.
- **C8 (trazabilidad):** origen = PLAN-012 / `prompt-lab/prompts/PROMPT-012-INSTAGRAM-DM.md`.
- **Egress (patrón ADR, no checkpoint):** el transporte de IG introduce/amplía un borde de egress → **decisión de ADR obligatoria** (ampliar ADR-006 y/o crear ADR-017), con allowlist de host por código + entrada en `check-externos-backend.sh`. No se introduce ningún egress de inferencia.

---

## 7. Preguntas abiertas para el Lead (VINCULANTES — DOCTOR STRANGE las necesita para fijar alcance)

> Formato con opciones (como en PROMPT-009/010/011). El Lead responde; la respuesta se anexará como "§7.1 Respuestas del Lead — VINCULANTES" antes de PLAN-012.

**Q1 — 🔴 Meta App Review: ¿es un prerequisito YA resuelto, o un bloqueo externo pendiente? (la pregunta MÁS crítica)**
La Instagram Messaging API exige una app de Meta con `instagram_manage_messages` **aprobado por App Review** + una cuenta de IG Business/Creator vinculada a una Página de Facebook (§1.5). Sin esto, no hay mensajería con usuarios reales — solo con cuentas de prueba.
- **(A) El Lead YA tiene app de Meta + permisos de Instagram Messaging aprobados + cuenta IG Business vinculada + tokens reales** → el equipo puede apuntar a verificación E2E real al final de la fase. — *ideal, pero XAVIER lo DUDA por defecto (no hay rastro de ello en el repo/secretos).*
- **(B) NO está resuelto / está en trámite** → el equipo **construye y prueba TODO con payloads firmados simulados + cuentas de prueba** (modo desarrollo de la app de Meta), y la activación con usuarios reales queda **DIFERIDA al Lead** cuando Meta apruebe (análogo a los deploys con secretos reales de fases anteriores). — *recomendación de XAVIER: diseñar para esto por defecto; no bloquear el desarrollo esperando a Meta.*
- **(C) No hay app de Meta todavía** → entonces App Review es un **prerequisito externo bloqueante** que el Lead debe iniciar en paralelo; el equipo entrega el canal "listo para conectar" (como un tenant se crea sin WhatsApp y se conecta después, PLAN-009).

**Q2 — Alcance de contenido de la V1: ¿solo texto, o también media/audio desde el día 1?**
- **(A) Solo TEXTO en la V1.** — *recomendación de XAVIER: entrega el camino crítico (DM de texto → RAG → aprobación → envío) rápido y acotado; el manejo de media de IG (y su posible CDN de egress nuevo, §1.4) es la parte de más incertidumbre.*
- **(B) Texto + imágenes/adjuntos** (descarga a almacén cifrado, patrón `media_client.py`) — añade el borde de egress del CDN de IG (ADR-017).
- **(C) Texto + notas de voz entrantes** reutilizando el pipeline STT ya construido (PLAN-006, `stt:jobs`/sink por destino) — **a confirmar por DOCTOR STRANGE** si IG entrega audio en un formato reutilizable; mayor alcance e incertidumbre.

**Q3 — Human-in-the-loop: ¿se reutiliza el flujo de aprobación de borrador RAG TAL CUAL?**
El flujo de WhatsApp genera un borrador `propuesto` que un agente aprueba antes de enviar (SPEC-019), sin autoenvío.
- **(A) Reutilizar idéntico** (borrador RAG + aprobación humana, cero autoenvío) — *recomendación de XAVIER: es el invariante de seguridad/UX del producto; Instagram no justifica cambiarlo.*
- **(B) Instagram necesita algo distinto** (p. ej. autorespuestas automáticas a ciertos intents) — abre alcance y una discusión de política de autoenvío que hoy el producto no tiene.

**Q4 — Modelo de datos de idempotencia: ¿se reutiliza la columna `messages.wamid` como id de mensaje de canal genérico, o se añade uno propio para Instagram (`mid`)?**
- **(A) Reutilizar `messages.wamid`** como "id de mensaje del canal externo" genérico (conceptualmente renombrado, el `mid` de IG se guarda ahí; UNIQUE ya existe). — *XAVIER: lo más aditivo, menos esquema nuevo; a validar que no colisione semánticamente con WhatsApp.*
- **(B) Añadir una columna/estructura propia** para el `mid` de Instagram (más explícito, más esquema). — *decisión fina para DOCTOR STRANGE/BLACK PANTHER.*

**Q5 — Frontend: ¿esta fase toca la SPA, o el canal queda "headless" (backend + API)?**
La Bandeja omnicanal (SPEC-004) y la API de conversaciones ya aceptan `canal="instagram"` (§1.2).
- **(A) Headless / mínimo** — backend + API; a lo sumo un badge/filtro de canal en la Bandeja (la API ya lo soporta). — *recomendación de XAVIER, coherente con cómo WhatsApp integró la SPA por feature-flag.*
- **(B) Trabajo de UI dedicado** para Instagram (vista/experiencia propia) — probablemente innecesario dado que la Bandeja ya es omnicanal.

**Q-ADR (derivada, la responde DOCTOR STRANGE con guía del Lead) — ¿el egress de Instagram amplía ADR-006 o crea ADR-017?**
El envío va a `graph.facebook.com` (ya autorizado por ADR-006 para WhatsApp), pero la **allowlist por ruta** del CI lo limita hoy a `app/integrations/whatsapp/`. Y la descarga de media de IG (si entra, Q2-B/C) puede usar un **CDN de host distinto** (borde de egress nuevo). DOCTOR STRANGE propone: **ampliar ADR-006** para el envío (añadir la ruta `instagram/` a la allowlist) + **ADR-017 acotado** solo si el CDN de media de IG es un host nuevo. El Lead confirma al aprobar PLAN-012.

---

## 7.1 Respuestas del Lead — VINCULANTES (2026-10-03)

- **Q1 (Meta App Review):** **Opción B** — NO está resuelto / en trámite. El equipo construye y prueba TODO con payloads firmados simulados + cuentas de prueba (modo desarrollo de la app de Meta). La activación con usuarios reales queda **DIFERIDA al Lead** cuando Meta apruebe los permisos — análogo a los deploys con secretos reales diferidos en fases anteriores. HAWKEYE documenta explícitamente este límite de verificación E2E (§1.5), no lo oculta ni lo fuerza.
- **Q2 (alcance de contenido V1):** **Opción B** — Texto + imágenes/adjuntos. Entra en alcance la descarga de adjuntos a almacén cifrado (patrón `media_client.py`). **Consecuencia directa:** si el CDN de media de Instagram usa un host distinto de `graph.facebook.com`, es un borde de egress NUEVO que exige su propio ADR acotado (candidato ADR-017) con allowlist de host por código + entrada en `check-externos-backend.sh` — DOCTOR STRANGE debe confirmar los hostnames reales del CDN de Meta antes de fijar esto en la SPEC correspondiente. Notas de voz (Q2-C) quedan **fuera de esta V1**.
- **Q3 (human-in-the-loop):** **Opción A** — se reutiliza idéntico: borrador RAG en estado `propuesto`, cero autoenvío, aprobación humana obligatoria antes de cualquier envío real. No se abre ninguna discusión de política de autoenvío.
- **Q4 (idempotencia):** **Opción A** — se reutiliza la columna `messages.wamid` existente como "id de mensaje del canal externo" genérico; el `mid` de Instagram se guarda ahí (UNIQUE ya existe). BLACK PANTHER/DOCTOR STRANGE validan en la SPEC que esto no colisiona semánticamente con WhatsApp (p. ej. mismo nombre de columna, distinto significado conceptual — documentarlo claramente).
- **Q5 (frontend):** **Opción A** — headless/mínimo. Solo backend + API; a lo sumo un badge/filtro de canal en la Bandeja ya omnicanal (la API ya acepta `canal="instagram"` sin cambios). Sin trabajo de UI dedicado.

**Consecuencia directa para DOCTOR STRANGE:** PLAN-012 cubre el transporte completo de Instagram DM (webhook, parser, routing multi-tenant, worker de ingesta, pipeline IA reutilizado, worker de envío con aprobación humana, descarga de adjuntos/imágenes) espejando WhatsApp, con egress extendido (ADR-006 ampliado para el envío + ADR-017 candidato para el CDN de media si aplica), sin tocar el frontend más allá de lo que la API ya soporta, y con el bloqueo de Meta App Review documentado como riesgo top + puerta externa que condiciona la verificación E2E real pero NO bloquea el desarrollo/pruebas con simuladores.

---

## 8. Fuera de alcance (anti-scope explícito)

- **Reconstruir el dominio o el pipeline IA:** `Conversation`/`Message`/`Contact`, RAG (SPEC-017/019), sentimiento (SPEC-018) y el human-in-the-loop (SPEC-019) se **reutilizan**, no se rehacen (§1.2). El canal "instagram" ya es un valor de `canal` válido en el dominio/API.
- **Reimplementar infra ya endurecida:** egress acotado (ADR-006), observabilidad (PLAN-010), rate-limiting general (PLAN-011), contenedores no-root/límites (PLAN-011), fail-fast de secretos (PLAN-011/SPEC-021) — se **heredan y extienden**, no se rediseñan.
- **Facebook Messenger como canal separado** (aunque comparte Graph API): el Lead pidió **Instagram DM**. Messenger es un canal distinto; si se quisiera, sería otra fase (el enum `CANALES_VALIDOS` ya lo contempla, pero no está en este encargo).
- **Autoenvío de respuestas sin aprobación humana** (salvo que Q3-B lo abra explícitamente) — rompería el invariante de producto.
- **Gestionar/acelerar el proceso de Meta App Review** — es un trámite externo del Lead/negocio con Meta; el equipo entrega el canal verificable con simuladores + cuentas de prueba (§1.5).
- **SaaS/BSP intermediario** (Twilio/360dialog/ManyChat para IG): un tercero vería el contenido de los DMs → contradice SENSIBLE (mismo criterio que descartó los BSP en ADR-006). Transporte directo a Meta.

---

## 9. Trazabilidad

- **Origen:** objetivo verbatim del Lead "Fase D: Canal Instagram (Direct Message)" (4ª y última de 4 fases ordenadas; 1–3 cerradas: PLAN-009/010/011).
- **Evidencia del estado real** (verificada por XAVIER en esta sesión, 2026-10-03): `app/integrations/` solo tiene `whatsapp/` y `pbx/` — **CERO transporte de Instagram**; `integrations/whatsapp/{webhook,inbound_parser,graph_client,media_client}.py` (patrón exacto a espejar: challenge+HMAC sobre RAW body, parser puro `object:"whatsapp_business_account"`, allowlist de host `graph.facebook.com` por código, descarga de media cifrada); `workers/whatsapp_inbound_worker.py` (routing `resolve_tenant_by_phone_number_id` SECURITY DEFINER ADR-008, RLS antes de escribir, idempotencia por `wamid`, disparo de sentimiento SPEC-018 + borrador RAG SPEC-019 sin autoenvío); `models/whatsapp_account.py` (plantilla de `instagram_accounts`); `models/conversation.py` (`canal` String(50) libre); `models/message.py` (`wamid` UNIQUE nullable como clave de idempotencia, `tipo` texto/audio, `estado_entrega`); **`app/schemas/conversation.py:15` `CANALES_VALIDOS` YA incluye `"instagram"`/`"messenger"`** y `app/api/conversations.py` ya los documenta (heredado de la maqueta, sin transporte real); `backend/check-externos-backend.sh` (sección 7: allowlist por ruta de `graph.facebook.com` SOLO en `app/integrations/whatsapp`; secciones 8-9: IG no debe importar IA ni la IA httpx); `.swarm/adrs/ADR-006-excepcion-egress-transporte-whatsapp.md` (excepción de egress a `graph.facebook.com`, allowlist por ruta) y `ADR-007-idempotencia-wamid-enrutado-tenant.md` (idempotencia por id de mensaje + routing por tabla bajo RLS, patrón a espejar con `mid`/`instagram_accounts`); `docker-compose.yml` (servicios endurecidos de WhatsApp a espejar); `.swarm/specs.json` (`next_plan:12`, `next_spec:85`, `next_adr:17`, PLAN-009/010/011 CERRADO/APROBADO); nota de PLAN-006 ("Instagram del tamaño de reconstruir el Entregable #3") **refinada por XAVIER a la baja** dado que el pipeline IA/observabilidad/hardening/routing-SECURITY-DEFINER ya existen y se heredan.
- **Siguiente paso:** el Lead responde §7 (Q1–Q5 + Q-ADR), con **Q1 (Meta App Review) como la decisión crítica que condiciona todo lo demás** → se anexan respuestas VINCULANTES (§7.1) → 🔮 DOCTOR STRANGE redacta PLAN-012 → aprobación del Lead → SPECs → aprobación → implementación (BLACK PANTHER líder backend).
