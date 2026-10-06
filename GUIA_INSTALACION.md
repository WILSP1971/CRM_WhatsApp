# Guía de instalación, configuración, implementación y ejecución — OmniCore AI

Guía única y consolidada para poner en marcha el proyecto completo (SPA + backend FastAPI + PostgreSQL + Redis + Ollama + canales WhatsApp/Instagram) en un servidor propio con Docker. Para operación 24x7, troubleshooting detallado y rotación de secretos, ver `RUNBOOK.md`; para el checklist de producción, `DEPLOYMENT_CHECKLIST.md`.

> **Proyecto SENSIBLE (`.no-externo`)**: cero CDN, cero IA externa, cero telemetría. La inferencia (LLM + embeddings) corre 100% local vía Ollama, aislada en una red Docker sin salida a internet (`ia_internal`, `internal: true`). Los únicos egress permitidos son el transporte de los canales de mensajería (`graph.facebook.com`, WhatsApp/Instagram) desde módulos acotados por código.

---

## 1. Requisitos previos

### Software

| Herramienta | Versión mínima | Uso |
|---|---|---|
| Docker + Docker Compose v2 | Docker 24+ | Backend completo (API, workers, BD, Redis, IA) |
| Node.js | 20+ | SPA (frontend) |
| npm | 10+ | SPA (frontend) |
| Git | cualquiera reciente | Clonar el repo |
| `openssl` | cualquiera | Generar secretos fuertes |
| `make` | opcional | Atajos de `Makefile` (no estrictamente necesario, se puede usar `docker compose` directo) |

### Hardware recomendado

- **CPU-only (sin GPU)**: viable para todo el proyecto. El LLM local (`qwen2.5:7b-instruct`) corre en CPU; existe fallback cuantizado Q4 más liviano (`make models-q4`) si el hardware es limitado. STT (`faster-whisper`) y TTS (`Piper`) también corren en CPU.
- **RAM**: mínimo 8 GB, recomendado 16 GB+ (el LLM + embeddings + Postgres + Redis conviven en el mismo host).
- **Almacenamiento**: al menos 15 GB libres (modelos Ollama ~5 GB, imágenes Docker, volúmenes de datos).
- **GPU** (opcional): acelera el LLM/STT si está disponible, pero el proyecto fue validado explícitamente para funcionar sin ella (ver notas de `STT_DEVICE=cpu` en `.env.example`).

### Permisos de Docker

El usuario que ejecute los comandos debe poder hablar con el daemon de Docker sin `sudo` en cada comando:

```bash
sudo usermod -aG docker "$USER"
# cerrar sesión y volver a entrar (o `newgrp docker`) para que el cambio de grupo tome efecto
docker version   # debe responder sin "permission denied"
```

---

## 2. Instalación

### 2.1. Clonar el repositorio

```bash
git clone https://github.com/WILSP1971/CRM_WhatsApp.git
cd CRM_WhatsApp
```

### 2.2. Instalar dependencias del frontend (SPA)

```bash
npm install
```

El backend **no** requiere instalación manual de dependencias Python en el host: corre siempre dentro de los contenedores Docker (la imagen se construye con `docker compose up`, que instala `backend/requirements.txt` durante el build).

---

## 3. Configuración

### 3.1. Crear el archivo `.env`

```bash
cp .env.example .env
```

`.env.example` documenta **cada variable con su propósito y nivel de sensibilidad** (579 líneas comentadas). Nunca commitear `.env` (ya está en `.gitignore`).

### 3.2. Dos modos de arranque

**Modo A — Prueba funcional rápida (sin credenciales reales de Meta/terceros):**

Dejá `ENVIRONMENT=development` (valor por defecto del `.env.example`). En este modo:
- Los secretos (`JWT_SECRET_KEY`, `DB_PASSWORD`, `WHATSAPP_*`, `INSTAGRAM_*`, etc.) usan valores de desarrollo documentados en el código si no los seteás — el backend **no aborta el arranque**.
- Los canales WhatsApp/Instagram se pueden ejercitar con los simuladores de webhook firmado (sección 6) sin necesitar cuentas reales de Meta.
- **No uses este modo para producción real** ni lo expongas a internet.

**Modo B — Producción real:**

Con `ENVIRONMENT` en cualquier valor distinto de `development`, el backend **falla rápido al arrancar (`ConfigurationError`)** si falta o es débil cualquiera de estos secretos obligatorios (checkpoint C3, fail-fast):

