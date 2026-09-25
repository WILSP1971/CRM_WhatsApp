"""Cola Redis `recording:fetch:jobs` — solicitudes de descarga de grabaciones
desde un PBX EXTERNO (SPEC-037, ADR-010). Consumida SOLO por
`app/workers/recording_fetch_worker.py`, activo únicamente si
`PBX_EXTERNAL_ENABLED=true` (SUP-42: inerte por defecto, topología on-prem).

Este módulo transporta la URL de descarga + metadatos (NUNCA el binario del
audio, que aún no se ha descargado) — mismo criterio de contrato mínimo que
el resto de colas del proyecto. `app/integrations/pbx/webhook.py` encola
AQUÍ (en vez de `pbx:recordings:inbound`) únicamente cuando el PBX notifica
una URL en vez de adjuntar el fichero (variante habilitada solo con PBX
externo); el camino feliz por defecto (PBX on-prem que entrega el fichero
directamente) nunca usa esta cola.

CHECKPOINT C3: `REDIS_URL` viene exclusivamente de `Settings` (env).
CHECKPOINT SENSIBLE (ADR-010): este módulo NO descarga nada — solo
transporta la referencia (URL) hasta `recording_fetch_worker`, que es quien
invoca `app/services/telefonia/pbx_client.py` con la allowlist de host.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import redis.asyncio as redis_asyncio

RECORDING_FETCH_QUEUE_KEY = "recording:fetch:jobs"


@dataclass(frozen=True)
class RecordingFetchJob:
    """Solicitud de descarga de una grabación notificada por URL (PBX
    externo, ADR-010). `recording_url` se valida por `pbx_client.py` contra
    el host único permitido (configurado en `Settings`, ver
    `app/core/config.py`) ANTES de cualquier petición — este dataclass solo
    transporta el dato, no lo valida."""

    call_id: str
    numero: str
    numero_destino: str
    direccion: str
    recording_url: str
    duracion: int | None = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_json(self) -> str:
        return json.dumps(
            {
                "event_id": self.event_id,
                "call_id": self.call_id,
                "numero": self.numero,
                "numero_destino": self.numero_destino,
                "direccion": self.direccion,
                "duracion": self.duracion,
                "recording_url": self.recording_url,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "RecordingFetchJob":
        data = json.loads(raw)
        return cls(
            event_id=data["event_id"],
            call_id=data["call_id"],
            numero=data["numero"],
            numero_destino=data["numero_destino"],
            direccion=data["direccion"],
            duracion=data.get("duracion"),
            recording_url=data["recording_url"],
        )


async def enqueue_recording_fetch_job(
    redis_client: redis_asyncio.Redis, *, job: RecordingFetchJob
) -> RecordingFetchJob:
    """Encola una solicitud de descarga (SOLO PBX externo, ADR-010)."""
    await redis_client.rpush(RECORDING_FETCH_QUEUE_KEY, job.to_json())
    return job


async def dequeue_recording_fetch_job(
    redis_client: redis_asyncio.Redis, *, timeout_seconds: int = 0
) -> RecordingFetchJob | None:
    """Extrae (bloqueante opcional) la siguiente solicitud de descarga
    pendiente. `timeout_seconds=0` hace `LPOP` no bloqueante (tests);
    `timeout_seconds>0` hace `BLPOP` (uso previsto por
    `recording_fetch_worker`)."""
    if timeout_seconds > 0:
        result = await redis_client.blpop(
            [RECORDING_FETCH_QUEUE_KEY], timeout=timeout_seconds
        )
        if result is None:
            return None
        _, raw = result
    else:
        raw = await redis_client.lpop(RECORDING_FETCH_QUEUE_KEY)
        if raw is None:
            return None
    return RecordingFetchJob.from_json(raw)
