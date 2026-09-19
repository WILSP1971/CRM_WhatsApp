"""Tests de `app.core.worker_resilience.resilient_worker_loop` — SPEC-032
(hardening deuda técnica SPEC-027, BLACK PANTHER).

Unitarios puros (sin Redis/Postgres reales): verifican el contrato de
resiliencia que `run_worker_loop` de los 4 workers de proceso independiente
(`rag_ingest_worker`, `sentiment_worker`, `whatsapp_inbound_worker`,
`wa_send_worker`) delega en este módulo:

  (a) una excepción en una iteración NO propaga fuera del loop (el worker no
      muere / no hay crash-loop);
  (b) se aplica backoff exponencial entre reintentos tras fallos consecutivos;
  (c) una iteración exitosa resetea el backoff a su valor base;
  (d) `stop_event` detiene el loop de forma ordenada, incluso durante una
      espera de backoff.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.worker_resilience import resilient_worker_loop


@pytest.mark.asyncio
async def test_exception_in_iteration_does_not_propagate_and_loop_continues():
    """(a) Una iteración que lanza excepción no tumba el loop: tras varios
    fallos, el loop sigue vivo hasta que se le pide detenerse."""
    calls = {"n": 0}
    stop_event = asyncio.Event()

    async def flaky_iteration() -> None:
        calls["n"] += 1
        if calls["n"] >= 3:
            stop_event.set()
            return
        raise ConnectionError("Redis/Postgres caído (simulado)")

    # No debe lanzar excepción alguna fuera del loop.
    await resilient_worker_loop(
        flaky_iteration,
        stop_event=stop_event,
        worker_name="test_worker",
        base_backoff_seconds=0.01,
        max_backoff_seconds=0.05,
    )

    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_backoff_grows_exponentially_and_is_capped():
    """(b) El backoff crece 1x, 2x, 4x... hasta el techo `max_backoff_seconds`."""
    sleep_calls: list[float] = []
    calls = {"n": 0}
    stop_event = asyncio.Event()

    async def always_fails() -> None:
        calls["n"] += 1
        if calls["n"] > 4:
            stop_event.set()
            return
        raise RuntimeError("fallo simulado")

    original_wait_for = asyncio.wait_for

    async def spy_wait_for(aw, timeout):
        sleep_calls.append(timeout)
        # Resuelve casi instantáneo para no ralentizar el test: se limita a
        # esperar el mínimo indispensable, dejando que expire por timeout
        # (igual que en producción, sin necesidad de más de unos ms reales).
        return await original_wait_for(aw, timeout=min(timeout, 0.01))

    asyncio.wait_for = spy_wait_for
    try:
        await resilient_worker_loop(
            always_fails,
            stop_event=stop_event,
            worker_name="test_worker",
            base_backoff_seconds=1.0,
            max_backoff_seconds=4.0,
        )
    finally:
        asyncio.wait_for = original_wait_for

    # 4 fallos -> backoffs esperados: 1, 2, 4, 4 (capado en max_backoff_seconds).
    assert sleep_calls == [1.0, 2.0, 4.0, 4.0]


@pytest.mark.asyncio
async def test_successful_iteration_resets_backoff():
    """(c) Tras una iteración exitosa, el siguiente fallo vuelve a esperar el
    backoff BASE (no continúa creciendo desde donde iba)."""
    sleep_calls: list[float] = []
    calls = {"n": 0}
    stop_event = asyncio.Event()

    async def fail_fail_succeed_fail() -> None:
        calls["n"] += 1
        if calls["n"] in (1, 2):
            raise RuntimeError("fallo simulado")
        if calls["n"] == 3:
            return  # éxito: resetea el backoff
        if calls["n"] == 4:
            raise RuntimeError("fallo simulado tras éxito")
        stop_event.set()

    original_wait_for = asyncio.wait_for

    async def spy_wait_for(aw, timeout):
        sleep_calls.append(timeout)
        return await original_wait_for(aw, timeout=min(timeout, 0.01))

    asyncio.wait_for = spy_wait_for
    try:
        await resilient_worker_loop(
            fail_fail_succeed_fail,
            stop_event=stop_event,
            worker_name="test_worker",
            base_backoff_seconds=1.0,
            max_backoff_seconds=8.0,
        )
    finally:
        asyncio.wait_for = original_wait_for

    # Fallo 1 -> backoff base (1.0); fallo 2 -> backoff duplicado (2.0);
    # éxito (iteración 3) resetea; fallo 4 -> vuelve a backoff base (1.0).
    assert sleep_calls == [1.0, 2.0, 1.0]


@pytest.mark.asyncio
async def test_stop_event_set_during_backoff_wait_stops_loop_promptly():
    """(d) Si `stop_event` se activa mientras se espera el backoff, el loop
    se detiene sin esperar el backoff completo."""
    stop_event = asyncio.Event()

    async def always_fails() -> None:
        raise RuntimeError("fallo simulado")

    async def _set_stop_soon() -> None:
        await asyncio.sleep(0.02)
        stop_event.set()

    setter = asyncio.create_task(_set_stop_soon())
    await asyncio.wait_for(
        resilient_worker_loop(
            always_fails,
            stop_event=stop_event,
            worker_name="test_worker",
            base_backoff_seconds=30.0,  # backoff largo; debe interrumpirse antes
            max_backoff_seconds=30.0,
        ),
        timeout=2.0,
    )
    await setter


@pytest.mark.asyncio
async def test_stop_event_already_set_never_calls_iteration():
    stop_event = asyncio.Event()
    stop_event.set()
    calls = {"n": 0}

    async def iteration() -> None:
        calls["n"] += 1

    await resilient_worker_loop(
        iteration, stop_event=stop_event, worker_name="test_worker"
    )

    assert calls["n"] == 0
