#!/bin/bash
# init_audio_store.sh — Inicialización del almacén de audio (SPEC-035, ADR-009)
#
# Aplica permisos mínimos (0700) al punto de montaje del volumen de audio
# antes de que el worker de STT comience a procesar. Garantiza que SOLO el
# usuario del contenedor pueda leer/escribir el audio cifrado en reposo.
#
# Ejecutado como entrypoint del stt_worker en docker-compose.yml.
#
# SPEC-080 (PLAN-011 F0, RF-05): adaptado para funcionar TANTO bajo el stage
# `development` (root, comportamiento histórico sin cambios: puede `chown`
# libremente) COMO bajo el stage `production` (usuario no-root `appuser`,
# UID:GID 1000:1000). Un volumen Docker nombrado nuevo nace `root:root`; si
# el proceso ya NO es root, no puede hacer `chown` de un path que no posee
# todavía. Por eso el script primero intenta tomar ownership (solo posible
# como root) y, si no puede (no-root sin privilegio), verifica que el path ya
# sea escribible por el usuario actual (ownership correcto pre-establecido
# fuera del contenedor, p. ej. por un paso de aprovisionamiento de producción
# que fija `chown 1000:1000` sobre el volumen antes del primer arranque) y
# falla con un mensaje explícito si no lo es — nunca degrada a permisos más
# laxos como workaround.

set -e

AUDIO_STORE_PATH="${AUDIO_STORAGE_PATH:-/audio_store}"

echo "[init_audio_store] Inicializando almacén de audio en: ${AUDIO_STORE_PATH}"

# Crear directorio si no existe (solo posible si el proceso actual ya tiene
# permiso de escritura en el padre, p. ej. root, o el volumen ya existe).
if [ ! -d "${AUDIO_STORE_PATH}" ]; then
    echo "[init_audio_store] Directorio no existe, creando: ${AUDIO_STORE_PATH}"
    mkdir -p "${AUDIO_STORE_PATH}"
fi

CURRENT_UID="$(id -u)"

# Si el proceso es root (stage `development`, o `docker run --user root`),
# conserva el comportamiento histórico: toma ownership explícito del propio
# usuario de ejecución antes de aplicar permisos. Si es no-root (stage
# `production`, `appuser`), NO puede chown un path root:root recién creado
# por Docker — se asume que el ownership ya fue fijado fuera del contenedor
# (aprovisionamiento de producción) y solo se verifica.
if [ "${CURRENT_UID}" = "0" ]; then
    echo "[init_audio_store] Ejecutando como root: fijando ownership de ${AUDIO_STORE_PATH}"
    chown "$(id -u)":"$(id -g)" "${AUDIO_STORE_PATH}"
else
    if [ ! -w "${AUDIO_STORE_PATH}" ]; then
        echo "[init_audio_store] ✗ ERROR: usuario no-root (uid=${CURRENT_UID}) sin permiso de" \
             "escritura en ${AUDIO_STORE_PATH}. El volumen debe tener ownership" \
             "correcto (uid:gid del usuario no-root de la imagen de producción)" \
             "antes del primer arranque. NO se degradan permisos como workaround."
        exit 1
    fi
    echo "[init_audio_store] Ejecutando como no-root (uid=${CURRENT_UID}): ownership ya correcto, se preserva"
fi

# Aplicar permisos mínimos (0700): SOLO owner puede leer/escribir/ejecutar.
# Funciona tanto si el owner es root (development) como el usuario no-root
# (production), siempre que el paso anterior haya garantizado la propiedad.
echo "[init_audio_store] Aplicando permisos 0700 a ${AUDIO_STORE_PATH}"
chmod 0700 "${AUDIO_STORE_PATH}"

# Verificar
if [ "$(stat -c '%a' "${AUDIO_STORE_PATH}")" = "700" ]; then
    echo "[init_audio_store] ✓ Permisos 0700 aplicados correctamente"
else
    echo "[init_audio_store] ✗ ADVERTENCIA: permisos no son 0700 (actual: $(stat -c '%a' "${AUDIO_STORE_PATH}"))"
    exit 1
fi

echo "[init_audio_store] Almacén de audio inicializado. Iniciando worker STT..."

# Pasar control al comando principal (python -m app.workers.stt_worker)
exec "$@"
