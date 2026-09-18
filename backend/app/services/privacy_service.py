"""
Derechos del titular (HABEAS DATA/GDPR-like) sobre un contacto — SPEC-021.

Implementa las dos operaciones que la SPEC exige para "exportar y eliminar
(lógico/anonimizar) los datos personales de un contacto bajo su tenant":

  - `export_contact_personal_data`: junta los datos personales del contacto
    (datos propios + conversaciones + mensajes) en una estructura serializable
    para entregarla al titular (portabilidad/derecho de acceso).
  - `erase_contact_personal_data`: anonimiza los campos identificantes del
    contacto (`nombre`, `telefono`, `email`) y lo marca `activo=False`
    (borrado lógico, C2) — NUNCA hace DELETE físico. El contenido de los
    mensajes NO se reescribe (son registros de la conversación, no
    identificadores del titular por sí mismos) pero deja de ser accesible
    para nuevas consultas de negocio porque el contacto ya no está activo;
    si el Lead pide además anonimizar el contenido de mensajes, es alcance
    adicional (OUT de esta SPEC).

Ambas operaciones se ejecutan SIEMPRE dentro de la sesión con `tenant_id` ya
fijado (`get_tenant_db`, RLS activa, ADR-004): un usuario nunca puede
exportar/anonimizar datos de otro tenant, ni siquiera con un `contact_id`
adivinado, porque RLS hace que la fila sencillamente no exista para esa
sesión.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.message import Message

# Marcador no identificante usado al anonimizar (no es un dato personal real,
# es una constante de dominio; documentado para BLACK WIDOW).
_ANONYMIZED_NAME = "Contacto anonimizado (HABEAS DATA)"


class ContactNotFoundError(Exception):
    """El contacto no existe (o no es del tenant de la sesión, ver RLS)."""


@dataclass(frozen=True)
class ContactPersonalDataExport:
    """Estructura de exportación de datos personales de un contacto."""

    contact: dict
    conversations: list[dict] = field(default_factory=list)


def _get_contact_or_raise(db: Session, contact_id: uuid.UUID) -> Contact:
    contact = db.scalar(select(Contact).where(Contact.id == contact_id))
    if contact is None:
        raise ContactNotFoundError(str(contact_id))
    return contact


def export_contact_personal_data(
    db: Session, contact_id: uuid.UUID
) -> ContactPersonalDataExport:
    """Exporta los datos personales del contacto (derecho de acceso/portabilidad).

    Lanza `ContactNotFoundError` si el contacto no existe en el tenant de la
    sesión (RLS ya garantiza el aislamiento; este 404 es indistinguible de
    "es de otro tenant", igual que el resto de endpoints de `contacts`).
    """
    contact = _get_contact_or_raise(db, contact_id)

    conversations = db.scalars(
        select(Conversation).where(Conversation.contact_id == contact.id)
    ).all()

    conversations_export: list[dict] = []
    for conversation in conversations:
        messages = db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc())
        ).all()
        conversations_export.append(
            {
                "id": str(conversation.id),
                "canal": conversation.canal,
                "estado": conversation.estado,
                "activo": conversation.activo,
                "created_at": conversation.created_at.isoformat(),
                "messages": [
                    {
                        "id": str(m.id),
                        "remitente": m.remitente,
                        "contenido": m.contenido,
                        "estado_entrega": m.estado_entrega,
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in messages
                ],
            }
        )

    return ContactPersonalDataExport(
        contact={
            "id": str(contact.id),
            "nombre": contact.nombre,
            "telefono": contact.telefono,
            "email": contact.email,
            "activo": contact.activo,
            "anonymized_at": (
                contact.anonymized_at.isoformat() if contact.anonymized_at else None
            ),
            "created_at": contact.created_at.isoformat(),
        },
        conversations=conversations_export,
    )


def erase_contact_personal_data(db: Session, contact_id: uuid.UUID) -> Contact:
    """Anonimiza los datos identificantes del contacto y lo desactiva (C2).

    Idempotente: si el contacto ya estaba anonimizado, no vuelve a
    sobrescribir `anonymized_at` (conserva la fecha original del ejercicio
    del derecho) pero sigue devolviendo el estado actual sin error.
    """
    contact = _get_contact_or_raise(db, contact_id)

    if contact.anonymized_at is None:
        contact.nombre = _ANONYMIZED_NAME
        contact.telefono = None
        contact.email = None
        contact.anonymized_at = datetime.now(timezone.utc)
    contact.activo = False

    db.flush()
    db.refresh(contact)
    return contact
