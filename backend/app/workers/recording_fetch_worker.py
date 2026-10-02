"""
Recording Fetch Worker — Descarga de grabaciones desde PBX externo (SPEC-035, SPEC-037, ADR-010)

Procesa solicitudes de descarga de grabaciones desde un PBX externo de forma
asíncrona desde Redis (`recording:fetch:jobs`, `app.core.recording_fetch_queue`).
Se levanta SOLO si:
1. El Lead confirma PBX EXTERNO (PBX_EXTERNAL_ENABLED=true).
2. Se ejecuta `docker compose --profile pbx-externo up`.

Características (por defecto: desactivado, SUP-42):
- Egress ACOTADO SOLO al host del PBX (firewall host + allowlist check-externos-backend.sh)
- La descarga en sí NUNCA se hace en este módulo con un cliente HTTP directo
  (la auditoría de CI prohíbe ese tipo de cliente de transporte dentro de
  `app/workers/`): se delega EXCLUSIVAMENTE a
  `app/services/telefonia/pbx_client.download_recording`, que valida el host
  exacto (`PBX_EXTERNAL_HOST`) antes de cualquier petición (ADR-010).
- Tras descargar, reencola el audio en `pbx:recordings:inbound`
  (`app.core.recording_queue`) para que `recording_ingest_worker` (SPEC-037)
  aplique el MISMO pipeline (resolución de tenant, dedup por `call_id`,
  almacenamiento cifrado, encolado STT) que el camino feliz on-prem — sin
  duplicar esa lógica en este worker.
- STT/IA jamás pueden importar este módulo ni `pbx_client.py` (auditado en CI,
  sección 11 de `check-externos-backend.sh`).

Notas de seguridad (C3, ADR-010):
- Las credenciales del PBX (host, puerto, auth token) vienen del env (NUNCA hardcoded)
- Descarga de grabación → reencolada para el almacén local cifrado (vía
  `recording_ingest_worker`), nunca escrita en claro por este worker.

Riesgos mitigados:
- R-45 (egress del PBX): allowlist por host + firewall host, validado en
  `pbx_client.py` (único módulo autorizado a usar un cliente HTTP de
  transporte fuera de `app/workers`).
- Preferible: PBX on-prem sin egress nuevo (SUP-42).

NOTA DE DIFERIMIENTO (SPEC-037, decisión explícita del Lead): este worker
NO RECIBE TRABAJO HOY. La rama del webhook que notificaría "solo URL" (en
vez de adjuntar el fichero) y encolaría en `recording_fetch_queue`
(`recording:fetch:jobs`) fue diferida a una fase posterior con aprobación
explícita del Lead, cuando se confirme un PBX externo real
(`PBX_EXTERNAL_ENABLED=true`). Este módulo queda como capacidad lista pero
INERTE: sin productor activo, y ya aislado por `profiles: ["pbx-externo"]`
en `docker-compose.yml` (no se levanta con `docker compose up` por
defecto). Ver `.swarm/specs/SPEC-037.md`, sección "Nota de diferimiento
formal".
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

import redis.asyncio as redis_asyncio
import structlog

from app.core.async_utils import run_coroutine_best_effort
from app.core.recording_queue import (
    build_recording_inbound_job,
    enqueue_recording_inbound_event,
)
from app.core.recording_fetch_queue import (
    RECORDING_FETCH_QUEUE_KEY,
    RecordingFetchJob,
    dequeue_recording_fetch_job,
)
from app.core.redis_client import get_redis_client
from app.core.worker_resilience import resilient_worker_loop

logger = structlog.get_logger(__name__)
_stdlib_logger = logging.getLogger(__name__)


def process_job(
    job: RecordingFetchJob,
    *,
    redis_client: redis_asyncio.Redis,
) -> None:
    """Descarga la grabación notificada por URL (SOLO PBX externo, ADR-010) y
    reencola el audio ya obtenido en `pbx:recordings:inbound` para que
    `recording_ingest_worker` aplique el pipeline común (tenant/dedup/
    almacenamiento cifrado/STT).

    Import LOCAL del cliente de descarga (en vez de en el top-level del
    módulo): mantiene la dependencia de descarga confinada al camino de
    código que de verdad se ejecuta cuando `PBX_EXTERNAL_ENABLED` está
    activo, sin cambiar el resultado de la auditoría estática (el import
    sigue siendo hacia `app/services/telefonia/`, el único módulo permitido,
    ADR-010).
    """
    from app.services.telefonia.pbx_client import (
        PbxDownloadError,
        PbxHostNotAllowedError,
        download_recording,
    )

    try:
        audio_bytes = download_recording(recording_url=job.recording_url)
    except (PbxDownloadError, PbxHostNotAllowedError):
        logger.error(
            "recording_fetch_download_failed",
            call_id=job.call_id,
            event_id=job.event_id,
            exc_info=True,
        )
        return

    inbound_job = build_recording_inbound_job(
        call_id=job.call_id,
        numero=job.numero,
        numero_destino=job.numero_destino,
        direccion=job.direccion,
        audio_bytes=audio_bytes,
        duracion=job.duracion,
    )

    # CORRECCIÓN (bug de producción encontrado ejecutando la suite contra
    # Postgres real, ver `app.core.async_utils`): `process_job` corre en
    # producción real dentro del loop activo de `drain_one`/
    # `run_worker_loop` — `asyncio.run()` directo aquí SIEMPRE fallaba con
    # `RuntimeError: asyncio.run() cannot be called from a running event
    # loop`, silenciado por el `except Exception` de abajo: el evento
    # reencolado nunca llegaba a `recording:inbound` en producción.
    try:
        run_coroutine_best_effort(
            enqueue_recording_inbound_event(redis_client, job=inbound_job)
        )
    except Exception:  # noqa: BLE001 — best-effort, se loguea sin tumbar el worker
        logger.error(
            "recording_fetch_reenqueue_failed",
            call_id=job.call_id,
            event_id=job.event_id,
            exc_info=True,
        )
        return

    logger.info(
        "recording_fetch_downloaded_and_reenqueued",
        call_id=job.call_id,
        event_id=job.event_id,
        audio_length=len(audio_bytes),
    )


async def drain_one(
    redis_client: redis_asyncio.Redis, *, timeout_seconds: int = 0
) -> bool:
    """Extrae y procesa UNA única solicitud pendiente de
    `recording:fetch:jobs`. Devuelve `True` si procesó un job, `False` si la
    cola estaba vacía."""
    job = await dequeue_recording_fetch_job(
        redis_client, timeout_seconds=timeout_seconds
    )
    if job is None:
        return False
    process_job(job, redis_client=redis_client)
    return True


async def run_worker_loop(
    redis_client: redis_asyncio.Redis | None = None,
    *,
    block_timeout_seconds: int = 5,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Loop principal del proceso worker (`recording_fetch_worker` en
    docker-compose, `profiles: ["pbx-externo"]`). Consume
    `recording:fetch:jobs` con `BLPOP` — mismo patrón de resiliencia
    (`resilient_worker_loop`) que el resto de workers del proyecto."""
    redis_client = redis_client or get_redis_client()
    stop_event = stop_event or asyncio.Event()

    async def _iteration() -> None:
        await drain_one(redis_client, timeout_seconds=block_timeout_seconds)

    logger.info("recording_fetch_worker_started", queue=RECORDING_FETCH_QUEUE_KEY)
    await resilient_worker_loop(
        _iteration, stop_event=stop_event, worker_name="recording_fetch_worker"
    )
    logger.info("recording_fetch_worker_stopped")


