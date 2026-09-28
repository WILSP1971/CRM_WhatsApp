"""
Tests HTTP de `app/api/analytics.py` (`GET /analytics/business`, SPEC-063)
contra PostgreSQL real.

Mismo patrón que `tests/test_calls_api.py` (SPEC-040): se ejercita la API
completa end-to-end vía `TestClient` + `dependency_overrides` de
`get_tenant_db`/`get_current_user` (fixtures `client`/`api_as_tenant` de
`tests/conftest.py`), inyectando una sesión real de Postgres con el
`tenant_id`/usuario de prueba ya resueltos (rol `omnicore_app`, ADR-008 —
ejerce RLS real, NO el rol owner). Requiere el `db` de `docker-compose.yml`
(PostgreSQL 16 + pgvector) con el esquema de SPEC-012/SPEC-062 aplicado vía
Alembic; si no hay Postgres accesible, se SKIPEAN automáticamente vía el
fixture `postgres_engine` (no se marcan como aprobados en falso).

Formaliza en la suite lo que SPEC-065 pide como evidencia del endpoint HTTP
completo (antes solo verificado manualmente por el orquestador):
  1. `GET /analytics/business` 200 con JWT + datos reales, coincidiendo con
     fixtures deterministas (mismo cálculo a mano que
     `tests/test_analytics_service.py`, pero cruzando la capa HTTP: query
     params, serialización Pydantic, dependencias FastAPI).
  2. 401 sin JWT.
  3. 422 con `desde > hasta` (rango inválido).
  4. 422 con `canal` fuera de `CANALES_VALIDOS`.
  5. 422 con un rango que excede `ANALYTICS_MAX_RANGE_DAYS`.
  6. 200 con todo en cero/`null` cuando el rango no tiene ninguna
     conversación del tenant (nunca 4xx/5xx ante "sin datos").
  7. Aislamiento cross-tenant REAL contra el endpoint HTTP (no solo el
     servicio): un tenant no ve en su respuesta ningún agregado que incluya
     datos de otro tenant.
  8. La respuesta NO contiene ningún campo de PII individual (`contact_id`,
     contenido de mensaje, id de conversación, etc.) — solo agregados.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa

from app.core.config import get_settings

UTC = timezone.utc

# `client` y `api_as_tenant` son fixtures compartidos de `tests/conftest.py`
# (mismo patrón que `tests/test_calls_api.py`).


# ---------------------------------------------------------------------------
# Helpers de bootstrap (SQL directo vía `postgres_engine`, fuera de RLS a
# propósito — mismo patrón que `tests/test_analytics_service.py`).
# ---------------------------------------------------------------------------


def _insert_conversation(
    engine,
    *,
    tenant_id,
    contact_id,
    canal="whatsapp",
    estado="abierta",
    created_at=None,
    activo=True,
):
    conversation_id = uuid.uuid4()
    created_at = created_at or datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conversations "
                "(id, tenant_id, contact_id, canal, estado, activo, "
                " created_at, updated_at) "
                "VALUES (:id, :tenant_id, :contact_id, :canal, :estado, "
                " :activo, :created_at, :created_at)"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "contact_id": contact_id,
                "canal": canal,
                "estado": estado,
                "activo": activo,
                "created_at": created_at,
            },
        )
    return conversation_id


def _insert_message(
    engine,
    *,
    tenant_id,
    conversation_id,
    remitente,
    created_at,
    contenido="hola",
    activo=True,
):
    message_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO messages "
                "(id, tenant_id, conversation_id, remitente, contenido, tipo, "
                " activo, estado_entrega, wamid, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :conversation_id, :remitente, "
                " :contenido, 'texto', :activo, 'enviado', :wamid, "
                " :created_at, :created_at)"
            ),
            {
                "id": message_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "remitente": remitente,
                "contenido": contenido,
                "activo": activo,
                "wamid": f"wamid.analytics-api-test-{uuid.uuid4().hex[:16]}",
                "created_at": created_at,
            },
        )
    return message_id


def _dt(d: date, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC)


ENDPOINT = "/api/v1/analytics/business"


# ---------------------------------------------------------------------------
# 1. 200 con JWT + datos reales coincidentes con fixtures deterministas
# ---------------------------------------------------------------------------


def test_get_business_analytics_200_matches_deterministic_fixtures(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    tenant_id = data["tenant_a_id"]
    contact_id = data["contact_a_id"]
    hoy = date.today()
    ayer = hoy - timedelta(days=1)

    # 3 conversaciones activas en rango: 2 whatsapp (1 abierta, 1 cerrada) +
    # 1 webchat (cerrada) -> total=3, abiertas=1, cerradas=2.
    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal="whatsapp",
        estado="abierta",
        created_at=_dt(hoy),
    )
    conv_cerrada = _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal="whatsapp",
        estado="cerrada",
        created_at=_dt(hoy, hour=14),
    )
    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal="webchat",
        estado="cerrada",
        created_at=_dt(ayer),
    )
    # Respuesta de agente 10s tras el entrante en la conversación cerrada.
    base = _dt(hoy, hour=14, minute=0)
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_cerrada,
        remitente="contacto",
        created_at=base,
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_cerrada,
        remitente="agente",
        created_at=base + timedelta(seconds=10),
    )

    with api_as_tenant(tenant_id):
        response = client.get(
            ENDPOINT, params={"desde": str(ayer), "hasta": str(hoy)}
        )

    assert response.status_code == 200
    body = response.json()

    assert body["desde"] == str(ayer)
    assert body["hasta"] == str(hoy)
    assert body["canal"] is None

    conversaciones = body["conversaciones"]
    assert conversaciones["total"] == 3
    assert conversaciones["abiertas"] == 1
    assert conversaciones["cerradas"] == 2

    por_canal = {p["canal"]: p for p in conversaciones["por_canal"]}
    assert por_canal["whatsapp"]["total"] == 2
    assert por_canal["webchat"]["total"] == 1

    serie_por_fecha = {p["fecha"]: p["total"] for p in conversaciones["serie_diaria"]}
    assert serie_por_fecha[str(ayer)] == 1
    assert serie_por_fecha[str(hoy)] == 2
    assert len(conversaciones["serie_diaria"]) == 2  # rango completo: ayer..hoy

    tiempos = body["tiempos_respuesta"]
    assert tiempos["conversaciones_con_respuesta"] == 1
    assert tiempos["primera_respuesta_promedio_seg"] == 10.0
    assert tiempos["respuesta_promedio_seg"] == 10.0

    conversion = body["conversion"]
    assert conversion["totales"] == 3
    assert conversion["cerradas"] == 2
    assert conversion["tasa"] == 2 / 3


def test_get_business_analytics_filters_by_canal(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    tenant_id = data["tenant_a_id"]
    contact_id = data["contact_a_id"]
    hoy = date.today()

    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal="whatsapp",
        created_at=_dt(hoy),
    )
    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal="webchat",
        created_at=_dt(hoy),
    )

    with api_as_tenant(tenant_id):
        response = client.get(
            ENDPOINT, params={"desde": str(hoy), "hasta": str(hoy), "canal": "webchat"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["canal"] == "webchat"
    assert body["conversaciones"]["total"] == 1
    assert [p["canal"] for p in body["conversaciones"]["por_canal"]] == ["webchat"]


# ---------------------------------------------------------------------------
# 2. 401 sin JWT
# ---------------------------------------------------------------------------


def test_get_business_analytics_requires_auth_401_without_token(client):
    hoy = date.today()
    response = client.get(ENDPOINT, params={"desde": str(hoy), "hasta": str(hoy)})
    assert response.status_code == 401
    assert response.json()["detail"] == "No autenticado"


# ---------------------------------------------------------------------------
# 3-5. 422: rango inválido, canal inválido, rango excede ANALYTICS_MAX_RANGE_DAYS
# ---------------------------------------------------------------------------


def test_get_business_analytics_422_when_desde_after_hasta(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    hoy = date.today()
    ayer = hoy - timedelta(days=1)

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(ENDPOINT, params={"desde": str(hoy), "hasta": str(ayer)})

    assert response.status_code == 422


def test_get_business_analytics_422_when_canal_invalido(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    hoy = date.today()

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(
            ENDPOINT,
            params={"desde": str(hoy), "hasta": str(hoy), "canal": "fax"},
        )

    assert response.status_code == 422


def test_get_business_analytics_422_when_range_exceeds_max_days(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    max_days = get_settings().analytics_max_range_days
    hasta = date.today()
    # Un día más allá del máximo permitido (inclusive) -> debe rechazar.
    desde = hasta - timedelta(days=max_days)

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(ENDPOINT, params={"desde": str(desde), "hasta": str(hasta)})

    assert response.status_code == 422
    assert "máximo permitido" in response.json()["detail"]


def test_get_business_analytics_200_when_range_equals_max_days(
    client, api_as_tenant, two_tenants_with_data
):
    """Caso borde: el rango exactamente en el límite (inclusive) SÍ es
    válido — solo lo que lo supera es 422."""
    data = two_tenants_with_data
    max_days = get_settings().analytics_max_range_days
    hasta = date.today()
    desde = hasta - timedelta(days=max_days - 1)

    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(ENDPOINT, params={"desde": str(desde), "hasta": str(hasta)})

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 6. 200 con ceros en rango sin datos
# ---------------------------------------------------------------------------


def test_get_business_analytics_200_with_zeros_when_no_data_in_range(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    tenant_id = data["tenant_a_id"]
    contact_id = data["contact_a_id"]
    hoy = date.today()
    lejos = hoy - timedelta(days=100)

    # Conversación real, pero FUERA del rango consultado.
    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        created_at=_dt(hoy),
    )

    with api_as_tenant(tenant_id):
        response = client.get(
            ENDPOINT, params={"desde": str(lejos), "hasta": str(lejos)}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["conversaciones"]["total"] == 0
    assert body["conversaciones"]["abiertas"] == 0
    assert body["conversaciones"]["cerradas"] == 0
    assert body["conversaciones"]["por_canal"] == []
    assert body["conversaciones"]["serie_diaria"] == [
        {"fecha": str(lejos), "total": 0}
    ]
    assert body["tiempos_respuesta"]["primera_respuesta_promedio_seg"] is None
    assert body["tiempos_respuesta"]["respuesta_promedio_seg"] is None
    assert body["tiempos_respuesta"]["conversaciones_con_respuesta"] == 0
    assert body["conversion"]["tasa"] is None  # nunca 0, nunca división por cero
    assert body["conversion"]["totales"] == 0
    assert body["conversion"]["cerradas"] == 0


# ---------------------------------------------------------------------------
# 7. Cross-tenant REAL contra el endpoint HTTP
# ---------------------------------------------------------------------------


def test_get_business_analytics_tenant_a_never_sees_tenant_b_aggregates(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    tenant_a_id = data["tenant_a_id"]
    tenant_b_id = data["tenant_b_id"]
    hoy = date.today()

    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_a_id,
        contact_id=data["contact_a_id"],
        estado="cerrada",
        created_at=_dt(hoy),
    )
    # Tenant B: 5 conversaciones que NUNCA deben aparecer en la respuesta
    # HTTP del tenant A.
    for _ in range(5):
        _insert_conversation(
            postgres_engine,
            tenant_id=tenant_b_id,
            contact_id=data["contact_b_id"],
            estado="cerrada",
            created_at=_dt(hoy),
        )

    with api_as_tenant(tenant_a_id):
        response_a = client.get(ENDPOINT, params={"desde": str(hoy), "hasta": str(hoy)})

    with api_as_tenant(tenant_b_id):
        response_b = client.get(ENDPOINT, params={"desde": str(hoy), "hasta": str(hoy)})

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert response_a.json()["conversaciones"]["total"] == 1
    assert response_b.json()["conversaciones"]["total"] == 5


# ---------------------------------------------------------------------------
# 8. PII: solo agregados, ningún campo individual
# ---------------------------------------------------------------------------

# Claves que NUNCA deben aparecer en ningún nivel del JSON de respuesta —
# identificarían un contacto/conversación/mensaje individual.
_FORBIDDEN_KEYS = {
    "contact_id",
    "contacto_id",
    "conversation_id",
    "conversacion_id",
    "message_id",
    "mensaje_id",
    "contenido",
    "telefono",
    "nombre",
    "email",
    "wamid",
}


def _collect_keys(node, found: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            _collect_keys(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_keys(item, found)


def test_get_business_analytics_response_contains_no_individual_pii(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    tenant_id = data["tenant_a_id"]
    contact_id = data["contact_a_id"]
    hoy = date.today()

    conv_id = _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        estado="cerrada",
        created_at=_dt(hoy),
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="contacto",
        contenido="Contenido confidencial del contacto",
        created_at=_dt(hoy),
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="agente",
        created_at=_dt(hoy, hour=13),
    )

    with api_as_tenant(tenant_id):
        response = client.get(ENDPOINT, params={"desde": str(hoy), "hasta": str(hoy)})

    assert response.status_code == 200
    body = response.json()
    raw_text = response.text

    # Ningún literal de PII sembrado en el fixture debe aparecer en el JSON.
    assert str(conv_id) not in raw_text
    assert str(contact_id) not in raw_text
    assert "Contenido confidencial del contacto" not in raw_text

    found_keys: set[str] = set()
    _collect_keys(body, found_keys)
    leaked = found_keys & _FORBIDDEN_KEYS
    assert not leaked, f"Claves de PII individual filtradas en la respuesta: {leaked}"

    # Forma esperada: únicamente los 4 bloques agregados + metadatos de rango.
    assert set(body.keys()) == {
        "desde",
        "hasta",
        "canal",
        "conversaciones",
        "tiempos_respuesta",
        "conversion",
        "ia_asistencia",
    }
