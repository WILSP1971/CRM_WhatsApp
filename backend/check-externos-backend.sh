#!/bin/bash
#
# check-externos-backend.sh — Auditoría de "cero egress de inferencia" en backend
# (Equivalente a scripts/check:externos de la SPA, pero para backend)
#
# Falla el CI si encuentra:
# - URLs/dominios de APIs de inferencia externas (OpenAI, Anthropic, Google, etc.)
# - SDKs de IA de terceros (openai, anthropic, google-generativeai, etc.)
# - Endpoints de servicios remotos de inferencia
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

# Patrones PROHIBIDOS: URLs y SDKs de terceros
declare -a FORBIDDEN_URLS=(
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
)

declare -a FORBIDDEN_SDKS=(
    "openai"
    "anthropic"
    "google-generativeai"
    "google-cloud-aiplatform"
    "cohere"
    "replicate"
    "huggingface_hub"
    "together"
    "groq"
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

# Resumen
echo -e "\n${YELLOW}========================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ APROBADO: cero referencias a APIs externas de IA${NC}"
else
    echo -e "${RED}✗ RECHAZADO: se encontraron referencias prohibidas a APIs externas${NC}"
fi
echo -e "${YELLOW}========================================${NC}"

exit $EXIT_CODE
