"""Router `messages` — SPEC-014.

Los mensajes se anidan bajo su conversación (`/conversations/{id}/messages`)
porque no tienen sentido de negocio fuera de una conversación. Mismo patrón
de seguridad: JWT + `get_tenant_db` (RLS), sin inactivos por defecto (C2),
borrado lógico en DELETE. Alta de mensajes: no incluye edición de contenido
(fuera de alcance SPEC-014; los mensajes son inmutables salvo borrado lógico,
igual que un log de conversación real).
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_db
from app.api.pagination import paginate
from app.core.redis_client import get_redis_client
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.schemas.common import Page
from app.schemas.message import MessageCreate, MessageOut
from app.services.message_service import create_message as persist_message
from app.services.message_service import schedule_sentiment_analysis

router = APIRouter(
    prefix="/conversations/{conversation_id}/messages", tags=["Messages"]
)


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


def _get_message_activo_or_404(
    db: Session, conversation_id: uuid.UUID, message_id: uuid.UUID
) -> Message:
    message = db.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
            Message.activo.is_(True),
        )
    )
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Mensaje no encontrado"
        )
    return message


@router.get("", response_model=Page[MessageOut])
def list_messages(
    conversation_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> Page[MessageOut]:
    """Lista mensajes de una conversación del tenant autenticado (paginado)."""
    _get_conversation_activa_or_404(db, conversation_id)
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.activo.is_(True))
        .order_by(Message.created_at.asc())
    )
    return paginate(db, stmt, page=page, page_size=page_size, schema=MessageOut)


def _run_schedule_sentiment_analysis(message: Message) -> None:
    """Wrapper sync para `BackgroundTasks` (endpoint REST sync): ejecuta el
    encolado async del sentimiento (SPEC-018) DESPUÉS de responder al
    cliente, sin bloquear el ciclo request/response (RF de SPEC-018)."""
    asyncio.run(schedule_sentiment_analysis(get_redis_client(), message=message))


@router.post("", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def create_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> MessageOut:
    """Crea un mensaje en una conversación del tenant autenticado.

    Persistencia delegada en `app.services.message_service.create_message`
    (SPEC-015), compartida con el canal WebSocket para no duplicar la lógica.
    El análisis de sentimiento (SPEC-018) se encola en `BackgroundTasks`
    -tras responder al cliente- para no bloquear la creación del mensaje.
    """
    _get_conversation_activa_or_404(db, conversation_id)
    message = persist_message(
        db,
        tenant_id=current_user.tenant_id,
        conversation_id=conversation_id,
        remitente=payload.remitente,
        contenido=payload.contenido,
        created_by=current_user.email,
    )
    background_tasks.add_task(_run_schedule_sentiment_analysis, message)
    return MessageOut.model_validate(message)


@router.get("/{message_id}", response_model=MessageOut)
def get_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> MessageOut:
    """Obtiene un mensaje por id dentro de la conversación/tenant autenticado."""
    _get_conversation_activa_or_404(db, conversation_id)
    message = _get_message_activo_or_404(db, conversation_id, message_id)
    return MessageOut.model_validate(message)


@router.delete(
    "/{message_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
def delete_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> None:
    """Borrado LÓGICO (C2): marca `activo=False`. Nunca DELETE físico."""
    _get_conversation_activa_or_404(db, conversation_id)
    message = _get_message_activo_or_404(db, conversation_id, message_id)
    message.activo = False
    db.flush()