| Variable | Generación sugerida |
|---|---|
| `DB_PASSWORD` | `openssl rand -hex 32` |
| `DB_APP_PASSWORD` | `openssl rand -hex 32` (distinta de `DB_PASSWORD`) |
| `JWT_SECRET_KEY` | `openssl rand -hex 32` |
| `AUDIO_ENCRYPTION_KEY` | `openssl rand -base64 32` |
| `WEBHOOK_VERIFY_TOKEN` / `WEBHOOK_SECRET` | `openssl rand -hex 16` / `openssl rand -hex 32` |
| `WHATSAPP_TOKEN` / `WHATSAPP_VERIFY_TOKEN` / `WHATSAPP_APP_SECRET` | Obtenidos del panel de Meta (WhatsApp Business Platform) + `openssl rand -hex 16` para el verify token |
| `INSTAGRAM_APP_SECRET` / `INSTAGRAM_VERIFY_TOKEN` / `INSTAGRAM_PAGE_ACCESS_TOKEN` | Obtenidos del panel de Meta (ver `RUNBOOK_INSTAGRAM.md`) + `openssl rand -hex 16` para el verify token |
| `GF_SECURITY_ADMIN_PASSWORD` (Grafana) | `openssl rand -hex 32` |

**Generá estos valores directamente en el `.env` del servidor real. Nunca los pegues en un chat, nunca los commitees al repo.**

### 3.3. Bloques de configuración en `.env.example` (referencia rápida)

| Bloque | Variables clave | Obligatorio fuera de `development` |
|---|---|---|
| PostgreSQL + roles RLS | `DB_PASSWORD`, `DB_APP_PASSWORD`, `DATABASE_URL*` | Sí |
| Redis | `REDIS_URL` | No (tiene default funcional) |
| Ollama (IA local) | `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_EMBED_MODEL` | No (defaults funcionan con `make models`) |
| JWT / CORS | `JWT_SECRET_KEY`, `CORS_ORIGINS` | `JWT_SECRET_KEY` sí |
| STT/TTS + audio cifrado | `AUDIO_ENCRYPTION_KEY`, `STT_*` | `AUDIO_ENCRYPTION_KEY` sí |
| Canal WhatsApp | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | Sí (si vas a usar el canal con usuarios reales) |
| Canal Instagram | `INSTAGRAM_APP_SECRET`, `INSTAGRAM_VERIFY_TOKEN`, `INSTAGRAM_PAGE_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Sí (ídem; además requiere Meta App Review aprobado — ver `RUNBOOK_INSTAGRAM.md`) |
| Observabilidad (Prometheus/Grafana) | `GF_SECURITY_ADMIN_PASSWORD` | Sí |
| SPA (`VITE_*`) | `VITE_USE_REAL_API`, `VITE_API_BASE_URL` | No (OFF por defecto = mocks) |

### 3.4. Validar el `docker-compose.yml`

```bash
make setup
# equivalente manual:
docker compose config --quiet && echo "válido"
```

---

## 4. Implementación (arranque del stack)

### 4.1. Levantar los servicios

```bash
make up
# equivalente manual:
docker compose up -d
```

Servicios que se levantan (ver `docker-compose.yml`): `db` (Postgres 16 + pgvector), `redis`, `ia` (Ollama), `api`, `rag_worker`, `sentiment_worker`, `whatsapp_inbound_worker` / `wa_send_worker`, `instagram_inbound_worker` / `instagram_send_worker`, `stt_worker`, `tts_worker`, `recording_ingest_worker` / `recording_fetch_worker` (PBX, inerte por defecto), `voice_stt` / `voice_tts` / `voice_gateway` (VoiceBot en vivo, inerte/archivado), `caddy` (reverse proxy TLS), `prometheus` / `alertmanager` / `grafana` (observabilidad).

```bash
make logs-api   # seguir el arranque de la API
```

Salida esperada: `Application startup complete`, `Database pool opened`, `Redis client connected`.

### 4.2. Verificar salud

```bash
make health
# o individualmente:
curl -s http://localhost:8000/healthz
docker compose ps   # todos "healthy"/"running"
```

### 4.3. Migraciones de base de datos

```bash
make migrate
# equivalente: docker compose exec api alembic upgrade head
```

### 4.4. Sembrar datos de prueba (tenant demo)

```bash
make seed
# docker compose exec api python -m app.scripts.seed_demo_tenant
```

### 4.5. Descargar los modelos de IA local (Ollama)

```bash
make models        # qwen2.5:7b-instruct (LLM, ~5 GB) + nomic-embed-text (embeddings, ~274 MB)
# alternativa en hardware limitado:
make models-q4      # variante cuantizada Q4, más liviana (requiere además fijar OLLAMA_MODEL=qwen2.5:7b-instruct-q4_1 en .env)
```

Puede tardar 10-45 minutos según CPU/GPU y ancho de banda.

### 4.6. Levantar el frontend (SPA)

```bash
npm run dev     # http://localhost:5173 (modo mock por defecto, VITE_USE_REAL_API=false)
```

Para que la SPA consuma el backend real en vez de los mocks, en un `.env.local` propio de la raíz del repo:

```bash
VITE_USE_REAL_API=true
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_WS_BASE_URL=ws://localhost:8000/api/v1
```

(variables `VITE_DEV_*` documentadas en `.env.example`, usan el tenant/usuario sembrado por `make seed`).

### 4.7. Verificaciones de seguridad (proyecto SENSIBLE)

```bash
make test-egress       # confirma que el contenedor de IA NO tiene salida a internet
make check-externos    # auditoría de "cero referencias a APIs externas de IA" (backend/check-externos-backend.sh)
```

Ambos deben terminar en verde antes de considerar el entorno listo.

---

## 5. Ejecución y uso cotidiano

```bash
make ps              # estado de los contenedores
make logs             # logs de todos los servicios en vivo
make logs-api         # solo la API
make stats            # consumo de CPU/RAM por contenedor
make shell-api        # shell dentro del contenedor api
make shell-db         # psql dentro del contenedor db
make down             # parar servicios (conserva volúmenes/datos)
make clean            # BORRA TODO (BD, Redis, modelos) — pide confirmación explícita
```

Acceso:
- API: `http://localhost:8000` (docs interactivas en `/docs`, solo si `ENVIRONMENT=development`)
- SPA: `http://localhost:5173` (dev) o el build servido (`npm run preview`)
- Grafana: puerto expuesto por el servicio `grafana` (ver `docker-compose.yml`)