def main():
    """
    Punto de entrada del worker de descarga de grabaciones (SPEC-035, SPEC-037).

    Verifica `PBX_EXTERNAL_ENABLED` antes de arrancar el loop: este servicio
    NUNCA debería levantarse si el PBX es on-prem (SUP-42) — el
    `docker-compose.yml` ya lo aísla tras `profiles: ["pbx-externo"]`, esta
    comprobación es una defensa adicional en runtime.
    """
    try:
        from app.core.config import get_settings

        settings = get_settings()
    except Exception as e:
        _stdlib_logger.error(
            f"[Recording Fetch Worker] Error al cargar configuración: {e}"
        )
        sys.exit(1)

    _stdlib_logger.info(
        "[Recording Fetch Worker] Iniciando worker de descarga de grabaciones (SPEC-035/037, ADR-010)."
    )

    if not settings.pbx_external_enabled:
        _stdlib_logger.warning(
            "[Recording Fetch Worker] PBX_EXTERNAL_ENABLED=false (PBX on-prem). "
            "Este worker no debería estar levantado. Revisar docker-compose.yml profiles."
        )
        sys.exit(1)

    _stdlib_logger.info(
        "[Recording Fetch Worker] PBX externo: %s:%s (egress acotado, ADR-010)",
        settings.pbx_external_host,
        settings.pbx_external_port,
    )

    def _run_forever_with_signal_handling() -> None:
        async def _main() -> None:
            stop_event = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, stop_event.set)
            await run_worker_loop(stop_event=stop_event)

        asyncio.run(_main())

    try:
        _run_forever_with_signal_handling()
    except KeyboardInterrupt:
        _stdlib_logger.info(
            "[Recording Fetch Worker] Interrupción recibida. Cerrando..."
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
