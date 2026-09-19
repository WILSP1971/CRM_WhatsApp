"""Tests del webhook de WhatsApp — SPEC-026 (challenge GET + firma HMAC-SHA256
+ ACK rápido).

Unitarios/con `fakeredis` (SIN Postgres real, sin daemon Redis real, SIN
llamadas a Meta): cubren exactamente los criterios de aceptación de
SPEC-026. El webhook no toca Postgres (eso es SPEC-027), así que ningún test
aquí depende de `postgres_engine`/`DATABASE_URL`.

Cubre:
  (a) GET challenge con `verify_token` correcto -> devuelve `hub.challenge`;
      token incorrecto/ausente -> 403.
  (b) POST con firma HMAC-SHA256 válida (calculada en el test con el mismo
      `WHATSAPP_APP_SECRET` sobre el RAW body) -> 200 y evento encolado en
      `wa:inbound`.
  (c) POST sin cabecera de firma o con firma inválida -> 401, y el evento NO
      se encola (la cola queda vacía).
  (d) La verificación usa `hmac.compare_digest` (tiempo constante) — se
      verifica por inspección de la implementación (no hay atajo de
      early-return) y con un caso de firma "casi correcta" (mismo prefijo,
      último carácter distinto) que igual debe fallar como 401.
  (e) El secreto (`WHATSAPP_APP_SECRET`/`WHATSAPP_VERIFY_TOKEN`) no aparece
      en ninguna respuesta ni se propaga en los logs de la ruta feliz/error
      (se verifica que el 401 no incluye detalle que filtre el secreto).
"""

from __future__ import annotations

import hashlib
import hmac
import json

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.redis_client import get_redis_client
from app.core.whatsapp_queue import INBOUND_QUEUE_KEY
from app.main import app

WEBHOOK_URL = "/api/v1/whatsapp/webhook"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fake_redis():
    """Doble de Redis en memoria (mismo patrón que `test_rag_api.py`/SPEC-017):
    permite probar el encolado SIN un daemon Redis real.

    `TestClient` ejecuta cada request en un hilo/loop propio (portal de
    `anyio`), distinto del loop del test; un `FakeRedis` async normal se
    "ata" al primer loop que lo usa y falla con `RuntimeError` si luego se
    consulta desde otro loop. Para evitarlo, el fixture expone un cliente
    SÍNCRONO (`fakeredis.FakeStrictRedis`) que comparte el mismo `FakeServer`
    en memoria: permite inspeccionar la cola tras `client.post(...)` sin
    cruzar loops de asyncio.
    """
    server = fakeredis.FakeServer()
    async_client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    sync_inspector = fakeredis.FakeStrictRedis(server=server, decode_responses=True)
    app.dependency_overrides[get_redis_client] = lambda: async_client
    yield sync_inspector
    app.dependency_overrides.pop(get_redis_client, None)


def _sign(body: bytes, app_secret: str) -> str:
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# (a) Challenge GET
# ---------------------------------------------------------------------------


def test_get_challenge_with_correct_verify_token_returns_challenge(client):
    settings = get_settings()

    response = client.get(
        WEBHOOK_URL,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.whatsapp_verify_token,
            "hub.challenge": "challenge-esperado-123",
        },
    )

    assert response.status_code == 200
    assert response.text == "challenge-esperado-123"


def test_get_challenge_with_wrong_verify_token_returns_403(client):
    response = client.get(
        WEBHOOK_URL,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "token-incorrecto",
            "hub.challenge": "challenge-esperado-123",
        },
    )

    assert response.status_code == 403
    assert "challenge-esperado-123" not in response.text


def test_get_challenge_missing_verify_token_returns_403(client):
    response = client.get(WEBHOOK_URL, params={"hub.mode": "subscribe"})

    assert response.status_code == 403


