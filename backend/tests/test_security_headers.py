"""
Tests de cabeceras de seguridad HTTP (SPEC-021, criterio "headers presentes").

No requieren Postgres/Redis/Docker: usan el fixture `client` compartido
(`tests/conftest.py`, `TestClient` sobre `app.main.app`), mismo patrón que
`tests/test_healthz.py`.
"""

from __future__ import annotations


def test_healthz_response_includes_security_headers(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert "max-age=" in response.headers["Strict-Transport-Security"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert "camera=()" in response.headers["Permissions-Policy"]


def test_security_headers_present_on_error_responses_too(client):
    """Las cabeceras deben aplicar también a respuestas de error (401/404)."""
    response = client.get("/api/v1/contacts")  # sin JWT -> 401

    assert response.status_code == 401
    assert "Strict-Transport-Security" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_request_id_header_present_and_stable_per_request(client):
    response = client.get("/healthz")
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


def test_request_id_is_propagated_when_provided_by_client(client):
    custom_id = "trace-abc-123"
    response = client.get("/healthz", headers={"X-Request-ID": custom_id})
    assert response.headers["X-Request-ID"] == custom_id


def test_request_id_differs_across_requests_when_not_provided(client):
    r1 = client.get("/healthz")
    r2 = client.get("/healthz")
    assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]
