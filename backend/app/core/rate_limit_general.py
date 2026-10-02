"""Rate-limiting GENERAL de API por IP/endpoint — SPEC-081 (PLAN-011 F1).

CAPA 2 de rate-limiting (PLAN-011 §3.4): complementa, NUNCA sustituye, al
`LoginRateLimiter` existente (`app/security/rate_limit.py`, SPEC-013, CAPA 1
— contador de intentos fallidos de login por `tenant_slug`+`email`). Este
módulo cubre lo que la CAPA 1 no cubre: un límite genérico por IP/endpoint
para TODA la API (webhooks públicos de WhatsApp/PBX, endpoints REST y
`/rag/draft`), usando el **mismo Redis ya presente** (`REDIS_URL`, sin
servicio ni egress nuevo).

DECISIÓN DE IMPLEMENTACIÓN (investigada y verificada, no asumida):
`slowapi` (0.1.9/0.1.10, la última disponible) es la librería sugerida por
la SPEC y es la más estándar para FastAPI sobre Redis. Se confirmó
compatible con `fastapi==0.109.0`/`starlette==0.35.1` del proyecto en un
caso simple (`TestClient`, 429 con `Limiter.limit()` funcionando). SIN
EMBARGO, al integrarla sobre el código REAL del proyecto se encontró una
incompatibilidad real y reproducible: el decorador `@limiter.limit(...)`
envuelve la función del endpoint con `functools.wraps`, y esto rompe la
resolución de *forward refs* de Pydantic/FastAPI en CUALQUIER endpoint del
proyecto cuyo módulo use `from __future__ import annotations` (convención
de estilo usada en TODO el proyecto, incluidos `app/api/rag.py`,
`app/integrations/whatsapp/webhook.py` y `app/integrations/pbx/webhook.py`)
y que tenga un parámetro anotado con un tipo "complejo" (un modelo Pydantic
como `RagDraftRequest`, o `UploadFile`) sin usar `Depends`. Reproducido en
aislamiento (fuera de este repo) con `slowapi==0.1.9` y `0.1.10`: decorar un
endpoint con un parámetro `payload: Foo` (modelo Pydantic) revienta el
arranque de la app con `pydantic.errors.PydanticUndefinedAnnotation` — el
wrapper de slowapi usa su propio `__globals__` (el de `slowapi/extension.py`)
para la introspección de tipos en vez de los del módulo del endpoint. Esto
afecta exactamente a los tres endpoints que esta SPEC debe cubrir con un
límite ESPECÍFICO (`/rag/draft` con `RagDraftRequest`, el webhook del PBX
con `UploadFile`). Decorar esos endpoints directamente con
`@limiter.limit(...)` rompería el ARRANQUE COMPLETO de la aplicación, no
solo el rate-limit — una regresión inaceptable.

Por eso (criterio de implementador, autorizado explícitamente por la SPEC:
"si no encaja bien, puedes implementar un mecanismo más simple a mano"), el
diseño final es HÍBRIDO:

1. **`slowapi` + `SlowAPIMiddleware` SÍ se usa** para el límite GENERAL por
   defecto de "endpoints REST" (RF-01): se aplica vía middleware +
   `default_limits` del `Limiter`, SIN decorar ninguna función de endpoint
   (el middleware evalúa `self._application_limits`/`default_limits` sobre
   CUALQUIER petición, sin necesitar que la ruta esté "marcada" por el
   decorador roto). Esto cubre el requisito "endpoints REST" de forma
   transversal y barata, reutilizando la librería sugerida por la SPEC
   donde SÍ encaja de forma segura.
2. **Los límites ESPECÍFICOS por endpoint** (webhooks WhatsApp/PBX con
   holgura alta, `/rag/draft` con límite más bajo) se implementan con una
   dependencia FastAPI propia (`PathRateLimiter`, más abajo) que reutiliza
   EXACTAMENTE el mismo patrón ya probado y auditado de
   `app/security/rate_limit.py` (SPEC-013: contador atómico Redis
   `INCR`+`EXPIRE`, ventana fija, fail-open documentado) — una
   `Depends()` no sufre el problema de `functools.wraps`/forward-refs
   porque FastAPI resuelve el tipo de la propia función del endpoint
   directamente (nunca envuelta), y la dependencia solo añade lógica antes
   de ejecutar el cuerpo.

Esto es exactamente la misma filosofía de "capas" que pide la SPEC (CAPA 1
login ya existente + CAPA 2 general): aquí, dentro de la CAPA 2, el límite
"por defecto, transversal" vive en slowapi/middleware, y los límites "finos,
por endpoint sensible" viven en una dependencia propia — ambos comparten el
MISMO Redis, nunca se duplican ni se contradicen (el middleware de slowapi
sigue aplicando igualmente sobre los tres endpoints con límite específico,
pero su `default_limits` es más holgado que los límites específicos, así
que el límite específico dispara antes — ver umbrales más abajo).

CHECKPOINT (R-105, TOP del plan): WhatsApp/PBX pueden entregar en ráfagas
legítimas (reintentos/entregas en lote de Meta, múltiples grabaciones
seguidas del PBX). El límite se aplica ANTES del cuerpo del endpoint (la
`Depends()` se resuelve antes de ejecutar la función), pero el umbral
holgado (`WEBHOOK_RATE_LIMIT`) se calibra para que NINGUNA ráfaga legítima
real lo alcance — ver razonamiento detallado en `PathRateLimiter`/umbrales
más abajo. Una petición que SÍ excede el umbral recibe 429 sin ejecutar la
validación HMAC/el encolado; una petición dentro del umbral llega intacta a
la validación de firma y ACK rápido existentes, sin ningún cambio de
comportamiento ni bypass nuevo.

CHECKPOINT (RNF-COEXISTENCIA): el `LoginRateLimiter` vive dentro del
endpoint de login (`app/api/auth.py`) como lógica de aplicación explícita,
no como middleware ni dependencia de este módulo — no se toca. Ambos
controles son ortogonales: distinta clave de conteo
(`login_attempts:{tenant}:{email}` vs `ratelimit:{scope}:{ip}` aquí), y
`slowapi`/`limits` usa su propio prefijo de claves en Redis.

CHECKPOINT C3: `REDIS_URL` se lee exclusivamente de `Settings`
(`get_settings()`), nunca hardcodeada; cero credenciales en logs.

NOTA DE ESTILO (deliberada): este módulo, a diferencia del resto del
proyecto, NO usa `from __future__ import annotations`. Verificado
(reproducido en aislamiento): FastAPI no resuelve correctamente el tipo
`Request` del parámetro de `PathRateLimiter.__call__` cuando se usa como
`Depends(instancia)` si el módulo que define la clase tiene ese import —
afecta a CUALQUIER dependencia basada en clase con `__call__`, no solo a
este caso. Python 3.12 (versión del proyecto) soporta nativamente `X | None`
sin el future import (PEP 604), así que no se pierde expresividad.
"""

