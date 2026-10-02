#!/usr/bin/env bash
#
# firewall-host.sh — Política de firewall de host (nftables), SPEC-083 (PLAN-011 F3)
# Materializa ADR-016 (política de firewall de host como contrato de
# seguridad estructural por encima del aislamiento de red de Docker).
#
# ============================================================================
# ADVERTENCIA — ESTE SCRIPT NO SE APLICA AUTOMÁTICAMENTE (CHECKPOINT C6)
# ============================================================================
# Este archivo es un ARTEFACTO VERSIONADO, documentado, para que un OPERADOR
# HUMANO lo revise y lo aplique MANUALMENTE en un host real, SOLO tras
# aprobación explícita del Lead + notificación (C6, ADR-016 §3). NINGÚN
# pipeline de CI/CD invoca este script. No existe ningún cron/systemd timer,
# hook de despliegue, ni paso de `docker compose up` que lo ejecute. Si
# encuentras este script siendo invocado automáticamente en algún lugar del
# repo, es una REGRESIÓN de C6 — repórtalo, no lo soluciones ampliando el
# alcance de esta SPEC.
#
# Por qué: aplicar un firewall de host de forma no supervisada puede dejar un
# host incomunicado (SSH incluido, si las reglas se equivocan) sin que nadie
# lo note hasta que ya sea demasiado tarde. Deploy manual, sin CD (Q3=A,
# PLAN-011 §1).
#
# ============================================================================
# QUÉ HACE (ADR-016 §"Decisión")
# ============================================================================
# 1. DROP del egress de IA a internet — refuerzo de defensa en profundidad
#    POR ENCIMA de `ia_internal internal:true` (ADR-005). Si la red Docker
#    `ia_internal` se reconfigurara mal en el futuro (p. ej. alguien quita
#    `internal: true` por error), este firewall de host sigue conteniendo el
#    egress de los contenedores de IA/STT/TTS a nivel de kernel.
# 2. Restringe los puertos del host: SOLO permite el borde entrante legítimo
#    (Caddy, 80/443) y bloquea la exposición directa de `5432` (Postgres),
#    `6379` (Redis) y `11434` (Ollama) a interfaces públicas. `db`/`redis` ya
#    NO publican `ports:` en `docker-compose.yml` (ver ese archivo, mismo
#    SPEC-083) y `api` queda tras loopback (`127.0.0.1:8000`) — este firewall
#    es una SEGUNDA línea de defensa independiente de esa configuración de
#    Docker, no depende de ella para funcionar.
#
# Ninguna de estas reglas SUSTITUYE al aislamiento de red de Docker
# (`ia_internal`, ADR-005) ni a `check-externos-backend.sh`: ambos mecanismos
# coexisten (ADR-016 §1, "defensa en profundidad, NO sustitución").
#
# ============================================================================
# SUPUESTOS DE TOPOLOGÍA (ajustar antes de aplicar en un host real)
# ============================================================================
# - No hay un servidor de producción dedicado confirmado todavía (Q3=A,
#   PLAN-011 §1.4). Este script asume el patrón típico de un host Linux
#   con `nftables` disponible (kernel >= 3.13, paquete `nftables` instalado)
#   que corre el `docker-compose.yml` de este repo con la interfaz de red
#   por defecto de Docker (`docker0`/`br-*`).
# - Variables que el operador DEBE revisar/ajustar para su host real antes
#   de aplicar (nunca se asumen automáticamente):
#     * WAN_IFACE: interfaz de red pública del host (ej. eth0, ens3). Se
#       autodetecta abajo con una heurística (ruta por defecto), pero el
#       operador debe CONFIRMARLA antes de aplicar.
#     * SSH_PORT: puerto de SSH a preservar SIEMPRE accesible (por defecto
#       22) para no dejar al operador fuera del host.
#     * ADMIN_SOURCE_CIDR (opcional): si se define, restringe SSH a un rango
#       de IPs de administración en vez de "cualquier origen". Vacío por
#       defecto (no se asume ninguna IP de administración real — C3: este
#       script no contiene secretos ni IPs reales del operador).
#
# ============================================================================
# CÓMO SE APLICARÍA (documentado, NO ejecutado por este script automáticamente)
# ============================================================================
#   sudo bash scripts/ops/firewall-host.sh --dry-run   # imprime el ruleset,
#                                                        # no toca nftables
#   sudo bash scripts/ops/firewall-host.sh --apply      # aplica de verdad
#                                                        # (requiere --i-understand-this-is-sensitive)
#
# El flag `--apply` exige ADEMÁS `--i-understand-this-is-sensitive` como
# segunda confirmación explícita en la línea de comandos — ningún valor por
# defecto aplica el firewall con una sola bandera. Esto es intencional: hace
# imposible que una ejecución accidental (p. ej. copiar/pegar mal un comando)
# aplique reglas de firewall sin que el operador haya escrito literalmente
# esa frase, reforzando C6 a nivel de UX del propio script.
#
# ============================================================================
# C3 — SIN SECRETOS
# ============================================================================
# Este script NO contiene credenciales, tokens, IPs reales de producción ni
# ningún otro secreto. Las variables de topología (interfaz WAN, CIDR de
# administración) se dejan vacías/autodetectadas y deben ser confirmadas por
# el operador en su propio entorno, nunca hardcodeadas aquí por el agente.
#
set -euo pipefail

