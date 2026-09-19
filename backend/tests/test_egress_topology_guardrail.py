"""Guardarraíl anti-regresión de la topología de egress — SPEC-032
(RF-01/RF-02, ADR-006, criterio central "verificación de egress auditable y
reproducible").

Parsea `docker-compose.yml` (raíz del repo) y falla si algún servicio de IA
gana una ruta de egress: la invariante de topología (ADR-006 §2, PLAN-003
§3.2) es que SOLO `api` y `wa_send_worker` están en la red `app` (bridge CON
egress); `ia`, `rag_worker`, `sentiment_worker`, `whatsapp_inbound_worker`,
`db` y `redis` viven EXCLUSIVAMENTE en `ia_internal` (`internal: true`, sin
salida a internet).

Esto complementa `check-externos-backend.sh` (que audita referencias de
código: URLs/SDKs/imports) con una verificación ESTRUCTURAL de la topología
de red declarada en `docker-compose.yml` — si un cambio futuro añadiera la
red `app` a un servicio de IA (por error o a propósito), este test falla
ANTES de que llegue a producción, sin depender de un firewall/captura de red
real (esa evidencia real se documenta aparte, ver runbook).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.yml"

# Invariante de topología (ADR-006 §2): estos servicios NUNCA deben tener
# egress a internet (permanecen únicamente en `ia_internal internal:true`).
_SERVICIOS_SIN_EGRESS_ESPERADO = {
    "ia",
    "rag_worker",
    "sentiment_worker",
    "whatsapp_inbound_worker",
    "db",
    "redis",
}

# Únicos servicios autorizados a tener egress (ADR-006 §1): transporte hacia
# `graph.facebook.com` exclusivamente, nunca inferencia.
_SERVICIOS_CON_EGRESS_PERMITIDO = {"api", "wa_send_worker"}

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
    """RF-01 SPEC-032: un servicio de IA/datos con la red `app` (egress)
    añadida sería una fuga de topología — este test la detecta y falla la
    build ANTES de que se despliegue.
    """
    compose = _load_compose()
    services = compose["services"]
    assert service_name in services, f"Servicio '{service_name}' no existe en compose"

    networks = _networks_of(services[service_name])
    assert _RED_CON_EGRESS not in networks, (
        f"REGRESIÓN DE EGRESS: el servicio '{service_name}' está en la red "
        f"'{_RED_CON_EGRESS}' (con salida a internet). Invariante violada "
        "(ADR-006 §2): SOLO 'api'/'wa_send_worker' pueden tener egress."
    )
    assert _RED_SIN_EGRESS in networks, (
        f"El servicio '{service_name}' debería estar en '{_RED_SIN_EGRESS}' "
        "(sin egress) y no lo está — revisa la topología de red."
    )


@pytest.mark.parametrize("service_name", sorted(_SERVICIOS_CON_EGRESS_PERMITIDO))
def test_only_api_and_wa_send_worker_have_egress_network(service_name):
    """RF-02 SPEC-032: `api`/`wa_send_worker` SÍ deben tener la red `app`
    (excepción acotada de egress, ADR-006) — si alguno la pierde, el canal
    real deja de funcionar (webhook/envío)."""
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
