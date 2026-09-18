"""Esquemas de derechos del titular (HABEAS DATA/GDPR-like) — SPEC-021."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.contact import ContactOut


class ContactPersonalDataExportOut(BaseModel):
    """Exportación de datos personales de un contacto (derecho de acceso)."""

    contact: dict
    conversations: list[dict]


class ContactEraseOut(BaseModel):
    """Resultado de anonimizar (borrado lógico) los datos de un contacto."""

    contact: ContactOut
    detail: str = "Datos personales anonimizados (borrado lógico, C2)."
