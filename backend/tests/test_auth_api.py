"""
Tests de API HTTP de autenticación (SPEC-013) — SIN Postgres/Redis reales.

Estrategia: se mockea la capa de acceso a datos (`app.services.auth_service`)
y las dependencias de FastAPI (`app.api.deps`) con `dependency_overrides` /
monkeypatch, para ejercitar el contrato HTTP real (rutas, códigos de estado,
esquema de respuesta) sin requerir un Postgres vivo. Esto es fiel para lo que
prueba (enrutamiento, validación de payload, mapeo de errores a códigos HTTP,
forma del JWT emitido) pero NO reemplaza la prueba de aislamiento RLS real
(esa vive en `tests/test_rls_isolation.py` / `test_auth_cross_tenant_rls.py`,
que requieren Postgres y se SKIPEAN documentadamente si no está disponible;
ver `tests/conftest.py`).

Cubre criterios de aceptación de SPEC-013:
  - #2 `POST /auth/login` con credenciales válidas emite JWT; inválidas -> 401.
  - #6 Endpoints protegidos devuelven 401 sin token válido.
  - #7 Rate-limit de login (429 tras exceder intentos).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app
from app.services import auth_service


@pytest.fixture
def client():
    return TestClient(app)


def _fake_user(tenant_id: uuid.UUID, rol: str = "agente") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        email="agente@tenant-a.test",
        nombre="Agente de Prueba",
        rol=rol,
        activo=True,
    )


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


def test_login_valid_credentials_returns_token_with_tenant(client, monkeypatch):
    tenant_id = uuid.uuid4()
    fake_user = _fake_user(tenant_id)

    def fake_authenticate(db, *, tenant_slug, email, password):
        assert tenant_slug == "tenant-a"
        assert email == "agente@tenant-a.test"
        assert password == "ClaveValida123"
        from app.security.jwt import create_access_token

        token = create_access_token(
            user_id=fake_user.id, tenant_id=fake_user.tenant_id, rol=fake_user.rol
        )
        return auth_service.LoginResult(
            access_token=token, expires_in_seconds=1800, user=fake_user
        )

    monkeypatch.setattr(auth_service, "authenticate", fake_authenticate)
    # El router importó `authenticate` por nombre; parchea también esa referencia.
    import app.api.auth as auth_router_module

    monkeypatch.setattr(auth_router_module, "authenticate", fake_authenticate)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "tenant-a",
            "email": "agente@tenant-a.test",
            "password": "ClaveValida123",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data and data["access_token"]
    assert data["token_type"] == "bearer"

    from app.security.jwt import decode_access_token

    decoded = decode_access_token(data["access_token"])
    assert decoded.tenant_id == str(tenant_id)


def test_login_invalid_credentials_returns_401_without_leaking_info(
    client, monkeypatch
):
    import app.api.auth as auth_router_module

    def fake_authenticate(db, *, tenant_slug, email, password):
        raise auth_service.InvalidCredentialsError("Credenciales inválidas")

    monkeypatch.setattr(auth_router_module, "authenticate", fake_authenticate)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "tenant-a",
            "email": "nadie@tenant-a.test",
            "password": "incorrecta",
        },
    )

    assert response.status_code == 401
    body = response.json()
    # No debe distinguir "tenant no existe" de "password incorrecta".
    assert body["detail"] == "Credenciales inválidas"


def test_login_rate_limited_returns_429(client, monkeypatch):
    import app.api.auth as auth_router_module

    def fake_authenticate(db, *, tenant_slug, email, password):
        raise auth_service.RateLimitedError(retry_after_seconds=42)

    monkeypatch.setattr(auth_router_module, "authenticate", fake_authenticate)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "tenant-a",
            "email": "agente@tenant-a.test",
            "password": "cualquiera",
        },
    )

    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "42"


def test_login_rejects_malformed_payload(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "tenant-a", "email": "no-es-un-email", "password": "x"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Endpoints protegidos: /auth/me, /auth/logout (criterio #6)
# ---------------------------------------------------------------------------


def test_me_without_token_returns_401(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_with_invalid_token_returns_401(client):
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer token-invalido"}
    )
    assert response.status_code == 401


def test_me_with_valid_token_returns_current_user(client, monkeypatch):
    tenant_id = uuid.uuid4()
    fake_user = _fake_user(tenant_id, rol="admin")

    from app.security.jwt import create_access_token

    token = create_access_token(
        user_id=fake_user.id, tenant_id=tenant_id, rol=fake_user.rol
    )

    def fake_get_current_user():
        return fake_user

    def fake_get_tenant_db():
        yield None  # no se toca BD real en este test de contrato HTTP

    app.dependency_overrides[deps.get_current_user] = fake_get_current_user
    app.dependency_overrides[deps.get_tenant_db] = fake_get_tenant_db
    try:
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == fake_user.email
    assert data["rol"] == "admin"
    assert data["tenant_id"] == str(tenant_id)
    assert "password_hash" not in data


def test_logout_without_token_returns_401(client):
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 401


def test_logout_with_valid_token_returns_200(client):
    fake_user = _fake_user(uuid.uuid4())

    def fake_get_current_user():
        return fake_user

    app.dependency_overrides[deps.get_current_user] = fake_get_current_user
    try:
        response = client.post("/api/v1/auth/logout")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
