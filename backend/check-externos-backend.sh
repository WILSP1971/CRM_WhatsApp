#!/bin/bash
#
# check-externos-backend.sh — Auditoría de "cero egress de inferencia" + transporte acotado
# (Equivalente a scripts/check:externos de la SPA, pero para backend)
#
# Falla el CI si encuentra:
# - URLs/dominios de APIs de inferencia externas (OpenAI, Anthropic, Google, etc.)
# - SDKs de IA de terceros (openai, anthropic, google-generativeai, etc.)
# - Endpoints de servicios remotos de inferencia
# - graph.facebook.com FUERA del módulo de WhatsApp (ADR-006, SPEC-024)
#
# Permite:
# - graph.facebook.com DENTRO de app/integrations/whatsapp/ (transporte, no inferencia)
#
# Uso: ./backend/check-externos-backend.sh
# Retorna: 0 si OK, 1 si hay violación
#

set -e

BACKEND_DIR="${1:-.}"
EXIT_CODE=0

# ANSI colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}[check-externos-backend] Auditando backend por referencias externas de IA...${NC}"

# Patrones PROHIBIDOS: URLs y SDKs de terceros (inferencia IA + STT/TTS)
# SPEC-035/ADR-009: STT/TTS de terceros PROHIBIDOS — audio (dato personal/PHI)
# jamás a terceros. Inferencia (ADR-005) igual: solo Ollama local en ia_internal.
declare -a FORBIDDEN_URLS=(
    # Inferencia (SPEC-016, ADR-005)
    "api.openai.com"
    "api.anthropic.com"
    "generativelanguage.googleapis.com"
    "vertex.googleapis.com"
    "bedrock.amazonaws.com"
    "api.cohere.com"
    "api.replicate.com"
    "huggingface.co"
    "api.huggingface.co"
    "together.ai"
    "runwayml.com"
    "fireworks.ai"
    "groq.com"
    "api.groq.com"
    "vllm.ai"
    # STT de terceros (SPEC-035, ADR-009: STT local con faster-whisper, sin audio a terceros)
    "speech.googleapis.com"
    "transcribe.googleapis.com"
    "transcribestreaming.googleapis.com"
    "transcribe.us-east-1.amazonaws.com"
    "transcribestreaming.us-east-1.amazonaws.com"
    "api.transcribe.aws"
    "api-inference.huggingface.co"
    "api.deepgram.com"  # Deepgram STT
    "api.assemblyai.com"  # AssemblyAI
    "speech.microsoft.com"  # Azure Speech / Cognitive Services
    "api.azure.microsoft.com"
    "westus.tts.speech.microsoft.com"
    # TTS de terceros (SPEC-044, ADR-012: TTS local con Piper o pregrabado)
    "api.elevenlabs.io"
    "polly.us-east-1.amazonaws.com"
    "tts.googleapis.com"
    "texttospeech.googleapis.com"
    "api.elevenlabs.co"
    "play.ht"
    "api.playht.com"
    "api.playai.com"
    "api.deepgram.com"  # Deepgram también tiene TTS
    "api.coqui-cloud.com"
    "tts\.ai"
    "api\.mutagen\.ai"
)

