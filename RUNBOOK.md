# Runbook Operativo — OmniCore AI (SPEC-023)

> Guía de procedimientos operativos, respuesta a incidentes, backups y rollback para el despliegue on-prem.
> Clasificación: SENSIBLE (`.no-externo`). Todos los procedimientos respetan C2 (borrado lógico) y C3 (secretos).

## Tabla de contenidos

1. [Arranque y parada](#arranque-y-parada)
2. [Healthchecks y diagnosticó](#healthchecks-y-diagnóstico)
3. [Backups de PostgreSQL](#backups-de-postgresql)
4. [Rotación y renovación de secretos](#rotación-y-renovación-de-secretos)
5. [Respuesta a incidentes comunes](#respuesta-a-incidentes-comunes)
6. [Procedimiento de rollback](#procedimiento-de-rollback)
7. [Verificación de egress bloqueado](#verificación-de-egress-bloqueado)
8. [Verificación de aislamiento multi-tenant (RLS)](#verificación-de-aislamiento-multi-tenant)
9. [Logs y observabilidad](#logs-y-observabilidad)
10. [Escenarios de degradación](#escenarios-de-degradación)
11. [Onboarding multi-tenant (PLAN-009)](#onboarding-multi-tenant-plan-009)
12. [Entregable #5 — Notas de voz de WhatsApp: deploy on-prem](#entregable-5--notas-de-voz-de-whatsapp-deploy-on-prem)
13. [Entregable #6 — TTS de respuesta en notas de voz (SPEC-067/069/072)](#entregable-6--tts-de-respuesta-en-notas-de-voz-spec-067069072)
14. [Dashboard de Analítica de Negocio (SPEC-064/066)](#dashboard-de-analítica-de-negocio-spec-064066)

---

## Arranque y parada

### Startup completo (después de un apagón o restart del host)

```bash
# 1. Ir al directorio del proyecto
cd /ruta/a/CRM_WhatsApp

# 2. Verificar que .env existe con secretos
[ -f .env ] && echo "✓ .env OK" || echo "✗ FALLO: .env no existe"

# 3. Arrancar todo (Docker Compose maneja las dependencias)
docker compose up -d

# 4. Esperar healthchecks (máximo 60 s)
docker compose ps  # Todos deben estar "(healthy)" o "Up"

# 5. Verificar logs de inicio
docker compose logs --tail=30 api

# Salida esperada:
# [INFO] Application startup complete
# [INFO] Database pool opened
# [INFO] Redis client connected
```

### Startup paso a paso (troubleshooting)

Si `docker compose up -d` falla:

```bash
# 1. Revisar errores específicos
docker compose logs --tail=50 api

# 2. Si BD no arranca:
docker compose logs db
# Buscar: "LOG: database system is ready to accept connections"

# 3. Si Ollama falla:
docker compose logs ia
# Buscar: "Listening on http://0.0.0.0:11434"

# 4. Si Redis falla:
docker compose logs redis
# Buscar: "Ready to accept connections"

# 5. Si todo falla: restart completo (sin perder datos)
docker compose down
docker compose up -d
```

### Parada ordenada

```bash
# Parada limpia (sin timeout forzado)
docker compose stop --timeout 30

# Salida esperada: todos los containers "Stopped"
docker compose ps  # Deben estar "Exited"

# Para reanimar sin perder datos:
docker compose start
```

### Parada con pérdida de volúmenes (CUIDADO)

```bash
# Remover TODO incluyendo BD, Redis, modelos
docker compose down -v

# NOTA: Esto borrará:
# - PostgreSQL schema y datos
# - Redis cache
# - Modelos Ollama descargados
# Requerirá re-descargar modelos y re-ejecutar migraciones.
```

---

## Healthchecks y diagnóstico

### Health check rápido (5 comandos)

```bash
# 1. PostgreSQL listo
docker compose exec db pg_isready -U postgres

# Salida: "accepting connections" = OK

# 2. Redis listo
docker compose exec redis redis-cli ping

# Salida: "PONG" = OK

# 3. Ollama listo
docker compose exec ia curl -s http://localhost:11434/api/tags | jq . | head -5

# Salida: { "models": [...] } = OK

# 4. API listo
curl -s http://localhost:8000/healthz | jq .

# Salida: { "status": "ok" } = OK

# 5. API listo con dependencias
curl -s http://localhost:8000/readyz | jq .

# Salida: { "ready": true, "db": "ok", "redis": "ok", "ollama": "ok" } = OK
```

### Estado detallado de contenedores

```bash
# Ver estado y recursos de todos los servicios
docker compose ps --all

# Ver detalles de un servicio específico
docker compose ps api

# Ver logs en tiempo real (últimos 10 líneas)
docker compose logs -f api --tail=10

# Detener logs: Ctrl+C
```

### Métricas de recursos

```bash
# CPU, memoria, I/O de cada contenedor (actualiza cada 2 s)
docker compose stats

# Salida esperada (mientras hay actividad):
# CONTAINER ID   NAME              CPU %     MEM USAGE / LIMIT
# ...            crm_api           2.3%      320MiB / 32GiB
# ...            crm_ia            45.2%     8.5GiB / 32GiB  (inferencia RAG activa)
# ...            crm_db            1.5%      150MiB / 32GiB
# ...            crm_redis         0.8%      80MiB / 32GiB

# Para salir: Ctrl+C
```

---

## Backups de PostgreSQL

### Backup manual (full dump)

```bash
# Crear directorio para backups
mkdir -p /backups/crm

# Ejecutar pg_dump desde el contenedor db
docker compose exec db pg_dump \
  -U postgres \
  -d omnicore_ai \
  --format=plain \
  > /backups/crm/backup_$(date +%Y%m%d_%H%M%S).sql

# Salida esperada: archivo SQL creado (~10–100 MB dependiendo de volumen)

# Verificar que se creó
ls -lh /backups/crm/

# Ejemplo: -rw-r--r-- 1 root root 45M Sep 18 16:30 backup_20260918_163000.sql
```

### Backup automático con cron (recomendado)

```bash
# Crear script de backup
cat > /usr/local/bin/backup-crm.sh << 'EOF'
#!/bin/bash
set -e
BACKUP_DIR="/backups/crm"
BACKUP_FILE="${BACKUP_DIR}/backup_$(date +%Y%m%d_%H%M%S).sql"
cd /ruta/a/CRM_WhatsApp
docker compose exec db pg_dump -U postgres -d omnicore_ai --format=plain > "$BACKUP_FILE"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] Backup creado: $BACKUP_FILE" | logger
# Retener últimos 7 días
find "$BACKUP_DIR" -name "backup_*.sql" -mtime +7 -delete
EOF

chmod +x /usr/local/bin/backup-crm.sh

# Añadir a crontab (ejecutar diariamente a las 2 AM)
crontab -e
# Añadir línea:
# 0 2 * * * /usr/local/bin/backup-crm.sh
```

### Restaurar desde backup

```bash
# 1. Detener la aplicación (opcional, pero recomendado)
docker compose stop api rag_worker sentiment_worker

# 2. Detener BD (CUIDADO: borrará datos actuales)
docker compose stop db

# 3. Borrar volumen de datos (IRREVERSIBLE)
# Nota: Docker normaliza el nombre del proyecto a minúsculas
docker volume rm crm_whatsapp_db_data

# 4. Recrear el contenedor y volumen
docker compose up -d db

# 5. Esperar a que PostgreSQL esté listo
docker compose exec db pg_isready -U postgres

# 6. Restaurar desde el backup
docker compose exec -T db psql -U postgres < /backups/crm/backup_20260918_163000.sql

# Salida esperada: psql muestra líneas de "CREATE TABLE", "INSERT", etc.

# 7. Reiniciar el resto de servicios
docker compose up -d api rag_worker sentiment_worker

# 8. Verificar que todo está OK
curl http://localhost:8000/readyz | jq .
```

### Validar integridad del backup

```bash
# Comprimir para almacenamiento a largo plazo
gzip /backups/crm/backup_*.sql

# Almacenar en un servidor remoto seguro (ej. rsync, S3)
rsync -av --delete /backups/crm/ usuario@servidor-backup:/backups/crm/

# Verificar que el backup comprimido se puede expandir
zcat /backups/crm/backup_20260918_163000.sql.gz | head -20

# Salida: primeras 20 líneas del dump (comentarios SQL)
```

---

## Rotación y renovación de secretos

### Cambiar contraseña de PostgreSQL

```bash
# PRECAUCIÓN: Requiere actualizar .env y reiniciar servicios

# 1. Generar contraseña nueva
NEW_PASSWORD=$(openssl rand -hex 32)
echo "Nueva contraseña: $NEW_PASSWORD"

# 2. Actualizar en PostgreSQL
docker compose exec db psql -U postgres -c "ALTER USER postgres WITH PASSWORD '$NEW_PASSWORD';"

# 3. Actualizar .env
sed -i "s/DB_PASSWORD=.*/DB_PASSWORD=$NEW_PASSWORD/" .env

# 4. Reiniciar servicios que usan BD
docker compose restart api rag_worker sentiment_worker

# 5. Verificar conexión
docker compose exec api alembic current

# Salida: "Running with database at postgresql://..." = OK
```

### Cambiar JWT_SECRET_KEY

```bash
# PRECAUCIÓN: Todos los tokens activos se invalidarán

# 1. Generar clave nueva
NEW_JWT_SECRET=$(openssl rand -hex 32)
echo "Nuevo JWT_SECRET_KEY: $NEW_JWT_SECRET"

# 2. Actualizar .env
sed -i "s/JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$NEW_JWT_SECRET/" .env

# 3. Reiniciar API (servicios que generan/validan tokens)
docker compose restart api rag_worker sentiment_worker

# 4. Notificar a usuarios/clientes: sus tokens JWT anteriores ya NO son válidos
#    Deben hacer re-login.

# 5. Verificar que los nuevos tokens funcionan
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"tenant_slug":"demo","email":"agente@demo.local","password":"..."}'
```

### Cambiar CORS_ORIGINS

```bash
# Modificar .env
CORS_ORIGINS=https://newdomain.com,https://internal.corp.local

# Reiniciar API
docker compose restart api

# Verificar con un OPTIONS request
curl -i -X OPTIONS http://localhost:8000/api/v1/conversations \
  -H "Origin: https://newdomain.com" \
  -H "Access-Control-Request-Method: GET"

# Salida esperada: respuesta con Access-Control-Allow-Origin: https://newdomain.com
```

---

## Respuesta a incidentes comunes

### Incidente: Redis caído

**Síntomas:** Colas de ingesta RAG no se procesan; WebSocket desconectado; errores en logs de `rag_worker`.

**Diagnóstico:**

```bash
# 1. Verificar estado
docker compose ps redis

# Si status es "Exited": Redis se crasheó

# 2. Ver logs
docker compose logs redis --tail=50

# Buscar: "OutOfMemory", "CORRUPT", "SIGTERM"
```

**Recuperación:**

```bash
# Opción 1: Restart simple (datos en Redis se pierden, pero eso es aceptable para caché)
docker compose restart redis

# Opción 2: Si está corrompido, borrar datos y recrear
docker compose stop redis
# Nota: Docker normaliza el nombre del proyecto a minúsculas
docker volume rm crm_whatsapp_redis_data
docker compose up -d redis

# Resultado: Redis vacío, colas/pub-sub se reinician, trabajos pendientes se reintentarán
```

### Incidente: PostgreSQL caído

**Síntomas:** API devuelve `503 Service Unavailable`; logs de `api` muestran "connection refused".

**Diagnóstico:**

```bash
# 1. Verificar estado
docker compose ps db

# 2. Ver logs
docker compose logs db --tail=50

# Buscar: "PANIC", "FATAL", "disk full"
```

**Recuperación:**

```bash
# Opción 1: Restart simple
docker compose restart db

# Esperar healthcheck
docker compose exec db pg_isready -U postgres

# Opción 2: Si está corrupto, restaurar desde backup (ver sección "Restaurar desde backup")
```

### Incidente: Ollama no responde (timeout en inferencia)

**Síntomas:** RAG lento; `POST /api/v1/rag/draft` devuelve 504 Gateway Timeout.

**Diagnóstico:**

```bash
# 1. Verificar que Ollama está vivo
docker compose ps ia

# 2. Comprobar modelo cargado en memoria
docker compose exec ia curl -s http://localhost:11434/api/tags | jq '.models[] | {name, size}'

# Si está vacío: los modelos no se descargaron aún

# 3. Ver logs de Ollama
docker compose logs ia --tail=50

# Buscar: "error loading model", "OutOfMemory", "CUDA out of memory"
```

**Recuperación:**

```bash
# Opción 1: Restart del contenedor (libera memoria)
docker compose restart ia

# Opción 2: Si no hay modelos, descargarlos
docker compose exec ia ollama pull qwen2.5:7b-instruct

# Opción 3: Cambiar a modelo más pequeño/CPU si sin GPU
# Editar .env:
# OLLAMA_MODEL=qwen2.5:7b-instruct-q4_1
docker compose restart ia
docker compose exec ia ollama pull qwen2.5:7b-instruct-q4_1
```

### Incidente: Trabajador RAG/sentimiento se queda atascado (sin procesar jobs)

**Síntomas:** Redis tiene jobs pendientes en `rag:ingest:*` o `sentiment:analyze:*`, pero no se procesan.

**Diagnóstico:**

```bash
# 1. Comprobar que el worker está vivo
docker compose ps rag_worker sentiment_worker

# Si status es "Exited": el worker crasheó

# 2. Ver logs del worker
docker compose logs rag_worker --tail=50

# Buscar: "exception", "error", "SIGTERM"

# 3. Ver jobs pendientes en Redis
docker compose exec redis redis-cli KEYS "rag:ingest:*"

# Salida: lista de jobs pendientes
```

**Recuperación:**

```bash
# Opción 1: Restart del worker (reinicia desde where it left off)
docker compose restart rag_worker sentiment_worker

# Opción 2: Si hay jobs corruptos, limpiar la cola
docker compose exec redis redis-cli DEL rag:ingest:queue

# Opción 3: Ver si es error de timeout
# Editar .env: aumentar AI_REQUEST_TIMEOUT_SECONDS
# AI_REQUEST_TIMEOUT_SECONDS=60  # (en vez de 30)
docker compose restart rag_worker
```

### Incidente: API en loop de crashes (no arranca)

**Síntomas:** `docker compose up` muestra `api` en estado `Exited (1)` repetidamente.

**Diagnóstico:**

```bash
# 1. Ver logs de error
docker compose logs api --tail=100

# Buscar: "ModuleNotFoundError", "ImportError", "SyntaxError", "ValueError: ..."

# 2. Comprobar que dependencias están listas
docker compose exec db pg_isready -U postgres
docker compose exec redis redis-cli ping
docker compose exec ia curl http://localhost:11434/api/tags

# 3. Validar secretos en .env
grep -E "^(DB_PASSWORD|JWT_SECRET_KEY)=" .env

# Si están vacíos, falla startup
```

**Recuperación:**

```bash
# Opción 1: Comprobar sintaxis de .env
# Asegurarse de que no hay espacios alrededor de '='
# DB_PASSWORD=valor (OK)
# DB_PASSWORD = valor (NO OK)

# Opción 2: Validar docker-compose.yml
docker compose config --quiet

# Opción 3: Rebuild de la imagen (si hay cambios en Dockerfile)
docker compose build --no-cache api

# Opción 4: Reiniciar con logs
docker compose restart api
docker compose logs api -f --tail=50

# Salida: debería mostrar "Application startup complete"
```

---

## Procedimiento de rollback

### Rollback de migración de BD (downgrade de schema)

Si una migración introduces un bug o incompatibilidad:

```bash
# 1. Identificar la revisión anterior buena
docker compose exec api alembic history --tail=10

# Salida ejemplo:
# (database) 2026-09-15 00:00:00 -> a1b2c3d4e5f6, Crear tabla documento...
# (database) 2026-09-10 00:00:00 -> f6e5d4c3b2a1, Crear tabla mensaje...
# (head) 2026-09-18 00:00:00 -> 7f8e9d0c1b2a, Crear índice RAG (PROBLEMA)

# 2. Downgrade a la revisión anterior
docker compose exec api alembic downgrade f6e5d4c3b2a1

# Salida esperado:
# INFO [alembic.runtime.migration] Running downgrade 7f8e9d0c1b2a -> f6e5d4c3b2a1, ...

# 3. Verificar estado
docker compose exec api alembic current

# Salida: debe mostrar "f6e5d4c3b2a1" como current (no "7f8e9d0c1b2a")

# 4. Reiniciar servicios para que lean el nuevo schema
docker compose restart api rag_worker sentiment_worker

# 5. Verificar que todo está OK
curl http://localhost:8000/readyz | jq .
```

### Rollback de código de aplicación (versión anterior de imagen)

Si un deploy de código introduce un bug:

```bash
# 1. Recuperar versión anterior de la imagen Docker
# (Asumiendo que etiquetaste imágenes con commits o versiones)

# Opción A: Si tienes imágenes locales con tags
docker images | grep crm_api

# Ejemplo: crm_whatsapp-api   v1.0.0      a1b2c3d4e5f6
# Ejemplo: crm_whatsapp-api   v0.9.5      f6e5d4c3b2a1  <- versión anterior buena

# 2. Actualizar docker-compose.yml temporalmente para usar imagen anterior
# O usar docker-compose override:
cat > docker-compose.override.yml << 'EOF'
version: '3.9'
services:
  api:
    image: crm_whatsapp-api:v0.9.5
EOF

# 3. Reiniciar con imagen anterior
docker compose down
docker compose up -d api rag_worker sentiment_worker

# 4. Verificar que está OK
curl http://localhost:8000/healthz

# 5. Investigar qué falló en v1.0.0
git log --oneline v0.9.5..v1.0.0
git show <commit>

# 6. Una vez corregido, reconstruir y redeploy
rm docker-compose.override.yml
docker compose build api
docker compose up -d api
```

### Rollback de datos (restauración desde backup)

Si datos fueron corrompidos/borrados accidentalmente:

```bash
# Ver sección "Restaurar desde backup" arriba (procedimiento completo)
```

---

## Verificación de egress bloqueado

### Prueba automática: `check-externos-backend.sh`

```bash
# Ejecutar desde la raíz del proyecto
bash backend/check-externos-backend.sh

# Salida esperada (todo en verde):
# ✓ APROBADO: cero referencias a APIs externas de IA
```

### Prueba manual: Intentar alcanzar internet desde Ollama

```bash
# Intenta conectar a un servicio externo CONOCIDO (fallará si egress está bloqueado)
docker exec crm_ia wget -T5 -qO- http://1.1.1.1 2>&1 \
  && echo "✗ FALLO: egress desbloqueado" \
  || echo "✓ EGRESS BLOQUEADO (timeout o error de red)"

# Salida esperada: "✓ EGRESS BLOQUEADO (timeout)"

# Alternativa con curl
docker exec crm_ia sh -c 'timeout 5 curl -v https://api.openai.com 2>&1 | head -5' \
  && echo "✗ FALLO: conexión exitosa (egress NO bloqueado)" \
  || echo "✓ EGRESS BLOQUEADO (timeout)"
```

### Análisis de rutas de red

```bash
# Ver tabla de rutas dentro del contenedor Ollama (debería SIN gateway a internet)
docker exec crm_ia ip route

# Salida esperada: solo rutas locales a 172.20.0.0/16, sin gateway (0.0.0.0/0)
# Ejemplo:
# 172.20.0.0/16 dev eth0 proto kernel scope link src 172.20.0.2
# (sin "default via" que apunte a internet)

# Si hay una línea "default via 172.17.0.1" o similar: EGRESS NO está bloqueado
```

---

## Verificación de aislamiento multi-tenant (RLS)

### Test manual: Intentar acceso cross-tenant

```bash
# 1. Login con usuario del tenant A
TENANT_A_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_slug": "demo",
    "email": "agente@demo.local",
    "password": "demo-password"
  }' | jq -r '.access_token')

# 2. Intentar acceder a datos del tenant B (usando token de A)
curl -s -X GET http://localhost:8000/api/v1/contacts \
  -H "Authorization: Bearer $TENANT_A_TOKEN" \
  -H "X-Tenant-ID: otro-tenant" \
  | jq .

# Salida esperada:
# { "detail": "Acceso denegado: tenant mismatch o RLS violation" }
# (NO: { "data": [...] } de otro tenant)
```

### Test automatizado (HAWKEYE — pytest)

```bash
# Ver `tests/test_rls_isolation.py` (SPEC-022 CE-22)
# Ejecutar:
docker compose exec api pytest tests/test_rls_isolation.py -v

# Salida esperada (todos los tests PASAN):
# test_rls_isolation.py::test_cross_tenant_contact_access FAILED  # Esperado: debe fallar (RLS bloquea)
# test_rls_isolation.py::test_same_tenant_access PASSED

# NOTA: El test `test_cross_tenant_contact_access` DEBE fallar;
# si PASA, quiere decir que RLS NO está funcionando (ALARMA).
```

---

## Logs y observabilidad

### Logs en tiempo real (todos los servicios)

```bash
# Ver logs de TODOS los contenedores
docker compose logs -f

# Salida: timestamp + servicio + línea de log, actualiza en tiempo real

# Filtrar por servicio específico
docker compose logs -f api

# Último N líneas
docker compose logs -f --tail=50 api

# Salir: Ctrl+C
```

### Logs formateados (JSON structured logs)

El backend emite logs en formato JSON para parseo automático:

```bash
# Ver logs JSON del API
docker compose logs api --tail=20 | jq .

# Salida esperada:
# {
#   "timestamp": "2026-09-18T15:30:00Z",
#   "level": "INFO",
#   "message": "POST /api/v1/conversations",
#   "tenant_id": "demo",
#   "request_id": "a1b2c3d4",
#   "latency_ms": 45
# }
```

### Métricas Prometheus

```bash
# Acceder al endpoint `/metrics` (formato OpenMetrics)
curl -s http://localhost:8000/metrics | head -30

# Salida: métricas de Prometheus (HELP, TYPE, datos)

# Graficar en Prometheus/Grafana (si está disponible)
# Query de ejemplo:
# histogram_quantile(0.95, rate(ai_request_duration_seconds_bucket[5m]))
# Resultado: p95 latencia de inferencia IA en los últimos 5 minutos
```

---

## Escenarios de degradación

### Escenario 1: Sin GPU, CPU overflow

**Síntoma:** RAG muy lento (p95 > 30 s); CPU del host en ~100%.

**Acción:**

1. Confirmar sin GPU:
   ```bash
   docker compose logs ia | grep -i cuda
   # Si no hay menciones a CUDA: confirmado sin GPU
   ```

2. Cambiar a modelo Q4 (más pequeño):
   ```bash
   # Editar .env
   OLLAMA_MODEL=qwen2.5:7b-instruct-q4_1
   
   # Descargar
   docker compose exec ia ollama pull qwen2.5:7b-instruct-q4_1
   
   # Reiniciar
   docker compose restart api rag_worker sentiment_worker
   ```

3. Documentar degradación en observabilidad:
   ```bash
   # Ver p95 actual
   curl -s http://localhost:8000/metrics | grep ai_request_duration
   # Buscar: histogram_quantile(0.95, ...) = ~15–30 s esperado
   ```

### Escenario 2: Poco almacenamiento (disco lleno)

**Síntoma:** PostgreSQL rechaza writes; Redis deja de persistir; logs indican "No space left on device".

**Acción:**

1. Verificar espacio disponible:
   ```bash
   df -h /var/lib/docker
   # Si < 10% disponible: problema
   ```

2. Limpiar volúmenes no usados:
   ```bash
   docker compose down
   docker system prune -a  # Borra contenedores, redes, imágenes no usadas
   docker volume prune     # Borra volúmenes no usados
   ```

3. Aumentar almacenamiento:
   ```bash
   # Expandir partición del host o añadir disco
   # (Fuera del alcance de este runbook — consultar DevOps de infraestructura)
   ```

4. Volver a arrancar:
   ```bash
   docker compose up -d
   ```

### Escenario 3: Tráfico muy alto, latencia aumentada

**Síntoma:** `/api/v1/contacts` devuelve p95 > 200 ms; logs muestran conexiones lentias a PostgreSQL.

**Acción:**

1. Ver estadísticas de pool de conexiones:
   ```bash
   docker compose exec api python -c "from app.core.db import get_db_stats; print(get_db_stats())"
   ```

2. Aumentar límite de conexiones si es necesario (en `.env`):
   ```bash
   # Si no existe, el pool por defecto es ~20 conexiones
   # Añadir a .env (si aplicable):
   DB_POOL_SIZE=30
   DB_MAX_OVERFLOW=10
   
   # Reiniciar API
   docker compose restart api rag_worker sentiment_worker
   ```

3. Verificar índices en PostgreSQL:
   ```bash
   docker compose exec db psql -U postgres -d omnicore_ai -c "\d+ contacts"
   # Buscar índices en tenant_id, user_id, etc.
   ```

---

## Onboarding multi-tenant (PLAN-009)

### Resumen

El onboarding multi-tenant implementa un flujo seguro y atómico para que un **admin de plataforma** (credencial separada del modelo de tenants) cree una **sede nueva** (tenant) con su **primer usuario administrador** en una única operación. El tenant queda aislado por RLS desde el primer commit, y el admin puede autenticarse inmediatamente con las credenciales de SPEC-013 (sin cambios).

**Nota importante:** El antiguo flujo de alta manual vía `backend/app/db/seed.py` queda **SOLO para demo y pruebas locales**. La alta de producción real de nuevas sedes usa el flujo nuevo (API o CLI interno), decisión ya confirmada por el Lead (PLAN-009 §12.4).

### Crear o renovar el primer admin de plataforma (bootstrap, C3)

El admin de plataforma es un usuario separado del modelo tenant-scoped (tabla `platform_admins`, sin `tenant_id`). Su credencial se establece mediante bootstrap — una operación de plataforma idempotente que:

1. Lee credenciales **exclusivamente de variables de entorno** (nunca hardcodeadas, C3).
2. Hashea la contraseña con bcrypt (patrón SPEC-013).
3. Inserta en `platform_admins` usando `ON CONFLICT ... DO NOTHING` (no falla ni duplica si el email ya existe).

**Variables de entorno requeridas:**

```bash
PLATFORM_ADMIN_BOOTSTRAP_EMAIL=<EMAIL_AQUI>
PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=<TU_PASSWORD_AQUI>  # 8 caracteres mínimo
PLATFORM_ADMIN_BOOTSTRAP_NOMBRE="Admin de Plataforma"  # Opcional, default si no se define
```

**Ejecución (una sola vez o re-ejecución segura):**

```bash
# En el host del servidor, con DATABASE_URL ya en el entorno:
cd /ruta/a/CRM_WhatsApp
export PLATFORM_ADMIN_BOOTSTRAP_EMAIL=admin@platform.local
export PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=CAMBIA-ESTO-2026
export PLATFORM_ADMIN_BOOTSTRAP_NOMBRE="Admin Operativo"

python -m app.db.bootstrap_platform_admin

# Salida esperada:
# Si es la primera vez:
#   "Bootstrap completo: platform_admin creado (id=..., email='admin@platform.local')."
# Si se re-ejecuta (mismo email):
#   "Bootstrap idempotente: ya existía un platform_admin con email 'admin@platform.local' (sin cambios)."
```

**Seguridad (C3):** Las credenciales NO deben pegarse en chat, logs ni historial de shell. Se recomienda:
- Usar variables de entorno en el servidor (ej. `/etc/systemd/system/crm-bootstrap.service`).
- Nunca guardar la contraseña en un archivo versionado; crearla ad-hoc con `openssl rand -hex 16` y comunicarla por canal seguro.
- Verificar que `.env` está en `.gitignore` y que `bootstrap_platform_admin.py` **nunca** imprime la contraseña.

### Alta de una sede nueva: vía API REST

Una vez que el admin de plataforma está creado, puede autenticarse y crear tenants.

#### Paso 1: Obtener JWT de plataforma

```bash
curl -X POST http://localhost:8000/api/v1/platform/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@platform.local",
    "password": "CAMBIA-ESTO-2026"
  }' | jq .

# Respuesta esperada (200 OK):
# {
#   "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
#   "token_type": "bearer",
#   "expires_in": 3600
# }
```

**Errores esperados:**

- `401 Unauthorized / "Credenciales inválidas"` — email no existe, contraseña incorrecta o admin inactivo.
- `429 Too Many Requests` — demasiados intentos fallidos (rate-limit), reintentar después de `Retry-After` segundos.
- `503 Service Unavailable` — servicio de autenticación (Redis) no disponible.

#### Paso 2: Dar de alta el tenant + primer admin

```bash
TOKEN="eyJ0eXAiOiJKV1QiLCJhbGc..."  # Del paso 1

curl -X POST http://localhost:8000/api/v1/platform/tenants \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "nombre": "Clínica Campbell Sede Bogotá",
    "slug": "clinica-campbell-bogota",
    "admin_email": "admin@clinica-bogota.local",
    "admin_password": "AdminPassword123!",
    "admin_nombre": "Administrador Bogotá"
  }' | jq .

# Respuesta esperada (201 Created):
# {
#   "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
#   "slug": "clinica-campbell-bogota"
# }
```

**Campos del body (`TenantProvisionRequest`):**

| Campo | Tipo | Restricciones | Ejemplo |
|-------|------|---------------|---------|
| `nombre` | string | 1–255 caracteres, no vacío | "Clínica Campbell Sede Bogotá" |
| `slug` | string | 1–100 caracteres, solo dígitos + guiones simples tras normalizar (mayúsculas se bajan a minúsculas automáticamente, igual que `admin_email`; espacios/underscore/guion inicial-final SÍ rechazan); reservados: `platform`, `admin`, `api`, `me` | "clinica-campbell-bogota" |
| `admin_email` | string | 3–255 caracteres, email válido, **único por-tenant** | "admin@clinica-bogota.local" |
| `admin_password` | string | 8–255 caracteres mínimo | "AdminPassword123!" |
| `admin_nombre` | string | 1–255 caracteres, no vacío | "Administrador Bogotá" |

**Errores esperados (tipados, no 500):**

| Código | Descripción | Causa | Acción |
|--------|-------------|-------|--------|
| `401 Unauthorized` | "No autenticado" | Header `Authorization` ausente, malformado o con credenciales inválidas. | Verificar que el JWT de plataforma es válido y no ha expirado. Reintentar `POST /platform/auth/login`. |
| `403 Forbidden` | "Este endpoint requiere credenciales de administrador de plataforma" | Se presentó un JWT de TENANT válido (ej. de un usuario de un tenant existente) en lugar de uno de PLATAFORMA. | Usar únicamente JWT obtenidos de `POST /platform/auth/login`, no de `/api/v1/auth/login`. |
| `409 Conflict` | "El slug '...' ya está en uso" o "El email '...' ya está en uso en este tenant" | Colisión de slug (único global en `tenants`) o email (único por-tenant). | Elegir un slug/email diferente. El slug es único globalmente; el email es único dentro del tenant, pero si se reintenta la misma combinación slug+email tras un fallo, colisiona. |
| `422 Unprocessable Entity` | "El slug debe contener solo minúsculas..." o "La contraseña debe tener al menos 8 caracteres..." | Validación de formato: slug con espacios/underscore/guion inicial-final/caracteres inválidos (las mayúsculas NO fallan, se normalizan solas), password corta, nombre vacío, email con formato inválido o slug reservado. | Revisar el formato según la tabla arriba. Ejemplo: si slug es "Clinica Demo", cambiar a "clinica-demo" (el espacio es el problema, no las mayúsculas). |

#### Paso 3: Verificar que el tenant está aislado

Tras el alta, el tenant existe y el primer admin puede autenticarse:

```bash
# Autenticarse como el primer admin del tenant recién creado (SPEC-013, sin cambios)
TENANT_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_slug": "clinica-campbell-bogota",
    "email": "admin@clinica-bogota.local",
    "password": "AdminPassword123!"
  }' | jq -r '.access_token')

# Verificar que puede acceder a sus propios datos (vacíos de inicio)
curl -s -H "Authorization: Bearer $TENANT_TOKEN" \
  http://localhost:8000/api/v1/tenants/me | jq .

# Salida esperada:
# {
#   "tenant_id": "550e8400-...",
#   "nombre": "Clínica Campbell Sede Bogotá",
#   "slug": "clinica-campbell-bogota"
# }
```

### Alta de una sede nueva: vía CLI interno

Para uso administrativo desde el servidor (sin HTTP), hay un CLI que invoca el mismo servicio:

```bash
cd /ruta/a/CRM_WhatsApp

# Opción 1: Password vía variable de entorno (recomendado, C3)
export PROVISION_TENANT_ADMIN_PASSWORD="AdminPassword123!"
python -m app.db.provision_tenant \
  --nombre "Clínica Campbell Sede Cali" \
  --slug clinica-campbell-cali \
  --admin-email admin@clinica-cali.local \
  --admin-nombre "Administrador Cali"

# Opción 2: Password vía argumento (NO recomendado, queda en historial de shell)
python -m app.db.provision_tenant \
  --nombre "Clínica Campbell Sede Cali" \
  --slug clinica-campbell-cali \
  --admin-email admin@clinica-cali.local \
  --admin-password "AdminPassword123!" \
  --admin-nombre "Administrador Cali"
```

**Salida esperada (éxito):**

```
Tenant aprovisionado: tenant_id=550e8400-e29b-41d4-a716-446655440000 slug=clinica-campbell-cali admin_user_id=6ba7b810-9dad-11d1-80b4-00c04fd430c8
```

**Errores esperados (codigo de salida distinto a 0):**

- **Código 2:** Error de validación (slug inválido, password corta, nombre vacío, email con formato inválido, slug reservado).
- **Código 1:** Error de colisión (slug ya existe, email ya existe, u otro error de integridad).

**Variables de entorno:**

| Variable | Requerida | Fuente | Propósito |
|----------|-----------|--------|----------|
| `DATABASE_URL` | Sí | Sistema (`.env` o entorno del servidor) | Conexión a PostgreSQL |
| `PROVISION_TENANT_ADMIN_PASSWORD` | No (opcional) | Sistema | Si se define, se usa en lugar de `--admin-password` (C3) |

### Garantías de atomicidad y aislamiento

Ambos flujos (API y CLI) invocan el **mismo servicio transaccional** `tenant_provisioning_service.provision_tenant`, que garantiza:

1. **Atomicidad (todo o nada):** Si algo falla a mitad del proceso (p.ej. el email ya existe en ese tenant, aunque es improbable en un recién creado), toda la transacción se revierte. **Nunca se crea un tenant huérfano sin admin, ni un admin sin tenant.**

2. **Aislamiento inmediato (RLS efectiva):** El tenant se crea y queda aislado desde el primer `INSERT` en `tenants`. El primer admin se inserta bajo RLS efectiva (patrón `set_tenant_session` → `app.tenant_id` fijado), no con bypass owner. Es exactamente el patrón de `auth_service.authenticate` (SPEC-013), probado y documentado en ADR-004/ADR-008.

3. **Validación tipada:** No hay excepciones 500 inesperadas. Todos los errores operacionales se tipan (409 colisión, 422 validación, 401/403 autenticación).

**Verificar aislamiento cruzado (test manual, multi-tenant):**

```bash
# Suponiendo 2 tenants: "clinica-campbell-bogota" y "clinica-campbell-cali"
# Admin de Bogotá obtiene token
TOKEN_A=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_slug": "clinica-campbell-bogota",
    "email": "admin@clinica-bogota.local",
    "password": "AdminPassword123!"
  }' | jq -r '.access_token')

# Admin de Cali obtiene token
TOKEN_B=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_slug": "clinica-campbell-cali",
    "email": "admin@clinica-cali.local",
    "password": "AdminPassword456!"
  }' | jq -r '.access_token')

# Bogotá intenta acceder a contactos (vacío, ya que no hay datos)
curl -s -H "Authorization: Bearer $TOKEN_A" \
  http://localhost:8000/api/v1/contacts | jq '.items | length'
# Salida: 0

# Cali intenta acceder a contactos (vacío también)
curl -s -H "Authorization: Bearer $TOKEN_B" \
  http://localhost:8000/api/v1/contacts | jq '.items | length'
# Salida: 0

# Ambos ven sus propios datos, nunca los del otro (RLS funciona)
```

### Seed.py: uso limitado (demo/pruebas, no producción)

El archivo `backend/app/db/seed.py` permanece **intacto** pero es ahora **solo para demo local y CI/tests**. Define dos tenants ficticios (`clinica-demo-norte` y `clinica-demo-sur`) con datos de ejemplo.

**Cuándo usar `seed.py`:**

- Desarrollo local (`docker compose up`): proporciona datos iniciales para pruebas manuales.
- Tests automatizados (`pytest`): fixtures usan datos del seed para verificar aislamiento RLS.
- Documentación/demostraciones: la base de datos comienza con tenants de ejemplo.

**Cuándo NO usar `seed.py`:**

- **Producción real:** No ejecutes `python -m app.db.seed` en un servidor de producción. El alta de nuevas sedes debe hacerse vía:
  - API: `POST /platform/tenants` (requiere JWT de admin de plataforma).
  - CLI: `python -m app.db.provision_tenant` (directa, para equipo interno confiable).
- **Migración de tenants existentes:** Si ya tienes tenants en producción creados de otra forma, son conservados tales cuales (out of scope).

**Verificar que seed.py se ejecutó** (para local/CI):

```bash
docker compose exec db psql -U postgres -d omnicore_ai << 'EOF'
SELECT COUNT(*) as tenants_count FROM tenants;
SELECT COUNT(*) as users_count FROM users;
EOF

# Salida esperada (tras seed):
# tenants_count | 2
# users_count   | 2 (si el seed también crea usuarios, depende de la versión)
```

### Troubleshooting

#### Síntoma: `401 Unauthorized` en `POST /platform/auth/login`

**Causa 1:** Email no existe en `platform_admins`.
```bash
# Verificar que el bootstrap se ejecutó correctamente
docker compose exec db psql -U postgres -d omnicore_ai \
  -c "SELECT id, email, activo FROM platform_admins;"

# Si está vacío, ejecutar bootstrap (ver arriba)
```

**Causa 2:** Contraseña incorrecta.
```bash
# Verificar que escribes correctamente la contraseña
# (se hashea con bcrypt; el hash en BD no es reversible, así que solo se puede verificar re-ejecutando bootstrap)
```

**Causa 3:** Admin inactivo (`activo = false`).
```bash
# Ver estado del admin
docker compose exec db psql -U postgres -d omnicore_ai \
  -c "SELECT id, email, activo FROM platform_admins WHERE email = 'admin@platform.local';"

# Si activo = false, actualizar:
# UPDATE platform_admins SET activo = true WHERE email = 'admin@platform.local';
```

#### Síntoma: `403 Forbidden / "Este endpoint requiere credenciales de administrador de plataforma"`

**Causa:** Se está presentando un JWT de tenant (de `POST /api/v1/auth/login`) en lugar de uno de plataforma (de `POST /api/v1/platform/auth/login`).

```bash
# Asegurar que usas el JWT de PLATAFORMA, no el de tenant
# Correcto:
curl -X POST http://localhost:8000/api/v1/platform/tenants \
  -H "Authorization: Bearer <PLATFORM_JWT_DE_POST_/platform/auth/login>"

# Incorrecto (JWT de tenant, rechazado con 403):
curl -X POST http://localhost:8000/api/v1/platform/tenants \
  -H "Authorization: Bearer <TENANT_JWT_DE_POST_/api/v1/auth/login>"
```

#### Síntoma: `409 Conflict / "El slug ... ya está en uso"`

**Causa:** El slug ya existe en `tenants` (único global).

```bash
# Ver slugs existentes
docker compose exec db psql -U postgres -d omnicore_ai \
  -c "SELECT slug FROM tenants WHERE activo = true;"

# Elegir un slug diferente
# Ejemplo: cambiar "clinica-demo" a "clinica-demo-nueva"
```

#### Síntoma: `422 Unprocessable Entity / "El slug debe contener solo minúsculas..."`

**Causa:** Formato inválido del slug.

**Ejemplos incorrectos:**
- "Clinica Demo" → el ESPACIO es el problema, no las mayúsculas (cambiar a "clinica-demo"; "Clinica-Demo" sin espacio sí sería aceptado y normalizado a "clinica-demo")
- "clinica_demo" → underscore (cambiar a "clinica-demo")
- "clinica--demo" → guiones dobles (cambiar a "clinica-demo")
- "-clinica-demo" → empieza con guion (cambiar a "clinica-demo")
- "clinica-demo-" → termina con guion (cambiar a "clinica-demo")

**Slugs reservados (siempre 422):**
- "platform"
- "admin"
- "api"
- "me"

#### Síntoma: `422 Unprocessable Entity / "La contraseña debe tener al menos 8 caracteres..."`

**Causa:** Password demasiado corta.

- Mínimo: 8 caracteres.
- Recomendación: ≥12 caracteres con mezcla de mayúsculas, dígitos, caracteres especiales.

#### Síntoma: Tenant creado pero no puedo autenticar el primer admin

**Verificación:**

```bash
# 1. Verificar que el tenant existe
docker compose exec db psql -U postgres -d omnicore_ai \
  -c "SELECT id, nombre, slug FROM tenants WHERE slug = 'clinica-campbell-bogota';"

# 2. Verificar que el usuario existe en ese tenant
docker compose exec db psql -U postgres -d omnicore_ai \
  -c "SELECT id, email, rol FROM users WHERE tenant_id = '<TENANT_ID_DEL_PASO_1>';"

# 3. Intentar login con el flujo de SPEC-013
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_slug": "clinica-campbell-bogota",
    "email": "admin@clinica-bogota.local",
    "password": "AdminPassword123!"
  }' | jq .

# Si falla, revisar que:
# - Email coincide exactamente (se normaliza a .strip().lower())
# - Password es la misma que se usó en el alta
```

---

## Entregable #5 — Notas de voz de WhatsApp: deploy on-prem

### Superficie de red expuesta (verificación)

El Entregable #5 (SPEC-053..061) implementa ingesta, almacenamiento cifrado y transcripción de notas de voz de WhatsApp. **No introduce ningún servicio nuevo ni puerto expuesto adicional** sobre lo que ya hay en Entregable #3/4:

- **Webhook HTTPS (ya existente):** `/api/v1/whatsapp/webhook` recibe notas de voz con `type=="audio"` en el mismo puerto 8000 (API FastAPI)
- **Descarga de media (ya existente):** `graph.facebook.com` (ADR-006, WHATSAPP_TOKEN, mismo que envíos de WhatsApp)
- **Almacén de audio (ya existente):** volumen `/audio_store` en `whatsapp_inbound_worker`/`stt_worker` (mismo almacén cifrado que grabaciones de PBX)
- **STT transcripción (ya existente):** `stt_worker` en red `ia_internal` (mismo que Entregable #4, sin egress nuevo)

**Verificación post-deploy:**

```bash
# 1. Confirmar que SOLO el webhook HTTPS está expuesto
docker compose port api
# Salida esperada: 0.0.0.0:8000

# 2. Confirmar que NO hay puertos nuevos expuestos
docker compose ps | grep -E "whatsapp_inbound_worker|stt_worker"
# Ambos SIN "PORTS" abiertos (red interna)

# 3. Confirmar que ia_internal es red interna
docker compose inspect ia_internal | grep -i "internal.*true"
# Debe devolver "true"

# 4. Confirmar que check-externos pasa
make check-externos
# Salida: ✓ APROBADO (cero referencias a APIs externas de IA)
```

**Variables de entorno añadidas (si no existían):**

- `VOICE_NOTE_MAX_DURATION_SECONDS` (default: 600) — límite de duración en ingesta
- `AUDIO_RETENTION_DAYS` (default: 30) — retención de mensajes de audio, reutiliza el job existente `run_call_retention_job`
- `AUDIO_ENCRYPTION_KEY` (ya existente desde Entregable #4) — cifrado del almacén

No hay secretos nuevos introducidos. Todos son rotables por los procedimientos estándar (restarts ordenados).

**Deployment (sin cambios):**

```bash
# Standard docker compose up (con whatsapp_inbound_worker y stt_worker ya en el archivo)
docker compose up -d

# Verificar salud de todos los servicios
docker compose ps  # Todos deben estar "Up" o "(healthy)"

# Probar webhook en local (ver RUNBOOK_WHATSAPP.md sección 7/8)
export WHATSAPP_APP_SECRET=$(openssl rand -hex 32)
export WEBHOOK_URL=http://localhost:8000/api/v1/whatsapp/webhook
python backend/tools/wa_webhook_simulator.py --audio
```

---

## Entregable #6 — TTS de respuesta en notas de voz (SPEC-067/069/072)

### Motor, latencia y configuración

El Entregable #6 (SPEC-067/069/070/071/072) implementa síntesis de voz **100% local** para responder con notas de voz de WhatsApp. No introduce egress externo de inferencia ni terceros.

#### Motor TTS elegido y por qué

- **Motor:** Piper TTS 1.8.0 (SPEC-067, decisión por evidencia medida)
- **Voz:** `es_ES-davefx-medium` (única combinación motor+voz que cumple el techo de latencia ≤10 segundos en las 8 categorías de guion probadas, peor caso p95 = 7.19 s)
- **Alternativa rechazada:** `es_MX-ald-medium` (acento más cercano a LatAm, pero incumple el techo en el guion más largo: 10.137 s medidos)
- **Acento:** español peninsular; trade-off documentado como aceptable para el contexto de atención médica (entienden fácilmente hablantes de LatAm)
- **Configuración:** CPU-only, `use_cuda=False` (ninguna GPU disponible en máquina objetivo)
- **Pesos:** montados por volumen (`respuesta_tts_piper_voices`, sin descarga en runtime — ADR-009/012)

#### Techo de latencia efectivo

- **Objetivo:** ≤5 segundos (objetivo ambicioso para clips cortos)
- **Aceptable:** ≤10 segundos (techo firme, medido por THOR en SPEC-071)
- **Origen del techo:** evaluación de 8 guiones reales (corto 90 chars, medio 180 chars, largo 420 chars) bajo carga CPU concurrente (proxy de STT/RAG/sentimiento corriendo en paralelo)
- **Máximo observado:** 3.67 segundos (guion mediano de 420 chars, bajo máxima concurrencia)
- **Límite sintetizable:** 420 caracteres (bajado de 750 después de que THOR midió guiones más largos excediendo el techo: 11-15 segundos observados)

**¿Por qué 420 caracteres?** El Lead decidió priorizar consistencia de latencia sobre soporte de guiones largos. Cualquier guion > 420 chars se rechaza con error (`tts_estado="error"`, fallback a texto intacto) en lugar de arriesgar exceder el techo bajo carga concurrente.

#### Configuración de throttling y concurrencia

```bash
# En .env:
RESPUESTA_TTS_MAX_CHARS=420              # Límite sintetizable (Q3-c, ADR-014)
RESPUESTA_TTS_TIMEOUT_SECONDS=10         # Techo de latencia
RESPUESTA_TTS_CONCURRENCIA=1             # 1 job de síntesis a la vez (R-84)
RESPUESTA_TTS_ENGINE=piper               # Motor (solo "piper" válido hoy)
RESPUESTA_TTS_PERSIST_ENABLED=false      # NO persistir clips por defecto
```

**¿Por qué concurrencia=1?** THOR (SPEC-071) no validó múltiples workers bajo carga real. Fijar en 1 evita contención CPU compartida con STT/RAG/análisis de sentimiento. Si en el futuro la máquina se amplía (más vCPU/GPU), reevaluar este parámetro con evidence medida.

#### Política de retención

**Por defecto:** No persistir el clip TTS tras envío.

- **Ventaja:** basta el guion aprobado (persiste en `rag_drafts.content` + `Message.body`)
- **Almacenamiento:** transitorios en el almacén cifrado (`/audio_store`), purgados automáticamente tras `wa_send_worker` enviar
- **Conformidad:** C2 (borrado lógico), sin acumulación indefinida de audio sintético

**Activar persistencia (auditoría):**

```bash
# En .env (SENSIBLE, C6 — requiere aprobación explícita del Lead):
RESPUESTA_TTS_PERSIST_ENABLED=true
AUDIO_RETENTION_DAYS=30  # Retención máxima del clip (configurable)
```

Si activado:
- Los clips se cifran vía `app.services.telefonia.audio_store` (mismo régimen que audio entrante, SPEC-041)
- Se puebla `rag_drafts.audio_salida_ref` (referencia opaca, namespaced por tenant/draft_id)
- **Importante (verificado, no asumir):** a diferencia del audio ENTRANTE (`messages.audio_ref`, purgado por `call_retention_service`/`retention_service` existentes), **no existe hoy ningún job de purga automática para `rag_drafts.audio_salida_ref`** — `AUDIO_RETENTION_DAYS` gobierna la retención del audio entrante, no la de este clip de salida. Si se activa la persistencia por auditoría, la purga debe hacerse manualmente (o implementarse como SPEC nueva) hasta que exista ese job; no asumir limpieza automática.

### Disclaimer de voz sintética

La SPA (`src/components/rag/RagDraftCard.tsx`, SPEC-070) muestra un disclaimer **siempre** que `respuesta_modo=="audio"`:

```
🔊 Respuesta de voz asistida
```

- **Marca ligera**, no desactivable (requisito ADR-014)
- **Propósito:** transparencia ante el usuario sobre si la respuesta es síntesis o grabada
- **Control de activación:** toggle `VITE_USE_REAL_API` (reutilizado, no flag nuevo)
  - `VITE_USE_REAL_API=true` → disclaimer visible, UX de audio activa
  - `VITE_USE_REAL_API=false` → mock, sin audio (Entregable #1)

### Operación de rutas híbridas

El sistema soporta **dos rutas** de operación (ADR-014, aprobación híbrida):

#### Ruta 1: Por defecto (aprobar → generar → enviar)

```
Agente approves guion → API: POST approve_and_send()
  → Encola TtsSynthesisJob(modo="enviar")
  → tts_worker: sintetiza
  → Transiciona rag_drafts.tts_estado="listo"
  → Encola WhatsAppOutboundJob (wa_send_worker lo envía)
  → Usuario recibe nota de voz
```

**Curl de ejemplo** (rutas reales del router `app/api/rag.py`, montado bajo `/api/v1/rag`):

```bash
# 1. Aprobación (guion + TTS si respuesta_modo="audio"; endpoint real: /approve)
curl -X POST http://localhost:8000/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/approve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"
# Salida esperada: 200 OK
# rag_drafts.tts_estado pasa a "generando", luego "listo" (async, background)

# 2. Verificar estado del clip (opcional, antes de envío)
curl -X GET http://localhost:8000/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id} \
  -H "Authorization: Bearer $TOKEN"
# Respuesta: {..., "tts_estado": "listo", "audio_listo": true, ...} (nunca expone audio_salida_ref crudo)
```

#### Ruta 2: Opcional — Escuchar antes de enviar

```
Agente solicita "escuchar" (opt-in) → API: POST listen
  → Encola TtsSynthesisJob(modo="escuchar")
  → tts_worker: sintetiza
  → NO encola envío (clip queda en almacén, esperando)
  → Agente: GET audio para descargar y reproducir localmente
  → Agente: decide si aprueba (POST approve, reutiliza el clip ya listo) o rechaza
```

**Curl de ejemplo** (rutas reales del router `app/api/rag.py`, montado bajo `/api/v1/rag`):

```bash
# 1. Solicitar síntesis sin envío ("escuchar antes de decidir")
curl -X POST http://localhost:8000/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/listen \
  -H "Authorization: Bearer $TOKEN"
# Salida esperada: 202 Accepted
# rag_drafts.tts_estado pasa a "generando", luego "listo"

# 2. Descargar el clip (GET, reproducible en navegador)
curl -X GET http://localhost:8000/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/audio \
  -H "Authorization: Bearer $TOKEN" \
  --output clip.ogg
# Salida esperada: 200 OK, binario audio/ogg (~30-100 KB típicamente); 404 si aún no hay clip "listo"

# 3. Decidir: si OK, aprobar (el clip YA listo se envía directo, sin resintetizar)
curl -X POST http://localhost:8000/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/approve \
  -H "Authorization: Bearer $TOKEN"

# O: rechazar (vuelve a texto antes de aprobar)
curl -X PATCH http://localhost:8000/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/respuesta-modo \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"respuesta_modo":"texto"}'
# Ruta de audio desactivada; enviar como texto
```

#### Endpoint de cambio de modo

```bash
# Cambiar modo PRE-aprobación (PATCH, idempotente); campo del body: "respuesta_modo"
curl -X PATCH http://localhost:8000/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/respuesta-modo \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"respuesta_modo":"audio"}'  # o "texto"
# Salida esperada: 200 OK
# rag_drafts.respuesta_modo se actualiza; SÍ puede cambiar antes de aprobar
# Tras aprobar, cambiar modo ya no tiene efecto (síntesis ya encolada)
```

### Troubleshooting

#### Síntoma: `tts_estado="error"` (sin generar clip)

**Causas comunes:**

1. **Guion > 420 caracteres**
   ```bash
   # Verificar longitud
   echo "tu guion aquí" | wc -c
   # Solución: acortar guion o aumentar RESPUESTA_TTS_MAX_CHARS (no recomendado)
   ```

2. **Motor Piper no cargado (pesos no encontrados)**
   ```bash
   # Verificar que el volumen está montado
   docker compose exec tts_worker ls -la /piper_voices
   # Esperado: es_ES-davefx-medium.onnx, es_ES-davefx-medium.onnx.json
   # Si falta: descargar pre-deployment (manual, no en runtime)
   ```

3. **ffmpeg falla transcodificando**
   ```bash
   # Verificar que ffmpeg está disponible
   docker compose exec tts_worker which ffmpeg
   # Si falta: `apt-get install ffmpeg` en el Dockerfile o imagen base
   ```

4. **Timeout de síntesis (>10 segundos)**
   ```bash
   # Ver logs del worker
   docker compose logs --tail=50 tts_worker | grep -i error
   # Aumentar RESPUESTA_TTS_TIMEOUT_SECONDS si es legítimo (no recomendado; mejor acortar guion)
   ```

5. **Base de datos o Redis caídos**
   ```bash
   # Verificar que tts_worker puede conectar
   docker compose exec tts_worker redis-cli -h redis ping
   # Salida esperada: PONG
   docker compose exec tts_worker pg_isready -h db -U omnicore_app
   # Salida esperada: accepting connections
   ```

#### Síntoma: `tts_estado="listo"` pero clip no se envía

**Causas comunes:**

1. **wa_send_worker no leyó la cola `wa:outbound`**
   ```bash
   # Verificar que wa_send_worker está up
   docker compose ps wa_send_worker
   # Esperado: "Up"
   
   # Ver logs
   docker compose logs --tail=20 wa_send_worker
   ```

2. **Credenciales WhatsApp no válidas**
   ```bash
   # Verificar token
   echo $WHATSAPP_TOKEN | head -c 20
   # Si vacío o "dev-only": actualizar .env con token real
   
   # Restart del worker
   docker compose restart wa_send_worker
   ```

3. **Clip no persistido (si `RESPUESTA_TTS_PERSIST_ENABLED=false`)**
   ```bash
   # El clip se purga tras envío — si el envío falla, se pierde
   # Activar persistencia para re-intentos:
   # RESPUESTA_TTS_PERSIST_ENABLED=true (C6 change, requiere aprobación)
   ```

#### Síntoma: Formato OGG/Opus inválido

**Verificación:**

```bash
# Descargar clip via API
curl -X GET http://localhost:8000/api/v1/rag/conversations/{conversation_id}/drafts/{draft_id}/audio \
  -H "Authorization: Bearer $TOKEN" \
  -o test.ogg

# Verificar firma OGG
file test.ogg
# Esperado: "test.ogg: Ogg data, Opus audio, ..."

# O: hexdump (primeros 4 bytes deben ser 0x4F 0x67 0x67 0x53 = "OggS")
hexdump -C test.ogg | head -1
# Esperado: 00000000  4f 67 67 53 ...

# Reproducir (si ffplay disponible localmente)
ffplay test.ogg
```

### Limpieza de residuos documentada (PLAN-005 archivado)

El proyecto archivó el VoiceBot en vivo (PLAN-005, barge-in ≤700 ms, nunca implementado) que usaba tres variables de config GPU:

- `TTS_MODE` (interfaz conmutable "piper generativo" ↔ "modo pregrabado" de bajo cómputo)
- `TTS_VRAM_FRACTION` (reserva de VRAM para TTS en vivo)
- `PIPER_VOICE` (voz Piper, heredada — RETENIDA como única fuente de verdad, CORREGIDA en valor)

**Estado actual:**

| Variable | Estado | Ubicación | Motivo |
|---|---|---|---|
| `TTS_MODE` | ELIMINADA | (residuo, no usado) | No aplica en CPU-only; motor está fijado a Piper |
| `TTS_VRAM_FRACTION` | ELIMINADA | (residuo, no usado) | CPU-only, no hay GPU en máquina objetivo (R-87) |
| `PIPER_VOICE` | RETENIDA, CORREGIDA | `.env.example` línea 345 | Fuente única de verdad (motor+voz); `es_CO-pablo-medium` no existe (404); corregida a `es_ES-davefx-medium` |

**Servicio legado (`voice_tts`):**

El bloque `voice_tts` en `docker-compose.yml` (líneas 872-903) permanece **INTACTO A PROPÓSITO**:
- Imagen placeholder (nunca ejecuta lógica real)
- Heredan `TTS_MODE`, `PIPER_VOICE`, `TTS_VRAM_FRACTION` del `.env.example` (líneas 329-351)
- NO se reactivan; quedan como documentación archivada del diseño de F0
- El Entregable #6 REAL usa prefijo `RESPUESTA_TTS_*` (variables deliberadamente distintas)

**Migración para `.env` existentes:**

Si tus máquinas en producción aún tienen `.env` con `TTS_VRAM_FRACTION`:

```bash
# 1. Editar .env
nano .env

# 2. Buscar y eliminar (NUNCA reemplazar con otro valor; es residuo)
# TTS_VRAM_FRACTION=...
# → Eliminar la línea COMPLETA

# 3. Guardar y reiniciar
docker compose restart
```

No tienes que hacer nada especial. Las variables eliminadas simplemente se ignoran (no son consumidas por ningún módulo de código). Leyendo en `config.py`, las únicas variables leídas son:

- `RESPUESTA_TTS_*` (TTS asincrónico, NUEVO)
- `PIPER_VOICE` / `PIPER_VOICE_DIR` (compartidas, únicamente)
- `AUDIO_*` (almacén, existentes)

**Verificación automática:**

```bash
# Verificar que .env.example NO tiene TTS_VRAM_FRACTION en el bloque tts_worker
grep -A 70 "# TTS asíncrono" .env.example | grep -i "TTS_VRAM_FRACTION"
# Salida esperada: vacío (no encontrado)

# Verificar que docker-compose.yml NO referencia TTS_VRAM_FRACTION en tts_worker
sed -n '561,635p' docker-compose.yml | grep -i "TTS_VRAM_FRACTION"
# Salida esperada: vacío
```

### Simulador local sin egress

Para validar el slice end-to-end localmente (síntesis + formato) sin internet de inferencia:

```bash
# Simulador por defecto (guion ejemplo corto)
python backend/tools/tts_simulator.py

# Simulador con guion personalizado
python backend/tools/tts_simulator.py --guion "Hola, buenos días. Confirmamos tu cita."

# Simulador con guion cercano al límite (400 chars)
python backend/tools/tts_simulator.py --guion "$(python -c 'print(\"Paso a confirmar tu información. Nombre, \" * 30)')"

# Simulador con guion que EXCEDE el límite (430+ chars, debe rechazarse)
python backend/tools/tts_simulator.py --guion "$(python -c 'print(\"a \" * 250)')"
```

**Qué valida:**

1. Motor real (Piper TTS 1.8.0) desde `app.services.telefonia.tts_engine`
2. Normalización de texto (cifras → palabras, siglas → letras)
3. Formato OGG/Opus válido (firma `OggS`, codec Opus)
4. Métricas de latencia (síntesis + transcodificación, objetivo ≤10s)
5. Manejo de errores (`SynthesizableTextTooLongError`, modelo no encontrado, ffmpeg fallo)

**Qué NO valida (scope limitado, como simuladores anteriores):**

- Descarga real desde Graph API de Meta (no hay credenciales, no hay `media_id` real)
- Upload real a WhatsApp (simulador imprime lo que se enviaría, sin ejecutarlo)

Para e2e real, la suite de tests (`backend/tests/test_rag_tts_api.py`) sí valida el ciclo completo en Docker con mocks apropiados.

---

## Dashboard de Analítica de Negocio (SPEC-064/066)

### Operación: vista general

El dashboard de analítica (`GET /api/v1/analytics/business`, endpoint SPEC-063; SPA `AnalyticsPage.tsx`, SPEC-064) proporciona KPIs agregados en tiempo real: volumen de conversaciones, tiempos de respuesta, tasa de conversión y asistencia IA. Modo on-demand (sin caché): cada request recalcula sobre el rango pedido.

**Visibilidad:** cada operador/supervisor ve SOLO datos de su tenant (RLS efectiva, ADR-004/008).

### Configuración de feature-flag

```bash
# Editar .env para activar/desactivar la vista en tiempo real
nano .env

# Agregar (u modificar si existe):
VITE_USE_REAL_API=true              # ON = datos reales; OFF/falta = mock (Entregable #1)
VITE_API_BASE_URL=http://localhost:8000/api/v1  # URL del backend
ANALYTICS_MAX_RANGE_DAYS=366        # Máximo rango de días en una query (protección runaway)
```

Cambio reversible: editar, rebuild del contenedor SPA (`docker compose build --no-cache spa`), reiniciar.

Ver **ANALYTICS_FEATURE_FLAG_GUIDE.md** para procedimiento completo.

### Prueba de extremo a extremo

```bash
# 1. Confirmar backend listo
curl -s http://localhost:8000/readyz | jq .
# Buscar: { "ready": true, "db": "ok", "redis": "ok", "ollama": "ok" }

# 2. Autenticarse y obtener token JWT
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@demo.com", "password": "password"}' \
  | jq -r '.access_token')

# 3. Probar endpoint con rango típico (últimos 30 días)
TODAY=$(date +%Y-%m-%d)
DESDE=$(date -d "30 days ago" +%Y-%m-%d)

curl -s \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/analytics/business?desde=${DESDE}&hasta=${TODAY}" \
  | jq .

# Salida esperada: 200 con estructura BusinessAnalyticsOut (conversaciones, tiempos_respuesta, conversion, etc.)

# 4. Probar error 422 (rango inválido)
curl -s \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/analytics/business?desde=2026-09-27&hasta=2026-09-20" \
  | jq '.detail'

# Salida esperada: "El parámetro 'desde' no puede ser posterior a 'hasta'."

# 5. Probar con filtro de canal
curl -s \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/analytics/business?desde=${DESDE}&hasta=${TODAY}&canal=whatsapp" \
  | jq '.conversaciones.por_canal'

# Salida esperada: array con máximo 1 entrada (canal "whatsapp")
```

### Interpretación de métricas

Ver **METRICS_ANALYTICS.md** para definición precisa de:

- **Volumen:** conversaciones total/abiertas/cerradas/por canal/serie diaria.
- **Tiempos de respuesta:** TPR (primera respuesta) en segundos; respuesta promedio.
- **Conversión:** = cerradas / totales. `null` si totales = 0 (ausencia de datos, no "0%").
- **Asistencia IA:** % de conversaciones con >= 1 draft RAG aprobado; distribución de sentimiento.

**Operador lee:**
- TPR 245 s ≈ 4 min desde que un contacto abre hasta primera respuesta.
- Conversión 83% = de 150 conversaciones, 125 se cerraron.
- IA: 65% de conversaciones tuvieron borradores aprobados; 60% sentimiento positivo.

### Performance y límites

**Latencia objetivo (SPEC-065):** p95 ≤ 1500 ms.

**Límites configurables (`.env`):**

- `ANALYTICS_MAX_RANGE_DAYS` (default 366): máximo número de días en una query. Protege contra queries que exploten la BD. Si se excede: HTTP 422.

**Índices requeridos (migración `b1c8f3d5a704`):**
- `ix_messages_conversation_id_created_at` (compuesto, clave para tiempos de respuesta).
- `ix_conversations_created_at` (filtro de rango de fechas).
- `ix_conversations_canal` (filtro opcional por canal).

Verificar disponibilidad:

```bash
docker compose exec db psql -U postgres -d omnicore_ai -c "\di" | grep -E "messages_conversation_id_created_at|conversations_created_at|conversations_canal"
# Los 3 deben listarse (confirmando que la migración b1c8f3d5a704 pasó)
```

### Verificación de RLS efectiva

Cada endpoint es ejecutado con `SET LOCAL app.tenant_id = '<id_del_jwt>'` antes del handler (fijado en `get_tenant_db`, SPEC-013). Verificar:

```bash
# Simular request de dos tenants distintos (para ambiente con múltiples tenants)
# Tenant A obtiene token TA, solicita analytics
TOKEN_A=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin_a@demo.com", "password": "pass_a"}' | jq -r '.access_token')

# Tenant B obtiene token TB
TOKEN_B=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin_b@demo.com", "password": "pass_b"}' | jq -r '.access_token')

# Ambos consultan el mismo rango
curl -s -H "Authorization: Bearer $TOKEN_A" \
  "http://localhost:8000/api/v1/analytics/business?desde=2026-09-01&hasta=2026-09-30" | jq '.conversaciones.total' > /tmp/a.txt

curl -s -H "Authorization: Bearer $TOKEN_B" \
  "http://localhost:8000/api/v1/analytics/business?desde=2026-09-01&hasta=2026-09-30" | jq '.conversaciones.total' > /tmp/b.txt

# Los totales DEBEN SER DISTINTOS (si ambos tenants tienen conversaciones)
# Si son iguales: ALERTA — posible bypass de RLS
diff /tmp/a.txt /tmp/b.txt
# Si no hay salida: ✗ PROBLEMA (ambos ven lo mismo)
# Si hay salida: ✓ OK (cada uno ve solo sus datos)
```

Los tests de SPEC-065 verifican esto de forma automatizada con fixtures de múltiples tenants.

### Borrado lógico (C2)

Todas las métricas excluyen registros con `activo = False`:

- `Conversation.activo = True`
- `Message.activo = True`
- `RagDraft.activo = True`

Verificar:

```bash
# 1. Crear una conversación
# 2. Obtener analytics (incluye la conversación)
# 3. Soft-delete la conversación (UPDATE Conversation SET activo = false WHERE id = ...)
# 4. Volver a obtener analytics → el total DEBE DISMINUIR en 1

# En SQL (desde el contenedor db):
docker compose exec db psql -U postgres -d omnicore_ai << 'EOF'
-- Contar conversaciones activas
SELECT COUNT(*) as activas FROM conversations WHERE activo = true;
-- Contar TODAS (incluyendo soft-deleted)
SELECT COUNT(*) as todas FROM conversations;
-- El endpoint solo cuenta "activas"
EOF
```

### Caso de uso: supervisión de SLA

Un supervisor quiere verificar el SLA de "Primera respuesta < 5 minutos" en los últimos 7 días:

```bash
# 1. Consultar dashboard con rango [hoy - 6 días, hoy]
# 2. Leer "tiempos_respuesta.primera_respuesta_promedio_seg" = ~245 s ≈ 4 min
# 3. Interpretar: el promedio está bajo 5 min ✓ SLA OK

# En desarrollo:
TODAY=$(date +%Y-%m-%d)
DESDE=$(date -d "6 days ago" +%Y-%m-%d)

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/analytics/business?desde=${DESDE}&hasta=${TODAY}" \
  | jq '.tiempos_respuesta.primera_respuesta_promedio_seg'
# Salida: 245.3 segundos = 4 min 5 s
```

### Troubleshooting

**Síntoma:** endpoint devuelve latencia muy alta (>5000 ms).

**Diagnóstico:**

```bash
# 1. Verificar índices (migración aplicada)
docker compose exec db psql -U postgres -d omnicore_ai -c "\di" | grep messages_conversation_id_created_at
# Si no aparece: la migración no pasó

# 2. Verificar rango solicitado
# Si rango > 90 días: esperado que sea lento (muchos datos)
# Si rango < 7 días pero lento: posible problema de índices/stats

# 3. Verificar CPU/memoria
docker compose stats api db
# Si DB está al 100% CPU: bottleneck de BD

# 4. Ver plan de ejecución (EXPLAIN ANALYZE)
# Desde dentro del contenedor db, ejecutar una versión simplificada de la query
docker compose exec db psql -U postgres -d omnicore_ai << 'EOF'
EXPLAIN ANALYZE
SELECT COUNT(*) FROM conversations
WHERE tenant_id = 'demo'  -- Tenant example
  AND activo = true
  AND created_at >= '2026-09-01'::timestamp
  AND created_at < '2026-10-01'::timestamp;
EOF
# Buscar "Index Scan" (rápido) vs. "Seq Scan" (lento)
```

**Síntoma:** endpoint devuelve 422 "rango no permitido".

**Diagnóstico:**

```bash
# 1. Revisar ANALYTICS_MAX_RANGE_DAYS en .env
grep ANALYTICS_MAX_RANGE_DAYS .env
# Default: 366 días (1 año)

# 2. Contar días solicitados
# Error menciona: "X días solicitados, máximo Y"
# Solución: el operador debe usar rangos más pequeños (p.ej. 30 días a la vez)
```

---

## Escalada y contactos

Si un incidente requiere ayuda especializada:

| Componente | Equipo responsable | Contacto/Escalada |
|---|---|---|
| PostgreSQL / BD | DBA / DevOps | slack: #database-ops |
| Redis / colas | Backend / DevOps | slack: #backend-ops |
| Ollama / IA | ML Eng / Backend | slack: #ai-ops |
| Docker / Infraestructura | DevOps | slack: #infrastructure |
| Seguridad / egress bloqueado | Security / DevOps | slack: #security-incident |

---

## Resumen de procedimientos críticos

| Procedimiento | Comando | Tiempo | Reversibilidad |
|---|---|---|---|
| Backup BD | `docker compose exec db pg_dump ...` | 5 min | ✓ Restaurable |
| Cambiar secreto DB | `pg_isready`, actualizar `.env`, restart | 1 min | ✓ Revertible |
| Cambiar secreto JWT | Editar `.env`, restart | 30 s | ✓ (invalida tokens actuales) |
| Downgrade migraciones | `alembic downgrade <revision>` | 1 min | ✓ Reversible |
| Rollback código | Cambiar imagen Docker, restart | 2 min | ✓ Reversible |
| Limpiar caché Redis | `redis-cli FLUSHALL` | 10 s | ✓ Datos no críticos |
| Verificar egress bloqueado | `docker exec crm_ia wget...` | 10 s | ✓ No destructivo |
| Verificar RLS | Prueba cross-tenant | 20 s | ✓ No destructivo |
| Activar dashboard analítica | Editar `.env`, rebuild SPA | 2 min | ✓ Reversible (toggle flag) |
| Prueba e2e dashboard | Curl endpoint + verificación | 1 min | ✓ No destructivo |

---

## Checkpoints aplicables

- **C2 (Borrado lógico):** Backups NO incluyen DELETE físicos; datos inactivos se marcan como Inactivo.
- **C3 (Secretos):** Procedimientos de cambio de secretos NO muestran valores en logs; `.env` en `.gitignore`.
- **C4 (Criterios verificables):** Todos los procedimientos son reproducibles; no dependen de configuración manual ad-hoc.
- **C6 (Deploy sensible):** Rollbacks documentados; cambios de secretos requieren aprobación explícita.

---

**Referencia:** OPERACION.md para startup inicial; ADR-003/004/005 para decisiones técnicas subyacentes.
