"""Tests del endpoint `GET /api/v1/ai/health` — SPEC-016.

Sigue el mismo patrón que `tests/test_api_v1_http_contract.py` (SPEC-014):
usa `app.dependency_overrides` para no requerir Postgres real y para
mockear el cliente de IA (`get_ai_client`) sin llamar a un modelo real.

El caso "401 sin token" ya está cubierto en `PROTECTED_ENDPOINTS` de
`test_api_v1_http_contract.py`; aquí se cubre el contrato de la respuesta
autenticada, en modo disponible y en modo degradado (R-21).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import ai as ai_router_module
from app.api import deps
from app.main import app
from app.security.jwt import create_access_token
from app.services.ai_service import get_ai_client


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_token():
    tenant_id = uuid.uuid4()
    token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, rol="agente")
    return token, tenant_id


@pytest.fixture
def override_auth(auth_token):
    token, tenant_id = auth_token

    def fake_get_current_user():
        return SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            email="agente@tenant.test",
            nombre="Agente de Prueba",
            rol="agente",
            activo=True,
        )

    def fake_get_tenant_db():
        yield None

    app.dependency_overrides[deps.get_current_user] = fake_get_current_user
    app.dependency_overrides[deps.get_tenant_db] = fake_get_tenant_db
    try:
        yield token
    finally:
        app.dependency_overrides.clear()


def test_ai_health_reports_available_when_ollama_responds(client, override_auth):
    token = override_auth
    app.dependency_overrides[get_ai_client] = lambda: SimpleNamespace(
        is_available=lambda: True
    )

    response = client.get(
        "/api/v1/ai/health", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["disponible"] is True
    assert data["modelo_llm"]
    assert data["modelo_embeddings"]


def test_ai_health_reports_unavailable_in_degraded_mode(client, override_auth):
    """Modo degradado (R-21): el servicio de IA no responde, pero el
    endpoint de salud sigue contestando 200 con `disponible=false` (no
    lanza 500) para que el resto de la app pueda reaccionar."""
    token = override_auth
    app.dependency_overrides[get_ai_client] = lambda: SimpleNamespace(
        is_available=lambda: False
    )

    response = client.get(
        "/api/v1/ai/health", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["disponible"] is False


def test_ai_health_never_exposes_internal_base_url(client, override_auth):
    """El endpoint no debe filtrar la URL interna (topología de red)."""
    token = override_auth
    app.dependency_overrides[get_ai_client] = lambda: SimpleNamespace(
        is_available=lambda: True
    )

    response = client.get(
        "/api/v1/ai/health", headers={"Authorization": f"Bearer {token}"}
    )

    body_text = response.text
    assert "11434" not in body_text
    assert "http://ia" not in body_text


def test_ai_router_uses_get_current_user_dependency():
    """Verifica que el router de IA usa el mismo mecanismo de auth central
    (`get_current_user`) que el resto de la API core, no uno propio."""
    import inspect

    source = inspect.getsource(ai_router_module)
    assert "get_current_user" in source
