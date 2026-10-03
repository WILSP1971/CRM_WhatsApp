"""Webhook de Instagram Direct Messages (Meta Graph API) — SPEC-086 (F1),
espejo EXACTO de `app.integrations.whatsapp.webhook` (SPEC-026).

Implementa EXCLUSIVAMENTE lo que corresponde a SPEC-086:

- `GET /api/v1/instagram/webhook`: challenge de suscripción de Meta. Valida
  `hub.mode=subscribe` y `hub.verify_token == INSTAGRAM_VERIFY_TOKEN`; si es
  válido, responde `hub.challenge` en texto plano; si no, **403**.
- `POST /api/v1/instagram/webhook`: valida la firma `X-Hub-Signature-256`
  (HMAC-SHA256 sobre el RAW body con `INSTAGRAM_APP_SECRET`, comparación en
  tiempo constante). Si falta o no coincide -> **401**, sin procesar. Si es
  válida, **encola** el payload crudo en `ig:inbound`
  (`app.core.instagram_queue`) y responde **200 de inmediato** (RNF-ACK, ACK
  p95 <= 500 ms). Si el encolado falla (Redis no disponible/timeout) responde
  **503** controlado en vez de un 500 sin distinción, para que Meta
  reintente la entrega por el mecanismo esperado (mismo hardening que
  SPEC-032 aplicó a WhatsApp).

FUERA DE ALCANCE de este módulo (delegado a SPEC-087): resolución de tenant
(`instagram_business_account_id -> tenant_id`), fijado de RLS, idempotencia
por `mid`, y cualquier escritura en Postgres. Este endpoint NO ejecuta IA ni
SQL pesado (criterio de aceptación SPEC-086): solo valida + encola.

CHECKPOINT SENSIBLE / allowlist por ruta: este archivo RECIBE (egress
cero); nunca llama a `graph.facebook.com` (eso es el envío saliente, fuera
de alcance de esta SPEC). Vive dentro de `app/integrations/instagram/`
únicamente para respetar la organización del módulo de transporte del canal
(allowlist por ruta de `check-externos-backend.sh`), no porque llame a la
Graph API.

CHECKPOINT C3: `INSTAGRAM_APP_SECRET`/`INSTAGRAM_VERIFY_TOKEN` se leen
EXCLUSIVAMENTE de `Settings` (env, fail-fast fuera de development). Ninguno
de los dos, ni el header de firma recibido, se escribe jamás en logs.
"""

from __future__ import annotations

import hashlib
import hmac

import redis.asyncio as redis_asyncio
import structlog
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.core.config import Settings, get_settings
from app.core.instagram_queue import enqueue_inbound_instagram_event
from app.core.rate_limit_general import instagram_webhook_rate_limiter
from app.core.redis_client import get_redis_client

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/instagram", tags=["Instagram"])

_SIGNATURE_HEADER = "X-Hub-Signature-256"
_SIGNATURE_PREFIX = "sha256="


@router.get("/webhook")
async def verify_webhook_challenge(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    settings: Settings = Depends(get_settings),
) -> Response:
    """RF-01 (SPEC-086): challenge de suscripción del webhook de Meta.

    `hub.mode` debe ser `subscribe` y `hub.verify_token` debe coincidir
    (comparación en tiempo constante, igual criterio que la firma HMAC) con
    `INSTAGRAM_VERIFY_TOKEN`. Si es válido, se devuelve `hub.challenge` en
    texto plano (formato exigido por Meta); si no, 403 sin filtrar detalle.
    """
    token_valido = hub_verify_token is not None and hmac.compare_digest(
        hub_verify_token, settings.instagram_verify_token
    )

    if hub_mode == "subscribe" and token_valido and hub_challenge is not None:
        logger.info("instagram_webhook_challenge_ok")
        return PlainTextResponse(content=hub_challenge, status_code=status.HTTP_200_OK)

    logger.warning("instagram_webhook_challenge_rejected", hub_mode=hub_mode)
    return PlainTextResponse(content="Forbidden", status_code=status.HTTP_403_FORBIDDEN)


