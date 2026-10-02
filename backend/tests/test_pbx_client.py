"""Tests de `app.services.telefonia.pbx_client` — SPEC-037, ADR-010.

Unitarios (sin red real): cubren la validación de allowlist de host (SOLO
`PBX_EXTERNAL_HOST` exacto), el rechazo cuando `PBX_EXTERNAL_ENABLED=false`
(SUP-42, comportamiento por defecto) y que este módulo es el ÚNICO punto de
egress de descarga (mockeando `httpx.Client` para no requerir red real).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.config import get_settings
from app.services.telefonia.pbx_client import (
    PbxDownloadError,
    PbxHostNotAllowedError,
    download_recording,
)


@pytest.fixture
def pbx_external_enabled():
    settings = get_settings()
    original_enabled = settings.pbx_external_enabled
    original_host = settings.pbx_external_host
    settings.pbx_external_enabled = True
    settings.pbx_external_host = "pbx.proveedor-demo.test"
    yield settings
    settings.pbx_external_enabled = original_enabled
    settings.pbx_external_host = original_host


def test_download_rejected_when_pbx_external_disabled():
    settings = get_settings()
    assert settings.pbx_external_enabled is False  # comportamiento por defecto (SUP-42)

    with pytest.raises(PbxHostNotAllowedError):
        download_recording(recording_url="https://pbx.proveedor-demo.test/rec/1.wav")


def test_download_rejected_for_host_outside_allowlist(pbx_external_enabled):
    with pytest.raises(PbxHostNotAllowedError):
        download_recording(
            recording_url="https://otro-host-no-permitido.test/rec/1.wav"
        )


def test_download_rejected_for_http_scheme_even_with_allowed_host(pbx_external_enabled):
    """SOLO 'https' está permitido (mismo criterio que
    `graph_client._validate_graph_host`, ADR-006/ADR-010): el audio es dato
    personal/posible PHI y nunca debe viajar en claro por HTTP, incluso si
    el host coincide exactamente con el permitido."""
    with pytest.raises(PbxHostNotAllowedError):
        download_recording(recording_url="http://pbx.proveedor-demo.test/rec/1.wav")


def test_download_rejected_for_subdomain_spoofing_attempt(pbx_external_enabled):
    """Un host que contiene el permitido como substring/subdominio falso NO
    debe aceptarse (mismo criterio anti-spoofing que graph_client.py)."""
    with pytest.raises(PbxHostNotAllowedError):
        download_recording(
            recording_url="https://evil.pbx.proveedor-demo.test.attacker.net/rec/1.wav"
        )


def test_download_succeeds_for_exact_allowed_host(pbx_external_enabled):
    fake_response = MagicMock()
    fake_response.content = b"audio-descargado-de-prueba"
    fake_response.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    fake_client.get.return_value = fake_response

    with patch("httpx.Client", return_value=fake_client):
        result = download_recording(
            recording_url="https://pbx.proveedor-demo.test/rec/1.wav"
        )

    assert result == b"audio-descargado-de-prueba"
    fake_client.get.assert_called_once()


def test_download_does_not_follow_redirects(pbx_external_enabled):
    """El cliente HTTP se construye con `follow_redirects=False` (defensa
    contra un PBX comprometido que redirija la petición fuera de la
    allowlist)."""
    import inspect

    from app.services.telefonia import pbx_client as pbx_client_module

    source = inspect.getsource(pbx_client_module)
    assert "follow_redirects=False" in source


def test_download_raises_pbx_download_error_on_http_failure(pbx_external_enabled):
    import httpx

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    fake_client.get.side_effect = httpx.ConnectError("conexión rechazada (simulada)")

    with patch("httpx.Client", return_value=fake_client):
        with pytest.raises(PbxDownloadError):
            download_recording(
                recording_url="https://pbx.proveedor-demo.test/rec/1.wav"
            )


def test_download_sends_bearer_auth_token_when_configured(pbx_external_enabled):
    settings = get_settings()
    original_token = settings.pbx_external_auth_token
    settings.pbx_external_auth_token = "token-de-prueba-no-real"

    fake_response = MagicMock()
    fake_response.content = b"audio"
    fake_response.raise_for_status = MagicMock()
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    fake_client.get.return_value = fake_response

    try:
        with patch("httpx.Client", return_value=fake_client):
            download_recording(
                recording_url="https://pbx.proveedor-demo.test/rec/1.wav"
            )
    finally:
        settings.pbx_external_auth_token = original_token

    _, kwargs = fake_client.get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer token-de-prueba-no-real"
