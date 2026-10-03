"""
Tests de cabeceras de seguridad HTTP (SPEC-021, criterio "headers presentes").

No requieren Postgres/Redis/Docker: usan el fixture `client` compartido
(`tests/conftest.py`, `TestClient` sobre `app.main.app`), mismo patrón que
`tests/test_healthz.py`.
"""

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def _reload_main_in_development(monkeypatch):
    """Reconstruye `app.main` con `ENVIRONMENT=development` explícito (mismo
    patrón que `tests/test_openapi_contract.py::_reload_main_with_env`).

    Necesario porque `_docs_enabled`/`docs_url`/`redoc_url` se calculan en
    tiempo de IMPORT de `app.main` a partir de la env var — si otro test del
    proceso (p.ej. `test_openapi_contract.py::test_docs_endpoint_disabled_outside_development`)
    ya recargó el módulo con `ENVIRONMENT=production`, el objeto `app.main.app`
    global queda con Swagger/ReDoc deshabilitados para el resto del proceso,
    dando un falso 404 en este test si se usara el fixture `client` genérico.
    Se aísla explícitamente en vez de depender del orden de ejecución de la
    suite completa."""
    for key in ("ENVIRONMENT", "JWT_SECRET_KEY", "DB_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")

    import app.main as main_module

    importlib.reload(main_module)
    return main_module


def test_healthz_response_includes_security_headers(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert "max-age=" in response.headers["Strict-Transport-Security"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert "camera=()" in response.headers["Permissions-Policy"]


def test_hsts_max_age_is_exactly_one_year_with_subdomains(client):
    """CE-110/D-1 (PLAN-011 §11.2): HSTS de PRODUCCIÓN = 1 año
    (`max-age=31536000`) + `includeSubDomains` — el valor concreto que
    `DEPLOYMENT_CHECKLIST.md` exige como fuente de verdad más estricta
    (180 días del código anterior quedó endurecido por SPEC-083)."""
    response = client.get("/healthz")

    assert (
        response.headers["Strict-Transport-Security"]
        == "max-age=31536000; includeSubDomains"
    )


def test_csp_on_api_routes_has_no_unsafe_inline(client):
    """CE-110/D-1: la CSP estricta global (`/api/*`, `/healthz`, `/metrics`,
    etc.) NUNCA lleva `'unsafe-inline'` — esa relajación existe SOLO como
    excepción acotada para `/docs`/`/redoc` (ver
    `test_docs_route_receives_the_acotated_relaxed_csp_override` abajo)."""
    response = client.get("/healthz")
    csp = response.headers["Content-Security-Policy"]

    assert "'unsafe-inline'" not in csp
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_docs_route_receives_the_acotated_relaxed_csp_override(monkeypatch):
    """CE-110/D-1: SOLO `/docs`/`/redoc` reciben la CSP relajada (necesaria
    para que Swagger UI/ReDoc rendericen estilos/JS inline) — ninguna otra
    ruta de la API debe recibir esta excepción (`development`, único
    entorno donde estas rutas responden 200 — ver
    `tests/test_openapi_contract.py` para la verificación de que están
    deshabilitadas fuera de `development`).

    Fuerza `ENVIRONMENT=development` explícitamente (ver
    `_reload_main_in_development`) en vez de usar el fixture `client`
    genérico: el estado del módulo `app.main` es compartido por proceso, y
    otro test de la suite puede haberlo dejado en modo no-development."""
    main_module = _reload_main_in_development(monkeypatch)
    client = TestClient(main_module.app)

    docs_response = client.get("/docs")
    redoc_response = client.get("/redoc")

    assert docs_response.status_code == 200
    assert redoc_response.status_code == 200
    assert "'unsafe-inline'" in docs_response.headers["Content-Security-Policy"]
    assert "'unsafe-inline'" in redoc_response.headers["Content-Security-Policy"]

    # La ruta plana de la API sigue estricta en la MISMA app (no es un modo
    # global activado por la presencia de /docs).
    api_response = client.get("/healthz")
    assert "'unsafe-inline'" not in api_response.headers["Content-Security-Policy"]


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
