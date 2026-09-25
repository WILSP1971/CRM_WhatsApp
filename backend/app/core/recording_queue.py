"""Cola Redis para eventos entrantes crudos de grabaciones del PBX
(`pbx:recordings:inbound`) — SPEC-037 (webhook + worker de ingesta),
ADR-007/ADR-010.

Mismo patrón que `app.core.whatsapp_queue` (SPEC-026/027): el webhook de
grabaciones (`app/integrations/pbx/webhook.py`) valida `verify_token`/firma y
responde **ACK rápido** SIN dedup por `call_id`, SIN resolución de tenant y
SIN escritura en Postgres — todo eso lo hace el
`recording_ingest_worker` (SPEC-037) de forma asíncrona (RNF-02).

CHECKPOINT SENSIBLE: el job transporta el AUDIO ya recibido (bytes) más los
metadatos declarados por el PBX (`call_id`, `numero`, `numero_destino`,
`direccion`, `duracion`). El audio viaja en Redis SOLO el tiempo que tarda el
worker en consumir el job (persistente en `appendonly yes`, igual que el
resto de colas) y jamás sale de la red interna del host — no hay egress
nuevo en este módulo (transporte de recepción, no inferencia).

CHECKPOINT C3: `REDIS_URL` viene exclusivamente de `Settings` (env).
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, field

import redis.asyncio as redis_asyncio

RECORDING_INBOUND_QUEUE_KEY = "pbx:recordings:inbound"


@dataclass(frozen=True)
class RecordingInboundJob:
    """Job encolado por el webhook de grabaciones para el worker de ingesta
    (SPEC-037).

    `audio_bytes_b64`: el fichero de audio (WAV/OGG) recibido, codificado en
    base64 para viajar como texto JSON en Redis (mismo criterio de
    serialización simple que el resto de colas del proyecto). `call_id`,
    `numero`, `numero_destino`, `direccion`, `duracion` son los metadatos
    DECLARADOS por el PBX tal cual llegaron — el worker es quien valida su
    forma y resuelve el tenant (ADR-007), este módulo no interpreta nada.
    """

    call_id: str
    numero: str
    numero_destino: str
    direccion: str
    audio_bytes_b64: str
    duracion: int | None = None
    content_type: str = "audio/wav"
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
                "content_type": self.content_type,
                "audio_bytes_b64": self.audio_bytes_b64,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "RecordingInboundJob":
        data = json.loads(raw)
        return cls(
            event_id=data["event_id"],
            call_id=data["call_id"],
            numero=data["numero"],
            numero_destino=data["numero_destino"],
            direccion=data["direccion"],
            duracion=data.get("duracion"),
            content_type=data.get("content_type", "audio/wav"),
            audio_bytes_b64=data["audio_bytes_b64"],
        )

    @property
    def audio_bytes(self) -> bytes:
        return base64.b64decode(self.audio_bytes_b64)


def build_recording_inbound_job(
    *,
    call_id: str,
    numero: str,
    numero_destino: str,
    direccion: str,
    audio_bytes: bytes,
    duracion: int | None = None,
    content_type: str = "audio/wav",
) -> RecordingInboundJob:
    """Construye el job a partir de los bytes crudos del audio (helper para
    que el webhook no maneje base64 directamente)."""
    return RecordingInboundJob(
        call_id=call_id,
        numero=numero,
        numero_destino=numero_destino,
        direccion=direccion,
        duracion=duracion,
        content_type=content_type,
        audio_bytes_b64=base64.b64encode(audio_bytes).decode("ascii"),
    )


async def enqueue_recording_inbound_event(
    redis_client: redis_asyncio.Redis,
    *,
    job: RecordingInboundJob,
) -> RecordingInboundJob:
    """Encola el evento crudo (audio + metadatos, ya verificado por
    firma/verify_token) para que el worker de SPEC-037 lo procese de forma
    asíncrona (RNF-02, ACK rápido)."""
    await redis_client.rpush(RECORDING_INBOUND_QUEUE_KEY, job.to_json())
    return job


async def dequeue_recording_inbound_event(
    redis_client: redis_asyncio.Redis,
    *,
    timeout_seconds: int = 0,
) -> RecordingInboundJob | None:
    """Extrae (bloqueante opcional) el siguiente evento crudo de la cola.

    `timeout_seconds=0` hace un `LPOP` no bloqueante (usado en tests);
    `timeout_seconds>0` hace `BLPOP` (uso previsto por el worker de ingesta).
    """
    if timeout_seconds > 0:
        result = await redis_client.blpop(
            [RECORDING_INBOUND_QUEUE_KEY], timeout=timeout_seconds
        )
        if result is None:
            return None
        _, raw = result
    else:
        raw = await redis_client.lpop(RECORDING_INBOUND_QUEUE_KEY)
        if raw is None:
            return None
    return RecordingInboundJob.from_json(raw)
