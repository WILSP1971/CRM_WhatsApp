"""Cola Redis de mensajes SALIENTES aprobados, pendientes de envío por Graph
API — SPEC-029, ADR-006. Consumida por `app/workers/wa_send_worker.py`.

Mismo patrón que `app.core.whatsapp_queue` (SPEC-026/027) y
`app.core.rag_queue`/`sentiment_queue`: la cola es persistente (Redis
`appendonly yes`) para que un reinicio de `api`/worker NUNCA pierda un envío
ya aprobado por el humano — el job sigue en Redis hasta que
`wa_send_worker` lo consume con éxito.

CHECKPOINT SENSIBLE (RF-02 SPEC-029): SOLO se encola un job DESPUÉS de que
`draft_review_service.approve_and_send` (SPEC-019, aprobación humana
explícita) ya persistió el `Message` saliente. Este módulo no decide cuándo
enviar — solo transporta la referencia (`message_id`) del mensaje YA
aprobado hasta el worker de envío. No contiene lógica de ventana de 24 h ni
de plantilla (eso vive en `wa_send_worker`, más cerca del cliente Graph).

CHECKPOINT C3: `REDIS_URL` viene exclusivamente de `Settings` (env). El job
NUNCA lleva el token de WhatsApp ni el contenido crudo del mensaje más allá
de lo necesario para que el worker lo relea de Postgres bajo RLS (se
transporta `message_id`/`tenant_id`/`conversation_id`, no un payload libre).

Extensión aditiva (Entregable #6, SPEC-069, ADR-014): `tipo`/`audio_ref`/
`audio_mime_type` (todos con default que preserva el comportamiento EXACTO
anterior — `tipo="texto"`, los otros dos `None`) permiten que
`approve_draft_endpoint`, tras generar Y aprobar un clip TTS (`respuesta_
modo="audio"`), encole el ENVÍO del audio por el MISMO worker/cola que el
texto — reutilizando `wa_send_worker`/`graph_client.send_audio_message` en
vez de duplicar la lógica de resolución de `phone_number_id`/ventana de 24h/
plantilla. `audio_ref` es una referencia OPACA al almacén cifrado
(`audio_store.py`, SPEC-035) — el job NUNCA transporta el binario del clip
por Redis (evita inflar el payload JSON con audio, y mantiene el mismo
criterio de "solo referencias, nunca binarios" que `stt_queue`/`tts_queue`).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import redis.asyncio as redis_asyncio

OUTBOUND_QUEUE_KEY = "wa:outbound"

# Tipos de envío válidos (SPEC-069, aditivo). "texto" es el default histórico
# (SPEC-029): un job sin `tipo` explícito (formato anterior) se comporta
# IDÉNTICO a hoy. "audio" es el clip TTS de salida del Entregable #6.
OUTBOUND_TIPOS_VALIDOS = {"texto", "audio"}
OUTBOUND_TIPO_TEXTO = "texto"
OUTBOUND_TIPO_AUDIO = "audio"


@dataclass(frozen=True)
class OutboundSendJob:
    """Job encolado tras la aprobación humana de un borrador/mensaje
    saliente por canal WhatsApp (SPEC-019 + SPEC-029), extendido por
    SPEC-069 para el envío de un clip TTS de salida.

    `message_id`/`tenant_id`/`conversation_id`: identifican el `Message` ya
    persistido (estado `estado_entrega="enviado"` en Postgres desde que se
    creó, pendiente de transporte real) que el worker debe enviar por Graph
    API. `job_id` es solo para trazabilidad en logs (no sustituye la
    idempotencia real, que se basa en que el worker solo envía mensajes SIN
    `wamid` todavía — ver `wa_send_worker.py`).

    `tipo` (aditivo, default `"texto"`): gobierna la RAMA de envío que
    ejecuta `wa_send_worker` — `"texto"` es EXACTAMENTE el comportamiento de
    SPEC-029 (sin cambio); `"audio"` (SPEC-069) envía el clip referenciado
    por `audio_ref`/`audio_mime_type` con `GraphApiClient.
    send_audio_message` en vez de `send_text_message`/`send_template_message`
    (el audio NUNCA usa plantilla HSM: WhatsApp no soporta plantillas de
    tipo audio arbitrario, así que fuera de la ventana de 24h un job `audio`
    se marca `failed` sin intentar la Graph API, igual criterio fail-closed
    que el texto sin plantilla configurada).
    """

    tenant_id: str
    conversation_id: str
    message_id: str
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tipo: str = OUTBOUND_TIPO_TEXTO
    audio_ref: str | None = None
    audio_mime_type: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "tenant_id": self.tenant_id,
                "conversation_id": self.conversation_id,
                "message_id": self.message_id,
                "tipo": self.tipo,
                "audio_ref": self.audio_ref,
                "audio_mime_type": self.audio_mime_type,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "OutboundSendJob":
        data = json.loads(raw)
        kwargs = {
            "tenant_id": data["tenant_id"],
            "conversation_id": data["conversation_id"],
            "message_id": data["message_id"],
            "job_id": data["job_id"],
        }
        # Compatibilidad hacia atrás (SPEC-069, aditivo): un mensaje de un
        # formato ANTERIOR sin estos 3 campos (jobs en vuelo encolados antes
        # de este cambio) no debe romper la deserialización — se comporta
        # como el job de texto de siempre.
        if "tipo" in data and data["tipo"] is not None:
            kwargs["tipo"] = data["tipo"]
        if "audio_ref" in data:
            kwargs["audio_ref"] = data["audio_ref"]
        if "audio_mime_type" in data:
            kwargs["audio_mime_type"] = data["audio_mime_type"]
        return cls(**kwargs)


async def enqueue_outbound_send(
    redis_client: redis_asyncio.Redis,
    *,
    tenant_id: uuid.UUID | str,
    conversation_id: uuid.UUID | str,
    message_id: uuid.UUID | str,
    tipo: str = OUTBOUND_TIPO_TEXTO,
    audio_ref: str | None = None,
    audio_mime_type: str | None = None,
) -> OutboundSendJob:
    """Encola el envío de un mensaje YA aprobado por un humano (RF-02).

    Debe llamarse EXCLUSIVAMENTE después de que el `Message` esté persistido
    (p.ej. desde `approve_draft_endpoint`/`draft_review_service.
    approve_and_send`), nunca antes ni de forma automática. `tipo="audio"`
    (SPEC-069) además requiere `audio_ref` ya poblado (el clip TTS ya
    generado y almacenado transitoriamente por `tts_worker`, cifrado vía
    `audio_store.py`).
    """
    job = OutboundSendJob(
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        message_id=str(message_id),
        tipo=tipo,
        audio_ref=audio_ref,
        audio_mime_type=audio_mime_type,
    )
    await redis_client.rpush(OUTBOUND_QUEUE_KEY, job.to_json())
    return job


async def dequeue_outbound_send(
    redis_client: redis_asyncio.Redis,
    *,
    timeout_seconds: int = 0,
) -> OutboundSendJob | None:
    """Extrae (bloqueante opcional) el siguiente job de envío pendiente.

    `timeout_seconds=0` hace un `LPOP` no bloqueante (usado en tests);
    `timeout_seconds>0` hace `BLPOP` (uso previsto por `wa_send_worker`).
    """
    if timeout_seconds > 0:
        result = await redis_client.blpop([OUTBOUND_QUEUE_KEY], timeout=timeout_seconds)
        if result is None:
            return None
        _, raw = result
    else:
        raw = await redis_client.lpop(OUTBOUND_QUEUE_KEY)
        if raw is None:
            return None
    return OutboundSendJob.from_json(raw)