# ----------------------------------------------------------------------------
# Configuración (ajustable por el operador antes de aplicar)
# ----------------------------------------------------------------------------

# Puerto SSH a preservar SIEMPRE accesible. Evita que este script deje al
# operador fuera del host (riesgo real de cualquier firewall mal aplicado).
SSH_PORT="${FIREWALL_SSH_PORT:-22}"

# CIDR opcional de administración para restringir SSH (vacío = cualquier
# origen puede intentar SSH, sujeto igualmente a la autenticación de SSH).
# C3: sin IP real por defecto; el operador la define en su propio entorno
# vía variable de entorno, nunca hardcodeada en este archivo.
ADMIN_SOURCE_CIDR="${FIREWALL_ADMIN_SOURCE_CIDR:-}"

# Puertos entrantes del borde de Caddy (reverse proxy TLS, SPEC-035/083).
# Deben coincidir con CADDY_HTTP_PORT/CADDY_HTTPS_PORT de .env/.env.example.
HTTP_PORT="${FIREWALL_HTTP_PORT:-80}"
HTTPS_PORT="${FIREWALL_HTTPS_PORT:-443}"

# Puertos que este firewall NUNCA debe exponer a interfaces públicas
# (ADR-016 §2: `db`/`redis`/`ia` quedan en red Docker interna/loopback).
POSTGRES_PORT="${FIREWALL_POSTGRES_PORT:-5432}"
REDIS_PORT="${FIREWALL_REDIS_PORT:-6379}"
OLLAMA_PORT="${FIREWALL_OLLAMA_PORT:-11434}"
API_PORT="${FIREWALL_API_PORT:-8000}"

# Interfaz de red pública (WAN) del host. Heurística: la interfaz de la ruta
# por defecto. El operador DEBE confirmar este valor en su host real antes
# de aplicar (puede diferir, p. ej. bonding, VLANs, múltiples NICs).
detect_wan_iface() {
    ip route show default 2>/dev/null | awk '/default/ {print $5; exit}'
}
WAN_IFACE="${FIREWALL_WAN_IFACE:-$(detect_wan_iface || true)}"

NFT_BIN="$(command -v nft || true)"

# ----------------------------------------------------------------------------
# Generación del ruleset nftables (siempre se imprime; nunca se aplica salvo
# que el operador pase explícitamente --apply + --i-understand-this-is-sensitive)
# ----------------------------------------------------------------------------

