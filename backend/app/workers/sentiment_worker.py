"""Worker de análisis de sentimiento — consume la cola Redis real — SPEC-018.

`process_job` clasifica el sentimiento del mensaje referenciado por el job
(`app.services.sentiment_service.classify_sentiment`, LLM local vía
`AIClient`) y persiste `sentimiento`/`sentimiento_score` en el propio
`Message`, bajo RLS fijando `app.tenant_id` al tenant DUEÑO REAL del mensaje
(nunca al `tenant_id` del job sin verificar antes, mismo criterio de defensa
en profundidad que `app/workers/rag_ingest_worker.py::process_job`, revisión
BLACK PANTHER SPEC-017).

`run_worker_loop`/`__main__` implementan el proceso worker independiente
(servicio `sentiment_worker` de `docker-compose.yml`) que consume
`app.core.sentiment_queue` con `BLPOP` (bloqueante, sin busy-waiting): la API
solo encola (`app/services/message_service.py::create_message`) y el
procesamiento (que habla con el LLM local, potencialmente cientos de ms) corre
en otro proceso — así la recepción/persistencia del mensaje nunca se bloquea
(RF de SPEC-018).

Modo degradado (R-21): si `AIClient` no está disponible o la respuesta del
LLM no es parseable, `classify_sentiment` devuelve un resultado en modo
degradado (`label=None`); `process_job` simplemente no persiste ningún
cambio (el mensaje queda `sentimiento IS NULL`, indistinguible de "aún no
clasificado") y NO reintenta indefinidamente ni bloquea el worker — el
mensaje ya fue persistido correctamente por el flujo principal.
"""

from __future__ import annotations

import asyncio
import signal
import uuid
from decimal import Decimal
from typing import Callable

import redis.asyncio as redis_asyncio
import sqlalchemy as sa
import structlog
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis_client
from app.core.sentiment_queue import (
    NOTIFY_KEY,
    SentimentJob,
    dequeue_sentiment_job,
)
from app.core.worker_resilience import resilient_worker_loop
from app.db.session import SessionLocal, set_tenant_session
from app.models.message import Message
from app.services.ai_service import AIClient
from app.services.sentiment_service import classify_sentiment

logger = structlog.get_logger(__name__)


class TenantMismatchError(RuntimeError):
    """El `tenant_id` del job no coincide con el dueño real del mensaje."""