---

## 6. Probar los canales de mensajería sin cuentas reales de Meta

El repo incluye simuladores de webhook **firmado** (HMAC-SHA256 real, igual que el webhook real de Meta) para validar el flujo completo end-to-end sin depender de una app aprobada por Meta.

### WhatsApp

```bash
make wa-sim-challenge   # GET challenge de suscripción
make wa-sim             # POST firmado, mensaje entrante → debe encolar y responder 200
make wa-sim-dup         # mismo wamid dos veces → prueba idempotencia
make wa-sim-status      # callbacks sent→delivered→read
```

### Instagram DM

```bash
make ig-sim-challenge      # GET challenge de suscripción
make ig-sim                # POST firmado, mensaje entrante → 200 + encolado
make ig-sim-bad-signature  # firma inválida → debe responder 401
make ig-sim-dup            # mismo mid dos veces → prueba idempotencia
make ig-sim-attachment     # payload con adjunto → prueba persistencia de media_url (URL del CDN de Meta, sin descarga)
```

Después de cada simulación, revisá en la Bandeja omnicanal (frontend, con `VITE_USE_REAL_API=true`) que el mensaje aparezca con su badge de canal y que se haya propuesto un borrador de respuesta (RAG, con ≥3 citas trazables) en estado `propuesto` — **el sistema nunca envía nada automáticamente**, un agente humano debe revisar y aprobar cada respuesta antes de enviarla (invariante human-in-the-loop, sin excepciones).

> **Bloqueo externo conocido (Instagram):** sin que Meta apruebe la App Review de tu app (permisos `instagram_manage_messages`/`instagram_basic`/`pages_messaging`), solo podés intercambiar mensajes reales con cuentas de prueba (admin/tester/developer) agregadas en el Meta Dashboard — nunca con usuarios reales. Detalle completo en `RUNBOOK_INSTAGRAM.md`.

---

## 7. Siguientes pasos / producción real

1. Leer `DEPLOYMENT_CHECKLIST.md` completo antes de exponer el servidor a internet (secretos, firewall, TLS, backups, RLS, pruebas de carga, aprobación del Lead).
2. Dar de alta las apps de Meta (WhatsApp Business Platform / Instagram) siguiendo `RUNBOOK_WHATSAPP.md` / `RUNBOOK_INSTAGRAM.md`.
3. Configurar `CADDY_DOMAIN` con un dominio real para TLS automático (Let's Encrypt vía Caddy) — nunca usar `localhost` en producción.
4. Activar backups periódicos (`make backup`, o cron según `RUNBOOK.md` §Backups).
5. Revisar `OPERACION.md` para el detalle de hardware/escalado recomendado.

## Referencias

| Documento | Para qué |
|---|---|
| `README.md` | Overview general del proyecto y de la SPA |
| `OPERACION.md` | Guía de despliegue local detallada |
| `RUNBOOK.md` | Operación 24x7, troubleshooting, backups, rotación de secretos |
| `RUNBOOK_WHATSAPP.md` | Alta y operación del canal WhatsApp |
| `RUNBOOK_INSTAGRAM.md` | Alta y operación del canal Instagram DM (incluye el bloqueo de Meta App Review explicado sin edulcorar) |
| `DEPLOYMENT_CHECKLIST.md` / `DEPLOYMENT_CHECKLIST_INSTAGRAM.md` / `DEPLOYMENT_CHECKLIST_WHATSAPP.md` | Checklists de pre-flight para producción |
| `EXAMPLES_OPENAPI.md` | Ejemplos de uso de la API REST/WebSocket |
