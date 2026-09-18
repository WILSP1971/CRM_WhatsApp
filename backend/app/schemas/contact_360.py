"""Esquema de "contacto 360°" — SPEC-014 RF.

Agrega el contacto + sus conversaciones + el historial de mensajes de cada
una, todo dentro del mismo tenant (RLS ya garantiza el aislamiento; el
endpoint además filtra explícitamente por `contact_id` + tenant en la query,
defensa en profundidad igual que `get_current_user`).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.contact import ContactOut
from app.schemas.message import MessageOut


class ConversationWithMessages(BaseModel):
    """Conversación con su historial de mensajes embebido."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID
    canal: str
    estado: str
    activo: bool
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]

    model_config = {"from_attributes": True}


class Contact360Out(BaseModel):
    """Contacto + conversaciones (con mensajes) del mismo tenant."""

    contact: ContactOut
    conversations: list[ConversationWithMessages]
