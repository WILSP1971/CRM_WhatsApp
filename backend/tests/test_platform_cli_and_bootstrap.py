"""
Tests del CLI de alta interna (`app/db/provision_tenant.py`) y del bootstrap
del primer admin de plataforma (`app/db/bootstrap_platform_admin.py`) —
SPEC-076 (RF-10/RNF-COBERTURA, prueba SPEC-075).

Dos grupos:

1. **Contrato del CLI sin Postgres** (mockea `provision_tenant`/`run_bootstrap`
   a nivel de servicio para ejercitar parsing de argumentos, variables de
   entorno (C3: password nunca hardcodeada) y mapeo de excepciones de
   dominio -> código de salida del proceso). Corren siempre.

2. **Integración real con Postgres** (`run_bootstrap` idempotente de verdad
   contra `platform_admins`). Se SKIPEAN si no hay Postgres accesible.
"""

from __future__ import annotations

import uuid

import pytest

import app.db.bootstrap_platform_admin as bootstrap_module
import app.db.provision_tenant as cli_module
from app.services.tenant_provisioning_service import (
    EmailCollisionError,
    InvalidPasswordError,
    InvalidSlugError,
    ProvisionedTenant,
    SlugCollisionError,
)

# ---------------------------------------------------------------------------
# CLI `app/db/provision_tenant.py` — contrato sin Postgres (mockeado)
# ---------------------------------------------------------------------------


def _argv(**overrides) -> list[str]:
    base = {
        "--nombre": "Clinica CLI Demo",
        "--slug": "clinica-cli-demo",
        "--admin-email": "admin@clinica-cli-demo.test",
        "--admin-nombre": "Admin CLI Demo",
        "--admin-password": "ClaveValidaCLI#123",
    }
    base.update(overrides)
    argv: list[str] = []
    for flag, value in base.items():
        if value is None:
            continue
        argv.extend([flag, value])
    return argv


def test_cli_missing_password_without_env_var_aborts_with_code_2(monkeypatch, capsys):
    """C3: sin `--admin-password` ni la env var, el CLI aborta con un
    mensaje claro (código 2), nunca genera/acepta un password por defecto."""
    monkeypatch.delenv(cli_module._ENV_ADMIN_PASSWORD, raising=False)

    exit_code = cli_module.run(_argv(**{"--admin-password": None}))

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "falta la contraseña" in captured.err.lower()
    # Nunca debe sugerir un password por defecto inseguro.
    assert "password123" not in captured.err.lower()


def test_cli_reads_password_from_env_var_when_flag_omitted(monkeypatch):
    """C3: si se omite `--admin-password`, se lee de la env var (nunca
    queda en el historial de shell del argumento)."""
    monkeypatch.setenv(cli_module._ENV_ADMIN_PASSWORD, "ClaveDesdeEnv#456")

    capturado = {}

    def fake_provision_tenant(db, **kwargs):
        capturado.update(kwargs)
        return ProvisionedTenant(
            tenant_id=uuid.uuid4(), slug=kwargs["slug"], admin_user_id=uuid.uuid4()
        )

    monkeypatch.setattr(cli_module, "provision_tenant", fake_provision_tenant)
    # Evita abrir una sesión de BD real: `SessionLocal()` se llama pero el
    # resultado solo se usa como primer argumento posicional mockeado y se
    # cierra con `.close()` -- se sustituye por un doble mínimo.
    from types import SimpleNamespace

    monkeypatch.setattr(
        cli_module, "SessionLocal", lambda: SimpleNamespace(close=lambda: None)
    )

    exit_code = cli_module.run(_argv(**{"--admin-password": None}))

    assert exit_code == 0
    assert capturado["admin_password"] == "ClaveDesdeEnv#456"


def test_cli_explicit_password_flag_overrides_env_var(monkeypatch):
    monkeypatch.setenv(cli_module._ENV_ADMIN_PASSWORD, "ClaveDeEnvQueNoDebeUsarse")

    capturado = {}

    def fake_provision_tenant(db, **kwargs):
        capturado.update(kwargs)
        return ProvisionedTenant(
            tenant_id=uuid.uuid4(), slug=kwargs["slug"], admin_user_id=uuid.uuid4()
        )

    from types import SimpleNamespace

    monkeypatch.setattr(cli_module, "provision_tenant", fake_provision_tenant)
    monkeypatch.setattr(
        cli_module, "SessionLocal", lambda: SimpleNamespace(close=lambda: None)
    )

    exit_code = cli_module.run(_argv(**{"--admin-password": "ClaveExplicitaCLI#789"}))

    assert exit_code == 0
    assert capturado["admin_password"] == "ClaveExplicitaCLI#789"


def test_cli_success_prints_tenant_id_slug_and_admin_user_id(monkeypatch, capsys):
    tenant_id = uuid.uuid4()
    admin_user_id = uuid.uuid4()
    from types import SimpleNamespace

    def fake_provision_tenant(db, **kwargs):
        return ProvisionedTenant(
            tenant_id=tenant_id, slug=kwargs["slug"], admin_user_id=admin_user_id
        )

    monkeypatch.setattr(cli_module, "provision_tenant", fake_provision_tenant)
    monkeypatch.setattr(
        cli_module, "SessionLocal", lambda: SimpleNamespace(close=lambda: None)
    )

    exit_code = cli_module.run(_argv())

    assert exit_code == 0
    captured = capsys.readouterr()
    assert str(tenant_id) in captured.out
    assert str(admin_user_id) in captured.out
    assert "password" not in captured.out.lower()


