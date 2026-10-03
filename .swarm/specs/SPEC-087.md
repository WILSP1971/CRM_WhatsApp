# SPEC-087 — Ingesta idempotente + enrutado multi-tenant + disparo del pipeline IA local (`instagram_inbound_worker`, cola `ig:inbound`) + servicio Docker endurecido (F2) 🔴 SENSIBLE

- Estado: APROBADA · Responsable: BLACK PANTHER · Colaboran/revisan: BLACK WIDOW (cross-tenant/RLS), HAWKEYE (idempotencia/cross-tenant), WOLVERINE (no-regresión), THOR (no competir con STT/IA en CPU) · Prioridad: ALTA · Tipo: BACKEND/WORKER/SEGURIDAD · Fase: F2
- Deriva de: PLAN-012 (F2, §2.IN.3, §3.1, §3.2 N-1/N-2/N-3, §3.4, §4 tabla F2, §5, §6 R-111/R-113, §7 CE-116/CE-117) · Clasificación: SENSIBLE (`.no-externo`) · **Depende de SPEC-086** (evento en `ig:inbound`) **y SPEC-085** (función de routing + idempotencia + modelo) · **Reutiliza SIN REIMPLEMENTAR SPEC-018 (sentimiento) y SPEC-017/019 (RAG + human-in-the-loop)** · Espeja `backend/app/workers/whatsapp_inbound_worker.py` (SPEC-027/028), `docker-compose.yml` (servicios endurecidos, PLAN-011) · ADR-004/007/008

## Objetivo

Construir el **worker de ingesta de Instagram**, espejo exacto de `whatsapp_inbound_worker.py`, que convierte un evento firmado de `ig:inbound` en dominio persistido bajo RLS y dispara el pipeline IA local existente sin crear IA nueva: `BLPOP ig:inbound` → parsea (SPEC-086) → **resuelve tenant** por `instagram_account_id` con `resolve_tenant_by_instagram_account_id` (`SECURITY DEFINER`, ADR-008, pre-RLS, sin mapeo → **descarte auditado, cero escritura**) → **fija RLS** (`set_tenant_session`) ANTES de escribir → **idempotencia por `mid`** guardado en `messages.wamid` (guarda de worker + UNIQUE de BD) → get-or-create `Contact`/`Conversation(canal="instagram")`/`Message` → dispara **sentimiento (SPEC-018, YA EXISTENTE)** + **borrador RAG ≥3 citas en `propuesto` (SPEC-019, YA EXISTENTE)** best-effort/modo degradado, **SIN autoenvío** → si hay adjuntos, encola su descarga (contrato consumido por SPEC-088). El servicio Docker del worker se endurece como los de PLAN-011 (no-root, límites holgados, `no-new-privileges`, `cap_drop`).

## Contexto

