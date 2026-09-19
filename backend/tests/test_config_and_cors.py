"""
Tests de config fail-fast y política de CORS (SPEC-013, hallazgos BLACK WIDOW).

- `Settings` (`app/core/config.py`): fuera de `development`, `JWT_SECRET_KEY`
  y `DB_PASSWORD` son obligatorios y deben ser "fuertes" (>=32 caracteres,
  fuera de la lista negra de valores genéricos); si no, el arranque ABORTA
  con `ConfigurationError`. En `development` arranca con valores por defecto
  documentados de desarrollo.
- `app/main.py`: `CORS_ORIGINS` se calcula desde env como allowlist explícita
  (nunca `"*"` combinado con `allow_credentials=True`).

No requieren Postgres/Redis/Docker: corren en cualquier entorno.
"""

from __future__ import annotations

import importlib

import pytest


ENV_KEYS = (
    "ENVIRONMENT",
    "JWT_SECRET_KEY",
    "DB_PASSWORD",
    "CORS_ORIGINS",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_VERIFY_TOKEN",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Limpia las variables relevantes antes de cada test (aislamiento)."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield monkeypatch


# ---------------------------------------------------------------------------
# Fail-fast de Settings (BLOQUEANTE ALTO #1/#2)
# ---------------------------------------------------------------------------


def _reload_config():
    import app.core.config as config_module

    importlib.reload(config_module)
    return config_module


def test_settings_development_starts_with_dev_defaults(clean_env):
    clean_env.setenv("ENVIRONMENT", "development")
    config_module = _reload_config()

    settings = config_module.Settings()

    assert settings.jwt_secret_key == "dev-only-change-me"
    assert settings.db_password == "postgres"


def test_settings_production_without_jwt_secret_aborts(clean_env):
    clean_env.setenv("ENVIRONMENT", "production")
    clean_env.setenv("DB_PASSWORD", "x" * 40)  # válido, para aislar el fallo al JWT
    config_module = _reload_config()

    with pytest.raises(config_module.ConfigurationError):
        config_module.Settings()


def test_settings_production_without_db_password_aborts(clean_env):
    clean_env.setenv("ENVIRONMENT", "production")
    clean_env.setenv("JWT_SECRET_KEY", "x" * 40)
    config_module = _reload_config()

    with pytest.raises(config_module.ConfigurationError):
        config_module.Settings()


@pytest.mark.parametrize(
    "weak_value", ["changeme", "dev-only-change-me", "secret", "postgres", "short"]
)
def test_settings_production_rejects_weak_or_blacklisted_secret(clean_env, weak_value):
    clean_env.setenv("ENVIRONMENT", "production")
    clean_env.setenv("JWT_SECRET_KEY", weak_value)
    clean_env.setenv("DB_PASSWORD", "y" * 40)
    config_module = _reload_config()

    with pytest.raises(config_module.ConfigurationError):
        config_module.Settings()


def test_settings_production_starts_with_strong_secrets(clean_env):
    clean_env.setenv("ENVIRONMENT", "production")
    clean_env.setenv("JWT_SECRET_KEY", "a" * 40)
    clean_env.setenv("DB_PASSWORD", "b" * 40)
    # WHATSAPP_APP_SECRET/WHATSAPP_VERIFY_TOKEN: obligatorios fuera de
    # development (SPEC-026, mismo fail-fast C3 que JWT_SECRET_KEY/DB_PASSWORD).
    clean_env.setenv("WHATSAPP_APP_SECRET", "c" * 40)
    clean_env.setenv("WHATSAPP_VERIFY_TOKEN", "d" * 40)
    # WHATSAPP_TOKEN: obligatorio fuera de development (SPEC-029, mismo
    # fail-fast C3 que el resto de secretos del canal WhatsApp).
    clean_env.setenv("WHATSAPP_TOKEN", "e" * 40)
    config_module = _reload_config()

    settings = config_module.Settings()

    assert settings.jwt_secret_key == "a" * 40
    assert settings.db_password == "b" * 40
    assert settings.whatsapp_app_secret == "c" * 40
    assert settings.whatsapp_verify_token == "d" * 40
    assert settings.whatsapp_token == "e" * 40


def test_settings_production_fails_fast_without_whatsapp_app_secret(clean_env):
    """SPEC-026 C3: sin WHATSAPP_APP_SECRET fuera de development, el arranque
    ABORTA (un secreto ausente permitiría desactivar de facto la validación
    de firma del webhook)."""
    clean_env.setenv("ENVIRONMENT", "production")
    clean_env.setenv("JWT_SECRET_KEY", "a" * 40)
    clean_env.setenv("DB_PASSWORD", "b" * 40)
    clean_env.setenv("WHATSAPP_VERIFY_TOKEN", "d" * 40)
    clean_env.setenv("WHATSAPP_TOKEN", "e" * 40)
    config_module = _reload_config()

    with pytest.raises(config_module.ConfigurationError):
        config_module.Settings()


def test_settings_production_fails_fast_without_whatsapp_verify_token(clean_env):
    """SPEC-026 C3: sin WHATSAPP_VERIFY_TOKEN fuera de development, el
    arranque ABORTA (impide validar el challenge GET de alta del webhook)."""
    clean_env.setenv("ENVIRONMENT", "production")
    clean_env.setenv("JWT_SECRET_KEY", "a" * 40)
    clean_env.setenv("DB_PASSWORD", "b" * 40)
    clean_env.setenv("WHATSAPP_APP_SECRET", "c" * 40)
    clean_env.setenv("WHATSAPP_TOKEN", "e" * 40)
    config_module = _reload_config()

    with pytest.raises(config_module.ConfigurationError):
        config_module.Settings()


def test_settings_production_fails_fast_without_whatsapp_token(clean_env):
    """SPEC-029 C3: sin WHATSAPP_TOKEN fuera de development, el arranque
    ABORTA (un access token ausente/débil bloquearía el envío en vez de
    fallar silenciosamente en cada request a la Graph API)."""
    clean_env.setenv("ENVIRONMENT", "production")
    clean_env.setenv("JWT_SECRET_KEY", "a" * 40)
    clean_env.setenv("DB_PASSWORD", "b" * 40)
    clean_env.setenv("WHATSAPP_APP_SECRET", "c" * 40)
    clean_env.setenv("WHATSAPP_VERIFY_TOKEN", "d" * 40)
    config_module = _reload_config()

    with pytest.raises(config_module.ConfigurationError):
        config_module.Settings()


def test_settings_staging_environment_also_enforces_fail_fast(clean_env):
    """Cualquier valor distinto de 'development' (p.ej. 'staging') exige secretos fuertes."""
    clean_env.setenv("ENVIRONMENT", "staging")
    config_module = _reload_config()

    with pytest.raises(config_module.ConfigurationError):
        config_module.Settings()


# ---------------------------------------------------------------------------
# CORS: nunca "*" + allow_credentials=True (MEDIO-1)
# ---------------------------------------------------------------------------


def _reload_main_with_env(monkeypatch, **env):
    for key in ("ENVIRONMENT", "CORS_ORIGINS", "JWT_SECRET_KEY", "DB_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import app.main as main_module

    importlib.reload(main_module)
    return main_module


def test_cors_development_uses_fixed_allowlist_not_wildcard(monkeypatch):
    main_module = _reload_main_with_env(monkeypatch, ENVIRONMENT="development")

    assert "*" not in main_module.CORS_ORIGINS
    assert main_module.CORS_ORIGINS  # allowlist local no vacía
    assert main_module.CORS_ALLOW_CREDENTIALS is True


def test_cors_explicit_origins_from_env_are_used(monkeypatch):
    main_module = _reload_main_with_env(
        monkeypatch,
        ENVIRONMENT="development",
        CORS_ORIGINS="https://app.omnicore.example,https://admin.omnicore.example",
    )

    assert main_module.CORS_ORIGINS == [
        "https://app.omnicore.example",
        "https://admin.omnicore.example",
    ]
    assert "*" not in main_module.CORS_ORIGINS


def test_cors_production_without_origins_disables_credentials_not_wildcard(
    monkeypatch,
):
    main_module = _reload_main_with_env(
        monkeypatch,
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a" * 40,
        DB_PASSWORD="b" * 40,
    )

    # Sin CORS_ORIGINS configurado en producción: NO se abre "*", se
    # deshabilitan credenciales y la allowlist queda vacía (CORS bloqueado).
    assert main_module.CORS_ORIGINS == []
    assert main_module.CORS_ALLOW_CREDENTIALS is False


def test_cors_middleware_never_combines_wildcard_with_credentials(monkeypatch):
    """Verifica directamente la configuración pasada al middleware instalado."""
    main_module = _reload_main_with_env(monkeypatch, ENVIRONMENT="development")

    cors_middlewares = [
        m for m in main_module.app.user_middleware if m.cls.__name__ == "CORSMiddleware"
    ]
    assert cors_middlewares, "Debe existir un CORSMiddleware registrado"

    kwargs = cors_middlewares[0].kwargs
    allow_origins = kwargs.get("allow_origins")
    allow_credentials = kwargs.get("allow_credentials")

    if allow_credentials:
        assert allow_origins != ["*"], (
            "CORS inseguro: allow_credentials=True combinado con " "allow_origins=['*']"
        )
