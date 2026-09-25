"""Worker de ingesta de grabaciones — consume `pbx:recordings:inbound` —
SPEC-037, ADR-007/ADR-008/ADR-010.

`process_job` procesa UN evento crudo ya extraído de la cola
(`RecordingInboundJob`, encolado por `app/integrations/pbx/webhook.py`):

  1. RESUELVE `numero_destino -> tenant_id` con la función SQL
     `resolve_tenant_by_pbx_line` (SECURITY DEFINER, ADR-008) — SIN fijar
     `app.tenant_id` de sesión todavía (mismo patrón que
     `whatsapp_inbound_worker._resolve_tenant_id`, ADR-007). Sin mapeo ->
     **descarte auditado**, CERO persistencia de audio (RF-03): se loguea
     `numero_destino`/`call_id`/`event_id` (metadatos de enrutado), NUNCA el
     contenido/bytes del audio (C2/C3, minimización de datos).
  2. Con el tenant resuelto, fija RLS (`set_tenant_session`) e IDEMPOTENCIA
     por `call_id` (RF-02, ADR-007): si ya existe una `Call` con ese
     `call_id` DENTRO del tenant resuelto (restricción UNIQUE
     `tenant_id+call_id`, SPEC-036), no-op — un reenvío del PBX con el mismo
     `call_id` NO crea una segunda `Call` ni un segundo trabajo STT.
  3. Solo en el camino feliz (llamada nueva): almacena el audio CIFRADO en el
     almacén on-prem (`app.services.telefonia.audio_store`, SPEC-035),
     persiste la `Call` con `audio_ref`, y ENCOLA el trabajo STT en
     `stt:jobs` (`app.core.stt_queue`) para que lo consuma `stt_worker`
     (SPEC-038, fuera de alcance aquí — este worker NUNCA transcribe).

Robustez (mismo criterio que `whatsapp_inbound_worker`, RNF-05): un fallo
procesando un job se loguea con `exc_info` y NO detiene el loop del worker —
el job ya salió de la cola (`BLPOP` es destructivo), así que un evento que
falle de forma persistente no bloquea a los siguientes; queda auditado en
logs para investigación manual.

CHECKPOINT SENSIBLE: este módulo NUNCA importa `app/services/telefonia/
pbx_client.py` (descarga del PBX externo) — solo el almacén cifrado
(`audio_store.py`) y la cola STT. No hay egress en este worker.
"""

from __future__ import annotations

import asyncio
import signal
import uuid
from typing import Callable

import redis.asyncio as redis_asyncio
import sqlalchemy as sa
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.recording_queue import (
    RECORDING_INBOUND_QUEUE_KEY,
    RecordingInboundJob,
    dequeue_recording_inbound_event,
)
from app.core.redis_client import get_redis_client
from app.core.stt_queue import enqueue_stt_job
from app.core.worker_resilience import resilient_worker_loop
from app.db.session import SessionLocal, set_tenant_session
from app.models.call import Call
from app.services.telefonia.audio_store import AudioStoreError, build_audio_ref, store_audio

logger = structlog.get_logger(__name__)

_ESTADO_CALL_FINALIZADA = "finalizada"


def _resolve_tenant_id(db: Session, *, numero_destino: str) -> uuid.UUID | None:
    """Invoca la función SQL `resolve_tenant_by_pbx_line` (SECURITY DEFINER,
    ADR-008) — NUNCA un SELECT directo sobre `pbx_lines`, que devolvería 0
    filas bajo RLS sin `app.tenant_id` fijado todavía (la resolución es, por
    definición, PRE-tenant). Se ejecuta en su propia transacción de solo
    lectura, sin fijar RLS."""
    try:
        tenant_id = db.execute(
            sa.text("SELECT resolve_tenant_by_pbx_line(:numero_destino) AS tenant_id"),
            {"numero_destino": numero_destino},
        ).scalar_one_or_none()
    finally:
        db.rollback()  # cierra la transacción de solo lectura sin efectos
    return tenant_id


