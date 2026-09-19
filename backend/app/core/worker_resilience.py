"""Resiliencia compartida de los workers de proceso independiente — SPEC-032
(hardening deuda técnica SPEC-027, BLACK PANTHER).

`run_worker_loop` de cada worker (`rag_ingest_worker`, `sentiment_worker`,
`whatsapp_inbound_worker`, `wa_send_worker`) hace `BLPOP`/`LPOP` contra Redis
y, dentro de `process_job`, abre sesiones de Postgres. Sin manejo de errores
alrededor de esa espera, una caída transitoria de Redis o Postgres hace que
la excepción se propague fuera del `while`, el proceso del contenedor
termina, y `restart: unless-stopped` (docker-compose.yml) lo reinicia de
inmediato — reintentando la misma operación fallida sin pausa, en un
crash-loop que satura CPU/logs y no da tiempo a que el dependiente se
recupere.

`resilient_worker_loop` envuelve el cuerpo del loop (una única iteración) en
try/except: ante una excepción, loguea con `exc_info` y espera un backoff
exponencial (con techo) antes de reintentar la siguiente iteración, en vez de
dejar que el proceso completo muera. Iteraciones exitosas resetean el backoff
a su valor base.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

# Backoff exponencial con techo: 1s, 2s, 4s, 8s, ... hasta el máximo.
_DEFAULT_BASE_SECONDS = 1.0
_DEFAULT_MAX_SECONDS = 30.0


async def resilient_worker_loop(
    iteration: Callable[[], Awaitable[None]],
    *,
    stop_event: asyncio.Event,
    worker_name: str,
    base_backoff_seconds: float = _DEFAULT_BASE_SECONDS,
    max_backoff_seconds: float = _DEFAULT_MAX_SECONDS,
) -> None:
    """Ejecuta `iteration()` repetidamente hasta que `stop_event` se active.

    Ante una excepción no controlada dentro de `iteration()` (p.ej. Redis o
    Postgres caídos), se loguea el evento (`worker_iteration_failed`, con
    `exc_info`) y se espera un backoff exponencial (capado en
    `max_backoff_seconds`) antes de reintentar — el proceso NUNCA termina
    por esta causa, evitando el crash-loop de `restart: unless-stopped`. Una
    iteración exitosa reinicia el backoff a `base_backoff_seconds`.

    La espera de backoff también respeta `stop_event` (se interrumpe antes
    si se pide apagado ordenado durante la espera).
    """
    backoff = base_backoff_seconds
    while not stop_event.is_set():
        try:
            await iteration()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — nunca debe tumbar el proceso worker
            logger.error(
                "worker_iteration_failed",
                worker=worker_name,
                backoff_seconds=backoff,
                exc_info=True,
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, max_backoff_seconds)
        else:
            backoff = base_backoff_seconds
