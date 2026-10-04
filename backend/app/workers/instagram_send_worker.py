"""Worker de envío saliente por Instagram DM — consume `ig:outbound` —
SPEC-089 (F4), ADR-006 ampliado. Espejo ESTRUCTURAL de
`app.workers.wa_send_worker` (SPEC-029/030) adaptado a la ventana de
mensajería PROPIA de Instagram (message tags, NO plantillas HSM, N-5).

`process_job` procesa UN job ya encolado (`InstagramOutboundSendJob`,
`app.core.instagram_outbound_queue`) DESPUÉS de que el agente humano aprobó
el borrador (SPEC-019, `draft_review_service.approve_and_send` +
`approve_draft_endpoint`, único encolador — ver `app/api/rag.py`):

  1. Relee el `Message` bajo RLS (fijando `app.tenant_id` al `tenant_id`
     DECLARADO por el job, mismo criterio de defensa en profundidad que
     `wa_send_worker`/`instagram_inbound_worker`: si el mensaje no pertenece
     a ese tenant, se descarta sin enviar).
  2. Idempotencia (RF-06): si el mensaje YA tiene un id de mensaje externo
     persistido (`message.wamid`, §3.4 — reutilizado para el `mid` de
     Instagram), es no-op — NUNCA se reenvía un mensaje que ya tiene
     confirmación de Meta.
  3. Resuelve el `instagram_business_account_id` (cuenta emisora del
     tenant, `instagram_accounts` activa) y el `recipient_id` (identificador
     de Instagram del contacto de la conversación, reutilizado en
     `Contact.telefono`, MISMO criterio que `instagram_inbound_worker`).
  4. Calcula la ventana de mensajería PROPIA de Instagram (RF-03,
     `_resolve_send_tag`): dentro de 24h -> sin tag; entre 24h y 7 días ->
     tag `HUMAN_AGENT` (uso legítimo porque el borrador YA fue aprobado por
     un agente humano real, nunca enviado por un sistema automatizado, y
     SOLO se aplica fuera de la ventana estándar — ver docstring de
     `_resolve_send_tag`); más de 7 días -> BLOQUEADO con motivo explícito,
     SIN intentar la Graph API (evita arriesgar un rechazo de Meta).
  5. Llama a `app.integrations.instagram.graph_client` (ÚNICO módulo con
     egress hacia la Graph API de Meta para este canal, allowlist ADR-006
     ampliado) — este worker NUNCA importa `httpx` directamente (auditado
     por `check-externos-backend.sh`, verificación 9).
  6. Persiste el `mid` devuelto por Meta en `message.wamid` (§3.4, columna
     genérica reutilizada) y mantiene `estado_entrega` (RF-05); ante error
     transitorio agotado (429/5xx, RF-04) o ventana bloqueada, persiste
     `estado_entrega="failed"` (mismo vocabulario que `wa_send_worker`,
     `ESTADO_ENTREGA_FAILED`).

FUERA DE ALCANCE de este worker: procesar los callbacks `delivery` de Meta
(SPEC-089 RF-05, ver `instagram_inbound_worker._process_delivery_event`,
que comparte la MISMA cola de ingesta `ig:inbound` donde llegan los
callbacks del webhook). Este worker solo hace el ENVÍO inicial y su
resultado inmediato (enviado/failed).

CHECKPOINT SENSIBLE (RNF-EGRESS-ACOTADO SPEC-089, ADR-006 ampliado): este
módulo NUNCA importa `app.services.rag`/`app.services.ai_service` ni genera
contenido — el texto que se envía es EXACTAMENTE `message.contenido`, ya
aprobado por un humano y persistido antes de que este worker exista como
job.

RNF-VENTANA-PROPIA (R-116, decisión de arquitecto fijada en SPEC-089, NO
reabrir): este worker NO reutiliza `send_template_message`/
`whatsapp_template_*`/`whatsapp_session_window_hours` de WhatsApp —
Instagram NO tiene plantillas HSM, usa message tags. `_resolve_send_tag`
implementa el mecanismo PROPIO de Instagram, aislado y testeable por
separado.
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
from app.core.instagram_outbound_queue import (
    OUTBOUND_QUEUE_KEY,
    InstagramOutboundSendJob,
    dequeue_outbound_send,
)
from app.core.redis_client import get_redis_client
from app.core.worker_resilience import resilient_worker_loop
from app.db.session import SessionLocal, set_tenant_session
from app.integrations.instagram.graph_client import (
    INSTAGRAM_HUMAN_AGENT_TAG,
    GraphApiClient,
    GraphApiError,
    GraphApiHostError,
    GraphApiTransientError,
)
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.instagram_account import InstagramAccount
from app.models.message import ESTADO_ENTREGA_FAILED, Message

logger = structlog.get_logger(__name__)

_REMITENTE_CONTACTO = "contacto"

# Ventanas de mensajería de Instagram (RF-03 SPEC-089, confirmado contra la
# documentación vigente de Meta — ver contexto de la SPEC): 24h estándar sin
# tag; hasta 7 días con el tag `HUMAN_AGENT` (uso legítimo SOLO porque el
# borrador ya fue aprobado por un humano, nunca un sistema automatizado);
# más de 7 días, bloqueado. Deliberadamente DISTINTAS de
# `Settings.whatsapp_session_window_hours` (WhatsApp): no se comparte la
# misma variable de configuración porque son mecanismos de plataforma
# diferentes (R-116) — hardcodeadas aquí como constantes de dominio, no
# como variables de entorno, porque no son un parámetro operativo ajustable
# sino un HECHO de la política de Meta para Instagram Messaging.
_STANDARD_WINDOW = timedelta(hours=24)
_HUMAN_AGENT_WINDOW = timedelta(days=7)


class OutboundConfigurationError(RuntimeError):
    """Falta configuración imprescindible para enviar (cuenta emisora,
    destinatario) — se registra como `failed`, nunca se intenta la Graph API
    con datos incompletos."""


class WindowBlockedError(RuntimeError):
    """Fuera de la ventana de mensajería de Instagram (>7 días desde el
    último mensaje del contacto, RF-03): el envío se bloquea con motivo, sin
    intentar la Graph API."""


def _resolve_send_tag(
    last_inbound_at: datetime | None, now: datetime
) -> str | None:
    """Resuelve el message tag de Instagram a aplicar al envío (RF-03,
    RNF-VENTANA-PROPIA) — función PURA y testeable por separado del worker.

    Reglas (ventana PROPIA de Instagram, confirmadas contra la documentación
    vigente de Meta; NO HSM, NO reutiliza la lógica de WhatsApp — R-116):

    - Sin mensaje entrante previo del contacto (`last_inbound_at is None`,
      conversación iniciada por el agente, caso raro): se trata como FUERA
      de ventana por completo (fail-closed, mismo criterio que
      `wa_send_worker._within_service_window` para WhatsApp) -> lanza
      `WindowBlockedError`.
    - `now - last_inbound_at <= 24h`: ventana ESTÁNDAR -> devuelve `None`
      (el tag se OMITE del body, texto libre sin restricción de uso).
    - `24h < now - last_inbound_at <= 7 días`: ventana EXTENDIDA -> devuelve
      `INSTAGRAM_HUMAN_AGENT_TAG` ("HUMAN_AGENT"). Uso LEGÍTIMO conforme a
      la política de Meta (confirmado en el contexto de SPEC-089): el envío
      ocurre DESPUÉS de que un agente humano real aprobó el borrador
      (SPEC-019, invariante duro de este worker — nunca hay autoenvío), y es
      para dar seguimiento a un caso de soporte en curso (el contacto ya
      escribió, hay una conversación abierta), nunca marketing/promoción.
    - `now - last_inbound_at > 7 días`: fuera de CUALQUIER ventana soportada
      por Instagram -> lanza `WindowBlockedError` (NO se intenta la Graph
      API, evita arriesgar un rechazo/sanción de Meta por mal uso del tag).
    """
    if last_inbound_at is None:
        raise WindowBlockedError(
            "sin mensaje entrante previo del contacto: no hay evidencia de "
            "una ventana de mensajería abierta (fail-closed)"
        )
    if last_inbound_at.tzinfo is None:
        last_inbound_at = last_inbound_at.replace(tzinfo=timezone.utc)

    elapsed = now - last_inbound_at
    if elapsed <= _STANDARD_WINDOW:
        return None
    if elapsed <= _HUMAN_AGENT_WINDOW:
        return INSTAGRAM_HUMAN_AGENT_TAG
    raise WindowBlockedError(
        f"fuera de toda ventana de mensajería de Instagram (>{_HUMAN_AGENT_WINDOW.days} "
        "días desde el último mensaje del contacto): Meta rechazaría el envío, "
        "ningún message tag cubre este caso"
    )


def _resolve_instagram_business_account_id(
    db: Session, *, tenant_id: uuid.UUID
) -> str | None:
    """Cuenta EMISORA (Instagram Business del tenant, SPEC-085).

    Prioriza la cuenta activa registrada en `instagram_accounts`; si el
    tenant no tiene ninguna (entorno de una sola cuenta por variable de
    entorno), cae al fallback `Settings.instagram_business_account_id`."""
    account = db.scalar(
        sa.select(InstagramAccount)
        .where(InstagramAccount.activo.is_(True))
        .limit(1)
    )
    if account is not None:
        return account.instagram_business_account_id
    return get_settings().instagram_business_account_id


def _resolve_recipient(db: Session, *, contact_id: uuid.UUID) -> str | None:
    """Identificador RECEPTOR (id de Instagram del contacto, reutilizado
    como `Contact.telefono` — mismo criterio que `instagram_inbound_worker`
    al crear el contacto por `sender_id`)."""
    contact = db.get(Contact, contact_id)
    if contact is None or not contact.activo:
        return None
    return contact.telefono


def _last_inbound_message_at(
    db: Session, *, conversation_id: uuid.UUID
) -> datetime | None:
    """Timestamp del ÚLTIMO mensaje ENTRANTE de la conversación (base de la
    ventana de mensajería, RF-03): la ventana de Instagram se mide desde el
    último mensaje del CONTACTO, no desde el último saliente."""
    return db.scalar(
        sa.select(sa.func.max(Message.created_at)).where(
            Message.conversation_id == conversation_id,
            Message.remitente == _REMITENTE_CONTACTO,
        )
    )


def _mark_failed(db: Session, message: Message) -> None:
    # Reutiliza el mismo campo `estado_entrega` que WhatsApp (SPEC-015/025,
    # ver `app/models/message.py`): `failed` es un estado TERMINAL propio
    # del transporte de envío (RF-04), no participa de la progresión
    # monotónica enviado -> entregado -> leido de los callbacks de
    # `instagram_inbound_worker._process_delivery_event`.
    message.estado_entrega = ESTADO_ENTREGA_FAILED
    db.flush()


def process_job(
    job: InstagramOutboundSendJob,
    *,
    session_factory: Callable[[], Session] | None = None,
    graph_client: GraphApiClient | None = None,
) -> None:
    """Procesa un job de envío ya extraído de `ig:outbound`.

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
                "instagram_outbound_job_invalid_ids",
                job_id=job.job_id,
                tenant_id=job.tenant_id,
            )
            return

        with db.begin():
            set_tenant_session(db, str(tenant_id))

            message = db.get(Message, message_id)
            if message is None or not message.activo:
                logger.warning(
                    "instagram_outbound_message_not_found_or_inactive",
                    job_id=job.job_id,
                    message_id=job.message_id,
                    tenant_id=job.tenant_id,
                )
                return

            if message.wamid:
                # RF-06 idempotencia: reintento/redelivery de un envío ya
                # confirmado por Meta -> no-op, JAMÁS reenviar.
                logger.info(
                    "instagram_outbound_already_sent_skipped",
                    job_id=job.job_id,
                    message_id=job.message_id,
                    mid=message.wamid,
                )
                return

            conversation = db.get(Conversation, conversation_id)
            if conversation is None or not conversation.activo:
                logger.warning(
                    "instagram_outbound_conversation_not_found_or_inactive",
                    job_id=job.job_id,
                    conversation_id=job.conversation_id,
                )
                return

            try:
                instagram_business_account_id = (
                    _resolve_instagram_business_account_id(db, tenant_id=tenant_id)
                )
                if not instagram_business_account_id:
                    raise OutboundConfigurationError(
                        "sin instagram_business_account_id configurado para el tenant"
                    )

                recipient_id = _resolve_recipient(
                    db, contact_id=conversation.contact_id
                )
                if not recipient_id:
                    raise OutboundConfigurationError(
                        "contacto sin identificador de Instagram o inactivo"
                    )

                last_inbound_at = _last_inbound_message_at(
                    db, conversation_id=conversation_id
                )
                tag = _resolve_send_tag(last_inbound_at, datetime.now(timezone.utc))

                client = graph_client or GraphApiClient()
                result = client.send_message(
                    instagram_business_account_id=instagram_business_account_id,
                    recipient_id=recipient_id,
                    text=message.contenido,
                    idempotency_key=str(message.id),
                    tag=tag,
                )
            except (
                OutboundConfigurationError,
                WindowBlockedError,
                GraphApiError,
                GraphApiHostError,
                GraphApiTransientError,
            ) as exc:
                logger.error(
                    "instagram_outbound_send_failed",
                    job_id=job.job_id,
                    message_id=job.message_id,
                    conversation_id=job.conversation_id,
                    error_type=type(exc).__name__,
                )
                _mark_failed(db, message)
                return

            message.wamid = result.mid
            db.flush()

        logger.info(
            "instagram_outbound_sent",
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
    """Extrae y procesa UN único job pendiente de `ig:outbound`.

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
    """Loop principal del proceso worker (`instagram_send_worker` en
    docker-compose). Consume `ig:outbound` con `BLPOP` (bloqueante, sin
    busy-waiting), mismo patrón que `wa_send_worker`.

    Hardening (mismo patrón que SPEC-032/`wa_send_worker`): cada iteración
    corre envuelta en `resilient_worker_loop` — ante una caída transitoria
    de Redis/Postgres, se loguea y se espera backoff exponencial en vez de
    dejar morir el proceso (evita crash-loop de `restart: unless-stopped`).
    """
    redis_client = redis_client or get_redis_client()
    stop_event = stop_event or asyncio.Event()

    async def _iteration() -> None:
        await drain_one(redis_client, timeout_seconds=block_timeout_seconds)

    logger.info("instagram_send_worker_started", queue=OUTBOUND_QUEUE_KEY)
    await resilient_worker_loop(
        _iteration, stop_event=stop_event, worker_name="instagram_send_worker"
    )
    logger.info("instagram_send_worker_stopped")


def _run_forever_with_signal_handling() -> None:
    """Punto de entrada del proceso worker independiente (`python -m
    app.workers.instagram_send_worker`), usado por el servicio
    `instagram_send_worker` de `docker-compose.yml`. Se apaga limpiamente
    ante SIGTERM/SIGINT."""

    async def _main() -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)
        await run_worker_loop(stop_event=stop_event)

    asyncio.run(_main())


if __name__ == "__main__":
    _run_forever_with_signal_handling()
