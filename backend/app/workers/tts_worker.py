"""TTS Worker — síntesis de voz 100% local con Piper (SPEC-067/069, ADR-014).

`process_job` procesa UN trabajo ya extraído de `tts:jobs`
(`TtsSynthesisJob`, encolado por `app.api.rag` tras la aprobación del guion —
ruta por defecto — o tras la solicitud "escuchar antes de enviar" — ruta
opcional, `app.core.tts_queue`):

  1. Bajo RLS (`set_tenant_session`, ADR-004/008), transiciona
     `rag_drafts.tts_estado` a `"generando"` con un UPDATE condicional
     ATÓMICO (mismo criterio de `draft_review_service._atomic_transition`) —
     IDEMPOTENCIA (RF-02): si el borrador YA tiene un clip `"listo"` para
     este mismo job (o ya está `"generando"` por otro worker/reintento), este
     job es no-op — nunca se sintetiza dos veces ni se produce un segundo
     clip para el mismo guion aprobado.
  2. Sintetiza el guion (`job.texto`, snapshot congelado al encolar — NUNCA
     se relee `rag_drafts.content` aquí) con
     `app.services.telefonia.tts_engine.synthesize_to_ogg_opus` — 100% local,
     CPU-only, `ia_internal` sin egress.
  3. Persiste el clip TRANSITORIAMENTE en el almacén cifrado
     (`app.services.telefonia.audio_store`, SPEC-035, MISMO almacén que el
     audio ENTRANTE) — necesario para que `wa_send_worker` (otro proceso,
     ruta "enviar") o el endpoint de descarga bajo demanda (ruta "escuchar",
     SPEC-070 lo consume) puedan leer el binario sin que este worker importe
     el cliente de WhatsApp ni exponga el binario por Redis.
  4. `tts_estado` transiciona a `"listo"`/`"error"` (RF-03/RF-04/RF-07).
  5. SOLO si `job.modo == "enviar"`: encola el envío por
     `app.core.whatsapp_outbound_queue` (consumido por `wa_send_worker`, que
     es el único autorizado a hablar con `app.integrations.whatsapp/`) —
     este worker JAMÁS importa ni ejecuta ese cliente (CHECKPOINT SENSIBLE
     abajo). Si `job.modo == "escuchar"`, el clip queda `"listo"` en el
     almacén SIN encolar ningún envío — el contrato que consume SPEC-070
     (endpoint `GET .../drafts/{id}/audio`, `app/api/rag.py`) sirve ese
     mismo `audio_ref` bajo demanda.

CHECKPOINT SENSIBLE (RNF-01, ADR-005/006/009/012): este módulo NUNCA importa
`httpx` ni `app/integrations/whatsapp/` (auditado por
`check-externos-backend.sh`) — la única salida hacia el cliente de WhatsApp
es a través de la cola `wa:outbound`/`wa_send_worker`, un proceso SEPARADO en
otra red (`app` + `ia_internal`). El servicio TTS mismo vive SOLO en
`ia_internal internal:true`, sin ruta a internet.

Robustez (mismo criterio que el resto de workers, RNF-05): un fallo
procesando un job se loguea con `exc_info` y NO detiene el loop del worker.
"""

from __future__ import annotations

import asyncio
import signal
import time
import uuid
from typing import Callable

import redis.asyncio as redis_asyncio
import sqlalchemy as sa
import structlog
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis_client
from app.core.tts_queue import (
    TTS_JOB_MODO_ENVIAR,
    TTS_JOBS_QUEUE_KEY,
    TtsSynthesisJob,
    dequeue_tts_job,
)
from app.core.whatsapp_outbound_queue import (
    OUTBOUND_TIPO_AUDIO,
    enqueue_outbound_send,
)
from app.core.worker_resilience import resilient_worker_loop
from app.db.session import SessionLocal, set_tenant_session
from app.models.rag_draft import RagDraft
from app.services.telefonia import audio_store
from app.services.telefonia.tts_engine import (
    SynthesizableTextTooLongError,
    TtsEngineError,
    synthesize_to_ogg_opus,
)

