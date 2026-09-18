"""Cliente Redis y utilidades de pub/sub del WebChat — SPEC-015.

CHECKPOINT C3: la URL de conexión (`REDIS_URL`) se lee exclusivamente de
`app.core.config.get_settings()` (variables de entorno), nunca hardcodeada.

Namespacing de canales (riesgo R-23, "fuga cross-tenant en pub/sub"): todo
canal de pub/sub incluye el `tenant_id` en el nombre, de forma que un
suscriptor de otro tenant NUNCA está suscrito al canal correcto aunque el
proceso comparta la misma conexión Redis física. El aislamiento se refuerza
en `ws_chat.py`, que solo se suscribe al canal de la conversación/tenant
resuelto por el JWT (nunca por un parámetro que el cliente pueda manipular).
"""

from __future__ import annotations

import redis.asyncio as redis_asyncio

from app.core.config import get_settings

settings = get_settings()

_redis_client: redis_asyncio.Redis | None = None


def channel_name(tenant_id, conversation_id) -> str:
    """Nombre del canal Redis pub/sub para una conversación de un tenant.

    Namespaced como `chat:{tenant_id}:{conversation_id}` para que el
    aislamiento por tenant sea estructural: nunca se construye ni se escucha
    un canal sin el tenant_id resuelto del JWT (R-23).
    """
    return f"chat:{tenant_id}:{conversation_id}"


def get_redis_client() -> redis_asyncio.Redis:
    """Cliente Redis async (singleton de proceso) para pub/sub del WebChat.

    Usa `redis.asyncio` porque el endpoint WebSocket de FastAPI es async; una
    sola conexión/pool se reutiliza entre conexiones WS del mismo worker.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_asyncio.from_url(
            settings.redis_url, decode_responses=True
        )
    return _redis_client


async def close_redis_client() -> None:
    """Cierra el cliente Redis (usado en el lifespan de FastAPI y en tests)."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