declare -a FORBIDDEN_SDKS=(
    # Inferencia (SPEC-016, ADR-005)
    "openai"
    "anthropic"
    "google-generativeai"
    "google-cloud-aiplatform"
    "cohere"
    "replicate"
    "huggingface_hub"
    "together"
    "groq"
    # STT/TTS de terceros (SPEC-035, ADR-009, SPEC-044)
    "google-cloud-speech"
    "google-cloud-text-to-speech"
    "azure-cognitiveservices-speech"
    "deepgram-sdk"
    "deepgram"
    "assemblyai"
    # NOTA (WOLVERINE, corrección post SPEC-044): `boto3`/`google-auth` son
    # SDKs COMPLETOS y dependencias transitivas comunes de features no
    # relacionadas con IA (p.ej. `boto3` para S3/SES, `google-auth` para
    # OAuth). Bloquear el paquete entero aquí (`requirements.txt`/`import X`
    # literal) es desproporcionado y genera falsos positivos reales en fases
    # futuras — se eliminan de esta lista. El USO concreto peligroso
    # (`boto3` + Transcribe/Polly, `google.auth` + Speech) SÍ sigue
    # prohibido: acotado como patrón de texto libre en la sección 10
    # (`STT_TTS_FORBIDDEN_PATTERNS`, ver `boto3.*transcribe`/`boto3.*polly`/
    # `google\.auth.*speech` más abajo), que evalúa con `grep -ri` sobre todo
    # el árbol de `app/` y no depende de que el import/uso estén en la misma
    # línea de una forma rígida.
    # NOTA (WOLVERINE): `librosa`/`pyannote` son librerías de procesamiento
    # de audio 100% LOCALES y legítimas (sin egress) — `pyannote` incluso se
    # menciona en `stt_engine.py` como posible opción de diarización local
    # futura (SPEC-047). NO se prohíben por defecto. Si en el futuro se corre
    # bajo un allowlist de módulo (mismo patrón que STT/PBX en las secciones
    # 11/12 de este script: permitido SOLO dentro de
    # `app/services/telefonia/`), documentar aquí el cambio de política.
    # TTS de terceros (SPEC-044, ADR-012)
    "elevenlabs"
    "playht"
    "google-cloud-texttospeech"
    "azure-text-to-speech"
    "openai-python"
    # NOTA (WOLVERINE): `mutagen` es una librería ESTÁNDAR de metadata de
    # audio local (lectura/escritura de tags ID3, etc.), sin relación con
    # TTS de terceros. NO se prohíbe el paquete completo — el caso real de
    # preocupación (uso de `mutagen` como wrapper de un backend TTS online)
    # ya está acotado con precisión en la sección 10 (`mutagen.*tts`).
)

# Función para buscar y reportar
#
# NOTA (SPEC-016): se excluye `tests/` del escaneo de URLs/dominios externos.
# Los tests de la defensa "cero inferencia externa" (p.ej.
# `tests/test_ai_config_egress.py`) NECESITAN contener literalmente dominios
# como "api.openai.com" para verificar que `Settings`/este mismo script los
# RECHAZAN si aparecieran en código/config real — no son un uso real de esas
# APIs. El código de aplicación (`app/`) y la infraestructura
# (docker-compose.yml, requirements.txt, Dockerfile) SÍ se siguen auditando
# sin excepción.
check_pattern() {
    local pattern="$1"
    local file_type="$2"
    local violation_type="$3"

    echo -e "${YELLOW}  → Buscando ${violation_type}: '${pattern}'${NC}"

    # Buscar en archivos de código (excluyendo tests: ver nota arriba)
    if grep -r --include="${file_type}" "${pattern}" "${BACKEND_DIR}" 2>/dev/null \
        | grep -v "node_modules" | grep -v ".git" | grep -v "__pycache__" \
        | grep -v -E "(^|/)tests/"; then
        echo -e "${RED}    ✗ FALLO: encontrado '${pattern}' en ${file_type}${NC}"
        EXIT_CODE=1
    fi
}

# Comprobar URLs externas en todo el código (Python, YAML, JSON, Dockerfile)
echo -e "\n${YELLOW}1. Comprobando URLs de APIs externas de IA...${NC}"
for url in "${FORBIDDEN_URLS[@]}"; do
    check_pattern "${url}" "*.py" "URL API ${url}"
    check_pattern "${url}" "*.yml" "URL API ${url}"
    check_pattern "${url}" "*.yaml" "URL API ${url}"
    check_pattern "${url}" "*.json" "URL API ${url}"
    check_pattern "${url}" "Dockerfile" "URL API ${url}"
done