logger = structlog.get_logger(__name__)

_TTS_ESTADO_GENERANDO = "generando"
_TTS_ESTADO_LISTO = "listo"
_TTS_ESTADO_ERROR = "error"

# Estados desde los que se puede INICIAR una nueva síntesis (idempotencia
# RF-02): un borrador sin solicitud previa (`tts_estado IS NULL`, valor
# lógico "no_solicitado") o que falló en un intento anterior (RNF-HITL: un
# error previo no bloquea reintentar). `"generando"`/`"listo"` NO están aquí
# a propósito — un job que llega mientras otro ya está en curso o ya
# terminado con éxito es un no-op (nunca dos clips para el mismo guion).
_TTS_ESTADOS_INICIABLES = (None, _TTS_ESTADO_ERROR)

_AUDIO_MIME_TYPE = "audio/ogg; codecs=opus"


def _audio_ref_prefix(*, tenant_id: uuid.UUID, draft_id: uuid.UUID) -> str:
    """Namespacing del almacén, mismo criterio que
    `audio_store.build_audio_ref` (usa `call_id` como parte del nombre) —
    aquí el "call_id" conceptual es el `draft_id`, ya que el clip TTS de
    salida no pertenece a ninguna `Call`."""
    return str(draft_id)


def _try_start_synthesis(db: Session, *, draft_id: uuid.UUID) -> bool:
    """UPDATE condicional atómico (RF-02, mismo patrón que
    `draft_review_service._atomic_transition`): solo transiciona a
    `"generando"` si el borrador sigue en un estado que admite iniciar una
    síntesis nueva EN LA BASE DE DATOS en este instante. `rowcount == 0`
    significa que otro worker/reintento ya está sintetizando o ya terminó
    con éxito — este job se descarta sin producir un segundo clip."""
    result = db.execute(
        update(RagDraft)
        .where(
            RagDraft.id == draft_id,
            sa.or_(
                RagDraft.tts_estado.is_(None),
                RagDraft.tts_estado == _TTS_ESTADO_ERROR,
            ),
        )
        .values(tts_estado=_TTS_ESTADO_GENERANDO)
    )
    return result.rowcount > 0


def _mark_estado(
    db: Session,
    *,
    draft_id: uuid.UUID,
    tts_estado: str,
    audio_salida_ref: str | None = None,
) -> None:
    values: dict = {"tts_estado": tts_estado}
    if audio_salida_ref is not None:
        values["audio_salida_ref"] = audio_salida_ref
    db.execute(update(RagDraft).where(RagDraft.id == draft_id).values(**values))
    db.flush()


