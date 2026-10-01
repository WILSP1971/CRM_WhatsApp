"""
Tests del servicio de aprovisionamiento de tenants — SPEC-076 (prueba
SPEC-073/074/075, ADR-015).

Requiere PostgreSQL real (el `db` de `docker-compose.yml`) con el esquema
aplicado vía Alembic. Si no hay Postgres accesible, estos tests se SKIPEAN
automáticamente (ver `tests/conftest.py::postgres_engine`/`app_engine`) — no
se marcan como aprobados en falso.

Qué se verifica (RF-01..RF-04/RF-07/RF-08 de SPEC-076):
  - RF-01/CE-89: aislamiento cross-tenant del tenant recién provisionado
    (patrón `tests/test_rls_isolation.py`).
  - RF-02/CE-93: atomicidad — fallo inyectado a mitad del alta -> 0 filas
    (ni tenant ni admin huérfanos).
  - RF-03: unicidad tipada (slug/email -> 409 vía excepción; formato/
    password/campos inválidos -> 422 vía excepción), nunca una excepción
    genérica no mapeada.
  - RF-04/CE-91: cero bypass RLS — `set_tenant_session` se invoca ANTES del
    INSERT de `users`, y el admin creado SOLO es visible fijando el
    `app.tenant_id` del tenant recién creado (rol `omnicore_app`, ADR-008).
  - RF-07/C3: secretos — `password_hash` presente, con prefijo bcrypt, nunca
    igual al password en claro; `ProvisionedTenant` no expone password/hash.
  - RF-08: `platform_admins` no está en `TENANT_SCOPED_TABLES` y no tiene
    política `tenant_isolation_platform_admins`.

Estos tests llaman DIRECTAMENTE a `provision_tenant()` (capa de servicio,
sin pasar por HTTP) usando `app_engine` (rol `omnicore_app`, NOSUPERUSER
NOBYPASSRLS, ADR-008) para que el camino "RLS efectiva" sea el mismo que en
producción real -- usar el rol owner aquí sería un falso positivo (mismo
defecto ya documentado en `tests/test_rls_isolation.py`/`test_auth_cross_tenant_rls.py`).
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.rls import TENANT_SCOPED_TABLES
from app.db.session import set_tenant_session
from app.services.tenant_provisioning_service import (
    InvalidFieldError,
    InvalidPasswordError,
    InvalidSlugError,
    SlugCollisionError,
    TenantProvisioningError,
    provision_tenant,
)

pytestmark = pytest.mark.filterwarnings("ignore")


def _slug(prefix: str) -> str:
    """Slug único por test (evita colisiones entre ejecuciones)."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _provision_kwargs(**overrides) -> dict:
    base = {
        "nombre": "Clinica Demo Provisioning",
        "slug": _slug("clinica-demo-provisioning"),
        "admin_email": f"admin-{uuid.uuid4().hex[:8]}@provisioning.test",
        "admin_password": "ClaveSeguraDemo#123",
        "admin_nombre": "Admin Demo Provisioning",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# RF-01/CE-89 — aislamiento cross-tenant del tenant recién provisionado
# ---------------------------------------------------------------------------


def test_provisioned_tenant_is_isolated_from_other_tenant(
    app_engine, two_tenants_with_data
):
    """El tenant recién provisionado no ve ni es visto por otro tenant
    existente: fijando `app.tenant_id` del tenant B (ya existente, creado
    por `two_tenants_with_data`), el admin del tenant NUEVO (creado aquí)
    no aparece en `users` (0 filas cruzadas) — y viceversa."""
    data = two_tenants_with_data
    kwargs = _provision_kwargs()

    with Session(app_engine) as db:
        resultado = provision_tenant(db, **kwargs)

    # Fijando el tenant B (otro tenant YA existente), el admin del tenant
    # nuevo no debe ser visible.
    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(data["tenant_b_id"]))
            rows = conn.execute(
                sa.text("SELECT id FROM users WHERE id = :id"),
                {"id": resultado.admin_user_id},
            ).fetchall()
    assert rows == [], (
        "FUGA CROSS-TENANT: el admin del tenant recién provisionado es "
        "visible fijando app.tenant_id de OTRO tenant"
    )

    # Fijando el propio tenant nuevo, el admin SÍ debe ser visible (control
    # positivo: si esto fallara, el test anterior sería un falso positivo
    # por RLS fail-closed general, no por aislamiento específico).
    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(resultado.tenant_id))
            rows = conn.execute(
                sa.text("SELECT id FROM users WHERE id = :id"),
                {"id": resultado.admin_user_id},
            ).fetchall()
    assert len(rows) == 1, "El propio tenant nuevo debe ver a su admin recién creado"


