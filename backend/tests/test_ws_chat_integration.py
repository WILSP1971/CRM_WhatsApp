"""
Tests de integración e2e del canal WebChat por WebSocket (SPEC-015) contra
PostgreSQL real.

Requiere el `db` de `docker-compose.yml` (PostgreSQL 16 + pgvector) con el
esquema de SPEC-012/015 aplicado vía Alembic (columna `estado_entrega`
incluida). Si no hay Postgres accesible (p.ej. este sandbox sin daemon
Docker), estos tests se SKIPEAN automáticamente vía el fixture
`postgres_engine` (`tests/conftest.py`) — no se marcan como aprobados en
falso; quedan documentados como pendientes de ejecutar en CI (mismo patrón
que `tests/test_api_v1_integration.py` y `tests/test_rls_isolation.py`).

El pub/sub de Redis se sustituye por `fakeredis.aioredis.FakeRedis` (mismo
protocolo `redis.asyncio`, sin requerir un daemon Redis real) inyectado vía
`app.api.ws_chat.get_redis_client` — así se prueba el fan-out real (publish/
subscribe) sin depender de infraestructura externa al proceso de test. La
integración con un Redis real de `docker-compose.yml` es la MISMA API
(`redis.asyncio`), por lo que este doble es fiel al contrato.

Qué se verifica (criterios de aceptación de SPEC-015):
  1. Un mensaje enviado por el WebSocket se persiste en BD (via el mismo
     `message_service` que usa el REST de SPEC-014) y se recibe por el otro
     extremo (fan-out Redis pub/sub) con estado de entrega actualizado.
  2. Aislamiento cross-tenant: un cliente del tenant A NUNCA recibe mensajes
     publicados en el canal del tenant B, aunque comparta `conversation_id`
     o el mismo proceso Redis.
  3. Estados de entrega: enviado -> entregado tras persistir/publicar;
     leído tras el evento `{"type": "read", ...}` del otro extremo.
  4. Reconexión: tras cerrar y reabrir el socket, los mensajes ya
     persistidos se recuperan sin pérdida vía el REST existente
     (`GET /conversations/{id}/messages`, SPEC-014).
"""

from __future__ import annotations

import json
import uuid

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.api import ws_chat
from app.db.session import set_tenant_session
from app.main import app
from app.security.jwt import create_access_token

fakeredis = pytest.importorskip(
    "fakeredis",
    reason="fakeredis no instalado en este entorno (dependencia de test, no de producción)",
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fake_redis_client():
    """Un único `FakeRedis` compartido por todas las conexiones del test,
    simulando el bus Redis real compartido entre workers/conexiones."""
    server = fakeredis.aioredis.FakeServer()
    fake = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    original_get_client = ws_chat.get_redis_client
    ws_chat.get_redis_client = lambda: fake
    try:
        yield fake
    finally:
        ws_chat.get_redis_client = original_get_client


@pytest.fixture
def conversation_in_db(postgres_engine, two_tenants_with_data):
    """Crea una conversación real (tenant A) para probar el WS end-to-end."""
    data = two_tenants_with_data
    conversation_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        set_tenant_session(conn, str(data["tenant_a_id"]))
        conn.execute(
            sa.text(
                "INSERT INTO conversations (id, tenant_id, contact_id, canal, estado) "
                "VALUES (:id, :tenant_id, :contact_id, 'webchat', 'abierta')"
            ),
            {
                "id": conversation_id,
                "tenant_id": data["tenant_a_id"],
                "contact_id": data["contact_a_id"],
            },
        )
    return {**data, "conversation_id": conversation_id, "_engine": postgres_engine}


def _token_for(tenant_id) -> str:
    return create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, rol="agente")


def test_message_sent_over_websocket_is_persisted_and_received(
    client, fake_redis_client, conversation_in_db
):
    """Criterio: mensaje enviado se persiste y se recibe por el otro extremo."""
    conversation_id = conversation_in_db["conversation_id"]
    tenant_id = conversation_in_db["tenant_a_id"]
    token = _token_for(tenant_id)

    url = f"/api/v1/ws/chat/{conversation_id}?token={token}"
    with client.websocket_connect(url) as visitor_ws:
        with client.websocket_connect(url) as agent_ws:
            visitor_ws.send_text(
                json.dumps(
                    {"remitente": "contacto", "contenido": "Hola, necesito ayuda"}
                )
            )

            # El propio emisor recibe la confirmación persistida...
            confirmation = json.loads(visitor_ws.receive_text())
            assert confirmation["type"] == "message"
            assert confirmation["message"]["contenido"] == "Hola, necesito ayuda"
            assert confirmation["message"]["estado_entrega"] == "enviado"
            message_id = confirmation["message"]["id"]

            # ...y el otro extremo (agente) también lo recibe (fan-out).
            received_by_agent = json.loads(agent_ws.receive_text())
            assert received_by_agent["type"] == "message"
            assert received_by_agent["message"]["id"] == message_id

            # Tras publicar, el estado de entrega pasa a "entregado" y se
            # difunde a ambos.
            status_visitor = json.loads(visitor_ws.receive_text())
            assert status_visitor["type"] == "delivery_status"
            assert status_visitor["estado_entrega"] == "entregado"


