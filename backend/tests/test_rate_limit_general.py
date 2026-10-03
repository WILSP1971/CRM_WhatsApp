"""Tests del rate-limit GENERAL de API por IP/endpoint — SPEC-081/SPEC-084
(PLAN-011 F1/F4, CE-106).

Verifica el criterio de aceptación "exceso por IP/endpoint -> 429; ráfaga
legítima de webhooks -> SIN 429; coexiste con `LoginRateLimiter`" SIN
Postgres/Redis reales (mismo patrón que `test_whatsapp_webhook.py`/
`test_pbx_recordings_webhook.py`): usa `fakeredis` como doble del cliente
Redis SÍNCRONO (`redis.Redis.from_url`) que `PathRateLimiter`
(`app/core/rate_limit_general.py`) crea internamente (NO es una dependencia
de FastAPI inyectable vía `app.dependency_overrides`, a diferencia de
`get_redis_client`/pub-sub — por eso se parchea `redis.Redis.from_url` en el
propio módulo).

HALLAZGO ENCONTRADO Y CORREGIDO (SPEC-084, R-105): HAWKEYE detectó que el
middleware GENERAL (`SlowAPIMiddleware`/`default_limits`) se evalúa, por
diseño de `slowapi`, sobre **todas** las rutas cuando corre "en middleware"
(`_check_request_limit(..., in_middleware=True)` IGNORA `_route_limits`/
`_dynamic_route_limits` y cae siempre a `_default_limits` — verificado
leyendo `slowapi/extension.py::Limiter._check_request_limit`). Sin
corrección, esto dejaba el umbral "holgado" de los webhooks
(`WEBHOOK_RATE_LIMIT_PER_MINUTE`, 300/min) INALCANZABLE en la práctica: el
general (60/min, más estricto) disparaba primero — justo el riesgo TOP que
SPEC-081/R-105 debía mitigar (ráfagas legítimas de WhatsApp/PBX
rechazadas). CORREGIDO en `rate_limit_general.py`: los 3 endpoints con
límite ESPECÍFICO (webhooks WhatsApp/PBX + `/rag/draft`) se eximen del
middleware general (`limiter._exempt_routes`, mismo patrón ya usado para
`login`) — el `PathRateLimiter` de cada uno pasa a ser la ÚNICA capa que
los protege, con el umbral correcto y calibrado.

Cubre:
  (a) Exceder el umbral ESPECÍFICO real de los webhooks (300/min por
      defecto, `WEBHOOK_RATE_LIMIT_PER_MINUTE`) -> 429 con `Retry-After`,
      SIN tocar el cuerpo del endpoint (ni siquiera llega a validar la
      firma HMAC).
  (b) Una ráfaga DENTRO del umbral específico (simulando tráfico legítimo
      real de WhatsApp/PBX, incluyendo volúmenes que ANTES de la
      corrección habrían recibido 429 del middleware general a partir de
      60/min) -> NUNCA 429; cada petición llega intacta a la validación
      HMAC existente.
  (c) El contador ESPECÍFICO (`PathRateLimiter`) es independiente por
      `scope` (WhatsApp vs PBX no cruzan contadores), ejercido
      directamente sobre las instancias (sin pasar por HTTP/middleware).
  (d) El rate-limit GENERAL (capa transversal `slowapi`/`default_limits`,
      sin Redis real en este entorno -> fallback en memoria de proceso
      documentado) sigue disparando 429 sobre un endpoint REST SIN límite
      específico (`/healthz`) al exceder su umbral, confirmando RF-01
      ("cobertura general, no solo los 3 endpoints con límite
      específico") — y que la exención de (a)/(b) es ACOTADA a esas 3
      rutas, no una desactivación global del middleware general.
  (e) Coexistencia: `test_login_rate_limited_returns_429`
      (`tests/test_auth_api.py`, SPEC-013) sigue en verde SIN que esta
      suite lo toque — se re-ejecuta explícitamente en este módulo para
      dejar evidencia conjunta (RNF-COEXISTENCIA).
"""

from __future__ import annotations

import hashlib
import hmac

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.redis_client import get_redis_client
from app.main import app

import app.core.rate_limit_general as rate_limit_general_module

WHATSAPP_WEBHOOK_URL = "/api/v1/whatsapp/webhook"
PBX_WEBHOOK_URL = "/webhooks/pbx/recordings"


@pytest.fixture
def client():
    return TestClient(app)


