"""Router de derechos del titular (HABEAS DATA/GDPR-like) — SPEC-021.

Endpoints:
  - `GET  /contacts/{contact_id}/personal-data`  : exporta los datos
    personales del contacto (derecho de acceso/portabilidad).
  - `POST /contacts/{contact_id}/personal-data/erase` : anonimiza los datos
    identificantes del contacto y lo marca inactivo (derecho de
    supresión/HABEAS DATA) — borrado LÓGICO, nunca DELETE físico (C2).

Protección (auth + tenant, ADR-004): ambos endpoints requieren JWT válido
(`get_current_user` -> 401 si falta/inválido) y usan `get_tenant_db` (sesión
con `app.tenant_id` ya fijado) -> RLS impide que un usuario ejerza estos
derechos sobre un contacto de OTRO tenant, incluso si adivina el UUID (la
fila sencillamente no existe para esa sesión -> 404, igual que el resto de
endpoints de `contacts`, sin filtrar si "no existe" vs "es de otro tenant").
`current_user.rol` (embebido en el JWT, SPEC-013) queda disponible para
endurecer a un rol administrativo específico si el Lead lo pide en una SPEC
futura; por ahora seguimos el mismo criterio de autorización que el resto de
operaciones sobre `contacts` (cualquier agente autenticado del tenant).

Auditoría (RF de SPEC-021): cada acceso queda registrado vía
`app.core.audit_log.log_personal_data_access` con quién (`user_id`/tenant),
qué (`resource`/`resource_id`) y cuándo (timestamp del log), correlacionado
por `request_id` — NUNCA se vuelca el dato personal exportado/anonimizado en
el propio log de auditoría.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_db
from app.core.audit_log import log_personal_data_access
from app.core.request_id import get_request_id
from app.models.user import User
from app.schemas.contact import ContactOut
from app.schemas.privacy import ContactEraseOut, ContactPersonalDataExportOut
from app.services.privacy_service import (
    ContactNotFoundError,
    erase_contact_personal_data,
    export_contact_personal_data,
)

router = APIRouter(prefix="/contacts", tags=["Privacy (HABEAS DATA)"])


@router.get(
    "/{contact_id}/personal-data",
    response_model=ContactPersonalDataExportOut,
    responses={404: {"description": "Contacto no encontrado"}},
)
def export_personal_data(
    contact_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> ContactPersonalDataExportOut:
    """Exporta los datos personales del contacto (derecho de acceso/portabilidad)."""
    try:
        export = export_contact_personal_data(db, contact_id)
    except ContactNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contacto no encontrado"
        ) from exc

    log_personal_data_access(
        action="export",
        resource="contacts",
        resource_id=str(contact_id),
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
        user_email=current_user.email,
        request_id=get_request_id(request),
    )

    return ContactPersonalDataExportOut(
        contact=export.contact, conversations=export.conversations
    )


@router.post(
    "/{contact_id}/personal-data/erase",
    response_model=ContactEraseOut,
    responses={404: {"description": "Contacto no encontrado"}},
)
def erase_personal_data(
    contact_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> ContactEraseOut:
    """Anonimiza los datos del contacto y lo desactiva (borrado lógico, C2)."""
    try:
        contact = erase_contact_personal_data(db, contact_id)
    except ContactNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contacto no encontrado"
        ) from exc

    log_personal_data_access(
        action="erase",
        resource="contacts",
        resource_id=str(contact_id),
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
        user_email=current_user.email,
        request_id=get_request_id(request),
    )

    return ContactEraseOut(contact=ContactOut.model_validate(contact))
