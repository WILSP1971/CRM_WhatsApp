"""Recuperación top-k por similitud coseno en `pgvector` — SPEC-017 RF-07.

Embebe la consulta con el mismo `AIClient`/modelo de embeddings usado en la
ingesta (SPEC-016) y busca los `k` chunks más similares dentro del tenant de
la sesión (RLS/ADR-004): la query NUNCA añade un filtro manual de tenant_id
porque el aislamiento lo garantiza la política RLS de la sesión (`SET LOCAL
app.tenant_id`, fijada por `get_tenant_db`) — igual que el resto de routers
del proyecto. Además, se excluyen documentos/chunks/embeddings inactivos
(borrado lógico, C2).

Usa el operador de distancia coseno de `pgvector` (`<=>`, compatible con el
índice HNSW `vector_cosine_ops` creado en SPEC-012). `similarityScore` se
reporta como `1 - distancia_coseno` (a mayor score, más similar), acotado a
[0, 1] para consumo directo por `draft_service`/la API.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.embedding import Embedding
from app.services.ai_service import AIClient

DEFAULT_TOP_K = 5
MAX_TOP_K = 20


class TopKConfigError(ValueError):
    """`top_k` fuera de rango permitido."""


@dataclass(frozen=True)
class RetrievedChunk:
    """Un chunk recuperado, con su fuente y score de similitud coseno."""

    chunk_id: str
    document_id: str
    source: str
    excerpt: str
    similarity_score: float


def _validar_top_k(top_k: int) -> None:
    if top_k <= 0:
        raise TopKConfigError("top_k debe ser > 0")
    if top_k > MAX_TOP_K:
        raise TopKConfigError(f"top_k no puede superar {MAX_TOP_K}")


def retrieve_top_k(
    db: Session,
    ai_client: AIClient,
    *,
    query: str,
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """Recupera los `top_k` chunks más similares a `query` dentro del tenant
    de la sesión de BD (RLS ya activa vía `get_tenant_db`).

    No filtra manualmente por `tenant_id`: la sesión ya tiene `app.tenant_id`
    fijado (RLS fail-closed, ADR-004) — es la misma defensa en profundidad que
    usa el resto de servicios/routers del proyecto (p.ej.
    `app/services/message_service.py`).
    """
    _validar_top_k(top_k)

    query_embedding = ai_client.embed(query)

    distance = Embedding.vector.cosine_distance(query_embedding.vector).label(
        "distance"
    )
    stmt = (
        select(Embedding, Chunk, Document, distance)
        .join(Chunk, Chunk.id == Embedding.chunk_id)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Embedding.activo.is_(True),
            Chunk.activo.is_(True),
            Document.activo.is_(True),
        )
        .order_by(distance.asc())
        .limit(top_k)
    )

    results: list[RetrievedChunk] = []
    for _embedding, chunk, document, dist in db.execute(stmt).all():
        similarity = max(0.0, min(1.0, 1.0 - float(dist)))
        results.append(
            RetrievedChunk(
                chunk_id=str(chunk.id),
                document_id=str(document.id),
                source=document.nombre_archivo,
                excerpt=chunk.contenido,
                similarity_score=round(similarity, 6),
            )
        )
    return results
