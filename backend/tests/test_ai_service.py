"""Tests del cliente de IA local (Ollama) — SPEC-016.

Todos los tests MOCKEAN el transporte HTTP (`httpx.MockTransport`): NO hay
llamada real a un modelo ni se requiere GPU/daemon de Ollama en este entorno.
Verifican:
  (a) el cliente construye las peticiones contra el host INTERNO configurado
      (nunca un dominio externo);
  (b) manejo de error/timeout -> `AIServiceUnavailableError` (modo degradado);
  (c) respuestas mal formadas -> `AIServiceResponseError`;
  (d) el checkpoint de arranque (`Settings`) rechaza un host de IA externo.

Lo que queda para CI/entorno con Ollama real (fuera de alcance aquí, sin
GPU/daemon disponible en este sandbox):
  - Latencia p95 de generación/embeddings (RNF-04, formalizado en SPEC-022/THOR).
  - Prueba de egress vacío real (`docker exec crm_ia curl https://api.openai.com`
    debe fallar) — documentada en `backend/TEST_EGRESS_BLOCKED.md`.
  - Captura de red (netstat/pcap) durante una corrida real sin conexiones a
    IPs públicas.
  - Arranque real con modelo Q4 en CPU (fallback sin GPU) y medición de
    latencia degradada.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.ai_service import (
    AIClient,
    AIServiceResponseError,
    AIServiceUnavailableError,
)

INTERNAL_BASE_URL = "http://ia:11434"


def _client_with_handler(handler, **kwargs) -> AIClient:
    """Crea un `AIClient` cuyo transporte HTTP está mockeado (sin red real)."""
    transport = httpx.MockTransport(handler)
    httpx_client = httpx.Client(base_url=INTERNAL_BASE_URL, transport=transport)
    return AIClient(base_url=INTERNAL_BASE_URL, client=httpx_client, **kwargs)


# ---------------------------------------------------------------------------
# (a) El cliente habla SOLO con el host interno configurado
# ---------------------------------------------------------------------------


def test_chat_requests_only_internal_host_never_external_domain():
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        assert request.url.host == "ia"
        assert str(request.url).startswith(INTERNAL_BASE_URL)
        return httpx.Response(
            200,
            json={"message": {"content": "hola"}, "model": "qwen2.5:7b-instruct"},
        )

    client = _client_with_handler(handler)
    result = client.chat([{"role": "user", "content": "hola"}])

    assert result.content == "hola"
    assert len(seen_requests) == 1
    # Ningún dominio externo conocido debe aparecer en absoluto en la petición.
    for forbidden in ("openai.com", "anthropic.com", "googleapis.com"):
        assert forbidden not in str(seen_requests[0].url)


def test_embed_requests_only_internal_host():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "ia"
        assert request.url.path == "/api/embeddings"
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3, 0.4]})

    client = _client_with_handler(handler)
    result = client.embed("texto de prueba")

    assert result.dimension == 4
    assert result.vector == [0.1, 0.2, 0.3, 0.4]
    assert result.model == "nomic-embed-text"


def test_ai_client_default_base_url_comes_from_internal_settings(monkeypatch):
    """Sin overrides, `AIClient` usa `Settings.ai_base_url` (host interno)."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    from app.core import config as config_module

    config_module.get_settings.cache_clear()
    client = AIClient()

    assert client.base_url == "http://ia:11434"
    config_module.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# (b) Manejo de error / timeout -> modo degradado (R-21)
# ---------------------------------------------------------------------------


def test_chat_timeout_raises_ai_service_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout simulado", request=request)

    client = _client_with_handler(handler)

    with pytest.raises(AIServiceUnavailableError):
        client.chat([{"role": "user", "content": "hola"}])


def test_embed_connection_error_raises_ai_service_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conexión rechazada simulada", request=request)

    client = _client_with_handler(handler)

    with pytest.raises(AIServiceUnavailableError):
        client.embed("texto")


def test_chat_server_error_5xx_raises_ai_service_unavailable():
    """503 típico de Ollama cuando el modelo no está descargado/cargado."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="model not found")

    client = _client_with_handler(handler)

    with pytest.raises(AIServiceUnavailableError):
        client.chat([{"role": "user", "content": "hola"}])


def test_chat_client_error_4xx_raises_ai_service_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    client = _client_with_handler(handler)

    with pytest.raises(AIServiceResponseError):
        client.chat([{"role": "user", "content": "hola"}])


def test_is_available_false_on_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexión simulada", request=request)

    client = _client_with_handler(handler)

    assert client.is_available() is False


def test_is_available_true_on_200():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": []})

    client = _client_with_handler(handler)

    assert client.is_available() is True


# ---------------------------------------------------------------------------
# (c) Respuestas mal formadas
# ---------------------------------------------------------------------------


def test_chat_missing_message_content_raises_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "qwen2.5:7b-instruct"})

    client = _client_with_handler(handler)

    with pytest.raises(AIServiceResponseError):
        client.chat([{"role": "user", "content": "hola"}])


def test_embed_missing_embedding_field_raises_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    client = _client_with_handler(handler)

    with pytest.raises(AIServiceResponseError):
        client.embed("texto")


def test_chat_non_json_response_raises_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>no json</html>")

    client = _client_with_handler(handler)

    with pytest.raises(AIServiceResponseError):
        client.chat([{"role": "user", "content": "hola"}])
