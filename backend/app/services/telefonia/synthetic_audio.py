"""Generador de audio SINTÉTICO (WAV, PCM 16-bit mono) — módulo neutral
compartido entre `tests/fixtures_audio/synthetic_call_audio.py` (SPEC-042,
HAWKEYE) y `tools/pbx_recording_simulator.py` (SPEC-043, QUICKSILVER).

CHECKPOINT DE DISEÑO (WOLVERINE, corrección de hallazgo bloqueante en la
revisión de SPEC-043): las funciones de generación de WAV vivían duplicadas
en ambos sitios. Se extraen aquí, a `app/services/telefonia/` (módulo de
dominio de telefonía real, junto a `audio_store.py`, `wer.py`,
`pbx_client.py`, `stt_engine.py`), en vez de que `tools/` (herramienta de
operación) importe directamente desde `tests/` (código de test, que
normalmente no se empaqueta ni se distribuye junto con las herramientas de
operación). Ambos consumidores importan desde aquí; no hay duplicación.

El contenido generado es un tono sintético (onda senoidal) + tramos de
silencio, con el módulo estándar `wave` de Python (sin `numpy`) — NO es habla
real. Sirve para ejercitar el FORMATO del pipeline de audio (ingesta,
almacenamiento cifrado, cola STT, worker STT), no para medir WER real (ver
`tests/test_stt_wer.py` y el reporte de HAWKEYE para esa limitación).

Todos los ficheros generados son EFÍMEROS/ficticios: sin datos personales,
sin PHI, sin voces reales (C3).
"""

from __future__ import annotations

import io
import math
import struct
import wave

SAMPLE_RATE_HZ = 16_000  # mismo sample rate que espera faster-whisper internamente
SAMPLE_WIDTH_BYTES = 2  # PCM 16-bit
CHANNELS = 1  # mono


def tone_samples(
    *, duration_seconds: float, frequency_hz: float, amplitude: float = 0.2
) -> bytes:
    """Genera `duration_seconds` de una onda senoidal pura a `frequency_hz`,
    codificada como PCM 16-bit little-endian — sin `numpy` (no disponible en
    este sandbox), solo `math`/`struct` de la librería estándar."""
    n_samples = int(SAMPLE_RATE_HZ * duration_seconds)
    max_amplitude = int(32767 * amplitude)
    frames = bytearray()
    for i in range(n_samples):
        value = int(
            max_amplitude * math.sin(2 * math.pi * frequency_hz * i / SAMPLE_RATE_HZ)
        )
        frames += struct.pack("<h", value)
    return bytes(frames)


def silence_samples(*, duration_seconds: float) -> bytes:
    n_samples = int(SAMPLE_RATE_HZ * duration_seconds)
    return b"\x00\x00" * n_samples


def build_wav_bytes(pcm_frames: bytes) -> bytes:
    """Empaqueta PCM crudo en un contenedor WAV válido (cabecera RIFF/WAVE) —
    exactamente el formato que `audio_store.store_audio`/`stt_engine.
    transcribe_audio_bytes` esperan recibir como `audio_bytes` en memoria."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(SAMPLE_RATE_HZ)
        wav_file.writeframes(pcm_frames)
    return buffer.getvalue()


def is_valid_wav(audio_bytes: bytes) -> bool:
    """Valida que `audio_bytes` sea un WAV bien formado (cabecera RIFF/WAVE
    parseable) con el sample rate/canales esperados."""
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            return (
                wav_file.getnchannels() == CHANNELS
                and wav_file.getframerate() == SAMPLE_RATE_HZ
            )
    except (wave.Error, EOFError):
        return False