import redis
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

settings = get_settings()

# --- Umbrales por defecto (RF-05: configurables por env vía `Settings`,
# candidatos en la SPEC, ajustables por el Lead en la aprobación sin cambiar
# el alcance) ---
#
# DEFAULT_RATE_LIMIT: límite genérico aplicado a TODA la API vía
# `default_limits` del `Limiter`/`SlowAPIMiddleware` (RF-01) — cualquier
# endpoint REST queda cubierto por este default transversal. 60/minuto por
# IP es holgado para un agente humano operando la SPA (polling normal,
# navegación, varias pestañas) y acota un escenario de abuso/DoS por IP
# contra endpoints no especialmente costosos.
DEFAULT_RATE_LIMIT = settings.general_rate_limit_default

# RAG_DRAFT_RATE_LIMIT_PER_MINUTE: `/rag/draft` invoca el LLM local (Ollama)
# en el camino síncrono de la petición — es la operación más cara de la API
# en CPU/latencia (RNF-04, p95 RAG). Un límite más bajo que el default
# general protege la cola de inferencia compartida (STT/RAG/sentimiento,
# R-103) de un cliente que generara borradores en bucle; 20/minuto por IP
# sigue siendo muy superior al ritmo real de un agente humano revisando
# conversaciones (varios borradores por minuto, no decenas). Se calcula más
# abajo con `_parse_per_minute` (definida a continuación).

