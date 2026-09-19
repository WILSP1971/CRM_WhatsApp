"""Tests de `app.integrations.whatsapp.graph_client` — SPEC-029 (transporte
de envío saliente, Graph API), ADR-006.

Todos los tests MOCKEAN el transporte HTTP (`httpx.MockTransport`): NO hay
llamada real a `graph.facebook.com`, ni red real de ningún tipo. Cubren
exactamente los criterios de aceptación de SPEC-029 relativos al cliente:

  (a) `send_text_message` hace POST a
      `graph.facebook.com/<version>/<phone_number_id>/messages` con
      `Authorization: Bearer <token>` (mockeado) y parsea el `wamid` de la
      respuesta.
  (b) Host allowlist: una URL base con host != `graph.facebook.com` es
      RECHAZADA (`GraphApiHostError`), sin abrir conexión.
  (c) El token NO se loguea (se inspecciona `caplog`/eventos `structlog`).
  (d) Manejo de 429/5xx: reintento con backoff hasta agotar, y agotado ->
      `GraphApiTransientError` (idempotente, sin duplicar el POST más allá
      de los reintentos configurados). Un 4xx no reintentable ->
      `GraphApiError` inmediato (sin reintentos).
"""

from __future__ import annotations

import httpx
import pytest

from app.integrations.whatsapp.graph_client import (
    GraphApiClient,
    GraphApiError,
    GraphApiHostError,
    GraphApiTransientError,
    GraphSendResult,
    _validate_graph_host,
)

_TOKEN = "test-token-should-never-appear-in-logs-abc123"


def _client_with_handler(handler, **kwargs) -> GraphApiClient:
    transport = httpx.MockTransport(handler)
    httpx_client = httpx.Client(transport=transport)
    return GraphApiClient(
        access_token=_TOKEN,
        api_version="v21.0",
        client=httpx_client,
        max_retries=kwargs.pop("max_retries", 3),
        backoff_base_seconds=0,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# (a) POST a graph.facebook.com/<version>/<phone_number_id>/messages con
#     Bearer token, y el wamid se parsea de la respuesta.
# ---------------------------------------------------------------------------


def test_send_text_message_posts_to_graph_api_with_bearer_and_parses_wamid():
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.HBgXY123=="}]})

    client = _client_with_handler(handler)

    result = client.send_text_message(
        phone_number_id="1234567890",
        to="573000000001",
        text="Hola, tu pedido está listo.",
        idempotency_key="msg-uuid-1",
    )

    assert isinstance(result, GraphSendResult)
    assert result.wamid == "wamid.HBgXY123=="
    assert len(seen_requests) == 1
    request = seen_requests[0]
    assert request.url.host == "graph.facebook.com"
    assert str(request.url) == ("https://graph.facebook.com/v21.0/1234567890/messages")
    assert request.headers["Authorization"] == f"Bearer {_TOKEN}"
    assert request.headers["Content-Type"] == "application/json"


def test_send_template_message_posts_template_payload_and_parses_wamid():
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.TEMPLATE1"}]})

    client = _client_with_handler(handler)

    result = client.send_template_message(
        phone_number_id="1234567890",
        to="573000000001",
        template_name="ventana_utilitaria",
        language_code="es",
        idempotency_key="msg-uuid-2",
    )

    assert result.wamid == "wamid.TEMPLATE1"
    body = seen_requests[0].content
    assert b'"type": "template"' in body or b'"type":"template"' in body
    assert b"ventana_utilitaria" in body


# ---------------------------------------------------------------------------
# (b) Host allowlist: cualquier host != graph.facebook.com es RECHAZADO.
# ---------------------------------------------------------------------------


def test_host_allowlist_rejects_non_graph_host_at_construction():
    with pytest.raises(GraphApiHostError):
        GraphApiClient(
            access_token=_TOKEN,
            base_url="https://evil.example.com",
        )


@pytest.mark.parametrize(
    "malicious_url",
    [
        "https://graph.facebook.com.attacker.net",
        "https://evil-graph.facebook.com",
        "http://graph.facebook.com.evil.io",
        "https://notgraph.facebook.com",
        "ftp://graph.facebook.com",
        "",
    ],
)
def test_validate_graph_host_rejects_lookalike_and_malformed_hosts(malicious_url):
    with pytest.raises(GraphApiHostError):
        _validate_graph_host(malicious_url)


def test_validate_graph_host_accepts_exact_host():
    assert _validate_graph_host("https://graph.facebook.com") == (
        "https://graph.facebook.com"
    )


# ---------------------------------------------------------------------------
# (f) Hardening SPEC-032 (BLACK WIDOW SPEC-029): userinfo embebido rechazado
#     explícitamente, incluso cuando el hostname coincide exactamente con el
#     permitido (defensa en profundidad, no solo comparación de `.hostname`).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url_con_userinfo",
    [
        "https://user:pass@graph.facebook.com",
        "https://attacker@graph.facebook.com",
        "https://:secret@graph.facebook.com",
    ],
)
def test_validate_graph_host_rejects_embedded_userinfo(url_con_userinfo):
    with pytest.raises(GraphApiHostError):
        _validate_graph_host(url_con_userinfo)


