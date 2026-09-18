"""
Tests de los endpoints de derechos del titular (HABEAS DATA/GDPR-like,
SPEC-021) contra PostgreSQL real.

Requiere el `db` de `docker-compose.yml` con el esquema aplicado vía
Alembic; si no hay Postgres accesible se SKIPEAN automáticamente (ver
`tests/conftest.py::postgres_engine`), mismo patrón que
`tests/test_api_v1_integration.py`.

Qué se verifica (criterios de aceptación de SPEC-021):
  1. `GET .../personal-data` exporta los datos del contacto (auth + tenant).
  2. `POST .../personal-data/erase` anonimiza campos identificantes y
     desactiva el contacto (borrado LÓGICO, C2, nunca DELETE físico).
  3. Aislamiento cross-tenant (RLS, ADR-004): un usuario del tenant A no
     puede exportar/anonimizar el contacto del tenant B (404, dato intacto).
  4. El acceso queda auditado (structlog) sin volcar el dato personal crudo.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
import structlog

# `client` y `api_as_tenant` son fixtures compartidos, definidos en
# `tests/conftest.py` (disponibles automáticamente por pytest, sin import
# explícito).


def test_export_personal_data_happy_path(client, api_as_tenant, two_tenants_with_data):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(f"/api/v1/contacts/{data['contact_a_id']}/personal-data")
        assert response.status_code == 200
        body = response.json()
        assert body["contact"]["id"] == str(data["contact_a_id"])
        assert body["contact"]["nombre"] == "Contacto Confidencial A"
        assert "conversations" in body


def test_export_personal_data_audits_access_without_leaking_raw_data(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    with structlog.testing.capture_logs() as captured:
        with api_as_tenant(data["tenant_a_id"]):
            response = client.get(
                f"/api/v1/contacts/{data['contact_a_id']}/personal-data"
            )
    assert response.status_code == 200

    audit_entries = [e for e in captured if e.get("event") == "personal_data_access"]
    assert len(audit_entries) == 1
    entry = audit_entries[0]
    assert entry["action"] == "export"
    assert entry["resource"] == "contacts"
    assert entry["resource_id"] == str(data["contact_a_id"])
    assert entry["tenant_id"] == str(data["tenant_a_id"])

    # El log de auditoría NUNCA contiene el nombre/teléfono crudo del contacto.
    serialized = str(captured)
    assert "Contacto Confidencial A" not in serialized
    assert "3000000001" not in serialized


def test_erase_personal_data_anonymizes_and_soft_deletes(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.post(
            f"/api/v1/contacts/{data['contact_a_id']}/personal-data/erase"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["contact"]["nombre"] != "Contacto Confidencial A"
        assert body["contact"]["telefono"] is None
        assert body["contact"]["activo"] is False

    # Verificación fuera de RLS (owner de test): la fila SIGUE existiendo
    # (nunca DELETE físico, C2) pero anonimizada.
    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT nombre, telefono, email, activo, anonymized_at "
                "FROM contacts WHERE id = :id"
            ),
            {"id": data["contact_a_id"]},
        ).fetchone()
        assert row is not None, "El contacto fue borrado FÍSICAMENTE (viola C2)"
        assert row.nombre != "Contacto Confidencial A"
        assert row.telefono is None
        assert row.email is None
        assert row.activo is False
        assert row.anonymized_at is not None


def test_erase_personal_data_is_idempotent(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    """Un segundo intento de anonimizar no falla ni sobrescribe la fecha original."""
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        first = client.post(
            f"/api/v1/contacts/{data['contact_a_id']}/personal-data/erase"
        )
        assert first.status_code == 200
        first_anonymized_at = first.json()["contact"]

        second = client.post(
            f"/api/v1/contacts/{data['contact_a_id']}/personal-data/erase"
        )
        assert second.status_code == 200
        assert second.json()["contact"]["nombre"] == first_anonymized_at["nombre"]


def test_tenant_a_cannot_export_personal_data_of_tenant_b(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(f"/api/v1/contacts/{data['contact_b_id']}/personal-data")
        assert response.status_code == 404


def test_tenant_a_cannot_erase_personal_data_of_tenant_b(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.post(
            f"/api/v1/contacts/{data['contact_b_id']}/personal-data/erase"
        )
        assert response.status_code == 404

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT nombre, activo FROM contacts WHERE id = :id"),
            {"id": data["contact_b_id"]},
        ).fetchone()
        assert row.nombre == "Contacto Confidencial B"
        assert row.activo is True


def test_export_personal_data_requires_auth(client, two_tenants_with_data):
    """Sin JWT -> 401 (no se puede ejercer el derecho sin autenticación)."""
    response = client.get(f"/api/v1/contacts/{uuid.uuid4()}/personal-data")
    assert response.status_code == 401
