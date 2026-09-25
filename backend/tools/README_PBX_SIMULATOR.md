# Simulador de grabaciones PBX — SPEC-043

Herramienta CLI para emitir eventos ficticios de grabación (audio WAV sintético + metadatos) contra el webhook real del canal de voz, sin egress de internet.

## Instalación de dependencias

```bash
# El simulador necesita httpx (cliente HTTP asíncrono)
pip install httpx
```

## Uso rápido

### Escenario 1: Grabación simple

```bash
python backend/tools/pbx_recording_simulator.py \
    --scenario simple \
    --webhook-url http://localhost:8000 \
    --webhook-secret "changeme-solo-para-desarrollo-local-webhook-secret"
```

**Esperado:**
- Status 202 (ACK del webhook).
- Logs: `[INFO] pbx_webhook_recording_enqueued`.
- STT worker comienza a transcribir (logs: `[INFO] stt_worker: Transcribing`).

### Escenario 2: Reentrega (prueba idempotencia)

```bash
python backend/tools/pbx_recording_simulator.py \
    --scenario redelivery \
    --webhook-url http://localhost:8000 \
    --webhook-secret "changeme-solo-para-desarrollo-local-webhook-secret" \
    --call-id "test-idempotent" \
    --count 2
```

**Esperado:**
- 2 PETs, ambos con 202.
- Postgres: **1 sola** `Call` y **1 sola** `call_transcript` para ese `call_id` (no duplicados).

### Escenario 3: Sin mapeo de tenant

```bash
python backend/tools/pbx_recording_simulator.py \
    --scenario unmapped \
    --webhook-url http://localhost:8000 \
    --webhook-secret "changeme-solo-para-desarrollo-local-webhook-secret" \
    --numero-destino "999-no-existe"
```

**Esperado:**
- Status 202 (ACK de transporte).
- Logs: webhook encoló, pero worker detectó falta de mapeo y descartó (auditado, sin crash).
- Postgres: sin registros para ese `call_id` (correctamente descartado).

## Variables de entorno

```bash
# Opcional: si pasas estas, no necesitas --webhook-secret / --webhook-url

export WEBHOOK_URL="http://localhost:8000"
export WEBHOOK_SECRET="tu-webhook-secret"

# Luego:
python backend/tools/pbx_recording_simulator.py --scenario simple
```

## Referencia completa de argumentos

```bash
python backend/tools/pbx_recording_simulator.py --help
```

| Argumento | Valores | Default | Descripción |
|-----------|---------|---------|-------------|
| `--scenario` | simple, redelivery, unmapped | REQUERIDO | Escenario a ejecutar |
| `--webhook-url` | URL | http://localhost:8000 (env WEBHOOK_URL) | URL base del webhook |
| `--webhook-secret` | string | env WEBHOOK_SECRET | WEBHOOK_SECRET configurado en backend |
| `--call-id` | string | simulator-test | call_id del evento |
| `--numero` | string | +573001234567 | Número de origen (formato E.164) |
| `--numero-destino` | string | 000-test-line | pbx_line destino |
| `--count` | int | 1 | Repeticiones del envío. Aplica a **cualquier** escenario (simple, redelivery, unmapped), no solo redelivery — útil para reentrega/carga. Debe ser >= 1. |

## Ejemplo: Test local end-to-end (sin backend real)

Si no tienes el backend levantado, el simulador reportará error de conexión (esperado, sin traceback):

```bash
python backend/tools/pbx_recording_simulator.py \
    --scenario simple \
    --webhook-url http://localhost:9999 \
    --webhook-secret "changeme-solo-para-desarrollo-local-webhook-secret"  # Puerto inexistente
# [*] Simulador PBX Recording — SPEC-043
#     Escenario: simple
#     Webhook: http://localhost:9999
#
# [*] Enviando grabación simple
#     call_id: simulator-test
#     numero: +573001234567
#     numero_destino: 000-test-line
#     duracion: 3.0s
# [✗] Status: (connection error)
#     ✗ Error de conexión: (connection error) [Errno 111] Connection refused
#
# [*] Simulación completa. Revisar logs:
#     docker compose logs --tail=30 api | grep pbx_webhook
#     docker compose logs --tail=30 stt_worker | grep call_id
```

El script termina con código de salida 1 (fallo) en este caso — útil para scripts/CI que encadenan el simulador. Eso es NORMAL y **seguro** de ejecutar en cualquier lado (el simulador NUNCA descarga datos, solo genera audio sintético y lo firma; el error de conexión se captura explícitamente, nunca se propaga como traceback crudo).

## Verificación de firma HMAC

El simulador calcula la firma HMAC-SHA256 exactamente igual que un PBX real:

```python
signature = "sha256=" + hmac.new(
    WEBHOOK_SECRET.encode("utf-8"),
    AUDIO_BYTES,
    hashlib.sha256
).hexdigest()
```

Puedes verificar manualmente:

```bash
# 1. Generar un WAV (el simulador ya lo hace internamente)
dd if=/dev/zero bs=16000 count=48 of=/tmp/test.wav 2>/dev/null

# 2. Calcular firma
WEBHOOK_SECRET="tu-secret"
SIGNATURE=$(echo -n "$(cat /tmp/test.wav | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" -hex | cut -d' ' -f2)" | sed 's/^/sha256=/')
echo "$SIGNATURE"

# 3. Usar en curl
curl -X POST http://localhost:8000/webhooks/pbx/recordings \
    -F "call_id=test" \
    -F "numero=+573001234567" \
    -F "numero_destino=000-test" \
    -F "direccion=entrante" \
    -F "file=@/tmp/test.wav" \
    -H "X-Webhook-Signature-256: $SIGNATURE"
```

## Carga/stress testing

```bash
# Enviar 10 grabaciones seguidas (para medir RTF bajo carga, ver SPEC-042)
for i in {1..10}; do
    python backend/tools/pbx_recording_simulator.py \
        --scenario simple \
        --webhook-url http://localhost:8000 \
        --webhook-secret "changeme-solo-para-desarrollo-local-webhook-secret" \
        --call-id "stress-test-$i"
    sleep 0.5  # Pequeño delay entre envíos
done

# Ver cómo la cola stt:jobs se llena y vacía
watch -n 2 'docker compose exec redis redis-cli LLEN stt:jobs'
```

## Troubleshooting

### "ERROR: httpx no instalado"

```bash
pip install httpx
```

### "Status: (connection error)"

El webhook no está accesible. Verifica:

```bash
# 1. Backend levantado
docker compose ps | grep api

# 2. API respondiendo
curl http://localhost:8000/healthz

# 3. URL correcta
# Por defecto: http://localhost:8000
# Si cambió: usar --webhook-url http://new-host:port
```

### "Status: 401 Unauthorized"

Firma HMAC incorrecta. Verifica:

```bash
# 1. WEBHOOK_SECRET coincide
grep "^WEBHOOK_SECRET=" .env | cut -d= -f2

# 2. Pasarlo al simulador (o env var)
python backend/tools/pbx_recording_simulator.py --webhook-secret "<tu-secret>"
```

### "Status: 202 OK" pero STT no transcribe

El webhook ACK (correcto), pero el worker no procesó. Causas comunes:

1. **STT worker no está corriendo:**
   ```bash
   docker compose ps | grep stt_worker
   # Si no está "Up", iniciar:
   docker compose up -d stt_worker
   ```

2. **Modelo no está descargado:**
   ```bash
   docker compose exec stt_worker ls /root/.cache/huggingface/models/
   # Si vacío, ver RUNBOOK_VOICE.md § "Preparación de modelos STT"
   ```

3. **Tenant no mapeado (escenario unmapped):**
   ```bash
   docker compose logs recording_ingest_worker | grep "unmapped\|Discarded"
   # Esperado: evento descartado (no es error, es correcto)
   ```

## Seguridad y datos ficticios

- ✅ **Audio:** Totalmente sintético (tonos, no voces reales). SIN PHI, SIN datos personales.
- ✅ **Metadatos:** Números ficticios (+573001234567, etc.). NO datos reales.
- ✅ **Secretos:** Se leen ÚNICAMENTE de env/CLI, NUNCA hardcodeados.
- ✅ **Egress:** SIN salida de internet (solo conecta a localhost/internal).

Es **100% seguro** ejecutar este simulador en desarrollo, staging, o incluso producción (para testing).

## Documentación relacionada

- **RUNBOOK_VOICE.md** — Operación diaria del canal de voz.
- **EXAMPLES_OPENAPI_VOICE.md** — Ejemplos de curl para el webhook.
- **DEPLOYMENT_VOICE_ONPREM.md** — Guía completa de deploy on-prem.
- **SPEC-043.md** — Especificación técnica (documentación, simulador, deploy).

## Autor

QUICKSILVER (DevOps/SPEC-043) · Reutiliza el generador de audio sintético de
SPEC-042 (HAWKEYE) vía el módulo neutral compartido
`backend/app/services/telefonia/synthetic_audio.py` (sin duplicación de
código entre `tools/` y `tests/fixtures_audio/synthetic_call_audio.py`) ·
Correcciones de manejo de errores/`--count` uniforme: CAPTAIN AMERICA
(revisión WOLVERINE, hallazgos bloqueantes de SPEC-043).
