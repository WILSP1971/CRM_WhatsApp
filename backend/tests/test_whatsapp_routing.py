"""
Tests de SPEC-025 — Datos del canal WhatsApp (ADR-007):

  1. `whatsapp_accounts` resuelve `phone_number_id -> tenant_id` y el índice
     único evita duplicados (RF-01).
  2. `messages.wamid` tiene restricción de unicidad — base de idempotencia a
     nivel de esquema (RF-02, ADR-007).
  3. `whatsapp_accounts` es tenant-scoped (lleva `tenant_id` propio) y por
     tanto está bajo RLS ENABLE+FORCE: un tenant no ve el routing de otro
     (RNF-04, R-34). Se prueba con el mismo patrón que
     `tests/test_rls_isolation.py` (SPEC-012).
  4. No hay regresión del contrato existente de `messages`
     (`remitente`/`sentimiento`/`estado_entrega` siguen presentes, RNF-07).

Requiere PostgreSQL real (fixture `postgres_engine` de `tests/conftest.py`).
Si no hay Postgres accesible, se SKIPEAN explícitamente (no se marcan como
aprobados en falso) — correrán en CI contra el `db` del docker-compose.yml.
"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.db.rls import TENANT_SCOPED_TABLES
from app.db.session import set_tenant_session


# ---------------------------------------------------------------------------
# RF-01: routing phone_number_id -> tenant_id + unicidad
# ---------------------------------------------------------------------------


def test_whatsapp_accounts_resolves_phone_number_id_to_tenant(
    postgres_engine, two_tenants_with_data
):
    """Una fila de `whatsapp_accounts` mapea un `phone_number_id` a un único
    `tenant_id`; el webhook (SPEC-026/027) resuelve el tenant con este SELECT
    antes de fijar RLS de sesión."""
    data = two_tenants_with_data
    phone_number_id = f"pni-{uuid.uuid4().hex[:12]}"

    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO whatsapp_accounts (id, tenant_id, phone_number_id) "
                "VALUES (:id, :tenant_id, :phone_number_id)"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": data["tenant_a_id"],
                "phone_number_id": phone_number_id,
            },
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT tenant_id FROM whatsapp_accounts WHERE phone_number_id = :pni"
            ),
            {"pni": phone_number_id},
        ).fetchone()

    assert row is not None
    assert row.tenant_id == data["tenant_a_id"]


def test_whatsapp_accounts_phone_number_id_unique_constraint(
    postgres_engine, two_tenants_with_data
):
    """Criterio de aceptación: `phone_number_id` tiene restricción de
    unicidad — un mismo número no puede enrutar a dos tenants distintos."""
    data = two_tenants_with_data
    phone_number_id = f"pni-dup-{uuid.uuid4().hex[:12]}"

    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO whatsapp_accounts (id, tenant_id, phone_number_id) "
                "VALUES (:id, :tenant_id, :phone_number_id)"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": data["tenant_a_id"],
                "phone_number_id": phone_number_id,
            },
        )

    with pytest.raises(IntegrityError):
        with postgres_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO whatsapp_accounts (id, tenant_id, phone_number_id) "
                    "VALUES (:id, :tenant_id, :phone_number_id)"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": data["tenant_b_id"],
                    "phone_number_id": phone_number_id,
                },
            )


# ---------------------------------------------------------------------------
# RF-02: unicidad de messages.wamid (idempotencia, ADR-007)
# ---------------------------------------------------------------------------


def test_messages_wamid_unique_constraint(postgres_engine, two_tenants_with_data):
    """Criterio de aceptación: `messages.wamid` tiene restricción de
    unicidad — un webhook reentregado con el mismo `wamid` no puede insertar
    un segundo mensaje (idempotencia a nivel de esquema, ADR-007)."""
    data = two_tenants_with_data
    wamid = f"wamid.{uuid.uuid4().hex}"

    conversation_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conversations (id, tenant_id, contact_id, canal) "
                "VALUES (:id, :tenant_id, :contact_id, 'whatsapp')"
            ),
            {
                "id": conversation_id,
                "tenant_id": data["tenant_a_id"],
                "contact_id": data["contact_a_id"],
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO messages "
                "(id, tenant_id, conversation_id, remitente, contenido, wamid) "
                "VALUES (:id, :tenant_id, :conversation_id, 'contacto', "
                "'hola', :wamid)"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": data["tenant_a_id"],
                "conversation_id": conversation_id,
                "wamid": wamid,
            },
        )

    with pytest.raises(IntegrityError):
        with postgres_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO messages "
                    "(id, tenant_id, conversation_id, remitente, contenido, wamid) "
                    "VALUES (:id, :tenant_id, :conversation_id, 'contacto', "
                    "'hola de nuevo', :wamid)"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": data["tenant_a_id"],
                    "conversation_id": conversation_id,
                    "wamid": wamid,
                },
            )


def test_messages_wamid_nullable_no_regression_other_channels(
    postgres_engine, two_tenants_with_data
):
    """Sin regresión (RNF-07): mensajes de otros canales (p.ej. webchat) no
    llevan `wamid` (`NULL`) y varios `NULL` no colisionan entre sí bajo la
    restricción UNIQUE estándar de PostgreSQL."""
    data = two_tenants_with_data
    conversation_id = uuid.uuid4()

    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conversations (id, tenant_id, contact_id, canal) "
                "VALUES (:id, :tenant_id, :contact_id, 'webchat')"
            ),
            {
                "id": conversation_id,
                "tenant_id": data["tenant_a_id"],
                "contact_id": data["contact_a_id"],
            },
        )
        for _ in range(2):
            conn.execute(
                sa.text(
                    "INSERT INTO messages "
                    "(id, tenant_id, conversation_id, remitente, contenido) "
                    "VALUES (:id, :tenant_id, :conversation_id, 'contacto', 'hola')"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": data["tenant_a_id"],
                    "conversation_id": conversation_id,
                },
            )

    with postgres_engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT remitente, sentimiento, estado_entrega, wamid FROM messages "
                "WHERE conversation_id = :cid"
            ),
            {"cid": conversation_id},
        ).fetchall()

    assert len(rows) == 2
    for row in rows:
        assert row.remitente == "contacto"
        assert row.estado_entrega == "enviado"  # default existente, sin regresión
        assert row.wamid is None


# ---------------------------------------------------------------------------
# RNF-04 / R-34: whatsapp_accounts es tenant-scoped y está bajo RLS
# ---------------------------------------------------------------------------


def test_whatsapp_accounts_is_tenant_scoped_table():
    """`whatsapp_accounts` está registrada como tabla tenant-scoped (misma
    fuente de verdad que usa la migración de RLS y los tests de aislamiento,
    evitando que la lista se desincronice)."""
    assert "whatsapp_accounts" in TENANT_SCOPED_TABLES


def test_whatsapp_accounts_rls_enabled_and_forced(postgres_engine):
    """Criterio de aceptación: RLS ENABLE + FORCE en `whatsapp_accounts`
    (igual que el resto de `TENANT_SCOPED_TABLES`, SPEC-012/ADR-004)."""
    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE relname = 'whatsapp_accounts'"
            )
        ).fetchone()
    assert row is not None, "whatsapp_accounts no existe"
    row_security_enabled, row_security_forced = row
    assert row_security_enabled is True, "whatsapp_accounts: RLS no está ENABLE"
    assert row_security_forced is True, "whatsapp_accounts: RLS no está FORCE"


def test_whatsapp_accounts_cross_tenant_isolation(
    postgres_engine, app_engine, two_tenants_with_data
):
    """Criterio de aceptación (R-34): una sesión de tenant A no lee el
    routing (`phone_number_id`) de otro tenant, aunque el SELECT no filtre
    por `tenant_id`. Ejerce RLS con `app_engine` (rol `omnicore_app`,
    ADR-008): con el owner/superuser de `postgres_engine` este test pasaría
    por accidente sin probar el aislamiento real (hallazgo BLACK PANTHER)."""
    data = two_tenants_with_data
    pni_a = f"pni-a-{uuid.uuid4().hex[:10]}"
    pni_b = f"pni-b-{uuid.uuid4().hex[:10]}"

    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO whatsapp_accounts (id, tenant_id, phone_number_id) "
                "VALUES (:id, :tenant_id, :pni)"
            ),
            [
                {
                    "id": uuid.uuid4(),
                    "tenant_id": data["tenant_a_id"],
                    "pni": pni_a,
                },
                {
                    "id": uuid.uuid4(),
                    "tenant_id": data["tenant_b_id"],
                    "pni": pni_b,
                },
            ],
        )

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(data["tenant_a_id"]))
            rows = conn.execute(
                sa.text("SELECT phone_number_id FROM whatsapp_accounts")
            ).fetchall()
            visible = {r.phone_number_id for r in rows}

    assert pni_a in visible, "El tenant A debe ver su propio routing"
    assert (
        pni_b not in visible
    ), "FUGA CROSS-TENANT: el tenant A puede ver el routing del tenant B"


def test_whatsapp_accounts_session_without_tenant_sees_zero_rows(
    postgres_engine, app_engine, two_tenants_with_data
):
    """Fail-closed (ADR-004): sin `app.tenant_id` fijado, una sesión con el
    rol de aplicación (`app_engine`, ADR-008) no ve ningún routing, ni
    siquiera con SELECT sin WHERE."""
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO whatsapp_accounts (id, tenant_id, phone_number_id) "
                "VALUES (:id, :tenant_id, :pni)"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": data["tenant_a_id"],
                "pni": f"pni-noauth-{uuid.uuid4().hex[:10]}",
            },
        )

    with app_engine.connect() as conn:
        with conn.begin():
            conn.execute(sa.text("RESET app.tenant_id"))
            rows = conn.execute(sa.text("SELECT id FROM whatsapp_accounts")).fetchall()
            assert rows == [], "Sesión sin tenant fijado no debe ver ningún routing"


# ---------------------------------------------------------------------------
# C2: borrado lógico de whatsapp_accounts
# ---------------------------------------------------------------------------


def test_whatsapp_accounts_soft_delete_no_physical_delete(
    postgres_engine, two_tenants_with_data
):
    """C2: dar de baja un número es `activo=False`, la fila permanece (nunca
    DELETE físico); las consultas de "vigentes" excluyen inactivos."""
    data = two_tenants_with_data
    account_id = uuid.uuid4()
    pni = f"pni-baja-{uuid.uuid4().hex[:10]}"

    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO whatsapp_accounts (id, tenant_id, phone_number_id) "
                "VALUES (:id, :tenant_id, :pni)"
            ),
            {"id": account_id, "tenant_id": data["tenant_a_id"], "pni": pni},
        )
        conn.execute(
            sa.text("UPDATE whatsapp_accounts SET activo = false WHERE id = :id"),
            {"id": account_id},
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT activo FROM whatsapp_accounts WHERE id = :id"),
            {"id": account_id},
        ).fetchone()
        vigentes = conn.execute(
            sa.text(
                "SELECT id FROM whatsapp_accounts WHERE id = :id AND activo = true"
            ),
            {"id": account_id},
        ).fetchall()

    assert row is not None, "El borrado lógico no debe eliminar la fila (C2)"
    assert row.activo is False
    assert vigentes == [], "Las consultas de vigentes deben excluir inactivos"


# ---------------------------------------------------------------------------
# ADR-008 — resolve_tenant_by_phone_number_id (SECURITY DEFINER) + roles de BD
#
# MARCADOS PARA CI: requieren Postgres real con `init-sql/01-roles-app.sh`
# (rol `omnicore_app`) y la migración `54c75efefe3c` (función
# `resolve_tenant_by_phone_number_id`) ya aplicados. Corrige el BLOQUEANTE #2
# de SPEC-025 (hallazgo BLACK PANTHER): antes, la resolución pre-tenant
# "funcionaba por accidente" porque el backend se conectaba como superusuario
# `postgres` (ve todo, sin RLS). Estos tests ejecutan la función con el rol
# de aplicación real (`omnicore_app`) para probar el mecanismo explícito.
# ---------------------------------------------------------------------------


def test_resolve_tenant_by_phone_number_id_security_definer_without_tenant_set(
    postgres_engine, app_engine, two_tenants_with_data
):
    """Criterio de verificación #2 de ADR-008: la función
    `resolve_tenant_by_phone_number_id` ejecutada por el rol de aplicación
    (`omnicore_app`), SIN fijar `app.tenant_id` de sesión, devuelve el
    `tenant_id` correcto (gracias a `SECURITY DEFINER`: corre con los
    privilegios del owner, no del invocador)."""
    data = two_tenants_with_data
    pni = f"pni-resolve-{uuid.uuid4().hex[:10]}"

    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO whatsapp_accounts (id, tenant_id, phone_number_id, activo) "
                "VALUES (:id, :tenant_id, :pni, true)"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": data["tenant_a_id"],
                "pni": pni,
            },
        )

    with app_engine.connect() as conn:
        # Deliberadamente SIN set_tenant_session(): la función SECURITY
        # DEFINER debe resolver el tenant sin necesitar app.tenant_id fijado.
        row = conn.execute(
            sa.text("SELECT resolve_tenant_by_phone_number_id(:pni) AS tenant_id"),
            {"pni": pni},
        ).fetchone()

    assert row is not None
    assert row.tenant_id == data["tenant_a_id"], (
        "resolve_tenant_by_phone_number_id debe devolver el tenant correcto "
        "aunque la sesión (rol omnicore_app) no tenga app.tenant_id fijado"
    )


def test_resolve_tenant_by_phone_number_id_ignores_inactive_accounts(
    postgres_engine, app_engine, two_tenants_with_data
):
    """La función solo resuelve cuentas `activo = true` (ADR-008): un
    `phone_number_id` dado de baja no debe resolver a ningún tenant."""
    data = two_tenants_with_data
    pni = f"pni-inactivo-{uuid.uuid4().hex[:10]}"

    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO whatsapp_accounts (id, tenant_id, phone_number_id, activo) "
                "VALUES (:id, :tenant_id, :pni, false)"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": data["tenant_a_id"],
                "pni": pni,
            },
        )

    with app_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT resolve_tenant_by_phone_number_id(:pni) AS tenant_id"),
            {"pni": pni},
        ).fetchone()

    assert row is not None
    assert row.tenant_id is None, (
        "Un phone_number_id inactivo (activo=false) no debe resolver a " "ningún tenant"
    )


def test_omnicore_app_cannot_read_whatsapp_accounts_of_other_tenant_directly(
    postgres_engine, app_engine, two_tenants_with_data
):
    """Criterio de verificación #1/#3 de ADR-008: `omnicore_app` NO puede leer
    filas de otro tenant vía SELECT directo (solo la función SECURITY
    DEFINER, acotada, resuelve pre-tenant); RLS sigue aplicándose siempre a
    las consultas directas del rol de aplicación."""
    data = two_tenants_with_data
    pni_a = f"pni-direct-a-{uuid.uuid4().hex[:8]}"
    pni_b = f"pni-direct-b-{uuid.uuid4().hex[:8]}"

    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO whatsapp_accounts (id, tenant_id, phone_number_id) "
                "VALUES (:id, :tenant_id, :pni)"
            ),
            [
                {"id": uuid.uuid4(), "tenant_id": data["tenant_a_id"], "pni": pni_a},
                {"id": uuid.uuid4(), "tenant_id": data["tenant_b_id"], "pni": pni_b},
            ],
        )

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(data["tenant_a_id"]))
            rows = conn.execute(
                sa.text(
                    "SELECT phone_number_id FROM whatsapp_accounts "
                    "WHERE phone_number_id = :pni"
                ),
                {"pni": pni_b},
            ).fetchall()

    assert rows == [], (
        "FUGA CROSS-TENANT: omnicore_app pudo leer directamente el routing "
        "de otro tenant sin pasar por la función SECURITY DEFINER"
    )


def test_omnicore_app_cannot_execute_ddl(app_engine):
    """Criterio de verificación #3 de ADR-008: el rol de aplicación
    `omnicore_app` NO puede ejecutar DDL (CREATE/ALTER/DROP fallan por
    permisos) — separación de deberes: Alembic/DDL usa el rol privilegiado,
    nunca el runtime de la app."""
    from sqlalchemy.exc import DBAPIError

    with app_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            with conn.begin():
                conn.execute(
                    sa.text("CREATE TABLE adr008_ddl_probe (id serial PRIMARY KEY)")
                )
        assert "permission denied" in str(exc_info.value).lower()
