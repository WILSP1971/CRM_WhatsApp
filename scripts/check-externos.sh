#!/usr/bin/env bash
# check-externos.sh — Verifica "cero dependencias/llamadas externas".
#
# Proyecto SENSIBLE (.no-externo): prohibido cualquier URL http(s) que apunte
# a un dominio de terceros (CDNs, Google Fonts, analytics, APIs remotas...).
# Se permite explícitamente localhost/127.0.0.1 (dev server) y rutas relativas.
#
# Uso: npm run check:externos   (o bash scripts/check-externos.sh)
# Exit 0  -> no se encontraron referencias externas.
# Exit 1  -> se encontró al menos una URL externa; imprime coincidencias.

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Directorios/archivos a inspeccionar: código fuente + HTML raíz + configs.
# Se excluyen node_modules, dist, .git y este mismo script (documenta ejemplos
# de dominios prohibidos en comentarios, no debe autodispararse).
SEARCH_PATHS=(
  "index.html"
  "src"
  "public"
  "vite.config.ts"
  "tailwind.config.ts"
)

# Patrón: http:// o https:// seguidos de un host que NO sea localhost/127.0.0.1.
PATTERN='https?://(?!localhost|127\.0\.0\.1)[a-zA-Z0-9.-]+'

EXCLUDE_GLOBS=(
  "--glob" "!**/node_modules/**"
  "--glob" "!**/dist/**"
  "--glob" "!**/*.md"
  "--glob" "!**/fonts/README.md"
)

MATCHES=""

if command -v rg >/dev/null 2>&1; then
  MATCHES="$(rg -n -P "$PATTERN" "${SEARCH_PATHS[@]}" "${EXCLUDE_GLOBS[@]}" 2>/dev/null || true)"
else
  # Fallback sin ripgrep: grep -R con soporte de -P si está disponible.
  if grep --version 2>/dev/null | grep -q GNU; then
    MATCHES="$(grep -R -n -P "$PATTERN" "${SEARCH_PATHS[@]}" \
      --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" \
      --include="*.css" --include="*.html" --include="*.json" \
      2>/dev/null | grep -v '/node_modules/' | grep -v '/dist/' || true)"
  else
    echo "check-externos: no se encontró 'rg' ni 'grep -P'; instala ripgrep para una verificación completa." >&2
    MATCHES="$(grep -R -n -E 'https?://[a-zA-Z0-9.-]+' "${SEARCH_PATHS[@]}" \
      --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" \
      --include="*.css" --include="*.html" --include="*.json" \
      2>/dev/null | grep -v '/node_modules/' | grep -v '/dist/' \
      | grep -v -E 'https?://(localhost|127\.0\.0\.1)' || true)"
  fi
fi

if [ -n "$MATCHES" ]; then
  echo "check-externos: se encontraron referencias externas prohibidas:" >&2
  echo "$MATCHES" >&2
  exit 1
fi

echo "check-externos: OK — sin referencias http(s) externas (localhost permitido)."
exit 0
