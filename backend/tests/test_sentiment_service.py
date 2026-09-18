"""Tests de `app.services.sentiment_service` — SPEC-018.

Unitarios, `AIClient` MOCKEADO (`FakeAIClient` de `tests/rag_ai_client_fake.py`,
extendido aquí con un doble local que permite fijar la respuesta cruda del
"LLM" para ejercitar el parsing). Sin Postgres, sin red real.
"""

from __future__ import annotations

import pytest

from app.services.ai_service import AIServiceUnavailableError
from app.services.sentiment_service import classify_sentiment


class _FakeChatResult:
    def __init__(self, content: str):
        self.content = content
        self.model = "qwen2.5-fake"
        self.raw: dict = {}


class _FakeChatClient:
    """Doble mínimo de `AIClient` que solo implementa `chat` (lo único que
    usa `sentiment_service`), con respuesta o falla configurable."""

    def __init__(self, *, response: str | None = None, unavailable: bool = False):
        self._response = response
        self._unavailable = unavailable
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages, *, model=None, temperature=0.2, stream=False):
        if self._unavailable:
            raise AIServiceUnavailableError("servicio de IA no disponible (fake)")
        self.calls.append(messages)
        return _FakeChatResult(self._response or "")


@pytest.mark.parametrize(
    "raw_response,expected_label,expected_score",
    [
        ('{"sentimiento": "positivo", "score": 0.95}', "positivo", 0.95),
        ('{"sentimiento": "neutral", "score": 0.5}', "neutral", 0.5),
        ('{"sentimiento": "negativo", "score": 0.8}', "negativo", 0.8),
        # Texto adicional alrededor del JSON (el modelo a veces "explica").
        (
            'Claro, aquí está: {"sentimiento": "positivo", "score": 0.7} '
            "espero que ayude.",
            "positivo",
            0.7,
        ),
        # Sinónimos/mayúsculas tolerados.
        ('{"sentimiento": "POSITIVE", "score": 0.6}', "positivo", 0.6),
        # Score fuera de rango se clampa, no se descarta.
        ('{"sentimiento": "negativo", "score": 1.5}', "negativo", 1.0),
    ],
)
def test_classify_sentiment_parses_well_formed_and_tolerant_responses(
    raw_response, expected_label, expected_score
):
    client = _FakeChatClient(response=raw_response)

    result = classify_sentiment(client, contenido="mensaje de prueba")

    assert result.label == expected_label
    assert result.score == pytest.approx(expected_score)
    assert result.used_fallback is False


@pytest.mark.parametrize(
    "raw_response",
    [
        "no puedo ayudarte con eso",  # sin JSON en absoluto
        "{}",  # JSON vacío
        '{"sentimiento": "muy contento", "score": 0.9}',  # etiqueta no reconocida
        '{"sentimiento": "positivo", "score": "no-numero"}',  # score no numérico
        "",  # respuesta vacía
        '{"sentimiento": null, "score": null}',
    ],
)
def test_classify_sentiment_falls_back_to_none_on_unparseable_response(raw_response):
    """RF (parsing robusto): una respuesta rara del LLM cae a fallback, sin
    lanzar excepción y sin inventar una etiqueta no soportada."""
    client = _FakeChatClient(response=raw_response)

    result = classify_sentiment(client, contenido="mensaje de prueba")

    assert result.label is None
    assert result.score is None
    assert result.used_fallback is True


def test_classify_sentiment_degrades_when_ai_service_unavailable():
    """Modo degradado (R-21): si el LLM local no responde, no se lanza una
    excepción — se devuelve un resultado sin clasificar."""
    client = _FakeChatClient(unavailable=True)

    result = classify_sentiment(client, contenido="mensaje de prueba")

    assert result.label is None
    assert result.score is None
    assert result.used_fallback is True


def test_classify_sentiment_sends_system_prompt_and_user_content():
    client = _FakeChatClient(response='{"sentimiento": "neutral", "score": 0.5}')

    classify_sentiment(client, contenido="¿Cuál es el horario de atención?")

    assert len(client.calls) == 1
    messages = client.calls[0]
    assert messages[0]["role"] == "system"
    assert messages[1] == {
        "role": "user",
        "content": "¿Cuál es el horario de atención?",
    }
