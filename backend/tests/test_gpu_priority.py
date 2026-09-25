"""Tests de `app.core.gpu_priority` — ADR-011 §2/§3, SPEC-044.

Unitarios con `fakeredis` (SIN Postgres real, sin daemon Redis real): cubre
el contrato de la señal de prioridad de GPU (`voice:active_calls`) que usa
el `stt_worker` batch para pausarse ante llamadas en vivo activas.

Corrección WOLVERINE (post SPEC-044): el módulo usaba `logging` stdlib con
kwargs estilo `structlog` (`logger.warning("msg", key=..., exc_info=True)`),
lo que lanzaba `TypeError` en TODA llamada al logger — incluyendo dentro de
los propios bloques `except` que implementan el fail-open ante Redis caído
(rompiendo exactamente la garantía de RF-02 de SPEC-044). El test
`test_*_redis_exception_fails_open_without_raising` de cada función es el
que habría atrapado esa regresión: simula que el cliente Redis lanza una
excepción y confirma que NINGUNA excepción (ni la original de Redis, ni un
`TypeError` de logging) se propaga fuera de la función.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.core.gpu_priority import (
    VOICE_ACTIVE_CALLS_KEY,
    check_voice_active_calls,
    decrement_active_calls,
    increment_active_calls,
    should_pause_batch_for_voice,
)


class _BoomRedis:
    """Doble de Redis que simula una caída de conexión en cada operación.

    Usado para ejercer el camino `except` (fail-open) de cada función del
    módulo sin depender de un servidor Redis real caído.
    """

    async def get(self, *_args, **_kwargs):
        raise ConnectionError("redis caído (simulado)")

    async def incr(self, *_args, **_kwargs):
        raise ConnectionError("redis caído (simulado)")

    async def decr(self, *_args, **_kwargs):
        raise ConnectionError("redis caído (simulado)")

    async def set(self, *_args, **_kwargs):
        raise ConnectionError("redis caído (simulado)")


# ---------------------------------------------------------------------------
# should_pause_batch_for_voice / check_voice_active_calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_pause_batch_for_voice_returns_false_when_key_missing():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    assert await should_pause_batch_for_voice(redis_client) is False


@pytest.mark.asyncio
async def test_should_pause_batch_for_voice_returns_false_when_key_is_zero():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await redis_client.set(VOICE_ACTIVE_CALLS_KEY, 0)

    assert await should_pause_batch_for_voice(redis_client) is False


@pytest.mark.asyncio
async def test_should_pause_batch_for_voice_returns_true_when_key_positive():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await redis_client.set(VOICE_ACTIVE_CALLS_KEY, 1)

    assert await should_pause_batch_for_voice(redis_client) is True


@pytest.mark.asyncio
async def test_check_voice_active_calls_returns_zero_when_key_missing():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    assert await check_voice_active_calls(redis_client) == 0


# ---------------------------------------------------------------------------
# increment_active_calls / decrement_active_calls — camino feliz
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_increment_active_calls_increments_atomically_via_incr():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    first = await increment_active_calls(redis_client)
    second = await increment_active_calls(redis_client)

    assert first == 1
    assert second == 2
    assert await check_voice_active_calls(redis_client) == 2


@pytest.mark.asyncio
async def test_decrement_active_calls_decrements_atomically_via_decr():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await redis_client.set(VOICE_ACTIVE_CALLS_KEY, 2)

    result = await decrement_active_calls(redis_client)

    assert result == 1
    assert await check_voice_active_calls(redis_client) == 1


@pytest.mark.asyncio
async def test_decrement_active_calls_never_goes_below_zero():
    """Garantía de seguridad documentada: un decremento excesivo (bug o
    ataque) nunca deja el contador en negativo — se resetea a 0."""
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await redis_client.set(VOICE_ACTIVE_CALLS_KEY, 0)

    result = await decrement_active_calls(redis_client)

    assert result == 0
    assert await check_voice_active_calls(redis_client) == 0


# ---------------------------------------------------------------------------
# Fail-open real ante caída de Redis (caso que habría atrapado el bug de
# `logging` stdlib con kwargs de `structlog` — TypeError propagado sin
# capturar en el propio bloque `except`).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_voice_active_calls_redis_exception_fails_open_without_raising():
    boom = _BoomRedis()

    result = await check_voice_active_calls(boom)

    assert result == 0


@pytest.mark.asyncio
async def test_should_pause_batch_for_voice_redis_exception_fails_open_without_raising():
    boom = _BoomRedis()

    result = await should_pause_batch_for_voice(boom)

    assert result is False


@pytest.mark.asyncio
async def test_increment_active_calls_redis_exception_fails_open_without_raising():
    boom = _BoomRedis()

    result = await increment_active_calls(boom)

    assert result == 0


@pytest.mark.asyncio
async def test_decrement_active_calls_redis_exception_fails_open_without_raising():
    boom = _BoomRedis()

    result = await decrement_active_calls(boom)

    assert result == 0
