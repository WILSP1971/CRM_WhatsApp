"""Tests de `app.services.telefonia.wer.compute_wer` — SPEC-042 (CE-41, "WER
documentado").

Estos tests SÍ se ejecutan completos en este sandbox (sin PostgreSQL/GPU):
verifican el ALGORITMO de WER con texto conocido, no requieren infraestructura
externa. Ver `tests/fixtures_audio/synthetic_call_audio.py` y el reporte de
HAWKEYE para por qué el WER "real" sobre audio con habla real es-CO NO se
puede medir en este sandbox (el set de fixtures es audio sintético por tono,
sin habla).
"""

from __future__ import annotations

import pytest

from app.services.telefonia.wer import compute_wer


def test_identical_transcription_has_zero_wer():
    result = compute_wer(
        "hola buenas tardes quisiera consultar mi cita",
        "hola buenas tardes quisiera consultar mi cita",
    )
    assert result.wer == pytest.approx(0.0)
    assert result.substitutions == 0
    assert result.insertions == 0
    assert result.deletions == 0


def test_case_and_whitespace_are_normalized_before_comparison():
    result = compute_wer(
        "Hola Buenas Tardes",
        "  hola   buenas    tardes  ",
    )
    assert result.wer == pytest.approx(0.0)


def test_single_substitution():
    result = compute_wer(
        "quisiera consultar mi cita",
        "quisiera consultar mi cuenta",
    )
    assert result.substitutions == 1
    assert result.insertions == 0
    assert result.deletions == 0
    assert result.wer == pytest.approx(1 / 4)


def test_single_insertion():
    result = compute_wer(
        "quisiera consultar mi cita",
        "quisiera consultar mi cita por favor",
    )
    assert result.insertions == 2
    assert result.substitutions == 0
    assert result.deletions == 0
    assert result.wer == pytest.approx(2 / 4)


def test_single_deletion():
    result = compute_wer(
        "quisiera consultar mi cita de mañana",
        "quisiera consultar mi cita",
    )
    assert result.deletions == 2
    assert result.substitutions == 0
    assert result.insertions == 0
    assert result.wer == pytest.approx(2 / 6)


def test_completely_different_transcription_has_wer_one():
    result = compute_wer("hola buenas tardes", "xyz abc def")
    assert result.wer == pytest.approx(1.0)


def test_empty_reference_and_empty_hypothesis_has_zero_wer():
    result = compute_wer("", "")
    assert result.wer == pytest.approx(0.0)
    assert result.reference_word_count == 0


def test_empty_reference_with_nonempty_hypothesis_is_capped_at_one():
    """Caso borde documentado: sin palabras de referencia, cualquier
    contenido en la hipótesis se trata como WER 1.0 (no se deja crecer sin
    límite dividiendo por cero)."""
    result = compute_wer("", "esto no debería estar aquí")
    assert result.wer == pytest.approx(1.0)


def test_matches_property_reflects_correct_words():
    result = compute_wer(
        "hola buenas tardes quisiera consultar mi cita",
        "hola buenas tardes quisiera consultar mi cuenta",
    )
    # 6 de 7 palabras de referencia coinciden (1 sustitución: cita -> cuenta).
    assert result.matches == 6
    assert result.reference_word_count == 7


def test_wer_on_realistic_es_co_call_transcript_sample():
    """Ejemplo realista es-CO (texto ficticio, documentado como muestra de
    referencia para el reporte de WER — ver el docstring del módulo sobre por
    qué esto NO sustituye una medición con habla real)."""
    referencia = (
        "buenas tardes gracias por comunicarse con la clinica "
        "en que le puedo ayudar el dia de hoy"
    )
    hipotesis_con_errores_tipicos_stt = (
        "buenas tardes gracias por comunicarse con la clinica "
        "en que le puedo ayudar el día de hoy"
    )
    # "dia" vs "día": con la normalización actual (lower + split, SIN
    # remover tildes) estas son palabras DISTINTAS -> 1 sustitución. Se deja
    # así intencionalmente (documentado en el módulo): la normalización de
    # acentos es una decisión de negocio que puede endurecerse más adelante.
    result = compute_wer(referencia, hipotesis_con_errores_tipicos_stt)
    assert result.substitutions == 1
    assert result.reference_word_count == 17
    assert result.wer == pytest.approx(1 / 17)
