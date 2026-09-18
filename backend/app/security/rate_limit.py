"""
Rate-limit básico de login — SPEC-013 ("bloqueo por intentos fallidos /
rate-limit básico de login (Redis)").

Estrategia: contador de intentos fallidos por clave `(tenant_slug, email)`
con ventana deslizante fija (fixed window). Backend primario: Redis
(`REDIS_URL`, ya definido en SPEC-011/012). Si Redis no está accesible
(p.ej. este sandbox de desarrollo sin daemon), se usa automáticamente un
backend en memoria de proceso como *fallback* — documentado explícitamente:
el fallback en memoria NO es apto para producción multi-worker (cada worker
tendría su propio contador). En producción (docker-compose,
`REDIS_URL=redis://redis:6379`) se usa siempre el backend Redis real.

CHECKPOINT (BLACK WIDOW, SPEC-013 MEDIO-2): la caída a memoria NUNCA es
silenciosa. Se loguea siempre con `logger.warning`/`logger.error`. Además,
fuera de `development`, si `LOGIN_RATE_LIMIT_STRICT_REDIS=true` (por defecto
`true` fuera de development), Redis inaccesible se trata como error de
arranque de la protección — se loguea `error` y se sigue funcionando en modo
degradado (fail-open del rate-limit, no del login) para no tumbar el
servicio, pero queda visible y auditable en los logs.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import structlog

from app.core.config import get_settings

settings = get_settings()
logger = structlog.get_logger(__name__)


class LoginRateLimitExceeded(Exception):
    """Se superó el número de intentos fallidos permitidos en la ventana."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Demasiados intentos fallidos; reintente en {retry_after_seconds}s"
        )


class RateLimitBackendUnavailableError(Exception):
    """Redis inaccesible en modo estricto (`LOGIN_RATE_LIMIT_STRICT_REDIS`).

    Se lanza en vez de degradar silenciosamente a memoria fuera de
    development, para que la capa de servicio decida cómo responder
    (p.ej. 503) en lugar de aplicar un rate-limit per-worker no confiable.
    """


class _InMemoryBackend:
    """Backend de respaldo en memoria de proceso (solo dev/test, ver docstring)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, tuple[int, float]] = {}

    def incr_with_window(self, key: str, window_seconds: int) -> tuple[int, int]:
        now = time.monotonic()
        with self._lock:
            count, window_start = self._counters.get(key, (0, now))
            if now - window_start >= window_seconds:
                count, window_start = 0, now
            count += 1
            self._counters[key] = (count, window_start)
            remaining = max(0, int(window_seconds - (now - window_start)))
            return count, remaining

    def reset(self, key: str) -> None:
        with self._lock:
            self._counters.pop(key, None)


class _RedisBackend:
    """Backend Redis real (producción) — contador atómico con expiración."""

    def __init__(self, redis_url: str) -> None:
        import redis  # import perezoso: opcional si Redis no está instalado/activo

        self._client = redis.Redis.from_url(redis_url, socket_connect_timeout=1)
        self._client.ping()

    def incr_with_window(self, key: str, window_seconds: int) -> tuple[int, int]:
        pipe = self._client.pipeline()
        pipe.incr(key, 1)
        pipe.ttl(key)
        count, ttl = pipe.execute()
        if ttl is None or ttl < 0:
            self._client.expire(key, window_seconds)
            ttl = window_seconds
        return int(count), int(ttl)

    def reset(self, key: str) -> None:
        self._client.delete(key)


@dataclass
class LoginRateLimiter:
    """Limita intentos de login fallidos por clave lógica (tenant + email)."""

    max_attempts: int = field(
        default_factory=lambda: settings.login_rate_limit_max_attempts
    )
    window_seconds: int = field(
        default_factory=lambda: settings.login_rate_limit_window_seconds
    )
    _backend: object = field(default=None, init=False, repr=False)

    def _get_backend(self):
        if self._backend is not None:
            return self._backend
        try:
            self._backend = _RedisBackend(settings.redis_url)
            return self._backend
        except Exception as exc:
            if settings.login_rate_limit_strict_redis:
                logger.error(
                    "Rate-limit de login: Redis inaccesible en modo estricto "
                    "(LOGIN_RATE_LIMIT_STRICT_REDIS=true); se rechaza el "
                    "intento en vez de degradar a memoria per-worker.",
                    redis_url=settings.redis_url,
                    error=str(exc),
                )
                raise RateLimitBackendUnavailableError(
                    "Redis inaccesible para el rate-limit de login (modo estricto)"
                ) from exc

            logger.warning(
                "Rate-limit de login: Redis inaccesible, usando fallback en "
                "memoria de proceso (NO válido para producción multi-worker; "
                "ver LOGIN_RATE_LIMIT_STRICT_REDIS).",
                redis_url=settings.redis_url,
                error=str(exc),
            )
            self._backend = _InMemoryBackend()
            return self._backend

    @staticmethod
    def _key(tenant_slug: str, email: str) -> str:
        return f"login_attempts:{tenant_slug}:{email.strip().lower()}"

    def check_and_increment(self, tenant_slug: str, email: str) -> None:
        """Incrementa el contador de intentos fallidos y bloquea si excede el límite.

        Debe llamarse tras una credencial inválida. Lanza
        `LoginRateLimitExceeded` si ya se superó `max_attempts` en la ventana.
        """
        key = self._key(tenant_slug, email)
        backend = self._get_backend()
        count, retry_after = backend.incr_with_window(key, self.window_seconds)
        if count > self.max_attempts:
            raise LoginRateLimitExceeded(retry_after)

    def reset(self, tenant_slug: str, email: str) -> None:
        """Limpia el contador tras un login exitoso."""
        self._get_backend().reset(self._key(tenant_slug, email))


login_rate_limiter = LoginRateLimiter()