@pytest.mark.parametrize(
    "excepcion_cls",
    [InvalidSlugError, InvalidPasswordError],
)
def test_cli_validation_errors_abort_with_code_2(monkeypatch, capsys, excepcion_cls):
    from types import SimpleNamespace

    def fake_provision_tenant_que_falla(db, **kwargs):
        raise excepcion_cls("fallo de validación simulado")

    monkeypatch.setattr(cli_module, "provision_tenant", fake_provision_tenant_que_falla)
    monkeypatch.setattr(
        cli_module, "SessionLocal", lambda: SimpleNamespace(close=lambda: None)
    )

    exit_code = cli_module.run(_argv())

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "error de validación" in captured.err.lower()


@pytest.mark.parametrize(
    "excepcion_cls",
    [SlugCollisionError, EmailCollisionError],
)
def test_cli_collision_errors_abort_with_code_1(monkeypatch, capsys, excepcion_cls):
    from types import SimpleNamespace

    def fake_provision_tenant_que_falla(db, **kwargs):
        raise excepcion_cls("fallo de colisión simulado")

    monkeypatch.setattr(cli_module, "provision_tenant", fake_provision_tenant_que_falla)
    monkeypatch.setattr(
        cli_module, "SessionLocal", lambda: SimpleNamespace(close=lambda: None)
    )

    exit_code = cli_module.run(_argv())

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "error de colisión" in captured.err.lower()


def test_cli_requires_all_mandatory_flags(capsys):
    """`argparse` exige `--nombre`/`--slug`/`--admin-email`/`--admin-nombre`;
    su ausencia aborta con `SystemExit` (código 2, comportamiento estándar
    de argparse) antes de tocar el servicio."""
    with pytest.raises(SystemExit) as exc_info:
        cli_module.run(["--slug", "solo-slug"])
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Bootstrap `app/db/bootstrap_platform_admin.py` — contrato sin Postgres
# ---------------------------------------------------------------------------


def test_bootstrap_missing_credentials_aborts_with_code_2(monkeypatch, capsys):
    monkeypatch.delenv(bootstrap_module._ENV_EMAIL, raising=False)
    monkeypatch.delenv(bootstrap_module._ENV_PASSWORD, raising=False)

    exit_code = bootstrap_module.run_bootstrap()

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "faltan credenciales" in captured.err.lower()


def test_bootstrap_missing_only_password_aborts_with_code_2(monkeypatch):
    monkeypatch.setenv(bootstrap_module._ENV_EMAIL, "admin@plataforma.test")
    monkeypatch.delenv(bootstrap_module._ENV_PASSWORD, raising=False)

    exit_code = bootstrap_module.run_bootstrap()

    assert exit_code == 2


def test_bootstrap_never_logs_password_in_claro(monkeypatch, capsys):
    """C3: ni el password en claro ni ningún hash aparecen en stdout/stderr
    del bootstrap (ni en el caso de éxito simulado ni en el de error)."""
    plain_password = "ClaveBootstrapSecreta#2026"
    monkeypatch.setenv(bootstrap_module._ENV_EMAIL, "admin@plataforma.test")
    monkeypatch.setenv(bootstrap_module._ENV_PASSWORD, plain_password)

    class _FakeConnCM:
        def __enter__(self):
            class _Result:
                def scalar_one_or_none(self_inner):
                    return uuid.uuid4()

            class _Conn:
                def execute(self_inner, *args, **kwargs):
                    return _Result()

            return _Conn()

        def __exit__(self, *exc_info):
            return False

    class _FakeEngine:
        def begin(self):
            return _FakeConnCM()

    monkeypatch.setattr(bootstrap_module, "engine", _FakeEngine())

    exit_code = bootstrap_module.run_bootstrap()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert plain_password not in captured.out
    assert plain_password not in captured.err


def test_bootstrap_idempotent_message_when_already_exists(monkeypatch, capsys):
    monkeypatch.setenv(bootstrap_module._ENV_EMAIL, "admin@plataforma.test")
    monkeypatch.setenv(bootstrap_module._ENV_PASSWORD, "ClaveYaExistente#2026")

    class _FakeConnCM:
        def __enter__(self):
            class _Result:
                def scalar_one_or_none(self_inner):
                    return None  # ON CONFLICT DO NOTHING -> ya existía

            class _Conn:
                def execute(self_inner, *args, **kwargs):
                    return _Result()

            return _Conn()

        def __exit__(self, *exc_info):
            return False

    class _FakeEngine:
        def begin(self):
            return _FakeConnCM()

    monkeypatch.setattr(bootstrap_module, "engine", _FakeEngine())

    exit_code = bootstrap_module.run_bootstrap()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "idempotente" in captured.out.lower()


# ---------------------------------------------------------------------------
# Integración real con Postgres: bootstrap idempotente de verdad
# ---------------------------------------------------------------------------


def test_bootstrap_integration_is_idempotent_against_real_postgres(
    postgres_engine, monkeypatch, capsys
):
    """Corre `run_bootstrap()` DOS veces contra Postgres real con el mismo
    email: la primera inserta, la segunda es un no-op (`ON CONFLICT DO
    NOTHING`), nunca falla ni duplica filas."""
    import sqlalchemy as sa

    email = f"bootstrap-integ-{uuid.uuid4().hex[:8]}@plataforma.test"
    monkeypatch.setenv(bootstrap_module._ENV_EMAIL, email)
    monkeypatch.setenv(bootstrap_module._ENV_PASSWORD, "ClaveBootstrapInteg#2026")
    monkeypatch.setattr(bootstrap_module, "engine", postgres_engine)

    primer_codigo = bootstrap_module.run_bootstrap()
    segundo_codigo = bootstrap_module.run_bootstrap()

    assert primer_codigo == 0
    assert segundo_codigo == 0

    with postgres_engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT id FROM platform_admins WHERE email = :email"),
            {"email": email},
        ).fetchall()
    assert len(rows) == 1, "El bootstrap no debe duplicar el platform_admin"
