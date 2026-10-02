"""Almacén de audio cifrado en reposo on-prem (SPEC-035/037, ADR-009).

Escribe/lee el fichero de audio de una llamada bajo `AUDIO_STORAGE_PATH`
(volumen local montado por `docker-compose.yml`, `audio_store`), cifrado con
Fernet (AES-128-CBC + HMAC, `cryptography.fernet`) usando `AUDIO_ENCRYPTION_KEY`
(C3, obligatorio fuera de development).

CHECKPOINT SENSIBLE (RNF-41/RNF-43): este módulo NUNCA envía el audio a un
tercero — solo lee/escribe el volumen local. No importa `httpx`/ningún
cliente de red (auditado por `check-externos-backend.sh`): es almacenamiento
puro, no transporte. El transporte de descarga (si el PBX es externo) vive en
`app/services/telefonia/pbx_client.py`, un módulo separado.

`audio_ref` (persistido en `calls.audio_ref`, SPEC-036) es un identificador
opaco relativo al almacén — NUNCA la ruta absoluta del filesystem ni el
binario — para no filtrar detalles de infraestructura en la BD ni en logs.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class AudioStoreError(RuntimeError):
    """Fallo de E/S o de cifrado al operar sobre el almacén de audio."""


def _fernet_key_from_secret(raw_secret: str) -> bytes:
    """Deriva una clave Fernet (32 bytes urlsafe-base64) a partir del secreto
    de configuración (`AUDIO_ENCRYPTION_KEY`), que puede tener cualquier
    longitud/formato (placeholder de desarrollo o secreto real del gestor de
    secretos). Se normaliza con SHA-256 + base64 urlsafe, requisito exacto de
    `Fernet` (32 bytes)."""
    import base64
    import hashlib

    digest = hashlib.sha256(raw_secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    settings = get_settings()
    return Fernet(_fernet_key_from_secret(settings.audio_encryption_key))


def _resolve_path(audio_ref: str) -> Path:
    """Resuelve `audio_ref` (identificador opaco, p.ej. `<tenant_id>/<uuid>.enc`)
    a una ruta ABSOLUTA dentro de `AUDIO_STORAGE_PATH`, rechazando cualquier
    intento de escapar el directorio base (path traversal) — defensa en
    profundidad aunque `audio_ref` se genera internamente y nunca proviene
    directamente de un input externo sin normalizar."""
    settings = get_settings()
    base = Path(settings.audio_storage_path).resolve()
    candidate = (base / audio_ref).resolve()
    if base not in candidate.parents and candidate != base:
        raise AudioStoreError(f"audio_ref fuera del almacén permitido: {audio_ref!r}")
    return candidate


def build_audio_ref(*, tenant_id: uuid.UUID | str, call_id: str) -> str:
    """Genera un identificador opaco y único para el audio de una llamada,
    namespaced por tenant (defensa adicional, aunque el aislamiento real lo
    da RLS sobre `calls.audio_ref`, no la ruta del filesystem)."""
    safe_call_id = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in call_id
    )
    return f"{tenant_id}/{safe_call_id}-{uuid.uuid4().hex[:8]}.enc"


def store_audio(*, audio_ref: str, audio_bytes: bytes) -> None:
    """Cifra `audio_bytes` con Fernet y lo escribe en `AUDIO_STORAGE_PATH`
    bajo `audio_ref`. Crea los directorios intermedios (namespacing por
    tenant) con permisos restrictivos (0700)."""
    path = _resolve_path(audio_ref)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        encrypted = _fernet().encrypt(audio_bytes)
        # Escritura atómica: fichero temporal + rename, para que un fallo a
        # mitad de escritura nunca deje un fichero parcial/corrupto legible.
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_bytes(encrypted)
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(path)
    except OSError as exc:
        raise AudioStoreError(f"No se pudo escribir el audio cifrado: {exc}") from exc


def purge_audio(*, audio_ref: str) -> bool:
    """Borra FÍSICAMENTE el blob de audio cifrado referenciado por `audio_ref`
    (SPEC-041, política de retención) — el ÚNICO punto del código donde el
    audio se elimina del disco (fuera de esto, el ciclo de vida es
    exclusivamente borrado lógico, C2).

    Idempotente: si el fichero ya no existe (purga previa, o nunca se llegó
    a escribir) NO lanza error, retorna `False`. Retorna `True` si el
    fichero existía y se borró en esta llamada. Quien invoca (el job de
    retención) es responsable de limpiar `Call.audio_ref` y marcar
    `Call.audio_purged_at` — este módulo solo gestiona el almacén, no el
    modelo de datos (mismo criterio que `store_audio`/`load_audio`).
    """
    path = _resolve_path(audio_ref)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise AudioStoreError(f"No se pudo purgar el audio cifrado: {exc}") from exc


def load_audio(*, audio_ref: str) -> bytes:
    """Lee y descifra el audio referenciado por `audio_ref`. Usado por el
    `stt_worker` (SPEC-038, fuera de alcance aquí) para obtener el audio en
    claro SOLO en memoria de proceso, nunca reescrito a disco sin cifrar."""
    path = _resolve_path(audio_ref)
    try:
        encrypted = path.read_bytes()
    except OSError as exc:
        raise AudioStoreError(f"No se pudo leer el audio cifrado: {exc}") from exc
    try:
        return _fernet().decrypt(encrypted)
    except InvalidToken as exc:
        raise AudioStoreError(
            "El audio cifrado no pudo descifrarse (clave incorrecta o "
            "fichero corrupto)."
        ) from exc
