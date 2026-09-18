"""Generación de borrador RAG con citas trazables — SPEC-017 RF-07.

Construye un prompt con el contexto recuperado (`retrieval_service`) y pide al
LLM local (`AIClient.chat`, SPEC-016) un borrador de respuesta. El borrador
SIEMPRE incluye **al menos 3 citas trazables** (`source`, `excerpt`,
`similarityScore`), independientemente de lo que el LLM haya escrito en su
texto libre: las citas se arman de forma determinista a partir de los chunks
realmente recuperados (contrato `rag.citations`), no se dejan a la
discreción del modelo generativo. Así, aunque el LLM local no siga el
formato pedido en el prompt, el contrato de salida sigue siendo verificable.

Human-in-the-loop (SPEC-019, fuera de alcance aquí): este servicio SOLO
genera el borrador; no lo envía ni lo marca como aprobado.

Modo degradado (R-21): si no hay suficientes chunks recuperados (<3) o el LLM
no está disponible, se propaga la condición explícita (`InsufficientContext
Error`/`AIServiceError`) para que el llamador (endpoint) devuelva un estado
claro en vez de fabricar citas falsas.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.ai_service import AIClient
from app.services.rag.retrieval_service import (
    DEFAULT_TOP_K,
    RetrievedChunk,
    retrieve_top_k,
)

MIN_CITATIONS = 3


class InsufficientContextError(RuntimeError):
    """No hay suficientes chunks recuperados para garantizar ≥3 citas."""


@dataclass(frozen=True)
class Citation:
    """Cita trazable: contrato `rag.citations` (Entregable #1)."""

    source: str
    excerpt: str
    similarity_score: float
    chunk_id: str
    document_id: str


@dataclass(frozen=True)
class RagDraftResult:
    """Borrador generado con su lista de citas trazables (≥3)."""

    content: str
    model: str
    citations: list[Citation]


def _build_prompt(query: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
    context_blocks = "\n\n".join(
        f"[Fuente {i + 1}: {chunk.source}]\n{chunk.excerpt}"
        for i, chunk in enumerate(chunks)
    )
    system_prompt = (
        "Eres un asistente que redacta borradores de respuesta para un agente "
        "humano de atención al cliente. Responde SOLO con base en el contexto "
        "proporcionado. Si el contexto no alcanza para responder con certeza, "
        "dilo explícitamente. Cita las fuentes por su número entre corchetes, "
        "por ejemplo [Fuente 1], cuando uses información de un fragmento."
    )
    user_prompt = (
        f"Contexto recuperado:\n\n{context_blocks}\n\n"
        f"Pregunta/consulta del cliente:\n{query}\n\n"
        "Redacta un borrador de respuesta breve y profesional en español."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def generate_rag_draft(
    db: Session,
    ai_client: AIClient,
    *,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    min_citations: int = MIN_CITATIONS,
) -> RagDraftResult:
    """Recupera contexto del tenant y genera un borrador con ≥`min_citations`
    citas trazables.

    Criterio de aceptación SPEC-017: "Ante una pregunta, el borrador generado
    incluye ≥3 citas con source + excerpt + similarityScore" y "las citas
    apuntan a chunks reales del documento ingerido". Por eso las citas se
    construyen SIEMPRE a partir de `RetrievedChunk` reales (nunca inventadas
    por el LLM), tomando los `min_citations` chunks de mayor similitud.
    """
    # `effective_top_k` nunca es menor que `min_citations`: así siempre hay
    # material suficiente para cumplir el contrato de ≥3 citas trazables,
    # sin importar cómo el llamador configure `top_k`.
    effective_top_k = max(top_k, min_citations)
    retrieved = retrieve_top_k(db, ai_client, query=query, top_k=effective_top_k)

    if len(retrieved) < min_citations:
        raise InsufficientContextError(
            f"Solo se recuperaron {len(retrieved)} chunk(s) del tenant; se "
            f"requieren al menos {min_citations} para citas trazables."
        )

    messages = _build_prompt(query, retrieved)
    chat_result = ai_client.chat(messages)

    citations = [
        Citation(
            source=chunk.source,
            excerpt=chunk.excerpt,
            similarity_score=chunk.similarity_score,
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
        )
        for chunk in retrieved
    ]

    return RagDraftResult(
        content=chat_result.content, model=chat_result.model, citations=citations
    )