Verificado en el repo (fuente de verdad — 2026-10-03):
- **`whatsapp_inbound_worker.py` es la plantilla EXACTA** (SPEC-027/028/030): `_resolve_tenant_id` invoca la función `SECURITY DEFINER` en su propia transacción de solo lectura con `db.rollback()` (líneas 206–219), NUNCA un SELECT directo (fail-closed bajo RLS sin tenant). Sin mapeo → `logger.warning("..._unmapped_..._discarded")` con solo metadatos (`phone_number_id`/`wamid`/`event_id`), **cero escritura** (líneas 436–444). Con tenant: `with db.begin(): set_tenant_session(db, str(tenant_id))` ANTES de cualquier escritura; `_message_wamid_exists` (guarda, líneas 222–234) + UNIQUE de BD (garantía dura ante carreras → `except IntegrityError` tratado como duplicado, líneas 494–507); get-or-create `Contact` (por `telefono==wa_id`) + `Conversation(canal=...)` + `create_message`; `message.wamid = event.wamid`. Captura `message_id`/`conversation_id` DENTRO de la transacción (comentario extenso líneas 480–492 sobre `expire_on_commit`/`ObjectDeletedError` bajo RLS real). Tras persistir: `_schedule_sentiment_best_effort` (SPEC-018, `run_coroutine_best_effort`) + `_generate_rag_draft_best_effort` (SPEC-017/019, `generate_rag_draft` + `draft_review_service.create_draft`, estado `propuesto`, **NUNCA** `approve_and_send`). Modo degradado (`AIServiceError`/`InsufficientContextError` → no genera borrador, no revierte la ingesta, líneas 360–396). Robustez: un fallo por mensaje se loguea y no tumba el loop (`process_job`, líneas 964–996); `run_worker_loop` con `resilient_worker_loop` + señales.
- **El pipeline IA se REUTILIZA tal cual** (PLAN-012 §3.2/§8): `schedule_sentiment_analysis` (SPEC-018), `generate_rag_draft` + `draft_review_service.create_draft` (SPEC-017/019) operan sobre `Conversation`/`Message`, agnósticos de canal. El worker de IG los **dispara igual**. **NO se crea lógica de IA nueva** (invariante de PLAN-012; si una SPEC tienta a "crear" IA, es error).
- **Diferencias de IG (N-1/N-2/N-3):** routing por `instagram_account_id` (=`recipient.id`) → `resolve_tenant_by_instagram_account_id` (SPEC-085); contacto por `sender_id` (el id de Instagram del remitente, reutilizado como identificador del `Contact`, mismo criterio que `wa_id` en WhatsApp — BLACK PANTHER confirma el campo del `Contact` a usar); `Conversation(canal="instagram")`; idempotencia por `mid` guardado en `messages.wamid` (§3.4, Q4=A — la columna es el "id de mensaje del canal externo" genérico, sin renombrar).
- **Contenedores endurecidos (PLAN-011):** los servicios worker de `docker-compose.yml` corren no-root, con límites de recursos holgados, `security_opt: no-new-privileges`, `cap_drop: ALL`. El worker de IG se suma a ese patrón sin competir de forma dañina con STT/IA en la máquina CPU-only (THOR).
- **BLOQUEO DE META APP REVIEW (R-110):** la ingesta se verifica con el simulador firmado (SPEC-091) + cuentas de prueba; NO con tráfico de usuarios reales hasta que Meta apruebe (Q1=B, DIFERIDO al Lead).

## Alcance

### IN
- **`app/workers/instagram_inbound_worker.py`** (espejo de `whatsapp_inbound_worker.py`):
  - `_resolve_tenant_id(db, instagram_account_id)` vía `SELECT resolve_tenant_by_instagram_account_id(:id)` en transacción de solo lectura (`db.rollback()` al cerrar); sin mapeo → descarte auditado con metadatos (`instagram_account_id`/`mid`/`event_id`), **cero escritura** (RF espejo de ADR-007).
  - `with db.begin(): set_tenant_session(db, str(tenant_id))` ANTES de escribir; `_message_mid_exists(db, mid)` (consulta `SELECT 1 FROM messages WHERE wamid = :mid`) como guarda + `except IntegrityError` → duplicado no-op (garantía dura por UNIQUE).
  - get-or-create `Contact` (por el identificador de IG del remitente) + `Conversation(canal="instagram")` + `Message(remitente="contacto", contenido=texto o "[tipo]")`; `message.wamid = event.mid` (§3.4); captura `message_id`/`conversation_id` DENTRO de la transacción (mismo patrón `expire_on_commit`).
  - Si `event.attachments` (imágenes/adjuntos, Q2=B): encola su descarga con el contrato que consumirá SPEC-088 (no descarga aquí; la descarga vive en `media_client.py` de IG, F3). El camino de texto NO se ve afectado por la existencia de adjuntos.
  - Disparo IA (reutilizado): `_schedule_sentiment_best_effort` (SPEC-018) + `_generate_rag_draft_best_effort` (SPEC-017/019, estado `propuesto`, ≥3 citas, modo degradado si el LLM local cae, **SIN autoenvío**). Ningún error de IA revierte ni bloquea la ingesta.
  - `process_job`/`drain_one`/`run_worker_loop`/`_run_forever_with_signal_handling` espejo de WhatsApp, consumiendo `ig:inbound` (`resilient_worker_loop`, SIGTERM/SIGINT).
