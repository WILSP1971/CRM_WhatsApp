"""
Tests de la API HTTP del plano-plataforma (`/api/v1/platform/...`) —
SPEC-076 (prueba SPEC-073/074/075, ADR-015).

Dos grupos de tests:

1. **Contrato HTTP sin Postgres** (patrón `tests/test_auth_api.py`): mockean
   la capa de servicio (`app.services.platform_auth_service`,
   `app.services.tenant_provisioning_service`) para ejercitar enrutamiento,
   mapeo de excepciones -> códigos HTTP, y la guard `require_platform_admin`
   vía JWTs reales (el guard en sí no toca BD salvo el SELECT final a
   `platform_admins`, que si se mockea evita requerir Postgres). Corren
   SIEMPRE, con o sin Postgres.

2. **Integración end-to-end con Postgres real** (RF-05/RF-06/CE-90/CE-92):
   alta real vía `POST /platform/tenants` + login inmediato del admin nuevo
   vía `POST /auth/login` (flujo EXISTENTE de tenant, SPEC-013). Requieren
   `app_engine`/`client` conectados a Postgres real; se SKIPEAN si no hay
   Postgres accesible (ver `tests/conftest.py`).

Cubre RF-05 (protección del endpoint: 401/403/201), RF-06 (login inmediato
200 + tenant_id/rol correctos), RF-07 (la respuesta 201 nunca expone
password/hash), RF-03 (409/422 nunca 500 a través del contrato HTTP).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security.jwt import create_access_token, create_platform_access_token


@pytest.fixture
def api_client():
    return TestClient(app)


def _platform_token(platform_admin_id: uuid.UUID | None = None) -> str:
    return create_platform_access_token(
        platform_admin_id=platform_admin_id or uuid.uuid4()
    )


def _tenant_token(tenant_id: uuid.UUID | None = None, rol: str = "agente") -> str:
    return create_access_token(
        user_id=uuid.uuid4(), tenant_id=tenant_id or uuid.uuid4(), rol=rol
    )


# ---------------------------------------------------------------------------
# RF-05/CE-92 — protección del endpoint (sin Postgres: la guard requiere un
# SELECT final a platform_admins, que se mockea para aislar el contrato HTTP
# de enrutamiento/mapeo de errores de la disponibilidad de BD real).
# ---------------------------------------------------------------------------


def test_create_tenant_without_credentials_returns_401(api_client):
    response = api_client.post(
        "/api/v1/platform/tenants",
        json={
            "nombre": "Clinica X",
            "slug": "clinica-x",
            "admin_email": "admin@clinica-x.test",
            "admin_password": "ClaveValida123",
            "admin_nombre": "Admin X",
        },
    )
    assert response.status_code == 401


def test_create_tenant_with_malformed_bearer_returns_401(api_client):
    response = api_client.post(
        "/api/v1/platform/tenants",
        headers={"Authorization": "Bearer token-basura-no-es-un-jwt"},
        json={
            "nombre": "Clinica X",
            "slug": "clinica-x",
            "admin_email": "admin@clinica-x.test",
            "admin_password": "ClaveValida123",
            "admin_nombre": "Admin X",
        },
    )
    assert response.status_code == 401


def test_create_tenant_with_tenant_jwt_returns_403_not_401(api_client):
    """JWT de agente/admin de un TENANT normal (SPEC-013) presentado en el
    endpoint de plataforma -> 403 (token válido, plano equivocado), NUNCA
    401 (que implicaría "no autenticado")."""
    token = _tenant_token(rol="admin")
    response = api_client.post(
        "/api/v1/platform/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "nombre": "Clinica X",
            "slug": "clinica-x",
            "admin_email": "admin@clinica-x.test",
            "admin_password": "ClaveValida123",
            "admin_nombre": "Admin X",
        },
    )
    assert response.status_code == 403


def test_create_tenant_with_valid_platform_admin_returns_201(api_client, monkeypatch):
    """Admin de plataforma válido (JWT + fila activa en `platform_admins`,
    mockeada aquí para no requerir Postgres) -> 201, con la respuesta
    `{tenant_id, slug}` y SIN password/hash (RF-05/RF-07)."""
    from types import SimpleNamespace

    import app.api.platform as platform_router_module
    import app.api.platform_deps as platform_deps_module

    platform_admin_id = uuid.uuid4()
    fake_admin = SimpleNamespace(
        id=platform_admin_id, email="admin@plataforma.test", activo=True
    )

    def fake_require_platform_admin():
        return fake_admin

    nuevo_tenant_id = uuid.uuid4()
    nuevo_admin_id = uuid.uuid4()

    def fake_provision_tenant(db, **kwargs):
        from app.services.tenant_provisioning_service import ProvisionedTenant

        assert kwargs["admin_password"] == "ClaveValida123"
        return ProvisionedTenant(
            tenant_id=nuevo_tenant_id, slug=kwargs["slug"], admin_user_id=nuevo_admin_id
        )

    monkeypatch.setattr(
        platform_router_module, "provision_tenant", fake_provision_tenant
    )
    app.dependency_overrides[platform_deps_module.require_platform_admin] = (
        fake_require_platform_admin
    )
    try:
        response = api_client.post(
            "/api/v1/platform/tenants",
            headers={"Authorization": f"Bearer {_platform_token(platform_admin_id)}"},
            json={
                "nombre": "Clinica X",
                "slug": "clinica-x",
                "admin_email": "admin@clinica-x.test",
                "admin_password": "ClaveValida123",
                "admin_nombre": "Admin X",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body == {"tenant_id": str(nuevo_tenant_id), "slug": "clinica-x"}
    assert "password" not in response.text
    assert "hash" not in response.text


# ---------------------------------------------------------------------------
# RF-03 — unicidad tipada / validación vía contrato HTTP (nunca 500)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "excepcion_modulo,status_esperado",
    [
        ("SlugCollisionError", 409),
        ("EmailCollisionError", 409),
        ("InvalidSlugError", 422),
        ("InvalidPasswordError", 422),
        ("InvalidFieldError", 422),
    ],
)
def test_create_tenant_maps_domain_exceptions_to_expected_status(
    api_client, monkeypatch, excepcion_modulo, status_esperado
):
    from types import SimpleNamespace

    import app.api.platform as platform_router_module
    import app.api.platform_deps as platform_deps_module
    import app.services.tenant_provisioning_service as svc_module

    excepcion_cls = getattr(svc_module, excepcion_modulo)

    def fake_require_platform_admin():
        return SimpleNamespace(id=uuid.uuid4(), activo=True)

    def fake_provision_tenant_que_falla(db, **kwargs):
        raise excepcion_cls("fallo de dominio simulado")

    monkeypatch.setattr(
        platform_router_module, "provision_tenant", fake_provision_tenant_que_falla
    )
    app.dependency_overrides[platform_deps_module.require_platform_admin] = (
        fake_require_platform_admin
    )
    try:
        response = api_client.post(
            "/api/v1/platform/tenants",
            headers={"Authorization": f"Bearer {_platform_token()}"},
            json={
                "nombre": "Clinica X",
                "slug": "clinica-x",
                "admin_email": "admin@clinica-x.test",
                "admin_password": "ClaveValida123",
                "admin_nombre": "Admin X",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == status_esperado
    assert response.status_code != 500


def test_create_tenant_without_credentials_and_malformed_payload_returns_401(
    api_client,
):
    """FastAPI evalúa la dependencia (`require_platform_admin`) ANTES de
    validar el body: sin credenciales, un payload también inválido sigue
    devolviendo 401 (la ausencia de autenticación manda), no 422 -- se deja
    explícito para no confundir este caso con el de abajo."""
    response = api_client.post(
        "/api/v1/platform/tenants",
        json={
            "nombre": "Clinica X",
            "slug": "clinica-x",
            "admin_email": "no-es-un-email",
            "admin_password": "corta",
            "admin_nombre": "Admin X",
        },
    )
    assert response.status_code == 401


def test_create_tenant_with_valid_credentials_and_malformed_payload_returns_422(
    api_client,
):
    """Con un admin de plataforma autenticado (guard mockeada vía
    `dependency_overrides`, sin requerir Postgres real), un payload con
    formato inválido (email mal formado, password corta) SÍ se valida por
    Pydantic -> 422, antes de llegar al servicio (RF-03)."""
    from types import SimpleNamespace

    import app.api.platform_deps as platform_deps_module

    app.dependency_overrides[platform_deps_module.require_platform_admin] = (
        lambda: SimpleNamespace(id=uuid.uuid4(), activo=True)
    )
    try:
        response = api_client.post(
            "/api/v1/platform/tenants",
            headers={"Authorization": f"Bearer {_platform_token()}"},
            json={
                "nombre": "Clinica X",
                "slug": "clinica-x",
                "admin_email": "no-es-un-email",
                "admin_password": "corta",
                "admin_nombre": "Admin X",
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Login de plataforma — contrato HTTP
# ---------------------------------------------------------------------------


def test_platform_login_invalid_credentials_returns_401(api_client, monkeypatch):
    import app.api.platform as platform_router_module
    from app.services.platform_auth_service import InvalidPlatformCredentialsError

    def fake_authenticate_platform_admin(db, *, email, password):
        raise InvalidPlatformCredentialsError("Credenciales inválidas")

    monkeypatch.setattr(
        platform_router_module,
        "authenticate_platform_admin",
        fake_authenticate_platform_admin,
    )

    response = api_client.post(
        "/api/v1/platform/auth/login",
        json={"email": "nadie@plataforma.test", "password": "incorrecta"},
    )
    assert response.status_code == 401
    assert "password" not in response.text


def test_platform_login_valid_credentials_returns_token(api_client, monkeypatch):
    import app.api.platform as platform_router_module
    from app.services.platform_auth_service import PlatformLoginResult
    from types import SimpleNamespace

    def fake_authenticate_platform_admin(db, *, email, password):
        token = _platform_token()
        return PlatformLoginResult(
            access_token=token,
            expires_in_seconds=1800,
            platform_admin=SimpleNamespace(id=uuid.uuid4()),
        )

    monkeypatch.setattr(
        platform_router_module,
        "authenticate_platform_admin",
        fake_authenticate_platform_admin,
    )

    response = api_client.post(
        "/api/v1/platform/auth/login",
        json={"email": "admin@plataforma.test", "password": "ClaveValida123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert "access_token" in body and body["access_token"]
    assert "password" not in response.text
    assert "hash" not in response.text


# ---------------------------------------------------------------------------
# Integración end-to-end con Postgres real: alta real + login inmediato
# (RF-06/CE-90, RF-05/CE-92 con platform_admin persistido de verdad).
# ---------------------------------------------------------------------------


@pytest.fixture
def platform_admin_in_db(app_engine):
    """Crea un `platform_admin` real (rol `omnicore_app`, tabla sin RLS) y
    devuelve `(id, email, password_plain)`. Requiere Postgres real."""
    import sqlalchemy as sa

    from app.security.passwords import hash_password

    admin_id = uuid.uuid4()
    email = f"platform-admin-{uuid.uuid4().hex[:8]}@plataforma.test"
    password_plain = "ClavePlataforma#Valida123"

    with app_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO platform_admins (id, email, password_hash, nombre, "
                "activo, created_at, updated_at) VALUES "
                "(:id, :email, :password_hash, :nombre, true, now(), now())"
            ),
            {
                "id": admin_id,
                "email": email,
                "password_hash": hash_password(password_plain),
                "nombre": "Admin de Plataforma de Prueba",
            },
        )

    return {"id": admin_id, "email": email, "password": password_plain}


# ---------------------------------------------------------------------------
# `authenticate_platform_admin` real (sin mockear) contra Postgres real:
# RNF-COBERTURA -- este servicio nunca se ejercita de verdad en los tests de
# contrato HTTP de arriba (todos mockean `authenticate_platform_admin`), así
# que la verificación de password/estado `activo` necesita su propio test
# de integración.
# ---------------------------------------------------------------------------


def test_authenticate_platform_admin_with_valid_credentials_returns_token(
    app_engine, platform_admin_in_db
):
    from sqlalchemy.orm import Session

    from app.services.platform_auth_service import authenticate_platform_admin

    with Session(app_engine) as db:
        resultado = authenticate_platform_admin(
            db,
            email=platform_admin_in_db["email"],
            password=platform_admin_in_db["password"],
        )
    assert resultado.access_token
    assert resultado.expires_in_seconds > 0
    assert resultado.platform_admin.id == platform_admin_in_db["id"]


def test_authenticate_platform_admin_with_wrong_password_raises_invalid_credentials(
    app_engine, platform_admin_in_db
):
    from sqlalchemy.orm import Session

    from app.services.platform_auth_service import (
        InvalidPlatformCredentialsError,
        authenticate_platform_admin,
    )

    with Session(app_engine) as db:
        with pytest.raises(InvalidPlatformCredentialsError):
            authenticate_platform_admin(
                db,
                email=platform_admin_in_db["email"],
                password="password-incorrecta-no-es-la-real",
            )


def test_authenticate_platform_admin_with_unknown_email_raises_invalid_credentials(
    app_engine,
):
    from sqlalchemy.orm import Session

    from app.services.platform_auth_service import (
        InvalidPlatformCredentialsError,
        authenticate_platform_admin,
    )

    with Session(app_engine) as db:
        with pytest.raises(InvalidPlatformCredentialsError):
            authenticate_platform_admin(
                db,
                email=f"nadie-{uuid.uuid4().hex[:8]}@plataforma.test",
                password="cualquier-cosa",
            )


def test_authenticate_platform_admin_with_inactive_admin_raises_invalid_credentials(
    app_engine,
):
    """Mismo criterio que `auth_service.authenticate` para usuarios de
    tenant inactivos: un `platform_admin` desactivado (C2, borrado lógico)
    nunca se autentica, con el MISMO mensaje genérico que email inexistente
    o password incorrecta (sin filtrar la causa)."""
    import sqlalchemy as sa
    from sqlalchemy.orm import Session

    from app.security.passwords import hash_password
    from app.services.platform_auth_service import (
        InvalidPlatformCredentialsError,
        authenticate_platform_admin,
    )

    admin_id = uuid.uuid4()
    email = f"inactivo-auth-{uuid.uuid4().hex[:8]}@plataforma.test"
    password_plain = "ClaveInactivaAuth#2026"
    with app_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO platform_admins (id, email, password_hash, nombre, "
                "activo, created_at, updated_at) VALUES "
                "(:id, :email, :password_hash, :nombre, false, now(), now())"
            ),
            {
                "id": admin_id,
                "email": email,
                "password_hash": hash_password(password_plain),
                "nombre": "Admin Inactivo Auth",
            },
        )

    with Session(app_engine) as db:
        with pytest.raises(InvalidPlatformCredentialsError):
            authenticate_platform_admin(db, email=email, password=password_plain)


@pytest.fixture
def end_to_end_client(app_engine, monkeypatch):
    """`TestClient` cuyas dependencias `get_db`/sesión usan `app_engine`
    (rol de aplicación real, ADR-008) en vez del engine por defecto de
    `app.db.session` (que podría apuntar a una BD distinta en este proceso
    de test). Sobreescribe `get_db` (usado por los routers vía `Depends`)
    para servir sesiones de `app_engine`.

    IMPORTANTE: `require_platform_admin` (`app/api/platform_deps.py`) NO usa
    `Depends(get_db)` -- llama directamente a `SessionLocal()` (el
    `sessionmaker` module-level de `app.db.session`, ligado a `engine`). Un
    `dependency_overrides[get_db]` NO lo alcanza. Para que el guard también
    lea el `platform_admin` recién insertado en `app_engine` (y no en el
    `engine` por defecto, que podría apuntar a otra URL/rol en este proceso
    de test), se monkeypatchea el `SessionLocal` que usa el módulo
    `app.api.platform_deps` para que produzca sesiones de `app_engine`."""
    from sqlalchemy.orm import sessionmaker

    from app.db.session import get_db

    _AppSessionLocal = sessionmaker(bind=app_engine, future=True)

    def fake_get_db():
        db = _AppSessionLocal()
        try:
            yield db
        finally:
            db.close()

    import app.api.platform_deps as platform_deps_module

    monkeypatch.setattr(platform_deps_module, "SessionLocal", _AppSessionLocal)
    app.dependency_overrides[get_db] = fake_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_end_to_end_provision_then_login_as_new_admin(
    end_to_end_client, platform_admin_in_db
):
    """RF-06/CE-90: alta real vía `POST /platform/tenants` (protegida por un
    `platform_admin` real) -> login inmediato del primer admin del tenant
    nuevo vía el flujo EXISTENTE `/auth/login` (SPEC-013) -> 200, con
    `tenant_id` correcto y `rol="admin"`."""
    from app.security.jwt import decode_access_token

    slug = f"clinica-e2e-{uuid.uuid4().hex[:8]}"
    admin_email = f"admin-e2e-{uuid.uuid4().hex[:8]}@clinica-e2e.test"
    admin_password = "ClaveNuevoAdmin#2026"

    platform_token = create_platform_access_token(
        platform_admin_id=platform_admin_in_db["id"]
    )

    create_response = end_to_end_client.post(
        "/api/v1/platform/tenants",
        headers={"Authorization": f"Bearer {platform_token}"},
        json={
            "nombre": "Clinica E2E",
            "slug": slug,
            "admin_email": admin_email,
            "admin_password": admin_password,
            "admin_nombre": "Admin E2E",
        },
    )
    assert create_response.status_code == 201, create_response.text
    body = create_response.json()
    assert body["slug"] == slug
    assert "password" not in create_response.text
    assert "hash" not in create_response.text
    tenant_id = body["tenant_id"]

    login_response = end_to_end_client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": slug,
            "email": admin_email,
            "password": admin_password,
        },
    )
    assert login_response.status_code == 200, login_response.text
    login_body = login_response.json()
    payload = decode_access_token(login_body["access_token"])
    assert payload.tenant_id == tenant_id
    assert payload.rol == "admin"


def test_end_to_end_create_tenant_with_duplicate_slug_returns_409(
    end_to_end_client, platform_admin_in_db
):
    slug = f"clinica-e2e-dup-{uuid.uuid4().hex[:8]}"
    platform_token = create_platform_access_token(
        platform_admin_id=platform_admin_in_db["id"]
    )
    payload = {
        "nombre": "Clinica Duplicada",
        "slug": slug,
        "admin_email": f"admin-dup-{uuid.uuid4().hex[:8]}@clinica-dup.test",
        "admin_password": "ClaveDuplicada#2026",
        "admin_nombre": "Admin Duplicado",
    }

    first = end_to_end_client.post(
        "/api/v1/platform/tenants",
        headers={"Authorization": f"Bearer {platform_token}"},
        json=payload,
    )
    assert first.status_code == 201

    payload["admin_email"] = f"otro-{uuid.uuid4().hex[:8]}@clinica-dup.test"
    second = end_to_end_client.post(
        "/api/v1/platform/tenants",
        headers={"Authorization": f"Bearer {platform_token}"},
        json=payload,
    )
    assert second.status_code == 409
    assert second.status_code != 500


def test_end_to_end_inactive_platform_admin_returns_401(end_to_end_client, app_engine):
    """Un `platform_admin` desactivado (borrado lógico, C2) con un JWT que en
    su momento fue válido debe ser rechazado con 401 (mismo criterio que
    `get_current_user` para usuarios de tenant inactivos)."""
    import sqlalchemy as sa

    from app.security.passwords import hash_password

    admin_id = uuid.uuid4()
    email = f"inactivo-{uuid.uuid4().hex[:8]}@plataforma.test"
    with app_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO platform_admins (id, email, password_hash, nombre, "
                "activo, created_at, updated_at) VALUES "
                "(:id, :email, :password_hash, :nombre, false, now(), now())"
            ),
            {
                "id": admin_id,
                "email": email,
                "password_hash": hash_password("ClaveInactiva#2026"),
                "nombre": "Admin Inactivo",
            },
        )

    token = create_platform_access_token(platform_admin_id=admin_id)
    response = end_to_end_client.post(
        "/api/v1/platform/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "nombre": "Clinica Inactivo",
            "slug": f"clinica-inactivo-{uuid.uuid4().hex[:8]}",
            "admin_email": f"admin-{uuid.uuid4().hex[:8]}@clinica-inactivo.test",
            "admin_password": "ClaveValida123",
            "admin_nombre": "Admin Inactivo Test",
        },
    )
    assert response.status_code == 401