def process_job(
    job: SentimentJob,
    *,
    ai_client: AIClient | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """Procesa un job de sentimiento ya extraído de la cola (RLS por tenant).

    Verifica primero, en una sesión SIN `tenant_id` fijado, que el mensaje
    referenciado pertenece efectivamente al `tenant_id` declarado por el job
    (defensa contra un job forjado/corrupto). Si no coincide, se rechaza sin
    fijar RLS ni tocar el mensaje. Si el mensaje no existe (p.ej. borrado
    lógico posterior o id inválido), se loguea y se descarta sin excepción.
    """
    client = ai_client or AIClient()
    db = (session_factory or SessionLocal)()
    try:
        try:
            message_id = uuid.UUID(job.message_id)
        except ValueError:
            logger.warning(
                "sentiment_job_invalid_message_id", message_id=job.message_id
            )
            return

        try:
            row = db.execute(
                sa.text(
                    "SELECT tenant_id, contenido, activo FROM messages WHERE id = :id"
                ),
                {"id": message_id},
            ).one_or_none()
        finally:
            db.rollback()  # cierra la transacción de solo lectura sin efectos

        if row is None:
            logger.warning(
                "sentiment_job_message_not_found",
                message_id=job.message_id,
                tenant_id=job.tenant_id,
            )
            return

        message_tenant_id, contenido, activo = row

        if str(message_tenant_id) != str(job.tenant_id):
            # Defensa en profundidad (mismo criterio que rag_ingest_worker):
            # nunca fijar `app.tenant_id` con un valor del job sin haberlo
            # verificado antes contra el dueño real del recurso referenciado.
            logger.error(
                "sentiment_job_tenant_mismatch_rejected",
                message_id=job.message_id,
                job_tenant_id=job.tenant_id,
                actual_tenant_id=str(message_tenant_id),
            )
            raise TenantMismatchError(
                f"El job declara tenant_id={job.tenant_id} pero el mensaje "
                f"{job.message_id} pertenece a tenant_id={message_tenant_id}"
            )

        if not activo:
            # C2: un mensaje borrado lógicamente no se reclasifica.
            logger.info(
                "sentiment_job_skipped_inactive_message", message_id=job.message_id
            )
            return

        result = classify_sentiment(client, contenido=contenido)
        if result.label is None:
            # Modo degradado (R-21): no se persiste nada; el mensaje queda
            # sin clasificar en vez de bloquear/reintentar sin control.
            logger.warning(
                "sentiment_job_degraded_no_label_persisted",
                message_id=job.message_id,
            )
            return

        with db.begin():
            set_tenant_session(db, job.tenant_id)
            message = db.get(Message, message_id)
            if message is None or not message.activo:
                return
            message.sentimiento = result.label
            message.sentimiento_score = (
                Decimal(str(round(result.score, 3)))
                if result.score is not None
                else None
            )

        logger.info(
            "sentiment_job_processed",
            message_id=job.message_id,
            tenant_id=job.tenant_id,
            sentimiento=result.label,
        )
    finally:
        db.close()


async def notify_new_job(redis_client: redis_asyncio.Redis, tenant_id: str) -> None:
    """Notifica al worker que hay un job nuevo para `tenant_id`."""
    await redis_client.rpush(NOTIFY_KEY, tenant_id)


async def drain_one(
    redis_client: redis_asyncio.Redis,
    *,
    tenant_id: uuid.UUID | str,
    timeout_seconds: int = 0,
    session_factory: Callable[[], Session] | None = None,
) -> bool:
    """Extrae y procesa UN único job pendiente de un tenant.

    Devuelve `True` si procesó un job, `False` si la cola estaba vacía.
    """
    job = await dequeue_sentiment_job(
        redis_client, tenant_id=tenant_id, timeout_seconds=timeout_seconds
    )
    if job is None:
        return False
    process_job(job, session_factory=session_factory)
    return True


async def run_worker_loop(
    redis_client: redis_asyncio.Redis | None = None,
    *,
    block_timeout_seconds: int = 5,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Loop principal del proceso worker (`sentiment_worker` en docker-compose).

    Espera notificaciones en `NOTIFY_KEY` (`BLPOP`, bloqueante, sin
    busy-waiting) y, por cada notificación, drena la cola del tenant
    señalado hasta vaciarla. Mismo patrón que
    `app.workers.rag_ingest_worker.run_worker_loop` (SPEC-017).

    Hardening (SPEC-032, deuda SPEC-027/BLACK PANTHER): cada iteración corre
    envuelta en `resilient_worker_loop` — ante una caída transitoria de
    Redis/Postgres, se loguea y se espera backoff exponencial en vez de
    dejar morir el proceso (evita crash-loop de `restart: unless-stopped`).
    """
    redis_client = redis_client or get_redis_client()
    stop_event = stop_event or asyncio.Event()

    async def _iteration() -> None:
        result = await redis_client.blpop([NOTIFY_KEY], timeout=block_timeout_seconds)
        if result is None:
            return
        _, tenant_id = result
        while await drain_one(redis_client, tenant_id=tenant_id, timeout_seconds=0):
            pass

    logger.info("sentiment_worker_started")
    await resilient_worker_loop(
        _iteration, stop_event=stop_event, worker_name="sentiment_worker"
    )
    logger.info("sentiment_worker_stopped")


def _run_forever_with_signal_handling() -> None:
    """Punto de entrada del proceso worker independiente (`python -m
    app.workers.sentiment_worker`), usado por el servicio `sentiment_worker`
    de `docker-compose.yml`. Se apaga limpiamente ante SIGTERM/SIGINT."""

    async def _main() -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)
        await run_worker_loop(stop_event=stop_event)

    asyncio.run(_main())


if __name__ == "__main__":
    _run_forever_with_signal_handling()
