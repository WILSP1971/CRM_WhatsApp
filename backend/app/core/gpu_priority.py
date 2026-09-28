"""GPU Priority Manager — mecanismo de prioridad de GPU para VoiceBot en vivo.

ADR-011 §2/§3: el VoiceBot en vivo (voice_stt) tiene prioridad estricta sobre
el `stt_worker` batch de #4 cuando hay ≥1 llamada en vivo activa. Este módulo
implementa la señal de prioridad:

1. Una clave Redis `voice:active_calls` (contador int, 0 por defecto) registra
   el número de llamadas en vivo activas.
2. El `stt_worker` batch consulta esta clave ANTES de procesar un job.
3. Si `voice:active_calls > 0`, el worker pausa/duerme y retorna sin procesar
   (reducción de consumo de GPU). El job queda en la cola para reintento
   (tolerante a cola por diseño del batch, SPEC-038).
4. Al completar una llamada en vivo, `voice_gateway` decrementa la clave.
5. El worker reanuda normalmente cuando la clave vuelve a 0 (no hay llamadas
   en vivo activas).

DISEÑO (F0, SPEC-044):
- Sin GPU real en sandbox: se verifica por inspección/mock.
- Con GPU real (F6, SPEC-050): se instrumenta contención real (latencia de
  GPU, backlog del batch) para evidenciar que la prioridad funciona.
- Nota (SPEC-068, R-87): el VoiceBot en vivo con GPU compartida descrito en
  este módulo NO se implementó (memoria de proyecto: "No GPU / VoiceBot
  pivot", CPU-only). La antigua clave `TTS_VRAM_FRACTION` (fracción de VRAM
  para TTS en vivo) se ELIMINÓ de `config.py` por no tener sentido en
  CPU-only; si en el futuro se reactivara este módulo con GPU real, la
  configuración de reserva de VRAM se re-diseñaría en esa SPEC, no se
  restauraría este flag archivado.

RUNBOOK PARA ACTIVACION CON GPU REAL:
1. En deployment con GPU: el `voice_gateway` SIEMPRE incrementa
   `voice:active_calls` al recibir una llamada entrante (inicio).
2. Al colgar (fin de llamada), decrementa.
3. El `stt_worker` respeta la señal: pausa/duerme si > 0.
4. Métricas (SPEC-050): se exportan en `/metrics` para evidenciar latencia
   de GPU + backlog del batch (objetivo: ≤700 ms p95 de voz en vivo, SLA
   batch tolerante a cola documentado).

No hay punto de activación condicional: siempre existe la lógica, pero en F0
sin GPU real es un no-op (contador siempre en 0).
"""

import redis.asyncio as redis_asyncio
import structlog

logger = structlog.get_logger(__name__)

# Clave Redis para contador de llamadas en vivo activas (ADR-011 §2).
# Valor: int (0 por defecto, sin llamadas activas).
VOICE_ACTIVE_CALLS_KEY = "voice:active_calls"

# Backoff (segundos) para pausa del `stt_worker` cuando hay llamadas en vivo
# activas. Corto (0.1-0.5 s) para minimizar latencia de reanudación al
# completar la llamada en vivo, pero no tan agresivo que cause busy-waiting.
GPU_PRIORITY_BACKOFF_SECONDS = 0.2


async def check_voice_active_calls(
    redis_client: redis_asyncio.Redis,
) -> int:
    """Consulta el contador de llamadas en vivo activas (ADR-011 §2).

    Devuelve: int >= 0. Si la clave no existe en Redis, devuelve 0
    (comportamiento por defecto: sin llamadas en vivo activas).
    """
    try:
        count = await redis_client.get(VOICE_ACTIVE_CALLS_KEY)
        if count is None:
            return 0
        return int(count)
    except Exception:
        logger.warning(
            "gpu_priority_check_failed",
            key=VOICE_ACTIVE_CALLS_KEY,
            exc_info=True,
        )
        return 0  # Fail-open: si algo falla, asume sin llamadas activas


async def increment_active_calls(
    redis_client: redis_asyncio.Redis,
) -> int:
    """Incrementa el contador de llamadas en vivo activas (llamada recibida).

    Usado por `voice_gateway` al recibir una llamada entrante.
    Devuelve: nuevo valor del contador.
    """
    try:
        new_count = await redis_client.incr(VOICE_ACTIVE_CALLS_KEY)
        logger.info(
            "gpu_priority_call_started",
            active_calls=new_count,
        )
        return new_count
    except Exception:
        logger.error(
            "gpu_priority_increment_failed",
            key=VOICE_ACTIVE_CALLS_KEY,
            exc_info=True,
        )
        return 0


async def decrement_active_calls(
    redis_client: redis_asyncio.Redis,
) -> int:
    """Decrementa el contador de llamadas en vivo activas (llamada finalizada).

    Usado por `voice_gateway` al colgar. Nunca permite valores negativos
    (garantía de seguridad).
    Devuelve: nuevo valor del contador.
    """
    try:
        new_count = await redis_client.decr(VOICE_ACTIVE_CALLS_KEY)
        # Protección contra decrementos excesivos (bug o ataque)
        if new_count < 0:
            await redis_client.set(VOICE_ACTIVE_CALLS_KEY, 0)
            logger.warning(
                "gpu_priority_negative_count_reset",
                previous_count=new_count,
            )
            return 0
        logger.info(
            "gpu_priority_call_ended",
            active_calls=new_count,
        )
        return new_count
    except Exception:
        logger.error(
            "gpu_priority_decrement_failed",
            key=VOICE_ACTIVE_CALLS_KEY,
            exc_info=True,
        )
        return 0


async def should_pause_batch_for_voice(
    redis_client: redis_asyncio.Redis,
) -> bool:
    """Consulta si el `stt_worker` batch debe pausarse (hay llamadas en vivo activas).

    Llamado por `drain_one` ANTES de procesar un job: si devuelve `True`,
    el worker pausa y retorna sin procesar (spriorización de GPU).
    """
    count = await check_voice_active_calls(redis_client)
    return count > 0
