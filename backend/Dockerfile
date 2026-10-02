# syntax=docker/dockerfile:1
#
# SPEC-080 (PLAN-011 F0): imagen de PRODUCCIÓN endurecida (usuario no-root,
# sin `--reload`, sin tests/`.env`, sin bind-mount) separada de la imagen de
# DESARROLLO que se conserva intacta (stage `development`, target por
# defecto — `docker-compose.yml` de desarrollo sigue construyendo este mismo
# Dockerfile sin pasar `target:`, por lo que su comportamiento NO cambia).
#
# Dos stages:
#   - `base`        : capa común (deps de sistema + deps Python), compartida.
#   - `development`  : (DEFAULT, conserva el comportamiento actual) root,
#                      `COPY . .` (incluye tests), `--reload`. Usado por el
#                      `docker-compose.yml` de desarrollo local sin cambios.
#   - `production`   : usuario no-root `appuser`, copia selectiva (solo
#                      `app/`, `alembic/`, `alembic.ini`, `requirements.txt`),
#                      sin tests ni `.env` (ver también `.dockerignore`),
#                      sin `--reload`, ownership correcto de los paths de
#                      escritura (audio_store, modelos, tmp).

FROM python:3.11-slim AS base

WORKDIR /app

# Dependencias del sistema
# ffmpeg: transcodificación local a OGG/Opus del clip TTS (Entregable #6,
# SPEC-069, R-88) — hallazgo de SPEC-067: NO estaba instalado (contradecía el
# supuesto de PLAN-008 de que ya venía con el stack STT; faster-whisper usa
# PyAV/FFmpeg embebido, sin binario de sistema, ver
# app/integrations/whatsapp/media_client.py). Sin egress: paquete de Debian,
# nunca invoca red en runtime.
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python (capa compartida por development y production)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Exponer puerto (definido por variable de entorno en compose)
EXPOSE 8000

# ============================================================================
# Stage: development (DEFAULT — se conserva intacto para `docker-compose.yml`
# de desarrollo local; ese compose NO declara `target:`, así que construir
# `docker build .` o `docker compose build` sigue resolviendo este stage por
# ser el ÚLTIMO definido, igual que el Dockerfile monolítico original).
# ============================================================================
FROM base AS development

# Copiar TODO el código de la aplicación (incluye tests; el bind-mount de
# `docker-compose.yml` lo sobreescribe en runtime, igual que hoy).
COPY . .

# Hacer ejecutable el script de inicialización del almacén de audio (SPEC-035)
RUN chmod +x /app/app/workers/init_audio_store.sh

# Comando por defecto: arrancar con uvicorn en modo desarrollo (--reload)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ============================================================================
# Stage: production (NUEVO, SPEC-080/RF-01): usuario no-root, sin `--reload`,
# sin tests/`.env`, sin bind-mount. Copia SELECTIVA del código de aplicación
# (nunca `COPY . .`) para que ni tests ni un `.env` presente en el build
# context terminen en la imagen, con `.dockerignore` como segunda barrera.
# ============================================================================
FROM base AS production

# Usuario de sistema no-root (grupo + usuario dedicados, sin shell de login,
# UID/GID fijos y deterministas para que el ownership de los volúmenes sea
# reproducible entre builds/hosts).
RUN groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid appuser --no-create-home --shell /usr/sbin/nologin appuser

# Copia SELECTIVA: solo lo que el runtime de producción necesita. Explícitamente
# NUNCA `COPY . .` en este stage (evita arrastrar tests/`.env`/`.git` aunque
# `.dockerignore` fallara). `scripts/` queda fuera (son herramientas de
# desarrollo/CI, no runtime; ver `backend/scripts/`).
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini

# Hacer ejecutable el script de inicialización del almacén de audio (SPEC-035)
RUN chmod +x /app/app/workers/init_audio_store.sh

# Ownership correcto de /app para el usuario no-root (código de aplicación:
# lectura/ejecución, sin necesidad de escritura salvo __pycache__ que Python
# puede regenerar en tmpfs si hiciera falta — no se escribe código en runtime).
RUN chown -R appuser:appuser /app

# Los paths de escritura en runtime (audio_store, modelos STT/Ollama, tmp) son
# VOLÚMENES montados por docker-compose.yml, no rutas de esta imagen: su
# ownership para el usuario no-root (uid:gid 1000:1000) se resuelve en
# `init_audio_store.sh` (que ahora corre con permisos de chown dirigidos al
# propio proceso no-root, ver ese script) y, para los volúmenes de modelos
# (`whisper_models`, `ollama_models`), son de solo lectura para el proceso de
# aplicación (poblados pre-deployment, ADR-009).

USER appuser

# Sin `--reload` (RF-01): modo producción, proceso único por réplica; el
# número de workers/réplicas se decide a nivel de orquestación (fuera de
# alcance de esta SPEC).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
