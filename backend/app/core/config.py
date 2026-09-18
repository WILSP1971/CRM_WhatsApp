"""
Configuración central de la aplicación — OmniCore AI backend (SPEC-012).

CHECKPOINT C3 (secretos): toda credencial/cadena de conexión se lee EXCLUSIVAMENTE
de variables de entorno (`.env` vía docker-compose o entorno del proceso). Nunca se
hardcodea un valor real en el código fuente; los valores por defecto aquí son
únicamente para desarrollo local y NO son secretos de producción.
"""

import os
from functools import lru_cache

# CHECKPOINT C3 (BLACK WIDOW, SPEC-013): valores de secretos débiles/genéricos
# que NUNCA deben aceptarse fuera de `development` (fail-fast en `Settings`).
_WEAK_SECRET_VALUES = {
    "",
    "changeme",
    "change-me",
    "dev-only-change-me",
    "secret",
    "postgres",
}
_MIN_SECRET_LENGTH = 32


class ConfigurationError(RuntimeError):
    """Configuración insegura para el entorno actual (fail-fast al arrancar)."""


class Settings:
    """Lee la configuración desde variables de entorno (C3: sin secretos en claro)."""

    def __init__(self) -> None:
        self.environment: str = os.getenv("ENVIRONMENT", "development")
        self._is_development = self.environment.strip().lower() == "development"

        # --- Base de datos (PostgreSQL 16 + pgvector) ---
        self.db_host: str = os.getenv("DB_HOST", "localhost")
        self.db_port: str = os.getenv("DB_PORT", "5432")
        self.db_name: str = os.getenv("DB_NAME", "omnicore_ai")
        self.db_user: str = os.getenv("DB_USER", "postgres")
        self.db_password: str = self._require_strong_secret(
            "DB_PASSWORD", os.getenv("DB_PASSWORD"), dev_default="postgres"
        )

        # DATABASE_URL explícita tiene prioridad (permite override total desde env/secret manager).
        self.database_url: str = os.getenv(
            "DATABASE_URL",
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}",
        )

        # --- Multi-tenant / RLS (ADR-004) ---
        # Nombre del parámetro de sesión de PostgreSQL que las políticas RLS usan
        # como predicado (SET LOCAL app.tenant_id = '<uuid>').
        self.tenant_session_var: str = os.getenv("TENANT_SESSION_VAR", "app.tenant_id")

        # --- Autenticación / JWT (SPEC-013) ---
        # CHECKPOINT C3 (BLACK WIDOW): sin default inseguro. Fuera de
        # `development`, el arranque ABORTA si `JWT_SECRET_KEY` falta o es
        # débil (< 32 caracteres o en la lista negra) — un secreto conocido
        # permitiría forjar tokens y hacer bypass de RLS (ADR-004).
        self.jwt_secret_key: str = self._require_strong_secret(
            "JWT_SECRET_KEY",
            os.getenv("JWT_SECRET_KEY"),
            dev_default="dev-only-change-me",
        )
        self.jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
        self.jwt_access_token_expire_minutes: int = int(
            os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
        )

        # --- Rate-limit de login (SPEC-013 RF, mitigación de fuerza bruta) ---
        self.login_rate_limit_max_attempts: int = int(
            os.getenv("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "5")
        )
        self.login_rate_limit_window_seconds: int = int(
            os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300")
        )
        # Fuera de development, por defecto se exige Redis real para el
        # rate-limit (evita degradar silenciosamente a memoria per-worker en
        # producción); en development degrada con warning (ver rate_limit.py).
        self.login_rate_limit_strict_redis: bool = os.getenv(
            "LOGIN_RATE_LIMIT_STRICT_REDIS",
            "false" if self._is_development else "true",
        ).strip().lower() in ("1", "true", "yes")

        # --- Redis (usado por el rate-limit de login; SPEC-011 ya lo define) ---
        self.redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")

        # --- IA local self-hosted (Ollama) — SPEC-016, SENSIBLE (.no-externo) ---
        # CHECKPOINT C3/RNF-01: el host del modelo se configura SOLO por env y
        # DEBE apuntar al servicio interno de la red `ia_internal` (SPEC-011,
        # `internal: true`). Nunca a un dominio de internet. `_require_internal_ai_host`
        # falla-rápido (arranque) si detecta un host que no es el interno esperado,
        # para que un error de configuración no abra una ruta de egress de inferencia.
        self.ai_base_url: str = self._require_internal_ai_host(
            "OLLAMA_BASE_URL",
            os.getenv("OLLAMA_BASE_URL", "http://ia:11434"),
        )
        self.ai_llm_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
        self.ai_embedding_model: str = os.getenv(
            "OLLAMA_EMBED_MODEL", "nomic-embed-text"
        )
        self.ai_request_timeout_seconds: float = float(
            os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "30")
        )
        self.ai_connect_timeout_seconds: float = float(
            os.getenv("AI_CONNECT_TIMEOUT_SECONDS", "5")
        )

        # --- Datos personales: minimización y retención (SPEC-021, HABEAS
        # DATA/GDPR-like) ---
        # `DATA_RETENTION_DAYS`: ventana (en días) tras la cual un contacto
        # inactivo (borrado lógico, C2) es candidato a anonimización por el
        # job de retención (`app.services.retention_service`). No aplica a
        # contactos activos: la retención opera SOLO sobre lo que ya fue
        # marcado `activo=False` (p.ej. por el titular vía HABEAS DATA o por
        # el agente), nunca borra/anonimiza datos en uso.
        self.data_retention_days: int = int(os.getenv("DATA_RETENTION_DAYS", "90"))
        # `ENABLE_DATA_ANONYMIZATION`: por defecto `false` — el job de
        # retención puede ejecutarse en modo "solo reporte" (dry-run) sin
        # tocar datos hasta que se habilite explícitamente. Evita que un
        # despliegue nuevo anonimice datos sin que el Lead lo haya decidido.
        self.enable_data_anonymization: bool = os.getenv(
            "ENABLE_DATA_ANONYMIZATION", "false"
        ).strip().lower() in ("1", "true", "yes")

    # Hosts permitidos para el servicio de IA: nombre de servicio Docker
    # (`ia`, resuelto en la red interna `ia_internal`) o loopback (para
    # ejecutar Ollama directamente en el host durante desarrollo local sin
    # Docker). Cualquier otro host se considera una fuga potencial de egress
    # de inferencia (RNF-01/CE-21) y aborta el arranque.
    _ALLOWED_AI_HOSTS = {"ia", "localhost", "127.0.0.1", "0.0.0.0", "[::1]"}

    def _require_internal_ai_host(self, var_name: str, raw_url: str) -> str:
        """Valida que la URL del servicio de IA apunte SOLO a la red interna.

        Defensa en profundidad (ADR-005): además del aislamiento de red
        Docker (`ia_internal` con `internal: true`) y del auditor estático
        `check-externos-backend.sh`, la propia aplicación rechaza arrancar
        si `OLLAMA_BASE_URL`/`AI_BASE_URL` no resuelve a un host interno
        conocido (servicio `ia` o loopback). Esto evita que un error de
        configuración (p.ej. pegar por accidente un endpoint de internet)
        active una ruta de inferencia externa.
        """
        from urllib.parse import urlparse

        parsed = urlparse(raw_url)
        host = (parsed.hostname or "").strip().lower()
        if host not in self._ALLOWED_AI_HOSTS:
            raise ConfigurationError(
                f"{var_name}='{raw_url}' no apunta a un host interno permitido "
                f"({sorted(self._ALLOWED_AI_HOSTS)}). CHECKPOINT SENSIBLE "
                "(.no-externo, RNF-01/CE-21): la inferencia de IA SOLO puede "
                "hablar con el servicio interno de la red `ia_internal` "
                "(SPEC-011). Revisa la variable de entorno antes de arrancar."
            )
        return raw_url

    def _require_strong_secret(
        self, var_name: str, raw_value: str | None, *, dev_default: str
    ) -> str:
        """Fail-fast (C3, BLACK WIDOW SPEC-013): exige un secreto robusto fuera
        de `development`.

        - En `development`: si la variable no está definida, se usa
          `dev_default` (documentado como valor de desarrollo, nunca válido
          en producción). Si SÍ está definida mantiene el valor dado aunque
          sea débil, para no romper flujos locales existentes.
        - Fuera de `development` (staging/production/cualquier otro valor):
          la variable es OBLIGATORIA, no puede estar en la lista negra de
          valores débiles/genéricos, y debe tener al menos
          `_MIN_SECRET_LENGTH` caracteres. Si no se cumple, se aborta el
          arranque con `ConfigurationError` (evita arrancar con un secreto
          conocido que permitiría forjar tokens o adivinar credenciales de BD).
        """
        if self._is_development:
            return raw_value if raw_value else dev_default

        if not raw_value:
            raise ConfigurationError(
                f"{var_name} es obligatorio cuando ENVIRONMENT="
                f"'{self.environment}' (no development). Configúralo como "
                "variable de entorno/secret manager (CHECKPOINT C3)."
            )
        if raw_value.strip().lower() in _WEAK_SECRET_VALUES:
            raise ConfigurationError(
                f"{var_name} tiene un valor débil/genérico no permitido fuera "
                "de development (CHECKPOINT C3). Usa un secreto robusto y "
                "único por entorno."
            )
        if len(raw_value) < _MIN_SECRET_LENGTH:
            raise ConfigurationError(
                f"{var_name} debe tener al menos {_MIN_SECRET_LENGTH} "
                f"caracteres fuera de development (longitud actual: "
                f"{len(raw_value)})."
            )
        return raw_value

    @property
    def sqlalchemy_database_url(self) -> str:
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
