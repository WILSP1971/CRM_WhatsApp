"""Tests de `app.integrations.whatsapp.media_client` — SPEC-054 (F1),
ADR-006/ADR-007/ADR-009.

Todos los tests MOCKEAN el transporte HTTP (`httpx.MockTransport`) o inyectan
dobles simples de `Session`/`Message`: NO hay llamada real a
`graph.facebook.com`, ni Postgres real, ni red de ningún tipo. Cubren los
criterios de aceptación de SPEC-054:

  (a) Doble-GET simulado: resuelve la URL temporal + descarga el binario,
      lo almacena CIFRADO (vía `audio_store.store_audio` real, sobre un
      `tmp_path`) y puebla `message.audio_ref`.
  (b) Host allowlist: un host distinto de `graph.facebook.com` en CUALQUIERA
      de los dos GETs aborta (`GraphApiHostError`) antes de conectar.
  (c) Idempotencia: `message.audio_ref` ya presente -> NO se re-descarga
      (cero requests HTTP).
  (d) Fallo controlado: reintentos agotados (URL "expirada"/5xx) ->
      `message.transcripcion_estado == "error"`, sin excepción no controlada.
  (e) El `access_token` nunca aparece en logs (`caplog`).
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.whatsapp.graph_client import GraphApiError, GraphApiHostError
from app.integrations.whatsapp.media_client import (
    GraphMediaClient,
    MediaDownloadError,
    MediaDownloadTransientError,
    MediaMetadata,
    download_and_store_voice_note,
)
from app.models.message import Message
from app.services.telefonia import audio_store

_TOKEN = "test-media-token-should-never-appear-in-logs-xyz789"
_MEDIA_ID = "1234567890-media-id"


def _client_with_handler(handler, **kwargs) -> GraphMediaClient:
    transport = httpx.MockTransport(handler)
    httpx_client = httpx.Client(transport=transport)
    return GraphMediaClient(
        access_token=_TOKEN,
        api_version="v21.0",
        client=httpx_client,
        max_retries=kwargs.pop("max_retries", 3),
        backoff_base_seconds=0,
        **kwargs,
    )


class _FakeSession:
    """Doble mínimo de `sqlalchemy.orm.Session`: solo registra `flush()`,
    sin abrir Postgres real (los tests de `download_and_store_voice_note`
    son unitarios, no de integración de RLS — esos ya existen en
    `test_messages_voice_note_data.py` para SPEC-053)."""

    def __init__(self) -> None:
        self.flush_calls = 0

    def flush(self) -> None:
        self.flush_calls += 1


def _build_message(*, audio_ref: str | None = None) -> Message:
    message = Message(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        remitente="contacto",
        tipo="audio",
        audio_ref=audio_ref,
        transcripcion_estado="pendiente",
    )
    return message


@pytest.fixture
def audio_store_tmp(tmp_path):
    settings = get_settings()
    original = settings.audio_storage_path
    settings.audio_storage_path = str(tmp_path)
    yield tmp_path
    settings.audio_storage_path = original


# ---------------------------------------------------------------------------
# (a) Doble-GET simulado: resuelve URL temporal + descarga binario cifrado.
# ---------------------------------------------------------------------------


def test_fetch_media_resolves_url_then_downloads_binary():
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        if request.url.path == f"/v21.0/{_MEDIA_ID}":
            return httpx.Response(
                200,
                json={
                    "url": "https://graph.facebook.com/media-temp/abc123",
                    "mime_type": "audio/ogg; codecs=opus",
                    "file_size": 4,
                },
            )
        return httpx.Response(200, content=b"OggS")

    client = _client_with_handler(handler)
    downloaded = client.fetch_media(_MEDIA_ID)

    assert downloaded.content == b"OggS"
    assert downloaded.mime_type == "audio/ogg; codecs=opus"
    assert len(seen_requests) == 2
    assert seen_requests[0].headers["Authorization"] == f"Bearer {_TOKEN}"
    assert seen_requests[1].headers["Authorization"] == f"Bearer {_TOKEN}"


def test_download_and_store_voice_note_persists_encrypted_audio_ref(audio_store_tmp):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v21.0/{_MEDIA_ID}":
            return httpx.Response(
                200,
                json={
                    "url": "https://graph.facebook.com/media-temp/abc123",
                    "mime_type": "audio/ogg",
                },
            )
        return httpx.Response(200, content=b"contenido-binario-de-la-nota-de-voz")

    client = _client_with_handler(handler)
    message = _build_message()
    db = _FakeSession()

    result = download_and_store_voice_note(
        db, message, media_id=_MEDIA_ID, client=client
    )

    assert result.audio_ref is not None
    assert result.transcripcion_estado == "pendiente"  # no se toca en éxito
    assert result.mime_type == "audio/ogg"  # WOLVERINE: se persiste, no se pierde
    assert db.flush_calls >= 1

    on_disk = audio_store_tmp / result.audio_ref
    on_disk_bytes = on_disk.read_bytes()
    assert b"contenido-binario-de-la-nota-de-voz" not in on_disk_bytes  # cifrado

    recovered = audio_store.load_audio(audio_ref=result.audio_ref)
    assert recovered == b"contenido-binario-de-la-nota-de-voz"


def test_download_and_store_voice_note_leaves_mime_type_none_when_meta_omits_it(
    audio_store_tmp,
):
    """Meta no siempre incluye `mime_type` en la respuesta de resolución de
    media (campo opcional documentado en la Graph API) — `message.mime_type`
    debe quedar `None`, no reventar (WOLVERINE)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v21.0/{_MEDIA_ID}":
            return httpx.Response(
                200, json={"url": "https://graph.facebook.com/media-temp/abc123"}
            )
        return httpx.Response(200, content=b"contenido-sin-mime")

    client = _client_with_handler(handler)
    message = _build_message()
    db = _FakeSession()

    result = download_and_store_voice_note(
        db, message, media_id=_MEDIA_ID, client=client
    )

    assert result.audio_ref is not None
    assert result.mime_type is None


