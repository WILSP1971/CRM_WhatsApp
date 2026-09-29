"""Tests de `app.services.telefonia.tts_engine` — SPEC-067/069, ADR-014.

Cubre:
  (a) normalización de texto (cifras/siglas expandidas) — sin dependencias
      externas, siempre corre.
  (b) límite de longitud sintetizable (Adenda SPEC-067) — `Synthesizable
      TextTooLongError` antes de intentar la síntesis.
  (c) síntesis END-TO-END con el motor Piper REAL (guion -> OGG/Opus válido)
      — se SKIPEA automáticamente si los pesos de la voz o `ffmpeg` no están
      disponibles en el entorno (mismo criterio de skip condicional que
      `test_stt_worker.py` con Postgres: la lógica se prueba siempre, la
      infraestructura real solo si está presente).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.telefonia import tts_engine

_SPIKE_VOICES_DIR = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "perf"
    / "tts_viability"
    / "voices"
    / "piper"
)
_VOICE_NAME = "es_ES-davefx-medium"


def _voz_disponible() -> bool:
    return (_SPIKE_VOICES_DIR / f"{_VOICE_NAME}.onnx").exists() and (
        _SPIKE_VOICES_DIR / f"{_VOICE_NAME}.onnx.json"
    ).exists()


def _ffmpeg_disponible() -> bool:
    return shutil.which("ffmpeg") is not None


# ---------------------------------------------------------------------------
# (a) Normalización de texto
# ---------------------------------------------------------------------------


def test_normalize_expands_simple_number_to_words():
    assert tts_engine.normalize_text("Tiene 5 mensajes") == "Tiene cinco mensajes"


def test_normalize_expands_large_number_to_words():
    resultado = tts_engine.normalize_text("El saldo es 45000 pesos")
    assert "cuarenta y cinco mil" in resultado
    assert "45000" not in resultado


def test_normalize_expands_acronym_letter_by_letter():
    assert tts_engine.normalize_text("Consulte su EPS") == "Consulte su E P S"


def test_normalize_does_not_touch_lowercase_words():
    assert tts_engine.normalize_text("Hola, buenas tardes") == "Hola, buenas tardes"


def test_normalize_handles_zero():
    assert tts_engine.normalize_text("Tiene 0 pendientes") == "Tiene cero pendientes"


def test_normalize_combines_numbers_and_acronyms():
    resultado = tts_engine.normalize_text("Su NIT 123 está registrado")
    assert resultado == "Su N I T ciento veinte y tres está registrado"


# ---------------------------------------------------------------------------
# (b) Límite de longitud sintetizable (Adenda SPEC-067)
# ---------------------------------------------------------------------------


def test_synthesize_raises_before_inference_when_text_too_long(monkeypatch):
    settings = get_settings()
    original = settings.respuesta_tts_max_chars
    settings.respuesta_tts_max_chars = 20
    try:
        # Guarda: si esto llamara al motor real, un guion falso de 21+ chars
        # con una voz inexistente lanzaría un TtsEngineError distinto (no
        # `SynthesizableTextTooLongError`) — la ausencia de esa excepción
        # confirma que el chequeo de longitud corre ANTES de tocar Piper.
        with pytest.raises(tts_engine.SynthesizableTextTooLongError):
            tts_engine.synthesize_to_ogg_opus("x" * 21, voice_name="voz-inexistente")
    finally:
        settings.respuesta_tts_max_chars = original


def test_synthesize_length_check_uses_original_text_not_normalized(monkeypatch):
    """El límite se aplica sobre el texto ORIGINAL (antes de normalizar) —
    normalizar puede alargarlo (una cifra corta se expande a varias
    palabras); el límite debe reflejar lo que el agente aprobó, no una
    versión ya inflada."""
    settings = get_settings()
    original = settings.respuesta_tts_max_chars
    settings.respuesta_tts_max_chars = 5
    try:
        # "12345" son 5 caracteres (dentro del límite) pero se normaliza a
        # una frase mucho más larga — el chequeo debe pasar (no debe lanzar
        # SynthesizableTextTooLongError) porque se mide ANTES de normalizar.
        # Como la voz no existe, debe fallar con TtsEngineError (fallo de
        # carga), NO con SynthesizableTextTooLongError.
        with pytest.raises(tts_engine.TtsEngineError) as exc_info:
            tts_engine.synthesize_to_ogg_opus("12345", voice_name="voz-inexistente")
        assert not isinstance(exc_info.value, tts_engine.SynthesizableTextTooLongError)
    finally:
        settings.respuesta_tts_max_chars = original


# ---------------------------------------------------------------------------
# (c) Síntesis end-to-end con el motor Piper REAL
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _voz_disponible(),
    reason="Pesos de la voz Piper es_ES-davefx-medium no disponibles en este entorno",
)
@pytest.mark.skipif(
    not _ffmpeg_disponible(), reason="ffmpeg no disponible en este entorno"
)
def test_synthesize_to_ogg_opus_end_to_end_with_real_piper_engine(monkeypatch):
    """Verificación de que el pipeline REAL (Piper + ffmpeg) funciona: guion
    -> clip OGG/Opus con bytes reales (no un mock del motor)."""
    settings = get_settings()
    original_dir = settings.piper_voice_dir
    settings.piper_voice_dir = str(_SPIKE_VOICES_DIR)
    try:
        resultado = tts_engine.synthesize_to_ogg_opus(
            "Hola, su NIT es 123456789 y el saldo pendiente es de 45000 pesos.",
            voice_name=_VOICE_NAME,
        )
    finally:
        settings.piper_voice_dir = original_dir

    assert len(resultado.ogg_opus_bytes) > 0
    # Firma de contenedor OGG ("OggS") al inicio del binario.
    assert resultado.ogg_opus_bytes[:4] == b"OggS"
    assert resultado.modelo_tts == f"piper/{_VOICE_NAME}"
    assert "ciento veinte y tres millones" in resultado.texto_normalizado
    assert resultado.tiempo_sintesis_segundos > 0
    assert resultado.tiempo_transcodificacion_segundos > 0


@pytest.mark.skipif(
    not _voz_disponible(),
    reason="Pesos de la voz Piper es_ES-davefx-medium no disponibles en este entorno",
)
def test_load_voice_raises_when_weights_missing(tmp_path):
    settings = get_settings()
    original_dir = settings.piper_voice_dir
    settings.piper_voice_dir = str(tmp_path)
    try:
        with pytest.raises(tts_engine.TtsEngineError):
            tts_engine._load_voice("voz-que-no-existe")
    finally:
        settings.piper_voice_dir = original_dir
