"""Servicio de resumen de llamada — SPEC-039.

Genera un resumen conciso de una llamada de voz ya transcrita
(`call_transcripts.segmentos`, SPEC-038) usando el LLM local (`AIClient.chat`,
SPEC-016). Es la ÚNICA pieza de prompt NUEVA de SPEC-039 (registrada en
`prompt-lab/prompts/2026-09-20-resumen-llamada-voz.md`, CHECKPOINT C8); el
resto del enriquecimiento (sentimiento, borrador RAG con citas) REUTILIZA
`app.services.sentiment_service`/`app.services.rag.draft_service` tal cual
(SPEC-017/018), sin crear componentes de IA nuevos.

Este módulo NO abre ninguna conexión de red por sí mismo (mismo criterio que
`sentiment_service`): delega TODA la inferencia en `AIClient`
(`app.services.ai_service`), el único punto de la aplicación autorizado a
hablar con el servicio de IA interno (CHECKPOINT SENSIBLE, `.no-externo`,
RNF-01, ADR-005/ADR-009).

Modo degradado (R-21, mismo criterio que `classify_sentiment`/
`generate_rag_draft`): si el LLM local no responde
(`AIServiceUnavailableError`/`AIServiceResponseError`), `generate_call_summary`
NO propaga la excepción — devuelve un `CallSummaryResult` sin texto
(`summary=None`) para que el llamador (`stt_worker`) nunca vea bloqueada ni
revertida la persistencia de la transcripción ya confirmada (SPEC-038) por
una falla del servicio de IA.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from app.services.ai_service import AIClient, AIServiceError

logger = structlog.get_logger(__name__)

# Prompt registrado en prompt-lab/ (CHECKPOINT C8, SPEC-039):
# ../../../prompt-lab/prompts/2026-09-20-resumen-llamada-voz.md
_SYSTEM_PROMPT = (
    "Eres un asistente que redacta resúmenes de llamadas para un agente "
    "humano de atención al cliente en español (es-CO). Dada la transcripción "
    "completa de una llamada (posiblemente con turnos de agente y cliente "
    "marcados), redacta un resumen breve y objetivo (máximo 5 líneas) que "
    "incluya: el motivo de la llamada, los puntos clave tratados y, si "
    "aplica, el siguiente paso acordado. Responde ÚNICAMENTE con el texto "
    "del resumen, sin encabezados ni explicaciones adicionales. Si la "
    "transcripción no tiene contenido suficiente para resumir, responde "
    'exactamente: "Sin contenido suficiente para resumir."'
)


@dataclass(frozen=True)
class CallSummaryResult:
    """Resultado de resumir el texto de una llamada.

    `summary=None` indica modo degradado (LLM no disponible) — el llamador
    debe tratarlo como "resumen aún no disponible", nunca como un error que
    deba interrumpir el flujo (la transcripción ya persistida NO se revierte).
    """

    summary: str | None
    model: str | None
    used_fallback: bool


def generate_call_summary(
    ai_client: AIClient, *, transcript_text: str
) -> CallSummaryResult:
    """Genera un resumen del texto completo de una llamada con el LLM local.

    Nunca lanza una excepción: ante indisponibilidad del LLM, devuelve un
    `CallSummaryResult` en modo degradado (`summary=None`,
    `used_fallback=True`) para no bloquear ni revertir la persistencia de la
    transcripción ya confirmada por `stt_worker` (SPEC-038).
    """
    try:
        result = ai_client.chat(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": transcript_text},
            ],
            temperature=0.2,
        )
    except AIServiceError as exc:
        logger.warning(
            "call_summary_degraded_ai_unavailable",
            error=str(exc),
        )
        return CallSummaryResult(summary=None, model=None, used_fallback=True)

    summary = result.content.strip()
    if not summary:
        logger.warning("call_summary_degraded_empty_response")
        return CallSummaryResult(summary=None, model=result.model, used_fallback=True)

    return CallSummaryResult(summary=summary, model=result.model, used_fallback=False)