# Comprobar SDKs de terceros en requirements.txt
echo -e "\n${YELLOW}2. Comprobando SDKs de IA de terceros en requirements.txt...${NC}"
if [ -f "${BACKEND_DIR}/requirements.txt" ]; then
    for sdk in "${FORBIDDEN_SDKS[@]}"; do
        if grep -i "^${sdk}" "${BACKEND_DIR}/requirements.txt"; then
            echo -e "${RED}    ✗ FALLO: SDK prohibido '${sdk}' en requirements.txt${NC}"
            EXIT_CODE=1
        fi
    done
fi

# Comprobar imports prohibidos en código Python
echo -e "\n${YELLOW}3. Comprobando imports prohibidos en código Python...${NC}"
for sdk in "${FORBIDDEN_SDKS[@]}"; do
    if grep -r "import ${sdk}" "${BACKEND_DIR}/app" 2>/dev/null; then
        echo -e "${RED}    ✗ FALLO: import prohibido 'import ${sdk}' encontrado${NC}"
        EXIT_CODE=1
    fi
    if grep -r "from ${sdk}" "${BACKEND_DIR}/app" 2>/dev/null; then
        echo -e "${RED}    ✗ FALLO: import prohibido 'from ${sdk}' encontrado${NC}"
        EXIT_CODE=1
    fi
done

# Comprobar que Ollama es la UNICA solución de IA
echo -e "\n${YELLOW}4. Verificando que Ollama es la única solución de IA local...${NC}"
if grep -r "OLLAMA" "${BACKEND_DIR}/app" 2>/dev/null | grep -q "OLLAMA_BASE_URL\|OLLAMA_MODEL"; then
    echo -e "${GREEN}    ✓ OK: Ollama está configurado como IA local${NC}"
else
    echo -e "${YELLOW}    ⚠ AVISO: Ollama no encontrado en configuración (puede ser intencional si aún no hay lógica de IA)${NC}"
fi

# Comprobar que docker-compose.yml (en raíz del proyecto) tiene ia_internal con internal: true
echo -e "\n${YELLOW}5. Verificando que docker-compose.yml tiene red ia_internal con internal: true...${NC}"
DC_FILE=$(find . -name "docker-compose.yml" -type f 2>/dev/null | head -1)
if [ -z "$DC_FILE" ]; then
    # Buscar en la raíz (asumiendo que el script se ejecuta desde el backend)
    DC_FILE="docker-compose.yml"
    if [ ! -f "$DC_FILE" ]; then
        DC_FILE="../docker-compose.yml"
    fi
fi

if [ -f "$DC_FILE" ]; then
    if grep -q "ia_internal:" "$DC_FILE" && grep -A5 "ia_internal:" "$DC_FILE" | grep -q "internal: true"; then
        echo -e "${GREEN}    ✓ OK: Red ia_internal tiene internal: true (egress bloqueado)${NC}"
    else
        echo -e "${RED}    ✗ FALLO: Red ia_internal NO tiene 'internal: true' — PERMITE EGRESS A INTERNET${NC}"
        EXIT_CODE=1
    fi
else
    echo -e "${RED}    ✗ FALLO: docker-compose.yml no encontrado (no se puede validar egress bloqueado)${NC}"
    EXIT_CODE=1
fi

# Comprobar que OLLAMA_BASE_URL/AI_BASE_URL (si aparecen en .env.example o
# docker-compose.yml) apuntan SOLO a un host interno permitido (SPEC-016,
# ADR-005 defensa en profundidad). Un valor que no sea el servicio Docker
# `ia` ni loopback se considera fuga potencial de egress de inferencia.
echo -e "\n${YELLOW}6. Verificando que OLLAMA_BASE_URL/AI_BASE_URL apuntan a host interno...${NC}"
ALLOWED_AI_HOST_REGEX='^(http|https)://(ia|localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:[0-9]+)?/?$'