def test_graph_api_client_construction_rejects_userinfo_in_base_url():
    with pytest.raises(GraphApiHostError):
        GraphApiClient(
            access_token=_TOKEN,
            base_url="https://user:pass@graph.facebook.com",
        )


# ---------------------------------------------------------------------------
# (c) El token NUNCA se loguea.
# ---------------------------------------------------------------------------


def test_token_never_appears_in_logs_on_success(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": [{"id": "wamid.OK"}]})

    client = _client_with_handler(handler)
    client.send_text_message(
        phone_number_id="1",
        to="2",
        text="hola",
        idempotency_key="k1",
    )

    for record in caplog.records:
        assert _TOKEN not in record.getMessage()


def test_token_never_appears_in_logs_on_permanent_error(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad token"}})

    client = _client_with_handler(handler)

    with pytest.raises(GraphApiError):
        client.send_text_message(
            phone_number_id="1", to="2", text="hola", idempotency_key="k2"
        )

    for record in caplog.records:
        assert _TOKEN not in record.getMessage()


def test_token_never_appears_in_logs_after_retries_exhausted(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server error"})

    client = _client_with_handler(handler, max_retries=2)

    with pytest.raises(GraphApiTransientError):
        client.send_text_message(
            phone_number_id="1", to="2", text="hola", idempotency_key="k3"
        )

    for record in caplog.records:
        assert _TOKEN not in record.getMessage()


# ---------------------------------------------------------------------------
# (e) Manejo de 429/5xx: reintento con backoff; agotado -> error controlado.
#     4xx no reintentable -> error inmediato, sin reintentos.
# ---------------------------------------------------------------------------


def test_429_is_retried_and_succeeds_on_second_attempt():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.RETRY-OK"}]})

    client = _client_with_handler(handler, max_retries=3)

    result = client.send_text_message(
        phone_number_id="1", to="2", text="hola", idempotency_key="k4"
    )

    assert result.wamid == "wamid.RETRY-OK"
    assert attempts["n"] == 2


def test_5xx_retried_until_exhausted_raises_transient_error():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    client = _client_with_handler(handler, max_retries=3)

    with pytest.raises(GraphApiTransientError):
        client.send_text_message(
            phone_number_id="1", to="2", text="hola", idempotency_key="k5"
        )

    assert attempts["n"] == 3


def test_permanent_4xx_error_not_retried():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(400, json={"error": {"message": "invalid to"}})

    client = _client_with_handler(handler, max_retries=3)

    with pytest.raises(GraphApiError):
        client.send_text_message(
            phone_number_id="1", to="2", text="hola", idempotency_key="k6"
        )

    assert attempts["n"] == 1


def test_response_without_wamid_raises_graph_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    client = _client_with_handler(handler)

    with pytest.raises(GraphApiError):
        client.send_text_message(
            phone_number_id="1", to="2", text="hola", idempotency_key="k7"
        )
