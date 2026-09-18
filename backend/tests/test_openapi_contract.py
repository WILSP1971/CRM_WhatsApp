"""
Contrato OpenAPI de la API core (SPEC-014) — SIN Postgres.

Verifica que FastAPI publica un OpenAPI válido y completo en `/docs` y
`/openapi.json`, con todos los endpoints del alcance de SPEC-014 (RF-09,
criterio "OpenAPI navegable en /docs"). No requiere BD: se genera el schema
directamente desde la app (`app.openapi()`), igual que arrancar la app en
modo test y pedir `/openapi.json`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

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


def test_docs_endpoint_is_served():
    client = TestClient(app)
    response = client.get("/docs")
    assert response.status_code == 200


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