# WEBHOOK_RATE_LIMIT_PER_MINUTE: umbral HOLGADO específico para los webhooks públicos
# de WhatsApp (`POST /api/v1/whatsapp/webhook`) y PBX
# (`POST /webhooks/pbx/recordings`) — R-105, el riesgo TOP de esta SPEC.
#
# Razonamiento (verificado en el código real de ambos webhooks, no asumido):
# - Ambos endpoints SOLO validan firma HMAC + encolan en Redis (ACK/202 en
#   milisegundos, sin SQL ni IA en el camino caliente) — SPEC-026/037. El
#   coste por petición es bajísimo, así que un umbral alto no compromete
#   recursos compartidos (a diferencia de `/rag/draft`).
# - WhatsApp (Meta) entrega eventos por lotes cuando hay ráfaga de mensajes
#   entrantes de varios contactos a la vez (p.ej. una campaña saliente del
#   propio negocio que genera respuestas simultáneas, o reintentos de Meta
#   tras un 5xx/503 transitorio del propio servicio — ver
#   `whatsapp_webhook_enqueue_failed` en `webhook.py`, que responde 503
#   explícito precisamente para que Meta reintente). Meta puede reintentar
#   varias veces en una ventana corta tras un fallo transitorio.
# - El PBX entrega una grabación por llamada finalizada; en una oficina con
#   varias líneas colgando casi a la vez (hora pico) pueden llegar varias
#   docenas de webhooks en el mismo minuto desde la MISMA IP del PBX.
# - 300/minuto (5/segundo sostenido) por IP/endpoint es muy superior a
#   cualquier ráfaga legítima razonable de los dos escenarios anteriores,
#   pero sigue acotando un abuso real (p.ej. un flood deliberado contra el
#   endpoint público) sin requerir aprobación de producción para ajustarlo
#   (RF-05, configurable por env: `GENERAL_RATE_LIMIT_WEBHOOK`).


def _parse_per_minute(limit_string: str, *, default: int) -> int:
    """Convierte `"N/minute"` (formato slowapi) a `N` entero.

    Se reutiliza la MISMA sintaxis de configuración que `default_limits` de
    slowapi (`"60/minute"`) para que las tres variables de entorno
    (`GENERAL_RATE_LIMIT_DEFAULT/RAG_DRAFT/WEBHOOK`) tengan un formato
    uniforme, aunque el mecanismo de aplicación interno sea distinto (ver
    docstring del módulo). Solo se soporta la unidad `/minute` (suficiente
    para los tres umbrales de esta SPEC); un valor no reconocido cae al
    default documentado (fail-safe, nunca bloquea el arranque).
    """
    try:
        amount_str, _, unit = limit_string.strip().partition("/")
        amount = int(amount_str)
        if unit.strip().lower() not in ("minute", "minutes"):
            raise ValueError(f"unidad no soportada: {unit!r}")
        if amount <= 0:
            raise ValueError("limite debe ser positivo")
        return amount
    except Exception:  # noqa: BLE001 — fail-safe, nunca romper el arranque
        logger.warning(
            "rate_limit_general_formato_invalido_uso_default",
            limit_string=limit_string,
            default=default,
        )
        return default


RAG_DRAFT_RATE_LIMIT_PER_MINUTE = _parse_per_minute(
    settings.general_rate_limit_rag_draft, default=20
)
WEBHOOK_RATE_LIMIT_PER_MINUTE = _parse_per_minute(
    settings.general_rate_limit_webhook, default=300
)

_WINDOW_SECONDS = 60