# ---------------------------------------------------------------------------
# (b) Host allowlist: un host distinto de graph.facebook.com aborta.
# ---------------------------------------------------------------------------


def test_host_allowlist_rejects_non_graph_host_at_construction():
    with pytest.raises(GraphApiHostError):
        GraphMediaClient(access_token=_TOKEN, base_url="https://evil.example.com")


def test_resolve_media_metadata_rejects_malicious_temp_url():
    """El PRIMER GET responde OK pero con una `url` temporal apuntando a un
    host malicioso: `download_binary` debe abortar ANTES de conectar a esa
    URL (RF-01, defensa en profundidad sobre el segundo salto)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "url": "https://evil.attacker.net/steal-audio",
                "mime_type": "audio/ogg",
            },
        )

    client = _client_with_handler(handler)
    metadata = client.resolve_media_metadata(_MEDIA_ID)

    with pytest.raises(GraphApiHostError):
        client.download_binary(metadata)


def test_fetch_media_aborts_before_connecting_when_temp_url_is_malicious():
    connected_to_evil_host = {"value": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != "graph.facebook.com":
            connected_to_evil_host["value"] = True
        if request.url.path == f"/v21.0/{_MEDIA_ID}":
            return httpx.Response(
                200,
                json={"url": "https://evil.attacker.net/steal-audio"},
            )
        return httpx.Response(200, content=b"nunca-debe-llegar-aqui")

    client = _client_with_handler(handler)

    with pytest.raises(GraphApiHostError):
        client.fetch_media(_MEDIA_ID)

    assert connected_to_evil_host["value"] is False


def test_download_and_store_voice_note_reraises_host_error_as_incident():
    """Un `GraphApiHostError` (violación de allowlist) NO se traduce en
    `transcripcion_estado='error'` silencioso — se re-propaga como incidente
    de seguridad visible (RF-01, ADR-006)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"url": "https://evil.attacker.net/x"})

    client = _client_with_handler(handler)
    message = _build_message()
    db = _FakeSession()

    with pytest.raises(GraphApiHostError):
        download_and_store_voice_note(db, message, media_id=_MEDIA_ID, client=client)

    assert (
        message.transcripcion_estado == "pendiente"
    )  # sin tocar, no auditado como error normal


# ---------------------------------------------------------------------------
# (c) Idempotencia: audio_ref ya presente -> NO se re-descarga.
# ---------------------------------------------------------------------------


def test_download_and_store_voice_note_skips_when_audio_ref_already_present():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"url": "https://graph.facebook.com/x"})

    client = _client_with_handler(handler)
    message = _build_message(audio_ref="tenant-x/ya-descargado.enc")
    db = _FakeSession()

    result = download_and_store_voice_note(
        db, message, media_id=_MEDIA_ID, client=client
    )

    assert result.audio_ref == "tenant-x/ya-descargado.enc"
    assert calls["n"] == 0  # ni un solo GET a Meta
    assert db.flush_calls == 0


