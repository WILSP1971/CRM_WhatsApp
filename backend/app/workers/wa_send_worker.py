"""Worker de envío saliente por WhatsApp — consume `wa:outbound` — SPEC-029
(F4), ADR-006.

`process_job` procesa UN job ya encolado (`OutboundSendJob`,
`app.core.whatsapp_outbound_queue`) DESPUÉS de que el agente humano aprobó
el borrador (SPEC-019, `draft_review_service.approve_and_send` +
`approve_draft_endpoint`, único encolador — ver `app/api/rag.py`):

  1. Relee el `Message` bajo RLS (fijando `app.tenant_id` al `tenant_id`
     DECLARADO por el job, mismo criterio de defensa en profundidad que
     `sentiment_worker`/`whatsapp_inbound_worker`: si el mensaje no
     pertenece a ese tenant, se descarta sin enviar).
  2. Idempotencia (RF-04): si el mensaje YA tiene `wamid` persistido
     (reintento de un job duplicado, redelivery), es no-op — NUNCA se
     reenvía un mensaje que ya tiene confirmación de Meta.
  3. Resuelve el `phone_number_id` (número emisor del tenant,
     `whatsapp_accounts` activo) y el `to` (número del contacto de la
     conversación).
  4. Detecta la ventana de servicio de 24 h (RF-03): busca el último mensaje
     ENTRANTE (`remitente == "contacto"`) de la conversación. Dentro de la
     ventana -> texto libre (`send_text_message`); fuera de ventana -> exige
     ≥1 plantilla HSM utilitaria configurada (`Settings.whatsapp_template_
     name`); sin plantilla configurada, el envío se BLOQUEA con motivo
     explícito (estado `failed`, sin intentar la Graph API).
  5. Llama a `app.integrations.whatsapp.graph_client` (ÚNICO módulo con
     egress hacia la Graph API de Meta, allowlist ADR-006) — este worker
     NUNCA importa `httpx` directamente (auditado por
     `check-externos-backend.sh`, verificación 9: los módulos de
     `app/workers` no deben importar `httpx`; el transporte real vive
     exclusivamente en `app/integrations/whatsapp/`).
  6. Persiste el `wamid` devuelto por Meta y mantiene `estado_entrega`
     (RF-01); ante error transitorio agotado (429/5xx, RF-04) o ventana
     bloqueada sin plantilla, persiste `estado_entrega="failed"` (ver
     `ESTADOS_ENTREGA_ENVIO_VALIDOS` — extiende, no reemplaza, el vocabulario
     de SPEC-015/025).

FUERA DE ALCANCE de este worker: procesar los `statuses` de confirmación de
entrega/lectura de Meta (SPEC-030, callbacks) y cualquier indicador de UI
(SPEC-031). Este worker solo hace el ENVÍO inicial y su resultado inmediato
(enviado/failed).

CHECKPOINT SENSIBLE (RNF-01/RF-02 SPEC-029, ADR-006): este módulo NUNCA
importa `app.services.rag`/`app.services.ai_service` ni genera contenido —
el texto que se envía es EXACTAMENTE `message.contenido`, ya aprobado por un
humano y persistido antes de que este worker exista como job.
"""

from __future__ import annotations

import asyncio
import signal
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

import redis.asyncio as redis_asyncio
import sqlalchemy as sa
import structlog
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redis_client import get_redis_client
from app.core.whatsapp_outbound_queue import (
    OUTBOUND_QUEUE_KEY,
    OutboundSendJob,
    dequeue_outbound_send,
)
from app.core.worker_resilience import resilient_worker_loop
from app.db.session import SessionLocal, set_tenant_session
from app.integrations.whatsapp.graph_client import (
    GraphApiClient,
    GraphApiError,
    GraphApiHostError,
    GraphApiTransientError,
)
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.message import ESTADO_ENTREGA_FAILED, Message
from app.models.whatsapp_account import WhatsappAccount

logger = structlog.get_logger(__name__)

_REMITENTE_CONTACTO = "contacto"


class OutboundConfigurationError(RuntimeError):
    """Falta configuración imprescindible para enviar (número emisor,
    plantilla) — se registra como `failed`, nunca se intenta la Graph API
    con datos incompletos."""


class WindowBlockedError(RuntimeError):
    """Fuera de la ventana de 24 h y sin plantilla HSM configurada (RF-03):
    el envío se bloquea con motivo, sin intentar la Graph API."""