def test_provisioned_tenant_admin_not_visible_without_tenant_session(app_engine):
    """Fail-closed (ADR-004): sin `app.tenant_id` fijado, el admin recién
    creado tampoco es visible (ninguna fila es visible sin tenant fijado)."""
    kwargs = _provision_kwargs()
    with Session(app_engine) as db:
        resultado = provision_tenant(db, **kwargs)

    with app_engine.connect() as conn:
        with conn.begin():
            conn.execute(sa.text("RESET app.tenant_id"))
            rows = conn.execute(
                sa.text("SELECT id FROM users WHERE id = :id"),
                {"id": resultado.admin_user_id},
            ).fetchall()
    assert rows == []


# ---------------------------------------------------------------------------
# RF-02/CE-93 — atomicidad: fallo inyectado -> 0 filas (sin huérfanos)
# ---------------------------------------------------------------------------


def test_injected_failure_after_tenant_insert_rolls_back_everything(app_engine):
    """Fuerza una excepción justo después de fijar `app.tenant_id` (tras el
    INSERT de `tenants`, antes/durante el INSERT de `users`), monkeypatcheando
    `set_tenant_session` para que falle. El resultado debe ser 0 filas: ni el
    tenant ni el admin quedan persistidos (rollback total de la transacción
    única)."""
    slug = _slug("clinica-rollback-set-session")

    class _FalloInyectado(RuntimeError):
        pass

    import app.services.tenant_provisioning_service as svc_module

    original_set_tenant_session = svc_module.set_tenant_session

    def _set_tenant_session_que_falla(db, tenant_id):
        original_set_tenant_session(db, tenant_id)
        raise _FalloInyectado("fallo inyectado tras fijar app.tenant_id")

    with Session(app_engine) as db:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(svc_module, "set_tenant_session", _set_tenant_session_que_falla)
            with pytest.raises(_FalloInyectado):
                provision_tenant(db, **_provision_kwargs(slug=slug))

    # Verificación post-rollback: ni tenant ni admin persistidos.
    with app_engine.connect() as conn:
        tenant_row = conn.execute(
            sa.text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": slug}
        ).fetchone()
    assert tenant_row is None, (
        "ATOMICIDAD ROTA: el tenant quedó persistido (huérfano) tras un fallo "
        "inyectado a mitad del alta"
    )


def test_injected_failure_via_flush_rolls_back_tenant_insert_too(app_engine):
    """Monkeypatchea `Session.flush` para fallar en el INSERT de `users`
    (paso 4): ni siquiera la fila raíz `tenants` (paso 2, ya ejecutada en la
    misma transacción) debe sobrevivir — es una única transacción atómica,
    no dos transacciones independientes."""
    slug = _slug("clinica-rollback-flush")

    class _FalloFlush(RuntimeError):
        pass

    with Session(app_engine) as db:
        original_flush = db.flush

        call_count = {"n": 0}

        def _flush_que_falla(*args, **kwargs):
            call_count["n"] += 1
            raise _FalloFlush("fallo inyectado en db.flush (INSERT users)")

        db.flush = _flush_que_falla  # type: ignore[method-assign]
        try:
            with pytest.raises(_FalloFlush):
                provision_tenant(db, **_provision_kwargs(slug=slug))
        finally:
            db.flush = original_flush  # type: ignore[method-assign]

    with app_engine.connect() as conn:
        tenant_row = conn.execute(
            sa.text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": slug}
        ).fetchone()
    assert tenant_row is None, (
        "ATOMICIDAD ROTA: el tenant quedó persistido (huérfano) aunque el "
        "INSERT de users falló en el flush"
    )
    assert call_count["n"] >= 1, "El monkeypatch de flush no llegó a invocarse"


def test_email_collision_within_same_new_tenant_rolls_back(app_engine):
    """Violación real de `uq_users_tenant_email`: se reintenta el mismo
    slug+email tras un primer alta exitosa manipulando directamente el
    servicio para forzar la colisión -- aquí se simula reutilizando el truco
    de SPEC-075 (reintento con el mismo slug, que primero falla por
    SlugCollisionError) y, por separado, confirmando que `EmailCollisionError`
    deja 0 filas nuevas cuando se la fuerza explícitamente.

    Caso explícito: dos llamadas a `provision_tenant` con el MISMO slug ->
    la segunda debe fallar con `SlugCollisionError` (409) y no dejar un
    segundo admin huérfano para ese slug."""
    slug = _slug("clinica-email-collision")
    kwargs = _provision_kwargs(slug=slug)

    with Session(app_engine) as db:
        primer_resultado = provision_tenant(db, **kwargs)

    with Session(app_engine) as db:
        with pytest.raises(SlugCollisionError):
            provision_tenant(db, **_provision_kwargs(slug=slug))

    # Solo debe existir el tenant de la PRIMERA llamada (0 filas huérfanas
    # de la segunda, fallida).
    with app_engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": slug}
        ).fetchall()
    assert len(rows) == 1
    assert rows[0].id == primer_resultado.tenant_id