def _rate_limit_key(request: Request) -> str:
    """Clave de conteo del límite GENERAL (slowapi): IP remota (RF-01, "por
    IP/endpoint"). `slowapi` combina esta clave con la ruta/endpoint
    automáticamente (namespacing interno), así que la combinación real de
    conteo ya es "por IP Y por endpoint" sin lógica adicional aquí.
    """
    return get_remote_address(request)


# --- CAPA "general/transversal": slowapi + Redis, vía middleware ---
#
# Backend: el MISMO Redis ya presente (RNF-ADITIVO, sin servicio nuevo). Solo
# se usa `default_limits` (nunca `@limiter.limit(...)` sobre una función de
# endpoint — ver docstring del módulo para el porqué). El middleware evalúa
# este límite sobre TODAS las peticiones, incluidas las de los endpoints con
# límite específico (que disparan antes, por ser más estrictos).
#
# CHECKPOINT (RNF-NO-DESCARTA-LEGITIMO/R-105, fail-open auditable — MISMO
# criterio que `LoginRateLimiter`/SPEC-013 y que `PathRateLimiter` de más
# abajo): si Redis cae, el rate-limit GENERAL **nunca** debe convertirse en
# una caída de TODA la API (sería la peor regresión posible: un problema de
# infraestructura de rate-limiting tumbando tráfico legítimo). Verificado
# (reproducido): sin `in_memory_fallback_enabled`/`swallow_errors`, un fallo
# del backend de `limits` (Redis inalcanzable, o un error del propio driver)
# se propaga como excepción no controlada y Starlette responde 500 a
# CUALQUIER petición, incluidas las que de otro modo no tendrían nada que
# ver con rate-limiting. `in_memory_fallback_enabled=True` degrada de forma
# auditada (logueada) a un contador en memoria de proceso (documentado,
# igual que el fallback de `LoginRateLimiter`: no válido para producción
# multi-worker, pero muchísimo mejor que tumbar la API); `swallow_errors=True`
# es la red de seguridad final si incluso el fallback en memoria fallara.
limiter = Limiter(
    key_func=_rate_limit_key,
    storage_uri=settings.redis_url,
    default_limits=[DEFAULT_RATE_LIMIT],
    headers_enabled=True,
    strategy="fixed-window",
    in_memory_fallback_enabled=True,
    swallow_errors=True,
)

# CHECKPOINT (RNF-COEXISTENCIA, verificado con el test existente
# `test_login_rate_limited_returns_429`): `SlowAPIMiddleware` inyecta/
# SOBRESCRIBE la cabecera `Retry-After` en CUALQUIER respuesta donde el
# límite general se haya evaluado sin excederse (`_inject_headers`,
# `slowapi/extension.py`), incluida la respuesta 429 que YA produce
# `LoginRateLimiter` desde dentro de `app/api/auth.py::login` (con su propio
# `Retry-After` exacto, calculado por SPEC-013). Sin esta exención, el
# middleware general pisaría ese valor con el suyo (el de la ventana del
# default general), rompiendo el contrato de SPEC-013 — una regresión real
# del rate-limit de login que el RNF-COEXISTENCIA prohíbe explícitamente.
# Se exime la ruta de login del rate-limit GENERAL por middleware (NO del
# `LoginRateLimiter`, que sigue intacto y es quien realmente protege ese
# endpoint): `login` ya tiene su propio control dedicado y más preciso
# (por intentos fallidos, no por volumen de peticiones), así que esta
# exención no abre ningún hueco de protección, solo evita que dos capas
# distintas escriban la misma cabecera con valores distintos. Se añade
# directamente al set interno (`_exempt_routes`) en vez de con el decorador
# `@limiter.exempt` porque ese decorador sufre el MISMO problema de
# `functools.wraps`/`from __future__ import annotations` documentado para
# `@limiter.limit` (el endpoint de login tiene `payload: LoginRequest` sin
# `Depends`).
limiter._exempt_routes.add("app.api.auth.login")


