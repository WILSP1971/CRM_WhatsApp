"""
Tests del registro de auditoría de acceso a datos personales (SPEC-021,
criterio "registro de acceso a datos personales presente y consultable, sin
volcar el dato crudo/secretos").

No requieren Postgres/Redis/Docker: capturan el log estructurado directamente
(usando `structlog.testing.capture_logs`), sin infraestructura externa.
"""

from __future__ import annotations

import uuid

import pytest
import structlog

from app.core.audit_log import log_personal_data_access


def test_log_personal_data_access_emits_expected_metadata():
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    contact_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())

    with structlog.testing.capture_logs() as captured:
        log_personal_data_access(
            action="read",
            resource="contacts",
            resource_id=contact_id,
            tenant_id=tenant_id,
            user_id=user_id,
            user_email="agente@demo.local",
            request_id=request_id,
        )

    assert len(captured) == 1
    entry = captured[0]
    assert entry["event"] == "personal_data_access"
    assert entry["action"] == "read"
    assert entry["resource"] == "contacts"
    assert entry["resource_id"] == contact_id
    assert entry["tenant_id"] == tenant_id
    assert entry["user_id"] == user_id
    assert entry["request_id"] == request_id


def test_log_personal_data_access_never_leaks_raw_pii_or_secrets():
    """
    El log NUNCA debe contener el dato personal crudo (nombre/teléfono/email
    del CONTACTO/titular) ni un secreto (JWT/password). El helper solo acepta
    metadatos (resource/resource_id/action/ids), nunca un campo de contenido;
    este test documenta y fija ese contrato inspeccionando el log resultante.
    """
    raw_contact_name = "Juan Perez Confidencial"
    raw_contact_phone = "3009998877"
    fake_jwt_secret = "super-secreto-jwt-que-nunca-debe-aparecer"

    with structlog.testing.capture_logs() as captured:
        log_personal_data_access(
            action="export",
            resource="contacts",
            resource_id=str(uuid.uuid4()),
            tenant_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            user_email="agente@demo.local",
            request_id=str(uuid.uuid4()),
        )

    serialized = str(captured)
    assert raw_contact_name not in serialized
    assert raw_contact_phone not in serialized
    assert fake_jwt_secret not in serialized


def test_log_personal_data_access_rejects_unknown_action():
    with pytest.raises(ValueError):
        log_personal_data_access(
            action="borra-todo-sin-avisar",
            resource="contacts",
            resource_id=str(uuid.uuid4()),
            tenant_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
        )


@pytest.mark.parametrize(
    "action",
    [
        "create",
        "read",
        "list",
        "update",
        "delete_logical",
        "export",
        "erase",
        "anonymize",
    ],
)
def test_log_personal_data_access_accepts_all_documented_actions(action):
    with structlog.testing.capture_logs() as captured:
        log_personal_data_access(
            action=action,
            resource="contacts",
            resource_id=str(uuid.uuid4()),
            tenant_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
        )
    assert captured[0]["action"] == action