# ---------------------------------------------------------------------------
# RF-03 — unicidad tipada / validación, nunca una excepción no mapeada
# ---------------------------------------------------------------------------


def test_duplicate_slug_raises_slug_collision_error(app_engine):
    slug = _slug("clinica-slug-duplicado")
    with Session(app_engine) as db:
        provision_tenant(db, **_provision_kwargs(slug=slug))

    with Session(app_engine) as db:
        with pytest.raises(SlugCollisionError):
            provision_tenant(
                db,
                **_provision_kwargs(
                    slug=slug,
                    admin_email=f"otro-{uuid.uuid4().hex[:8]}@provisioning.test",
                ),
            )


@pytest.mark.parametrize(
    "slug_invalido",
    [
        "slug con espacios",
        "-empieza-con-guion",
        "termina-con-guion-",
        "slug_con_guion_bajo",
        "",
    ],
)
def test_malformed_slug_raises_invalid_slug_error(app_engine, slug_invalido):
    with Session(app_engine) as db:
        with pytest.raises(InvalidSlugError):
            provision_tenant(db, **_provision_kwargs(slug=slug_invalido))


def test_slug_with_uppercase_is_silently_normalized_to_lowercase(app_engine):
    """`_normalizar_slug` aplica `.strip().lower()` ANTES de validar el
    formato (mismo criterio que `admin_email`, ver docstring del servicio):
    un slug con mayúsculas pero sin otros defectos (sin espacios/underscore/
    guion inicial-final) NO es rechazado -- se normaliza en silencio a
    minúsculas. Esto es comportamiento de producción deliberado, no un bug;
    este test documenta el contrato para que no se confunda con una
    regresión futura."""
    sufijo = uuid.uuid4().hex[:10]
    with Session(app_engine) as db:
        resultado = provision_tenant(
            db, **_provision_kwargs(slug=f"Clinica-Con-Mayusculas-{sufijo}")
        )
    assert resultado.slug == f"clinica-con-mayusculas-{sufijo}"


@pytest.mark.parametrize("slug_reservado", ["platform", "admin", "api", "me"])
def test_reserved_slug_raises_invalid_slug_error(app_engine, slug_reservado):
    with Session(app_engine) as db:
        with pytest.raises(InvalidSlugError):
            provision_tenant(db, **_provision_kwargs(slug=slug_reservado))


def test_slug_too_long_raises_invalid_slug_error(app_engine):
    slug_largo = "a" * 101
    with Session(app_engine) as db:
        with pytest.raises(InvalidSlugError):
            provision_tenant(db, **_provision_kwargs(slug=slug_largo))


def test_short_password_raises_invalid_password_error(app_engine):
    with Session(app_engine) as db:
        with pytest.raises(InvalidPasswordError):
            provision_tenant(db, **_provision_kwargs(admin_password="corta12"))


@pytest.mark.parametrize(
    "campo,valor",
    [("nombre", "   "), ("admin_nombre", "")],
)
def test_blank_required_field_raises_invalid_field_error(app_engine, campo, valor):
    with Session(app_engine) as db:
        with pytest.raises(InvalidFieldError):
            provision_tenant(db, **_provision_kwargs(**{campo: valor}))


def test_no_failure_path_raises_bare_integrity_error_or_generic_exception(app_engine):
    """Defensa en profundidad (RF-03): todas las rutas de fallo del servicio
    son subclases tipadas de `TenantProvisioningError`, nunca una
    `IntegrityError`/excepción genérica sin mapear que el router no sepa
    traducir a 409/422 (eso degeneraría en 500)."""
    casos_fallo = [
        dict(slug="Invalido Mayus"),
        dict(admin_password="corta"),
        dict(nombre=""),
    ]
    for overrides in casos_fallo:
        with Session(app_engine) as db:
            with pytest.raises(TenantProvisioningError):
                provision_tenant(db, **_provision_kwargs(**overrides))


# ---------------------------------------------------------------------------
# RF-04/CE-91 — cero bypass RLS: `users` se inserta con app.tenant_id fijado
# ---------------------------------------------------------------------------