def test_get_challenge_wrong_mode_returns_403(client):
    settings = get_settings()

    response = client.get(
        WEBHOOK_URL,
        params={
            "hub.mode": "unsubscribe",
            "hub.verify_token": settings.whatsapp_verify_token,
            "hub.challenge": "challenge-esperado-123",
        },
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# (b) POST con firma válida -> 200 + encola
# ---------------------------------------------------------------------------


def test_post_with_valid_signature_returns_200_and_enqueues(client, fake_redis):
    settings = get_settings()
    raw_body = b'{"object":"whatsapp_business_account","entry":[{"id":"1"}]}'
    signature = _sign(raw_body, settings.whatsapp_app_secret)

    response = client.post(
        WEBHOOK_URL,
        content=raw_body,
        headers={
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    assert fake_redis.llen(INBOUND_QUEUE_KEY) == 1

    raw_job = fake_redis.lpop(INBOUND_QUEUE_KEY)
    job = json.loads(raw_job)
    assert job["raw_body"] == raw_body.decode("utf-8")


def test_post_signature_is_computed_over_exact_raw_body(client, fake_redis):
    """La firma debe calcularse sobre los bytes EXACTOS recibidos: un body
    con espaciado/orden distinto (pero "equivalente" si se reparseara como
    JSON) y firmado con el secreto correcto para OTRO body debe rechazarse."""
    settings = get_settings()
    raw_body = b'{"a": 1, "b": 2}'
    different_raw_body = b'{"b": 2, "a": 1}'  # JSON "equivalente", bytes distintos
    signature_for_different_body = _sign(
        different_raw_body, settings.whatsapp_app_secret
    )

    response = client.post(
        WEBHOOK_URL,
        content=raw_body,
        headers={
            "X-Hub-Signature-256": signature_for_different_body,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401
    assert fake_redis.llen(INBOUND_QUEUE_KEY) == 0


# ---------------------------------------------------------------------------
# (c) POST sin firma / firma inválida -> 401, no encola
# ---------------------------------------------------------------------------


def test_post_without_signature_header_returns_401_and_does_not_enqueue(
    client, fake_redis
):
    raw_body = b'{"object":"whatsapp_business_account","entry":[]}'

    response = client.post(
        WEBHOOK_URL, content=raw_body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 401
    assert fake_redis.llen(INBOUND_QUEUE_KEY) == 0


def test_post_with_invalid_signature_returns_401_and_does_not_enqueue(
    client, fake_redis
):
    raw_body = b'{"object":"whatsapp_business_account","entry":[]}'

    response = client.post(
        WEBHOOK_URL,
        content=raw_body,
        headers={
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401
    assert fake_redis.llen(INBOUND_QUEUE_KEY) == 0


def test_post_with_malformed_signature_header_returns_401(client, fake_redis):
    raw_body = b'{"object":"whatsapp_business_account","entry":[]}'

    response = client.post(
        WEBHOOK_URL,
        content=raw_body,
        headers={
            "X-Hub-Signature-256": "not-a-valid-signature-format",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401
    assert fake_redis.llen(INBOUND_QUEUE_KEY) == 0


# ---------------------------------------------------------------------------
# (d) Comparación en tiempo constante (hmac.compare_digest)
# ---------------------------------------------------------------------------


def test_signature_check_uses_constant_time_comparison():
    """Verifica por inspección que la implementación usa
    `hmac.compare_digest` (no un `==` de cadenas, que haría early-return por
    byte) tanto para el header de firma como para el verify_token del GET."""
    import inspect

    from app.integrations.whatsapp import webhook as webhook_module

    source = inspect.getsource(webhook_module)
    assert "hmac.compare_digest" in source
    # No debe haber comparación directa de cadenas del secreto/firma con "==".
    assert "header_value ==" not in source
    assert "hub_verify_token ==" not in source


def test_almost_correct_signature_last_byte_differs_is_rejected(client, fake_redis):
    """Firma casi correcta (todos los caracteres iguales salvo el último)
    debe rechazarse igual que una completamente distinta -> 401."""
    settings = get_settings()
    raw_body = b'{"almost":"correct"}'
    correct_signature = _sign(raw_body, settings.whatsapp_app_secret)
    tampered = correct_signature[:-1] + ("0" if correct_signature[-1] != "0" else "1")

    response = client.post(
        WEBHOOK_URL,
        content=raw_body,
        headers={
            "X-Hub-Signature-256": tampered,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401
    assert fake_redis.llen(INBOUND_QUEUE_KEY) == 0


# ---------------------------------------------------------------------------
# (e) No se filtra el secreto en la respuesta
# ---------------------------------------------------------------------------


def test_401_response_does_not_leak_app_secret(client):
    settings = get_settings()
    raw_body = b'{"object":"whatsapp_business_account","entry":[]}'

    response = client.post(
        WEBHOOK_URL, content=raw_body, headers={"Content-Type": "application/json"}
    )

    assert settings.whatsapp_app_secret not in response.text


def test_403_response_does_not_leak_verify_token(client):
    response = client.get(
        WEBHOOK_URL,
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong"},
    )

    settings = get_settings()
    assert settings.whatsapp_verify_token not in response.text


# ---------------------------------------------------------------------------
# Cola: sanity de la key usada (`wa:inbound`, ADR-006/SPEC-027)
# ---------------------------------------------------------------------------


def test_inbound_queue_key_matches_spec():
    assert INBOUND_QUEUE_KEY == "wa:inbound"


# ---------------------------------------------------------------------------
# (f) Hardening SPEC-032 (hallazgo M-1 BLACK WIDOW SPEC-026): si el encolado
#     en Redis falla (caída/timeout), el webhook responde 503 controlado en
#     vez de un 500 sin distinción, para que Meta reintente por el mecanismo
#     esperado en vez de escalar a una tormenta de reintentos agresivos.
# ---------------------------------------------------------------------------


@pytest.fixture
def broken_redis_client():
    """Doble de Redis que simula una caída/timeout: cualquier operación de
    escritura lanza una excepción, igual que un Redis real inalcanzable."""

    class _BrokenRedis:
        async def rpush(self, *args, **kwargs):
            raise ConnectionError("Redis no disponible (simulado)")

    app.dependency_overrides[get_redis_client] = lambda: _BrokenRedis()
    yield
    app.dependency_overrides.pop(get_redis_client, None)


def test_post_with_valid_signature_but_redis_down_returns_503_not_500(
    client, broken_redis_client
):
    settings = get_settings()
    raw_body = b'{"object":"whatsapp_business_account","entry":[{"id":"1"}]}'
    signature = _sign(raw_body, settings.whatsapp_app_secret)

    response = client.post(
        WEBHOOK_URL,
        content=raw_body,
        headers={
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 503


def test_503_response_does_not_leak_app_secret_or_internal_detail(
    client, broken_redis_client
):
    settings = get_settings()
    raw_body = b'{"object":"whatsapp_business_account","entry":[{"id":"1"}]}'
    signature = _sign(raw_body, settings.whatsapp_app_secret)

    response = client.post(
        WEBHOOK_URL,
        content=raw_body,
        headers={
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
    )

    assert settings.whatsapp_app_secret not in response.text
    assert "Redis" not in response.text