- **Servicio `instagram_inbound_worker` en `docker-compose.yml`** endurecido (patrón PLAN-011): no-root, límites holgados, `no-new-privileges`, `cap_drop: ALL`, `restart: unless-stopped`, en la red `app` (sin ruta a internet salvo la allowlist de transporte; esta SPEC no abre egress — la descarga de media es SPEC-088).

### OUT
- Descarga real de media (SPEC-088 implementa `media_client.py` de IG; aquí solo se encola/contrato).
- Envío saliente/statuses (SPEC-089).
- Cualquier **nueva** lógica de IA (sentimiento/RAG se reutilizan tal cual — PROHIBIDO reimplementar).
- Autoenvío (Q3=A, invariante de producto: el borrador queda `propuesto`).

## Dependencias
- **Depende de SPEC-086** (evento en `ig:inbound`) y **SPEC-085** (función `resolve_tenant_by_instagram_account_id`, modelo `instagram_accounts`, idempotencia `messages.wamid`). **Reutiliza SPEC-018 y SPEC-017/019** (ya existentes, no se reimplementan). **Habilita SPEC-088** (contrato de descarga) y el human-in-the-loop del borrador. Ruta crítica: F0 → F1 → **F2 (esta)** → {F3 ‖ F4}.

## Requisitos funcionales
- RF-01 Resuelve `instagram_account_id → tenant_id` con `resolve_tenant_by_instagram_account_id` (`SECURITY DEFINER`, pre-RLS); sin mapeo → descarte auditado (solo metadatos), **cero escritura** (CE-116).
- RF-02 Fija RLS (`set_tenant_session`) ANTES de cualquier `INSERT`; un evento de otro tenant NO cruza tenants (CE-116).
- RF-03 Idempotencia por `mid` guardado en `messages.wamid` (guarda de worker + UNIQUE de BD): una reentrega del mismo `mid` NO crea segundo `Message`/borrador; carrera concurrente → `IntegrityError` tratado como duplicado (CE-117).
- RF-04 get-or-create `Contact`/`Conversation(canal="instagram")`/`Message`; `message.wamid = mid`.
- RF-05 Tras persistir: dispara sentimiento (SPEC-018) + borrador RAG ≥3 citas en `propuesto` (SPEC-019); **nada se envía automáticamente** (human-in-the-loop intacto).
- RF-06 Modo degradado: si el LLM local cae (`AIServiceError`) o no hay contexto para ≥3 citas (`InsufficientContextError`), NO se genera el borrador; el mensaje ya persistido no se ve afectado (ingesta nunca revertida).
- RF-07 Si hay adjuntos (Q2=B), encola su descarga (contrato de SPEC-088); el camino de texto no se ve afectado por adjuntos.
- RF-08 Servicio Docker del worker endurecido (no-root, límites, `no-new-privileges`, `cap_drop`), consumiendo `ig:inbound`.

## Requisitos no funcionales
- RNF-CROSS-TENANT RLS fijada antes de escribir; la resolución pre-tenant es la única excepción (función acotada); descarte sin mapeo no persiste contenido (R-111).
- RNF-IDEMPOTENCIA `messages.wamid` como id de canal genérico (§3.4); UNIQUE de BD es la garantía dura; ningún código asume formato WhatsApp al leerla (R-113).
- RNF-IA-REUTILIZADA El worker NO crea componentes de IA; invoca los existentes (SPEC-017/018/019); el módulo `instagram/` y el worker NO importan Ollama directamente (el disparo de IA pasa por los servicios de dominio ya existentes, mismo patrón que el worker de WhatsApp — verificado por `check-externos-backend.sh`).
- RNF-ROBUSTEZ Un fallo por mensaje se loguea (con `exc_info`, solo metadatos) y NO tumba el loop; `resilient_worker_loop` ante caídas de Redis/Postgres.
- RNF-C2 Logs de descarte/error solo con metadatos (`instagram_account_id`/`mid`/`event_id`), NUNCA contenido del DM ni datos del contacto.
- RNF-NO-REGRESION Cola `ig:inbound` separada de `wa:inbound`; cero regresión del worker de WhatsApp (R-117).
- RNF-THOR El worker no compite de forma dañina con STT/IA en la máquina CPU-only (límites de PLAN-011).