check_ai_base_url_file() {
    local file="$1"
    [ -f "$file" ] || return 0
    local matches
    matches=$(grep -E '^\s*(OLLAMA_BASE_URL|AI_BASE_URL)\s*[:=]' "$file" 2>/dev/null || true)
    [ -z "$matches" ] && return 0
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        # Extrae el valor tras el primer '=' o ':' (soporta .env y YAML "KEY: value")
        local value
        value=$(echo "$line" | sed -E 's/^[^:=]+[:=][[:space:]]*//' | tr -d '"'"'"'' | sed -E 's/[[:space:]]+#.*$//' | tr -d '[:space:]')
        # Ignora referencias a variables de entorno (${VAR}) sin valor literal
        if [[ "$value" == *'${'* ]] || [ -z "$value" ]; then
            continue
        fi
        if [[ ! "$value" =~ $ALLOWED_AI_HOST_REGEX ]]; then
            echo -e "${RED}    ✗ FALLO: '${line}' en ${file} NO apunta a un host interno permitido${NC}"
            EXIT_CODE=1
        else
            echo -e "${GREEN}    ✓ OK: '${line}' en ${file} apunta a host interno${NC}"
        fi
    done <<< "$matches"
}

check_ai_base_url_file "${BACKEND_DIR}/.env.example"
check_ai_base_url_file "$(dirname "${BACKEND_DIR}")/.env.example"
check_ai_base_url_file "${DC_FILE:-docker-compose.yml}"

# Auditoría de transporte acotado (SPEC-024/SPEC-054, ADR-006): graph.facebook.com
# SOLO en módulo WhatsApp. Estado real (corrección BLACK WIDOW post SPEC-054): el
# módulo WhatsApp YA NO es un placeholder — `graph_client.py` (envío, SPEC-024/029)
# y `media_client.py` (descarga de media entrante, SPEC-054) contienen
# `graph.facebook.com` real. Esta sección verifica ACTIVAMENTE contra el código
# real (no por vacuidad) con el MISMO estilo de allowlist por ruta con
# grep/allowlist que las secciones 11/12 (PBX) de este script.
echo -e "\n${YELLOW}7. Verificando allowlist por ruta de graph.facebook.com (SOLO en módulo WhatsApp, SPEC-024/054, ADR-006)...${NC}"

GRAPH_ALLOWED_MODULES=(
    "app/integrations/whatsapp"
)
GRAPH_ALLOWED_PATH_REGEX=$(IFS='|'; echo "${GRAPH_ALLOWED_MODULES[*]}")

GRAPH_VIOLATION=0
matches=$(grep -r "graph\.facebook\.com" "${BACKEND_DIR}/app" 2>/dev/null | grep -v "__pycache__" || true)

if [ -n "$matches" ]; then
    outside_whatsapp=$(echo "$matches" | grep -vE "${GRAPH_ALLOWED_PATH_REGEX}" || true)

    if [ -n "$outside_whatsapp" ]; then
        echo -e "${RED}    ✗ FALLO: graph.facebook.com encontrado FUERA del módulo WhatsApp (debe estar SOLO en ${GRAPH_ALLOWED_MODULES[*]}):${NC}"
        echo "$outside_whatsapp" | sed 's/^/      /'
        GRAPH_VIOLATION=1
    else
        echo -e "${GREEN}    ✓ OK: graph.facebook.com solo en ${GRAPH_ALLOWED_MODULES[*]} (transporte real: graph_client.py envío SPEC-024/029, media_client.py descarga SPEC-054)${NC}"
    fi
else
    # No debería ocurrir hoy (el módulo ya tiene transporte real, no placeholder);
    # se deja como aviso, no como fallo, por si el código se reestructura.
    echo -e "${YELLOW}    ⚠ AVISO: graph.facebook.com no aparece en código (inesperado: el módulo ya no es placeholder desde SPEC-024/054)${NC}"
fi

if [ $GRAPH_VIOLATION -ne 0 ]; then
    EXIT_CODE=1
fi

# Verificar que el módulo de STT/IA NO importa el cliente de descarga de media de
# WhatsApp (RF-05 SPEC-054, ADR-009: el STT nunca descarga, solo lee del almacén
# ya poblado por `media_client.py`). Mismo estilo de verificación activa que la
# comprobación de PBX en la sección 11 (STT_IA_MODULES).
echo -e "\n${YELLOW}    → Verificando que STT/IA NO importan el cliente de descarga de media de WhatsApp (SPEC-054, ADR-009)...${NC}"
declare -a MEDIA_CLIENT_FORBIDDEN_IMPORT_MODULES=(
    "${BACKEND_DIR}/app/workers/stt_worker.py"
    "${BACKEND_DIR}/app/workers/sentiment_worker.py"
    "${BACKEND_DIR}/app/workers/rag_ingest_worker.py"
    "${BACKEND_DIR}/app/services/rag"
)

