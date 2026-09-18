"""Router `contacts` — SPEC-014.

Todos los endpoints:
  - Requieren JWT válido (`get_current_user`) -> 401 si falta/inválido.
  - Usan `get_tenant_db` (sesión con `app.tenant_id` ya fijado) -> RLS aísla
    por tenant a nivel de motor, además del filtro explícito por
    `Contact.tenant_id`/RLS implícito (defensa en profundidad).
  - Listados excluyen `activo=false` por defecto (C2, borrado lógico).
  - `DELETE` marca `activo=False`; NUNCA hace DELETE físico (C2).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_db
from app.api.pagination import paginate
from app.core.audit_log import log_personal_data_access
from app.core.request_id import get_request_id
from app.models.contact import Contact
from app.models.user import User
from app.schemas.common import Page
from app.schemas.contact import ContactCreate, ContactOut, ContactUpdate

router = APIRouter(prefix="/contacts", tags=["Contacts"])


def _get_contact_activo_or_404(db: Session, contact_id: uuid.UUID) -> Contact:
    """Busca un contacto activo. RLS ya acota a la sesión por tenant; el 404
    es indistinguible entre "no existe" y "es de otro tenant" (no filtra
    información cross-tenant)."""
    contact = db.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.activo.is_(True))
    )
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contacto no encontrado"
        )
    return contact


@router.get("", response_model=Page[ContactOut])
def list_contacts(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    nombre: str
    | None = Query(default=None, description="Filtro por nombre (contiene)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> Page[ContactOut]:
    """Lista contactos del tenant autenticado (paginado; excluye inactivos)."""
    stmt = (
        select(Contact)
        .where(Contact.activo.is_(True))
        .order_by(Contact.created_at.desc())
    )
    if nombre:
        stmt = stmt.where(Contact.nombre.ilike(f"%{nombre}%"))
    page_result = paginate(db, stmt, page=page, page_size=page_size, schema=ContactOut)

    log_personal_data_access(
        action="list",
        resource="contacts",
        resource_id=None,
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
        user_email=current_user.email,
        request_id=get_request_id(request),
        extra={"count": len(page_result.items)},
    )
    return page_result


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
def create_contact(
    payload: ContactCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> ContactOut:
    """Crea un contacto en el tenant autenticado."""
    contact = Contact(
        tenant_id=current_user.tenant_id,
        nombre=payload.nombre,
        telefono=payload.telefono,
        email=payload.email,
        created_by=current_user.email,
    )
    db.add(contact)
    db.flush()
    db.refresh(contact)

    log_personal_data_access(
        action="create",
        resource="contacts",
        resource_id=str(contact.id),
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
        user_email=current_user.email,
        request_id=get_request_id(request),
    )
    return ContactOut.model_validate(contact)


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(
    contact_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> ContactOut:
    """Obtiene un contacto por id dentro del tenant autenticado (404 si no existe)."""
    contact = _get_contact_activo_or_404(db, contact_id)

    log_personal_data_access(
        action="read",
        resource="contacts",
        resource_id=str(contact_id),
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
        user_email=current_user.email,
        request_id=get_request_id(request),
    )
    return ContactOut.model_validate(contact)


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: uuid.UUID,
    payload: ContactUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> ContactOut:
    """Actualiza parcialmente un contacto del tenant autenticado."""
    contact = _get_contact_activo_or_404(db, contact_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(contact, field, value)
    db.flush()
    db.refresh(contact)

    log_personal_data_access(
        action="update",
        resource="contacts",
        resource_id=str(contact_id),
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
        user_email=current_user.email,
        request_id=get_request_id(request),
    )
    return ContactOut.model_validate(contact)


@router.delete(
    "/{contact_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
def delete_contact(
    contact_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> None:
    """Borrado LÓGICO (C2): marca `activo=False`. Nunca DELETE físico."""
    contact = _get_contact_activo_or_404(db, contact_id)
    contact.activo = False
    db.flush()

    log_personal_data_access(
        action="delete_logical",
        resource="contacts",
        resource_id=str(contact_id),
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
        user_email=current_user.email,
        request_id=get_request_id(request),
    )
