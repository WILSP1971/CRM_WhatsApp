# Runbook Operativo — Canal WhatsApp (SPEC-034)

> Guía de procedimientos operativos para configuración, mantenimiento y troubleshooting del canal WhatsApp Business Cloud API.
> Clasificación: SENSIBLE (`.no-externo`). Extiende RUNBOOK.md.

## Tabla de contenidos

1. [Alta de WABA y número](#alta-de-waba-y-número)
2. [Configuración del webhook en Meta](#configuración-del-webhook-en-meta)
3. [Secret manager y variables de entorno](#secret-manager-y-variables-de-entorno)
4. [TLS del webhook (HTTPS)](#tls-del-webhook-https)
5. [Plantillas HSM (Highly Structured Messages)](#plantillas-hsm-highly-structured-messages)
6. [Rotación de tokens de acceso](#rotación-de-tokens-de-acceso)
7. [Simulador local de webhook](#simulador-local-de-webhook)
8. [Troubleshooting — Incidentes comunes](#troubleshooting--incidentes-comunes)
9. [Monitoring y observabilidad](#monitoring-y-observabilidad)
10. [Verificación de egress acotado](#verificación-de-egress-acotado)

---

## Alta de WABA y número

### Prerrequisitos

- Cuenta de Meta Business (https://business.facebook.com)
- Aplicación de WhatsApp Business API configurada
- Acceso a API Dashboard

### Procedimiento de alta de WABA

1. **Acceder a Meta for Developers:**
   ```
   https://developers.facebook.com/apps/<APP_ID>/dashboard/
   ```

2. **Crear o vincular un WABA (WhatsApp Business Account):**
   - Ir a "WhatsApp → Getting Started"
   - Seleccionar "Create New WABA" o "Link Existing WABA"
   - Seguir los pasos de verificación de la empresa

3. **Verificación de número de teléfono:**
   - Ir a "Phone Numbers" en el dashboard
   - Añadir un número: puede ser un número existente o solicitar uno nuevo
   - Meta enviará un código de verificación por SMS
   - Ingresar el código para completar la verificación

4. **Obtener IDs necesarios:**
   - `WABA_ID`: ID de la cuenta de WhatsApp (visible en dashboard)
   - `PHONE_NUMBER_ID`: ID del número (visible bajo "Phone Numbers")
   - Guardar estos valores en secret manager (NO en repo)

---

## Configuración del webhook en Meta

### Requisitos de TLS

Meta requiere que el webhook sea **HTTPS válido** (certificado TLS válido). En producción:

- Usar un certificado de Let's Encrypt o CA corporativa
- Certificado NO expirado, NO autofirmado
- Disponible en un dominio público (ej. `api.tudominio.com`)

### Pasos de configuración en Meta

1. **Acceder a la configuración del webhook:**
   ```
   https://developers.facebook.com/apps/<APP_ID>/webhooks/
   ```

2. **Configurar el webhook:**
   - **Callback URL:** `https://api.tudominio.com/api/v1/whatsapp/webhook` (HTTPS obligatorio)
   - **Verify Token:** Generar una cadena aleatoria fuerte:
     ```bash
     openssl rand -hex 16
     ```
     Ejemplo: `a7f2d4c9e1b5f8a3`

3. **Suscribirse a eventos:**
   - Messages (mensajes entrantes)
   - Message Status (cambios de estado de mensajes enviados)
   - Dejar sin marcar: Account Alerts, etc.

4. **Guardar y validar:**
   - Meta enviará un GET con `hub.mode=subscribe`, `hub.verify_token`, `hub.challenge`
   - El webhook debe responder con `hub.challenge` en texto plano si el token coincide
   - SPEC-026 implementa esto en el endpoint GET `/api/v1/whatsapp/webhook`

---

## Secret manager y variables de entorno

### Variables críticas (CHECKPOINT C3)

Las 4 variables **NUNCA** deben estar en repo ni en texto plano en logs:

| Variable | Descripción | Generación |
|---|---|---|
| `WHATSAPP_TOKEN` | Access token permanente (long-lived) | Meta → API Dashboard → Tokens |
| `WHATSAPP_PHONE_NUMBER_ID` | ID del número de teléfono | Meta → Phone Numbers |
| `WHATSAPP_VERIFY_TOKEN` | Token de verificación del webhook | `openssl rand -hex 16` |
| `WHATSAPP_APP_SECRET` | Secreto de firma (X-Hub-Signature-256) | Meta → App Settings → Basic |

### Gestión en producción

**NUNCA en `.env` de repo ni en commits:**

```bash
# ❌ MAL (hardcodeado, expuesto):
WHATSAPP_TOKEN=EAA...<token-de-ejemplo-NO-real>...

# ✓ CORRECTO (placeholder + secret manager):
WHATSAPP_TOKEN=your-whatsapp-business-token-placeholder
```

**En producción, usar secret manager:**

- **HashiCorp Vault:**
  ```bash
  vault kv put secret/whatsapp \
    token=<token-real> \
    phone_number_id=<id-real> \
    verify_token=<token-real> \
    app_secret=<secret-real>
  ```

- **AWS Secrets Manager:**
  ```bash
  aws secretsmanager create-secret \
    --name crm/whatsapp \
    --secret-string '{
      "token":"...",
      "phone_number_id":"...",
      "verify_token":"...",
      "app_secret":"..."
    }'
  ```

- **Inyección en docker-compose (production):**
  ```yaml
  api:
    environment:
      WHATSAPP_TOKEN: ${WHATSAPP_TOKEN}  # desde secret manager, no .env
      WHATSAPP_PHONE_NUMBER_ID: ${WHATSAPP_PHONE_NUMBER_ID}
      WHATSAPP_VERIFY_TOKEN: ${WHATSAPP_VERIFY_TOKEN}
      WHATSAPP_APP_SECRET: ${WHATSAPP_APP_SECRET}
  ```

### Auditoría de exposición (C3)

```bash
# Verificar que NO hay secretos reales en repo
git log --all -p -- ".env" ".env.example" | grep -E "EAA|ya29\.|sk-" && echo "FALLO: secretos encontrados" || echo "✓ OK: sin secretos en repo"

# Verificar que .env no está trackeado
git check-ignore .env && echo "✓ OK: .env en .gitignore" || echo "FALLO: .env está trackeado"

# Verificar logs en producción
docker compose logs api 2>&1 | grep -i "whatsapp_token\|app_secret" && echo "FALLO: secretos en logs" || echo "✓ OK: sin secretos en logs"
```

---

## TLS del webhook (HTTPS)

### Configuración de reverse proxy

El endpoint `/api/v1/whatsapp/webhook` DEBE estar accesible por HTTPS desde internet.

**Ejemplo con Nginx:**

```nginx
upstream api_backend {
    server api:8000;  # Host Docker interno
}

server {
    listen 443 ssl http2;
    server_name api.tudominio.com;

    # Certificado TLS (Let's Encrypt o CA)
    ssl_certificate /etc/letsencrypt/live/api.tudominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.tudominio.com/privkey.pem;

    # Headers de seguridad
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;

    # Permitir webhook de WhatsApp
    location /api/v1/whatsapp/webhook {
        proxy_pass http://api_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        client_max_body_size 10M;
    }

    # Redirigir otros paths a HTTPS
    location / {
        proxy_pass http://api_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}

# Redirigir HTTP plano a HTTPS
server {
    listen 80;
    server_name api.tudominio.com;
    return 301 https://$server_name$request_uri;
}
```

### Verificación de TLS

```bash
# Test básico
curl -v https://api.tudominio.com/api/v1/whatsapp/webhook \
  -H "X-Hub-Signature-256: sha256=fake" \
  -d '{"test":"payload"}'

# Debe responder 401 (sin firma válida) o 400 (bad request),
# pero NUNCA connection refused (TLS debe estar OK)

# Inspeccionar certificado
openssl s_client -connect api.tudominio.com:443 -showcerts | grep -A2 "Verify return code"

# Salida esperada:
# Verify return code: 0 (ok)
```

---

## Plantillas HSM (Highly Structured Messages)

### Contexto (SPEC-029)

Dentro de la **ventana de 24 horas** desde el último mensaje del contacto, se puede enviar texto libre.
Fuera de ventana, Meta requiere una **plantilla pre-aprobada** (HSM).

### Crear una plantilla en Meta

1. **Acceder a Business Manager:**
   ```
   https://business.facebook.com/wa/manage/message-templates/
   ```

2. **Crear una plantilla:**
   - Nombre: `generic_template` (o similar, configurable en `.env`)
   - Lenguaje: `es` (español, configurable)
   - Categoría: `UTILITY` (general)
   - Contenido de ejemplo:
     ```
     Hola {{1}},

     Este es un mensaje automatizado de nuestro sistema.
     Tenemos novedades sobre tu solicitud.

     Responde a este mensaje para continuar.

     {{2}}
     ```

3. **Enviar a aprobación:**
   - Meta revisa (típicamente < 1 hora)
   - Una vez aprobada, aparecerá en "Status: APPROVED"

### Configuración en `.env`

```bash
# Una vez que Meta aprueba la plantilla:
WHATSAPP_TEMPLATE_NAME=generic_template
WHATSAPP_TEMPLATE_LANGUAGE=es
WHATSAPP_SESSION_WINDOW_HOURS=24
```

### Uso en SPEC-029

El worker `wa_send_worker` verifica automáticamente:

```python
# Si estamos dentro de la ventana de 24h desde el último mensaje del contacto
# → enviar texto libre (sin plantilla)
# Si estamos fuera de ventana
# → usar plantilla; si no está configurada, rechazar el envío
```

### Troubleshooting de plantillas

**Síntoma:** Error al enviar mensajes fuera de ventana.

**Diagnóstico:**

```bash
# Verificar que la plantilla está aprobada en Meta
curl -G "https://graph.facebook.com/v21.0/<PHONE_NUMBER_ID>/message_templates" \
  --data-urlencode "access_token=<WHATSAPP_TOKEN>" | jq '.data[] | {name, status}'

# Salida esperada:
# [
#   {
#     "name": "generic_template",
#     "status": "APPROVED"  # ← Debe estar APPROVED
#   }
# ]
```

**Si está REJECTED o PENDING:**

- Ver motivo: `GET ...message_templates?fields=name,status,rejection_reason`
- Corregir según feedback de Meta
- Reenviar

---

## Rotación de tokens de acceso

### Token de acceso permanente (`WHATSAPP_TOKEN`)

Meta emite un "long-lived token" con validez **~60 días**. Antes de expirar, se debe rotar.

### Procedimiento de rotación

1. **Obtener nuevo token:**
   ```
   Meta API Dashboard → Settings → User Token Manager
   o
   POST https://graph.facebook.com/oauth/access_token?
     grant_type=fb_exchange_token&
     client_id=<CLIENT_ID>&
     client_secret=<CLIENT_SECRET>&
     fb_exchange_token=<OLD_TOKEN>
   ```

2. **Almacenar en secret manager:**
   ```bash
   # En Vault:
   vault kv put secret/whatsapp token=<NEW_TOKEN>

   # En AWS:
   aws secretsmanager update-secret \
     --secret-id crm/whatsapp \
     --secret-string '{"token":"<NEW_TOKEN>","..."}'
   ```

3. **Actualizar en contenedor (con downtime mínimo):**
   ```bash
   # Opción A: Actualizar env, restart (downtime ~10 s)
   docker compose restart wa_send_worker api
   
   # Opción B: Si soporta hot-reload, solo reload (sin downtime)
   # (Depende de la configuración de settings/reloading de la app)
   ```

4. **Verificar que funciona:**
   ```bash
   # Test POST a Graph API (requiere un número/mensaje reales)
   curl -X POST https://graph.facebook.com/v21.0/<PHONE_NUMBER_ID>/messages \
     -H "Authorization: Bearer <NEW_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{
       "messaging_product": "whatsapp",
       "recipient_type": "individual",
       "to": "<RECIPIENT_PHONE>",
       "type": "text",
       "text": {"body": "Test de token nuevo"}
     }'
   ```

5. **Documentar:**
   - Fecha de rotación
   - Fecha de expiración esperada (actual + 60 días)
   - Revocar token antiguo (opcional, en Vault/AWS)

---

## Simulador local de webhook

### Propósito

Pruebas locales del endpoint `/api/v1/whatsapp/webhook` sin credenciales reales de Meta.

### Ubicación

```
backend/tools/wa_webhook_simulator.py
```

### Requisitos

```bash
# Dependencias Python
pip install httpx
```

### Uso

**1. Emitir un mensaje entrante (firma válida):**

```bash
cd /home/swarm/proyectos/CRM_WhatsApp

export WHATSAPP_APP_SECRET=$(openssl rand -hex 32)
export WEBHOOK_URL=http://localhost:8000/api/v1/whatsapp/webhook

python backend/tools/wa_webhook_simulator.py
```

**Salida esperada:**

```
📨 Emitiendo webhook de mensaje entrante...
  URL: http://localhost:8000/api/v1/whatsapp/webhook
  wamid: a1b2c3d4-e5f6-4718-9f0e-1d2c3b4a5f6e
  phone_number_id: 1234567890
  from_phone: +34600123456
  content: Hola, ¿cuál es el estado de mi pedido?...
  X-Hub-Signature-256: sha256=ab12cd34...
  Respuesta: 200

✓ Webhook ACEPTADO (200 OK)
  Verificar que el mensaje se encoló en Redis: wa:inbound
```

**2. Emitir un challenge (GET):**

```bash
python backend/tools/wa_webhook_simulator.py --challenge
```

**Salida esperada:**

```
📨 Emitiendo GET de challenge (suscripción)...
  hub.mode: subscribe
  hub.verify_token: test-verify-token
  hub.challenge: <uuid>
  Respuesta: 200
  ✓ Challenge OK (body: <uuid>)
```

**3. Probar idempotencia (mensaje duplicado):**

```bash
python backend/tools/wa_webhook_simulator.py --duplicate
```

**Salida esperada:**

```
[PASO 1] Emitiendo mensaje inicial...
  Respuesta: 200

[PASO 2] Emitiendo DUPLICADO del mismo wamid...
  wamid: <MISMO> (idéntico al anterior)
  Respuesta: 200

✓ Ambos webhooks aceptados (200).
  Verificar SPEC-027: debe haber solo 1 mensaje en BD (dedup por wamid)
```

**4. Probar conciliación de statuses:**

```bash
python backend/tools/wa_webhook_simulator.py --status
```

**Salida esperada:**

```
📨 Emitiendo webhook de STATUS...
  status: sent
  Respuesta: 200

📨 Emitiendo webhook de STATUS...
  status: delivered
  Respuesta: 200

📨 Emitiendo webhook de STATUS...
  status: read
  Respuesta: 200

✓ Sequence de statuses completada (sent → delivered → read)
  Verificar SPEC-030: conciliación idempotente por wamid
```

### Target Makefile

```bash
make wa-sim
```

(Ver sección "Actualización del Makefile" en DEPLOYMENT_CHECKLIST.md extendido)

---

## Troubleshooting — Incidentes comunes

### Incidente: Firma HMAC rechazada (401)

**Síntomas:**
- Webhook devuelve 401 Unauthorized
- Logs: `whatsapp_webhook_signature_rejected`

**Diagnóstico:**

```bash
# 1. Verificar que app_secret es correcto
echo "App Secret en env: $WHATSAPP_APP_SECRET"

# 2. Verificar que la firma se computa correctamente
python -c "
import hmac, hashlib
body = '{\"test\":\"payload\"}'
secret = 'tu-secret-aqui'
sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
print(f'sha256={sig}')
"

# 3. Comparar con el header que envía el simulador
python backend/tools/wa_webhook_simulator.py 2>&1 | grep "X-Hub-Signature"

# 4. Si es distinto → app_secret incorrecto
```

**Solución:**

```bash
# Verificar que .env tiene el correcto
grep WHATSAPP_APP_SECRET .env

# Actualizar en secret manager si cambió
vault kv put secret/whatsapp app_secret=<NEW_SECRET>

# Restart
docker compose restart api
```

### Incidente: Challenge rechazado (403)

**Síntomas:**
- Al configurar webhook en Meta, falla con "Invalid Verify Token"
- GET `/api/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...` devuelve 403

**Diagnóstico:**

```bash
# 1. Verificar que WHATSAPP_VERIFY_TOKEN está configurado
docker compose exec api env | grep WHATSAPP_VERIFY_TOKEN

# 2. Verificar que coincide con lo que Meta envía
# (Meta debe usar el valor que configuraste en el dashboard)

# 3. Test del simulador
export WEBHOOK_URL=http://localhost:8000/api/v1/whatsapp/webhook
python backend/tools/wa_webhook_simulator.py --challenge
```

**Solución:**

```bash
# En Meta Dashboard → Webhook Settings → Verify Token
# Generar uno nuevo fuerte:
openssl rand -hex 16

# Actualizar en .env / secret manager:
WHATSAPP_VERIFY_TOKEN=<NUEVO_TOKEN>

# Actualizar en Meta Dashboard exactamente con ese valor

# Retry challenge desde Meta Dashboard → "Verify and Save"
```

### Incidente: Webhook no se recibe en local

**Síntomas:**
- Simulador devuelve 200, pero webhook no se procesa
- Redis `wa:inbound` está vacío

**Diagnóstico:**

```bash
# 1. Verificar que Redis está vivo
docker compose exec redis redis-cli ping
# Salida: PONG

# 2. Ver colas pendientes
docker compose exec redis redis-cli KEYS "wa:inbound:*"

# 3. Verificar logs del webhook
docker compose logs api -f --tail=20 | grep whatsapp

# 4. Si hay error de encolado, ver Redis:
docker compose logs redis --tail=20
```

**Solución:**

```bash
# Si Redis está caído:
docker compose restart redis

# Si hay jobs atascados:
docker compose exec redis redis-cli DEL wa:inbound:queue

# Reintentar simulador
python backend/tools/wa_webhook_simulator.py
```

### Incidente: Rate limit de Meta (429 Too Many Requests)

**Síntomas:**
- Mensajes no se envían (wa_send_worker falla)
- Error 429 de Graph API

**Contexto:**

Meta implementa rate limits:
- ~60 mensajes/hora por número
- ~80 conversaciones/24h
- Reintentos automáticos con backoff exponencial

**Procedimiento:**

```bash
# 1. Ver logs de wa_send_worker
docker compose logs wa_send_worker --tail=30 | grep -i "429\|rate"

# 2. Esperar (Meta re-entrega automáticamente)
# 3. Verificar configuración de backoff en .env
WHATSAPP_SEND_MAX_RETRIES=3
WHATSAPP_SEND_BACKOFF_BASE_SECONDS=1

# Si la tasa de envío es muy alta, reducir temporalmente
# o distribuir en ventanas de tiempo
```

### Incidente: Ventana de 24h vencida, plantilla no configurada

**Síntomas:**
- Error al enviar fuera de la ventana: "Message template not configured"
- Mensajes quedan bloqueados en wa:outbound

**Solución:**

```bash
# 1. Crear plantilla en Meta (ver sección "Plantillas HSM")

# 2. Esperar aprobación (~1 hora)

# 3. Actualizar .env
WHATSAPP_TEMPLATE_NAME=generic_template
WHATSAPP_TEMPLATE_LANGUAGE=es

# 4. Reiniciar wa_send_worker
docker compose restart wa_send_worker

# 5. Reintentar envíos bloqueados
# (worker reintentará automáticamente si hay reintentos pendientes)
```

---

## Monitoring y observabilidad

### Métricas clave

**Webhooks recibidos:**

```bash
# Ver webhooks procesados
docker compose logs whatsapp_inbound_worker --tail=50 | grep "whatsapp_webhook"

# Salida esperada:
# [INFO] whatsapp_webhook_event_enqueued event_id=abc123
```

**Mensajes enviados:**

```bash
# Ver estatus de envío
docker compose logs wa_send_worker --tail=50 | grep "whatsapp_send"

# Salida esperada:
# [INFO] whatsapp_send_ok wamid=xyz789
```

**Errores de firma:**

```bash
# Ver rechazos de firma HMAC
docker compose logs api --tail=50 | grep "whatsapp_webhook_signature_rejected"
```

### Alertas recomendadas (si Prometheus/Grafana disponible)

```yaml
# Prometheus alerts
groups:
  - name: whatsapp
    rules:
      - alert: WhatsAppWebhookFailures
        expr: rate(whatsapp_webhook_error_total[5m]) > 0.01
        annotations:
          summary: "WhatsApp webhook failures"

      - alert: WhatsAppSendRate
        expr: rate(whatsapp_send_total[1h]) > 60
        annotations:
          summary: "Acercándose al rate limit de Meta"

      - alert: WhatsAppInboundQueueBacklog
        expr: whatsapp_inbound_queue_length > 100
        annotations:
          summary: "Backlog en cola wa:inbound"
```

---

## Verificación de egress acotado

### ADR-006: Excepción acotada a `graph.facebook.com`

Solo `api` y `wa_send_worker` pueden alcanzar internet, y SOLO a `graph.facebook.com`.

### Auditoría de egress

```bash
# 1. Verificar que check-externos-backend.sh pasa
make check-externos

# Salida esperada:
# ✓ APROBADO: cero referencias a APIs externas de IA
```

### Prueba manual de bloqueo

```bash
# 1. Contenedor IA NO tiene egress
docker exec crm_ia sh -c "timeout 5 wget -T3 -qO- https://graph.facebook.com 2>&1" \
  && echo "✗ FALLO: egress desbloqueado" \
  || echo "✓ EGRESS BLOQUEADO (expected)"

# 2. API SÍ tiene egress (necesario para enviar a Meta)
docker exec crm_api sh -c "timeout 5 curl -s -I https://graph.facebook.com | head -1"
# Salida esperada: HTTP/1.1 ... (cualquier respuesta, mientras no sea timeout)
```

### Captura de tráfico (verificación de red real)

```bash
# Capturar tráfico saliente del contenedor wa_send_worker
docker exec crm_wa_send_worker sh -c "netstat -tuln | grep -E 'ESTABLISHED|LISTEN'" \
  | grep "443\|80"

# Salida esperada: solo conexiones a IPs de Meta (gateways de graph.facebook.com)
# NO debería haber conexiones a OpenAI, Hugging Face, etc.
```

---

## Checklist de deployments

### Antes de desplegar a un nuevo entorno

- [ ] WHATSAPP_VERIFY_TOKEN generado (`openssl rand -hex 16`) y almacenado en secret manager
- [ ] WHATSAPP_APP_SECRET almacenado en secret manager (NO en repo)
- [ ] WHATSAPP_TOKEN almacenado en secret manager con rotación programada
- [ ] WHATSAPP_PHONE_NUMBER_ID configurado (número verificado en Meta)
- [ ] Webhook configurado en Meta Dashboard con URL HTTPS pública
- [ ] Certificado TLS válido (no expirado, cadena completa)
- [ ] Challenge respondido correctamente (`hub.challenge` en texto plano)
- [ ] Plantilla HSM creada y aprobada en Meta (si se enviará fuera de ventana de 24h)
- [ ] WHATSAPP_TEMPLATE_NAME y WHATSAPP_TEMPLATE_LANGUAGE configurados
- [ ] `make check-externos` devuelve "APROBADO"
- [ ] `docker compose config | grep -A2 ia_internal | grep internal` devuelve `true`
- [ ] Simulador local prueba firma HMAC (`python wa_webhook_simulator.py`)

---

**Última actualización:** 2026-09-19 · **SPEC:** SPEC-034 · **ADR:** ADR-006, ADR-007
**Referencias:** RUNBOOK.md, DEPLOYMENT_CHECKLIST.md, ADR-006 (excepción egress), ADR-007 (idempotencia)