render_ruleset() {
    cat <<NFT
#!/usr/sbin/nft -f
#
# Ruleset generado por scripts/ops/firewall-host.sh (SPEC-083, ADR-016).
# Tabla dedicada 'crm_hardening' para no interferir con reglas nftables
# preexistentes del host (p. ej. las que Docker ya gestiona para el
# bridge/NAT de sus propias redes — este ruleset NO las reemplaza).

table inet crm_hardening {

  # --------------------------------------------------------------------
  # Cadena de entrada (INPUT): permite SOLO el borde entrante legítimo.
  # --------------------------------------------------------------------
  chain input_hardening {
    type filter hook input priority filter + 10; policy accept;

    # Loopback siempre permitido (requerido por healthchecks/servicios
    # internos del propio host, p. ej. docker compose exec).
    iif "lo" accept

    # Conexiones ya establecidas/relacionadas: siempre permitidas (evita
    # romper respuestas legítimas de conexiones salientes ya aceptadas).
    ct state established,related accept

    # SSH: SIEMPRE accesible para que el operador no quede fuera del host.
    # Si ADMIN_SOURCE_CIDR está definido, se restringe el origen.
$( if [ -n "$ADMIN_SOURCE_CIDR" ]; then
     echo "    ip saddr ${ADMIN_SOURCE_CIDR} tcp dport ${SSH_PORT} accept"
   else
     echo "    tcp dport ${SSH_PORT} accept"
   fi )

    # Borde entrante de Caddy (reverse-proxy TLS, SPEC-035/044/083): HTTP
    # (redirección a HTTPS + validación ACME/Let's Encrypt cuando haya
    # dominio real) y HTTPS.
    tcp dport { ${HTTP_PORT}, ${HTTPS_PORT} } accept

    # Todo lo demás en interfaces públicas: DROP explícito, incluyendo
    # Postgres/Redis/Ollama/API directos (defensa en profundidad — en
    # docker-compose.yml ya no publican a 0.0.0.0, pero este firewall NO
    # depende de esa configuración para contenerlos).
    tcp dport { ${POSTGRES_PORT}, ${REDIS_PORT}, ${OLLAMA_PORT}, ${API_PORT} } drop

    # Resto de tráfico entrante no clasificado arriba: política por defecto
    # de esta cadena es 'accept' para no romper nada no contemplado por
    # esta SPEC (p. ej. ICMP de diagnóstico); el operador puede endurecer
    # a 'drop' explícito tras validar su topología real.
  }

  # --------------------------------------------------------------------
  # Cadena de salida (OUTPUT) a nivel de HOST: referencia documentada.
  # El egress de los contenedores de IA/STT/TTS ya está contenido por
  # 'ia_internal internal:true' (ADR-005) a nivel de Docker; esta cadena
  # añade una segunda línea a nivel de kernel del host por si la interfaz
  # de red de Docker para esos contenedores fuera identificable de forma
  # estable (depende del motor de red de Docker: bridge con subred fija,
  # macvlan, etc. — el operador debe completar el rango de IPs real de la
  # red 'ia_internal' en su host, ver 'docker network inspect ia_internal').
  # --------------------------------------------------------------------
  chain output_hardening_ia_egress {
    type filter hook output priority filter + 10; policy accept;

    # EJEMPLO (el operador reemplaza <IA_INTERNAL_SUBNET> por el resultado
    # real de 'docker network inspect <proyecto>_ia_internal' en su host):
    # ip daddr <IA_INTERNAL_SUBNET> accept
    # ip daddr != { <IA_INTERNAL_SUBNET>, 127.0.0.0/8 } meta mark 0x1 drop
    #
    # Sin el rango de subred real (varía por host/instalación de Docker),
    # este script NO genera una regla DROP de egress a ciegas — hacerlo
    # sin verificar la subred real arriesga un host incomunicado o, peor,
    # una regla que aparenta proteger pero no bloquea nada (falso
    # positivo de seguridad). El operador completa esta sección con la
    # subred real de 'ia_internal' de su despliegue antes de aplicar.
  }
}
NFT
}

usage() {
    cat <<EOF
Uso: $0 [--dry-run | --apply --i-understand-this-is-sensitive] [--help]

  --dry-run                          Imprime el ruleset nftables generado
                                      (por defecto si no se pasa ningún flag).
  --apply                            Aplica el ruleset con 'nft -f -' sobre
                                      el host actual. REQUIERE además:
  --i-understand-this-is-sensitive   Segunda confirmación explícita,
                                      obligatoria junto con --apply (C6).
  --help                              Muestra esta ayuda.

Este script NUNCA se invoca automáticamente desde CI/CD (C6, ADR-016 §3).
Aplicarlo en un host real requiere aprobación explícita del Lead +
notificación antes de ejecutar --apply.
EOF
}

MODE="dry-run"
CONFIRMED=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) MODE="dry-run" ;;
        --apply) MODE="apply" ;;
        --i-understand-this-is-sensitive) CONFIRMED=1 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Argumento desconocido: $arg" >&2; usage; exit 2 ;;
    esac
done

echo "# WAN_IFACE detectada (confirmar antes de aplicar): ${WAN_IFACE:-<no detectada>}" >&2

if [ "$MODE" = "apply" ]; then
    if [ "$CONFIRMED" -ne 1 ]; then
        echo "ERROR: --apply requiere también --i-understand-this-is-sensitive." >&2
        echo "Este es un cambio SENSIBLE (C6): requiere aprobación explícita" >&2
        echo "del Lead + notificación antes de aplicarse en un entorno real." >&2
        exit 1
    fi
    if [ -z "$NFT_BIN" ]; then
        echo "ERROR: 'nft' (nftables) no está instalado en este host." >&2
        exit 1
    fi
    echo "Aplicando ruleset con nft -f - ..." >&2
    render_ruleset | "$NFT_BIN" -f -
    echo "Ruleset aplicado. Verifica con: nft list table inet crm_hardening" >&2
else
    render_ruleset
fi
