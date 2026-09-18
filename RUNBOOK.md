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

---

## Checkpoints aplicables

- **C2 (Borrado lógico):** Backups NO incluyen DELETE físicos; datos inactivos se marcan como Inactivo.
- **C3 (Secretos):** Procedimientos de cambio de secretos NO muestran valores en logs; `.env` en `.gitignore`.
- **C4 (Criterios verificables):** Todos los procedimientos son reproducibles; no dependen de configuración manual ad-hoc.
- **C6 (Deploy sensible):** Rollbacks documentados; cambios de secretos requieren aprobación explícita.

---

**Referencia:** OPERACION.md para startup inicial; ADR-003/004/005 para decisiones técnicas subyacentes.
