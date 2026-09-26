"""Utilidad para invocar una corutina desde código síncrono sin asumir que
el hilo actual esté libre de un event loop en marcha.

Contexto del bug que esto corrige (encontrado ejecutando la suite contra
Postgres real, con un test `@pytest.mark.asyncio` que reproduce la condición
real de producción): `app/workers/stt_worker.py` y
`app/workers/whatsapp_inbound_worker.py` disparan el pipeline de sentimiento
(SPEC-018) best-effort desde `process_job`, una función SÍNCRONA, usando
`asyncio.run(...)`. En producción real, `process_job` es invocado desde
`drain_one`/`run_worker_loop` — corutinas que YA están corriendo dentro de un
event loop activo — así que ese `asyncio.run()` SIEMPRE lanzaba
`RuntimeError: asyncio.run() cannot be called from a running event loop`,
silenciado por el `except Exception` best-effort del llamador: el job de
sentimiento nunca se encolaba en producción, sin que ningún log de error
visible lo delatara como un fallo sistemático (solo un `warning` best-effort
por mensaje). Los tests anteriores nunca detectaron esto porque invocaban
`process_job` directamente desde una función de test SÍNCRONA (sin loop
activo), donde `asyncio.run()` funciona con normalidad.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import TypeVar

_T = TypeVar("_T")


def run_coroutine_best_effort(coro: Coroutine[None, None, _T]) -> _T:
    """Ejecuta `coro` hasta completarse, haya o no un event loop en marcha
    en el hilo actual.

    Sin loop activo (camino síncrono normal, p.ej. un test que llama
    `process_job` directamente): usa `asyncio.run()` sin overhead adicional.

    Con loop activo (camino real de producción, `process_job` invocado
    desde `drain_one`/`run_worker_loop`): `asyncio.run()` no puede anidarse
    dentro de un loop ya en marcha, así que `coro` se ejecuta en un loop
    NUEVO dentro de un hilo dedicado — bloquea el hilo actual hasta que
    termina (igual que ya bloqueaba `asyncio.run()` en el camino síncrono),
    sin intentar anidar loops.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_box: list[_T] = []
    error_box: list[BaseException] = []

    def _runner() -> None:
        try:
            result_box.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001 — se relanza en el hilo llamador
            error_box.append(exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if error_box:
        raise error_box[0]
    return result_box[0]
