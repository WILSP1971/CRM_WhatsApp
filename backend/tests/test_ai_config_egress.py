"""Tests del checkpoint SENSIBLE de config para el host de IA — SPEC-016.

`Settings._require_internal_ai_host` es la defensa en profundidad en código
(además de la red Docker `internal: true` y de `check-externos-backend.sh`):
si `OLLAMA_BASE_URL` no resuelve a un host interno permitido, el arranque
ABORTA con `ConfigurationError` en vez de dejar pasar una configuración que
abriría una ruta de inferencia externa.

No requiere Postgres/Redis/Docker: corre en cualquier entorno.
"""

from __future__ import annotations

import importlib

import pytest


ENV_KEYS = (
    "ENVIRONMENT",
    "JWT_SECRET_KEY",
    "DB_PASSWORD",
    "OLLAMA_BASE_URL",
)


@pytest.fixture
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield monkeypatch


def _reload_config():
    import app.core.config as config_module

    importlib.reload(config_module)
    return config_module


def test_default_ollama_base_url_is_internal_service(clean_env):
    clean_env.setenv("ENVIRONMENT", "development")
    config_module = _reload_config()

    settings = config_module.Settings()

    assert settings.ai_base_url == "http://ia:11434"


@pytest.mark.parametrize(
    "internal_url",
    [
        "http://ia:11434",
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://0.0.0.0:11434",
    ],
)
def test_internal_hosts_are_accepted(clean_env, internal_url):
    clean_env.setenv("ENVIRONMENT", "development")
    clean_env.setenv("OLLAMA_BASE_URL", internal_url)
    config_module = _reload_config()

    settings = config_module.Settings()

    assert settings.ai_base_url == internal_url


@pytest.mark.parametrize(
    "external_url",
    [
        "https://api.openai.com/v1",
        "https://api.anthropic.com",
        "http://evil.example.com:11434",
        "https://my-ollama-cloud.example.com",
        "http://8.8.8.8:11434",
    ],
)
def test_external_ai_host_aborts_startup(clean_env, external_url):
    """CHECKPOINT SENSIBLE (.no-externo, RNF-01/CE-21): un host que no es el
    servicio interno DEBE abortar el arranque, sin importar el entorno."""
    clean_env.setenv("ENVIRONMENT", "development")
    clean_env.setenv("OLLAMA_BASE_URL", external_url)
    config_module = _reload_config()

    with pytest.raises(config_module.ConfigurationError):
        config_module.Settings()


def test_external_ai_host_aborts_in_production_too(clean_env):
    clean_env.setenv("ENVIRONMENT", "production")
    clean_env.setenv("JWT_SECRET_KEY", "a" * 40)
    clean_env.setenv("DB_PASSWORD", "b" * 40)
    clean_env.setenv("OLLAMA_BASE_URL", "https://api.openai.com/v1")
    config_module = _reload_config()

    with pytest.raises(config_module.ConfigurationError):
        config_module.Settings()