def process_job(
    job: TtsSynthesisJob,
    *,
    session_factory: Callable[[], Session] | None = None,
    redis_client: redis_asyncio.Redis | None = None,
) -> None:
    """Procesa un job ya extraído de `tts:jobs`: sintetiza el guion
    congelado del job, persiste el clip transitoriamente y (solo en modo
    `"enviar"`) encola el envío por WhatsApp.

    `session_factory` es SOLO para pruebas (inyecta una `Session` sobre el
    `postgres_engine` de test en vez de la instancia real).
    """
    db = (session_factory or SessionLocal)()
    try:
        try:
            draft_id = uuid.UUID(job.draft_id)
            tenant_uuid = uuid.UUID(job.tenant_id)
        except ValueError:
            logger.warning(
                "tts_job_invalid_ids", draft_id=job.draft_id, tenant_id=job.tenant_id
            )
            return

        with db.begin():
            set_tenant_session(db, job.tenant_id)
            puede_iniciar = _try_start_synthesis(db, draft_id=draft_id)

        if not puede_iniciar:
            logger.info(
                "tts_job_duplicate_or_in_progress_skipped",
                draft_id=job.draft_id,
                tenant_id=job.tenant_id,
                job_id=job.job_id,
            )
            return

        # Síntesis FUERA de cualquier transacción de BD abierta (mismo
        # criterio que `stt_worker`/`_sink_call`: nunca mantener una
        # transacción larga bloqueando el pool mientras el motor infiere).
        try:
            resultado = synthesize_to_ogg_opus(job.texto)
        except (SynthesizableTextTooLongError, TtsEngineError):
            logger.error(
                "tts_job_synthesis_failed",
                draft_id=job.draft_id,
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                exc_info=True,
            )
            with db.begin():
                set_tenant_session(db, job.tenant_id)
                _mark_estado(db, draft_id=draft_id, tts_estado=_TTS_ESTADO_ERROR)
            return

        audio_ref = audio_store.build_audio_ref(
            tenant_id=tenant_uuid,
            call_id=_audio_ref_prefix(tenant_id=tenant_uuid, draft_id=draft_id),
        )
        try:
            audio_store.store_audio(
                audio_ref=audio_ref, audio_bytes=resultado.ogg_opus_bytes
            )
        except audio_store.AudioStoreError:
            logger.error(
                "tts_job_store_failed",
                draft_id=job.draft_id,
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                exc_info=True,
            )
            with db.begin():
                set_tenant_session(db, job.tenant_id)
                _mark_estado(db, draft_id=draft_id, tts_estado=_TTS_ESTADO_ERROR)
            return

        with db.begin():
            set_tenant_session(db, job.tenant_id)
            # `audio_salida_ref` se puebla SIEMPRE aquí (referencia al clip
            # transitorio recién generado) — es el contrato que la ruta
            # "escuchar" (SPEC-070) usa para servir el clip bajo demanda vía
            # `GET .../drafts/{id}/audio`. La retención NO-persistente por
            # defecto (RF-06) no depende de que esta columna quede vacía:
            # `wa_send_worker` la sobrescribe/limpia según
            # `Settings.respuesta_tts_persist_enabled` DESPUÉS del envío (ver
            # `_purge_tts_clip_unless_retained`); mientras tanto, el clip
            # "recién generado, aún no enviado" necesita ser localizable.
            _mark_estado(
                db,
                draft_id=draft_id,
                tts_estado=_TTS_ESTADO_LISTO,
                audio_salida_ref=audio_ref,
            )

        logger.info(
            "tts_job_synthesized",
            draft_id=job.draft_id,
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            modo=job.modo,
            modelo_tts=resultado.modelo_tts,
            tiempo_total_segundos=round(resultado.tiempo_total_segundos, 3),
            chars=len(job.texto),
        )

        if job.modo != TTS_JOB_MODO_ENVIAR:
            # Ruta "escuchar antes de enviar" (RF-04): el clip queda listo,
            # SIN encolar ningún envío. El agente lo aprueba/rechaza después
            # (endpoint separado, `app/api/rag.py`).
            return

        # Ruta por defecto (RF-03): el guion YA fue aprobado por un humano
        # ANTES de que este job existiera (invariante verificado por el
        # llamador, `approve_draft_endpoint` — este worker nunca decide
        # aprobación). Encola el ENVÍO real por el worker/módulo autorizado
        # (`wa_send_worker` -> `app/integrations/whatsapp/`) — este worker
        # NUNCA llama a esa Graph API directamente (CHECKPOINT SENSIBLE).
        _dispatch_send_best_effort(
            redis_client or get_redis_client(),
            tenant_id=tenant_uuid,
            conversation_id=job.conversation_id,
            draft_id=draft_id,
            audio_ref=audio_ref,
        )
    finally:
        db.close()


