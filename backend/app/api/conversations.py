"""Router `conversations` — SPEC-014.

Mismo patrón de seguridad que `app/api/contacts.py`: JWT + `get_tenant_db`
(RLS), listados sin inactivos por defecto (C2), borrado lógico en DELETE.
El `contact_id` de alta se valida contra el propio tenant (RLS ya lo filtra;
un `contact_id` de otro tenant simplemente no se encuentra -> 404 explícito
en vez de fallar la FK con un 500).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_db
from app.api.pagination import paginate
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.user import User
from app.schemas.common import Page
from app.schemas.conversation import (
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
)

router = APIRouter(prefix="/conversations", tags=["Conversations"])


def _get_conversation_activa_or_404(
    db: Session, conversation_id: uuid.UUID
) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.activo.is_(True)
        )
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversación no encontrada"
        )
    return conversation


def _validar_contact_id_del_tenant(db: Session, contact_id: uuid.UUID) -> None:
    """RLS ya acota `contacts` al tenant de sesión; si el id no aparece, es
    inexistente o de otro tenant -> 404 (sin distinguir, evita fuga de info)."""
    exists = db.scalar(
        select(Contact.id).where(Contact.id == contact_id, Contact.activo.is_(True))
    )
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contacto no encontrado"
        )


@router.get("", response_model=Page[ConversationOut])
def list_conversations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    contact_id: uuid.UUID
    | None = Query(default=None, description="Filtro por contacto"),
    estado: str | None = Query(default=None, description="Filtro por estado"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> Page[ConversationOut]:
    """Lista conversaciones del tenant autenticado (paginado; excluye inactivas)."""
    stmt = (
        select(Conversation)
        .where(Conversation.activo.is_(True))
        .order_by(Conversation.created_at.desc())
    )
    if contact_id is not None:
        stmt = stmt.where(Conversation.contact_id == contact_id)
    if estado is not None:
        stmt = stmt.where(Conversation.estado == estado)
    return paginate(db, stmt, page=page, page_size=page_size, schema=ConversationOut)


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> ConversationOut:
    """Crea una conversación en el tenant autenticado, ligada a un contacto propio."""
    _validar_contact_id_del_tenant(db, payload.contact_id)
    conversation = Conversation(
        tenant_id=current_user.tenant_id,
        contact_id=payload.contact_id,
        canal=payload.canal,
        estado=payload.estado,
        created_by=current_user.email,
    )
    db.add(conversation)
    db.flush()
    db.refresh(conversation)
    return ConversationOut.model_validate(conversation)


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> ConversationOut:
    """Obtiene una conversación por id dentro del tenant autenticado."""
    conversation = _get_conversation_activa_or_404(db, conversation_id)
    return ConversationOut.model_validate(conversation)


@router.patch("/{conversation_id}", response_model=ConversationOut)
def update_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> ConversationOut:
    """Actualiza el estado de una conversación del tenant autenticado."""
    conversation = _get_conversation_activa_or_404(db, conversation_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(conversation, field, value)
    db.flush()
    db.refresh(conversation)
    return ConversationOut.model_validate(conversation)


@router.delete(
    "/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> None:
    """Borrado LÓGICO (C2): marca `activo=False`. Nunca DELETE físico."""
    conversation = _get_conversation_activa_or_404(db, conversation_id)
    conversation.activo = False
    db.flush()
