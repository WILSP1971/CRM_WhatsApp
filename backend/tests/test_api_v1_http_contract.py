"""
Tests de contrato HTTP de la API core (SPEC-014) — SIN Postgres real.

Estrategia (mismo patrón que `tests/test_auth_api.py`, SPEC-013): se ejercita
el contrato HTTP real (rutas, códigos de estado, forma de la respuesta,
validación Pydantic) usando `app.dependency_overrides` para reemplazar
`get_current_user`/`get_tenant_db` sin requerir un Postgres vivo. Esto cubre:

  - #1 401 sin token en TODOS los routers de dominio (contacts, conversations,
    messages, documents, tenants, contacto 360°) -> ningún endpoint de datos
    queda desprotegido.
  - #2 422 ante payload inválido (antes de tocar la sesión de BD real).
  - #3 forma del OpenAPI (paths/tags/response_model) — ver
    `tests/test_openapi_contract.py`.

Lo que NO cubre (y por qué): el aislamiento cross-tenant real vía RLS y el
happy-path con persistencia real requieren PostgreSQL (dialecto UUID nativo,
`gen_random_uuid()`, políticas RLS) — SQLite no puede compilar el tipo UUID
de `sqlalchemy.dialects.postgresql`. Esos casos viven en
`tests/test_api_v1_integration.py` (Postgres real, SKIP documentado si no
hay daemon Docker, igual que `tests/test_rls_isolation.py` de SPEC-012).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app
from app.security.jwt import create_access_token


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_token():
    tenant_id = uuid.uuid4()
    token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, rol="agente")
    return token, tenant_id


@pytest.fixture
def override_deps_with_stub(auth_token):
    """Reemplaza `get_current_user`/`get_tenant_db` por un stub inerte: no
    toca Postgres real. Válido para probar 422 (la validación del body ocurre
    igual, incluso con dependencias resueltas) y la forma general del
    contrato en rutas GET que no requieren datos reales (se combinan con
    overrides adicionales por test cuando hace falta simular filas)."""
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


# ---------------------------------------------------------------------------
# Criterio: TODOS los endpoints de datos requieren JWT válido (401 sin token)
# ---------------------------------------------------------------------------

PROTECTED_ENDPOINTS = [
    ("GET", "/api/v1/tenants/me"),
    ("GET", "/api/v1/contacts"),
    ("POST", "/api/v1/contacts"),
    ("GET", f"/api/v1/contacts/{uuid.uuid4()}"),
    ("PATCH", f"/api/v1/contacts/{uuid.uuid4()}"),
    ("DELETE", f"/api/v1/contacts/{uuid.uuid4()}"),
    ("GET", f"/api/v1/contacts/{uuid.uuid4()}/360"),
    ("GET", "/api/v1/conversations"),
    ("POST", "/api/v1/conversations"),
    ("GET", f"/api/v1/conversations/{uuid.uuid4()}"),
    ("PATCH", f"/api/v1/conversations/{uuid.uuid4()}"),
    ("DELETE", f"/api/v1/conversations/{uuid.uuid4()}"),
    ("GET", f"/api/v1/conversations/{uuid.uuid4()}/messages"),
    ("POST", f"/api/v1/conversations/{uuid.uuid4()}/messages"),
    ("GET", f"/api/v1/conversations/{uuid.uuid4()}/messages/{uuid.uuid4()}"),
    ("DELETE", f"/api/v1/conversations/{uuid.uuid4()}/messages/{uuid.uuid4()}"),
    ("GET", "/api/v1/documents"),
    ("POST", "/api/v1/documents"),
    ("GET", f"/api/v1/documents/{uuid.uuid4()}"),
    ("DELETE", f"/api/v1/documents/{uuid.uuid4()}"),
    ("GET", "/api/v1/ai/health"),
]


@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
def test_endpoint_requires_auth_401_without_token(client, method, path):
    """Criterio de aceptación: ningún endpoint de datos es accesible sin JWT."""
    response = client.request(method, path)
    assert response.status_code == 401, f"{method} {path} debería exigir auth"
    assert response.json()["detail"] == "No autenticado"


@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
def test_endpoint_requires_auth_401_with_invalid_token(client, method, path):
    """Un token mal formado/con firma inválida también debe dar 401."""
    response = client.request(
        method, path, headers={"Authorization": "Bearer token-invalido"}
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Criterio: validación de entrada -> 422 (antes de tocar la BD)
# ---------------------------------------------------------------------------


def test_create_contact_rejects_empty_nombre_422(client, override_deps_with_stub):
    token = override_deps_with_stub
    response = client.post(
        "/api/v1/contacts",
        json={"nombre": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_create_contact_rejects_missing_nombre_422(client, override_deps_with_stub):
    token = override_deps_with_stub
    response = client.post(
        "/api/v1/contacts", json={}, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 422


def test_create_conversation_rejects_invalid_canal_422(client, override_deps_with_stub):
    token = override_deps_with_stub
    response = client.post(
        "/api/v1/conversations",
        json={"contact_id": str(uuid.uuid4()), "canal": "fax"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_create_conversation_rejects_invalid_contact_id_422(
    client, override_deps_with_stub
):
    token = override_deps_with_stub
    response = client.post(
        "/api/v1/conversations",
        json={"contact_id": "no-es-un-uuid"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_create_message_rejects_invalid_remitente_422(client, override_deps_with_stub):
    token = override_deps_with_stub
    response = client.post(
        f"/api/v1/conversations/{uuid.uuid4()}/messages",
        json={"remitente": "robot-desconocido", "contenido": "hola"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_create_message_rejects_empty_contenido_422(client, override_deps_with_stub):
    token = override_deps_with_stub
    response = client.post(
        f"/api/v1/conversations/{uuid.uuid4()}/messages",
        json={"remitente": "agente", "contenido": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_create_document_rejects_invalid_tipo_422(client, override_deps_with_stub):
    token = override_deps_with_stub
    response = client.post(
        "/api/v1/documents",
        json={"nombre_archivo": "manual.exe", "tipo": "exe"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_list_contacts_rejects_page_size_over_max_422(client, override_deps_with_stub):
    token = override_deps_with_stub
    response = client.get(
        "/api/v1/contacts",
        params={"page_size": 1000},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_list_contacts_rejects_negative_page_422(client, override_deps_with_stub):
    token = override_deps_with_stub
    response = client.get(
        "/api/v1/contacts",
        params={"page": -1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