## Criterios de aceptación (verificables)
- [ ] Evento con `instagram_account_id` sin fila en `instagram_accounts` → descarte auditado, **cero escritura** (CE-116).
- [ ] Evento cuyo `instagram_account_id`/`mid` pertenece a otro tenant NO cruza tenants (RLS fijada antes de escribir); **test cross-tenant que DEBE fallar** (HAWKEYE, CE-116).
- [ ] Webhook reentregado con el mismo `mid` → un solo `Message`/borrador (idempotencia); inspección de `messages.wamid` con el `mid` de IG (CE-117).
- [ ] Carrera concurrente sobre el mismo `mid` → `IntegrityError` tratado como duplicado, sin propagar (CE-117).
- [ ] Tras persistir un DM: se dispara sentimiento (SPEC-018) y se **propone** un borrador RAG ≥3 citas (SPEC-019) en `propuesto`; **nada se envía automáticamente** (CE-117, human-in-the-loop).
- [ ] LLM local caído → sin borrador, sin revertir la ingesta (modo degradado).
- [ ] `docker exec <instagram_inbound_worker> whoami` ≠ root; `no-new-privileges`/`cap_drop` presentes; límites configurados (CE-120).
- [ ] `check-externos-backend.sh` verde; `ig:inbound` ≠ `wa:inbound`; suites de WhatsApp verdes sin modificar asserts (CE-120).

## Notas de seguridad (C2/C3)
- C2: descartes/errores loguean solo metadatos de enrutado; borrado lógico heredado; cero contenido de DM en logs.
- C3: el worker no materializa secretos de transporte (el token Bearer vive en SPEC-089); si usa algún `INSTAGRAM_*`, solo desde `Settings`, nunca en logs.

## Restricción SENSIBLE / egress
- 🔴 SENSIBLE: la ingesta persiste bajo RLS fijada antes de escribir (ADR-004/008); el pipeline IA es 100% local sin egress (ADR-005); el worker vive en `app` pero esta SPEC NO abre egress a Meta (la descarga de media es SPEC-088; el envío es SPEC-089). `check-externos-backend.sh` verde. **Bloqueo de Meta App Review (R-110):** la ingesta se verifica con el simulador firmado (SPEC-091) + cuentas de prueba, NO con tráfico de usuarios reales hasta que Meta apruebe (Q1=B, DIFERIDO al Lead).

## Riesgos
- R-111 (**top** — fuga cross-tenant): función `SECURITY DEFINER` pre-RLS + RLS antes de escribir + descarte auditado sin mapeo; test cross-tenant que falla.
- R-113 (**top** — idempotencia/colisión de `wamid`): dedup por `mid` en `messages.wamid` (guarda + UNIQUE); nota §3.4; ningún código asume formato WhatsApp.
- R-117 (regresión de WhatsApp): cola/worker separados; pipeline IA reutilizado sin tocarlo.
- R-110 (bloqueo de Meta App Review): verificación con simulador + cuentas de prueba; activación real diferida al Lead (C6).

## Checkpoints aplicables
- C2 (minimización en logs/descartes). C3 (secretos solo desde `Settings`, fuera de logs). C4 (criterios verificables). C8 (origen PLAN-012 / `prompt-lab/prompts/PROMPT-012-INSTAGRAM-DM.md`).
