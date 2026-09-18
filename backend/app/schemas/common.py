"""Esquemas comunes de paginación y error — SPEC-014.

`Page[T]` envuelve cualquier listado con metadatos de paginación uniformes
para todos los routers de dominio (`contacts`, `conversations`, `messages`,
`documents`). `ErrorResponse` documenta la forma de los errores 4xx/5xx en el
contrato OpenAPI (sin filtrar detalles internos/stack traces, CHECKPOINT C3).
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

# Límites de paginación: evitan listados sin cota (RNF-04, p95 acotado) y
# devuelven 422 (validación de Pydantic/FastAPI) ante valores fuera de rango.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    """Parámetros de paginación comunes (query params `page`/`page_size`)."""

    page: int = Field(default=1, ge=1, description="Número de página (1-based).")
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Tamaño de página (máx. 100).",
    )


class Page(BaseModel, Generic[T]):
    """Envoltorio de paginación uniforme para listados tenant-aware."""

    items: list[T]
    total: int = Field(..., description="Total de registros que cumplen el filtro.")
    page: int
    page_size: int


class ErrorResponse(BaseModel):
    """Forma homogénea de error HTTP (sin stack traces ni detalles internos)."""

    detail: str