def _resolve_phone_number_id(db: Session, *, tenant_id: uuid.UUID) -> str | None:
    """Número EMISOR (cuenta de WhatsApp Business del tenant, SPEC-025).

    Prioriza la cuenta activa registrada en `whatsapp_accounts`; si el
    tenant no tiene ninguna (entorno de un solo número por variable de
    entorno), cae al fallback `Settings.whatsapp_phone_number_id`.
    """
    account = db.scalar(
        sa.select(WhatsappAccount).where(WhatsappAccount.activo.is_(True)).limit(1)
    )
    if account is not None:
        return account.phone_number_id
    return get_settings().whatsapp_phone_number_id


def _resolve_recipient(db: Session, *, contact_id: uuid.UUID) -> str | None:
    """Número RECEPTOR (`wa_id` del contacto, reutilizado como
    `Contact.telefono` — mismo criterio que `whatsapp_inbound_worker`)."""
    contact = db.get(Contact, contact_id)
    if contact is None or not contact.activo:
        return None
    return contact.telefono


def _last_inbound_message_at(
    db: Session, *, conversation_id: uuid.UUID
) -> datetime | None:
    """Timestamp del ÚLTIMO mensaje ENTRANTE de la conversación (base de la
    ventana de 24 h, RF-03): la ventana de servicio de WhatsApp se mide
    desde el último mensaje del CONTACTO, no desde el último saliente."""
    return db.scalar(
        sa.select(sa.func.max(Message.created_at)).where(
            Message.conversation_id == conversation_id,
            Message.remitente == _REMITENTE_CONTACTO,
        )
    )


def _within_service_window(last_inbound_at: datetime | None) -> bool:
    """RF-03: dentro de la ventana -> texto libre; sin mensaje entrante
    previo (conversación iniciada por el agente, caso raro) se trata como
    FUERA de ventana (fail-closed: exige plantilla en vez de asumir texto
    libre sin evidencia de una sesión abierta por el contacto)."""
    if last_inbound_at is None:
        return False
    if last_inbound_at.tzinfo is None:
        last_inbound_at = last_inbound_at.replace(tzinfo=timezone.utc)
    window = timedelta(hours=get_settings().whatsapp_session_window_hours)
    return datetime.now(timezone.utc) - last_inbound_at <= window


def _mark_failed(db: Session, message: Message) -> None:
    # Reutiliza el mismo campo `estado_entrega` que SPEC-015/025 (ver
    # `app/models/message.py`): `failed` es un estado TERMINAL propio del
    # transporte de envío (RF-04), no participa de la progresión monotónica
    # enviado -> entregado -> leido de los callbacks de SPEC-030.
    message.estado_entrega = ESTADO_ENTREGA_FAILED
    db.flush()


