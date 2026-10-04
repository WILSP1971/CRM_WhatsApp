# Runbook Operativo — Canal Instagram Direct Message (SPEC-091, cierra PLAN-012)

> Guía de procedimientos operativos para configuración, mantenimiento y troubleshooting del canal Instagram DM (Instagram Messaging API vía Meta Graph API).
> Clasificación: SENSIBLE (`.no-externo`). Extiende `RUNBOOK.md`, espejo del patrón de `RUNBOOK_WHATSAPP.md` (SPEC-034).
> **Depende de SPEC-085..090** (modelo de datos, webhook, ingesta, media, envío, auditoría de seguridad) — este runbook documenta el conjunto ya implementado.

## Tabla de contenidos

1. [Alta de la app de Meta y cuenta IG Business](#alta-de-la-app-de-meta-y-cuenta-ig-business)
2. [Configuración del webhook en Meta](#configuración-del-webhook-en-meta)
3. [Secret manager y variables de entorno](#secret-manager-y-variables-de-entorno)
4. [Ventana de mensajería de Instagram (message tags, NO HSM)](#ventana-de-mensajería-de-instagram-message-tags-no-hsm)
5. [Rotación de tokens de acceso](#rotación-de-tokens-de-acceso)
6. [Simulador local de webhook firmado](#simulador-local-de-webhook-firmado)
7. [Media: persistencia de URL del CDN de Meta (SPEC-088, sin descarga)](#media-persistencia-de-url-del-cdn-de-meta-spec-088-sin-descarga)
8. [Limitación conocida: `estado_entrega` no progresa automáticamente](#limitación-conocida-estado_entrega-no-progresa-automáticamente)
9. [🔴 BLOQUEO DE META APP REVIEW — explícito, sin edulcorar](#-bloqueo-de-meta-app-review--explícito-sin-edulcorar)
10. [Troubleshooting — Incidentes comunes](#troubleshooting--incidentes-comunes)
11. [Verificación de egress acotado](#verificación-de-egress-acotado)
12. [Informe de alcance E2E (HAWKEYE, SPEC-091)](#informe-de-alcance-e2e-hawkeye-spec-091)

---

## Alta de la app de Meta y cuenta IG Business

### Prerrequisitos (SOLO el Lead/negocio puede aportarlos)

- Cuenta de Meta Business (https://business.facebook.com)
- Una **Página de Facebook** vinculada a una **cuenta de Instagram Business** (o Creator) — la Instagram Messaging API opera sobre esa vinculación, no sobre un login directo de Instagram
- Una **app de Meta for Developers** con el producto **"Instagram"**/"Messenger" añadido
- **Meta App Review aprobado** para los permisos `instagram_manage_messages`, `instagram_basic`, `pages_messaging` (ver sección de bloqueo más abajo — esto es responsabilidad del Lead/negocio, NO del equipo de desarrollo)

### Procedimiento de alta

1. **Acceder a Meta for Developers:**
   ```
   https://developers.facebook.com/apps/<APP_ID>/dashboard/
   ```

2. **Vincular la Página de Facebook y la cuenta de Instagram Business:**
   - La cuenta de Instagram debe ser de tipo **Business** o **Creator** (no personal)
   - Debe estar vinculada a una Página de Facebook administrada por el mismo Business Manager
   - Ir a "Instagram → Configuración básica" en el dashboard de la app

3. **Obtener IDs necesarios:**
   - `instagram_business_account_id`: id de la cuenta de Instagram Business (visible en Graph API Explorer: `GET /me/accounts` → `instagram_business_account`)
   - Guardar este valor en la tabla `instagram_accounts` del CRM (SPEC-085, vía provisión del tenant), NUNCA solo en una variable de entorno en despliegues multi-tenant (`INSTAGRAM_BUSINESS_ACCOUNT_ID` de env es SOLO el fallback de un entorno de una sola cuenta)

4. **Solicitar Meta App Review** (ver sección dedicada abajo — bloqueante para usuarios reales).

---

## Configuración del webhook en Meta

### Requisitos de TLS

Igual que WhatsApp: Meta requiere **HTTPS válido** (certificado TLS no autofirmado, no expirado) en un dominio público.

### Pasos de configuración en Meta

1. **Acceder a la configuración de Webhooks de la app:**
   ```
   https://developers.facebook.com/apps/<APP_ID>/webhooks/
   ```
   Seleccionar el producto **Instagram** (los webhooks de Instagram DM son un producto separado de los de WhatsApp dentro de la misma app, aunque compartan infraestructura de Meta).

2. **Configurar el webhook:**
   - **Callback URL:** `https://api.tudominio.com/api/v1/instagram/webhook` (HTTPS obligatorio, path DISTINTO del de WhatsApp — `app/integrations/instagram/webhook.py`, SPEC-086)
   - **Verify Token:** generar una cadena aleatoria fuerte, DISTINTA del `WHATSAPP_VERIFY_TOKEN`:
     ```bash
     openssl rand -hex 16
     ```

3. **Suscribirse a los campos (`fields`) de `messaging`:**
   - `messages` (mensajes entrantes de texto/adjuntos) — el único campo que esta V1 necesita.
   - **`message_deliveries` NO está disponible para Instagram** (confirmado contra la documentación vigente de Meta: los campos de webhook ofrecidos para Instagram Messaging son `messages`, `message_reactions`, `messaging_postbacks`, `messaging_seen`, `messaging_optins`, `messaging_referrals` — `message_deliveries` es EXCLUSIVO de Messenger/Facebook). Por eso NO aparece como opción suscribible al configurar el webhook de Instagram en el Meta Dashboard; si aparece listado, es un artefacto de la UI compartida con Messenger y suscribirlo no tiene efecto para este canal. Ver la limitación de `estado_entrega` más abajo.
   - Dejar sin marcar: `message_reactions`, `messaging_postbacks`, `messaging_seen`, `messaging_optins`, `messaging_referrals`, etc. (fuera de alcance de esta V1; `messaging_seen` podría explorarse en una SPEC futura para aproximar "leído" vía su `watermark`, ver limitación de `estado_entrega`).

4. **Guardar y validar:**
   - Meta envía un GET con `hub.mode=subscribe`, `hub.verify_token`, `hub.challenge`
   - El webhook responde `hub.challenge` en texto plano si el token coincide (`GET /api/v1/instagram/webhook`, SPEC-086), 403 si no
   - Comparación en tiempo constante (`hmac.compare_digest`), igual criterio que WhatsApp

### Nota de alcance (bloqueo de App Review)

**Hasta que Meta apruebe la App Review**, este webhook SOLO puede recibir eventos de cuentas de rol de prueba (administradores/testers/developers de la app) en modo desarrollo — ver sección dedicada "🔴 BLOQUEO DE META APP REVIEW" más abajo.

---

## Secret manager y variables de entorno

### Variables críticas del canal (CHECKPOINT C3)

Mismo patrón que `WHATSAPP_*` (`RUNBOOK_WHATSAPP.md` §3) — **NUNCA** en repo ni en texto plano en logs:

| Variable | Descripción | Generación |
|---|---|---|
| `INSTAGRAM_APP_SECRET` | Secreto de firma (`X-Hub-Signature-256`, HMAC-SHA256) | Meta → App Settings → Basic |
| `INSTAGRAM_VERIFY_TOKEN` | Token de verificación del webhook (challenge GET) | `openssl rand -hex 16` |
| `INSTAGRAM_PAGE_ACCESS_TOKEN` | Access token (Bearer) de la Página/cuenta IG Business, usado por `graph_client.py` para ENVIAR | Meta → API Dashboard → Tokens (Page Access Token con permisos `instagram_manage_messages`) |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Fallback de una sola cuenta por entorno (en multi-tenant el id real viene de la tabla `instagram_accounts`, SPEC-085) | Graph API Explorer |
| `INSTAGRAM_API_VERSION` | Versión de la Graph API (el HOST queda FIJO a `graph.facebook.com`, nunca configurable — allowlist por código, ADR-006 ampliado) | Default `v21.0` |

Las 4 primeras tienen fail-fast fuera de `ENVIRONMENT=development` (`_require_strong_secret` en `app/core/config.py`): un valor débil/ausente impide arrancar el backend, igual criterio que `WHATSAPP_APP_SECRET`/`WHATSAPP_VERIFY_TOKEN`/`WHATSAPP_TOKEN`.

### Gestión en producción

**NUNCA en `.env` de repo ni en commits:**

```bash
# ❌ MAL (hardcodeado, expuesto):
INSTAGRAM_PAGE_ACCESS_TOKEN=EAA...<token-de-ejemplo-NO-real>...

# ✓ CORRECTO (placeholder + secret manager):
INSTAGRAM_PAGE_ACCESS_TOKEN=your-instagram-page-access-token-placeholder
```

**En producción, usar secret manager** (mismo patrón que WhatsApp, `RUNBOOK_WHATSAPP.md` §3):

```bash
# HashiCorp Vault:
vault kv put secret/instagram \
  app_secret=<secret-real> \
  verify_token=<token-real> \
  page_access_token=<token-real> \
  business_account_id=<id-real>

# AWS Secrets Manager:
aws secretsmanager create-secret \
  --name crm/instagram \
  --secret-string '{
    "app_secret":"...",
    "verify_token":"...",
    "page_access_token":"...",
    "business_account_id":"..."
  }'

# Inyección en docker-compose (producción, ya definido en docker-compose.yml):
#   instagram_send_worker:
#     environment:
#       INSTAGRAM_PAGE_ACCESS_TOKEN: ${INSTAGRAM_PAGE_ACCESS_TOKEN:?requerido}
#       INSTAGRAM_BUSINESS_ACCOUNT_ID: ${INSTAGRAM_BUSINESS_ACCOUNT_ID:-}
#       INSTAGRAM_API_VERSION: ${INSTAGRAM_API_VERSION:-v21.0}
```

### Auditoría de exposición (C3)

```bash
# Verificar que NO hay secretos reales en repo
git log --all -p -- ".env" ".env.example" | grep -E "EAA|ya29\.|sk-" && echo "FALLO: secretos encontrados" || echo "✓ OK: sin secretos en repo"

# Verificar que .env no está trackeado
git check-ignore .env && echo "✓ OK: .env en .gitignore" || echo "FALLO: .env está trackeado"

# Verificar logs en producción
docker compose logs api instagram_send_worker 2>&1 | grep -i "instagram_app_secret\|instagram_page_access_token\|instagram_verify_token" \
  && echo "FALLO: secretos en logs" || echo "✓ OK: sin secretos en logs"
```

---

## Ventana de mensajería de Instagram (message tags, NO HSM)

### Diferencia fundamental con WhatsApp

**Instagram Messaging API NO tiene plantillas HSM** (Highly Structured Messages) como WhatsApp. En su lugar usa **message tags** — una regla de ventana PROPIA, confirmada contra la documentación vigente de Meta (SPEC-089, `instagram_send_worker._resolve_send_tag`, decisión de arquitecto fijada, **NO reabrir** — R-116):

| Tiempo desde el último mensaje ENTRANTE del contacto | Comportamiento | Tag enviado |
|---|---|---|
| `≤ 24 horas` | Ventana ESTÁNDAR: texto libre sin restricción | (ninguno, se omite del body) |
| `24 horas < t ≤ 7 días` | Ventana EXTENDIDA: SOLO si el mensaje fue **aprobado por un agente humano real** (nunca autoenvío) y es seguimiento de un caso de soporte en curso | `HUMAN_AGENT` |
| `> 7 días` | **BLOQUEADO** — Meta rechazaría el envío; ningún tag lo cubre | N/A, no se intenta la Graph API |
| Sin mensaje entrante previo (conversación iniciada por el agente) | **BLOQUEADO** (fail-closed) | N/A |

**Nunca se reutiliza** `WHATSAPP_SESSION_WINDOW_HOURS`/`WHATSAPP_TEMPLATE_NAME` para Instagram: son mecanismos de plataforma distintos, hardcodeados como constantes de dominio en `app/integrations/instagram/graph_client.py` / `app/workers/instagram_send_worker.py` (no son un parámetro operativo configurable, sino un hecho de la política de Meta).

Un envío bloqueado por ventana persiste `estado_entrega="failed"` con el motivo en logs (`instagram_outbound_send_failed`, `error_type=WindowBlockedError`), sin reintento automático — requiere que el contacto vuelva a escribir para reabrir la ventana.

---

## Rotación de tokens de acceso

### `INSTAGRAM_PAGE_ACCESS_TOKEN`

Meta emite Page Access Tokens de larga duración (~60 días, igual que `WHATSAPP_TOKEN`). Procedimiento de rotación (espejo de `RUNBOOK_WHATSAPP.md` §6):

1. **Obtener nuevo token:**
   ```
   Meta API Dashboard → Settings → User Token Manager → Page Access Token
   o
   POST https://graph.facebook.com/oauth/access_token?
     grant_type=fb_exchange_token&
     client_id=<CLIENT_ID>&
     client_secret=<CLIENT_SECRET>&
     fb_exchange_token=<OLD_TOKEN>
   ```

2. **Almacenar en secret manager:**
   ```bash
   vault kv put secret/instagram page_access_token=<NEW_TOKEN>
   ```

3. **Actualizar en contenedor (downtime mínimo):**
   ```bash
   docker compose restart instagram_send_worker
   ```
   (El webhook de recepción, `api`, NO usa `INSTAGRAM_PAGE_ACCESS_TOKEN` — solo `instagram_send_worker` envía; un reinicio de ese worker NO afecta la ingesta.)

4. **Verificar que funciona** (requiere credenciales reales y una cuenta de prueba — bloqueado sin App Review para usuarios reales, ver sección dedicada):
   ```bash
   curl -X POST "https://graph.facebook.com/v21.0/<INSTAGRAM_BUSINESS_ACCOUNT_ID>/messages" \
     -H "Authorization: Bearer <NEW_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"recipient":{"id":"<TESTER_IG_SCOPED_ID>"},"message":{"text":"Token nuevo OK"}}'
   ```

5. **Documentar:** fecha de rotación, fecha de expiración esperada, revocar token antiguo.

### `INSTAGRAM_APP_SECRET` / `INSTAGRAM_VERIFY_TOKEN`

Mismo procedimiento que WhatsApp (`RUNBOOK_WHATSAPP.md` §6, troubleshooting de firma): rotar en Meta App Settings → Basic (app_secret) o regenerar con `openssl rand -hex 16` (verify_token) y actualizar ambos lados (secret manager + configuración del webhook en Meta Dashboard) de forma coordinada para evitar una ventana de rechazo.

---

## Simulador local de webhook firmado

### Propósito

Pruebas locales del endpoint `/api/v1/instagram/webhook` sin credenciales reales de Meta — espejo EXACTO del simulador de WhatsApp (SPEC-034), adaptado al formato `object:"instagram"`/`entry[].messaging[]` (SPEC-086).

### Ubicación

```
backend/tools/ig_webhook_simulator.py
```

### Uso

**1. Emitir un mensaje de texto entrante (firma válida):**

```bash
cd /home/swarm/proyectos/CRM_WhatsApp

export INSTAGRAM_APP_SECRET=$(openssl rand -hex 32)
export WEBHOOK_URL=http://localhost:8000/api/v1/instagram/webhook

python backend/tools/ig_webhook_simulator.py
```

**Salida esperada:**

```
📨 Emitiendo webhook de Instagram DM (mensaje entrante)...
  mid: mid.<uuid>
  instagram_account_id (recipient): IG_ACCOUNT_ID_PLACEHOLDER
  sender_id: ig-sender-9988776655
  texto: Hola, ¿tienen disponible el producto en talla M?...
  X-Hub-Signature-256: sha256=...
  Respuesta: 200

✓ Webhook ACEPTADO (200 OK)
  Verificar que el evento se encoló en Redis: ig:inbound
```

**2. Emitir un challenge (GET):**

```bash
python backend/tools/ig_webhook_simulator.py --challenge
```

(`--challenge --bad-token` emite un token incorrecto a propósito, espera 403.)

**3. Probar idempotencia (mensaje duplicado por `mid`):**

```bash
python backend/tools/ig_webhook_simulator.py --duplicate
```

```
[PASO 1] Emitiendo mensaje inicial... Respuesta: 200
[PASO 2] Emitiendo DUPLICADO del mismo mid... Respuesta: 200
✓ Ambos webhooks aceptados (200).
  Verificar SPEC-087: debe haber solo 1 Message en BD (dedup por mid)
```

**4. Probar persistencia de media (attachment, SPEC-088):**

```bash
python backend/tools/ig_webhook_simulator.py --attachment
```

Emite un adjunto con una URL CON FORMA de `lookaside.fbsbx.com` (placeholder ficticio, no un recurso real) — verifica que `messages.media_url`/`media_type` se persisten tal cual (ver sección de media más abajo).

**5. Probar rechazo de firma inválida/ausente (401, sin encolar):**

```bash
python backend/tools/ig_webhook_simulator.py --bad-signature
python backend/tools/ig_webhook_simulator.py --no-signature
```

### Verificado en esta SPEC (SPEC-091)

Ejecutado end-to-end contra una instancia local de `app.main:app` con un doble de Redis (`fakeredis` vía TCP): los 5 flujos (challenge válido/inválido, firma válida→200→encolado, firma inválida/ausente→401 sin encolar, duplicado por `mid`, attachment) respondieron con el status esperado y el payload se verificó en la cola `ig:inbound`. Ver informe de alcance E2E al final de este runbook.

### Target Makefile

```bash
make ig-sim               # mensaje simple
make ig-sim-dup           # duplicado (idempotencia)
make ig-sim-attachment    # con adjunto (media_url)
make ig-sim-challenge     # GET challenge
make ig-sim-bad-signature # firma inválida (401 esperado)
```

---

## Media: persistencia de URL del CDN de Meta (SPEC-088, sin descarga)

### Diseño vigente (revisado tras aprobación original — ver nota en `SPEC-088.md`)

A diferencia de WhatsApp (que SÍ descarga y cifra el binario de notas de voz, `whatsapp/media_client.py`, ADR-009), el canal Instagram DM **NO descarga ningún binario de media**. El worker de ingesta (`instagram_inbound_worker`, SPEC-087) solo:

1. Valida la FORMA de la URL recibida en `message.attachments[].payload.url` (`media_url_validator.py`): debe ser `https://`, host EXACTO `lookaside.fbsbx.com`, sin userinfo embebido (`user:pass@host`).
2. Si es válida, persiste la URL TAL CUAL en `messages.media_url` + el tipo (`image`/`video`/etc.) en `messages.media_type` — SIN abrir ninguna conexión HTTP a esa URL (cero egress de backend para media).
3. Si es inválida (host distinto, no-https, userinfo embebido), NO persiste la referencia, pero el mensaje de texto (`"[attachment]"`) sí se guarda — no rompe el flujo de ingesta.
4. El único consumidor real de esa URL es el **navegador del agente humano** en el frontend (`ConversationThread.tsx`, SPEC-090) al renderizar el adjunto — la URL del CDN de Meta expira tras un tiempo corto, es de un solo uso según política de Meta.

**Por eso ADR-017 (egress del CDN de media) NO se creó**: no hay egress de backend que acotar bajo este diseño.

### Verificación

```bash
# Simulador local (ver sección anterior):
python backend/tools/ig_webhook_simulator.py --attachment

# Tests automatizados (ya cubren esto exhaustivamente, SPEC-088/091):
pytest backend/tests/test_instagram_inbound_worker.py -k media -v
```

---

## Limitación conocida: `estado_entrega` no progresa automáticamente

**Decisión documentada en la nota de revisión de SPEC-089 (NO reabrir, confirmado contra documentación vigente de Meta, múltiples fuentes consistentes):**

El campo de suscripción de webhook `message_deliveries` (el callback `delivery`, `{"mids": [...], "watermark": ...}`) **NO está disponible para Instagram, SOLO para Messenger/Facebook**. Los campos que Instagram sí soporta son `messages`/`message_reactions`/`messaging_postbacks`/`messaging_seen`/`messaging_optins`/`messaging_referrals` — no existe ningún equivalente de `message_deliveries` para este canal.

En consecuencia:

- `parse_delivery_events`/`_process_delivery_event` (en `inbound_parser.py`/`instagram_inbound_worker.py`) **existen como código funcional y correcto**, pero son efectivamente **código MUERTO**: Meta nunca envía ese callback a Instagram, por lo que nunca se ejecutan en producción. No representan un riesgo (no hacen nada incorrecto si se invocaran), solo quedan sin disparar.
- `estado_entrega` de los mensajes salientes de Instagram se queda en **`"enviado"`** (confirmado de forma síncrona por el 200 OK de la Graph API al momento del envío) y **NO progresa automáticamente a `"entregado"`/`"leido"`** — a diferencia de WhatsApp (que sí progresa `enviado → entregado → leido` vía `value.statuses[]`).
- El campo `messaging_seen` (que sí soporta Instagram) trae un `watermark` de marca de tiempo sin `mid` por mensaje individual — no permite conciliar mensaje-por-mensaje; una extensión futura podría aproximar "leído" de forma agregada (todos los mensajes anteriores al `watermark`), pero eso es alcance de una SPEC nueva, no de esta.

**Esto es una limitación de la plataforma de Meta, no un bug del CRM, y no depende del estado de la App Review.** El frontend debe mostrar el estado "enviado" sin prometer confirmación de entrega/lectura para mensajes de Instagram.

---

## 🔴 BLOQUEO DE META APP REVIEW — explícito, sin edulcorar

### Qué exige Meta

La Instagram Messaging API (a través de la Graph API) exige, para intercambiar mensajes con **usuarios reales** (cualquier persona que no sea administrador/tester/developer de la propia app de Meta):

1. **Meta App Review aprobado** para los permisos:
   - `instagram_manage_messages` (leer/enviar DMs de Instagram)
   - `instagram_basic` (lectura básica de la cuenta IG Business)
   - `pages_messaging` (la infraestructura de mensajería de Instagram se apoya en el grafo de Páginas de Facebook)
2. Una **cuenta de Instagram Business (o Creator) vinculada** a una Página de Facebook del mismo Business Manager.
3. **Tokens de acceso reales** (`INSTAGRAM_PAGE_ACCESS_TOKEN`) emitidos tras la vinculación.

### Qué puede verificarse HOY sin App Review aprobado

- **Todo lo que NO requiera un usuario real de Instagram**: el modelo de datos (SPEC-085), el parseo del webhook (SPEC-086), la ingesta idempotente y el enrutado multi-tenant (SPEC-087), la persistencia de URLs de media (SPEC-088), la ventana de mensajería y el cliente de envío (SPEC-089, contra payloads simulados), la auditoría de seguridad (SPEC-090).
- **Payloads firmados simulados** (`ig_webhook_simulator.py`, esta SPEC) ejercitan el CONTRATO completo del webhook (firma HMAC, challenge, idempotencia por `mid`, media) sin necesitar que Meta apruebe nada — el simulador NUNCA llama a Meta, solo al webhook local.
- **Cuentas de rol de prueba** (admin/tester/developer añadidas manualmente a la app en Meta Dashboard → Roles): Meta SÍ permite intercambiar mensajes reales con ESAS cuentas específicas en modo desarrollo, sin App Review. Esto permitiría una prueba E2E real (webhook real de Meta → backend → respuesta real) pero:
  - Requiere que el Lead/negocio dé de alta una app de Meta real, vincule una cuenta IG Business real y añada cuentas de prueba — **prerequisitos que el equipo de desarrollo NO puede generar por sí mismo** (no se simulan credenciales/cuentas reales de Meta, C3).
  - **No se ejecutó en esta SPEC** porque esos prerequisitos NO están disponibles en este entorno de trabajo (confirmado: no hay app de Meta real configurada, no hay cuenta IG Business de prueba vinculada). Ver "Informe de alcance E2E" abajo.

### Qué queda DIFERIDO al Lead

- **La activación del canal con usuarios reales** (clientes finales escribiendo por Instagram DM) está **completamente bloqueada** hasta que:
  1. El Lead/negocio complete el trámite de Meta App Review (gestión externa, fuera del alcance de este equipo — PLAN-012 §OUT lo excluye explícitamente).
  2. Meta apruebe los 3 permisos.
  3. Se configuren los secretos reales (`INSTAGRAM_PAGE_ACCESS_TOKEN`, etc.) en el secret manager de producción.
- **El deploy on-prem de los servicios Docker** (`instagram_inbound_worker`, `instagram_send_worker`) puede ejecutarse ANTES de que Meta apruebe la app (los contenedores arrancan igual, el webhook responde igual) — pero sin App Review, el webhook real de Meta en producción solo recibirá eventos de cuentas de prueba, nunca de clientes reales. El deploy en sí mismo (C6) requiere aprobación explícita del Lead, independientemente del estado de App Review.

### Resumen (tabla de trazabilidad, R-110)

| Qué | Verificado HOY | Cómo |
|---|---|---|
| Firma HMAC-SHA256 (válida/inválida/ausente) | ✓ | Simulador + `test_instagram_webhook.py` |
| Challenge GET (token válido/inválido) | ✓ | Simulador + `test_instagram_webhook.py` |
| Idempotencia por `mid` | ✓ | Simulador + `test_instagram_inbound_worker.py` |
| Cross-tenant (aislamiento RLS) | ✓ | `test_instagram_inbound_worker.py` (payload simulado) |
| Persistencia de `media_url`/`media_type` | ✓ | Simulador + `test_instagram_inbound_worker.py` |
| Ventana de mensajería (24h/`HUMAN_AGENT`/7d) | ✓ (unidad, función pura) | `test_instagram_send_worker.py` |
| Envío real a un destinatario de Instagram | ✗ DIFERIDO | Requiere token real + cuenta de prueba/real de Meta |
| Recepción de un webhook REAL emitido por Meta | ✗ DIFERIDO | Requiere app de Meta + cuenta IG Business vinculada |
| `estado_entrega` progresando a "leído" | ✗ NO SOPORTADO | Instagram no expone ese callback (limitación de plataforma, no bloqueo de App Review) |
| Activación con usuarios reales | ✗ DIFERIDO AL LEAD (C6) | App Review aprobado + secretos reales + aprobación de deploy |

---

## Troubleshooting — Incidentes comunes

### Incidente: Firma HMAC rechazada (401)

**Síntomas:** Webhook devuelve 401, logs: `instagram_webhook_signature_rejected`.

**Diagnóstico:**

```bash
# Verificar que INSTAGRAM_APP_SECRET es correcto
docker compose exec api env | grep INSTAGRAM_APP_SECRET

# Comparar con el simulador
python backend/tools/ig_webhook_simulator.py 2>&1 | grep "X-Hub-Signature"
```

**Solución:** actualizar en secret manager + reiniciar `api`.

### Incidente: Challenge rechazado (403)

**Síntomas:** Al configurar webhook en Meta, falla con "The URL couldn't be validated"/token incorrecto.

**Diagnóstico:**

```bash
docker compose exec api env | grep INSTAGRAM_VERIFY_TOKEN
export WEBHOOK_URL=http://localhost:8000/api/v1/instagram/webhook
python backend/tools/ig_webhook_simulator.py --challenge
```

**Solución:** regenerar token (`openssl rand -hex 16`), actualizar en Meta Dashboard EXACTAMENTE con ese valor, reintentar "Verify and Save".

### Incidente: Webhook acepta (200) pero no se ve nada procesado

**Síntomas:** Simulador/Meta devuelve 200, pero `ig:inbound` no se vacía.

**Diagnóstico:**

```bash
docker compose exec redis redis-cli LLEN ig:inbound
docker compose logs instagram_inbound_worker --tail=50
```

**Solución:** verificar que `instagram_inbound_worker` está arriba (`docker compose ps`); reiniciar si está caído (`docker compose restart instagram_inbound_worker`).

### Incidente: Envío bloqueado por ventana (`WindowBlockedError`)

**Síntomas:** `instagram_outbound_send_failed` con `error_type=WindowBlockedError`; `estado_entrega="failed"`.

**Diagnóstico:** el contacto no ha escrito en los últimos 7 días (o nunca ha escrito, conversación iniciada por el agente).

**Solución:** no hay bypass — es una regla dura de Meta. Esperar a que el contacto vuelva a escribir (reabre la ventana de 24h) o, si aplica, usar otro canal (WhatsApp) para ese contacto.

### Incidente: Mensajes de Instagram nunca pasan a "entregado"/"leído"

**Síntomas:** `estado_entrega` se queda en "enviado" indefinidamente.

**Diagnóstico/Solución:** NO es un bug — ver sección "Limitación conocida" arriba. Instagram no expone un callback de lectura conciliable por mensaje; `delivery` existe en código pero su disponibilidad real depende de la política de Meta vigente (no confirmada en producción sin App Review).

---

## Verificación de egress acotado

### ADR-006 (ampliada para Instagram, PLAN-012 §11.1)

Mismo host ya autorizado para WhatsApp (`graph.facebook.com`), ahora también desde `app/integrations/instagram/`. Egress permitido SOLO desde `api` (webhook, que solo RECIBE — no egresa), `instagram_send_worker` (envío) — `instagram_inbound_worker` permanece SIN egress (solo persiste URLs de media, nunca las descarga).

```bash
# Verificar allowlist por ruta (check-externos-backend.sh, SPEC-085/090)
bash backend/check-externos-backend.sh .

# Verificar que instagram_inbound_worker NO tiene egress real
docker compose exec instagram_inbound_worker sh -c "timeout 5 wget -T3 -qO- https://graph.facebook.com 2>&1" \
  && echo "✗ FALLO: egress desbloqueado" \
  || echo "✓ EGRESS BLOQUEADO (expected, el worker de ingesta no debe egresar)"

# instagram_send_worker SÍ tiene egress (necesario para enviar a Meta)
docker compose exec instagram_send_worker sh -c "timeout 5 curl -s -I https://graph.facebook.com | head -1"
```

---

## Informe de alcance E2E (HAWKEYE, SPEC-091)

**Verificado en esta SPEC (2026-10-04, entorno de desarrollo local, sin Postgres/Redis de producción):**

1. **Simulador firmado end-to-end contra el webhook real del backend** (`app.main:app`, levantado localmente con `uvicorn`, Redis mediante un doble `fakeredis` en TCP): confirmado que
   - GET challenge con `verify_token` correcto → 200 + `hub.challenge` exacto en el body.
   - GET challenge con `verify_token` incorrecto → 403.
   - POST con firma HMAC-SHA256 válida → 200 + evento encolado en `ig:inbound` (verificado leyendo la cola directamente).
   - POST con firma inválida → 401, cola vacía.
   - POST sin cabecera de firma → 401, cola vacía.
   - POST duplicado (mismo `mid`) → ambos 200 (la deduplicación real ocurre en el worker de ingesta, verificado en los tests de Postgres de abajo).
   - POST con `attachments` (URL con forma de `lookaside.fbsbx.com`) → 200, payload correcto en cola.
2. **Suite automatizada completa del canal** (`test_instagram_webhook.py`, `test_instagram_inbound_parser.py`, `test_instagram_inbound_worker.py`, `test_instagram_send_worker.py`, `test_instagram_graph_client.py`, `test_instagram_queue.py`, `test_instagram_outbound_queue.py`): idempotencia por `mid` (incluida bajo concurrencia real con hilos), aislamiento cross-tenant (test que verifica fuga, con RLS real sobre Postgres), parser ante payloads reales/malformados, persistencia/no-persistencia de `media_url` según validación de host/esquema, disparo de sentimiento + borrador RAG, conciliación de `delivery` → `estado_entrega`.

**DIFERIDO (bloqueado por Meta App Review, R-110 — no ejecutado ni ejecutable en este entorno):**

- Webhook REAL emitido por Meta (no por el simulador) contra una app de Meta real.
- Envío real de un mensaje a un destinatario de Instagram (cuenta de prueba o real) vía `graph.facebook.com` con credenciales reales.
- Verificación del callback `delivery` real de Meta (su disponibilidad/forma exacta en producción no está confirmada sin App Review).
- Cualquier intercambio con un usuario final real de Instagram (bloqueado por diseño de Meta hasta App Review).

**Conclusión honesta:** el contrato de ingesta/envío/seguridad del canal Instagram DM está **completamente verificado en local con payloads simulados y la suite automatizada** (sin huecos de cobertura identificados en los criterios de aceptación de SPEC-091). La verificación con **tráfico real de Meta y usuarios reales permanece bloqueada** por el trámite externo de Meta App Review, responsabilidad del Lead/negocio — no se "completó" esa parte ni se simula de forma que oculte este límite.

---

**Última actualización:** 2026-10-04 · **SPEC:** SPEC-085..091 (cierra PLAN-012) · **ADR:** ADR-006 (ampliada), ADR-007, ADR-008
**Referencias:** RUNBOOK.md, RUNBOOK_WHATSAPP.md, DEPLOYMENT_CHECKLIST_INSTAGRAM.md, ADR-006 (excepción egress ampliada), SPEC-088.md (nota de revisión post-aprobación, media sin descarga), SPEC-089.md (nota de revisión, `estado_entrega` sin progresión automática)