def _reset_general_limiter_state() -> None:
    """El `Limiter` GENERAL (`app.state.limiter`, slowapi) es un singleton
    de PROCESO cuyo almacenamiento persiste entre tests. En este sandbox
    SIN Redis real, cada petición intenta conectar al Redis configurado
    (`settings.redis_url`), falla, y `slowapi` activa su
    `_fallback_storage` (`MemoryStorage` en memoria de proceso,
    `in_memory_fallback_enabled=True`, ver `rate_limit_general.py`) de
    forma marcada por `_storage_dead=True` — una vez activado, se queda
    así para el resto del proceso. `Limiter.reset()` NO sirve aquí: intenta
    resetear `self._storage` (el backend REAL, Redis) en vez del fallback,
    y revienta con `ConnectionError` sin Redis disponible. Se resetea
    directamente el `MemoryStorage` del fallback, que SÍ es local y no
    requiere red — sin tocar el comportamiento de producción (con Redis
    real disponible, `_storage_dead` nunca se activa y este reset es un
    no-op sobre un fallback que ni siquiera se usa)."""
    limiter = app.state.limiter
    fallback_storage = getattr(limiter, "_fallback_storage", None)
    if fallback_storage is not None:
        fallback_storage.reset()


@pytest.fixture(autouse=True)
def _reset_general_rate_limiter_storage():
    """Resetea el fallback in-memory del `Limiter` GENERAL antes y después
    de cada test de este módulo, para que cada uno sea determinista e
    independiente del orden de ejecución (ver `_reset_general_limiter_state`)."""
    _reset_general_limiter_state()
    yield
    _reset_general_limiter_state()


@pytest.fixture
def fake_queue_redis():
    """Doble de Redis para la cola de encolado (`get_redis_client`, async).

    A diferencia de `test_whatsapp_webhook.py`/`test_pbx_recordings_webhook.py`
    (que hacen UNA sola petición HTTP por test), estos tests disparan MUCHAS
    peticiones seguidas en el mismo test (ráfagas/exceso de umbral) — un
    único `fakeredis.aioredis.FakeRedis` se ata al primer loop/portal de
    `anyio` que lo usa y falla (`enqueue_failed` -> 503) en llamadas
    posteriores de `TestClient` que puedan correr en un loop distinto. Se
    evita creando un cliente async NUEVO (mismo `FakeServer` en memoria
    compartido, mismos datos) en cada resolución de la dependencia, igual
    que si cada request HTTP abriera su propia conexión — el `FakeServer`
    es el estado compartido real, no la instancia de cliente.
    """
    server = fakeredis.FakeServer()

    def _new_async_client():
        return fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    sync_inspector = fakeredis.FakeStrictRedis(server=server, decode_responses=True)
    app.dependency_overrides[get_redis_client] = _new_async_client
    yield sync_inspector
    app.dependency_overrides.pop(get_redis_client, None)


@pytest.fixture
def fake_path_rate_limiter_redis(monkeypatch):
    """Parchea el cliente Redis SÍNCRONO que `PathRateLimiter` crea
    internamente (`redis.Redis.from_url`, en `app.core.rate_limit_general`)
    por un `fakeredis.FakeStrictRedis` — permite ejercer el contador
    `INCR`/`EXPIRE` real sin un daemon Redis.

    Se resetea el `_client` cacheado de las 3 instancias de módulo
    (`whatsapp_webhook_rate_limiter`/`pbx_webhook_rate_limiter`/
    `rag_draft_rate_limiter`) antes y después de cada test, para que ningún
    contador de un test se filtre al siguiente (misma IP de prueba,
    `TestClient` siempre usa `testclient` como IP remota).
    """
    server = fakeredis.FakeServer()
    fake_client = fakeredis.FakeStrictRedis(server=server)

    def _fake_from_url(*_args, **_kwargs):
        return fake_client

    monkeypatch.setattr(
        rate_limit_general_module.redis.Redis, "from_url", staticmethod(_fake_from_url)
    )

    limiters = [
        rate_limit_general_module.whatsapp_webhook_rate_limiter,
        rate_limit_general_module.pbx_webhook_rate_limiter,
        rate_limit_general_module.rag_draft_rate_limiter,
    ]
    for limiter in limiters:
        limiter._client = None
    yield fake_client
    for limiter in limiters:
        limiter._client = None


