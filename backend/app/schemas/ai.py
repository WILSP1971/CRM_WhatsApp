"""Schemas del subsistema de IA local — SPEC-016."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AIHealthOut(BaseModel):
    """Estado de disponibilidad del servicio de IA local (Ollama interno).

    No expone la URL completa del host interno en la respuesta (evita filtrar
    detalles de topología de red a un cliente autenticado sin necesidad); solo
    confirma disponibilidad y los modelos configurados por env.
    """

    model_config = ConfigDict(from_attributes=True)

    disponible: bool
    modelo_llm: str
    modelo_embeddings: str
