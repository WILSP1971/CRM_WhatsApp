"""Helper de paginación compartido por los routers de dominio — SPEC-014."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.schemas.common import Page

ModelT = TypeVar("ModelT")
SchemaT = TypeVar("SchemaT", bound=BaseModel)


def paginate(
    db: Session,
    stmt: Select,
    *,
    page: int,
    page_size: int,
    schema: type[SchemaT],
) -> Page[SchemaT]:
    """Aplica `LIMIT/OFFSET` a `stmt` y devuelve un `Page[schema]`.

    `stmt` debe ser un `select(Model)...` ya filtrado (p.ej. `activo=True`,
    `contact_id=...`); esta función solo añade el conteo total y el recorte
    de página, sin tocar el filtrado de negocio (responsabilidad del router).
    """
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    return Page[schema](
        items=[schema.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