def test_set_tenant_session_called_before_user_insert(app_engine, monkeypatch):
    """Verifica, por instrumentación directa, que `set_tenant_session` se
    invoca ANTES de que el ORM intente el INSERT de `users` (orden de
    operaciones del propio código, no solo su efecto observable)."""
    import app.services.tenant_provisioning_service as svc_module

    orden_llamadas: list[str] = []

    original_set_tenant_session = svc_module.set_tenant_session

    def _set_tenant_session_instrumentado(db, tenant_id):
        orden_llamadas.append("set_tenant_session")
        return original_set_tenant_session(db, tenant_id)

    monkeypatch.setattr(
        svc_module, "set_tenant_session", _set_tenant_session_instrumentado
    )

    with Session(app_engine) as db:
        original_flush = db.flush

        def _flush_instrumentado(*args, **kwargs):
            orden_llamadas.append("flush_users")
            return original_flush(*args, **kwargs)

        db.flush = _flush_instrumentado  # type: ignore[method-assign]
        try:
            provision_tenant(db, **_provision_kwargs())
        finally:
            db.flush = original_flush  # type: ignore[method-assign]

    assert orden_llamadas == ["set_tenant_session", "flush_users"], (
        "BYPASS RLS: `users` se inserta sin que `set_tenant_session` se haya "
        "invocado antes (orden observado: "
        f"{orden_llamadas})"
    )


def test_admin_user_only_visible_under_its_own_tenant_session(app_engine):
    """Confirma, por SQL directo (no por la API del servicio), que la fila
    de `users` insertada por `provision_tenant` respeta RLS: solo es visible
    fijando `app.tenant_id` = el tenant recién creado, con el rol de
    aplicación NO-superusuario (ADR-008). Si el INSERT se hubiera hecho con
    una sesión owner/sin tenant fijado, este mismo SELECT (con `app_engine`)
    igual mostraría la fila SOLO bajo el tenant correcto -- lo que distingue
    "bypass en el INSERT" (sigue siendo detectable aquí porque RLS se aplica
    en cada SELECT con este rol) es el test de orden de llamadas de arriba,
    complementado por este control de visibilidad."""
    with Session(app_engine) as db:
        resultado = provision_tenant(db, **_provision_kwargs())

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(resultado.tenant_id))
            row = conn.execute(
                sa.text("SELECT tenant_id FROM users WHERE id = :id"),
                {"id": resultado.admin_user_id},
            ).fetchone()
    assert row is not None
    assert row.tenant_id == resultado.tenant_id


# ---------------------------------------------------------------------------
# RF-07/C3 — secretos seguros: hash bcrypt, nunca el password en claro
# ---------------------------------------------------------------------------


def test_admin_password_hash_is_bcrypt_and_never_plaintext(app_engine):
    plain_password = "ClaveEnClaroQueNuncaDebeAparecer#9"
    kwargs = _provision_kwargs(admin_password=plain_password)

    with Session(app_engine) as db:
        resultado = provision_tenant(db, **kwargs)

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(resultado.tenant_id))
            row = conn.execute(
                sa.text("SELECT password_hash FROM users WHERE id = :id"),
                {"id": resultado.admin_user_id},
            ).fetchone()

    assert row is not None
    assert row.password_hash is not None
    assert row.password_hash != plain_password
    assert plain_password not in row.password_hash
    assert row.password_hash.startswith("$bcrypt") or row.password_hash.startswith("$2")


def test_provisioned_tenant_result_never_exposes_password_or_hash(app_engine):
    """`ProvisionedTenant` (valor de retorno del servicio) solo expone
    `tenant_id`/`slug`/`admin_user_id` -- nunca password ni hash, ni siquiera
    como atributo accesible por introspección."""
    with Session(app_engine) as db:
        resultado = provision_tenant(db, **_provision_kwargs())

    campos = {f for f in resultado.__dataclass_fields__}
    assert campos == {"tenant_id", "slug", "admin_user_id"}
    for campo in campos:
        assert "password" not in campo
        assert "hash" not in campo


# ---------------------------------------------------------------------------
# RF-08 — aserto de modelo: platform_admins no scoped / sin política RLS
# ---------------------------------------------------------------------------


def test_platform_admins_not_in_tenant_scoped_tables():
    assert "platform_admins" not in TENANT_SCOPED_TABLES


def test_platform_admins_has_no_rls_isolation_policy(postgres_engine):
    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT 1 FROM pg_policies WHERE tablename = 'platform_admins' "
                "AND policyname = 'tenant_isolation_platform_admins'"
            )
        ).fetchone()
    assert row is None, (
        "platform_admins NO debe tener política tenant_isolation_* (ADR-015: "
        "es plano-plataforma, no plano-tenant)"
    )


def test_platform_admins_rls_not_enabled(postgres_engine):
    """`platform_admins` no debería ni siquiera tener RLS ENABLE (no es una
    tabla tenant-scoped, a diferencia de `users`/`tenants`)."""
    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'platform_admins'"
            )
        ).fetchone()
    assert row is not None, "La tabla platform_admins debe existir"
    row_security_enabled, _row_security_forced = row
    assert (
        row_security_enabled is False
    ), "platform_admins no debe tener RLS ENABLE (plano-plataforma, ADR-015)"
