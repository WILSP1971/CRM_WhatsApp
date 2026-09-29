"""Cola Redis `tts:jobs` — trabajos de síntesis de voz pendientes para el
`tts_worker` (SPEC-069, Entregable #6, ADR-014).

Mismo patrón que `app.core.stt_queue` (SPEC-037/038): cola Redis persistente
(`appendonly yes`), consumida por un worker dedicado que vive en la red
`ia_internal internal:true` (`tts_worker`, SIN egress, ADR-005). Este módulo
NUNCA importa `app/integrations/whatsapp/` ni ningún cliente de red — solo
transporta la referencia al `RagDraft` YA aprobado (o pendiente de escucha) y
el guion a sintetizar, nunca un binario.

Formato del job (contrato con `tts_worker`):
`{draft_id, tenant_id, conversation_id, texto, modo, enqueued_at_epoch_seconds}`
- `draft_id`: UUID de la fila `rag_drafts` (SPEC-019/068) — el `tts_worker` la
  usa para releer el guion vigente bajo RLS y escribir `tts_estado`/
  `audio_salida_ref` (si aplica).
- `tenant_id`: para que el `tts_worker` fije `app.tenant_id` de sesión (RLS,
  ADR-004/ADR-008) antes de tocar `rag_drafts`.
- `conversation_id`: para resolver el destino de envío (contacto/canal) SOLO
  en la ruta por defecto (`modo="enviar"`); en la ruta de escucha
  (`modo="escuchar"`) se usa únicamente para trazabilidad/logs, nunca se
  dispara un envío.
- `texto`: el guion YA congelado en el momento de encolar (snapshot de
  `draft.content`) — el worker sintetiza EXACTAMENTE este texto, nunca
  vuelve a leer `rag_drafts.content` por si cambiara entre el encolado y el
  consumo (evita una condición de carrera "aprobé X pero sonó Y").
- `modo`: `"enviar"` (ruta por defecto, RF-03: tras aprobar el guion, generar
  Y disparar el envío del clip) o `"escuchar"` (ruta opcional bajo demanda,
  RF-04: generar sin enviar, para que el agente lo apruebe/rechace antes de
  decidir el envío). Gobierna el comportamiento POST-síntesis del
  `tts_worker`; la síntesis en sí (motor/normalización/transcodificación) es
  idéntica en ambos modos.
- `enqueued_at_epoch_seconds`: instante (epoch, `time.time()`) en que este
  módulo encoló el mensaje — permite instrumentar la latencia real de cola
  (mismo criterio que `SttTranscriptionJob`, SPEC-038 post-revisión).

CHECKPOINT C3: `REDIS_URL` viene exclusivamente de `Settings` (env).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

import redis.asyncio as redis_asyncio

TTS_JOBS_QUEUE_KEY = "tts:jobs"

# Modos válidos del job (RF-03/RF-04 SPEC-069, Q1-C ADR-014).
TTS_JOB_MODO_ENVIAR = "enviar"
TTS_JOB_MODO_ESCUCHAR = "escuchar"
TTS_JOB_MODOS_VALIDOS = {TTS_JOB_MODO_ENVIAR, TTS_JOB_MODO_ESCUCHAR}


@dataclass(frozen=True)
class TtsSynthesisJob:
    """Trabajo de síntesis TTS encolado tras la aprobación del guion (ruta
    por defecto) o tras la solicitud explícita "escuchar antes de enviar"
    (ruta opcional) — SPEC-069, ADR-014.

    `job_id` es solo para trazabilidad en logs (no sustituye la idempotencia
    real del `tts_worker`, que se basa en `tts_estado`/`sent_message_id`,
    responsabilidad de ese módulo).
    """

    draft_id: str
    tenant_id: str
    conversation_id: str
    texto: str
    modo: str
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    enqueued_at_epoch_seconds: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.modo not in TTS_JOB_MODOS_VALIDOS:
            raise ValueError(
                f"modo de job TTS inválido: {self.modo!r} "
                f"(válidos: {sorted(TTS_JOB_MODOS_VALIDOS)})"
            )

    def to_json(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "draft_id": self.draft_id,
                "tenant_id": self.tenant_id,
                "conversation_id": self.conversation_id,
                "texto": self.texto,
                "modo": self.modo,
                "enqueued_at_epoch_seconds": self.enqueued_at_epoch_seconds,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "TtsSynthesisJob":
        data = json.loads(raw)
        kwargs = {
            "job_id": data["job_id"],
            "draft_id": data["draft_id"],
            "tenant_id": data["tenant_id"],
            "conversation_id": data["conversation_id"],
            "texto": data["texto"],
            "modo": data["modo"],
        }
        if "enqueued_at_epoch_seconds" in data:
            kwargs["enqueued_at_epoch_seconds"] = data["enqueued_at_epoch_seconds"]
        return cls(**kwargs)


async def enqueue_tts_job(
    redis_client: redis_asyncio.Redis,
    *,
    draft_id: uuid.UUID | str,
    tenant_id: uuid.UUID | str,
    conversation_id: uuid.UUID | str,
    texto: str,
    modo: str,
) -> TtsSynthesisJob:
    """Encola el trabajo de síntesis DESPUÉS de que el guion ya está
    disponible: `modo="enviar"` SOLO tras `approve_and_send` (SPEC-019) haber
    persistido el `Message`/transicionado el `RagDraft` a `aprobado`;
    `modo="escuchar"` tras la solicitud explícita del agente (ruta opcional,
    el borrador puede seguir mutable). Nunca se llama antes de que exista un
    guion vigente que sintetizar.
    """
    job = TtsSynthesisJob(
        draft_id=str(draft_id),
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        texto=texto,
        modo=modo,
    )
    await redis_client.rpush(TTS_JOBS_QUEUE_KEY, job.to_json())
    return job


async def dequeue_tts_job(
    redis_client: redis_asyncio.Redis,
    *,
    timeout_seconds: int = 0,
) -> TtsSynthesisJob | None:
    """Extrae (bloqueante opcional) el siguiente trabajo pendiente.

    `timeout_seconds=0` hace un `LPOP` no bloqueante (usado en tests);
    `timeout_seconds>0` hace `BLPOP` (uso previsto por `tts_worker`).
    """
    if timeout_seconds > 0:
        result = await redis_client.blpop([TTS_JOBS_QUEUE_KEY], timeout=timeout_seconds)
        if result is None:
            return None
        _, raw = result
    else:
        raw = await redis_client.lpop(TTS_JOBS_QUEUE_KEY)
        if raw is None:
            return None
    return TtsSynthesisJob.from_json(raw)
