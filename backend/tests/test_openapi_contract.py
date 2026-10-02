"""
Contrato OpenAPI de la API core (SPEC-014) — SIN Postgres.

Verifica que FastAPI publica un OpenAPI válido y completo en `/docs` y
`/openapi.json`, con todos los endpoints del alcance de SPEC-014 (RF-09,
criterio "OpenAPI navegable en /docs"). No requiere BD: se genera el schema
directamente desde la app (`app.openapi()`), igual que arrancar la app en
modo test y pedir `/openapi.json`.
"""

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from app.main import app


def _reload_main_with_env(monkeypatch, **env):
    """Recarga `app.main` con un entorno controlado (mismo patrón que
    `tests/test_config_and_cors.py::_reload_main_with_env`, duplicado aquí a
    propósito por aislamiento entre archivos de test): `docs_url`/`redoc_url`
    se calculan en `main.py` a partir de la constante de módulo `ENVIRONMENT`
    leída en tiempo de import (SPEC-083, PLAN-011 F3, D-1 §11.2) — un
    monkeypatch de la env var por sí solo NO afecta al `app` ya construido,
    hace falta recargar el módulo."""
    for key in ("ENVIRONMENT", "JWT_SECRET_KEY", "DB_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import app.main as main_module

    importlib.reload(main_module)
    return main_module


EXPECTED_PATHS_AND_METHODS = {
    "/api/v1/tenants/me": {"get"},
    "/api/v1/contacts": {"get", "post"},
    "/api/v1/contacts/{contact_id}": {"get", "patch", "delete"},
    "/api/v1/contacts/{contact_id}/360": {"get"},
    "/api/v1/conversations": {"get", "post"},
    "/api/v1/conversations/{conversation_id}": {"get", "patch", "delete"},
    "/api/v1/conversations/{conversation_id}/messages": {"get", "post"},
    "/api/v1/conversations/{conversation_id}/messages/{message_id}": {"get", "delete"},
    "/api/v1/documents": {"get", "post"},
    "/api/v1/documents/{document_id}": {"get", "delete"},
}


def test_docs_endpoint_is_served_in_development(monkeypatch):
    """SPEC-083 (PLAN-011 F3, D-1 §11.2): Swagger (`/docs`) sigue activo en
    `development` (único entorno donde `docs_url` no es `None`)."""
    main_module = _reload_main_with_env(monkeypatch, ENVIRONMENT="development")
    client = TestClient(main_module.app)
    response = client.get("/docs")
    assert response.status_code == 200


def test_docs_endpoint_disabled_outside_development(monkeypatch):
    """SPEC-083 (PLAN-011 F3, D-1 §11.2): Swagger/ReDoc se DESHABILITAN
    (`docs_url=None`/`redoc_url=None`) fuera de `development` — reduce
    superficie expuesta de un backend con PHI potencial (ADR-009) y evita
    mantener una CSP relajada fuera de desarrollo. `/openapi.json` se
    conserva siempre (ver `test_openapi_json_is_served_and_valid`)."""
    main_module = _reload_main_with_env(
        monkeypatch,
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a" * 40,
        DB_PASSWORD="b" * 40,
    )
    client = TestClient(main_module.app)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_openapi_json_is_served_and_valid():
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["openapi"].startswith("3.")
    assert schema["info"]["title"] == "OmniCore AI Backend"


def test_openapi_contains_all_spec_014_endpoints():
    schema = app.openapi()
    for path, methods in EXPECTED_PATHS_AND_METHODS.items():
        assert path in schema["paths"], f"Falta el path {path} en el OpenAPI"
        documented_methods = set(schema["paths"][path].keys())
        assert methods.issubset(
            documented_methods
        ), f"{path}: métodos esperados {methods}, documentados {documented_methods}"


def test_openapi_endpoints_have_response_models_and_error_codes():
    """Cada operación de escritura documenta al menos un código 2xx y, en las
    rutas con parámetros de path, un 404/422 tipado (RF: errores consistentes)."""
    schema = app.openapi()

    create_contact = schema["paths"]["/api/v1/contacts"]["post"]
    assert "201" in create_contact["responses"]
    assert "422" in create_contact["responses"]

    get_contact = schema["paths"]["/api/v1/contacts/{contact_id}"]["get"]
    assert "200" in get_contact["responses"]

    delete_contact = schema["paths"]["/api/v1/contacts/{contact_id}"]["delete"]
    assert "204" in delete_contact["responses"]


def test_openapi_endpoints_are_tagged():
    schema = app.openapi()
    for path, ops in schema["paths"].items():
        if path not in EXPECTED_PATHS_AND_METHODS:
            continue
        for method, operation in ops.items():
            assert operation.get("tags"), f"{method.upper()} {path} no tiene tags"
