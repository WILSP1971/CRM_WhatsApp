"""Tests de `app.services.telefonia.audio_store` — SPEC-035/037, ADR-009.

Unitarios puros (sin Postgres, sin Redis, sin red): cubren el cifrado en
reposo, la ida y vuelta cifrar/descifrar, y la defensa contra path traversal
en `audio_ref`.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.config import get_settings
from app.services.telefonia.audio_store import (
    AudioStoreError,
    build_audio_ref,
    load_audio,
    purge_audio,
    store_audio,
)


@pytest.fixture
def audio_store_tmp(tmp_path):
    settings = get_settings()
    original = settings.audio_storage_path
    settings.audio_storage_path = str(tmp_path)
    yield tmp_path
    settings.audio_storage_path = original


def test_build_audio_ref_is_namespaced_by_tenant():
    tenant_id = uuid.uuid4()
    ref = build_audio_ref(tenant_id=tenant_id, call_id="call-123")

    assert ref.startswith(f"{tenant_id}/")
    assert ref.endswith(".enc")


def test_build_audio_ref_sanitizes_unsafe_call_id_characters():
    tenant_id = uuid.uuid4()
    ref = build_audio_ref(tenant_id=tenant_id, call_id="../../etc/passwd")

    assert "/../" not in ref
    assert ".." not in ref.split("/", 1)[1]


def test_store_and_load_audio_round_trip(audio_store_tmp):
    tenant_id = uuid.uuid4()
    ref = build_audio_ref(tenant_id=tenant_id, call_id="call-roundtrip")
    original_bytes = b"contenido-de-audio-en-claro-para-round-trip"

    store_audio(audio_ref=ref, audio_bytes=original_bytes)
    recovered = load_audio(audio_ref=ref)

    assert recovered == original_bytes


def test_stored_audio_is_encrypted_on_disk(audio_store_tmp):
    tenant_id = uuid.uuid4()
    ref = build_audio_ref(tenant_id=tenant_id, call_id="call-encrypted")
    original_bytes = b"ESTE-TEXTO-NUNCA-DEBE-APARECER-EN-CLARO-EN-DISCO"

    store_audio(audio_ref=ref, audio_bytes=original_bytes)

    on_disk_path = audio_store_tmp / ref
    on_disk_bytes = on_disk_path.read_bytes()

    assert original_bytes not in on_disk_bytes


def test_stored_audio_is_not_a_valid_wav_without_decrypting(audio_store_tmp):
    """SPEC-041 (criterio de aceptación 'cifrado en reposo verificado'):
    confirma explícitamente que el fichero cifrado en disco NO es un WAV/OGG
    válido leído directamente (sin pasar por `load_audio`/Fernet) — más
    estricto que solo "el texto plano no aparece", verifica que ni siquiera
    la CABECERA del formato de audio es reconocible en claro."""
    tenant_id = uuid.uuid4()
    ref = build_audio_ref(tenant_id=tenant_id, call_id="call-wav-header")
    # Cabecera RIFF/WAVE real (los primeros 12 bytes de un .wav válido).
    fake_wav_bytes = b"RIFF" + (100).to_bytes(4, "little") + b"WAVEfmt "
    store_audio(audio_ref=ref, audio_bytes=fake_wav_bytes)

    on_disk_path = audio_store_tmp / ref
    on_disk_bytes = on_disk_path.read_bytes()

    # Ni la cabecera RIFF/WAVE ni el marcador OGG aparecen en el fichero
    # crudo: el cifrado Fernet produce un token base64 opaco sin firma de
    # formato de audio reconocible.
    assert not on_disk_bytes.startswith(b"RIFF")
    assert b"WAVE" not in on_disk_bytes
    assert not on_disk_bytes.startswith(b"OggS")

    # Confirma que SÍ se recupera correctamente pasando por el descifrado
    # (el cifrado es reversible con la clave correcta, no corrupción).
    recovered = load_audio(audio_ref=ref)
    assert recovered == fake_wav_bytes
    assert recovered.startswith(b"RIFF")


def test_purge_audio_deletes_the_physical_blob(audio_store_tmp):
    tenant_id = uuid.uuid4()
    ref = build_audio_ref(tenant_id=tenant_id, call_id="call-purge")
    store_audio(audio_ref=ref, audio_bytes=b"audio-a-purgar")

    on_disk_path = audio_store_tmp / ref
    assert on_disk_path.exists()

    deleted = purge_audio(audio_ref=ref)

    assert deleted is True
    assert not on_disk_path.exists()


def test_purge_audio_is_idempotent_when_already_purged(audio_store_tmp):
    tenant_id = uuid.uuid4()
    ref = build_audio_ref(tenant_id=tenant_id, call_id="call-purge-twice")
    store_audio(audio_ref=ref, audio_bytes=b"audio-a-purgar-dos-veces")

    first = purge_audio(audio_ref=ref)
    second = purge_audio(audio_ref=ref)

    assert first is True
    assert second is False  # ya no existía; no lanza error (idempotente)


def test_purge_audio_missing_file_returns_false_without_raising(audio_store_tmp):
    result = purge_audio(audio_ref="tenant-x/nunca-existio.enc")
    assert result is False


def test_purge_audio_path_traversal_is_rejected(audio_store_tmp):
    with pytest.raises(AudioStoreError):
        purge_audio(audio_ref="../outside.enc")


def test_stored_file_has_restrictive_permissions(audio_store_tmp):
    import stat

    tenant_id = uuid.uuid4()
    ref = build_audio_ref(tenant_id=tenant_id, call_id="call-perms")
    store_audio(audio_ref=ref, audio_bytes=b"audio")

    on_disk_path = audio_store_tmp / ref
    mode = stat.S_IMODE(on_disk_path.stat().st_mode)
    assert mode == 0o600


def test_audio_ref_path_traversal_is_rejected(audio_store_tmp):
    with pytest.raises(AudioStoreError):
        store_audio(audio_ref="../outside.enc", audio_bytes=b"x")


def test_load_audio_missing_file_raises_audio_store_error(audio_store_tmp):
    with pytest.raises(AudioStoreError):
        load_audio(audio_ref="tenant-x/no-existe.enc")


def test_load_audio_with_wrong_key_raises_audio_store_error(audio_store_tmp, monkeypatch):
    tenant_id = uuid.uuid4()
    ref = build_audio_ref(tenant_id=tenant_id, call_id="call-wrong-key")
    store_audio(audio_ref=ref, audio_bytes=b"audio-cifrado-con-clave-original")

    settings = get_settings()
    original_key = settings.audio_encryption_key
    settings.audio_encryption_key = "otra-clave-completamente-distinta-32chars"
    try:
        with pytest.raises(AudioStoreError):
            load_audio(audio_ref=ref)
    finally:
        settings.audio_encryption_key = original_key