for mod in "${MEDIA_CLIENT_FORBIDDEN_IMPORT_MODULES[@]}"; do
    if [ -f "$mod" ] || [ -d "$mod" ]; then
        if grep -rE "media_client|download_and_store_voice_note|GraphMediaClient" "$mod" 2>/dev/null | grep -v "__pycache__"; then
            echo -e "${RED}    ✗ FALLO: módulo de STT/IA importa/referencia el cliente de descarga de media de WhatsApp (prohibido, RF-05 SPEC-054, ADR-009):${NC}"
            GRAPH_VIOLATION=1
        fi
    fi
done

if [ $GRAPH_VIOLATION -eq 0 ]; then
    echo -e "${GREEN}    ✓ OK: media_client/download_and_store_voice_note/GraphMediaClient NO son importables desde STT/IA (SPEC-054, ADR-009)${NC}"
else
    EXIT_CODE=1
fi

# Verificar que el módulo WhatsApp NO importe Ollama ni servicios de IA (separación: transporte ≠ inferencia)
echo -e "\n${YELLOW}8. Verificando que módulo WhatsApp NO importa Ollama ni IA...${NC}"
WHATSAPP_MODULE="${BACKEND_DIR}/app/integrations/whatsapp"
if [ -d "$WHATSAPP_MODULE" ]; then
    # Patrones prohibidos dentro del módulo WhatsApp
    declare -a WHATSAPP_FORBIDDEN_IMPORTS=(
        "from.*ollama"
        "import ollama"
        "from.*ai_client"
        "from.*app.services.rag"
        "from.*app.workers"
    )

    WHATSAPP_VIOLATION=0
    for pattern in "${WHATSAPP_FORBIDDEN_IMPORTS[@]}"; do
        if grep -r "$pattern" "$WHATSAPP_MODULE" 2>/dev/null | grep -v "__pycache__"; then
            echo -e "${RED}    ✗ FALLO: patrón prohibido '$pattern' encontrado en módulo WhatsApp${NC}"
            WHATSAPP_VIOLATION=1
        fi
    done

    if [ $WHATSAPP_VIOLATION -eq 0 ]; then
        echo -e "${GREEN}    ✓ OK: módulo WhatsApp no tiene imports de IA (separación de responsabilidades: graph_client.py/media_client.py son transporte puro, SPEC-024/054)${NC}"
    else
        EXIT_CODE=1
    fi
else
    # Estado real (corrección BLACK WIDOW): el módulo WhatsApp existe desde
    # SPEC-024 y ya no es un placeholder — esta rama documenta el caso
    # defensivo (directorio ausente), no el estado esperado del proyecto.
    echo -e "${RED}    ✗ FALLO: módulo WhatsApp (${WHATSAPP_MODULE}) no existe — inesperado desde SPEC-024${NC}"
    EXIT_CODE=1
fi

# Verificar que módulos de IA NO importen httpx ni clientes HTTP de transporte a Meta
echo -e "\n${YELLOW}9. Verificando que módulos de IA NO importan httpx (transporte)...${NC}"
declare -a IA_MODULES=(
    "${BACKEND_DIR}/app/services/rag"
    "${BACKEND_DIR}/app/workers"
)

for ia_mod in "${IA_MODULES[@]}"; do
    if [ -d "$ia_mod" ]; then
        if grep -r "import httpx\|from httpx" "$ia_mod" 2>/dev/null | grep -v "__pycache__"; then
            echo -e "${RED}    ✗ FALLO: import httpx encontrado en módulo de IA $ia_mod (salida no permitida)${NC}"
            EXIT_CODE=1
        fi
    fi
