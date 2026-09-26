"""
Tests del servicio de retención/minimización de datos personales (SPEC-021)
contra PostgreSQL real.

Requiere el `db` de `docker-compose.yml` con el esquema aplicado vía
Alembic; si no hay Postgres accesible se SKIPEAN automáticamente (ver
`tests/conftest.py::postgres_engine`).

CORRECCIÓN RLS (mismo hallazgo BLACK PANTHER que SPEC-041, ver
`tests/test_call_retention_service.py`): `contacts` está en
`TENANT_SCOPED_TABLES` (`app/db/rls.py`) con RLS ENABLE+FORCE. Este módulo
ahora ejerce `run_retention_job`/`find_retention_candidates` con el fixture
`app_engine` (rol de aplicación NO-superusuario `omnicore_app`, ADR-008;
mismo rol con el que corre el job en producción), NO con `postgres_engine`
(rol owner/superusuario, SIEMPRE exento de RLS por regla fija de Postgres,
incluso con `FORCE ROW LEVEL SECURITY`). Antes de esta corrección los tests
usaban `postgres_engine` para EJERCER `run_retention_job`: "pasaban" sin
detectar que, con el rol real de producción, el job nunca fijaba
`app.tenant_id` y por lo tanto veía CERO filas — un falso positivo (mismo
patrón de defecto ya documentado en `test_rls_isolation.py`/
`test_whatsapp_routing.py`/`test_call_retention_service.py`, ADR-008).
`postgres_engine` se sigue usando SOLO para bootstrap de fixtures
(`_insert_contact`) y para verificar estado "administrativo" tras la corrida
(SELECT de verificación, no forma parte del camino que se prueba).

`find_retention_candidates` se ejercita aquí con una sesión de `app_engine`
con `app.tenant_id` fijado manualmente (`set_tenant_session`) — refleja el
uso interno que ahora hace `run_retention_job` tenant por tenant.
`run_retention_job` en sí NO requiere que el llamador fije el tenant:
internamente recorre todos los tenants activos y fija `app.tenant_id` por
cada uno.

Qué se verifica (criterios de aceptación de SPEC-021):
  1. Solo los contactos INACTIVOS y vencidos (según `retention_days`) son
     candidatos; un contacto activo NUNCA es candidato, sin importar su edad.
  2. En modo dry-run (`enabled=False`) no se escribe nada (solo reporta).
  3. En modo habilitado (`enabled=True`), los candidatos quedan anonimizados
     y desactivados — nunca DELETE físico (C2).
  4. Un contacto ya anonimizado no se vuelve a procesar (no aparece dos
     veces como candidato).
  5. `run_retention_job` SÍ encuentra candidatos bajo RLS real (rol
     `omnicore_app`), demostrando la corrección del bloqueante RLS (mismo
     hallazgo que SPEC-041).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.session import set_tenant_session
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


def _session_with_tenant(engine, tenant_id) -> Session:
    """Sesión ORM con `app.tenant_id` fijado (`SET LOCAL`) dentro de una
    transacción explícita, usando `app_engine` (rol `omnicore_app`, ADR-008)
    — ejerce RLS real, mismo patrón que `tests/test_rls_isolation.py` /
    `tests/test_call_retention_service.py`."""
    session = Session(engine)
    session.begin()
    set_tenant_session(session, str(tenant_id))
    return session


def test_active_contact_is_never_a_retention_candidate_even_if_old(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    old_active_contact_id = _insert_contact(
        postgres_engine, tenant_id=tenant_id, activo=True, updated_at=old_date
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        candidates = find_retention_candidates(session, retention_days=90)
        candidate_ids = {c.id for c in candidates}
        session.rollback()
    assert old_active_contact_id not in candidate_ids


def test_recently_inactive_contact_is_not_yet_a_candidate(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    recent_date = datetime.now(timezone.utc) - timedelta(days=5)
    recent_inactive_id = _insert_contact(
        postgres_engine, tenant_id=tenant_id, activo=False, updated_at=recent_date
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        candidates = find_retention_candidates(session, retention_days=90)
        candidate_ids = {c.id for c in candidates}
        session.rollback()
    assert recent_inactive_id not in candidate_ids


def test_old_inactive_non_anonymized_contact_is_a_candidate(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    old_inactive_id = _insert_contact(
        postgres_engine, tenant_id=tenant_id, activo=False, updated_at=old_date
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        candidates = find_retention_candidates(session, retention_days=90)
        candidate_ids = {c.id for c in candidates}
        session.rollback()
    assert old_inactive_id in candidate_ids


def test_already_anonymized_contact_is_not_a_candidate_again(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    already_anonymized_id = _insert_contact(
        postgres_engine,
        tenant_id=tenant_id,
        activo=False,
        updated_at=old_date,
        anonymized_at=old_date,
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        candidates = find_retention_candidates(session, retention_days=90)
        candidate_ids = {c.id for c in candidates}
        session.rollback()
    assert already_anonymized_id not in candidate_ids


def test_session_without_tenant_fixed_finds_zero_candidates(
    app_engine, postgres_engine, two_tenants_with_data
):
    """Demuestra el defecto original (BLACK PANTHER, mismo hallazgo que
    SPEC-041): con `app_engine` (rol `omnicore_app`) y SIN
    `set_tenant_session`, la consulta ve 0 filas por RLS fail-closed, aunque
    exista un contacto vencido real en BD — esto es justamente lo que le
    pasaba a `run_retention_job` antes de la corrección, y por lo que ahora
    fija el tenant explícitamente por cada tenant activo antes de
    consultar."""
    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    _insert_contact(
        postgres_engine,
        tenant_id=tenant_id,
        activo=False,
        updated_at=old_date,
        nombre="Notenant",
    )

    with Session(app_engine) as session:
        candidates = find_retention_candidates(session, retention_days=90)
    assert candidates == []


def test_run_retention_job_dry_run_does_not_write(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    contact_id = _insert_contact(
        postgres_engine,
        tenant_id=tenant_id,
        activo=False,
        updated_at=old_date,
        nombre="No Debe Cambiar",
    )

    with Session(app_engine) as session:
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
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    contact_id = _insert_contact(
        postgres_engine,
        tenant_id=tenant_id,
        activo=False,
        updated_at=old_date,
        nombre="Debe Ser Anonimizado",
    )

    with Session(app_engine) as session:
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


def test_run_retention_job_twice_is_idempotent(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    _insert_contact(
        postgres_engine,
        tenant_id=tenant_id,
        activo=False,
        updated_at=old_date,
        nombre="Idempotencia",
    )

    with Session(app_engine) as session:
        first = run_retention_job(session, retention_days=90, enabled=True)
    assert len(first.anonymized_contact_ids) >= 1

    # Segunda corrida: no debe fallar ni volver a "anonimizar" nada (0
    # candidatos), porque `anonymized_at` ya quedó seteado en la primera.
    with Session(app_engine) as session:
        second = run_retention_job(session, retention_days=90, enabled=True)
    assert second.anonymized_contact_ids == []
    assert second.candidates_found == 0
