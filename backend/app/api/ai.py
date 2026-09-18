"""Router `ai` — diagnóstico del subsistema de IA local (SPEC-016).

Expone únicamente un endpoint de salud/diagnóstico (protegido por auth, igual
que el resto de la API core) que reporta si el servicio Ollama interno está
disponible y qué modelos están configurados por env. No expone generación ni
embeddings de uso libre: eso queda para SPEC-017 (RAG)/SPEC-018 (sentimiento),
fuera de alcance de esta SPEC.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.models.user import User
from app.schemas.ai import AIHealthOut
from app.services.ai_service import AIClient, get_ai_client

router = APIRouter(prefix="/ai", tags=["IA local"])


@router.get(
    "/health",
    response_model=AIHealthOut,
    responses={401: {"description": "No autenticado"}},
)
def get_ai_health(
    current_user: User = Depends(get_current_user),
    ai_client: AIClient = Depends(get_ai_client),
) -> AIHealthOut:
    """Disponibilidad del servicio de IA local (Ollama, red interna).

    Requiere autenticación (mismo criterio que el resto de la API core,
    SPEC-013): no es un endpoint público, ya que revela si el subsistema de
    IA on-prem está operativo.
    """
    settings = get_settings()
    return AIHealthOut(
        disponible=ai_client.is_available(),
        modelo_llm=settings.ai_llm_model,
        modelo_embeddings=settings.ai_embedding_model,
    )