def _dispatch_send_best_effort(
    redis_client: redis_asyncio.Redis,
    *,
    tenant_id: uuid.UUID,
    conversation_id: str,
    draft_id: uuid.UUID,
    audio_ref: str,
) -> None:
    """Encola el envío del clip por `wa:outbound` (RF-03). Best-effort de
    encolado (mismo criterio que `approve_draft_endpoint`/SPEC-029): si Redis
    falla aquí, el clip YA quedó `tts_estado="listo"` con `audio_salida_ref`
    poblado — se loguea para reconciliar manualmente en vez de reintentar
    desde dentro de este worker (evita duplicar el mecanismo de reintento de
    `resilient_worker_loop`, que ya cubre la iteración completa)."""
    from app.core.async_utils import run_coroutine_best_effort

    try:
        with SessionLocal() as db:
            with db.begin():
                set_tenant_session(db, str(tenant_id))
                draft = db.get(RagDraft, draft_id)
                if draft is None or not draft.sent_message_id:
                    logger.error(
                        "tts_job_send_dispatch_missing_sent_message",
                        draft_id=str(draft_id),
                        tenant_id=str(tenant_id),
                    )
                    return
                message_id = draft.sent_message_id

        run_coroutine_best_effort(
            enqueue_outbound_send(
                redis_client,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message_id=message_id,
                tipo=OUTBOUND_TIPO_AUDIO,
                audio_ref=audio_ref,
                audio_mime_type=_AUDIO_MIME_TYPE,
            )
        )
    except Exception:  # noqa: BLE001 — best-effort, nunca bloquea el clip ya generado
        logger.error(
            "tts_job_send_dispatch_failed",
            draft_id=str(draft_id),
            tenant_id=str(tenant_id),
            exc_info=True,
        )


async def drain_one(
    redis_client: redis_asyncio.Redis,
    *,
    timeout_seconds: int = 0,
    session_factory: Callable[[], Session] | None = None,
) -> bool:
    """Extrae y procesa UN único job pendiente de `tts:jobs`.

    Devuelve `True` si procesó un job, `False` si la cola estaba vacía.
    """
    job = await dequeue_tts_job(redis_client, timeout_seconds=timeout_seconds)
    if job is None:
        return False
    process_job(job, session_factory=session_factory, redis_client=redis_client)
    return True


async def run_worker_loop(
    redis_client: redis_asyncio.Redis | None = None,
    *,
    block_timeout_seconds: int = 5,
    stop_event: asyncio.Event | None = None,
    concurrencia: int | None = None,
) -> None:
    """Loop principal del proceso worker (`tts_worker` en docker-compose).

    Consume `tts:jobs` con `BLPOP` (bloqueante, sin busy-waiting), mismo
    patrón que `stt_worker`. Throttling (Adenda SPEC-067, R-84): corre
    `concurrencia` tareas asyncio concurrentes sobre la MISMA cola (default
    `Settings.respuesta_tts_concurrencia`, inicialmente 1 — un solo job de
    síntesis a la vez en la máquina compartida con STT/RAG/sentimiento). Cada
    tarea es un loop independiente envuelto en `resilient_worker_loop`
    (hardening SPEC-032): ante una caída transitoria de Redis/Postgres, se
    loguea y se espera backoff exponencial en vez de dejar morir el proceso.
    """
    from app.core.config import get_settings

    redis_client = redis_client or get_redis_client()
    stop_event = stop_event or asyncio.Event()
    concurrencia = concurrencia or get_settings().respuesta_tts_concurrencia

    async def _iteration() -> None:
        await drain_one(redis_client, timeout_seconds=block_timeout_seconds)

    logger.info(
        "tts_worker_started", queue=TTS_JOBS_QUEUE_KEY, concurrencia=concurrencia
    )
    await asyncio.gather(
        *(
            resilient_worker_loop(
                _iteration, stop_event=stop_event, worker_name=f"tts_worker[{i}]"
            )
            for i in range(concurrencia)
        )
    )
    logger.info("tts_worker_stopped")


def _run_forever_with_signal_handling() -> None:
    """Punto de entrada del proceso worker independiente (`python -m
    app.workers.tts_worker`), usado por el servicio `tts_worker` de
    `docker-compose.yml`. Se apaga limpiamente ante SIGTERM/SIGINT."""

    async def _main() -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)
        await run_worker_loop(stop_event=stop_event)

    asyncio.run(_main())


if __name__ == "__main__":
    _run_forever_with_signal_handling()
