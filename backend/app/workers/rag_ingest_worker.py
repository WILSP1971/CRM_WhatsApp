"""Worker de ingesta RAG — consume la cola Redis real — SPEC-017 RNF-06/R-28.

`process_job` ejecuta la ingesta real (chunking + embeddings + persistencia,
`app.services.rag.ingest_service.ingest_document`) con el tenant del job
fijado (RLS). `run_worker_loop`/`__main__` implementan el PROCESO worker
independiente (servicio `rag_worker` de `docker-compose.yml`) que consume
`app.core.rag_queue` con `BLPOP` (bloqueante, sin busy-waiting) — así la API
solo encola (`POST /rag/documents/{id}/ingest`, `app/api/rag.py`) y el
procesamiento pesado corre en otro contenedor/proceso: un reinicio de la API
NO pierde el job (persiste en Redis, `appendonly yes`) y un reinicio del
worker simplemente retoma el siguiente `BLPOP`.

Defensa en profundidad (MAYOR, revisión BLACK PANTHER): `process_job` valida
que `document.tenant_id == job.tenant_id` ANTES de escribir nada, por si la
cola llegara a recibir un job forjado/corrupto (p.ej. un bug en otro
productor, o un mensaje inyectado directamente en Redis) — nunca confía
ciegamente en el `tenant_id` del payload para fijar RLS sin verificarlo
primero contra el dueño real del documento.
"""

from __future__ import annotations

import asyncio
import signal
import uuid
from typing import Callable

import redis.asyncio as redis_asyncio
import sqlalchemy as sa
import structlog
from sqlalchemy.orm import Session

from app.core.rag_queue import IngestJob, dequeue_ingest_job
from app.core.redis_client import get_redis_client
from app.core.worker_resilience import resilient_worker_loop
from app.db.session import SessionLocal, set_tenant_session
from app.services.ai_service import AIClient
from app.services.rag.ingest_service import ingest_document

logger = structlog.get_logger(__name__)

# Namespace fijo usado por el worker "genérico" (sin tenant conocido de
# antemano): en vez de `BLPOP` por tenant individual (requeriría conocer de
# antemano la lista de tenants activos), el worker escucha un canal de
# notificación ligero y resuelve la cola concreta del tenant señalado. Ver
# `NOTIFY_KEY`/`enqueue_ingest_job` + `notify_new_job` más abajo.
NOTIFY_KEY = "rag:ingest:notify"


class TenantMismatchError(RuntimeError):
    """El `tenant_id` del job no coincide con el dueño real del documento."""


def process_job(
    job: IngestJob,
    *,
    ai_client: AIClient | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """Procesa un job de ingesta ya extraído de la cola (RLS por tenant).

    Verifica primero, DENTRO de una sesión sin `tenant_id` fijado (para leer
    el documento por su id real sin depender de RLS), que el documento
    efectivamente pertenece al `tenant_id` declarado por el job. Si no
    coincide (job forjado/corrupto), se rechaza y se loguea SIN tocar RLS ni
    persistir nada.

    `session_factory` es SOLO para pruebas (inyecta una `Session` sobre el
    `postgres_engine` de test en vez del `SessionLocal` cacheado de
    `Settings`, que en producción SIEMPRE apunta a `DATABASE_URL`).
    """
    client = ai_client or AIClient()
    db = (session_factory or SessionLocal)()
    try:
        try:
            document_tenant_id = db.execute(
                sa.text("SELECT tenant_id FROM documents WHERE id = :id"),
                {"id": uuid.UUID(job.document_id)},
            ).scalar_one_or_none()
        finally:
            db.rollback()  # cierra la transacción de solo lectura sin efectos

        if document_tenant_id is None:
            logger.warning(
                "rag_ingest_job_document_not_found",
                document_id=job.document_id,
                tenant_id=job.tenant_id,
            )
            return

        if str(document_tenant_id) != str(job.tenant_id):
            # MAYOR (BLACK PANTHER): nunca fijar `app.tenant_id` con un valor
            # del job sin haber verificado antes que coincide con el dueño
            # real del documento — evita que un job forjado escriba/lea bajo
            # un tenant_id de sesión distinto al del recurso referenciado.
            logger.error(
                "rag_ingest_job_tenant_mismatch_rejected",
                document_id=job.document_id,
                job_tenant_id=job.tenant_id,
                actual_tenant_id=str(document_tenant_id),
            )
            raise TenantMismatchError(
                f"El job declara tenant_id={job.tenant_id} pero el documento "
                f"{job.document_id} pertenece a tenant_id={document_tenant_id}"
            )

        with db.begin():
            set_tenant_session(db, job.tenant_id)
            result = ingest_document(
                db,
                client,
                document_id=uuid.UUID(job.document_id),
                text=job.text,
                chunk_size=job.chunk_size,
                chunk_overlap=job.chunk_overlap,
            )
        logger.info(
            "rag_ingest_job_processed",
            document_id=job.document_id,
            tenant_id=job.tenant_id,
            estado=result.estado,
            chunks_creados=result.chunks_creados,
        )
    finally:
        db.close()


async def notify_new_job(redis_client: redis_asyncio.Redis, tenant_id: str) -> None:
    """Notifica al worker que hay un job nuevo para `tenant_id` (namespacing
    por tenant, R-23): el worker genérico escucha `NOTIFY_KEY` para saber en
    qué cola (`ingest_queue_key(tenant_id)`) hacer `BLPOP` a continuación,
    sin tener que conocer de antemano la lista completa de tenants."""
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
    Usado tanto por tests como por `run_worker_loop`. `session_factory` se
    propaga a `process_job` (solo para pruebas, ver su docstring).
    """
    job = await dequeue_ingest_job(
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
    """Loop principal del proceso worker (`rag_worker` en docker-compose).

    Espera notificaciones en `NOTIFY_KEY` (`BLPOP`, bloqueante, sin
    busy-waiting) y, por cada notificación, drena la cola del tenant
    señalado hasta vaciarla. Se detiene limpiamente al recibir `stop_event`
    (usado para pruebas y para el apagado ordenado por señal, ver
    `_run_forever_with_signal_handling`).

    Hardening (SPEC-032, deuda SPEC-027/BLACK PANTHER): cada iteración corre
    envuelta en `resilient_worker_loop` — si Redis/Postgres caen a mitad de
    una iteración, la excepción se loguea y se espera un backoff exponencial
    en vez de dejar morir el proceso (evita crash-loop de `restart:
    unless-stopped`).
    """
    redis_client = redis_client or get_redis_client()
    stop_event = stop_event or asyncio.Event()

    async def _iteration() -> None:
        result = await redis_client.blpop([NOTIFY_KEY], timeout=block_timeout_seconds)
        if result is None:
            return
        _, tenant_id = result
        # Drena TODOS los jobs pendientes de ese tenant antes de volver a
        # esperar la siguiente notificación (una notificación puede quedar
        # "vieja" si el tenant ya encoló varios documentos seguidos).
        while await drain_one(redis_client, tenant_id=tenant_id, timeout_seconds=0):
            pass

    logger.info("rag_ingest_worker_started")
    await resilient_worker_loop(
        _iteration, stop_event=stop_event, worker_name="rag_ingest_worker"
    )
    logger.info("rag_ingest_worker_stopped")


def _run_forever_with_signal_handling() -> None:
    """Punto de entrada del proceso worker independiente (`python -m
    app.workers.rag_ingest_worker`), usado por el servicio `rag_worker` de
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