done

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}    ✓ OK: módulos de IA no importan httpx (sin egress a Meta)${NC}"
fi

# SPEC-035/ADR-009: STT/TTS de terceros PROHIBIDOS — test negativo
# SPEC-044: extiende con TTS de terceros (ElevenLabs, AWS Polly, Google TTS, Azure Speech TTS,
# OpenAI TTS, Coqui-cloud, PlayHT, Deepgram TTS, etc.)
echo -e "\n${YELLOW}10. Verificando STT/TTS de terceros (SPEC-035, SPEC-044, ADR-009)...${NC}"
declare -a STT_TTS_FORBIDDEN_PATTERNS=(
    # STT de terceros (SPEC-035)
    "deepgram"
    "assemblyai"
    "google.*speech"
    "aws.*transcribe"
    "boto3.*transcribe"  # AWS SDK boto3 + submódulo Transcribe (WOLVERINE: boto3 completo ya no está en FORBIDDEN_SDKS)
    "transcribestreaming"
    "speech.microsoft.com"
    "azure.*cognitive.*speech"
    "openai.*whisper"
    "faster.whisper.*remote"  # Si existe un client remoto (prohibido)

    # TTS de terceros (SPEC-044, ADR-012: audio local solo)
    "elevenlabs"
    # NOTA (WOLVERINE, corrección post SPEC-044): se eliminó el patrón suelto
    # "polly" (sin acotar) — coincidía con cualquier subcadena "polly" en
    # nombres propios/variables legítimos (falso positivo confirmado:
    # `echo "polly_gonzalez_field = 1" | grep -i polly` da match). Ya está
    # cubierto con precisión por "aws.*polly" (línea de abajo).
    "aws.*polly"
    "boto3.*polly"  # AWS SDK boto3 + submódulo Polly (WOLVERINE: boto3 completo ya no está en FORBIDDEN_SDKS)
    "google.*texttospeech"
    "texttospeech"
    "openai.*audio.*speech"
    "openai.*tts"
    "azure.*speech.*synthesize"
    "azure.*cognitiveservices.*speech"
    "playht"
    "deepgram.*tts"
    "coqui.*cloud"
    "tts\.ai"  # Punto escapado (WOLVERINE): sin escapar coincidía con "xttsyai", etc.
    "mutagen.*tts"
    "pyttsx3.*online"  # Si se usa versión con backend online
)

STT_VIOLATION=0
for pattern in "${STT_TTS_FORBIDDEN_PATTERNS[@]}"; do
    if grep -ri "$pattern" "${BACKEND_DIR}/app" 2>/dev/null | grep -v "__pycache__" | grep -v "\.pyc"; then
        echo -e "${RED}    ✗ FALLO: patrón STT/TTS prohibido '$pattern' detectado en código de aplicación${NC}"
        grep -ri "$pattern" "${BACKEND_DIR}/app" 2>/dev/null | grep -v "__pycache__" | sed 's/^/      /'
        STT_VIOLATION=1
    fi
done

if [ $STT_VIOLATION -eq 0 ]; then
    echo -e "${GREEN}    ✓ OK: STT/TTS de terceros no encontrados (solo local con faster-whisper, ADR-009)${NC}"
else
    EXIT_CODE=1
fi

# SPEC-035/ADR-010: Allowlist por RUTA del host del PBX (si PBX externo)
# El host del PBX se permite SOLO dentro de:
# - app/services/telefonia/ (app/integrations/pbx, app/integrations/recording):
#   transporte de descarga real (cliente HTTP que hace la petición al PBX).
# - app/core/config.py: fuente de verdad de `Settings` (mismo patrón que
#   TODAS las demás variables de entorno del proyecto — WHATSAPP_TOKEN,
#   JWT_SECRET_KEY, etc. — se leen y documentan en `config.py`; no es el
#   cliente de transporte).
# - app/workers/recording_fetch_worker.py: SOLO referencia
#   `settings.pbx_external_host` para logging/diagnóstico (arranque y logs
#   informativos); la petición HTTP real está delegada exclusivamente a
#   `app/services/telefonia/pbx_client.download_recording` (ADR-010).
# Si el host/variable aparece fuera de estos módulos, falla el CI. STT/IA
# nunca lo importa (verificado por separado más abajo).
echo -e "\n${YELLOW}11. Verificando allowlist por ruta del host del PBX (SPEC-035, ADR-010)...${NC}"

