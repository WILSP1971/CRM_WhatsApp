"""Router `documents` — SPEC-014.

Alcance SPEC-014: alta de metadatos + CRUD tenant-aware (listar/obtener/
borrado lógico). La ingesta real del archivo, chunking y embeddings son de
SPEC-016/017 (fuera de alcance); aquí el documento nace en `estado=pendiente`
(default del modelo, SPEC-012) y ninguna transición de estado ocurre todavía.
Mismo patrón de seguridad que el resto de routers: JWT + `get_tenant_db`
(RLS), sin inactivos por defecto (C2), borrado lógico en DELETE.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_db
from app.api.pagination import paginate
from app.models.document import Document
from app.models.user import User
from app.schemas.common import Page
from app.schemas.document import DocumentCreate, DocumentOut

router = APIRouter(prefix="/documents", tags=["Documents"])


def _get_document_activo_or_404(db: Session, document_id: uuid.UUID) -> Document:
    document = db.scalar(
        select(Document).where(Document.id == document_id, Document.activo.is_(True))
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado"
        )
    return document


@router.get("", response_model=Page[DocumentOut])
def list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    estado: str | None = Query(default=None, description="Filtro por estado"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> Page[DocumentOut]:
    """Lista documentos del tenant autenticado (paginado; excluye inactivos)."""
    stmt = (
        select(Document)
        .where(Document.activo.is_(True))
        .order_by(Document.created_at.desc())
    )
    if estado is not None:
        stmt = stmt.where(Document.estado == estado)
    return paginate(db, stmt, page=page, page_size=page_size, schema=DocumentOut)


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: DocumentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> DocumentOut:
    """Registra los metadatos de un documento en el tenant autenticado."""
    document = Document(
        tenant_id=current_user.tenant_id,
        nombre_archivo=payload.nombre_archivo,
        tipo=payload.tipo,
        created_by=current_user.email,
    )
    db.add(document)
    db.flush()
    db.refresh(document)
    return DocumentOut.model_validate(document)


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> DocumentOut:
    """Obtiene un documento por id dentro del tenant autenticado."""
    document = _get_document_activo_or_404(db, document_id)
    return DocumentOut.model_validate(document)


@router.delete(
    "/{document_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> None:
    """Borrado LÓGICO (C2): marca `activo=False`. Nunca DELETE físico."""
    document = _get_document_activo_or_404(db, document_id)
    document.activo = False
    db.flush()