# ---------------------------------------------------------------------------
# (d) Fallo controlado: reintentos agotados -> transcripcion_estado="error".
# ---------------------------------------------------------------------------


def test_5xx_retried_until_exhausted_raises_transient_error():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    client = _client_with_handler(handler, max_retries=3)

    with pytest.raises(MediaDownloadTransientError):
        client.fetch_media(_MEDIA_ID)

    assert attempts["n"] == 3


def test_permanent_4xx_error_not_retried():
    """URL temporal expirada -> Meta responde 404 (no reintentable, R-67)."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(404, json={"error": "not found / expired"})

    client = _client_with_handler(handler, max_retries=3)

    with pytest.raises(MediaDownloadError):
        client.fetch_media(_MEDIA_ID)

    assert attempts["n"] == 1


def test_download_and_store_voice_note_marks_error_without_raising_on_exhausted_retries(
    audio_store_tmp,
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    client = _client_with_handler(handler, max_retries=2)
    message = _build_message()
    db = _FakeSession()

    result = download_and_store_voice_note(
        db, message, media_id=_MEDIA_ID, client=client
    )

    assert result.transcripcion_estado == "error"
    assert result.audio_ref is None
    assert db.flush_calls == 1


def test_download_and_store_voice_note_marks_error_on_permanent_error(audio_store_tmp):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "expired"})

    client = _client_with_handler(handler)
    message = _build_message()
    db = _FakeSession()

    result = download_and_store_voice_note(
        db, message, media_id=_MEDIA_ID, client=client
    )

    assert result.transcripcion_estado == "error"
    assert result.audio_ref is None


def test_response_without_url_raises_graph_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    client = _client_with_handler(handler)

    with pytest.raises(GraphApiError):
        client.fetch_media(_MEDIA_ID)


# ---------------------------------------------------------------------------
# (e) El token NUNCA se loguea.
# ---------------------------------------------------------------------------


def test_token_never_appears_in_logs_on_success(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v21.0/{_MEDIA_ID}":
            return httpx.Response(200, json={"url": "https://graph.facebook.com/x"})
        return httpx.Response(200, content=b"audio-bytes")

    client = _client_with_handler(handler)
    client.fetch_media(_MEDIA_ID)

    for record in caplog.records:
        assert _TOKEN not in record.getMessage()


def test_token_never_appears_in_logs_after_retries_exhausted(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server error"})

    client = _client_with_handler(handler, max_retries=2)

    with pytest.raises(MediaDownloadTransientError):
        client.fetch_media(_MEDIA_ID)

    for record in caplog.records:
        assert _TOKEN not in record.getMessage()


# ---------------------------------------------------------------------------
# MediaMetadata: construcción directa (dataclass, sin I/O).
# ---------------------------------------------------------------------------


def test_media_metadata_is_frozen_dataclass():
    metadata = MediaMetadata(
        url="https://graph.facebook.com/x",
        mime_type="audio/ogg",
        sha256=None,
        file_size=None,
    )
    with pytest.raises(AttributeError):
        metadata.url = "https://other.example.com"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SPEC-060: observabilidad (`whatsapp_media_downloads_total`) + rama de fallo
# de E/S genuina de `audio_store.store_audio` (AudioStoreError) + camino de
# producción real (sin `client=` inyectado, `fetch_media` abre/cierra su
# propio `httpx.Client`).
# ---------------------------------------------------------------------------


def test_download_and_store_voice_note_marks_error_when_audio_store_fails(
    audio_store_tmp,
):
    """Rama genuina no cubierta por los tests (d) de arriba: la descarga HTTP
    tiene éxito pero `audio_store.store_audio` falla (E/S real, p.ej. disco
    lleno/permiso denegado) — debe marcarse `transcripcion_estado='error'`
    igual que un fallo de descarga, SIN propagar la excepción (mismo
    contrato que el resto de `download_and_store_voice_note`)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v21.0/{_MEDIA_ID}":
            return httpx.Response(
                200, json={"url": "https://graph.facebook.com/media-temp/abc"}
            )
        return httpx.Response(200, content=b"audio-bytes-validos")

    client = _client_with_handler(handler)
    message = _build_message()
    db = _FakeSession()

    with patch(
        "app.integrations.whatsapp.media_client.audio_store.store_audio",
        side_effect=audio_store.AudioStoreError("disco lleno (simulado)"),
    ), patch(
        "app.integrations.whatsapp.media_client.increment_whatsapp_media_downloads"
    ) as mock_metric:
        result = download_and_store_voice_note(
            db, message, media_id=_MEDIA_ID, client=client
        )

    assert result.transcripcion_estado == "error"
    assert result.audio_ref is None
    mock_metric.assert_called_once_with(resultado="error")