PBX_ALLOWED_MODULES=(
    "app/services/telefonia"
    "app/integrations/pbx"
    "app/integrations/recording"
    "app/core/config\.py"
    "app/workers/recording_fetch_worker\.py"
)

# Busca referencias de credenciales/host del PBX (patrones como PBX_HOST,
# ASTERISK_HOST, FRESWITCH_HOST, PBX_EXTERNAL_HOST -variable real usada por
# SPEC-037/pbx_client.py/config.py-, etc.)
PBX_HOST_PATTERNS=(
    "PBX_HOST"
    "PBX_EXTERNAL_HOST"
    "pbx_external_host"
    "ASTERISK_HOST"
    "FRESWITCH_HOST"
    "PBX_URL"
    "PBX_IP"
    "pbx_host"
    "asterisk"
    "freswitch"
)

# Patrón único alternado (en vez de encadenar múltiples `-v -E` vía `eval`,
# que hace que grep interprete los patrones intermedios como RUTAS DE FICHERO
# inexistentes, falla con código de error, y con el `|| true` de abajo la
# violación real queda enmascarada — bug detectado por BLACK WIDOW).
PBX_ALLOWED_PATH_REGEX=$(IFS='|'; echo "${PBX_ALLOWED_MODULES[*]}")

PBX_VIOLATION=0
for pattern in "${PBX_HOST_PATTERNS[@]}"; do
    matches=$(grep -r "$pattern" "${BACKEND_DIR}/app" 2>/dev/null | grep -v "__pycache__" || true)

    if [ -n "$matches" ]; then
        # Si encontró referencias, verifica que todas estén en módulos permitidos
        outside_allowed=$(echo "$matches" | grep -vE "${PBX_ALLOWED_PATH_REGEX}" || true)

        if [ -n "$outside_allowed" ]; then
            echo -e "${RED}    ✗ FALLO: ${pattern} encontrado FUERA de módulos permitidos (debe estar SOLO en ${PBX_ALLOWED_MODULES[*]}):${NC}"
            echo "$outside_allowed" | sed 's/^/      /'
            PBX_VIOLATION=1
        fi
    fi
done

# STT/IA que importan cliente de descarga del PBX (prohibido)
echo -e "\n${YELLOW}    → Verificando que STT/IA NO importan cliente de descarga del PBX...${NC}"
declare -a STT_IA_MODULES=(
    "${BACKEND_DIR}/app/workers/stt_worker.py"
    "${BACKEND_DIR}/app/workers/sentiment_worker.py"
    "${BACKEND_DIR}/app/workers/rag_ingest_worker.py"
    "${BACKEND_DIR}/app/services/rag"
)

for mod in "${STT_IA_MODULES[@]}"; do
    if [ -f "$mod" ] || [ -d "$mod" ]; then
        if grep -r "pbx\|PBX\|asterisk\|freswitch\|recording.*fetch\|download.*pbx" "$mod" 2>/dev/null | grep -v "__pycache__"; then
            echo -e "${RED}    ✗ FALLO: STT/IA módulo importa/llama a descarga del PBX (prohibido, ADR-010):${NC}"
            PBX_VIOLATION=1
        fi
    fi
done

if [ $PBX_VIOLATION -eq 0 ]; then
    echo -e "${GREEN}    ✓ OK: allowlist por ruta del PBX respetado (SOLO en módulos de transporte, ADR-010)${NC}"
else
    EXIT_CODE=1
fi

