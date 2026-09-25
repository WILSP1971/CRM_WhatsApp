"""Tests del webhook de grabaciones del PBX — SPEC-037 (challenge GET +
firma HMAC-SHA256 sobre el audio crudo + ACK rápido, RF-01).

Unitarios/con `fakeredis` (SIN Postgres real, sin daemon Redis real, sin PBX
real): cubren exactamente los criterios de transporte de SPEC-037. El
webhook no toca Postgres (eso es `recording_ingest_worker`), así que ningún
test aquí depende de `postgres_engine`/`DATABASE_URL`.

Cubre:
  (a) GET challenge con `verify_token` correcto -> devuelve el `challenge`;
      token incorrecto/ausente -> 403.
  (b) POST multipart con firma HMAC-SHA256 válida (calculada sobre los bytes
      EXACTOS del fichero de audio) -> 202 Accepted y evento encolado en
      `pbx:recordings:inbound`.
  (c) POST sin cabecera de firma o con firma inválida -> 401, sin encolar.
  (d) `direccion` fuera de {"entrante","saliente"} -> 422, sin encolar.
  (e) Comparación en tiempo constante (`hmac.compare_digest`).
  (f) El secreto no se filtra en la respuesta.
  (g) Hardening: Redis caído -> 503 (mismo patrón que WhatsApp, SPEC-032).
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
from app.core.recording_queue import RECORDING_INBOUND_QUEUE_KEY, RecordingInboundJob
from app.core.redis_client import get_redis_client
from app.main import app

WEBHOOK_URL = "/webhooks/pbx/recordings"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fake_redis():
    """Doble de Redis en memoria (mismo patrón que `test_whatsapp_webhook.py`)."""
    server = fakeredis.FakeServer()
    async_client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    sync_inspector = fakeredis.FakeStrictRedis(server=server, decode_responses=True)
    app.dependency_overrides[get_redis_client] = lambda: async_client
    yield sync_inspector
    app.dependency_overrides.pop(get_redis_client, None)


def _sign(audio_bytes: bytes, webhook_secret: str) -> str:
    digest = hmac.new(webhook_secret.encode("utf-8"), audio_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _post_recording(
    client,
    *,
    audio_bytes: bytes,
    signature: str | None,
    call_id: str = "call-demo-000001",
    numero: str = "3001112222",
    numero_destino: str = "6011234500",
    direccion: str = "entrante",
    duracion: int | None = 42,
):
    headers = {}
    if signature is not None:
        headers["X-Webhook-Signature-256"] = signature

    data = {
        "call_id": call_id,
        "numero": numero,
        "numero_destino": numero_destino,
        "direccion": direccion,
    }
    if duracion is not None:
        data["duracion"] = str(duracion)

    files = {"file": ("grabacion.wav", audio_bytes, "audio/wav")}

    return client.post(WEBHOOK_URL, headers=headers, data=data, files=files)


# ---------------------------------------------------------------------------
# (a) Challenge GET
# ---------------------------------------------------------------------------


def test_get_challenge_with_correct_verify_token_returns_challenge(client):
    settings = get_settings()

    response = client.get(
        WEBHOOK_URL,
        params={"verify_token": settings.webhook_verify_token, "challenge": "abc-123"},
    )

    assert response.status_code == 200
    assert response.text == "abc-123"


def test_get_challenge_with_wrong_verify_token_returns_403(client):
    response = client.get(
        WEBHOOK_URL,
        params={"verify_token": "token-incorrecto", "challenge": "abc-123"},
    )

    assert response.status_code == 403
    assert "abc-123" not in response.text


def test_get_challenge_missing_verify_token_returns_403(client):
    response = client.get(WEBHOOK_URL, params={"challenge": "abc-123"})

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# (b) POST con firma válida -> 202 + encola
# ---------------------------------------------------------------------------


def test_post_with_valid_signature_returns_202_and_enqueues(client, fake_redis):
    settings = get_settings()
    audio_bytes = b"RIFF-fake-wav-bytes-0001"
    signature = _sign(audio_bytes, settings.webhook_secret)

    response = _post_recording(client, audio_bytes=audio_bytes, signature=signature)

    assert response.status_code == 202
    assert fake_redis.llen(RECORDING_INBOUND_QUEUE_KEY) == 1

    raw_job = fake_redis.lpop(RECORDING_INBOUND_QUEUE_KEY)
    job = RecordingInboundJob.from_json(raw_job)
    assert job.call_id == "call-demo-000001"
    assert job.numero_destino == "6011234500"
    assert job.direccion == "entrante"
    assert job.duracion == 42
    assert job.audio_bytes == audio_bytes


def test_post_signature_is_computed_over_exact_audio_bytes(client, fake_redis):
    """La firma debe calcularse sobre los bytes EXACTOS del audio: una firma
    válida para OTRO contenido debe rechazarse."""
    settings = get_settings()
    audio_bytes = b"audio-real"
    different_audio_bytes = b"audio-distinto"
    signature_for_different_audio = _sign(different_audio_bytes, settings.webhook_secret)

    response = _post_recording(
        client, audio_bytes=audio_bytes, signature=signature_for_different_audio
    )

    assert response.status_code == 401
    assert fake_redis.llen(RECORDING_INBOUND_QUEUE_KEY) == 0


# ---------------------------------------------------------------------------
# (c) POST sin firma / firma inválida -> 401, no encola
# ---------------------------------------------------------------------------


def test_post_without_signature_header_returns_401_and_does_not_enqueue(
    client, fake_redis
):
    response = _post_recording(client, audio_bytes=b"audio", signature=None)

    assert response.status_code == 401
    assert fake_redis.llen(RECORDING_INBOUND_QUEUE_KEY) == 0


def test_post_with_invalid_signature_returns_401_and_does_not_enqueue(
    client, fake_redis
):
    response = _post_recording(
        client, audio_bytes=b"audio", signature="sha256=" + "0" * 64
    )

    assert response.status_code == 401
    assert fake_redis.llen(RECORDING_INBOUND_QUEUE_KEY) == 0


def test_post_with_malformed_signature_header_returns_401(client, fake_redis):
    response = _post_recording(
        client, audio_bytes=b"audio", signature="not-a-valid-signature-format"
    )

    assert response.status_code == 401
    assert fake_redis.llen(RECORDING_INBOUND_QUEUE_KEY) == 0


def test_almost_correct_signature_last_byte_differs_is_rejected(client, fake_redis):
    settings = get_settings()
    audio_bytes = b"audio-casi-correcto"
    correct_signature = _sign(audio_bytes, settings.webhook_secret)
    tampered = correct_signature[:-1] + ("0" if correct_signature[-1] != "0" else "1")

    response = _post_recording(client, audio_bytes=audio_bytes, signature=tampered)

    assert response.status_code == 401
    assert fake_redis.llen(RECORDING_INBOUND_QUEUE_KEY) == 0


def test_signature_check_uses_constant_time_comparison():
    import inspect

    from app.integrations.pbx import webhook as webhook_module

    source = inspect.getsource(webhook_module)
    assert "hmac.compare_digest" in source
    assert "header_value ==" not in source
    assert "verify_token ==" not in source


# ---------------------------------------------------------------------------
# (d) direccion inválida -> 422, sin encolar
# ---------------------------------------------------------------------------


def test_post_with_invalid_direccion_returns_422_and_does_not_enqueue(
    client, fake_redis
):
    settings = get_settings()
    audio_bytes = b"audio-direccion-invalida"
    signature = _sign(audio_bytes, settings.webhook_secret)

    response = _post_recording(
        client, audio_bytes=audio_bytes, signature=signature, direccion="lateral"
    )

    assert response.status_code == 422
    assert fake_redis.llen(RECORDING_INBOUND_QUEUE_KEY) == 0


# ---------------------------------------------------------------------------
# (f) No se filtra el secreto en la respuesta
# ---------------------------------------------------------------------------


def test_401_response_does_not_leak_webhook_secret(client):
    response = _post_recording(client, audio_bytes=b"audio", signature=None)

    settings = get_settings()
    assert settings.webhook_secret not in response.text


def test_403_response_does_not_leak_verify_token(client):
    response = client.get(WEBHOOK_URL, params={"verify_token": "wrong"})

    settings = get_settings()
    assert settings.webhook_verify_token not in response.text


def test_recording_inbound_queue_key_matches_spec():
    assert RECORDING_INBOUND_QUEUE_KEY == "pbx:recordings:inbound"


# ---------------------------------------------------------------------------
# (g) Hardening: Redis caído -> 503, no 500 (mismo criterio que WhatsApp)
# ---------------------------------------------------------------------------


@pytest.fixture
def broken_redis_client():
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
    audio_bytes = b"audio-redis-down"
    signature = _sign(audio_bytes, settings.webhook_secret)

    response = _post_recording(client, audio_bytes=audio_bytes, signature=signature)

    assert response.status_code == 503


def test_503_response_does_not_leak_webhook_secret_or_internal_detail(
    client, broken_redis_client
):
    settings = get_settings()
    audio_bytes = b"audio-redis-down-2"
    signature = _sign(audio_bytes, settings.webhook_secret)

    response = _post_recording(client, audio_bytes=audio_bytes, signature=signature)

    assert settings.webhook_secret not in response.text
    assert "Redis" not in response.text