def test_increment_whatsapp_media_downloads_ok_on_success(audio_store_tmp):
    """RF observabilidad (SPEC-060): una descarga exitosa incrementa
    `whatsapp_media_downloads_total{resultado="ok"}` exactamente una vez."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v21.0/{_MEDIA_ID}":
            return httpx.Response(
                200, json={"url": "https://graph.facebook.com/media-temp/abc"}
            )
        return httpx.Response(200, content=b"audio-bytes-validos")

    client = _client_with_handler(handler)
    message = _build_message()
    db = _FakeSession()

    with patch(
        "app.integrations.whatsapp.media_client.increment_whatsapp_media_downloads"
    ) as mock_metric:
        download_and_store_voice_note(db, message, media_id=_MEDIA_ID, client=client)

    mock_metric.assert_called_once_with(resultado="ok")


def test_increment_whatsapp_media_downloads_error_on_download_failure(
    audio_store_tmp,
):
    """Un fallo de descarga (reintentos agotados) incrementa
    `whatsapp_media_downloads_total{resultado="error"}` exactamente una vez
    — y el no-op de idempotencia (audio_ref ya presente) NO incrementa nada,
    porque no hubo una descarga nueva que contar."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    client = _client_with_handler(handler, max_retries=2)
    message = _build_message()
    db = _FakeSession()

    with patch(
        "app.integrations.whatsapp.media_client.increment_whatsapp_media_downloads"
    ) as mock_metric:
        download_and_store_voice_note(db, message, media_id=_MEDIA_ID, client=client)

    mock_metric.assert_called_once_with(resultado="error")


def test_increment_whatsapp_media_downloads_not_called_when_idempotent_skip():
    """El camino de idempotencia (`message.audio_ref` ya poblado) NO debe
    incrementar el contador — no hubo una descarga nueva, solo un no-op."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"url": "https://graph.facebook.com/x"})

    client = _client_with_handler(handler)
    message = _build_message(audio_ref="tenant-x/ya-descargado.enc")
    db = _FakeSession()

    with patch(
        "app.integrations.whatsapp.media_client.increment_whatsapp_media_downloads"
    ) as mock_metric:
        download_and_store_voice_note(db, message, media_id=_MEDIA_ID, client=client)

    mock_metric.assert_not_called()


def test_fetch_media_without_injected_client_opens_and_closes_own_httpx_client(
    monkeypatch,
):
    """Camino de producción real (RF-01): sin `client=` inyectado en el
    constructor, `fetch_media` abre su PROPIO `httpx.Client` (reutilizado
    para ambos GETs) y lo cierra al terminar — cubre la rama `self._client is
    None` de `fetch_media`, no ejercida por el resto de la suite (que siempre
    inyecta un `httpx.MockTransport` vía el parámetro `client=`)."""
    seen_requests: list[httpx.Request] = []
    real_request = httpx.Client.request

    def _fake_request(self, method, url, **kwargs):
        seen_requests.append(url)
        transport = httpx.MockTransport(_handler)
        with httpx.Client(transport=transport) as fake_client:
            return real_request(fake_client, method, url, **kwargs)

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v21.0/{_MEDIA_ID}":
            return httpx.Response(
                200, json={"url": "https://graph.facebook.com/media-temp/xyz"}
            )
        return httpx.Response(200, content=b"produccion-real-sin-cliente-inyectado")

    monkeypatch.setattr(httpx.Client, "request", _fake_request)

    client = GraphMediaClient(access_token=_TOKEN, api_version="v21.0")
    assert client._client is None  # ninguna instancia inyectada (camino real)

    downloaded = client.fetch_media(_MEDIA_ID)

    assert downloaded.content == b"produccion-real-sin-cliente-inyectado"
    assert len(seen_requests) == 2
