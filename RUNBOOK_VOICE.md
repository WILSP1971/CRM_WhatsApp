# Runbook de voz — OmniCore AI (Entregable #4, SPEC-043)

> Guía operativa del canal de voz: integración PBX, descarga de modelos STT, política de retención, rotación de secretos y cifrado del almacén.
> Clasificación: SENSIBLE (`.no-externo`). Todos los procedimientos respetan C2 (borrado lógico) y C3 (secretos en env, placeholders en ejemplos).

---

## Tabla de contenidos

1. [Visión general del arquitectura de voz](#visión-general-de-la-arquitectura-de-voz)
2. [Integración PBX (on-prem o externo)](#integración-pbx-on-prem-o-externo)
3. [Preparación de modelos STT locales](#preparación-de-modelos-stt-locales)
4. [Política de retención y anonimización de audio](#política-de-retención-y-anonimización-de-audio)
5. [Rotación de secretos](#rotación-de-secretos)
6. [Cifrado del almacén de audio](#cifrado-del-almacén-de-audio)
7. [Escalado de réplicas `stt_worker`](#escalado-de-réplicas-stt_worker)
8. [Troubleshooting del canal de voz](#troubleshooting-del-canal-de-voz)

---

## Visión general de la arquitectura de voz

```
┌──────────────────────────────────────────────────────────────────┐
│  PBX On-Prem (Asterisk/FreeSWITCH)     o    PBX Externo (Cloud)  │
│  ↓ (sin descarga, PUSH de grabaciones)   ↓ (solo si habilitado)  │
│  POST /webhooks/pbx/recordings (firma HMAC-SHA256)               │
│                   ↓                                                │
├────────────────────────────────────────────────────────────────┤
│  Caddy (reverse proxy TLS, SPEC-035)                            │
│  Expone SOLO el path /webhooks/pbx/recordings                  │
│  Autentica con HTTPS, termina TLS, reenvía a API interna       │
├────────────────────────────────────────────────────────────────┤
│  API FastAPI (app:8000)                                         │
│  ↓                                                               │
│  POST /webhooks/pbx/recordings (webhook.py, SPEC-037)          │
│    ├─ Valida firma HMAC-SHA256 con WEBHOOK_SECRET              │
│    ├─ ACK 202 (rápido)                                         │
│    └─ Encola en Redis: pbx:recordings:inbound                  │
├────────────────────────────────────────────────────────────────┤
│  recording_ingest_worker (async, parte de app)                 │
│    ├─ Desencola de pbx:recordings:inbound                      │
│    ├─ Resuelve numero_destino → tenant_id                      │
│    ├─ Almacena audio cifrado (AES-256-GCM)                     │
│    ├─ Crea registro de Call en Postgres                        │
│    └─ Encola en stt:jobs                                       │
├────────────────────────────────────────────────────────────────┤
│  stt_worker (réplicas escalables, SPEC-035)                    │
│    ├─ Desencola de stt:jobs                                    │
│    ├─ Carga modelo faster-whisper (large-v3 o medium)         │
│    ├─ Transcribe (Spanish, es-CO)                              │
│    ├─ Segmentación + timestamps + diarización (opcional)      │
│    └─ Escribe Call_Transcript en Postgres                      │
├────────────────────────────────────────────────────────────────┤
│  retention_job (cron, SPEC-041)                                │
│    ├─ Ejecuta: python -m app.workers.call_retention_job       │
│    ├─ Política: AUDIO_RETENTION_DAYS + CALL_TRANSCRIPT_RETENTION_DAYS
│    ├─ Purga o anonimiza según AUDIO_RETENTION_ACTION           │
│    └─ Auditado en logs (creado_por/fecha)                      │
├────────────────────────────────────────────────────────────────┤
│  Red interna (ia_internal, internal: true) — EGRESS BLOQUEADO   │
│  STT + IA + workers: SIN salida a internet (verificable con     │
│  `make test-egress`, SPEC-035 ADR-009/ADR-010)                 │
└──────────────────────────────────────────────────────────────────┘
```

**Flujo de seguridad:**

- **C3 (secretos):** `WEBHOOK_SECRET`, `WEBHOOK_VERIFY_TOKEN`, `AUDIO_ENCRYPTION_KEY` viven en `env` del servidor, NUNCA en código/logs. Generar con `openssl rand -hex 32` (audio) o `openssl rand -hex 16` (tokens).
- **C2 (datos personales):** Audio se cifra en reposo (AES-256-GCM), nunca DELETE físico (borrado lógico). Retención configurable (días), anonimización bajo demanda.
- **Integridad de transporte:** HMAC-SHA256 en `X-Webhook-Signature-256` sobre bytes crudos del audio (igual que WhatsApp `X-Hub-Signature-256`). Firma inválida → 401, sin encolar.

---

## Integración PBX (on-prem o externo)

### Caso A: PBX on-prem (Asterisk/FreeSWITCH) — PREFERIDO

**Ventajas:**
- Cero egress nuevo desde la aplicación (archivos ya están on-prem).
- Red `ia_internal` no necesita excepciones.
- Infraestructura controlada.

**Procedimiento de integración:**

1. **Configurar PBX para PUSH de grabaciones**

   En el PBX (Asterisk conf o FreeSWITCH XML), establecer un script de post-grabación:

   ```bash
   # Ejemplo: Asterisk
   exten => _X.,n,System(curl -X POST \
       -H "X-Webhook-Signature-256: $(openssl dgst -sha256 -hmac '${WEBHOOK_SECRET}' ${RECORDING_FILE})" \
       -F "call_id=${CDR(uniqueid)}" \
       -F "numero=${CDR(src)}" \
       -F "numero_destino=${CDR(dst)}" \
       -F "direccion=entrante" \
       -F "duracion=${RECORDING_LEN}" \
       -F "file=@${RECORDING_FILE}" \
       https://omnicore.tudominio.com/webhooks/pbx/recordings)
   ```

   > **NOTA:** El hash HMAC debe calcularse sobre bytes CRUDOS del `.wav`. Usar herramientas offline (p. ej. `openssl dgst`) o el simulador de SPEC-043 para validar antes en local.

2. **Configurar variables de `.env`**

   ```bash
   # En .env del servidor on-prem
   PBX_EXTERNAL_ENABLED=false  # PBX on-prem: no activar egress
   WEBHOOK_SECRET=<generar con: openssl rand -base64 32>
   WEBHOOK_VERIFY_TOKEN=<generar con: openssl rand -hex 16>
   ```

3. **Validar conectividad**

   Desde el PBX:

   ```bash
   # Test de connectivity (GET challenge)
   curl -X GET https://omnicore.tudominio.com/webhooks/pbx/recordings \
       ?verify_token=<WEBHOOK_VERIFY_TOKEN>&challenge=test123
   # Respuesta esperada: texto plano "test123"

   # Test de POST (sin archivo real, simulado para esta prueba)
   # Ver sección "Simulador de grabaciones" para un test end-to-end
   ```

### Caso B: PBX Externo (cloud, proveedora con descarga)

**Riesgo:** egress nuevo desde `recording_fetch_worker`. **Mitigación:** allowlist por ruta y auditoría en CI (`check-externos-backend.sh`).

**Procedimiento:**

1. **Confirmar con el Lead que es necesario**

   PBX externo es contingencia (SUP-42 "sin PBX real en piloto"). Recopilar:
   - Host y puerto de acceso (p. ej. `pbx-cloud.provider.com:443`)
   - Token/credencial de API (genera uno fuerte en el portal de la proveedora)

2. **Configurar variables**

   ```bash
   # En .env
   PBX_EXTERNAL_ENABLED=true
   PBX_EXTERNAL_HOST=pbx-cloud.provider.com
   PBX_EXTERNAL_PORT=443
   PBX_EXTERNAL_AUTH_TOKEN=<Bearer token o API key del proveedor>
   WEBHOOK_SECRET=<generar>
   WEBHOOK_VERIFY_TOKEN=<generar>
   ```

3. **Validar egress**

   ```bash
   # Dentro del contenedor api/workers (red `app`)
   docker compose exec api python -c \
       "import socket; socket.create_connection(('pbx-cloud.provider.com', 443), timeout=5)"
   # Esperado: conexión exitosa

   # Verificar que NO está en ia_internal
   docker compose exec ia curl -I https://pbx-cloud.provider.com 2>&1 | grep -i "connection refused\|not found"
   # Esperado: connection refused (ia_internal está bloqueado)
   ```

4. **Auditar el código**

   ```bash
   # Verificar que SOLO app/services/telefonia/ puede descargar grabaciones
   grep -r "PBX_EXTERNAL_HOST" backend/app --include="*.py" | grep -v test
   # Esperado: solo en recording_fetch_worker.py, pbx_client.py
   grep -r "requests\|urllib\|httpx" backend/app/workers --include="*.py" | grep -v test
   # Esperado: nada en stt_worker.py (solo consume cola, no hace egress)
   ```

---

## Preparación de modelos STT locales

### Modelos soportados

| Modelo | Dispositivo | Tamaño | RTF (es-CO) | Casos de uso |
|--------|-------------|--------|-------------|--------------|
| `large-v3` | GPU ≥16GB | 3.1 GB | ≤ 1.0 (RTF) | Producción con GPU |
| `medium` | GPU ≥6GB | 1.5 GB | ~2–3 x RTF | Alternativa menor precisión |
| `whisper.cpp` (Q4) | CPU | 400 MB | ~4–10 x RTF | Fallback CPU pure |

### Descarga de pesos (antes del despliegue)

**Paso 1: Descargar en local (máquina de build o servidor on-prem)**

```bash
# Opción A: Con pip de faster-whisper
pip install faster-whisper
python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3')"
# Descarga ~3.1 GB a ~/.cache/huggingface/models

# Opción B: Manual (si faster-whisper no está disponible)
# Descargar desde Hugging Face:
# https://huggingface.co/openai/whisper-large-v3
# y copiarlo manualmente

# Opción C: Usar docker-compose con volumen montado
docker compose run --rm stt_worker \
    python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3')"
```

**Paso 2: Montar el volumen en docker-compose.yml**

```yaml
# En docker-compose.yml (Entregable #2, SPEC-023)
services:
  stt_worker:
    image: omnicore-stt-worker:latest
    volumes:
      - ./models/whisper:/root/.cache/huggingface/models:ro
    environment:
      STT_MODEL_DIR: /root/.cache/huggingface/models
      STT_MODEL: large-v3
      STT_DEVICE: cuda  # o cpu
```

**Paso 3: Verificar que están montados**

```bash
docker compose exec stt_worker ls -lh /root/.cache/huggingface/models
# Esperado: directorios/ficheros de modelo local

# Verificar que NO descarga en runtime
docker compose logs -f stt_worker | grep -i "downloading\|hugging" 
# Esperado: nada (no debería descargar en runtime)
```

### Fallback a CPU (degradación)

Si GPU no está disponible o OOM en GPU:

```bash
# En .env
STT_DEVICE=cpu
STT_MODEL=medium  # o whisper.cpp Q4
STT_FALLBACK_MODEL=medium
STT_FALLBACK_DEVICE=cpu
STT_COMPUTE_TYPE=int8  # más eficiente en CPU que float16
```

Documentar en logs/runbook:

```bash
docker compose logs stt_worker | grep "Using device\|RTF\|Model loaded"
# Esperado: `Using device: cpu` y RTF documentado (4–10x vs GPU)
```

---

## Política de retención y anonimización de audio

### Variables de configuración

```bash
# En .env

# AUDIO: tiempo de retención (días) antes de purga
AUDIO_RETENTION_DAYS=30

# TRANSCRIPCIÓN: tiempo de retención (días) antes de anonimización
CALL_TRANSCRIPT_RETENTION_DAYS=90

# AUDIO: acción al expirar retención
# "purge" (default): borra blob cifrado físicamente
# "anonymize": alias (mismo efecto que purge para binarios)
AUDIO_RETENTION_ACTION=purge

# TRANSCRIPCIÓN: acción al expirar retención
# "anonymize" (default): sobrescribe texto, conserva fila para auditoría
# "purge": además aplica borrado lógico (is_active=false)
CALL_TRANSCRIPT_RETENTION_ACTION=anonymize

# Activación del job (CUIDADO: cambio sensible C6)
ENABLE_CALL_RETENTION_PURGE=false  # dry-run por defecto
```

### Ejecución manual (desarrollo/testing)

```bash
# Modo dry-run (solo reporta, no modifica)
docker compose exec api python -m app.workers.call_retention_job

# Salida esperada:
# [INFO] call_retention_job: mode=dry-run
# [INFO] Audio candidates for purge (30 days): 5 files
# [INFO] Transcript candidates for anonymize (90 days): 3 records

# Con ENABLE_CALL_RETENTION_PURGE=true (PRODUCCIÓN)
# ⚠️ CUIDADO: CAMBIO SENSIBLE (C6) — requiere aprobación Lead + Telegram
docker compose exec api python -m app.workers.call_retention_job
# [INFO] call_retention_job: mode=enabled (REAL)
# [INFO] Purged 5 audio files (30 days)
# [INFO] Anonymized 3 transcripts (90 days)
```

### Programación con cron (producción)

```bash
# En el servidor on-prem, cron del usuario Docker/app

# Ejecutar job de retención DIARIAMENTE a las 02:00 UTC
0 2 * * * cd /ruta/a/CRM_WhatsApp && ENABLE_CALL_RETENTION_PURGE=true \
    docker compose exec -T api python -m app.workers.call_retention_job >> /var/log/omnicore/retention.log 2>&1

# Notas:
# - `-T` (sin tty) para uso en cron
# - Redirigir logs a un fichero específico (no a syslog directo por ahora)
# - Considerar alertas si el job falla (monitoreo SPEC-042)
```

### Auditoría de retención

```bash
# Verificar cuándo se ejecutó el último job
docker compose logs retention_job | tail -20

# Consultar en Postgres cuáles audio/transcritos se eliminaron
# (si tu setup tiene acceso a psql)
psql -U omnicore_app -h localhost omnicore_ai
> SELECT * FROM audit_log WHERE action = 'retention_purge' 
    ORDER BY created_at DESC LIMIT 10;
```

---

## Rotación de secretos

### Secretos que rotan (con impacto)

1. **`WEBHOOK_SECRET`** — Firma HMAC de webhooks PBX (X-Webhook-Signature-256)
2. **`WEBHOOK_VERIFY_TOKEN`** — Challenge de verificación del webhook
3. **`AUDIO_ENCRYPTION_KEY`** — Cifrado de audio en reposo

### Procedimiento sin downtime (WEBHOOK_SECRET / WEBHOOK_VERIFY_TOKEN)

Estos secretos SÍ pueden rotar sin downtime porque el webhook no necesita sincronización de estado.

**Paso 1: Generar nuevo secreto**

```bash
NEW_SECRET=$(openssl rand -base64 32)
echo "Nuevo WEBHOOK_SECRET: $NEW_SECRET"
```

**Paso 2: Configurar en secret manager (Vault, AWS Secrets, etc.)**

No reemplazcemos en `.env` directamente (ese fichero está versionado). En producción:

```bash
# Ejemplo con AWS Secrets Manager
aws secretsmanager update-secret \
    --secret-id omnicore/webhook-secret \
    --secret-string "$NEW_SECRET"
```

**Paso 3: Actualizar contenedor (zero-downtime)**

```bash
# El API relee env en cada request (no caché estático)
# Solo hay que recargar la configuración
docker compose exec api kill -HUP $(pgrep -f uvicorn)
# o
docker compose exec -it api /bin/bash -c "pkill -f 'uvicorn' && exit 0" &
# Esperar 5-10 segundos para que Kubernetes/supervisor reinicie

# Verificar que la API respondió post-rotación
curl -X GET http://localhost:8000/healthz
```

**Paso 4: Notificar al PBX (si es on-prem, comunícate con el operador)**

```bash
# Envío de correo al equipo de PBX:
# "Secreto rotado. Usar nuevo WEBHOOK_SECRET en requests HMAC a partir de [fecha/hora]."
# Mantener compatible con ambos secretos durante 24h (opcional, si el PBX soporta reintentos).
```

### Procedimiento de rotación de `AUDIO_ENCRYPTION_KEY` (MÁS DELICADO)

**Riesgo:** el audio EXISTENTE está cifrado con la clave vieja. Cambiar la clave → audio viejo irrecuperable (es la naturaleza del cifrado).

**Opción A: Rotar SIN preservar audio anterior (más simple, recomendado)**

1. Fijar política de retención más agresiva (AUDIO_RETENTION_DAYS más bajo).
2. Ejecutar el job de retención para purgar audio viejo (`ENABLE_CALL_RETENTION_PURGE=true`).
3. Esperar N días (ej. 30 días) a que TODO audio se purgue naturalmente.
4. ENTONCES cambiar `AUDIO_ENCRYPTION_KEY`.

**Opción B: Re-cifrar audio viejo (costoso, solo si es CRÍTICO preservarlo)**

1. Crear herramienta de migración: leer audio con clave vieja, re-cifrar con clave nueva.
2. Ejecutar durante ventana de mantenimiento (p. ej. 02:00 a 06:00 UTC).
3. Validar integridad de re-cifrado (checksum).
4. Cambiar `AUDIO_ENCRYPTION_KEY`.

**NUNCA ambas claves a la vez en `.env`** (código explícitamente rechaza múltiples claves activas, por simplicidad y seguridad). Si necesitas "overlap" de 24h, usa un secret manager con versiones (Vault puede).

---

## Cifrado del almacén de audio

### Verificación de que está activo

```bash
# 1. Verificar que AUDIO_ENCRYPTION_KEY está seteado (no vacío)
docker compose exec api python -c \
    "from app.core.config import get_settings; s = get_settings(); print('AUDIO_ENCRYPTION_KEY set:', bool(s.audio_encryption_key))"
# Esperado: True

# 2. Verificar que el volumen está cifrado (si usas Linux native)
# Listar volúmenes Docker
docker volume ls | grep audio_store
# Inspeccionarlo
docker volume inspect crm_whatsapp_audio_store
# En "Mountpoint" debería estar en una partición cifrada (LUKS/dm-crypt)

# 3. Test end-to-end: almacenar audio, leer blob crudo
docker compose exec api python -c "
from app.core.audio_store import AudioStore
store = AudioStore()
test_audio = b'\\x00' * 1024  # 1 KB dummy
result = store.store_audio(
    call_id='test-cipher',
    audio_bytes=test_audio,
    tenant_id='test-tenant'
)
print(f'Stored: {result}')
# Lee el blob crudo desde el volumen (debería estar ilegible/cifrado)
"
```

### Si se pierde la clave (disaster recovery)

**Situación:** Servidor crashea, `.env` se borra, nadie tiene copia de `AUDIO_ENCRYPTION_KEY`.

**Consecuencia:** Audio IRRECUPERABLE. Es la naturaleza del cifrado (no es un "oversight", es por diseño C2/C3).

**Prevención (CRÍTICA):**

1. **Guardar `AUDIO_ENCRYPTION_KEY` en secret manager** (Vault, AWS Secrets, GCP Secrets):
   ```bash
   # Ejemplo: HashiCorp Vault
   vault kv put secret/omnicore/audio_encryption_key value="$(cat .env | grep AUDIO_ENCRYPTION_KEY)"
   ```

2. **Backup regular de secret manager** (Vault snapshots, AWS backup policy).

3. **Procedimiento de recuperación documentado:**
   ```bash
   # Si se pierde .env, recuperar de secret manager
   vault kv get secret/omnicore/audio_encryption_key
   # y reescribir en .env (NUNCA en logs/código)
   ```

4. **Política de retención configurable** (`AUDIO_RETENTION_DAYS=30` por defecto) permite que audio viejo se purgue naturalmente en 30 días. Así, si la clave se pierde hoy, en 30 días no hay audio "irrecuperable" acumulado.

---

## Escalado de réplicas `stt_worker`

### Arquitectura de colas

```
Redis cola: stt:jobs (FIFO)
    ↓ (multiple consumers)
┌─ stt_worker #1 (transcribe audio 1)
├─ stt_worker #2 (transcribe audio 2)
├─ stt_worker #3 (transcribe audio 3)
└─ stt_worker #N (transcribe audio N)
    ↓
Postgres: call_transcript (escribe con RLS)
```

Cada worker es **independiente** y puede escalarse con `docker compose up --scale stt_worker=N`.

### Procedimiento de escalado

**En local (desarrollo):**

```bash
# Subir a 3 réplicas
docker compose up -d --scale stt_worker=3

# Verificar que levantaron
docker compose ps | grep stt_worker
# Esperado: 3 contenedores stt_worker_1, stt_worker_2, stt_worker_3

# Ver logs de todos
docker compose logs -f stt_worker | tail -50

# Test: enviar grabaciones y ver que se distribuyen
for i in {1..5}; do
    curl -X POST http://localhost:8000/webhooks/pbx/recordings \
        -F "call_id=scale-test-$i" \
        -F "numero=+573001234567" \
        -F "numero_destino=000-test" \
        -F "direccion=entrante" \
        -F "duracion=3" \
        -F "file=@/tmp/test_audio.wav" \
        -H "X-Webhook-Signature-256: $(tools/sign_webhook.py /tmp/test_audio.wav)"
done

# Monitorear cola
docker compose exec redis redis-cli LLEN stt:jobs
# Esperado: inicialmente 5, luego → 0 (workers las procesan)
```

**En producción (Kubernetes o máquina single-node):**

```bash
# Si usas docker-compose en VM único
docker compose up -d --scale stt_worker=5

# Si usas Kubernetes (futuro)
kubectl scale deployment stt-worker --replicas=5

# Verificar RTF bajo carga
# Ver SPEC-042 / loadtest/README.md para instrucciones
docker compose exec api python -m prometheus_client.exposition
curl http://localhost:8001/metrics | grep stt_rtf
```

### Monitoreo de cola

```bash
# Tamaño actual de stt:jobs
docker compose exec redis redis-cli LLEN stt:jobs

# Publicar métrica (SPEC-042 observabilidad)
# El stt_worker escribe en Prometheus la métrica stt_queue_depth
curl http://localhost:8001/metrics | grep stt_queue_depth

# Si la cola crece (backlog > N), considerar:
# 1. Escalado a más réplicas
# 2. Cambiar a modelo más rápido (medium en lugar de large-v3)
# 3. Cambiar STT_DEVICE a GPU si estaba en CPU
```

---

## Troubleshooting del canal de voz

### Síntoma: Webhook rechaza peticiones (401 Unauthorized)

**Causas comunes:**

1. **Firma HMAC inválida:**
   ```bash
   # Validar que el PBX está usando WEBHOOK_SECRET CORRECTO
   # Verificar: en backend logs
   docker compose logs api | grep "pbx_webhook_signature_rejected"
   
   # Usar simulador (SPEC-043) para test con firma válida
   python tools/pbx_recording_simulator.py --call-id test-001 --numero +573001234567
   ```

2. **WEBHOOK_SECRET no seteado o débil:**
   ```bash
   # Verificar en .env
   grep WEBHOOK_SECRET .env | grep -v "^#"
   # Debería haber un valor ≥32 caracteres
   
   # Si está vacío o débil:
   WEBHOOK_SECRET=$(openssl rand -base64 32)
   echo "WEBHOOK_SECRET=$WEBHOOK_SECRET" >> .env
   # Restart
   docker compose restart api
   ```

3. **Header de firma mal formado:**
   ```bash
   # El header debe ser: X-Webhook-Signature-256: sha256=<hex>
   # Validar en PBX o con curl -v
   curl -v -X POST http://localhost:8000/webhooks/pbx/recordings \
       -F "call_id=test" \
       -F "numero=+573001234567" \
       -F "numero_destino=000-test" \
       -F "direccion=entrante" \
       -F "file=@test.wav" \
       -H "X-Webhook-Signature-256: sha256=<hex correcto>"
   ```

### Síntoma: Audio no se transcribe (queda en cola stt:jobs)

**Posibles causas:**

1. **STT worker no arrancó o crasheó:**
   ```bash
   docker compose ps | grep stt_worker
   # Si no está "Up", revisar logs
   docker compose logs stt_worker | tail -50
   
   # Errores comunes:
   # - "CUDA driver not found" → STT_DEVICE=cpu fallback
   # - "OOM" → memoria insuficiente, cambiar a modelo medium
   # - "Model not found" → STT_MODEL_DIR no está montado
   ```

2. **Modelo no está descargado:**
   ```bash
   docker compose exec stt_worker ls -lh /root/.cache/huggingface/models
   # Si vacío: descargar manualmente (ver sección "Preparación de modelos")
   ```

3. **Tenant no mapeado (sin pbx_line):**
   ```bash
   # Si numero_destino no existe en pbx_lines para el tenant
   docker compose logs recording_ingest_worker | grep "unmapped_pbx_line"
   # Esperado: auditado y descartado (no es un error del STT, es correcto)
   ```

### Síntoma: RTF muy alto (>10 en GPU, >30 en CPU)

**Análisis:**

```bash
# 1. Verificar dispositivo de ejecución
docker compose logs stt_worker | grep "Using device\|CUDA"

# 2. Verificar si hay OOM (Out of Memory)
docker compose stats stt_worker  # Ver memoria usada
# Si >90% de la RAM disponible, cambiar:
STT_MODEL=medium  # en lugar de large-v3
STT_DEVICE=cpu  # en lugar de cuda

# 3. Verificar carga de CPU/GPU
nvidia-smi  # Si tienes GPU
# Si GPU está en 100%, considerar Scale out (más réplicas)

# 4. Verificar tamaño de audio
# Audio muy largo (>10 min) → RTF esperado más alto
```

### Síntoma: Error al almacenar audio cifrado

**Síntomas en logs:**

```
[ERROR] recording_ingest_worker: Failed to store audio
  message: "AES cipher failed"
  call_id: "..."
```

**Checks:**

```bash
# 1. Verificar que AUDIO_ENCRYPTION_KEY está seteado
grep AUDIO_ENCRYPTION_KEY .env | grep -v "^#"

# 2. Verificar que el volumen audio_store existe y tiene permiso
docker volume ls | grep audio_store
docker run --rm -v crm_whatsapp_audio_store:/mnt alpine ls -la /mnt/
# Debería tener permisos rw

# 3. Test cifrado básico
docker compose exec api python -c "
from app.core.audio_store import AudioStore
store = AudioStore()
try:
    result = store.store_audio(
        call_id='cipher-test',
        audio_bytes=b'test data',
        tenant_id='test-tenant'
    )
    print('✓ Cifrado OK:', result)
except Exception as e:
    print('✗ Error:', e)
"
```

### Síntoma: Retención de audio no funciona

**Verificar que el job se ejecuta:**

```bash
# Modo dry-run (siempre seguro)
docker compose exec api python -m app.workers.call_retention_job

# Si no reporta nada:
# 1. Verificar que hay datos viejos (>AUDIO_RETENTION_DAYS)
# 2. Verificar logs
docker compose logs api | grep retention

# Si quieres ejecutar de verdad (¡CUIDADO!):
docker compose exec api \
    sh -c "ENABLE_CALL_RETENTION_PURGE=true python -m app.workers.call_retention_job"
```

---

## Checklist de operación diaria

```bash
# ✓ Verificar salud del webhook
curl -X GET http://localhost:8000/healthz | jq .

# ✓ Verificar que stt_worker está up
docker compose ps | grep stt_worker

# ✓ Ver tamaño de cola (cero = healthy)
docker compose exec redis redis-cli LLEN stt:jobs

# ✓ Revisar logs de errores
docker compose logs --tail=100 stt_worker | grep ERROR

# ✓ Verificar espacio en disco (audio_store)
docker volume inspect crm_whatsapp_audio_store | jq .[0].Mountpoint
# y luego: du -sh <mountpoint>

# ✓ Si PHI_MODE_ENABLED=true, verificar anonimización
docker compose exec api python -m app.workers.call_retention_job
```

---

## Medición de WER (Word Error Rate) — Pendiente

### Estado actual

**WER no se mide automáticamente** en este entorno. El criterio de SPEC-042 (CE-41) es documentar el WER, no automatizar su cálculo.

### Qué se necesitaría para medir WER real

La medición de WER requiere:

1. **Corpus de habla es-CO con referencia humana:**
   - Mínimo 100–500 audio samples (llamadas/conversaciones)
   - Cada audio CON transcripción de referencia humana verificada
   - Consentimiento explícito de los hablantes (GDPR/HABEAS DATA, **nunca PHI real**)

2. **Opciones:**
   - **Corpus público con licencia compatible:** buscar en Hugging Face / OpenSLR.org (datasets de habla es-CO etiquetados)
   - **Corpus sintetizado (menos realista):** generar con TTS para española; no refleja ruido real/acentos
   - **Corpus personalizado:** recopilar y anotar internamente (costo operativo alto)

3. **Cálculo de WER:**
   ```bash
   pip install jiwer
   python -c "
   from jiwer import wer
   reference = 'el cliente solicita cambio de plan'  # transcripción humana de referencia
   hypothesis = model.transcribe('audio.wav')        # salida del faster-whisper
   error_rate = wer(reference, hypothesis)
   print(f'WER: {error_rate:.2%}')
   "
   ```

### Decisión pendiente del Lead

Este runbook espera decisión del Lead sobre:

- ¿Usar un corpus público (p. ej. CommonVoice es-CO)?
- ¿Recopilar corpus propio (costo/timeline)?
- ¿Aceptar WER documentado sin automatización (cambiar SPEC-042 CE-41)?

**Por ahora:** WER se valida manualmente en pre-produción contra muestras representativas, no en CI.

---

## Verificación en CI (on-prem con GPU)

### Flujo de CI estándar (backend-ci.yml)

Cubre tests unitarios + integración contra Postgres/Redis reales, SIN GPU:

```bash
# En runners de GitHub Actions (ubuntu-latest, sin GPU)
pytest backend/tests/test_stt_e2e_synthetic_audio.py -v
# → Valida que la lógica STT (parseo de audios ficticios) es correcta
```

**Limitación:** sin GPU, no se mide el RTF real ni se verifica Prometheus.

### Verificación on-prem adicional (workflow_dispatch manual)

Nuevo workflow `.github/workflows/voice-onprem-verification.yml` para:

1. **RTF bajo carga (SPEC-042, RNF-42):** escenario Locust `PbxRecordingWebhookUser` genera carga real
2. **Métricas Prometheus:** leer `stt_rtf{device="cuda"}` p95
3. **Egress vacío (SENSIBLE, ADR-009/ADR-010):** verificar que `stt_worker` no tiene acceso a internet

**Triggering:**

```bash
# Opción 1: desde CLI GitHub
gh workflow run voice-onprem-verification.yml \
    -f stt_model=large-v3 \
    -f test_duration_seconds=300

# Opción 2: UI de GitHub Actions — manual dispatch
# (solo si runner self-hosted con labels [gpu, on-prem] está registrado)
```

**Precondiciones del runner:**

- Labels: `self-hosted`, `gpu`, `on-prem`
- NVIDIA GPU con drivers (nvidia-smi disponible)
- Pesos de faster-whisper pre-descargados en `~/.cache/huggingface/models`
- docker-compose + python 3.11

**No dispara automáticamente** en push/PR (es workflow_dispatch, no hay trigger en push) — evita bloquear CI estándar ni fallar si el runner no existe.

---

**Fin del runbook de voz. Para más, ver OPERACION.md y RUNBOOK.md (Entregable #2).**
