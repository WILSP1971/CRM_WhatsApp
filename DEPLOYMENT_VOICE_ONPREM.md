# Deploy on-prem del canal de voz — OmniCore AI (Entregable #4, SPEC-043)

> Guía de pasos para desplegar el canal de voz 100% on-prem en un servidor dedicado.
> CUIDADO: Este es un **procedimiento documentado, no ejecutado automáticamente**. Requiere aprobación explícita del Lead (CHECKPOINT C6) antes de ejecutarse en infraestructura real.

---

## Tabla de contenidos

1. [Requisitos previos y validación](#requisitos-previos-y-validación)
2. [Generación de secretos (C3)](#generación-de-secretos-c3)
3. [Preparación de modelos STT](#preparación-de-modelos-stt)
4. [Configuración de infraestructura](#configuración-de-infraestructura)
5. [Deploy del stack completo](#deploy-del-stack-completo)
6. [Configuración de PBX on-prem](#configuración-de-pbx-on-prem)
7. [Validación post-deploy](#validación-post-deploy)
8. [Rollback (si algo falla)](#rollback-si-algo-falla)
9. [Monitoreo 24x7](#monitoreo-24x7)

---

## Requisitos previos y validación

### Hardware mínimo (voz a 16 kHz, es-CO)

```
CPU:        4+ núcleos (8+ recomendado para STT + IA concurrentes)
RAM:        16 GB mínimo; 32+ GB si tienes GPU
Almacenamiento: 200+ GB (BD, Redis, modelos Whisper, audio cifrado)
GPU:        NVIDIA CUDA 11.8+ (RECOMENDADO para RTF ≤ 1.0)
             SIN GPU: RTF ~4–10x, degradación documentada en SPEC-042
Red:        1 Gbps mínimo (PBX → webhook synchronous)
```

### Validaciones previas (checklist)

```bash
# 1. Verificar que el servidor ESTA AISLADO (no tiene acceso a internet, o firewall lo bloquea)
curl https://www.google.com 2>&1 | grep -i "refused\|timeout\|network"
# Esperado: conexión rechazada/timeout

# 2. Verificar Docker + Docker Compose
docker --version  # 24.0+
docker compose version  # 2.20+

# 3. Verificar almacenamiento disponible
df -h /  # Al menos 200 GB libres en /

# 4. Si tienes GPU NVIDIA
nvidia-smi  # Debería listar la GPU
# y en el mismo output: CUDA version (≥11.8)

# 5. Verificar que los puertos necesarios están libres
# (no es posible verificar todos sin intentar bindear, pero:)
sudo ss -tlnp | grep -E "8000|8443|5432|6379"
# Esperado: nada (puertos libres)
```

---

## Generación de secretos (C3)

**CRÍTICO:** Estos secretos son para ESCRIBIR en `.env` del servidor. NUNCA commitearlos al repo. NUNCA exponer en logs.

### Paso 1: Generar secretos fuertes

```bash
# En tu máquina LOCAL (segura):

# Generar WEBHOOK_SECRET (para firmar/validar webhooks del PBX)
WEBHOOK_SECRET=$(openssl rand -base64 32)
echo "WEBHOOK_SECRET=$WEBHOOK_SECRET"

# Generar WEBHOOK_VERIFY_TOKEN (para challenge del PBX)
WEBHOOK_VERIFY_TOKEN=$(openssl rand -hex 16)
echo "WEBHOOK_VERIFY_TOKEN=$WEBHOOK_VERIFY_TOKEN"

# Generar AUDIO_ENCRYPTION_KEY (para cifrado en reposo)
AUDIO_ENCRYPTION_KEY=$(openssl rand -base64 32)
echo "AUDIO_ENCRYPTION_KEY=$AUDIO_ENCRYPTION_KEY"

# Generar DB_PASSWORD (para PostgreSQL, si es nuevo)
DB_PASSWORD=$(openssl rand -hex 32)
echo "DB_PASSWORD=$DB_PASSWORD"

# Generar JWT_SECRET_KEY (para autenticación JWT)
JWT_SECRET_KEY=$(openssl rand -hex 32)
echo "JWT_SECRET_KEY=$JWT_SECRET_KEY"
```

### Paso 2: Transportar secretos al servidor on-prem (por canal seguro)

```bash
# OPCIÓN A: Via SSH (recomendado)
# Crear fichero temporal en local
cat > /tmp/secrets.txt <<EOF
WEBHOOK_SECRET=$WEBHOOK_SECRET
WEBHOOK_VERIFY_TOKEN=$WEBHOOK_VERIFY_TOKEN
AUDIO_ENCRYPTION_KEY=$AUDIO_ENCRYPTION_KEY
DB_PASSWORD=$DB_PASSWORD
JWT_SECRET_KEY=$JWT_SECRET_KEY
EOF

# Transferir via SCP
scp /tmp/secrets.txt operador@servidor-onprem:/tmp/

# En el servidor
ssh operador@servidor-onprem
cat /tmp/secrets.txt  # Revisar que está completo
# NO: rm /tmp/secrets.txt (aún, para copiar a .env)
```

```bash
# OPCIÓN B: Via secret manager (HashiCorp Vault, AWS Secrets Manager)
# Ejemplo Vault:
vault kv put secret/omnicore/voice/webhook_secret value=$WEBHOOK_SECRET
vault kv put secret/omnicore/voice/webhook_verify_token value=$WEBHOOK_VERIFY_TOKEN
vault kv put secret/omnicore/voice/audio_encryption_key value=$AUDIO_ENCRYPTION_KEY
# Luego, en el servidor, hacer pull via Vault CLI
```

### Paso 3: Escribir `.env` en el servidor on-prem

```bash
# En el servidor on-prem, en el directorio del proyecto

cd /ruta/a/CRM_WhatsApp

# Copiar plantilla
cp .env.example .env

# Editar `.env` con los secretos generados (usar editor seguro: vi, nano)
nano .env

# Agregar/actualizar SOLO estas líneas (el resto toma defaults de .env.example):
```

```bash
# En .env del servidor (NUNCA cometer esto al repo):

# Secretos de webhook PBX
WEBHOOK_SECRET=<pegar valor generado arriba>
WEBHOOK_VERIFY_TOKEN=<pegar valor generado>

# Cifrado de audio
AUDIO_ENCRYPTION_KEY=<pegar valor generado>

# BD (si es nuevo deployment)
DB_PASSWORD=<pegar valor generado>
DB_APP_PASSWORD=<generar nuevo con: openssl rand -hex 32>

# JWT
JWT_SECRET_KEY=<pegar valor generado>

# Configuración de voz (usar defaults de .env.example, pero customizar si es necesario)
STT_MODEL=large-v3  # Si tienes GPU con ≥16GB
# STT_MODEL=medium  # Si tienes GPU <16GB o quieres fallback más rápido
# STT_DEVICE=cuda   # Si tienes GPU NVIDIA con drivers correctos
# STT_DEVICE=cpu    # Si NO tienes GPU

AUDIO_RETENTION_DAYS=30  # Política de retención (días)
ENABLE_CALL_RETENTION_PURGE=false  # Dry-run por defecto (seguro)

PBX_EXTERNAL_ENABLED=false  # On-prem: NO activar egress
```

### Paso 4: Proteger `.env`

```bash
# En el servidor
chmod 600 .env  # Solo lectura para el propietario
ls -la .env  # Verificar: -rw------- 1 operador operador

# Verificar que no está en repo
grep ".env" .gitignore  # Debería listar .env (no .env.example)
```

---

## Preparación de modelos STT

### Opción A: Descargar modelos en el servidor on-prem (RECOMENDADO)

Esto ocupa 3+ GB, pero evita descargas en runtime.

```bash
# En el servidor on-prem

# Paso 1: Verificar que Python + pip están disponibles
python3 --version  # 3.10+

# Paso 2: Instalar faster-whisper (localmente)
pip3 install faster-whisper

# Paso 3: Descargar modelo large-v3 (toma 10–30 min, 3.1 GB)
python3 -c "from faster_whisper import WhisperModel; WhisperModel('large-v3')"
# Descarga a ~/.cache/huggingface/models/

# Paso 4: Verificar descarga
ls -lh ~/.cache/huggingface/models/
# Debería haber directorios con pesos del modelo

# Paso 5: Montar en docker-compose.yml
# En docker-compose.yml, asegurarse de que stt_worker + stt_fallback_worker tengan:
services:
  stt_worker:
    volumes:
      - ~/.cache/huggingface/models:/root/.cache/huggingface/models:ro
    environment:
      STT_MODEL_DIR: /root/.cache/huggingface/models
      STT_MODEL: large-v3
      STT_DEVICE: cuda  # o cpu
```

### Opción B: Descargar durante primera ejecución (MÁS LENTO, menos recomendado)

Si no hay tiempo pre-deploy o no hay espacio disponible:

```bash
# El contenedor stt_worker descargará automáticamente al arrancar
# PERO: no hay volumen persistente → cada reinicio descarga otra vez
# ALTERNATIVA: montar volumen pero sin pesos pre-descargados
docker compose up stt_worker  # Primera ejecución, ~30 min
# Luego guardarlo como snapshot/volumen persistente
```

### Validación post-descarga

```bash
# Verificar que el modelo está montado en el contenedor
docker compose exec stt_worker ls -lh /root/.cache/huggingface/models/
# Debería listar archivos de modelo (> 100 MB)

# Verificar que STT funciona (test simple)
docker compose exec stt_worker python3 -c "
from faster_whisper import WhisperModel
model = WhisperModel('large-v3', device='cuda')
print('✓ Model loaded successfully')
" 2>&1 | grep -i "success\|error"
```

---

## Configuración de infraestructura

### Paso 1: Verificar que el volumen de audio está cifrado

```bash
# En el servidor on-prem, IF usas encriptación a nivel de SO

# Opción A: LUKS (Linux Unified Key Setup)
sudo lsblk -la | grep crypt
# Debería haber entrada /dev/mapper/crypt_* si está cifrado

# Opción B: ZFS o storage nativo del proveedor
# Documentar en RUNBOOK_VOICE.md cómo verificar (varía por vendor)

# Si NO está cifrado:
# ⚠️ ADVERTENCIA: Audio en claro en disco
# Mitigación: activar cifrado a nivel SO ANTES de desplegar
# Referencia: `RUNBOOK_VOICE.md` → "Cifrado del almacén de audio"
```

### Paso 2: Configurar red interna `ia_internal` (ADR-009)

En `docker-compose.yml` (ya debe estar, SPEC-023), verificar:

```yaml
networks:
  ia_internal:
    internal: true  # BLOQUEADO: no egress a internet
  app:
    internal: false  # Permite egress pero restringido por firewall
```

### Paso 3: Configurar reverse proxy TLS (Caddy, SPEC-035)

```bash
# En docker-compose.yml, verificar que Caddy está configurado

services:
  reverse_proxy:
    image: caddy:2.8-alpine
    ports:
      - "80:80"
      - "443:443"  # ← HTTPS, escucha TLS
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data  # Certificados
      - caddy_config:/config
    environment:
      CADDY_DOMAIN: ${CADDY_DOMAIN}  # p.ej. omnicore.tudominio.com
      CADDY_HTTP_PORT: ${CADDY_HTTP_PORT}  # 80
      CADDY_HTTPS_PORT: ${CADDY_HTTPS_PORT}  # 443
```

Verificar `Caddyfile` (en raíz del repo):

```caddy
{
  # Auto-HTTPS (Let's Encrypt en producción, autofirmado en desarrollo)
  auto_https on
}

${CADDY_DOMAIN} {
  # IMPORTANTE: Expone SOLO el webhook de grabaciones
  handle /webhooks/pbx/recordings* {
    reverse_proxy api:8000
  }

  # TODO lo demás → 404 o redirige a documentación
  handle {
    respond "Not Found" 404
  }
}
```

**En producción:**

- `CADDY_DOMAIN=omnicore.tudominio.com` (con DNS válido).
- Caddy genera certificado de Let's Encrypt automáticamente.
- Expone SOLO `/webhooks/pbx/recordings`, nada más (hardening).

**En desarrollo (on-prem sin DNS):**

- `CADDY_DOMAIN=localhost`.
- Caddy genera certificado autofirmado.
- Para test: ignorar warnings de certificado (`curl -k https://localhost:443/webhooks/pbx/recordings`).

---

## Deploy del stack completo

### Paso 1: Chequeo final pre-deploy

```bash
cd /ruta/a/CRM_WhatsApp

# 1. Verificar que .env existe con secretos
[ -f .env ] && echo "✓ .env existe" || echo "✗ .env FALTA"

# 2. Validar docker-compose.yml
docker compose config > /dev/null && echo "✓ docker-compose.yml válido" || echo "✗ Errores en compose"

# 3. Revisar que ningún secret está en código
grep -r "WEBHOOK_SECRET\|AUDIO_ENCRYPTION_KEY" backend/app --include="*.py" | grep -v "get_settings\|Settings" | grep -v test
# Esperado: nada o solo en config.py (lectura de env, no hardcoded)

# 4. Revisar que no hay URLs de internet hardcodeadas
bash scripts/check-externos-backend.sh 2>&1 | head -20
# Esperado: "✓ Cero URLs externas" o similar
```

### Paso 2: Arrancar servicios (orden correcto)

```bash
# OPCIÓN A: Arrancar TODO (recomendado para first-time setup)
docker compose up -d

# OPCIÓN B: Arrancar por fases (debugging, si algo falla)
# Fase 1: Infraestructura (BD, Redis)
docker compose up -d db redis

# Esperar 10s
sleep 10

# Fase 2: IA (Ollama, necesario para RAG pero NO para voice)
docker compose up -d ia

# Esperar 20s
sleep 20

# Fase 3: API + workers
docker compose up -d api stt_worker recording_ingest_worker

# Esperar 5s
sleep 5

# Verificar que TODO levantó
docker compose ps
# Todos deben estar "Up" o "healthy"
```

### Paso 3: Healthchecks iniciales

```bash
# 1. API respondiendo
curl http://localhost:8000/healthz
# Esperado: JSON con status=ok

# 2. Todas las dependencias ready
curl http://localhost:8000/readyz | jq .
# Esperado: ready=true, dependencies.db=ok, dependencies.redis=ok, etc.

# 3. Redis accesible
docker compose exec redis redis-cli ping
# Esperado: PONG

# 4. BD accesible
docker compose exec db psql -U omnicore_app -d omnicore_ai -c "SELECT COUNT(*) FROM call;" 2>&1 | grep -i "error\|permission"
# Esperado: 0 (tabla vacía) o error de permiso que ignores por ahora
```

### Paso 4: Migraciones y seed

```bash
# Ejecutar migraciones (ALEMBIC)
docker compose exec api python -m alembic upgrade head
# Esperado: "INFO  [alembic.runtime.migration] Running upgrade (versions) ... done"

# Seed de datos iniciales (si aplica para tu tenant)
docker compose exec api python -m app.cli.seed_demo_tenant
# O tu procedimiento de seed específico
```

### Paso 5: Descargar modelos (si no los descargaste antes)

```bash
# En el contenedor stt_worker
docker compose exec stt_worker python3 -c "
from faster_whisper import WhisperModel
print('Descargando large-v3...')
model = WhisperModel('large-v3', device='cuda')  # o cpu
print('✓ Listo para usar')
"
# Toma 10–30 minutos la primera vez

# Mientras esperas, puedes revisar logs en otra terminal:
docker compose logs -f stt_worker
```

---

## Configuración de PBX on-prem

### Paso 1: Obtener los secretos del servidor

```bash
# En el servidor on-prem
cd /ruta/a/CRM_WhatsApp
grep "^WEBHOOK" .env | grep -v "^#"
# Copiar WEBHOOK_SECRET y WEBHOOK_VERIFY_TOKEN
```

### Paso 2: Configurar PBX (Asterisk o FreeSWITCH)

**Asterisk (extensions.conf):**

```ini
[recordings]
exten => _X.,n,System(
    /usr/local/bin/push_recording.sh \
    "${CDR(uniqueid)}" \
    "${CDR(src)}" \
    "${CDR(dst)}" \
    "${RECORDING_FILE}"
)
```

Script `/usr/local/bin/push_recording.sh`:

```bash
#!/bin/bash
CALL_ID=$1
NUMERO=$2
NUMERO_DESTINO=$3
RECORDING_FILE=$4

WEBHOOK_URL="https://omnicore.tudominio.com/webhooks/pbx/recordings"
WEBHOOK_SECRET="<pegar WEBHOOK_SECRET de .env del servidor>"

# Calcular firma HMAC-SHA256 sobre bytes del audio
SIGNATURE="sha256=$(openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" "$RECORDING_FILE" | awk '{print $NF}')"

# POST
curl -X POST "$WEBHOOK_URL" \
  -F "call_id=${CALL_ID}" \
  -F "numero=${NUMERO}" \
  -F "numero_destino=${NUMERO_DESTINO}" \
  -F "direccion=entrante" \
  -F "duracion=$(sox $RECORDING_FILE -n stat 2>&1 | grep "Length" | awk '{print $2}')" \
  -F "file=@${RECORDING_FILE}" \
  -H "X-Webhook-Signature-256: ${SIGNATURE}" \
  -k  # Ignorar warnings de certificado si usas autofirmado

# Logs de auditoría
echo "[$(date)] Grabación enviada: call_id=$CALL_ID status=$?" >> /var/log/asterisk/push_recordings.log
```

**FreeSWITCH (dialplan.xml):**

```xml
<extension name="record_and_push">
  <condition field="destination_number" expression=".*">
    <action application="record_session" data="$${recordings_dir}/${strftime(%s)}_${caller_id_number}.wav"/>
    <!-- Después de la llamada -->
    <action application="system" 
            data="/usr/local/bin/push_recording.sh '${uuid}' '${caller_id_number}' '${destination_number}' '$${recordings_dir}/${strftime(%s)}_${caller_id_number}.wav'"/>
  </condition>
</extension>
```

### Paso 3: Test del PBX→Webhook

```bash
# Desde el PBX o máquina cercana
# Generar dummy WAV
dd if=/dev/zero bs=16000 count=48 of=/tmp/test.wav 2>/dev/null
# (o usar herramienta del PBX para generar sample)

# Calcular firma
WEBHOOK_SECRET="<pegar de .env>"
SIGNATURE="sha256=$(openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" /tmp/test.wav | awk '{print $NF}')"

# POST
curl -X POST "https://omnicore.tudominio.com/webhooks/pbx/recordings" \
  -F "call_id=pbx-test-001" \
  -F "numero=+573001234567" \
  -F "numero_destino=000-pbx-line" \
  -F "direccion=entrante" \
  -F "file=@/tmp/test.wav" \
  -H "X-Webhook-Signature-256: ${SIGNATURE}" \
  -k  # Si usas certificado autofirmado
  -v  # Verbose para ver detalles

# Esperado: HTTP 202 Accepted
```

---

## Validación post-deploy

### Suite de healthchecks (ejecutar después de deploy)

```bash
#!/bin/bash

echo "=== VALIDACIÓN POST-DEPLOY DE VOZ ==="
echo ""

# 1. API respondiendo
echo "[*] Verificando API..."
curl -s http://localhost:8000/healthz | jq . || echo "✗ API no responde"

# 2. Webhook accesible (reverse proxy)
echo "[*] Verificando webhook..."
curl -s -k "https://localhost:443/webhooks/pbx/recordings?verify_token=$(grep WEBHOOK_VERIFY_TOKEN .env | cut -d= -f2)&challenge=test123" || echo "✗ Webhook no accesible"

# 3. STT worker running
echo "[*] Verificando STT worker..."
docker compose ps | grep stt_worker | grep -q "Up" && echo "✓ STT worker UP" || echo "✗ STT worker DOWN"

# 4. Redis accesible
echo "[*] Verificando Redis..."
docker compose exec redis redis-cli ping 2>/dev/null | grep -q "PONG" && echo "✓ Redis OK" || echo "✗ Redis fail"

# 5. BD accesible
echo "[*] Verificando PostgreSQL..."
docker compose exec db psql -U omnicore_app -d omnicore_ai -c "SELECT 1" 2>/dev/null | grep -q "1" && echo "✓ DB OK" || echo "✗ DB fail"

# 6. Ningún secret en logs
echo "[*] Verificando que no hay secretos en logs..."
docker compose logs api | grep -i "webhook_secret\|audio_encryption" && echo "✗ ¡SECRETOS EN LOGS!" || echo "✓ Sin secretos expuestos"

# 7. Egress bloqueado (IA)
echo "[*] Verificando egress bloqueado..."
docker compose exec ia curl -I https://www.google.com 2>&1 | grep -q "Connection refused\|Failed" && echo "✓ IA no tiene egress" || echo "✗ ¡IA tiene internet!"

echo ""
echo "=== VALIDACIÓN COMPLETADA ==="
```

Ejecutar:

```bash
bash scripts/validate_voice_deploy.sh
```

---

## Rollback (si algo falla)

### Rollback 1: Parar y revertir última versión

```bash
# 1. Parar todo (sin perder volúmenes/datos)
docker compose down

# 2. Cambiar a commit anterior (git)
git log --oneline -10  # Ver últimos commits
git checkout <commit-anterior-a-voz>
# O si no usas git: simplemente restaurar docker-compose.yml anterior

# 3. Arrancar de nuevo
docker compose up -d

# 4. Verificar salud
docker compose ps
docker compose logs --tail=50 api | grep -i error
```

### Rollback 2: Descartar datos de voz (DESTRUCTIVO, último recurso)

```bash
# ⚠️ CUIDADO: Esto BORRA audio almacenado

# 1. Parar servicios
docker compose stop

# 2. Borrar volúmenes (IRREVERSIBLE)
docker volume rm crm_whatsapp_audio_store
docker volume rm crm_whatsapp_redis_data  # Si quieres limpiar colas también

# 3. Limpiar BD (si quieres)
docker compose exec db psql -U postgres -d omnicore_ai -c \
  "DELETE FROM call WHERE created_at > NOW() - INTERVAL '1 day';"

# 4. Arrancar de nuevo (limpio)
docker compose up -d
```

---

## Monitoreo 24x7

### Alerts mínimas recomendadas

```bash
# 1. API caída (healthz no responde)
watch -n 5 'curl -s http://localhost:8000/healthz | jq .status'

# 2. Cola de STT creciendo (backlog)
watch -n 10 'docker compose exec redis redis-cli LLEN stt:jobs'
# Si crece constantemente, escalear stt_worker

# 3. Espacio en disco bajo
df -h /
# Alerta si < 20% libre

# 4. Audio no está siendo purgeado (AUDIO_RETENTION_DAYS expirado sin acción)
du -sh /ruta/a/audio_store
# Si > 100 GB y AUDIO_RETENTION_DAYS=30, verificar que el job se ejecutó

# 5. STT RTF degradando
docker compose logs stt_worker | grep "RTF=" | tail -5
# Si RTF > 1.5 (GPU) o > 5 (CPU), investigar carga

# 6. Cifrado de audio funcionando
# (cada X horas) test cifrado:
docker compose exec api python -c "
from app.core.audio_store import AudioStore
store = AudioStore()
result = store.store_audio(
    call_id='health-check-cipher',
    audio_bytes=b'test',
    tenant_id='health-check'
)
print('Cifrado OK' if result else 'FALLO EN CIFRADO')
"
```

### Logging y métricas (SPEC-042)

Verificar que la observabilidad está activa:

```bash
# 1. Logs estructurados (JSON)
docker compose logs --tail=10 api | jq . 2>/dev/null | head -5
# Esperado: JSON con campos call_id, tenant_id, event, etc.

# 2. Métricas Prometheus
curl -s http://localhost:8001/metrics | grep stt_rtf | head -5
# Esperado: histograma stt_rtf{model=...,device=...}

# 3. Trazas (X-Request-ID en headers)
curl -v http://localhost:8000/healthz 2>&1 | grep -i "X-Request-ID"
# Esperado: header presente
```

---

## Checklist pre-producción

- [ ] Hardware validado (CPU, RAM, GPU si aplica, almacenamiento)
- [ ] Secretos generados y almacenados en secret manager
- [ ] `.env` configurado con secretos (NUNCA committed)
- [ ] Modelos STT descargados (large-v3 o fallback medium)
- [ ] Volumen de audio está cifrado (LUKS/dm-crypt/ZFS)
- [ ] Network isolada: `ia_internal` con `internal: true`, egress bloqueado ✓
- [ ] Reverse proxy TLS (Caddy) configurado, certificado válido
- [ ] PBX on-prem configurado para PUSH de grabaciones
- [ ] Test del webhook con simulador (SPEC-043): 202 OK
- [ ] Validación post-deploy: healthchecks verdes
- [ ] Egress bloqueado verificado (STT sin internet) ✓
- [ ] No hay secretos en logs ✓
- [ ] Runbook (RUNBOOK_VOICE.md) impreso o accesible 24x7
- [ ] Monitoring configurado (alertas en Slack/Telegram/email)
- [ ] Aprobación del Lead (CHECKPOINT C6) obtenida
- [ ] Notificación Telegram enviada (inicio de deploy)

---

## Fin de la guía de deploy on-prem

**No ejecutes estos pasos sin aprobación explícita del Lead (CHECKPOINT C6).**

Volver a:
- **RUNBOOK_VOICE.md** — Operación diaria y troubleshooting
- **EXAMPLES_OPENAPI_VOICE.md** — Ejemplos de uso del webhook
- **backend/tools/pbx_recording_simulator.py** — Test del webhook antes de deploy