def test_message_delivery_status_progresses_to_leido_on_read_event(
    client, fake_redis_client, conversation_in_db
):
    conversation_id = conversation_in_db["conversation_id"]
    tenant_id = conversation_in_db["tenant_a_id"]
    token = _token_for(tenant_id)
    url = f"/api/v1/ws/chat/{conversation_id}?token={token}"

    with client.websocket_connect(url) as visitor_ws:
        with client.websocket_connect(url) as agent_ws:
            visitor_ws.send_text(
                json.dumps({"remitente": "contacto", "contenido": "Mensaje de prueba"})
            )
            confirmation = json.loads(visitor_ws.receive_text())
            message_id = confirmation["message"]["id"]
            json.loads(agent_ws.receive_text())  # fan-out del mensaje al agente
            json.loads(visitor_ws.receive_text())  # delivery_status "entregado"
            json.loads(agent_ws.receive_text())  # mismo evento al agente

            # El agente marca el mensaje como leído.
            agent_ws.send_text(json.dumps({"type": "read", "message_id": message_id}))

            read_event_visitor = json.loads(visitor_ws.receive_text())
            assert read_event_visitor["type"] == "delivery_status"
            assert read_event_visitor["estado_entrega"] == "leido"
            assert read_event_visitor["message_id"] == message_id


def test_websocket_isolates_messages_between_tenants(
    client, fake_redis_client, conversation_in_db, postgres_engine
):
    """Criterio CE-24/R-23: el pub/sub NO entrega mensajes a otro tenant,
    incluso si el mismo bus Redis físico es compartido entre workers."""
    data = conversation_in_db
    conversation_id_a = data["conversation_id"]

    # Conversación real del tenant B (distinta, pero podría coincidir en un
    # UUID adivinado; lo relevante es que el canal está namespaced por tenant).
    conversation_id_b = uuid.uuid4()
    with postgres_engine.begin() as conn:
        set_tenant_session(conn, str(data["tenant_b_id"]))
        conn.execute(
            sa.text(
                "INSERT INTO conversations (id, tenant_id, contact_id, canal, estado) "
                "VALUES (:id, :tenant_id, :contact_id, 'webchat', 'abierta')"
            ),
            {
                "id": conversation_id_b,
                "tenant_id": data["tenant_b_id"],
                "contact_id": data["contact_b_id"],
            },
        )

    token_a = _token_for(data["tenant_a_id"])
    token_b = _token_for(data["tenant_b_id"])

    with client.websocket_connect(
        f"/api/v1/ws/chat/{conversation_id_a}?token={token_a}"
    ) as ws_tenant_a:
        with client.websocket_connect(
            f"/api/v1/ws/chat/{conversation_id_b}?token={token_b}"
        ) as ws_tenant_b:
            ws_tenant_a.send_text(
                json.dumps({"remitente": "contacto", "contenido": "Secreto tenant A"})
            )
            # El propio tenant A sí lo recibe.
            own_confirmation = json.loads(ws_tenant_a.receive_text())
            assert own_confirmation["message"]["contenido"] == "Secreto tenant A"

            ws_tenant_b.send_text(
                json.dumps({"remitente": "contacto", "contenido": "Mensaje tenant B"})
            )
            b_confirmation = json.loads(ws_tenant_b.receive_text())
            assert b_confirmation["message"]["contenido"] == "Mensaje tenant B"

            # El tenant B NUNCA debe recibir el mensaje de A: el único mensaje
            # disponible en su socket es el propio "Mensaje tenant B" (ya
            # consumido) y su propio delivery_status; nada del tenant A.
            next_event_b = json.loads(ws_tenant_b.receive_text())
            assert next_event_b["type"] == "delivery_status"
            assert "Secreto tenant A" not in json.dumps(next_event_b)


def test_reconnect_recovers_persisted_messages_via_rest(
    client, fake_redis_client, conversation_in_db
):
    """Criterio: tras caída/reconexión, la conversación se recupera sin
    pérdida de mensajes ya persistidos (recuperados vía el REST de
    SPEC-014, ya que el WebSocket en sí es sin estado, RNF-05)."""
    conversation_id = conversation_in_db["conversation_id"]
    tenant_id = conversation_in_db["tenant_a_id"]
    token = _token_for(tenant_id)
    url = f"/api/v1/ws/chat/{conversation_id}?token={token}"

    with client.websocket_connect(url) as ws:
        ws.send_text(
            json.dumps({"remitente": "contacto", "contenido": "Mensaje antes de caída"})
        )
        json.loads(ws.receive_text())  # confirmación
    # Socket cerrado ("caída"); se reconecta.

    with client.websocket_connect(url):
        pass  # reconexión exitosa: la conversación sigue siendo válida.

    from types import SimpleNamespace

    from app.api import deps

    def fake_get_current_user():
        return SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            email="agente@tenant.test",
            nombre="Agente",
            rol="agente",
            activo=True,
        )

    def fake_get_tenant_db():
        with client.portal_engine.connect() as conn:  # type: ignore[attr-defined]
            with conn.begin():
                set_tenant_session(conn, str(tenant_id))
                yield conn

    # Reutiliza el MISMO engine de Postgres del fixture (sin abrir uno nuevo)
    # para verificar, vía el REST ya probado en SPEC-014, que los mensajes
    # persistidos por el WebSocket se leen igual que cualquier otro mensaje.
    client.portal_engine = conversation_in_db["_engine"]
    app.dependency_overrides[deps.get_current_user] = fake_get_current_user
    app.dependency_overrides[deps.get_tenant_db] = fake_get_tenant_db
    try:
        response = client.get(f"/api/v1/conversations/{conversation_id}/messages")
        assert response.status_code == 200
        contents = [m["contenido"] for m in response.json()["items"]]
        assert "Mensaje antes de caída" in contents
    finally:
        app.dependency_overrides.clear()
