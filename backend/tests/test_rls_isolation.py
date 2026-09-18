"""
Test de aislamiento multi-tenant por Row Level Security (SPEC-012, ADR-004,
riesgo R-23, criterio CE-22).

Requiere PostgreSQL real (el `db` de `docker-compose.yml`, pgvector/pg16) con
el esquema de SPEC-012 aplicado vía Alembic. Si no hay Postgres accesible
(p.ej. este sandbox sin daemon Docker), estos tests se SKIPEAN explícitamente
(ver `tests/conftest.py::postgres_engine`) — NO se marcan como aprobados en
falso; quedan documentados como pendientes de ejecutar en CI.

Qué se verifica (criterios de aceptación de SPEC-012):
  1. Con `app.tenant_id = A`, un SELECT sin WHERE sobre `contacts` devuelve
     SOLO filas del tenant A (0 filas del tenant B) — aislamiento de lectura.
  2. Un intento de UPDATE de una fila del tenant B, estando fijado el tenant A,
     afecta 0 filas (RLS bloquea la escritura cross-tenant vía WITH CHECK/USING).
  3. Un intento de DELETE de una fila del tenant B, estando fijado el tenant A,
     afecta 0 filas.
  4. Una sesión SIN `app.tenant_id` fijado no ve ninguna fila (fail-closed):
     `current_setting('app.tenant_id', true)` es NULL y `tenant_id = NULL` es
     siempre falso.
  5. RLS está ENABLE + FORCE en todas las tablas de `TENANT_SCOPED_TABLES`.
"""

import sys
import os

import sqlalchemy as sa

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db.rls import TENANT_SCOPED_TABLES  # noqa: E402
from app.db.session import set_tenant_session  # noqa: E402


def test_rls_enabled_and_forced_on_all_tenant_tables(postgres_engine):
    """Criterio: RLS ENABLE + FORCE en todas las tablas con tenant_id."""
    with postgres_engine.connect() as conn:
        for table in TENANT_SCOPED_TABLES:
            row = conn.execute(
                sa.text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = :table"
                ),
                {"table": table},
            ).fetchone()
            assert row is not None, f"Tabla {table} no existe"
            row_security_enabled, row_security_forced = row
            assert row_security_enabled is True, f"{table}: RLS no está ENABLE"
            assert row_security_forced is True, f"{table}: RLS no está FORCE"


def test_select_without_where_returns_only_own_tenant_rows(
    postgres_engine, two_tenants_with_data
):
    """
    Criterio: con app.tenant_id = A, un SELECT sin WHERE devuelve SOLO filas
    del tenant A (0 filas de B), aunque el query no filtre por tenant_id.
    """
    data = two_tenants_with_data
    with Session_with_tenant(postgres_engine, data["tenant_a_id"]) as conn:
        rows = conn.execute(sa.text("SELECT id, tenant_id FROM contacts")).fetchall()
        visible_ids = {row.id for row in rows}

        assert (
            data["contact_a_id"] in visible_ids
        ), "El tenant A debe ver su propio contacto"
        assert (
            data["contact_b_id"] not in visible_ids
        ), "FUGA CROSS-TENANT: el tenant A puede ver un contacto del tenant B"
        assert all(row.tenant_id == data["tenant_a_id"] for row in rows)


def test_cross_tenant_update_affects_zero_rows(postgres_engine, two_tenants_with_data):
    """
    Criterio: un intento de UPDATE de fila de otro tenant afecta 0 filas.
    Simula: agente del tenant A intenta modificar el contacto del tenant B.
    """
    data = two_tenants_with_data
    with Session_with_tenant(postgres_engine, data["tenant_a_id"]) as conn:
        result = conn.execute(
            sa.text("UPDATE contacts SET nombre = 'HACKEADO' WHERE id = :id"),
            {"id": data["contact_b_id"]},
        )
        assert (
            result.rowcount == 0
        ), "FUGA CROSS-TENANT: el tenant A pudo actualizar un contacto del tenant B"

    # Verifica, ya sin restricción de tenant (rol admin de test), que el dato
    # del tenant B permanece intacto.
    with postgres_engine.connect() as verify_conn:
        row = verify_conn.execute(
            sa.text("SELECT nombre FROM contacts WHERE id = :id"),
            {"id": data["contact_b_id"]},
        ).fetchone()
        assert (
            row.nombre == "Contacto Confidencial B"
        ), "El dato del tenant B fue alterado"


def test_cross_tenant_delete_affects_zero_rows(postgres_engine, two_tenants_with_data):
    """Criterio: un intento de DELETE de fila de otro tenant afecta 0 filas."""
    data = two_tenants_with_data
    with Session_with_tenant(postgres_engine, data["tenant_a_id"]) as conn:
        result = conn.execute(
            sa.text("DELETE FROM contacts WHERE id = :id"),
            {"id": data["contact_b_id"]},
        )
        assert (
            result.rowcount == 0
        ), "FUGA CROSS-TENANT: el tenant A pudo borrar un contacto del tenant B"

    with postgres_engine.connect() as verify_conn:
        row = verify_conn.execute(
            sa.text("SELECT 1 FROM contacts WHERE id = :id"),
            {"id": data["contact_b_id"]},
        ).fetchone()
        assert row is not None, "El contacto del tenant B fue eliminado indebidamente"


def test_session_without_tenant_sees_zero_rows(postgres_engine, two_tenants_with_data):
    """
    Criterio (fail-closed, ADR-004): una sesión sin app.tenant_id fijado no ve
    ninguna fila, ni siquiera con SELECT sin WHERE.
    """
    data = two_tenants_with_data  # noqa: F841 (asegura que existan filas)
    with postgres_engine.connect() as conn:
        with conn.begin():
            conn.execute(sa.text("RESET app.tenant_id"))
            rows = conn.execute(sa.text("SELECT id FROM contacts")).fetchall()
            assert (
                rows == []
            ), "Una sesión sin tenant_id fijado NO debe ver ninguna fila"


class Session_with_tenant:
    """Context manager: abre una transacción con `app.tenant_id` fijado (SET LOCAL)."""

    def __init__(self, engine, tenant_id):
        self._engine = engine
        self._tenant_id = tenant_id
        self._conn = None
        self._trans = None

    def __enter__(self):
        self._conn = self._engine.connect()
        self._trans = self._conn.begin()
        set_tenant_session(self._conn, str(self._tenant_id))
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._trans.commit()
        else:
            self._trans.rollback()
        self._conn.close()