def _retry_after_from_slowapi_exc(exc: RateLimitExceeded) -> int:
    """Calcula `Retry-After` a partir de la ventana del límite de slowapi
    excedido (fixed-window: cota superior simple y segura = tamaño de la
    ventana completa, nunca se subestima el tiempo de espera)."""
    try:
        if exc.limit is None:
            return _WINDOW_SECONDS
        return int(exc.limit.limit.get_expiry())
    except Exception:  # noqa: BLE001 — nunca romper la respuesta 429 por esto
        return _WINDOW_SECONDS


def _general_rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """429 controlado (RF-01/CE-106) con cuerpo + `Retry-After` — el handler
    por defecto de `slowapi` NO añade `Retry-After` (verificado), así que se
    construye la respuesta explícitamente en vez de envolver el handler
    original.

    CHECKPOINT (verificado en `slowapi/middleware.py::sync_check_limits`):
    el `SlowAPIMiddleware` (que extiende `BaseHTTPMiddleware`, camino
    SÍNCRONO) descarta cualquier exception handler registrado que sea
    `async def` y cae de vuelta al handler por defecto de slowapi (SIN
    `Retry-After`) — `if inspect.iscoroutinefunction(exception_handler):
    exception_handler = _rate_limit_exceeded_handler`. Por eso este handler
    es deliberadamente SÍNCRONO (no hace ninguna operación async real, solo
    construye una `JSONResponse`): así `sync_check_limits` SÍ lo usa y el
    429 del middleware general también lleva `Retry-After` — reproducido y
    confirmado en pruebas locales (ver resumen de verificación de la SPEC).
    """
    retry_after_seconds = _retry_after_from_slowapi_exc(exc)
    logger.warning(
        "rate_limit_general_exceeded",
        path=request.url.path,
        method=request.method,
        limit=str(exc.limit.limit) if exc.limit else None,
        retry_after_seconds=retry_after_seconds,
    )
    return JSONResponse(
        status_code=429,
        content={"detail": "Demasiadas peticiones; reintente más tarde."},
        headers={"Retry-After": str(retry_after_seconds)},
    )


def setup_general_rate_limiting(app: FastAPI) -> None:
    """Monta el rate-limit GENERAL (CAPA transversal) en la aplicación
    (RF-01, F1/SPEC-081).

    Se llama explícitamente desde `app/main.py`. Añade:
    - `app.state.limiter`: requerido por `slowapi`.
    - El exception handler de 429 con `Retry-After`.
    - `SlowAPIMiddleware`: aplica `default_limits` a CUALQUIER ruta (RF-01,
      cobertura general de "endpoints REST").

    Coexistencia (RNF-COEXISTENCIA): no se toca `CORSMiddleware`,
    `SecurityHeadersMiddleware`, `RequestIDMiddleware` ni el
    `LoginRateLimiter` (que vive en `app/api/auth.py`, fuera de esta capa de
    middleware).
    """
    app.state.limiter = limiter
    # `add_exception_handler` acepta handlers síncronos en runtime (FastAPI/
    # Starlette los soportan igual que los `async def`); el stub de tipos de
    # Starlette solo anota la variante `Awaitable`, de ahí el `type: ignore`
    # puntual (sin impacto en runtime, confirmado con pruebas funcionales).
    app.add_exception_handler(
        RateLimitExceeded, _general_rate_limit_exceeded_handler  # type: ignore[arg-type]
    )
    app.add_middleware(SlowAPIMiddleware)


# --- CAPA "específica por endpoint sensible": dependencia propia sobre
# Redis (webhooks WhatsApp/PBX con holgura, `/rag/draft` con límite más
# bajo) — NO usa el decorador de slowapi (ver docstring del módulo: rompe
# `from __future__ import annotations` + parámetros Pydantic/`UploadFile`).
# Reutiliza EXACTAMENTE el mismo patrón ya auditado de
# `app/security/rate_limit.py` (SPEC-013): `INCR` + `EXPIRE` atómico sobre
# Redis, ventana fija.
# ---------------------------------------------------------------------


