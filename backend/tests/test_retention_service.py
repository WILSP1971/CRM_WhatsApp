"""
Tests del servicio de retención/minimización de datos personales (SPEC-021)
contra PostgreSQL real.

Requiere el `db` de `docker-compose.yml` con el esquema aplicado vía
Alembic; si no hay Postgres accesible se SKIPEAN automáticamente (ver
`tests/conftest.py::postgres_engine`).

Qué se verifica (criterios de aceptación de SPEC-021):
  1. Solo los contactos INACTIVOS y vencidos (según `retention_days`) son
     candidatos; un contacto activo NUNCA es candidato, sin importar su edad.
  2. En modo dry-run (`enabled=False`) no se escribe nada (solo reporta).
  3. En modo habilitado (`enabled=True`), los candidatos quedan anonimizados
     y desactivados — nunca DELETE físico (C2).
  4. Un contacto ya anonimizado no se vuelve a procesar (no aparece dos
     veces como candidato).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app.services.retention_service import find_retention_candidates, run_retention_job


def _insert_contact(
    engine, *, tenant_id, activo, updated_at, anonymized_at=None, nombre="Contacto X"
):
    contact_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO contacts "
                "(id, tenant_id, nombre, telefono, activo, anonymized_at, "
                " created_at, updated_at) "
                "VALUES (:id, :tenant_id, :nombre, :telefono, :activo, "
                " :anonymized_at, :created_at, :updated_at)"
            ),
            {
                "id": contact_id,
                "tenant_id": tenant_id,
                "nombre": nombre,
                "telefono": f"300{uuid.uuid4().int % 10_000_000:07d}",
                "activo": activo,
                "anonymized_at": anonymized_at,
                "created_at": updated_at,
                "updated_at": updated_at,
            },
        )
    return contact_id


def test_active_contact_is_never_a_retention_candidate_even_if_old(
    postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    old_active_contact_id = _insert_contact(
        postgres_engine, tenant_id=tenant_id, activo=True, updated_at=old_date
    )

    candidates = find_retention_candidates(
        __import__("sqlalchemy.orm", fromlist=["Session"]).Session(postgres_engine),
        retention_days=90,
    )
    candidate_ids = {c.id for c in candidates}
    assert old_active_contact_id not in candidate_ids


def test_recently_inactive_contact_is_not_yet_a_candidate(
    postgres_engine, two_tenants_with_data
):
    from sqlalchemy.orm import Session

    tenant_id = two_tenants_with_data["tenant_a_id"]
    recent_date = datetime.now(timezone.utc) - timedelta(days=5)
    recent_inactive_id = _insert_contact(
        postgres_engine, tenant_id=tenant_id, activo=False, updated_at=recent_date
    )

    with Session(postgres_engine) as session:
        candidates = find_retention_candidates(session, retention_days=90)
    candidate_ids = {c.id for c in candidates}
    assert recent_inactive_id not in candidate_ids


def test_old_inactive_non_anonymized_contact_is_a_candidate(
    postgres_engine, two_tenants_with_data
):
    from sqlalchemy.orm import Session

    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    old_inactive_id = _insert_contact(
        postgres_engine, tenant_id=tenant_id, activo=False, updated_at=old_date
    )

    with Session(postgres_engine) as session:
        candidates = find_retention_candidates(session, retention_days=90)
    candidate_ids = {c.id for c in candidates}
    assert old_inactive_id in candidate_ids


def test_already_anonymized_contact_is_not_a_candidate_again(
    postgres_engine, two_tenants_with_data
):
    from sqlalchemy.orm import Session

    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    already_anonymized_id = _insert_contact(
        postgres_engine,
        tenant_id=tenant_id,
        activo=False,
        updated_at=old_date,
        anonymized_at=old_date,
    )

    with Session(postgres_engine) as session:
        candidates = find_retention_candidates(session, retention_days=90)
    candidate_ids = {c.id for c in candidates}
    assert already_anonymized_id not in candidate_ids


def test_run_retention_job_dry_run_does_not_write(
    postgres_engine, two_tenants_with_data
):
    from sqlalchemy.orm import Session

    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    contact_id = _insert_contact(
        postgres_engine,
        tenant_id=tenant_id,
        activo=False,
        updated_at=old_date,
        nombre="No Debe Cambiar",
    )

    with Session(postgres_engine) as session:
        result = run_retention_job(session, retention_days=90, enabled=False)

    assert result.dry_run is True
    assert result.candidates_found >= 1
    assert result.anonymized_contact_ids == []

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT nombre, anonymized_at FROM contacts WHERE id = :id"),
            {"id": contact_id},
        ).fetchone()
        assert row.nombre == "No Debe Cambiar"
        assert row.anonymized_at is None


def test_run_retention_job_enabled_anonymizes_candidates_without_physical_delete(
    postgres_engine, two_tenants_with_data
):
    from sqlalchemy.orm import Session

    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    contact_id = _insert_contact(
        postgres_engine,
        tenant_id=tenant_id,
        activo=False,
        updated_at=old_date,
        nombre="Debe Ser Anonimizado",
    )

    with Session(postgres_engine) as session:
        result = run_retention_job(session, retention_days=90, enabled=True)

    assert result.dry_run is False
    assert str(contact_id) in result.anonymized_contact_ids

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT nombre, telefono, activo, anonymized_at "
                "FROM contacts WHERE id = :id"
            ),
            {"id": contact_id},
        ).fetchone()
        assert row is not None, "El contacto fue borrado FÍSICAMENTE (viola C2)"
        assert row.nombre != "Debe Ser Anonimizado"
        assert row.telefono is None
        assert row.activo is False
        assert row.anonymized_at is not None
