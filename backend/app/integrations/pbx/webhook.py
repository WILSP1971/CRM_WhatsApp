"""Webhook de ingesta de grabaciones del PBX — SPEC-037, ADR-007/ADR-010.

Replica EXACTAMENTE el patrón de `app/integrations/whatsapp/webhook.py`
(SPEC-026/027): ACK rápido + validación de firma ANTES de cualquier
persistencia + encolado asíncrono. Montado en `app/main.py` SIN el prefijo
`/api/v1` (a diferencia del resto de la API) porque el `Caddyfile` (SPEC-035)
expone el path EXACTO `/webhooks/pbx/recordings` tras el reverse proxy TLS,
sin reescritura — es el único path público que Caddy reenvía a `api:8000`.

- `POST /webhooks/pbx/recordings`: recibe `multipart/form-data` con el
  fichero de audio (`file`, WAV/OGG) + metadatos (`call_id`, `numero`,
  `numero_destino`, `direccion`, `duracion` opcional). Valida
  `X-Webhook-Signature-256` (HMAC-SHA256 sobre el fichero de audio crudo con
  `WEBHOOK_SECRET`, comparación en tiempo constante — mismo criterio que
  `WHATSAPP_APP_SECRET`/SPEC-026). Sin firma o firma inválida -> **401**, SIN
  encolar. Con firma válida -> encola `{audio, metadatos}` en
  `pbx:recordings:inbound` y responde **202 Accepted** de inmediato
  (RNF-02): el guardado del audio, la resolución de tenant, el dedup por
  `call_id` y la creación de `Call` son responsabilidad exclusiva del
  `recording_ingest_worker` (SPEC-037), NUNCA de este módulo.
- `GET /webhooks/pbx/recordings`: challenge de verificación opcional (si el
  PBX/proveedor lo soporta, análogo al challenge de Meta): valida
  `verify_token` (query param) contra `WEBHOOK_VERIFY_TOKEN` y responde el
  `challenge` recibido en texto plano si coincide; si no, 403.

FUERA DE ALCANCE de este módulo (delegado a `recording_ingest_worker.py`):
dedup por `call_id`, resolución `numero_destino -> tenant_id`, fijado de RLS,
almacenamiento del audio cifrado y cualquier escritura en Postgres. Este
endpoint NO ejecuta IA ni SQL (criterio de aceptación SPEC-037): solo valida
+ encola.

CHECKPOINT SENSIBLE / ADR-010: este archivo RECIBE (egress cero); nunca
descarga del host del PBX (eso, solo si el PBX es externo, es
`app/services/telefonia/pbx_client.py` + `recording_fetch_worker.py`). Vive
en `app/integrations/pbx/` (módulo de transporte de RECEPCIÓN del canal, no
de descarga), consistente con la organización ya usada por WhatsApp.

CHECKPOINT C3: `WEBHOOK_SECRET`/`WEBHOOK_VERIFY_TOKEN` se leen
EXCLUSIVAMENTE de `Settings` (env, fail-fast fuera de development). Ninguno
de los dos, ni el header de firma recibido, se escribe jamás en logs.
"""

from __future__ import annotations

import hashlib
import hmac

import redis.asyncio as redis_asyncio
import structlog
from fastapi import APIRouter, Depends, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import PlainTextResponse

from app.core.config import Settings, get_settings
from app.core.recording_queue import (
    build_recording_inbound_job,
    enqueue_recording_inbound_event,
)
from app.core.redis_client import get_redis_client

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks/pbx", tags=["PBX Recordings"])

_SIGNATURE_HEADER = "X-Webhook-Signature-256"
_SIGNATURE_PREFIX = "sha256="

# Direcciones/campos aceptados a nivel de transporte — la validación de forma
# completa (valores permitidos, `call_id` no vacío) es responsabilidad del
# worker de ingesta (SPEC-037); aquí solo se exige lo mínimo para no encolar
# basura evidente sin tocar Postgres.
_DIRECCIONES_VALIDAS = {"entrante", "saliente"}


