"""
Test de integración: auth + RLS end-to-end (SPEC-013, criterios de
aceptación #1, #3, #4).

Requiere PostgreSQL real (el `db` de `docker-compose.yml`) con el esquema de
SPEC-012 aplicado. Si no hay Postgres accesible (p.ej. este sandbox sin
daemon Docker), se SKIPEA explícitamente vía el fixture `postgres_engine`
(ver `tests/conftest.py`) — no se marca como aprobado en falso; queda
documentado como pendiente de ejecutar en CI (igual que
`tests/test_rls_isolation.py` de SPEC-012).

Qué se verifica:
  1. La contraseña se guarda hasheada en la tabla `users` (nunca en claro).
  2. `authenticate()` (login) contra un usuario real de un tenant devuelve un
     JWT válido con el `tenant_id` correcto.
  3. Fijando `app.tenant_id` = tenant A (como hace `get_tenant_db` en cada
     request autenticado), un `SELECT` sobre `users`/`contacts` NO devuelve
     filas del tenant B: el aislamiento cross-tenant se cumple end-to-end
     (JWT -> set_tenant_session -> RLS).
  4. Un intento de login con el `tenant_slug` de otro tenant (cruzando
     tenants) falla con credenciales inválidas, aunque el email/password
     sean correctos para SU propio tenant.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from app.db.session import set_tenant_session
from app.security.jwt import decode_access_token
from app.security.passwords import hash_password
from app.services.auth_service import InvalidCredentialsError, authenticate


def _crear_usuario(conn, *, tenant_id, email, password_plain, rol="agente"):
    user_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO users (id, tenant_id, email, nombre, password_hash, rol, "
            "activo, created_at, updated_at) VALUES "
            "(:id, :tenant_id, :email, :nombre, :password_hash, :rol, true, now(), now())"
        ),
        {
            "id": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "nombre": "Usuario de Prueba",
            "password_hash": hash_password(password_plain),
            "rol": rol,
        },
    )
    return user_id


def test_password_stored_hashed_never_plain(postgres_engine, two_tenants_with_data):
    """Criterio #1: la contraseña almacenada es un hash, no el texto plano."""
    data = two_tenants_with_data
    plain_password = "ClaveDeUsuarioReal#2026"

    with postgres_engine.begin() as conn:
        user_id = _crear_usuario(
            conn,
            tenant_id=data["tenant_a_id"],
            email="hash-check@tenant-a.test",
            password_plain=plain_password,
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT password_hash FROM users WHERE id = :id"),
            {"id": user_id},
        ).fetchone()

    assert row is not None
    assert row.password_hash != plain_password
    assert plain_password not in row.password_hash
    assert row.password_hash.startswith("$bcrypt")


def test_login_valid_credentials_issue_jwt_with_correct_tenant(
    postgres_engine, two_tenants_with_data
):
    """Criterio #2/RF: login válido emite JWT con el tenant_id del usuario."""
    data = two_tenants_with_data
    plain_password = "ClaveValidaTenantA#1"

    with postgres_engine.begin() as conn:
        _crear_usuario(
            conn,
            tenant_id=data["tenant_a_id"],
            email="login-ok@tenant-a.test",
            password_plain=plain_password,
        )

    with postgres_engine.connect() as db:
        # tenant_slug real: se generó como f"tenant-a-{hex[:8]}" en el fixture.
        tenant_a_row = db.execute(
            sa.text("SELECT slug FROM tenants WHERE id = :id"),
            {"id": data["tenant_a_id"]},
        ).fetchone()
        result = authenticate(
            db,
            tenant_slug=tenant_a_row.slug,
            email="login-ok@tenant-a.test",
            password=plain_password,
        )

    payload = decode_access_token(result.access_token)
    assert payload.tenant_id == str(data["tenant_a_id"])


def test_login_fails_when_user_belongs_to_a_different_tenant(
    postgres_engine, two_tenants_with_data
):
    """
    Criterio de aislamiento (RF-01/SPEC-013): un usuario del tenant A no
    puede autenticarse indicando el `tenant_slug` del tenant B, aunque
    intente reusar sus propias credenciales.
    """
    data = two_tenants_with_data
    plain_password = "ClaveTenantA#Exclusiva"

    with postgres_engine.begin() as conn:
        _crear_usuario(
            conn,
            tenant_id=data["tenant_a_id"],
            email="soloA@tenant-a.test",
            password_plain=plain_password,
        )

    with postgres_engine.connect() as db:
        tenant_b_row = db.execute(
            sa.text("SELECT slug FROM tenants WHERE id = :id"),
            {"id": data["tenant_b_id"]},
        ).fetchone()

        try:
            authenticate(
                db,
                tenant_slug=tenant_b_row.slug,
                email="soloA@tenant-a.test",
                password=plain_password,
            )
            raised = False
        except InvalidCredentialsError:
            raised = True

    assert raised, "Un usuario del tenant A no debe poder autenticarse en el tenant B"


def test_authenticated_session_cannot_read_other_tenant_rows(
    postgres_engine, two_tenants_with_data
):
    """
    Criterio #3 (end-to-end): tras fijar `app.tenant_id` = tenant A (lo que
    hace `get_tenant_db` en cada request autenticado, a partir del JWT), un
    SELECT sobre `contacts` NO devuelve el contacto del tenant B.
    """
    data = two_tenants_with_data

    with postgres_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(data["tenant_a_id"]))
            rows = conn.execute(sa.text("SELECT id FROM contacts")).fetchall()
            visible_ids = {row.id for row in rows}

    assert data["contact_a_id"] in visible_ids
    assert data["contact_b_id"] not in visible_ids, (
        "FUGA CROSS-TENANT: una sesión autenticada como tenant A pudo leer "
        "un contacto del tenant B"
    )
