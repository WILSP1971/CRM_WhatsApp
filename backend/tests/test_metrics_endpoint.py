"""Tests del endpoint `GET /metrics` y de la instrumentación de latencia —
SPEC-022 (RNF-06 observabilidad, THOR/p95 RAG RNF-04).

No requiere Postgres/Redis/Ollama real: usa `TestClient` (que genera
peticiones HTTP reales al middleware de métricas) y mockea `AIClient` a
nivel de transporte HTTP (como `test_ai_service.py`) para verificar que
`ai_request_duration_seconds` se registra por operación.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.metrics import REGISTRY
from app.main import app
from app.services.ai_service import AIClient


@pytest.fixture
def client():
    return TestClient(app)


def test_metrics_endpoint_returns_prometheus_text_format(client):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    # Formato de exposición Prometheus: comentarios HELP/TYPE por métrica.
    assert "# HELP http_requests_total" in response.text
    assert "# TYPE http_request_duration_seconds histogram" in response.text
    assert "# TYPE ai_request_duration_seconds histogram" in response.text


def test_metrics_endpoint_counts_http_requests(client):
    # Genera al menos una petición conocida antes de leer /metrics.
    client.get("/healthz")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert 'http_requests_total{method="GET",path="/healthz",status_code="200"}' in (
        response.text
    )


def test_metrics_endpoint_never_exposes_internal_ai_base_url(client):
    """Igual que `test_ai_health_never_exposes_internal_base_url`: las
    métricas no deben filtrar la topología de red interna del servicio IA."""
    response = client.get("/metrics")

    assert "11434" not in response.text
    assert "http://ia" not in response.text


def test_ai_client_chat_records_duration_histogram():
    """`AIClient.chat()` debe registrar una observación en
    `ai_request_duration_seconds{operation="chat", model=...}` (usada por
    THOR para el p95 RAG de RNF-04)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"content": "hola"}, "model": "qwen2.5:7b-instruct"}
        )

    transport = httpx.MockTransport(handler)
    httpx_client = httpx.Client(base_url="http://ia:11434", transport=transport)
    ai_client = AIClient(base_url="http://ia:11434", client=httpx_client)

    before = (
        REGISTRY.get_sample_value(
            "ai_request_duration_seconds_count",
            {"operation": "chat", "model": "qwen2.5:7b-instruct"},
        )
        or 0.0
    )

    ai_client.chat([{"role": "user", "content": "hola"}])

    after = REGISTRY.get_sample_value(
        "ai_request_duration_seconds_count",
        {"operation": "chat", "model": "qwen2.5:7b-instruct"},
    )

    assert after == before + 1.0


def test_ai_client_embed_records_duration_histogram():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    transport = httpx.MockTransport(handler)
    httpx_client = httpx.Client(base_url="http://ia:11434", transport=transport)
    ai_client = AIClient(
        base_url="http://ia:11434",
        client=httpx_client,
        embedding_model="nomic-embed-text",
    )

    before = (
        REGISTRY.get_sample_value(
            "ai_request_duration_seconds_count",
            {"operation": "embed", "model": "nomic-embed-text"},
        )
        or 0.0
    )

    ai_client.embed("texto de prueba")

    after = REGISTRY.get_sample_value(
        "ai_request_duration_seconds_count",
        {"operation": "embed", "model": "nomic-embed-text"},
    )

    assert after == before + 1.0


def test_ai_client_error_increments_error_counter():
    """Un error de IA (timeout/conexión) se cuenta en
    `ai_request_errors_total{operation, error_type}` sin ocultar la excepción
    (modo degradado R-21, pero observable)."""
    from app.services.ai_service import AIServiceUnavailableError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conexión rechazada", request=request)

    transport = httpx.MockTransport(handler)
    httpx_client = httpx.Client(base_url="http://ia:11434", transport=transport)
    ai_client = AIClient(base_url="http://ia:11434", client=httpx_client)

    before = (
        REGISTRY.get_sample_value(
            "ai_request_errors_total",
            {"operation": "chat", "error_type": "AIServiceUnavailableError"},
        )
        or 0.0
    )

    with pytest.raises(AIServiceUnavailableError):
        ai_client.chat([{"role": "user", "content": "hola"}])

    after = REGISTRY.get_sample_value(
        "ai_request_errors_total",
        {"operation": "chat", "error_type": "AIServiceUnavailableError"},
    )

    assert after == before + 1.0