def _sign_whatsapp(body: bytes) -> str:
    settings = get_settings()
    digest = hmac.new(
        settings.whatsapp_app_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def _sign_pbx(audio_bytes: bytes) -> str:
    settings = get_settings()
    digest = hmac.new(
        settings.webhook_secret.encode("utf-8"), audio_bytes, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def _post_whatsapp(client, *, signed: bool = True):
    raw_body = b'{"object":"whatsapp_business_account","entry":[{"id":"1"}]}'
    headers = {"Content-Type": "application/json"}
    if signed:
        headers["X-Hub-Signature-256"] = _sign_whatsapp(raw_body)
    return client.post(WHATSAPP_WEBHOOK_URL, content=raw_body, headers=headers)


def _post_pbx(client, *, signed: bool = True, call_id: str = "call-demo-000001"):
    audio_bytes = b"RIFF....WAVEfmt "
    headers = {}
    if signed:
        headers["X-Webhook-Signature-256"] = _sign_pbx(audio_bytes)
    data = {
        "call_id": call_id,
        "numero": "3001112222",
        "numero_destino": "6011234500",
        "direccion": "entrante",
    }
    files = {"file": ("grabacion.wav", audio_bytes, "audio/wav")}
    return client.post(PBX_WEBHOOK_URL, headers=headers, data=data, files=files)


def _webhook_specific_threshold_per_minute() -> int:
    """Umbral REAL que protege los webhooks tras la corrección (SPEC-084):
    el ESPECÍFICO holgado (`PathRateLimiter`, `WEBHOOK_RATE_LIMIT_PER_MINUTE`
    = 300/min por defecto) — el middleware general ya NO interfiere (rutas
    exentas en `rate_limit_general.py`)."""
    return rate_limit_general_module.WEBHOOK_RATE_LIMIT_PER_MINUTE


# ---------------------------------------------------------------------------
# (a)/(b) Umbral específico de los webhooks: ráfaga legítima vs exceso -> 429
# ---------------------------------------------------------------------------


def test_whatsapp_webhook_burst_within_specific_threshold_never_returns_429(
    client, fake_queue_redis, fake_path_rate_limiter_redis
):
    """Ráfaga LEGÍTIMA, incluyendo un volumen que ANTES de la corrección de
    R-105 habría recibido 429 del middleware general (más de 60/min, pero
    muy por debajo del umbral específico holgado): ninguna de las
    peticiones recibe 429 — R-105, el riesgo TOP de SPEC-081."""
    threshold = _webhook_specific_threshold_per_minute()
    default_general_limit = int(rate_limit_general_module.DEFAULT_RATE_LIMIT.split("/")[0])

    burst_size = default_general_limit + 20
    assert burst_size < threshold, "la ráfaga de prueba debe seguir por debajo del umbral específico"
    statuses = [_post_whatsapp(client).status_code for _ in range(burst_size)]

    assert 429 not in statuses
    assert all(code == 200 for code in statuses)


def test_whatsapp_webhook_exceeding_specific_threshold_returns_429_with_retry_after(
    client, fake_queue_redis, fake_path_rate_limiter_redis
):
    """Exceder el umbral ESPECÍFICO real (300/min por defecto) -> 429 con
    `Retry-After`. El middleware general (60/min) ya NO dispara antes
    (exención verificada en `rate_limit_general.py`)."""
    threshold = _webhook_specific_threshold_per_minute()

    statuses = [_post_whatsapp(client).status_code for _ in range(threshold + 5)]

    assert 429 in statuses
    assert statuses[:threshold] == [200] * threshold
    assert statuses[threshold:] == [429] * 5

    last_response = _post_whatsapp(client)
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
    assert int(last_response.headers["Retry-After"]) > 0


def test_pbx_webhook_exceeding_specific_threshold_returns_429_before_signature_validation(
    client, fake_queue_redis, fake_path_rate_limiter_redis
):
    """Mismo criterio que WhatsApp, pero sobre el webhook del PBX — y
    explícitamente con firma INVÁLIDA para confirmar que el 429 se dispara
    ANTES de llegar a `_is_valid_signature` (si llegara a validarse, sería
    401, no 429)."""
    threshold = _webhook_specific_threshold_per_minute()

    for _ in range(threshold):
        response = _post_pbx(client, signed=True)
        assert response.status_code == 202

    # Firma deliberadamente inválida: si el rate-limit no disparara antes,
    # esto sería 401 (firma incorrecta), no 429.
    response = _post_pbx(client, signed=False)
    assert response.status_code == 429
    assert "Retry-After" in response.headers


# ---------------------------------------------------------------------------
# (c) El contador ESPECÍFICO por endpoint es independiente por scope —
#     aislado del general (monkeypatch del límite general a un valor que
#     esta prueba nunca alcanza, para ejercer SOLO `PathRateLimiter`).
# ---------------------------------------------------------------------------


def test_pbx_and_whatsapp_specific_rate_limits_are_independent_scopes(
    fake_path_rate_limiter_redis,
):
    """El contador ESPECÍFICO de WhatsApp y el del PBX son independientes
    (distinto `scope` namespaced) aunque ambos compartan la misma IP de
    origen — ejercido DIRECTAMENTE sobre `PathRateLimiter` (sin pasar por
    HTTP/middleware general) para aislar el comportamiento documentado en
    el HALLAZGO de este módulo (el middleware general interfiere si se
    ejercita vía `TestClient`).
    """
    from starlette.requests import Request

    def _fake_request() -> Request:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/fake",
            "client": ("203.0.113.10", 12345),
            "headers": [],
        }
        return Request(scope)

    whatsapp_limiter = rate_limit_general_module.whatsapp_webhook_rate_limiter
    pbx_limiter = rate_limit_general_module.pbx_webhook_rate_limiter
    threshold = whatsapp_limiter.max_requests

    # Agotar el contador de WhatsApp para esta IP...
    for _ in range(threshold):
        whatsapp_limiter(_fake_request())
    with pytest.raises(Exception) as exc_info:
        whatsapp_limiter(_fake_request())
    assert "429" in str(exc_info.value) or getattr(
        exc_info.value, "status_code", None
    ) == 429

    # ...no debe afectar al contador del PBX (scope distinto), que sigue
    # intacto para la MISMA IP.
    pbx_limiter(_fake_request())  # no debe lanzar


# ---------------------------------------------------------------------------
# (d) Rate-limit GENERAL (capa transversal, slowapi/default_limits)
# ---------------------------------------------------------------------------


def test_general_default_rate_limit_applies_to_plain_rest_endpoint(client):
    """RF-01: el límite GENERAL por defecto cubre CUALQUIER endpoint REST,
    no solo los 3 con límite específico — se ejercita sobre `/healthz`
    (sin auth, sin Postgres) para no acoplar el test a RLS/JWT.

    En este sandbox sin Redis real, `slowapi` cae a su fallback en memoria
    de proceso (`in_memory_fallback_enabled=True`, documentado en
    `rate_limit_general.py`) — el comportamiento observable (429 al exceder
    `default_limits`) es el mismo que con Redis real para el propósito de
    este test."""
    default_limit = rate_limit_general_module.DEFAULT_RATE_LIMIT
    per_minute = int(default_limit.split("/")[0])

    statuses = [client.get("/healthz").status_code for _ in range(per_minute + 10)]

    assert 429 in statuses
    assert statuses[:per_minute].count(200) == per_minute


def test_general_default_rate_limit_does_not_block_legitimate_low_volume_traffic(
    client,
):
    """Ráfaga pequeña y legítima (un agente humano navegando la SPA) nunca
    debe recibir 429 — contador limpio garantizado por el fixture
    `_reset_general_rate_limiter_storage` (autouse)."""
    small_burst = 5

    statuses = [client.get("/healthz").status_code for _ in range(small_burst)]

    assert all(code == 200 for code in statuses)
    assert 429 not in statuses


# ---------------------------------------------------------------------------
# (e) Coexistencia con `LoginRateLimiter` (SPEC-013) — evidencia conjunta
# ---------------------------------------------------------------------------


def test_login_rate_limiter_still_operates_independently_of_general_layer(
    client, monkeypatch
):
    """Re-ejecuta el criterio de `test_login_rate_limited_returns_429`
    (`tests/test_auth_api.py`, SPEC-013) EN ESTE MÓDULO, junto a las pruebas
    del rate-limit general, para dejar evidencia explícita de
    RNF-COEXISTENCIA: el login está exento del middleware general
    (`limiter._exempt_routes`, ver `rate_limit_general.py`) y su propio
    `Retry-After` (calculado por `LoginRateLimiter`/SPEC-013) NO es
    sobrescrito por el middleware transversal."""
    import app.api.auth as auth_router_module
    from app.services import auth_service

    def fake_authenticate(db, *, tenant_slug, email, password):
        raise auth_service.RateLimitedError(retry_after_seconds=42)

    monkeypatch.setattr(auth_router_module, "authenticate", fake_authenticate)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "tenant-a",
            "email": "agente@tenant-a.test",
            "password": "cualquiera",
        },
    )

    assert response.status_code == 429
    # El Retry-After de 42s es el calculado por SPEC-013/LoginRateLimiter;
    # si el middleware general lo pisara con el suyo (ventana del default
    # general, p.ej. 60s), este assert fallaría — confirma la exención.
    assert response.headers.get("Retry-After") == "42"
