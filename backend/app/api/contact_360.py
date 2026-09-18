"""Router "contacto 360°" — SPEC-014 RF.

Agrega en una sola respuesta: el contacto, sus conversaciones y el historial
de mensajes de cada conversación, todo del mismo tenant autenticado (JWT +
`get_tenant_db` -> RLS). Pensado como vista de apoyo al agente (Bandeja
omnicanal de la SPA); no reemplaza los endpoints CRUD individuales.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_db
from app.core.audit_log import log_personal_data_access
from app.core.request_id import get_request_id
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.schemas.contact import ContactOut
from app.schemas.contact_360 import Contact360Out, ConversationWithMessages
from app.schemas.message import MessageOut

router = APIRouter(prefix="/contacts", tags=["Contact 360"])


@router.get("/{contact_id}/360", response_model=Contact360Out)
def get_contact_360(
    contact_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> Contact360Out:
    """Contacto + conversaciones + historial de mensajes (mismo tenant)."""
    contact = db.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.activo.is_(True))
    )
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contacto no encontrado"
        )

    conversations = db.scalars(
        select(Conversation)
        .where(Conversation.contact_id == contact_id, Conversation.activo.is_(True))
        .order_by(Conversation.created_at.desc())
    ).all()

    conversations_out: list[ConversationWithMessages] = []
    for conversation in conversations:
        messages = db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.activo.is_(True),
            )
            .order_by(Message.created_at.asc())
        ).all()
        conversations_out.append(
            ConversationWithMessages(
                id=conversation.id,
                tenant_id=conversation.tenant_id,
                contact_id=conversation.contact_id,
                canal=conversation.canal,
                estado=conversation.estado,
                activo=conversation.activo,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                messages=[MessageOut.model_validate(m) for m in messages],
            )
        )

    log_personal_data_access(
        action="read",
        resource="contact_360",
        resource_id=str(contact_id),
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
        user_email=current_user.email,
        request_id=get_request_id(request),
        extra={"conversations_count": len(conversations_out)},
    )

    return Contact360Out(
        contact=ContactOut.model_validate(contact),
        conversations=conversations_out,
    )