@router.get("/recordings")
async def verify_webhook_challenge(
    verify_token: str | None = Query(default=None),
    challenge: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Challenge de verificación opcional del webhook de grabaciones (si el
    PBX/proveedor lo soporta). `verify_token` debe coincidir (comparación en
    tiempo constante) con `WEBHOOK_VERIFY_TOKEN`; si es válido, se devuelve
    `challenge` en texto plano; si no, 403 sin filtrar detalle."""
    token_valido = verify_token is not None and hmac.compare_digest(
        verify_token, settings.webhook_verify_token
    )

    if token_valido and challenge is not None:
        logger.info("pbx_webhook_challenge_ok")
        return PlainTextResponse(content=challenge, status_code=status.HTTP_200_OK)

    logger.warning("pbx_webhook_challenge_rejected")
    return PlainTextResponse(content="Forbidden", status_code=status.HTTP_403_FORBIDDEN)


def _is_valid_signature(
    *, raw_audio: bytes, header_value: str | None, webhook_secret: str
) -> bool:
    """HMAC-SHA256 del fichero de audio crudo con `webhook_secret`,
    comparación en tiempo constante (mismo criterio que
    `whatsapp/webhook.py::_is_valid_signature`, SPEC-026). Nunca hace
    early-return por diferencia de bytes: calcula un digest y compara incluso
    cuando el header viene ausente/mal formado, para no introducir una rama
    de timing distinta."""
    if not header_value or not header_value.startswith(_SIGNATURE_PREFIX):
        expected = hmac.new(
            webhook_secret.encode("utf-8"), raw_audio, hashlib.sha256
        ).hexdigest()
        hmac.compare_digest("", expected)
        return False

    received_hex = header_value.removeprefix(_SIGNATURE_PREFIX)
    expected_hex = hmac.new(
        webhook_secret.encode("utf-8"), raw_audio, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(received_hex, expected_hex)


@router.post("/recordings", status_code=status.HTTP_202_ACCEPTED)
async def receive_recording_webhook(
    request: Request,
    file: UploadFile,
    call_id: str = Form(...),
    numero: str = Form(...),
    numero_destino: str = Form(...),
    direccion: str = Form(...),
    duracion: int | None = Form(default=None),
    settings: Settings = Depends(get_settings),
    redis_client: redis_asyncio.Redis = Depends(get_redis_client),
) -> Response:
    """RF-01 (SPEC-037): recibe fichero + metadatos, valida firma sobre el
    audio crudo y hace ACK rápido (202 Accepted).

    Lee `file` (bytes EXACTOS del fichero) porque la firma HMAC se calcula
    sobre esos bytes tal cual — igual criterio que el webhook de WhatsApp
    (SPEC-026), que firma el RAW body en vez de una re-serialización.

    Sin firma o firma inválida -> 401, SIN encolar. Dirección fuera de
    `{"entrante", "saliente"}` -> 422 (validación mínima de transporte, sin
    tocar Postgres). Con firma válida -> encola audio + metadatos en
    `pbx:recordings:inbound` y responde 202 de inmediato, sin dedup/
    resolución de tenant/persistencia (eso es `recording_ingest_worker`,
    SPEC-037).
    """
    audio_bytes = await file.read()
    signature_header = request.headers.get(_SIGNATURE_HEADER)

    if not _is_valid_signature(
        raw_audio=audio_bytes,
        header_value=signature_header,
        webhook_secret=settings.webhook_secret,
    ):
        logger.warning(
            "pbx_webhook_signature_rejected",
            has_signature_header=signature_header is not None,
            audio_length=len(audio_bytes),
            call_id=call_id,
        )
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    if direccion not in _DIRECCIONES_VALIDAS:
        logger.warning(
            "pbx_webhook_invalid_direccion_rejected",
            direccion=direccion,
            call_id=call_id,
        )
        return Response(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    job = build_recording_inbound_job(
        call_id=call_id,
        numero=numero,
        numero_destino=numero_destino,
        direccion=direccion,
        audio_bytes=audio_bytes,
        duracion=duracion,
        content_type=file.content_type or "audio/wav",
    )

    # Hardening (mismo criterio que whatsapp/webhook.py, SPEC-032): si Redis
    # no está disponible, se responde 503 explícito (en vez de 500 genérico)
    # para que el PBX reintente la entrega por su propio mecanismo, sin
    # filtrar detalle del error interno ni el secreto de firma (C3).
    try:
        await enqueue_recording_inbound_event(redis_client, job=job)
    except Exception:  # noqa: BLE001 — Redis caído/timeout u otro fallo infra
        logger.error(
            "pbx_webhook_enqueue_failed",
            call_id=call_id,
            audio_length=len(audio_bytes),
            exc_info=True,
        )
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    logger.info(
        "pbx_webhook_recording_enqueued",
        call_id=call_id,
        event_id=job.event_id,
        audio_length=len(audio_bytes),
    )

    return Response(status_code=status.HTTP_202_ACCEPTED)
