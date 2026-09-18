"""Servicio de análisis de sentimiento de mensajes entrantes — SPEC-018.

Clasifica el `contenido` de un mensaje en {positivo, neutral, negativo} +
`score` (0..1) usando el LLM local (`AIClient.chat`, SPEC-016). Este módulo
NO abre ninguna conexión de red por sí mismo: delega TODA la inferencia en
`AIClient` (`app.services.ai_service`), el único punto de la aplicación
autorizado a hablar con el servicio de IA interno (CHECKPOINT SENSIBLE,
`.no-externo`, RNF-01/CE-21).

Parsing robusto (RF, R-27): el LLM local responde en lenguaje natural, no con
una API tipada, así que la respuesta puede venir con texto extra alrededor
del JSON, comillas simples, mayúsculas, sinónimos ("positive"/"pos") o
directamente sin poder parsearse. `classify_sentiment` intenta extraer un
JSON válido de la respuesta; si el formato es inesperado, cae a un resultado
neutral con score `None` (nunca lanza una excepción de parsing hacia el
llamador) y `used_fallback=True` para que el llamador pueda auditar cuántas
clasificaciones fueron degradadas por formato.

Modo degradado (R-21, requisito "no bloquea la recepción del mensaje"): si el
LLM local no responde (`AIServiceUnavailableError`/`AIServiceResponseError`),
`classify_sentiment` NO propaga la excepción — devuelve un `SentimentResult`
sin etiqueta (`label=None`, `score=None`, `used_fallback=True`) para que el
flujo de mensajería nunca se rompa por una falla del servicio de IA.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import structlog

from app.models.message import SENTIMIENTOS_VALIDOS
from app.services.ai_service import AIClient, AIServiceError

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = (
    "Eres un clasificador de sentimiento para mensajes de atención al "
    "cliente en español (es-CO). Dado el mensaje de un contacto, responde "
    "ÚNICAMENTE con un objeto JSON, sin texto adicional ni explicaciones, "
    'con el formato exacto: {"sentimiento": "positivo|neutral|negativo", '
    '"score": <numero entre 0 y 1>}. El campo "score" representa la '
    "confianza de la clasificación. Ejemplos:\n"
    '- "Muchas gracias, excelente atención!" -> '
    '{"sentimiento": "positivo", "score": 0.95}\n'
    '- "Quisiera saber el horario de atención" -> '
    '{"sentimiento": "neutral", "score": 0.80}\n'
    '- "Llevo 3 días esperando y nadie me responde, pesimo servicio" -> '
    '{"sentimiento": "negativo", "score": 0.92}'
)

# Extrae el primer objeto `{...}` de la respuesta del LLM, tolerando texto
# adicional antes/después (el modelo a veces antepone explicaciones pese a
# la instrucción del prompt).
_JSON_OBJECT_RE = re.compile(r"\{.*?\}", re.DOTALL)

# Sinónimos/variantes tolerados por si el modelo no respeta el vocabulario
# exacto pedido en el prompt (robustez adicional del parsing, R-27).
_LABEL_ALIASES = {
    "positivo": "positivo",
    "positive": "positivo",
    "pos": "positivo",
    "neutral": "neutral",
    "neutro": "neutral",
    "neu": "neutral",
    "negativo": "negativo",
    "negative": "negativo",
    "neg": "negativo",
}


@dataclass(frozen=True)
class SentimentResult:
    """Resultado de clasificar el sentimiento de un texto.

    `label`/`score` en `None` indican modo degradado (LLM no disponible o
    respuesta no parseable) — el llamador debe tratarlo como "sin
    clasificar", NUNCA como un error que deba interrumpir el flujo.
    """

    label: str | None
    score: float | None
    used_fallback: bool
    raw_response: str | None = None


def _normalizar_label(valor: object) -> str | None:
    if not isinstance(valor, str):
        return None
    candidato = _LABEL_ALIASES.get(valor.strip().lower())
    if candidato in SENTIMIENTOS_VALIDOS:
        return candidato
    return None


def _normalizar_score(valor: object) -> float | None:
    try:
        score = float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if score != score:  # NaN
        return None
    # Clampa a [0, 1] en vez de descartar (un modelo local puede devolver
    # 1.0/100 o valores ligeramente fuera de rango por redondeo).
    return max(0.0, min(1.0, score))


def _parse_llm_response(content: str) -> tuple[str | None, float | None]:
    """Intenta extraer `(label, score)` de la respuesta cruda del LLM.

    Nunca lanza: cualquier formato inesperado devuelve `(None, None)`.
    """
    match = _JSON_OBJECT_RE.search(content)
    if match is None:
        return None, None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None, None
    if not isinstance(data, dict):
        return None, None

    label = _normalizar_label(data.get("sentimiento") or data.get("label"))
    score = _normalizar_score(data.get("score") or data.get("confidence"))
    return label, score


def classify_sentiment(ai_client: AIClient, *, contenido: str) -> SentimentResult:
    """Clasifica el sentimiento de `contenido` con el LLM local.

    Nunca lanza una excepción: ante indisponibilidad del LLM o una respuesta
    no parseable, devuelve un `SentimentResult` en modo degradado
    (`label=None`, `score=None`, `used_fallback=True`) para no bloquear la
    persistencia/recepción del mensaje (RF, modo degradado R-21).
    """
    try:
        result = ai_client.chat(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": contenido},
            ],
            temperature=0.0,
        )
    except AIServiceError as exc:
        logger.warning(
            "sentiment_classification_degraded_ai_unavailable",
            error=str(exc),
        )
        return SentimentResult(label=None, score=None, used_fallback=True)

    label, score = _parse_llm_response(result.content)
    # RF-07 exige etiqueta + score: si cualquiera de los dos no se pudo
    # extraer/normalizar, se trata como fallback completo (nunca se persiste
    # una etiqueta "a medias" sin su score, ni un score sin etiqueta).
    if label is None or score is None:
        logger.warning(
            "sentiment_classification_degraded_unparseable_response",
            raw_response=result.content[:500],
        )
        return SentimentResult(
            label=None, score=None, used_fallback=True, raw_response=result.content
        )

    return SentimentResult(
        label=label, score=score, used_fallback=False, raw_response=result.content
    )