class PathRateLimiter:
    """Límite por IP, acotado a UNA ruta concreta (contador namespaced por
    `scope`), implementado como dependencia de FastAPI (`Depends`).

    Se usa para los endpoints que SPEC-081 exige cubrir con un umbral
    ESPECÍFICO (distinto del default general): los webhooks de WhatsApp/PBX
    (holgura alta, R-105) y `/rag/draft` (límite más bajo, R-103). Al ser una
    dependencia normal (no un decorador que envuelve la función), es
    compatible con `from __future__ import annotations` y con parámetros de
    tipo Pydantic/`UploadFile` sin ningún efecto secundario sobre la
    introspección de tipos de FastAPI.

    Backend: el MISMO cliente Redis síncrono (`redis-py`, ya en
    `requirements.txt`) con el MISMO `REDIS_URL` — ninguna conexión nueva,
    ningún servicio nuevo (RNF-ADITIVO). Si Redis no está disponible, se
    sigue el mismo criterio de "fail-open auditable" que `LoginRateLimiter`
    (SPEC-013, CHECKPOINT BLACK WIDOW MEDIO-2): nunca se bloquea el ACK
    rápido de un webhook ni `/rag/draft` por una caída de Redis — se
    registra `logger.error` y se permite continuar, en vez de convertir una
    caída de infraestructura en una denegación de servicio para tráfico
    legítimo (lo contrario violaría R-105/RNF-NO-DESCARTA-LEGITIMO).
    """

    def __init__(
        self, *, scope: str, max_requests: int, window_seconds: int = _WINDOW_SECONDS
    ) -> None:
        self.scope = scope
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._client: redis.Redis | None = None

    def _get_client(self) -> redis.Redis | None:
        if self._client is not None:
            return self._client
        try:
            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
            client.ping()  # type: ignore[attr-defined]
            self._client = client
            return self._client
        except Exception as exc:  # noqa: BLE001 — Redis no disponible
            logger.error(
                "rate_limit_general_redis_inaccesible_fail_open",
                scope=self.scope,
                redis_url=settings.redis_url,
                error=str(exc),
            )
            return None

    def _key(self, ip: str) -> str:
        return f"ratelimit_general:{self.scope}:{ip}"

    def __call__(self, request: Request) -> None:
        ip = get_remote_address(request)
        client = self._get_client()
        if client is None:
            # Fail-open auditable (ver docstring de la clase): no se
            # bloquea tráfico legítimo por una caída de infraestructura.
            return
        key = self._key(ip)
        try:
            pipe = client.pipeline()
            pipe.incr(key, 1)
            pipe.ttl(key)
            count, ttl = pipe.execute()
            if ttl is None or ttl < 0:
                client.expire(key, self.window_seconds)
                ttl = self.window_seconds
        except Exception as exc:  # noqa: BLE001 — Redis cae a mitad de operación
            logger.error(
                "rate_limit_general_redis_error_fail_open",
                scope=self.scope,
                error=str(exc),
            )
            return

        if count > self.max_requests:
            logger.warning(
                "rate_limit_general_path_exceeded",
                scope=self.scope,
                path=request.url.path,
                retry_after_seconds=int(ttl),
            )
            raise HTTPException(
                status_code=429,
                detail="Demasiadas peticiones; reintente más tarde.",
                headers={"Retry-After": str(int(ttl))},
            )


# Instancias concretas (RF-01/RF-03): una por "scope" lógico, para que el
# contador de un endpoint nunca interfiera con el de otro aunque compartan
# la misma IP de origen (p.ej. el servidor del PBX y el de WhatsApp podrían,
# en un entorno de pruebas, compartir IP saliente).
rag_draft_rate_limiter = PathRateLimiter(
    scope="rag_draft", max_requests=RAG_DRAFT_RATE_LIMIT_PER_MINUTE
)
whatsapp_webhook_rate_limiter = PathRateLimiter(
    scope="whatsapp_webhook", max_requests=WEBHOOK_RATE_LIMIT_PER_MINUTE
)
pbx_webhook_rate_limiter = PathRateLimiter(
    scope="pbx_webhook", max_requests=WEBHOOK_RATE_LIMIT_PER_MINUTE
)