def _is_valid_signature(
    *, raw_body: bytes, header_value: str | None, app_secret: str
) -> bool:
    """HMAC-SHA256 del RAW body con `app_secret`, comparación en tiempo
    constante (RNF-TIMING/criterio de aceptación SPEC-086). Nunca hace
    early-return por diferencia de bytes: usa `hmac.compare_digest` tanto
    para la propia firma como para no filtrar por timing si el header viene
    ausente/mal formado.
    """
    if not header_value or not header_value.startswith(_SIGNATURE_PREFIX):
        # Igualmente calculamos un digest y comparamos contra una cadena
        # vacía firmada, para no introducir una rama de timing distinta
        # entre "header ausente" y "header con firma incorrecta".
        expected = hmac.new(
            app_secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        hmac.compare_digest("", expected)
        return False

    received_hex = header_value.removeprefix(_SIGNATURE_PREFIX)
    expected_hex = hmac.new(
        app_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(received_hex, expected_hex)


@router.post("/webhook")
async def receive_webhook_event(
    request: Request,
    settings: Settings = Depends(get_settings),
    redis_client: redis_asyncio.Redis = Depends(get_redis_client),
    _rate_limit: None = Depends(instagram_webhook_rate_limiter),
) -> Response:
    """RF-02/RF-03 (SPEC-086): valida firma sobre el RAW body y hace ACK
    rápido.

    CHECKPOINT (espejo de SPEC-081, R-105): rate-limit GENERAL por IP con
    umbral HOLGADO (`instagram_webhook_rate_limiter`, ver
    `app/core/rate_limit_general.py`), aplicado ANTES de validar la firma —
    una petición que excede el umbral recibe 429 sin tocar el cuerpo del
    endpoint; una petición dentro del umbral llega intacta a la validación
    HMAC/ACK rápido de abajo, sin ningún cambio de comportamiento. Aplicado
    vía `Depends()` (mismo patrón que WhatsApp).

    Lee `request.body()` (bytes EXACTOS recibidos) ANTES de cualquier parseo
    JSON, porque la firma de Meta se calcula sobre esos bytes tal cual — una
    re-serialización del JSON parseado podría diferir (orden de claves,
    espacios) e invalidar la comparación.

    Sin firma o firma inválida -> 401, SIN encolar (criterio de aceptación).
    Con firma válida -> encola el payload crudo en `ig:inbound` y responde
    200 de inmediato, sin resolución de tenant/persistencia (eso es
    SPEC-087).
    """
    raw_body: bytes = await request.body()
    signature_header = request.headers.get(_SIGNATURE_HEADER)

    if not _is_valid_signature(
        raw_body=raw_body,
        header_value=signature_header,
        app_secret=settings.instagram_app_secret,
    ):
        logger.warning(
            "instagram_webhook_signature_rejected",
            has_signature_header=signature_header is not None,
            body_length=len(raw_body),
        )
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    # Hardening (espejo de SPEC-032, hallazgo M-1 BLACK WIDOW SPEC-026): si
    # Redis no está disponible, el encolado lanzaría una excepción sin
    # capturar y FastAPI respondería 500 genérico — Meta interpreta
    # cualquier no-200 como fallo y reintenta con backoff propio, pero un
    # 500 sin distinción no le da la señal correcta de "reintenta más
    # tarde". Se responde 503 (Service Unavailable) explícito para que el
    # reintento de Meta sea la vía esperada de recuperación, sin filtrar
    # detalle del error interno ni el secreto de firma en la respuesta (C3).
    try:
        job = await enqueue_inbound_instagram_event(
            redis_client, raw_body=raw_body.decode("utf-8", errors="replace")
        )
    except (
        Exception
    ):  # noqa: BLE001 — Redis caído/timeout u otro fallo de infraestructura
        logger.error(
            "instagram_webhook_enqueue_failed",
            body_length=len(raw_body),
            exc_info=True,
        )
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    logger.info("instagram_webhook_event_enqueued", event_id=job.event_id)

    return Response(status_code=status.HTTP_200_OK)