def _call_exists(db: Session, *, tenant_id: uuid.UUID, call_id: str) -> bool:
    """Dedup por `call_id` (RF-02, ADR-007): consulta previa bajo RLS (ya con
    `app.tenant_id` fijado) para no repetir trabajo (guardar audio, encolar
    STT) en el camino feliz. La restricción UNIQUE de BD
    (`uq_calls_tenant_call_id`, SPEC-036) es la garantía dura ante
    condiciones de carrera entre workers; esta consulta es una guarda
    adicional del worker, no el único mecanismo."""
    return (
        db.execute(
            sa.text(
                "SELECT 1 FROM calls WHERE tenant_id = :tenant_id "
                "AND call_id = :call_id LIMIT 1"
            ),
            {"tenant_id": str(tenant_id), "call_id": call_id},
        ).scalar_one_or_none()
        is not None
    )


def process_job(
    job: RecordingInboundJob,
    *,
    session_factory: Callable[[], Session] | None = None,
    redis_client: redis_asyncio.Redis | None = None,
) -> None:
    """Procesa un job ya extraído de `pbx:recordings:inbound`: resuelve
    tenant, deduplica por `call_id`, almacena el audio cifrado, persiste la
    `Call` y encola el trabajo STT.

    `session_factory`/`redis_client` son SOLO para pruebas (inyectan una
    `Session` sobre el `postgres_engine` de test y un doble de Redis en vez
    de las instancias reales).
    """
    db = (session_factory or SessionLocal)()
    try:
        tenant_id = _resolve_tenant_id(db, numero_destino=job.numero_destino)
        if tenant_id is None:
            # RF-03: sin mapeo de tenant -> descarte AUDITADO, CERO
            # persistencia del audio (ni siquiera se intenta escribir en el
            # almacén). Solo se loguean metadatos de enrutado, nunca bytes
            # de audio.
            logger.warning(
                "pbx_recording_unmapped_numero_destino_discarded",
                numero_destino=job.numero_destino,
                call_id=job.call_id,
                event_id=job.event_id,
            )
            return

        try:
            with db.begin():
                set_tenant_session(db, str(tenant_id))

                if _call_exists(db, tenant_id=tenant_id, call_id=job.call_id):
                    # RF-02: reenvío del PBX con el mismo call_id -> no-op
                    # idempotente. CERO segunda escritura de audio/Call/job STT.
                    logger.info(
                        "pbx_recording_duplicate_call_id_skipped",
                        call_id=job.call_id,
                        tenant_id=str(tenant_id),
                        event_id=job.event_id,
                    )
                    return

                audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=job.call_id)
                try:
                    store_audio(audio_ref=audio_ref, audio_bytes=job.audio_bytes)
                except AudioStoreError:
                    logger.error(
                        "pbx_recording_audio_store_failed",
                        call_id=job.call_id,
                        tenant_id=str(tenant_id),
                        event_id=job.event_id,
                        exc_info=True,
                    )
                    return

                call = Call(
                    tenant_id=tenant_id,
                    call_id=job.call_id,
                    numero=job.numero,
                    direccion=job.direccion,
                    duracion=job.duracion,
                    estado=_ESTADO_CALL_FINALIZADA,
                    audio_ref=audio_ref,
                )
                db.add(call)
                db.flush()
                db.refresh(call)
        except IntegrityError:
            # Condición de carrera entre workers/reintentos concurrentes
            # sobre el MISMO call_id: la restricción UNIQUE de BD
            # (uq_calls_tenant_call_id, SPEC-036) es la garantía dura de
            # idempotencia (ADR-007) cuando `_call_exists` pierde la carrera.
            db.rollback()
            logger.info(
                "pbx_recording_duplicate_call_id_race_detected",
                call_id=job.call_id,
                tenant_id=str(tenant_id),
                event_id=job.event_id,
            )
            return

        logger.info(
            "pbx_recording_call_persisted",
            tenant_id=str(tenant_id),
            call_id=job.call_id,
            call_row_id=str(call.id),
            event_id=job.event_id,
        )

        # RF-04: encola el trabajo STT (stt:jobs) para stt_worker (SPEC-038,
        # fuera de alcance aquí). Best-effort: si Redis falla al encolar, la
        # Call YA quedó persistida con su audio — se loguea el fallo sin
        # revertir la ingesta (misma filosofía de modo degradado que
        # sentimiento/RAG en whatsapp_inbound_worker).
        _enqueue_stt_job_best_effort(
            redis_client or get_redis_client(),
            call_id=call.id,
            audio_ref=audio_ref,
            tenant_id=tenant_id,
        )
    finally:
        db.close()


