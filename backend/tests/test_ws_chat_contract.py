"""
Tests de contrato del WebSocket del WebChat (SPEC-015) — SIN Postgres/Redis
reales.

Estrategia: igual patrón que `tests/test_auth_api.py` — se ejercita el
`TestClient.websocket_connect` real de FastAPI/Starlette (handshake HTTP ->
101/rechazo real) pero se sustituye la resolución de JWT
(`app.security.jwt.decode_access_token`) y la sesión de BD
(`app.api.ws_chat._tenant_session`) por dobles de prueba, para no requerir
un Postgres vivo. La prueba de aislamiento cross-tenant CONTRA Postgres real
vive en `tests/test_ws_chat_integration.py` (se SKIPEA documentadamente si no
hay Postgres, mismo patrón que `tests/test_api_v1_integration.py`).

Cubre criterios de aceptación de SPEC-015 verificables sin infraestructura:
  - El WebSocket exige credencial válida: sin token -> conexión rechazada
    (criterio de aceptación explícito de SPEC-015).
  - Token inválido/expirado -> conexión rechazada.
  - Conversación inexistente (o de otro tenant, vía RLS) -> conexión
    rechazada (no se acepta el socket).
"""

from __future__ import annotations

import contextlib
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import ws_chat
from app.main import app
from app.security.jwt import InvalidTokenError, TokenPayload


@pytest.fixture
def client():
    return TestClient(app)


def _fake_token_payload(tenant_id: uuid.UUID) -> TokenPayload:
    from datetime import datetime, timedelta, timezone

    return TokenPayload(
        sub=str(uuid.uuid4()),
        tenant_id=str(tenant_id),
        rol="agente",
        exp=datetime.now(timezone.utc) + timedelta(minutes=30),
    )


def test_websocket_rejects_connection_without_token(client):
    """Criterio de aceptación: conexiones sin credencial válida se rechazan."""
    conversation_id = uuid.uuid4()
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/api/v1/ws/chat/{conversation_id}"):
            pass
    assert exc_info.value.code == ws_chat.WS_CLOSE_UNAUTHORIZED


def test_websocket_rejects_connection_with_invalid_token(client, monkeypatch):
    def _raise_invalid(token: str) -> TokenPayload:
        raise InvalidTokenError("token de prueba inválido")

    monkeypatch.setattr(ws_chat, "decode_access_token", _raise_invalid)

    conversation_id = uuid.uuid4()
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            f"/api/v1/ws/chat/{conversation_id}?token=lo-que-sea"
        ):
            pass
    assert exc_info.value.code == ws_chat.WS_CLOSE_UNAUTHORIZED


def test_websocket_rejects_connection_when_conversation_not_found(client, monkeypatch):
    """Simula RLS ocultando la conversación (de otro tenant o inexistente):
    el socket debe rechazarse en vez de aceptarse (nunca expone el canal)."""
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()

    monkeypatch.setattr(
        ws_chat, "decode_access_token", lambda token: _fake_token_payload(tenant_id)
    )

    @contextlib.contextmanager
    def _fake_tenant_session(_tenant_id):
        yield SimpleNamespace()

    monkeypatch.setattr(ws_chat, "_tenant_session", _fake_tenant_session)
    monkeypatch.setattr(ws_chat, "get_conversation_activa", lambda db, conv_id: None)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            f"/api/v1/ws/chat/{conversation_id}?token=valido"
        ):
            pass
    assert exc_info.value.code == ws_chat.WS_CLOSE_NOT_FOUND
