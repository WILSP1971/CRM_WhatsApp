#!/bin/bash
# init_audio_store.sh — Inicialización del almacén de audio (SPEC-035, ADR-009)
#
# Aplica permisos mínimos (0700) al punto de montaje del volumen de audio
# antes de que el worker de STT comience a procesar. Garantiza que SOLO el
# usuario del contenedor pueda leer/escribir el audio cifrado en reposo.
#
# Ejecutado como entrypoint del stt_worker en docker-compose.yml.

set -e

AUDIO_STORE_PATH="${AUDIO_STORAGE_PATH:-/audio_store}"

echo "[init_audio_store] Inicializando almacén de audio en: ${AUDIO_STORE_PATH}"

# Crear directorio si no existe
if [ ! -d "${AUDIO_STORE_PATH}" ]; then
    echo "[init_audio_store] Directorio no existe, creando: ${AUDIO_STORE_PATH}"
    mkdir -p "${AUDIO_STORE_PATH}"
fi

# Aplicar permisos mínimos (0700): SOLO owner (root en contenedor) puede leer/escribir/ejecutar
echo "[init_audio_store] Aplicando permisos 0700 a ${AUDIO_STORE_PATH}"
chmod 0700 "${AUDIO_STORE_PATH}"

# Verificar
if [ $(stat -c '%a' "${AUDIO_STORE_PATH}") = "700" ]; then
    echo "[init_audio_store] ✓ Permisos 0700 aplicados correctamente"
else
    echo "[init_audio_store] ✗ ADVERTENCIA: permisos no son 0700 (actual: $(stat -c '%a' "${AUDIO_STORE_PATH}"))"
    exit 1
fi

echo "[init_audio_store] Almacén de audio inicializado. Iniciando worker STT..."

# Pasar control al comando principal (python -m app.workers.stt_worker)
exec "$@"
