# Operación on-prem — OmniCore AI (Entregable #2, SPEC-023)

> Documentación de despliegue local (Docker Compose) de la infraestructura backend + IA 100% on-prem.
> Proyecto SENSIBLE (`.no-externo`): cero salida a internet de inferencia; modelos descargados localmente.

## Tabla de contenidos

1. [Requisitos previos](#requisitos-previos)
2. [Preparación del entorno](#preparación-del-entorno)
3. [Arranque de servicios](#arranque-de-servicios)
4. [Verificación de salud](#verificación-de-salud)
5. [Descarga de modelos locales](#descarga-de-modelos-locales)
6. [Migraciones de BD e inicialización](#migraciones-de-bd-e-inicialización)
7. [Verificación de "cero externos"](#verificación-de-cero-externos)
8. [Acceso a endpoints](#acceso-a-endpoints)
9. [Parada de servicios](#parada-de-servicios)
10. [Notas sobre hardware y degradación CPU](#notas-sobre-hardware-y-degradación-cpu)

---

## Requisitos previos

### Hardware recomendado

- **CPU:** 4+ núcleos
- **RAM:** Mínimo 16 GB; **recomendado 32+ GB** si se ejecuta Ollama con LLM 7B.
- **Almacenamiento:** 100+ GB para los volúmenes Docker (BD, Redis, modelos).
- **GPU (opcional):**
  - NVIDIA: CUDA 11.8+ (mejor rendimiento RAG, <6 s p95).
  - Sin GPU: fallback a CPU con modelo cuantizado Q4 (Qwen2.5-7B Q4, ~15–30 s p95 por consulta RAG).
  - AMD: ROCm 5.x+ (soporte Ollama, desempeño comparable a CUDA).

### Software requerido

- **Docker Engine:** 24.0+ ([instalación](https://docs.docker.com/engine/install/))
- **Docker Compose:** 2.20+ (incluido en Docker Desktop)
- **Python:** 3.10+ (para scripts de seed y utilidades, no obligatorio para ejecutar contenedores)
- **Bash:** para scripts de utilidad

### Conectividad y red

- **Host aislado recomendado:** sin acceso directo a internet (o bloqueado en firewall).
- **Red interna `ia_internal`:** configurada con `internal: true` en `docker-compose.yml`; bloquea egress del contenedor IA a internet (SPEC-016, SENSIBLE).
- **Puertos necesarios:**
  - `8000` (API FastAPI): expuesto localmente; terminación TLS requiere reverse proxy externo (Nginx/Traefik).
  - `5432` (PostgreSQL): NO expuesto a internet (solo red Docker `app`).
  - `6379` (Redis): NO expuesto a internet (solo red Docker `app`).
  - `11434` (Ollama): NO accesible desde fuera (red interna `ia_internal`).

---

## Preparación del entorno

### 1. Clonar/verificar el repositorio

```bash
cd /ruta/a/CRM_WhatsApp
ls -la docker-compose.yml  # verificar que existe
```

### 2. Crear archivo `.env` con secretos

**CRÍTICO:** Los secretos (DB_PASSWORD, JWT_SECRET_KEY) son obligatorios y NO tienen defaults débiles.

```bash
# Copiar la plantilla de ejemplo
cp .env.example .env

# Editar .env con valores FUERTES (CHECKPOINT C3)
# Usar un editor seguro (vi, nano, etc.)
nano .env
```

**Variables OBLIGATORIAS (fail-fast si faltan o son débiles):**

- `DB_PASSWORD`: ≥32 caracteres alfanuméricos; evitar palabras comunes como "postgres", "changeme".
  ```bash
  # Generar una fuerte (NUNCA copies un valor concreto de documentación)
  openssl rand -hex 32
  # Resultado: una salida aleatoria de 64 caracteres hex
  # Copiar ESE resultado a .env, no a un ejemplo documentado
  ```
- `JWT_SECRET_KEY`: ≥32 caracteres; usada para firmar tokens JWT.
  ```bash
  # Generar una fuerte (NUNCA copies un valor concreto de documentación)
  openssl rand -hex 32
  # Resultado: una salida aleatoria de 64 caracteres hex
  # Copiar ESE resultado a .env, no a un ejemplo documentado
  ```

**Variables RECOMENDADAS (con defaults sensatos):**

- `ENVIRONMENT=production` (o `development` si es local para testing).
- `OLLAMA_MODEL=qwen2.5:7b-instruct` — modelo por defecto en español.
- `OLLAMA_EMBED_MODEL=nomic-embed-text` — embeddings locales.
- `DATA_RETENTION_DAYS=90` — antigüedad de contactos inactivos para anonimización.
- `CORS_ORIGINS=https://tudominio.com` — allowlist explícita (nunca `*` con credenciales).

**Ejemplo de `.env` con placeholders (REEMPLAZAR CON SECRETOS GENERADOS):**

```bash
# PostgreSQL
DB_NAME=omnicore_ai
DB_USER=postgres
DB_PASSWORD=<GENERAR: openssl rand -hex 32>
DB_PORT=5432
DATABASE_URL=postgresql://postgres:${DB_PASSWORD}@db:5432/omnicore_ai

# Redis
REDIS_URL=redis://redis:6379
REDIS_HOST=redis
REDIS_PORT=6379

# Ollama (IA local)
OLLAMA_BASE_URL=http://ia:11434
OLLAMA_MODEL=qwen2.5:7b-instruct
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_NUM_THREAD=4
AI_CONNECT_TIMEOUT_SECONDS=5
AI_REQUEST_TIMEOUT_SECONDS=30

# API
API_HOST=0.0.0.0
API_PORT=8000
ENVIRONMENT=production

# Seguridad (C3: secretos fuertes — REEMPLAZAR antes de desplegar)
JWT_SECRET_KEY=<GENERAR: openssl rand -hex 32>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30

# Rate-limiting
LOGIN_RATE_LIMIT_MAX_ATTEMPTS=5
LOGIN_RATE_LIMIT_WINDOW_SECONDS=300
LOGIN_RATE_LIMIT_STRICT_REDIS=true

# CORS allowlist (NUNCA "*" con credenciales)
CORS_ORIGINS=https://app.tudominio.com

# Datos personales (HABEAS DATA)
DATA_RETENTION_DAYS=90
ENABLE_DATA_ANONYMIZATION=false
```

### 3. Validar sintaxis de `docker-compose.yml`

```bash
# Verificar que la configuración es válida (requiere .env con secretos)
docker compose config --quiet

# Salida esperada: sin errores; exit code 0
```

---

## Arranque de servicios

### Paso 1: Levantar contenedores en orden

```bash
# Iniciar todos los servicios (con healthchecks automáticos)
docker compose up -d

# Salida esperada (volúmenes normalizados a minúsculas):
# [+] Running 5/7
#  ✓ Network app  Created
#  ✓ Network ia_internal  Created
#  ✓ Volume "crm_whatsapp_db_data"  Created
#  ✓ Volume "crm_whatsapp_redis_data"  Created
#  ✓ Volume "crm_whatsapp_ollama_models"  Created
#  ✓ Container crm_db  Started
#  ✓ Container crm_redis  Started
#  ✓ Container crm_ia  Started
#  ✓ Container crm_api  Started
#  ✓ Container crm_rag_worker  Started
#  ✓ Container crm_sentiment_worker  Started
```

### Paso 2: Monitorear logs de arranque

```bash
# Ver logs de todos los servicios
docker compose logs -f

# Logs específicos de la API (mostrar últimas 50 líneas)
docker compose logs -f api --tail=50

# Logs del contenedor IA (Ollama)
docker compose logs -f ia --tail=50
```

**Esperar a que aparezcan líneas como:**

```
crm_api | [INFO] Application startup complete
ia | Listening on http://0.0.0.0:11434
redis | Ready to accept connections
db | LOG: database system is ready to accept connections
```

---

## Verificación de salud

### Comando rápido: Estado de contenedores

```bash
docker compose ps

# Salida esperada: todos con "Up" y "(healthy)"
# CONTAINER ID   IMAGE              STATUS              ...
# ...            pgvector:pg16      Up 2m (healthy)
# ...            redis:7-alpine     Up 2m (healthy)
# ...            ollama:latest      Up 2m (healthy)
# ...            fastapi:...        Up 2m (healthy)
```

### Healthcheck endpoints

```bash
# Health check básico de la API
curl -s http://localhost:8000/healthz | jq .

# Salida esperada (JSON):
# {
#   "status": "ok",
#   "timestamp": "2026-09-18T15:30:00Z"
# }

# Readiness check (incluye dependencias: BD, Redis, Ollama)
curl -s http://localhost:8000/readyz | jq .

# Salida esperada:
# {
#   "ready": true,
#   "db": "ok",
#   "redis": "ok",
#   "ollama": "ok"
# }
```

### Verificar servicios individuales

```bash
# PostgreSQL: Check de conexión
docker compose exec db pg_isready -U postgres -d omnicore_ai
# Salida esperada: "accepting connections"

# Redis: PING
docker compose exec redis redis-cli ping
# Salida esperada: "PONG"

# Ollama: Listar modelos disponibles
docker compose exec ia curl -s http://localhost:11434/api/tags | jq .
# Salida esperada: { "models": [] } hasta que se descarguen los modelos
```

---

## Descarga de modelos locales

### Modelos necesarios

Dos modelos se ejecutan en el contenedor Ollama:

1. **`qwen2.5:7b-instruct`** — LLM para borradores RAG y sentimiento.
   - Tamaño: ~4.7 GB
   - Lenguaje: español/inglés de buena calidad.
   - Alternativa CPU Q4: `qwen2.5:7b-instruct-q4_1` (~2.4 GB, ~15–30 s por consulta en CPU).

2. **`nomic-embed-text`** — Embeddings locales para RAG.
   - Tamaño: ~274 MB
   - Dimensionalidad: 384D
   - Velocidad: muy rápido (ms por embedding).

### Descarga dentro del contenedor Ollama

**IMPORTANTE:** Los modelos se descargan DENTRO del contenedor, nunca en el host. No se ejecutan en tiempo de build de la imagen Docker (esto causaría egress bloqueado durante el build). En su lugar, se descargan al arrancar por primera vez.

```bash
# Descargar el LLM principal (ejecutar DENTRO del contenedor ia)
docker compose exec ia ollama pull qwen2.5:7b-instruct

# Salida esperada:
# pulling manifest
# pulling 8c547a56e837... 100% ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
# pulling 42901d5c5f6f... 100% ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
# ...
# success
```

**Tiempo estimado:**
- GPU (CUDA 11.8+): ~5–10 minutos.
- CPU: ~20–45 minutos (dependiendo del ancho de banda y almacenamiento).

```bash
# Descargar embeddings
docker compose exec ia ollama pull nomic-embed-text

# Salida esperada: "success" tras completar los layers
```

### Verificar modelos descargados

```bash
# Listar modelos en Ollama
docker compose exec ia curl -s http://localhost:11434/api/tags | jq '.models[] | {name: .name, size: .size}'

# Salida esperada:
# {
#   "name": "qwen2.5:7b-instruct",
#   "size": 4700000000
# }
# {
#   "name": "nomic-embed-text",
#   "size": 274000000
# }
```

### Usar modelo alternativo (CPU Q4)

Si el hardware no tiene GPU suficiente, usar:

```bash
# En .env, cambiar:
OLLAMA_MODEL=qwen2.5:7b-instruct-q4_1

# Descargar el modelo Q4 (más pequeño, CPU-friendly)
docker compose exec ia ollama pull qwen2.5:7b-instruct-q4_1
```

**Impacto en latencia:**
- GPU: RAG p95 ~6 s.
- CPU Q4: RAG p95 ~15–30 s (degradación documentada; aceptable para piloto).

---

## Migraciones de BD e inicialización

### Ejecutar migraciones (Alembic)

Las migraciones de esquema se ejecutan una sola vez al arrancar. Si la BD está vacía:

```bash
# Opción 1: Dentro del contenedor API (recomendado)
docker compose exec api alembic upgrade head

# Salida esperada:
# INFO [alembic.runtime.migration] Context impl PostgresqlImpl.
# INFO [alembic.runtime.migration] Will assume transactional DDL.
# INFO [alembic.runtime.migration] Running upgrade -> (fecha), Create tables...
# (varias líneas de "upgrade")
```

**Nota:** Si `docker-compose.yml` incluye un script de entrada que ejecuta migraciones automáticamente, NO es necesario correr este comando manualmente.

### Seed de datos iniciales (tenant demo)

```bash
# Opción: Ejecutar script de seed dentro del contenedor
docker compose exec api python -m app.scripts.seed_demo_tenant

# Salida esperada:
# [INFO] Creando tenant demo...
# [INFO] Creando usuario demo@demo.local...
# [INFO] Tenant y usuario creados exitosamente.
```

**Usuario de demostración creado:**
- Tenant slug: `demo`
- Email: `agente@demo.local`
- Contraseña: (generada aleatoriamente, ver logs)

---

## Verificación de "cero externos"

### Script de auditoría backend

Verificar que el código backend NO contiene referencias a APIs externas de IA:

```bash
# Ejecutar desde la raíz del proyecto
bash backend/check-externos-backend.sh

# Salida esperada (todos los checks en verde):
# ✓ APROBADO: cero referencias a APIs externas de IA
```

**¿Qué verifica?**
- URLs prohibidas (OpenAI, Anthropic, Google, etc.) en código/config.
- SDKs de IA de terceros en `requirements.txt`.
- Imports prohibidos en código Python.
- Red `ia_internal` con `internal: true` (bloquea egress).
- Variables `OLLAMA_BASE_URL` apuntando a hosts internos permitidos.

### Prueba de egress bloqueado (manual)

Verificar que el contenedor Ollama **NO puede alcanzar internet:**

```bash
# Intenta alcanzar un dominio externo desde el contenedor ia
docker exec crm_ia wget -T5 -qO- http://1.1.1.1 2>&1 && echo "FALLO: egress desbloqueado" || echo "✓ EGRESS BLOQUEADO (timeout o error de conexión)"

# Salida esperada: timeout o "Cannot assign requested address" (No hay gateway a internet)
```

**Alternativa con curl (si disponible en la imagen Ollama):**

```bash
docker exec crm_ia timeout 5 curl -v https://api.openai.com 2>&1 | head -3
# Salida esperada: timeout o error de conexión (NO conexión exitosa)
```

---

## Acceso a endpoints

### OpenAPI / Swagger UI

Una vez que la API está saludable, acceder a la documentación interactiva:

```
http://localhost:8000/docs
```

**Usuarios y endpoints disponibles:**
- **Health checks:** `GET /healthz`, `GET /readyz` (sin autenticación)
- **Autenticación:** `POST /api/v1/auth/login` (con credenciales del seed)
- **Conversaciones:** `GET /api/v1/conversations`, `POST /api/v1/conversations`
- **Contactos:** `GET /api/v1/contacts`, `POST /api/v1/contacts`
- **RAG:** `POST /api/v1/rag/draft` (generar borrador con contexto)
- **Métricas:** `GET /metrics` (Prometheus)

### Curl de ejemplo: Login

```bash
# Login con usuario del seed
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_slug": "demo",
    "email": "agente@demo.local",
    "password": "tu-contraseña-del-seed"
  }' | jq .

# Salida esperada:
# {
#   "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
#   "token_type": "bearer"
# }
```

### WebSocket: Chat en tiempo real

Acceso a la WebSocket para chat bidireccional:

```
ws://localhost:8000/api/v1/ws-chat?conversation_id=<id>&token=<JWT>
```

(Consultar `EXAMPLES_OPENAPI.json` para un cliente JavaScript de ejemplo.)

---

## Parada de servicios

### Detener todo (contenedores permanecen, volúmenes persisten)

```bash
docker compose stop

# Salida esperada:
# [+] Stopping 7/7
#  ✓ Container crm_sentiment_worker  Stopped
#  ✓ Container crm_rag_worker  Stopped
#  ✓ Container crm_api  Stopped
#  ✓ Container crm_ia  Stopped
#  ✓ Container crm_redis  Stopped
#  ✓ Container crm_db  Stopped
```

### Remover contenedores pero conservar volúmenes

```bash
# Útil para un reinicio limpio sin perder datos
docker compose down

# Salida esperada:
# [+] Removing 7/7
#  ✓ Container crm_sentiment_worker  Removed
#  ✓ Container crm_rag_worker  Removed
#  ✓ Container crm_api  Removed
#  ✓ Container crm_ia  Removed
#  ✓ Container crm_redis  Removed
#  ✓ Container crm_db  Removed
#  ✓ Network app  Removed
#  ✓ Network ia_internal  Removed
```

**Los volúmenes (`crm_whatsapp_db_data`, `crm_whatsapp_redis_data`, `crm_whatsapp_ollama_models`) permanecen** — datos no se pierden.

### Remover TODO incluyendo volúmenes (peligroso)

```bash
# CUIDADO: Borra BD, Redis, modelos Ollama — requiere re-descargar modelos
docker compose down -v
```

---

## Notas sobre hardware y degradación CPU

### Recomendación de GPU

**Óptimo:** GPU NVIDIA con ≥16 GB VRAM (p. ej. A100, L40, RTX 4090).
- RAG p95: ~6 s (LLM 7B fp16).
- Latencia: aceptable para IA asíncrona (human-in-the-loop).

**Fallback CPU:** Sin GPU o VRAM limitada.
- Usar modelo Q4 (cuantización 4 bits): `qwen2.5:7b-instruct-q4_1`.
- RAG p95: ~15–30 s (CPU multi-núcleo, ~8 núcleos).
- Aceptable para piloto/desarrollo; NO para producción de alto volumen.

### Parametrización por variable de entorno

El modelo se configura en `.env`:

```bash
# GPU (full precision)
OLLAMA_MODEL=qwen2.5:7b-instruct

# CPU (quantized 4-bit)
OLLAMA_MODEL=qwen2.5:7b-instruct-q4_1
```

No requiere reconstruir la imagen; solo cambiar `.env` y reiniciar:

```bash
# Cambiar .env y reiniciar
nano .env
docker compose restart api rag_worker sentiment_worker
```

### Monitoreo de recursos

```bash
# Ver uso de CPU/RAM en tiempo real
docker compose stats

# Salida esperada:
# CONTAINER ID   NAME              CPU %     MEM USAGE / LIMIT
# ...            crm_api           2.3%      250MiB / 16GiB
# ...            crm_ia            78.9%     8.2GiB / 16GiB  (inferencia activa)
# ...            crm_db            1.2%      300MiB / 16GiB
```

---

## Resumen de la operación

| Paso | Comando | Tiempo | Notas |
|------|---------|--------|-------|
| 1. Preparar `.env` | `cp .env.example .env && nano .env` | 5 min | Secretos fuertes (C3) |
| 2. Validar compose | `docker compose config --quiet` | 10 s | Verifica YAML |
| 3. Arrancar | `docker compose up -d` | 30 s | Crea volúmenes, containers |
| 4. Esperar healthchecks | `docker compose ps` | 60 s | Todos `(healthy)` |
| 5. Descargar modelos | `docker compose exec ia ollama pull ...` | 20–45 min | GPU/CPU depende |
| 6. Migraciones | `docker compose exec api alembic upgrade head` | 30 s | Crea esquema BD |
| 7. Seed | `docker compose exec api python -m app.scripts.seed_demo_tenant` | 10 s | Datos ficticios |
| 8. Verificar "cero externos" | `bash backend/check-externos-backend.sh` | 10 s | Auditoría SENSIBLE |
| 9. Acceder | `curl http://localhost:8000/healthz` | 1 s | Confirmar respuesta |

**Tiempo total:** ~25–50 minutos (depende de descarga de modelos).

---

## Checkpoints aplicables

- **C2 (Borrado lógico):** todos los contactos/mensajes pueden marcarse como Inactivo (no DELETE físico).
- **C3 (Secretos):** `.env` en `.gitignore`, `.env.example` sin valores reales, fail-fast en BD/JWT si faltan o son débiles.
- **C4 (Criterios verificables):** healthchecks, `docker compose config`, `check-externos-backend.sh`.
- **C6 (Deploy sensible):** requiere aprobación del Lead; este documento es guía de procedimiento.

---

**Siguiente:** Leer `RUNBOOK.md` para procedimientos de incidentes, backups y rollback.