def process_job(
    job: OutboundSendJob,
    *,
    session_factory: Callable[[], Session] | None = None,
    graph_client: GraphApiClient | None = None,
) -> None:
    """Procesa un job de envío ya extraído de `wa:outbound`.

    `session_factory`/`graph_client` son SOLO para pruebas (inyectan una
    `Session` de test / un doble del cliente Graph en vez de instancias
    reales — NUNCA se hace una llamada de red real en los tests unitarios de
    este worker).
    """
    db = (session_factory or SessionLocal)()
    try:
        try:
            tenant_id = uuid.UUID(job.tenant_id)
            conversation_id = uuid.UUID(job.conversation_id)
            message_id = uuid.UUID(job.message_id)
        except ValueError:
            logger.error(
                "whatsapp_outbound_job_invalid_ids",
                job_id=job.job_id,
                tenant_id=job.tenant_id,
            )
            return

        with db.begin():
            set_tenant_session(db, str(tenant_id))

            message = db.get(Message, message_id)
            if message is None or not message.activo:
                logger.warning(
                    "whatsapp_outbound_message_not_found_or_inactive",
                    job_id=job.job_id,
                    message_id=job.message_id,
                    tenant_id=job.tenant_id,
                )
                return

            if message.wamid:
                # RF-04 idempotencia: reintento/redelivery de un envío ya
                # confirmado por Meta -> no-op, JAMÁS reenviar.
                logger.info(
                    "whatsapp_outbound_already_sent_skipped",
                    job_id=job.job_id,
                    message_id=job.message_id,
                    wamid=message.wamid,
                )
                return

            conversation = db.get(Conversation, conversation_id)
            if conversation is None or not conversation.activo:
                logger.warning(
                    "whatsapp_outbound_conversation_not_found_or_inactive",
                    job_id=job.job_id,
                    conversation_id=job.conversation_id,
                )
                return

            try:
                phone_number_id = _resolve_phone_number_id(db, tenant_id=tenant_id)
                if not phone_number_id:
                    raise OutboundConfigurationError(
                        "sin phone_number_id configurado para el tenant"
                    )

                to = _resolve_recipient(db, contact_id=conversation.contact_id)
                if not to:
                    raise OutboundConfigurationError(
                        "contacto sin número de WhatsApp (telefono) o inactivo"
                    )

                last_inbound_at = _last_inbound_message_at(
                    db, conversation_id=conversation_id
                )
                settings = get_settings()
                client = graph_client or GraphApiClient()

                if _within_service_window(last_inbound_at):
                    result = client.send_text_message(
                        phone_number_id=phone_number_id,
                        to=to,
                        text=message.contenido,
                        idempotency_key=str(message.id),
                    )
                else:
                    if not settings.whatsapp_template_name:
                        raise WindowBlockedError(
                            "fuera de ventana de 24h y sin plantilla HSM "
                            "utilitaria configurada (WHATSAPP_TEMPLATE_NAME)"
                        )
                    result = client.send_template_message(
                        phone_number_id=phone_number_id,
                        to=to,
                        template_name=settings.whatsapp_template_name,
                        language_code=settings.whatsapp_template_language,
                        idempotency_key=str(message.id),
                    )
            except (
                OutboundConfigurationError,
                WindowBlockedError,
                GraphApiError,
                GraphApiHostError,
                GraphApiTransientError,
            ) as exc:
                logger.error(
                    "whatsapp_outbound_send_failed",
                    job_id=job.job_id,
                    message_id=job.message_id,
                    conversation_id=job.conversation_id,
                    error_type=type(exc).__name__,
                )
                _mark_failed(db, message)
                return

            message.wamid = result.wamid
            db.flush()

        logger.info(
            "whatsapp_outbound_sent",
            job_id=job.job_id,
            message_id=job.message_id,
            conversation_id=job.conversation_id,
        )
    finally:
        db.close()


async def drain_one(
    redis_client: redis_asyncio.Redis,
    *,
    timeout_seconds: int = 0,
    session_factory: Callable[[], Session] | None = None,
    graph_client: GraphApiClient | None = None,
) -> bool:
    """Extrae y procesa UN único job pendiente de `wa:outbound`.

    Devuelve `True` si procesó un job, `False` si la cola estaba vacía.
    """
    job = await dequeue_outbound_send(redis_client, timeout_seconds=timeout_seconds)
    if job is None:
        return False
    process_job(job, session_factory=session_factory, graph_client=graph_client)
    return True


async def run_worker_loop(
    redis_client: redis_asyncio.Redis | None = None,
    *,
    block_timeout_seconds: int = 5,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Loop principal del proceso worker (`wa_send_worker` en
    docker-compose). Consume `wa:outbound` con `BLPOP` (bloqueante, sin
    busy-waiting), mismo patrón que `whatsapp_inbound_worker`.

    Hardening (SPEC-032, deuda SPEC-027/BLACK PANTHER, extendido a este
    worker de envío por el mismo criterio): cada iteración corre envuelta en
    `resilient_worker_loop` — ante una caída transitoria de Redis/Postgres,
    se loguea y se espera backoff exponencial en vez de dejar morir el
    proceso (evita crash-loop de `restart: unless-stopped`).
    """
    redis_client = redis_client or get_redis_client()
    stop_event = stop_event or asyncio.Event()

    async def _iteration() -> None:
        await drain_one(redis_client, timeout_seconds=block_timeout_seconds)

    logger.info("wa_send_worker_started", queue=OUTBOUND_QUEUE_KEY)
    await resilient_worker_loop(
        _iteration, stop_event=stop_event, worker_name="wa_send_worker"
    )
    logger.info("wa_send_worker_stopped")


def _run_forever_with_signal_handling() -> None:
    """Punto de entrada del proceso worker independiente (`python -m
    app.workers.wa_send_worker`), usado por el servicio `wa_send_worker` de
    `docker-compose.yml`. Se apaga limpiamente ante SIGTERM/SIGINT."""

    async def _main() -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)
        await run_worker_loop(stop_event=stop_event)

    asyncio.run(_main())


if __name__ == "__main__":
    _run_forever_with_signal_handling()