# SPEC-044/ADR-011: Allowlist por RUTA del host del PBX de MEDIA en vivo (si PBX externo)
# El host del PBX de media (para voz en vivo, SIP/media) se permite SOLO dentro de:
# - app/integrations/voice_gateway/ o app/services/telefonia/ (conector SIP/media en vivo)
# - app/core/config.py (fuente de verdad de `Settings`)
# - app/workers/voice_gateway.py (si existiera como worker, SPEC-046)
# Si el host/variable aparece fuera de estos módulos (ej. en stt_worker, voice_stt, voice_tts),
# falla el CI (violación de seguridad: audio/inferencia exponiendo credenciales del PBX).
echo -e "\n${YELLOW}12. Verificando allowlist por ruta del host del PBX de MEDIA (SPEC-044, ADR-011)...${NC}"

PBX_MEDIA_ALLOWED_MODULES=(
    "app/services/telefonia"
    "app/integrations/voice_gateway"
    "app/core/config\.py"
)

# Patrones de variables/referencias del PBX de media
PBX_MEDIA_HOST_PATTERNS=(
    "PBX_MEDIA_HOST"
    "pbx_media_host"
    "PBX_MEDIA_PORT"
    "pbx_media_port"
    "PBX_MEDIA_AUTH"
    "pbx_media_auth"
)

PBX_MEDIA_ALLOWED_PATH_REGEX=$(IFS='|'; echo "${PBX_MEDIA_ALLOWED_MODULES[*]}")

PBX_MEDIA_VIOLATION=0
for pattern in "${PBX_MEDIA_HOST_PATTERNS[@]}"; do
    matches=$(grep -r "$pattern" "${BACKEND_DIR}/app" 2>/dev/null | grep -v "__pycache__" || true)

    if [ -n "$matches" ]; then
        # Si encontró referencias, verifica que todas estén en módulos permitidos
        outside_allowed=$(echo "$matches" | grep -vE "${PBX_MEDIA_ALLOWED_PATH_REGEX}" || true)

        if [ -n "$outside_allowed" ]; then
            echo -e "${RED}    ✗ FALLO: ${pattern} encontrado FUERA de módulos permitidos (debe estar SOLO en ${PBX_MEDIA_ALLOWED_MODULES[*]}):${NC}"
            echo "$outside_allowed" | sed 's/^/      /'
            PBX_MEDIA_VIOLATION=1
        fi
    fi
done

# Verificar que voice_stt, voice_tts, NLU NO importan cliente de transporte del PBX de media
echo -e "\n${YELLOW}    → Verificando que voice_stt/voice_tts/NLU NO importan cliente de PBX de media...${NC}"
declare -a VOICE_MODULES=(
    "${BACKEND_DIR}/app/services/telefonia/voice_stt.py"
    "${BACKEND_DIR}/app/services/telefonia/voice_tts.py"
    "${BACKEND_DIR}/app/workers/stt_worker.py"
    "${BACKEND_DIR}/app/workers/sentiment_worker.py"
    "${BACKEND_DIR}/app/workers/rag_ingest_worker.py"
)

for mod in "${VOICE_MODULES[@]}"; do
    if [ -f "$mod" ] || [ -d "$mod" ]; then
        if grep -r "PBX_MEDIA\|pbx_media\|voice_gateway\|media.*pbx" "$mod" 2>/dev/null | grep -v "__pycache__"; then
            echo -e "${RED}    ✗ FALLO: módulo de voz/IA menciona PBX de media (prohibido, debe estar solo en voice_gateway, ADR-011):${NC}"
            PBX_MEDIA_VIOLATION=1
        fi
    fi
done

if [ $PBX_MEDIA_VIOLATION -eq 0 ]; then
    echo -e "${GREEN}    ✓ OK: allowlist por ruta del PBX de media respetado (SOLO en voice_gateway, ADR-011)${NC}"
else
    EXIT_CODE=1
fi

# Resumen
echo -e "\n${YELLOW}========================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ APROBADO: cero referencias a APIs externas de IA${NC}"
else
    echo -e "${RED}✗ RECHAZADO: se encontraron referencias prohibidas a APIs externas${NC}"
fi
echo -e "${YELLOW}========================================${NC}"

exit $EXIT_CODE
