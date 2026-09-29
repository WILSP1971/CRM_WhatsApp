"""Guardarraíl anti-regresión de la topología de egress — SPEC-032/SPEC-035
(RF-01/RF-02, ADR-006/ADR-009/ADR-010, criterio central "verificación de
egress auditable y reproducible").

Parsea `docker-compose.yml` (raíz del repo) y falla si algún servicio de IA
o de datos gana una ruta de egress: la invariante de topología (ADR-006 §2,
PLAN-003 §3.2) es que SOLO un conjunto explícito y acotado de servicios está
en la red `app` (bridge CON salida al host/internet); `ia`, `rag_worker`,
`sentiment_worker`, `whatsapp_inbound_worker`, `stt_worker`, `db` y `redis`
viven EXCLUSIVAMENTE en `ia_internal` (`internal: true`, sin salida a
internet).

SPEC-035 (ADR-009/ADR-010) añade a la red `app`:
- `caddy`: reverse proxy TLS que expone SOLO el path del webhook de
  grabaciones (ingress hacia `api`, no egress de inferencia/audio).
- `recording_fetch_worker`: EXCEPCIÓN ACOTADA análoga a `wa_send_worker`
  (ADR-006) — egress restringido por allowlist al único host del PBX,
  SOLO si el PBX es externo (ADR-010). Entregado inerte bajo
  `profiles: ["pbx-externo"]`: no se levanta con `docker compose up` por
  defecto (SUP-42, PBX preferido on-prem).

`stt_worker` (SPEC-035/ADR-009) es STT 100% local: hereda el aislamiento de
la IA y permanece EXCLUSIVAMENTE en `ia_internal`, igual que `ia`/
`rag_worker`/`sentiment_worker` — nunca gana la red `app`.

SPEC-037 añade `recording_ingest_worker` (consumidor de `pbx:recordings:
inbound`, resolución de tenant + dedup por `call_id` + almacenamiento
cifrado + encolado STT): permanece EXCLUSIVAMENTE en `ia_internal`, igual
que `whatsapp_inbound_worker` — NUNCA hace peticiones salientes, ni siquiera
al PBX (esa excepción acotada, si aplica, es `recording_fetch_worker`, un
servicio DISTINTO).

Esto complementa `check-externos-backend.sh` (que audita referencias de
código: URLs/SDKs/imports, incluida la allowlist por ruta del host del PBX
dentro de `app/services/telefonia/`) con una verificación ESTRUCTURAL de la
topología de red declarada en `docker-compose.yml` — si un cambio futuro
añadiera la red `app` a un servicio de IA/STT (por error o a propósito),
este test falla ANTES de que llegue a producción, sin depender de un
firewall/captura de red real (esa evidencia real se documenta aparte, ver
runbook).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.yml"

# Invariante de topología (ADR-006 §2, ADR-009): estos servicios NUNCA deben
# tener egress a internet (permanecen únicamente en `ia_internal
# internal:true`). `stt_worker` (SPEC-035/ADR-009, STT 100% local) hereda el
# mismo aislamiento que `ia`/`rag_worker`/`sentiment_worker`. Los servicios
# de voz en vivo (`voice_stt`, `voice_tts`, SPEC-044) también permanecen
# aislados en `ia_internal` sin egress (ADR-011).
_SERVICIOS_SIN_EGRESS_ESPERADO = {
    "ia",
    "rag_worker",
    "sentiment_worker",
    "stt_worker",
    "recording_ingest_worker",
    "voice_stt",
    "voice_tts",
    # `tts_worker` (Entregable #6, SPEC-069, ADR-014): síntesis TTS 100%
    # local (Piper, CPU-only) — hereda el MISMO aislamiento que `stt_worker`
    # (ADR-005/009/012): NUNCA importa/ejecuta el cliente de subida de
    # WhatsApp, la subida real la hace `wa_send_worker` (que SÍ tiene
    # egress, ver `_SERVICIOS_CON_EGRESS_PERMITIDO`) leyendo el clip del
    # almacén cifrado compartido.
    "tts_worker",
    "db",
    "redis",
}

# Únicos servicios autorizados a tener egress/salida por la red `app`
# (ADR-006 §1, ADR-010, ADR-011):
# - `api`/`wa_send_worker`: transporte hacia `graph.facebook.com`
#   exclusivamente, nunca inferencia (ADR-006).
# - `whatsapp_inbound_worker`: EXCEPCIÓN ACOTADA (SPEC-054/SPEC-055, extendida
#   ADR-006) — descarga de notas de voz desde `graph.facebook.com` (host ya
#   autorizado, mismo módulo `app/integrations/whatsapp/` que `wa_send_worker`)
#   + auto-respuesta de descarte por duración (SPEC-055, reutilizando
#   `graph_client` de SPEC-029). NUNCA inferencia: IA/STT reciben del almacén
#   cifrado on-prem (ADR-009). Dedup por wamid/RLS igual que antes (SPEC-027).
# - `caddy`: reverse proxy TLS (SPEC-035) que expone SOLO el path del
#   webhook de grabaciones; no habla con `ia_internal` ni hace egress de
#   inferencia/audio, solo enruta ingress hacia `api`.
# - `recording_fetch_worker`: EXCEPCIÓN ACOTADA (SPEC-035/ADR-010) — egress
#   restringido por allowlist al único host del PBX, SOLO si el PBX es
#   externo; vive bajo `profiles: ["pbx-externo"]` (inerte por defecto).
# - `voice_gateway`: EXCEPCIÓN ACOTADA (SPEC-044/ADR-011 §7) — conector de
#   media en vivo que está en `app` pero con egress limitado por firewall
#   host SOLO al PBX de media si es externo (por defecto inerte en on-prem,
#   sin egress nuevo); también en `ia_internal` para hablar con voice_stt/
#   voice_tts/NLU por red interna.
_SERVICIOS_CON_EGRESS_PERMITIDO = {
    "api",
    "wa_send_worker",
    "whatsapp_inbound_worker",
    "caddy",
    "recording_fetch_worker",
    "voice_gateway",
}

# Red con egress a internet (bridge normal, sin `internal: true`).
_RED_CON_EGRESS = "app"
# Red sin egress (`internal: true`, ADR-005/006).
_RED_SIN_EGRESS = "ia_internal"


def _load_compose() -> dict:
    assert _COMPOSE_PATH.is_file(), f"No se encontró {_COMPOSE_PATH}"
    with _COMPOSE_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _networks_of(service_def: dict) -> set[str]:
    """Extrae los nombres de red de un servicio, soportando tanto la forma
    de lista (`networks: [a, b]`) como de mapeo (`networks: {a: {...}}`)."""
    networks = service_def.get("networks", [])
    if isinstance(networks, dict):
        return set(networks.keys())
    return set(networks)


def test_docker_compose_exists_and_parses():
    compose = _load_compose()
    assert "services" in compose
    assert "networks" in compose


def test_ia_internal_network_has_internal_true():
    """Invariante dura (ADR-005/006): sin `internal: true` la red completa
    perdería la garantía de bloqueo de egress a nivel Docker."""
    compose = _load_compose()
    ia_internal_def = compose["networks"].get(_RED_SIN_EGRESS)
    assert ia_internal_def is not None, f"Falta la red '{_RED_SIN_EGRESS}'"
    assert ia_internal_def.get("internal") is True, (
        f"La red '{_RED_SIN_EGRESS}' DEBE declarar 'internal: true' "
        "(ADR-005/006, bloqueo de egress de la IA)"
    )


@pytest.mark.parametrize("service_name", sorted(_SERVICIOS_SIN_EGRESS_ESPERADO))
def test_ia_and_data_services_have_no_egress_network(service_name):
    """RF-01 SPEC-032/SPEC-035: un servicio de IA/STT/datos con la red `app`
    (egress) añadida sería una fuga de topología — este test la detecta y
    falla la build ANTES de que se despliegue.
    """
    compose = _load_compose()
    services = compose["services"]
    assert service_name in services, f"Servicio '{service_name}' no existe en compose"

    networks = _networks_of(services[service_name])
    assert _RED_CON_EGRESS not in networks, (
        f"REGRESIÓN DE EGRESS: el servicio '{service_name}' está en la red "
        f"'{_RED_CON_EGRESS}' (con salida a internet). Invariante violada "
        f"(ADR-006 §2/ADR-009): SOLO {sorted(_SERVICIOS_CON_EGRESS_PERMITIDO)} "
        "pueden tener esa red."
    )
    assert _RED_SIN_EGRESS in networks, (
        f"El servicio '{service_name}' debería estar en '{_RED_SIN_EGRESS}' "
        "(sin egress) y no lo está — revisa la topología de red."
    )


@pytest.mark.parametrize("service_name", sorted(_SERVICIOS_CON_EGRESS_PERMITIDO))
def test_only_api_and_wa_send_worker_have_egress_network(service_name):
    """RF-02 SPEC-032/SPEC-035: `api`/`wa_send_worker` (ADR-006) y
    `caddy`/`recording_fetch_worker` (ADR-010, SPEC-035) SÍ deben tener la
    red `app` (excepción acotada de egress/ingress) — si alguno la pierde,
    el canal real deja de funcionar (webhook/envío/proxy TLS/descarga PBX)."""
    compose = _load_compose()
    services = compose["services"]
    assert service_name in services, f"Servicio '{service_name}' no existe en compose"

    networks = _networks_of(services[service_name])
    assert _RED_CON_EGRESS in networks, (
        f"El servicio '{service_name}' debería tener egress (red "
        f"'{_RED_CON_EGRESS}') según ADR-006 y no lo tiene."
    )


def test_no_other_service_has_egress_network():
    """Guardarraíl exhaustivo: además de los servicios explícitamente
    listados arriba, NINGÚN otro servicio del compose debe tener la red
    `app` — cubre también servicios añadidos en el futuro que no se hayan
    incorporado a `_SERVICIOS_SIN_EGRESS_ESPERADO`/`_SERVICIOS_CON_EGRESS_
    PERMITIDO` (fail-safe: por defecto, un servicio nuevo NO debería tener
    egress salvo que se declare explícitamente aquí también)."""
    compose = _load_compose()
    services = compose["services"]

    servicios_con_egress_real = {
        nombre
        for nombre, definicion in services.items()
        if _RED_CON_EGRESS in _networks_of(definicion)
    }

    assert servicios_con_egress_real == _SERVICIOS_CON_EGRESS_PERMITIDO, (
        "La lista de servicios con egress real en docker-compose.yml "
        f"({sorted(servicios_con_egress_real)}) no coincide con la "
        f"permitida por ADR-006 ({sorted(_SERVICIOS_CON_EGRESS_PERMITIDO)}). "
        "Si añadiste un servicio nuevo con egress, es una regresión salvo "
        "que actualices también este guardarraíl de forma deliberada "
        "(cambio SENSIBLE, requiere aprobación del Lead)."
    )
