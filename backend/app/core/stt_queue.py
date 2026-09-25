"""Cola Redis `stt:jobs` — trabajos de transcripción pendientes para el
`stt_worker` (SPEC-037 encola, SPEC-038 consume — SPEC-038 está FUERA de
alcance de SPEC-037; este módulo solo define el contrato del mensaje y el
lado de encolado).

Mismo patrón que `app.core.rag_queue`/`app.core.sentiment_queue`: cola Redis
persistente (`appendonly yes`), consumida por un worker dedicado que vive en
la red `ia_internal internal:true` (`stt_worker`, SIN egress, ADR-009). Este
módulo NUNCA importa nada de `app/services/telefonia/` ni del cliente de
descarga del PBX (auditado por `check-externos-backend.sh` sección 11): solo
transporta la referencia al audio YA almacenado en el almacén cifrado
on-prem, nunca el binario ni una URL externa.

Formato del job (contrato con SPEC-038):
`{call_id, audio_ref, tenant_id, enqueued_at_epoch_seconds, destino}`
- `call_id`: UUID de la fila `calls` (SPEC-036) ya persistida — el
  `stt_worker` la usa para escribir `call_transcripts.call_id` (FK).
- `audio_ref`: referencia al almacén cifrado on-prem (SPEC-035), NUNCA una
  ruta a un host externo ni un binario embebido — el `stt_worker` lee el
  audio directamente del volumen compartido (`AUDIO_STORAGE_PATH`).
- `tenant_id`: para que el `stt_worker` fije `app.tenant_id` de sesión (RLS,
  ADR-004) antes de escribir `call_transcripts`.
- `enqueued_at_epoch_seconds`: instante (epoch, `time.time()`) en que este
  módulo encoló el mensaje — permite a `stt_worker` calcular la latencia real
  de cola (`stt_queue_latency_seconds`, corrección SPEC-038 post-revisión
  BLACK PANTHER/WOLVERINE: antes NUNCA se poblaba en producción real, solo en
  tests que la inyectaban manualmente). Con default de fábrica (`time.time`
  en el momento de construir el dataclass) para que mensajes deserializados
  de un formato ANTERIOR sin este campo (`from_json`, sistema nuevo sin
  mensajes en vuelo, pero se tolera por robustez) no rompan — en ese caso se
  aproxima al momento de la propia deserialización en vez de fallar.
- `destino`: campo AÑADIDO por SPEC-055 (aditivo, ADR-007), gobierna el SINK
  de escritura que consumirá `stt_worker` (SPEC-056, fuera de alcance aquí:
  el `stt_worker` de HOY sigue leyendo únicamente `job.call_id` y NUNCA lee
  `destino`, por lo que su comportamiento con los jobs de llamadas del
  Entregable #4 es BYTE A BYTE el mismo, con o sin este campo). Formato
  `"call:{id}"` (DEFAULT, preserva el contrato original de SPEC-037 para
  quien no lo especifica — p.ej. `recording_ingest_worker`, que sigue
  encolando llamadas sin pasar `destino`) o `"message:{id}"` (SPEC-055: una
  nota de voz de WhatsApp, `id` = `Message.id`, NUNCA `Call.id`/`call_id`,
  ADR-013). SPEC-055 (aquí, PRODUCTOR) solo necesita poder escribir
  `destino="message:{id}"` al encolar desde el worker de ingesta de
  WhatsApp; SPEC-056 (CONSUMIDOR, fuera de alcance) implementará el
  enrutado real dentro de `stt_worker` según el prefijo de `destino`.

CHECKPOINT C3: `REDIS_URL` viene exclusivamente de `Settings` (env).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

import redis.asyncio as redis_asyncio

STT_JOBS_QUEUE_KEY = "stt:jobs"

# Default del campo `destino` (SPEC-055, aditivo): preserva el contrato
# ORIGINAL de SPEC-037 para todo job que no lo especifique explícitamente
# (los jobs de llamadas del Entregable #4 siguen construyéndose exactamente
# igual, ver `enqueue_stt_job` más abajo). El `{id}` real se interpola en
# `enqueue_stt_job`/`SttTranscriptionJob.__post_init__` a partir de `call_id`.
_DESTINO_CALL_PREFIX = "call:"
_DESTINO_MESSAGE_PREFIX = "message:"


@dataclass(frozen=True)
class SttTranscriptionJob:
    """Trabajo de transcripción encolado tras almacenar el audio (SPEC-037,
    extendido por SPEC-055 con el campo `destino`).

    `job_id` es solo para trazabilidad en logs (no sustituye la idempotencia
    real del `stt_worker`, que debe basarse en si `calls.estado` ya es
    `"transcrita"`/existe `call_transcripts.call_id`, responsabilidad de
    SPEC-038).

    `destino` (SPEC-055, aditivo): gobierna el SINK de escritura que
    consumirá `stt_worker` (SPEC-056, fuera de alcance de esta SPEC — el
    `stt_worker` de HOY ignora este campo por completo, solo lee
    `job.call_id`). Por defecto `"call:{call_id}"` (mismo `call_id` del job,
    preserva el comportamiento BYTE A BYTE de los jobs de llamadas
    existentes que no lo especifican). SPEC-055 lo usa para producir
    `"message:{message_id}"` al encolar desde la ingesta de WhatsApp
    (`whatsapp_inbound_worker`), pasando `call_id=str(message.id)` como
    valor de correlación transversal (el `stt_worker` de HOY sigue tratando
    ese valor igual que cualquier otro `call_id` recibido, sin enrutar según
    `destino` — ese enrutado es SPEC-056)."""

    call_id: str
    audio_ref: str
    tenant_id: str
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    enqueued_at_epoch_seconds: float = field(default_factory=time.time)
    destino: str | None = None

    def __post_init__(self) -> None:
        if self.destino is None:
            # `object.__setattr__` porque el dataclass es `frozen=True`
            # (mismo patrón que el resto de campos con `default_factory`).
            object.__setattr__(
                self, "destino", f"{_DESTINO_CALL_PREFIX}{self.call_id}"
            )

    def to_json(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "call_id": self.call_id,
                "audio_ref": self.audio_ref,
                "tenant_id": self.tenant_id,
                "enqueued_at_epoch_seconds": self.enqueued_at_epoch_seconds,
                "destino": self.destino,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "SttTranscriptionJob":
        data = json.loads(raw)
        kwargs = {
            "job_id": data["job_id"],
            "call_id": data["call_id"],
            "audio_ref": data["audio_ref"],
            "tenant_id": data["tenant_id"],
        }
        # Compatibilidad hacia atrás: un mensaje de un formato ANTERIOR sin
        # `enqueued_at_epoch_seconds` (no debería existir en producción real
        # -- sistema nuevo sin mensajes en vuelo -- pero se tolera por
        # robustez) no debe romper la deserialización; se aproxima al
        # instante de la propia deserialización en vez de fallar.
        if "enqueued_at_epoch_seconds" in data:
            kwargs["enqueued_at_epoch_seconds"] = data["enqueued_at_epoch_seconds"]
        # Compatibilidad hacia atrás (SPEC-055, aditivo): un mensaje de un
        # formato ANTERIOR sin `destino` (jobs en vuelo encolados antes de
        # este cambio) no debe romper la deserialización; `__post_init__`
        # calcula el default `"call:{call_id}"` cuando no viene en el JSON.
        if "destino" in data and data["destino"] is not None:
            kwargs["destino"] = data["destino"]
        return cls(**kwargs)


async def enqueue_stt_job(
    redis_client: redis_asyncio.Redis,
    *,
    call_id: uuid.UUID | str,
    audio_ref: str,
    tenant_id: uuid.UUID | str,
    destino: str | None = None,
) -> SttTranscriptionJob:
    """Encola el trabajo de transcripción DESPUÉS de que el audio ya quedó
    almacenado cifrado en el almacén on-prem y la `call`/`message` ya está
    persistida (RF-04 SPEC-037; SPEC-055 reutiliza esta misma función para
    encolar notas de voz de WhatsApp). Nunca se llama antes de esos dos
    pasos.

    `destino` (SPEC-055, aditivo, keyword-only, default `None`): si se omite
    (caso de HOY de `recording_ingest_worker`, llamadas del Entregable #4),
    `SttTranscriptionJob.__post_init__` calcula el default
    `"call:{call_id}"` — BYTE A BYTE el mismo comportamiento que antes de
    esta SPEC. `whatsapp_inbound_worker` (SPEC-055) pasa explícitamente
    `destino=f"message:{message.id}"`."""
    job = SttTranscriptionJob(
        call_id=str(call_id),
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        destino=destino,
    )
    await redis_client.rpush(STT_JOBS_QUEUE_KEY, job.to_json())
    return job


async def dequeue_stt_job(
    redis_client: redis_asyncio.Redis,
    *,
    timeout_seconds: int = 0,
) -> SttTranscriptionJob | None:
    """Extrae (bloqueante opcional) el siguiente trabajo pendiente.

    `timeout_seconds=0` hace un `LPOP` no bloqueante (usado en tests);
    `timeout_seconds>0` hace `BLPOP` (uso previsto por `stt_worker`, SPEC-038).
    """
    if timeout_seconds > 0:
        result = await redis_client.blpop([STT_JOBS_QUEUE_KEY], timeout=timeout_seconds)
        if result is None:
            return None
        _, raw = result
    else:
        raw = await redis_client.lpop(STT_JOBS_QUEUE_KEY)
        if raw is None:
            return None
    return SttTranscriptionJob.from_json(raw)