def _enqueue_stt_job_best_effort(
    redis_client: redis_asyncio.Redis,
    *,
    call_id: uuid.UUID,
    audio_ref: str,
    tenant_id: uuid.UUID,
) -> None:
    """Wrapper sync -> async para encolar el trabajo STT desde este worker
    síncrono (mismo patrón que `whatsapp_inbound_worker.
    _schedule_sentiment_best_effort`): `asyncio.run` crea/cierra su propio
    loop porque `process_job` no corre dentro de un loop activo."""
    try:
        asyncio.run(
            enqueue_stt_job(
                redis_client,
                call_id=call_id,
                audio_ref=audio_ref,
                tenant_id=tenant_id,
            )
        )
    except Exception:  # noqa: BLE001 — best-effort, nunca revierte la ingesta
        logger.error(
            "pbx_recording_stt_enqueue_failed",
            call_id=str(call_id),
            tenant_id=str(tenant_id),
            exc_info=True,
        )


async def drain_one(
    redis_client: redis_asyncio.Redis,
    *,
    timeout_seconds: int = 0,
    session_factory: Callable[[], Session] | None = None,
) -> bool:
    """Extrae y procesa UN único job pendiente de `pbx:recordings:inbound`.

    Devuelve `True` si procesó un job, `False` si la cola estaba vacía.
    """
    job = await dequeue_recording_inbound_event(
        redis_client, timeout_seconds=timeout_seconds
    )
    if job is None:
        return False
    process_job(job, session_factory=session_factory, redis_client=redis_client)
    return True


async def run_worker_loop(
    redis_client: redis_asyncio.Redis | None = None,
    *,
    block_timeout_seconds: int = 5,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Loop principal del proceso worker (`recording_ingest_worker` en
    docker-compose). Consume `pbx:recordings:inbound` con `BLPOP`
    (bloqueante, sin busy-waiting) — mismo patrón que
    `whatsapp_inbound_worker`/`rag_ingest_worker`.

    Hardening (mismo criterio que el resto de workers, SPEC-032): cada
    iteración corre envuelta en `resilient_worker_loop` — ante una caída
    transitoria de Redis/Postgres, se loguea y se espera backoff exponencial
    en vez de dejar morir el proceso.
    """
    redis_client = redis_client or get_redis_client()
    stop_event = stop_event or asyncio.Event()

    async def _iteration() -> None:
        await drain_one(redis_client, timeout_seconds=block_timeout_seconds)

    logger.info(
        "recording_ingest_worker_started", queue=RECORDING_INBOUND_QUEUE_KEY
    )
    await resilient_worker_loop(
        _iteration, stop_event=stop_event, worker_name="recording_ingest_worker"
    )
    logger.info("recording_ingest_worker_stopped")


def _run_forever_with_signal_handling() -> None:
    """Punto de entrada del proceso worker independiente (`python -m
    app.workers.recording_ingest_worker`), usado por el servicio
    `recording_ingest_worker` de `docker-compose.yml`. Se apaga limpiamente
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
