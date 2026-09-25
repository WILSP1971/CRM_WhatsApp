# Ejemplos OpenAPI — Webhook de Grabaciones (SPEC-043)

> Colección de ejemplos ejecutables de requests/responses para el webhook de ingesta de grabaciones PBX.
> Todos los ejemplos usan **placeholders** y datos ficticios. En producción, reemplazar `http://localhost:8000` con `https://app.tudominio.com`.

---

## Tabla de contenidos

1. [Challenge de verificación (GET)](#challenge-de-verificación-get)
2. [Ingesta de grabación con firma válida (POST 202)](#ingesta-de-grabación-con-firma-válida-post-202)
3. [Rechazo por firma inválida (POST 401)](#rechazo-por-firma-inválida-post-401)
4. [Rechazo por dirección inválida (POST 422)](#rechazo-por-dirección-inválida-post-422)
5. [Reentrega (idempotencia)](#reentrega-idempotencia)
6. [Sin mapeo de tenant (descarte auditado)](#sin-mapeo-de-tenant-descarte-auditado)
7. [Referencia: Firma HMAC-SHA256](#referencia-firma-hmac-sha256)

---

## Challenge de verificación (GET)

### Descripción

El PBX puede verificar la disponibilidad del webhook usando un challenge (similar al de Meta para WhatsApp). FastAPI expone automáticamente esta ruta como parte del esquema OpenAPI.

### Endpoint

```
GET /webhooks/pbx/recordings?verify_token=<WEBHOOK_VERIFY_TOKEN>&challenge=<test_string>
```

### Parámetros

| Parámetro | Tipo | Obligatorio | Descripción |
|-----------|------|-------------|-------------|
| `verify_token` | string | Sí | Debe coincidir con `WEBHOOK_VERIFY_TOKEN` configurado (comparación en tiempo constante) |
| `challenge` | string | Sí | Cadena arbitraria que será devuelta en el response si `verify_token` es válido |

### Ejemplo: Challenge válido

```bash
# Generar WEBHOOK_VERIFY_TOKEN (una única vez durante setup)
WEBHOOK_VERIFY_TOKEN=$(openssl rand -hex 16)
echo "Configurar en .env: WEBHOOK_VERIFY_TOKEN=$WEBHOOK_VERIFY_TOKEN"

# Test del challenge
curl -X GET "http://localhost:8000/webhooks/pbx/recordings?verify_token=${WEBHOOK_VERIFY_TOKEN}&challenge=my_test_challenge_123"
```

**Response (200 OK):**

```
my_test_challenge_123
```

### Ejemplo: Challenge inválido (token equivocado)

```bash
curl -X GET "http://localhost:8000/webhooks/pbx/recordings?verify_token=wrong_token&challenge=test"
```

**Response (403 Forbidden):**

```
Forbidden
```

---

## Ingesta de grabación con firma válida (POST 202)

### Descripción

El flujo normal: PBX POST un archivo de audio (WAV/OGG) + metadatos, con firma HMAC-SHA256 válida sobre los bytes del audio. El webhook valida la firma, ACK rápido (202), y encola el audio en Redis.

### Endpoint

```
POST /webhooks/pbx/recordings
Content-Type: multipart/form-data
X-Webhook-Signature-256: sha256=<hmac_hex>
```

### Parámetros (multipart form)

| Campo | Tipo | Obligatorio | Descripción |
|-------|------|-------------|-------------|
| `file` | binary (file) | Sí | Fichero WAV/OGG (audio crudo) |
| `call_id` | string | Sí | Identificador único de la llamada (para dedup) |
| `numero` | string | Sí | Número de origen (p. ej. +573001234567) |
| `numero_destino` | string | Sí | Línea de PBX destino (debe estar en `pbx_lines`) |
| `direccion` | string | Sí | `"entrante"` o `"saliente"` |
| `duracion` | integer | No | Duración en segundos (estimado u obtenido del audio) |

### Header requerido

| Header | Descripción |
|--------|-------------|
| `X-Webhook-Signature-256` | Firma HMAC-SHA256 en formato `sha256=<hex>` (ver sección Referencia) |

### Ejemplo: Ingesta de grabación válida

**Precondiciones:**

1. Tener un fichero WAV válido (p. ej. `test_audio.wav`)
2. Tener `WEBHOOK_SECRET` configurado en el backend (p. ej. en `.env`)
3. Usar el simulador de SPEC-043 O calcular la firma manualmente

**Opción A: Usar el simulador (recomendado)**

```bash
python backend/tools/pbx_recording_simulator.py \
    --scenario simple \
    --webhook-url http://localhost:8000 \
    --webhook-secret "<WEBHOOK_SECRET del backend>" \
    --call-id "call-demo-001" \
    --numero "+573001234567" \
    --numero-destino "000-demo-line"
```

**Opción B: curl manual (con firma calculada)**

```bash
# 1. Generar fichero de audio WAV dummy
dd if=/dev/zero bs=1 count=16384 of=/tmp/test.wav
# O usar uno real, p. ej. sample.wav

# 2. Calcular firma HMAC-SHA256
WEBHOOK_SECRET="changeme-solo-para-desarrollo-local-webhook-secret"
AUDIO_FILE="/tmp/test.wav"
SIGNATURE="sha256=$(openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" "$AUDIO_FILE" | awk '{print $NF}')"
echo "Firma calculada: $SIGNATURE"

# 3. POST con curl
curl -X POST http://localhost:8000/webhooks/pbx/recordings \
    -F "call_id=call-curl-001" \
    -F "numero=+573001234567" \
    -F "numero_destino=000-demo-line" \
    -F "direccion=entrante" \
    -F "duracion=3" \
    -F "file=@${AUDIO_FILE}" \
    -H "X-Webhook-Signature-256: ${SIGNATURE}" \
    -v
```

**Response (202 Accepted):**

```
HTTP/1.1 202 Accepted
Content-Length: 0

```

**Verificación en logs:**

```bash
# Webhook recibió la petición y la encoló
docker compose logs --tail=20 api | grep "pbx_webhook_recording_enqueued"
# [INFO] pbx_webhook_recording_enqueued call_id=call-curl-001 event_id=... audio_length=...

# Recording ingest worker procesó
docker compose logs --tail=20 recording_ingest_worker | grep "call-curl-001"
# [INFO] recording_ingest_worker: Processing call_id=call-curl-001

# STT worker inició transcripción
docker compose logs --tail=20 stt_worker | grep "call-curl-001"
# [INFO] stt_worker: Transcribing call_id=call-curl-001
```

---

## Rechazo por firma inválida (POST 401)

### Descripción

Si el header `X-Webhook-Signature-256` no coincide con el HMAC esperado (calculado sobre los bytes del audio), el webhook rechaza la petición sin encolar.

### Ejemplo: Firma incorrecta

```bash
curl -X POST http://localhost:8000/webhooks/pbx/recordings \
    -F "call_id=call-bad-sig-001" \
    -F "numero=+573001234567" \
    -F "numero_destino=000-demo-line" \
    -F "direccion=entrante" \
    -F "file=@/tmp/test.wav" \
    -H "X-Webhook-Signature-256: sha256=0000000000000000000000000000000000000000000000000000000000000000" \
    -v
```

**Response (401 Unauthorized):**

```
HTTP/1.1 401 Unauthorized
Content-Length: 0

```

**Logs del backend (SIN exponer la firma):**

```
[WARNING] pbx_webhook_signature_rejected has_signature_header=true audio_length=16384 call_id=call-bad-sig-001
```

---

## Rechazo por dirección inválida (POST 422)

### Descripción

Si `direccion` no está en `{"entrante", "saliente"}`, el webhook rechaza con 422 (validación de transporte, sin tocar BD).

### Ejemplo: Dirección inválida

```bash
curl -X POST http://localhost:8000/webhooks/pbx/recordings \
    -F "call_id=call-bad-dir-001" \
    -F "numero=+573001234567" \
    -F "numero_destino=000-demo-line" \
    -F "direccion=inválida" \
    -F "file=@/tmp/test.wav" \
    -H "X-Webhook-Signature-256: sha256=0000..." \
    -v
```

**Response (422 Unprocessable Entity):**

```
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/json

{
  "detail": "Dirección no válida"
}
```

---

## Reentrega (idempotencia)

### Descripción

Si el PBX reenvía una grabación con el **mismo `call_id`**, el webhook ACK nuevamente (202), pero el worker de ingesta debe detectar la reentrega y NO crear duplicados.

### Procedimiento

```bash
# Enviar la misma grabación 2 veces (mismo call_id)
for i in 1 2; do
    echo "[*] Envío $i"
    python backend/tools/pbx_recording_simulator.py \
        --scenario redelivery \
        --webhook-url http://localhost:8000 \
        --webhook-secret "<WEBHOOK_SECRET>" \
        --call-id "call-idempotent-001"
    sleep 2
done
```

**Comportamiento esperado:**

- Ambos POST reciben 202 (ack de transporte).
- En Postgres: **UNA sola** `Call` y **UNA sola** `call_transcript` para `call-idempotent-001`.
- Si hay duplicados, es un BUG en `recording_ingest_worker` (ver SPEC-042, criterio "Test idempotencia").

**Verificación:**

```bash
# Verificar en DB (si tienes acceso a psql)
docker compose exec db psql -U omnicore_app -d omnicore_ai -c \
    "SELECT COUNT(*) FROM call WHERE call_id = 'call-idempotent-001';"
# Esperado: 1 (no 2)

docker compose exec db psql -U omnicore_app -d omnicore_ai -c \
    "SELECT COUNT(*) FROM call_transcript WHERE call_id = 'call-idempotent-001';"
# Esperado: 1 (no 2)
```

---

## Sin mapeo de tenant (descarte auditado)

### Descripción

Si `numero_destino` no existe en `pbx_lines` (no está mapeado a ningún tenant), el webhook ACK 202, pero el worker de ingesta DEBE:

1. Detectar la falta de mapeo.
2. Auditar el descarte (log con call_id, numero_destino).
3. NO encolar en `stt:jobs` (evitar STT innecesario).
4. SIN crash ni error visible.

### Ejemplo

```bash
python backend/tools/pbx_recording_simulator.py \
    --scenario unmapped \
    --webhook-url http://localhost:8000 \
    --webhook-secret "<WEBHOOK_SECRET>" \
    --call-id "call-unmapped-001" \
    --numero-destino "999-no-existe"
```

**Response del webhook (202 — ACK de transporte):**

```
HTTP/1.1 202 Accepted
```

**Verificación en logs:**

```bash
# Webhook OK (recibió y encoló)
docker compose logs --tail=20 api | grep "pbx_webhook_recording_enqueued"
# [INFO] pbx_webhook_recording_enqueued call_id=call-unmapped-001 ...

# Recording ingest worker detectó el descarte (auditado)
docker compose logs --tail=20 recording_ingest_worker | grep -E "call-unmapped-001|unmapped"
# [WARNING] recording_ingest_worker: unmapped_pbx_line numero_destino=999-no-existe call_id=call-unmapped-001
# [INFO] Discarded event: call_id=call-unmapped-001 (no tenant mapping)

# STT worker NO procesó nada (la grabación nunca llegó a stt:jobs)
docker compose logs --tail=100 stt_worker | grep "call-unmapped-001"
# (nada — esperado)
```

---

## Referencia: Firma HMAC-SHA256

### Cálculo de la firma (pseudocódigo)

```python
import hashlib
import hmac

# Inputs
WEBHOOK_SECRET = "tu-webhook-secret-changeme"
AUDIO_BYTES = open("recording.wav", "rb").read()

# Cálculo
signature = "sha256=" + hmac.new(
    WEBHOOK_SECRET.encode("utf-8"),
    AUDIO_BYTES,
    hashlib.sha256
).hexdigest()

# Header
# X-Webhook-Signature-256: sha256=<resultado>
```

### En bash (openssl)

```bash
WEBHOOK_SECRET="tu-webhook-secret-changeme"
AUDIO_FILE="recording.wav"

# Calcular hash
HASH=$(openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" "$AUDIO_FILE" | awk '{print $NF}')
SIGNATURE="sha256=${HASH}"

echo "$SIGNATURE"
# sha256=abc123def456...
```

### Punto crítico: Se firma sobre bytes CRUDOS

La firma se calcula sobre los bytes **EXACTOS** del fichero de audio, no sobre el body multipart completo ni sobre ninguna re-serialización.

```python
# ✓ CORRECTO
signature = hmac.new(webhook_secret.encode(), audio_bytes, hashlib.sha256).hexdigest()

# ✗ INCORRECTO (firmar el JSON serializado, etc.)
signature = hmac.new(webhook_secret.encode(), json.dumps(data).encode(), hashlib.sha256).hexdigest()
```

Esto es idéntico a cómo firma Meta en `X-Hub-Signature-256` (WhatsApp, SPEC-026).

---

## Documentación de Schema OpenAPI

FastAPI genera automáticamente el schema OpenAPI para este endpoint. Acceder a:

```
GET /openapi.json
GET /docs (Swagger UI)
GET /redoc (ReDoc)
```

En `/docs` (Swagger UI local):

```
http://localhost:8000/docs
```

Navegar a `POST /webhooks/pbx/recordings` para ver:

- Parámetros esperados (formulario multipart).
- Header `X-Webhook-Signature-256`.
- Códigos de respuesta (202, 401, 422, 503).
- Esquema Pydantic del modelo (si existe).

El schema OpenAPI es **generado automáticamente** por FastAPI a partir de los docstrings y type hints del código en `app/integrations/pbx/webhook.py` (SPEC-037). No requiere documentación manual adicional.

---

## Checklist de validación (desarrollo)

```bash
# ✓ 1. Simulador con escenario simple (grabación normal)
python backend/tools/pbx_recording_simulator.py --scenario simple

# ✓ 2. Simulador con escenario reentrega (idempotencia)
python backend/tools/pbx_recording_simulator.py --scenario redelivery

# ✓ 3. Simulador con escenario sin mapeo
python backend/tools/pbx_recording_simulator.py --scenario unmapped

# ✓ 4. Verificar que NO hay secretos en logs
docker compose logs api | grep -i "WEBHOOK_SECRET\|X-Webhook-Signature"
# Esperado: nada

# ✓ 5. Acceder a OpenAPI
curl http://localhost:8000/openapi.json | jq .paths['/webhooks/pbx/recordings']

# ✓ 6. Verificar que audio está cifrado en reposo
docker volume inspect crm_whatsapp_audio_store | jq .[0].Mountpoint
# Los ficheros dentro debería ser ilegibles (cifrados)
```

---

**Fin de ejemplos OpenAPI de voz. Volver a RUNBOOK_VOICE.md para procedimientos operativos.**
