"""STT Worker — transcripción de audio 100% local con faster-whisper (SPEC-035, SPEC-038, ADR-009)

`process_job` procesa UN trabajo ya extraído de `stt:jobs`
(`SttTranscriptionJob`, encolado por `recording_ingest_worker` tras almacenar
el audio cifrado, SPEC-037):

  1. Lee y descifra el audio en memoria desde el almacén on-prem
     (`app.services.telefonia.audio_store.load_audio`, SPEC-035/037) — NUNCA
     por red, NUNCA vía el módulo de transporte externo de telefonía
     (fuera del alcance/imports de este worker, ver CHECKPOINT abajo).
  2. IDEMPOTENCIA por `call_id` (RF-03, SPEC-036 `call_transcripts.call_id`
     UNIQUE): si ya existe una `call_transcript` para el `call_id` del job,
     no-op — reprocesar (reintento, redelivery) NO duplica la transcripción.
     La restricción UNIQUE de BD es la garantía dura ante condiciones de
     carrera entre workers concurrentes (mismo patrón que
     `recording_ingest_worker::_call_exists` + `IntegrityError` como red de
     seguridad).
  3. Transcribe con `app.services.telefonia.stt_engine.transcribe_audio_bytes`
     (`faster-whisper` es-CO `large-v3`, fallback CPU/`medium` automático) —
     segmentos + timestamps + diarización básica opcional (VAD).
  4. Persiste `CallTranscript` (segmentos, idioma, modelo_stt) bajo RLS
     (`set_tenant_session`, ADR-004) y actualiza `calls.estado = "transcrita"`.
  5. Instrumenta RTF, latencia de cola real (encolado -> consumo, calculada
     con `SttTranscriptionJob.enqueued_at_epoch_seconds`, poblado por
     `enqueue_stt_job` en el momento real de encolado) y tasa de error del
     job, exportados a `/metrics` (`app.core.metrics`).

Robustez (mismo criterio que el resto de workers, RNF-05): un fallo
procesando un job se loguea con `exc_info` y NO detiene el loop del worker —
el job ya salió de la cola (`BLPOP` es destructivo); queda auditado en logs
(y en `stt_jobs_total{resultado="error"}`) para investigación manual/reintento
manual futuro.

CHECKPOINT SENSIBLE (RNF-41, ADR-009): este módulo NUNCA importa `httpx` ni
el cliente de transporte/descarga de telefonía externa (ADR-010, otro
módulo, fuera de estos imports) — solo el almacén cifrado (`audio_store.py`)
y el motor STT 100% local (`stt_engine.py`). No hay egress en este worker.

Enriquecimiento IA local sobre la transcripción — SPEC-039, reutiliza
SPEC-017/018/019 sin crear componentes de IA nuevos (mismo patrón exacto que
`whatsapp_inbound_worker.py` usa para enganchar WhatsApp al pipeline, SPEC-028):
  6. Tras persistir `CallTranscript` con éxito, se concatena el texto de los
     segmentos y se materializa como un `Message` entrante (`remitente=
     "contacto"`, mismo vocabulario que WhatsApp/WebChat) en la `Conversation`
     (`canal="voz"`) enlazada a la `Call` — creando contacto/conversación si
     aún no existían (`_get_or_create_contact`/`_get_or_create_conversation`,
     MISMA función que `whatsapp_inbound_worker`, sobre `Call.numero`/
     `Call.contact_id` en vez de `wa_id`). Materializar la transcripción como
     `Message` es lo que permite reutilizar el mecanismo de sentimiento de
     SPEC-018 (que opera sobre `Message.sentimiento`/`sentimiento_score`)
     TAL CUAL, sin ningún worker/columna nueva de sentimiento.
  7. Se dispara sentimiento (SPEC-018, `app.services.message_service.
     schedule_sentiment_analysis`, best-effort, no bloquea) sobre ese mensaje.
  8. Se genera un resumen de la llamada (SPEC-039, único prompt NUEVO,
     `app.services.call_summary_service.generate_call_summary`, registrado en
     `prompt-lab/`) y se persiste en `calls.resumen`.
  9. Se genera Y PERSISTE (estado `propuesto`, SPEC-019) un borrador RAG con
     ≥3 citas trazables (SPEC-017, `generate_rag_draft` +
     `draft_review_service.create_draft`, MISMA función que SPEC-028) para
     que el agente humano lo revise en la ficha de la llamada (SPEC-040,
     fuera de alcance aquí) — NADA se envía automáticamente.
  10. Modo degradado (R-21, RNF-01 sin egress): si el LLM local no está
      disponible (`AIServiceError`) o no hay contexto suficiente para ≥3
      citas (`InsufficientContextError`), NO se genera resumen/borrador — se
      loguea la condición y la transcripción YA PERSISTIDA en el paso 4 no se
      ve afectada; ningún error de IA revierte ni bloquea la transcripción.

Sink parametrizado por `destino` (SPEC-056, ADITIVO sobre SPEC-038/039) —
`process_job` despacha, DESPUÉS de transcribir con `stt_engine.py` (paso 3,
que NO cambia ni se toca), según el prefijo de `job.destino`
(`app.core.stt_queue.SttTranscriptionJob.destino`, añadido por SPEC-055):
  - sink `call:{id}` (DEFAULT, formato anterior o `destino` ausente): es
    EXACTAMENTE la lógica de los pasos 1-10 de arriba, extraída a
    `_sink_call` sin ningún cambio de comportamiento observable — cero
    regresión sobre los jobs de llamadas del Entregable #4.
  - sink `message:{id}` (NUEVO): la nota de voz de WhatsApp YA tiene su
    `Message(tipo="audio", contenido=None)` persistido por SPEC-055 —
    `_sink_message` solo ACTUALIZA ese `Message.contenido`/
    `transcripcion_estado="ok"` bajo RLS del tenant del job; NUNCA crea
    `CallTranscript`, NUNCA crea un `Message` nuevo, NUNCA toca `calls`
    (ADR-013). Idempotencia (RF-05 SPEC-056): si `transcripcion_estado`
    del `Message` ya es `"ok"`, no-op — la guarda corre ANTES de invocar
    `stt_engine.transcribe_audio_bytes` (mismo criterio que
    `_transcript_exists` del sink `call`, para no gastar cómputo
    transcribiendo un audio ya procesado) y se repite tras transcribir por
    si perdió una carrera con otro worker (mismo patrón de doble chequeo).
    El disparo del pipeline IA (sentimiento/RAG) sobre este `Message` queda
    para SPEC-057 — este sink solo deja el texto listo.
  - Un solo motor (`stt_engine.py`, sin tocar), un solo modelo Whisper en
    memoria, una sola ruta de inferencia — el sink solo cambia el DESTINO de
    escritura del resultado ya calculado; RTF/latencia de cola/tasa de error
    se siguen instrumentando igual para ambos sinks (RNF-42).
"""

from __future__ import annotations

import asyncio
import signal
import time
import uuid
from types import SimpleNamespace
from typing import Callable

import redis.asyncio as redis_asyncio
import sqlalchemy as sa
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.async_utils import run_coroutine_best_effort
from app.core.gpu_priority import (
    GPU_PRIORITY_BACKOFF_SECONDS,
    should_pause_batch_for_voice,
)
from app.core.metrics import (
    increment_stt_jobs,
    observe_stt_queue_latency,
    observe_stt_rtf,
)
from app.core.redis_client import get_redis_client
from app.core.stt_queue import STT_JOBS_QUEUE_KEY, SttTranscriptionJob, dequeue_stt_job
from app.core.worker_resilience import resilient_worker_loop
from app.db.session import SessionLocal, set_tenant_session
from app.models.call import Call
from app.models.call_transcript import CallTranscript
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.ai_service import AIClient, AIServiceError
from app.services.call_summary_service import generate_call_summary
from app.services.message_service import (
    create_message,
    schedule_sentiment_analysis,
)
from app.services.rag import draft_review_service
from app.services.rag.draft_service import InsufficientContextError, generate_rag_draft
from app.services.telefonia.audio_store import AudioStoreError, load_audio
from app.services.telefonia.stt_engine import SttEngineError, transcribe_audio_bytes

logger = structlog.get_logger(__name__)

_ESTADO_CALL_TRANSCRITA = "transcrita"
_CANAL_VOZ = "voz"
_REMITENTE_CONTACTO = "contacto"

# Prefijos del campo `destino` (SPEC-055/SPEC-056, ADR-013): gobiernan el
# sink de escritura que consume este worker. `_DESTINO_MESSAGE_PREFIX` es el
# ÚNICO prefijo reconocido para el sink nuevo; cualquier otro valor (incluido
# el prefijo `"call:"` y la ausencia total de `destino` en jobs legacy,
# tolerada por `SttTranscriptionJob.from_json`/`__post_init__`) se trata como
# el sink `call` — comportamiento IDÉNTICO a SPEC-038 (RF-01 SPEC-056).
_DESTINO_MESSAGE_PREFIX = "message:"

# `transcripcion_estado` terminal del sink `message` (SPEC-053/SPEC-056):
# una vez en "ok", reprocesar el mismo job es no-op (RF-05 SPEC-056).
_TRANSCRIPCION_ESTADO_OK = "ok"


def _transcript_exists(db: Session, *, call_id: uuid.UUID) -> bool:
    """Dedup por `call_id` (RF-03, ADR-007): consulta previa bajo RLS (ya con
    `app.tenant_id` fijado) para no repetir trabajo (transcribir de nuevo un
    audio ya procesado) en el camino feliz. La restricción UNIQUE de BD
    (`uq_call_transcripts_call_id`, SPEC-036) es la garantía dura ante
    condiciones de carrera entre workers/reintentos concurrentes; esta
    consulta es una guarda adicional del worker, no el único mecanismo."""
    return (
        db.execute(
            sa.text("SELECT 1 FROM call_transcripts WHERE call_id = :call_id LIMIT 1"),
            {"call_id": str(call_id)},
        ).scalar_one_or_none()
        is not None
    )


def _texto_completo_transcripcion(resultado) -> str:
    """Concatena el texto de todos los segmentos, en orden, separados por un
    espacio — mismo texto que se materializa como `Message.contenido` (SPEC-039)
    y que se pasa a sentimiento (SPEC-018)/resumen (SPEC-039)/RAG (SPEC-017)."""
    return " ".join(
        segmento.texto.strip()
        for segmento in resultado.segmentos
        if segmento.texto and segmento.texto.strip()
    ).strip()


def _get_or_create_contact_voz(
    db: Session, *, tenant_id: uuid.UUID, numero: str
) -> Contact:
    """Busca un contacto activo por `telefono == numero` dentro del tenant
    (RLS ya fijado); si no existe, lo crea. MISMO criterio que
    `whatsapp_inbound_worker._get_or_create_contact`, sobre el número remoto
    de la llamada (`Call.numero`) en vez de `wa_id`."""
    contact = db.scalar(
        sa.select(Contact).where(Contact.telefono == numero, Contact.activo.is_(True))
    )
    if contact is not None:
        return contact

    contact = Contact(tenant_id=tenant_id, nombre=numero, telefono=numero)
    db.add(contact)
    db.flush()
    db.refresh(contact)
    return contact


def _get_or_create_conversation_voz(
    db: Session, *, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> Conversation:
    """Busca una conversación activa de canal `voz` para el contacto; si no
    existe, la crea. MISMO criterio que
    `whatsapp_inbound_worker._get_or_create_conversation`."""
    conversation = db.scalar(
        sa.select(Conversation).where(
            Conversation.contact_id == contact_id,
            Conversation.canal == _CANAL_VOZ,
            Conversation.activo.is_(True),
        )
    )
    if conversation is not None:
        return conversation

    conversation = Conversation(
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal=_CANAL_VOZ,
        estado="cerrada",  # la llamada ya finalizó cuando se transcribe (SPEC-038)
    )
    db.add(conversation)
    db.flush()
    db.refresh(conversation)
    return conversation


def _materialize_transcript_message(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    call_id: uuid.UUID,
    call_numero: str,
    call_contact_id: uuid.UUID | None,
    call_conversation_id: uuid.UUID | None,
    texto: str,
):
    """Materializa el texto de la transcripción como un `Message` entrante
    (`remitente="contacto"`) en la conversación de voz de la llamada —
    creando contacto/conversación si aún no existían.

    Esto es lo que permite reutilizar el mecanismo de sentimiento de SPEC-018
    (`Message.sentimiento`/`sentimiento_score`) TAL CUAL sobre la
    transcripción, sin ningún worker/columna nueva de sentimiento (SPEC-039,
    mismo patrón que `whatsapp_inbound_worker._process_message_event`
    persiste el mensaje de WhatsApp antes de disparar el pipeline IA).

    Abre su PROPIA transacción con `set_tenant_session` (RLS, ADR-004): la
    transacción de persistencia de `CallTranscript` ya cerró (commit) al
    llegar aquí, mismo criterio que
    `whatsapp_inbound_worker._generate_rag_draft_best_effort` reabre RLS tras
    la transacción de `_process_message_event`.

    Devuelve `(message, conversation_id)`; `None` si `texto` está vacío (una
    transcripción sin contenido reconocible no genera mensaje ni dispara IA)
    o si la materialización falla (best-effort, R-21: nunca revierte la
    transcripción ya persistida).
    """
    if not texto:
        return None

    try:
        with db.begin():
            set_tenant_session(db, str(tenant_id))

            if call_contact_id is not None:
                contact_id = call_contact_id
            else:
                contact = _get_or_create_contact_voz(
                    db, tenant_id=tenant_id, numero=call_numero
                )
                contact_id = contact.id

            if call_conversation_id is not None:
                conversation_id = call_conversation_id
            else:
                conversation = _get_or_create_conversation_voz(
                    db, tenant_id=tenant_id, contact_id=contact_id
                )
                conversation_id = conversation.id

            message = create_message(
                db,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                remitente=_REMITENTE_CONTACTO,
                contenido=texto,
            )
            db.flush()
            # Capturado DENTRO de la transacción (con el tenant fijado):
            # `message.id` no puede leerse de forma fiable DESPUÉS de que
            # este `with` cierre (commit) — el commit expira los atributos
            # del ORM (`expire_on_commit=True` por defecto) y un acceso
            # posterior fuera de cualquier `app.tenant_id` fijado dispara un
            # refresh que, bajo RLS real, ve 0 filas (`ObjectDeletedError`,
            # confirmado contra Postgres real).
            message_id = message.id
    except Exception:  # noqa: BLE001 — best-effort, nunca bloquea la transcripción
        logger.error(
            "stt_transcript_message_materialization_failed",
            tenant_id=str(tenant_id),
            call_id=str(call_id),
            exc_info=True,
        )
        return None

    return message_id, conversation_id


def _schedule_sentiment_best_effort(redis_client: redis_asyncio.Redis, *, message) -> None:
    """Wrapper sync -> async para disparar sentimiento (SPEC-018) desde este
    worker síncrono — MISMO patrón que
    `whatsapp_inbound_worker._schedule_sentiment_best_effort`.

    CORRECCIÓN (bug de producción encontrado ejecutando la suite contra
    Postgres real, ver `app.core.async_utils`): `process_job` se invoca en
    producción real desde `drain_one`/`run_worker_loop`, que YA corren
    dentro de un event loop activo — `asyncio.run()` directo aquí SIEMPRE
    fallaba con `RuntimeError: asyncio.run() cannot be called from a
    running event loop`, silenciado por el `except Exception` de abajo:
    SPEC-018 nunca se disparaba en producción."""
    try:
        run_coroutine_best_effort(
            schedule_sentiment_analysis(redis_client, message=message)
        )
    except Exception:  # noqa: BLE001 — best-effort, nunca bloquea la transcripción
        logger.warning(
            "stt_sentiment_dispatch_failed",
            message_id=str(message.id),
            tenant_id=str(message.tenant_id),
            exc_info=True,
        )


def _generate_call_summary_best_effort(
    db: Session,
    ai_client: AIClient,
    *,
    tenant_id: uuid.UUID,
    call_id: uuid.UUID,
    texto: str,
) -> None:
    """Genera el resumen de la llamada (SPEC-039, único prompt NUEVO) y lo
    persiste en `calls.resumen`. Best-effort/modo degradado (R-21): si el LLM
    local no está disponible, se loguea y se retorna sin propagar — la
    transcripción ya persistida no se ve afectada."""
    try:
        result = generate_call_summary(ai_client, transcript_text=texto)
    except Exception:  # noqa: BLE001 — best-effort, nunca bloquea la transcripción
        logger.error(
            "stt_call_summary_dispatch_failed",
            tenant_id=str(tenant_id),
            call_id=str(call_id),
            exc_info=True,
        )
        return

    if result.summary is None:
        logger.info(
            "stt_call_summary_degraded_skipped",
            tenant_id=str(tenant_id),
            call_id=str(call_id),
        )
        return

    try:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            call = db.get(Call, call_id)
            if call is not None and call.activo:
                call.resumen = result.summary
    except Exception:  # noqa: BLE001 — best-effort, nunca bloquea la transcripción
        logger.error(
            "stt_call_summary_persist_failed",
            tenant_id=str(tenant_id),
            call_id=str(call_id),
            exc_info=True,
        )
        return

    logger.info(
        "stt_call_summary_persisted", tenant_id=str(tenant_id), call_id=str(call_id)
    )


def _generate_rag_draft_best_effort(
    db: Session,
    ai_client: AIClient,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    query: str,
) -> None:
    """Genera Y PERSISTE (estado `propuesto`, SPEC-019) el borrador RAG con
    ≥3 citas trazables (SPEC-017) para la llamada — MISMO flujo que
    `whatsapp_inbound_worker._generate_rag_draft_best_effort`
    (`generate_rag_draft` + `draft_review_service.create_draft`), reutilizado
    aquí sin duplicar lógica de generación/persistencia.

    RESTRICCIÓN DURA (SPEC-019, heredada): esta función NUNCA llama a
    `create_message`/`approve_and_send` — el borrador queda en `propuesto`.

    Modo degradado (R-21, RNF-01 IA sin egress): si el LLM local no está
    disponible (`AIServiceError`) o no hay contexto suficiente para ≥3 citas
    (`InsufficientContextError`), NO se genera el borrador — se loguea la
    condición y se retorna sin propagar.
    """
    try:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            try:
                result = generate_rag_draft(db, ai_client, query=query)
            except InsufficientContextError:
                logger.info(
                    "stt_rag_draft_insufficient_context",
                    tenant_id=str(tenant_id),
                    conversation_id=str(conversation_id),
                )
                return
            except AIServiceError:
                logger.warning(
                    "stt_rag_draft_ai_unavailable_degraded",
                    tenant_id=str(tenant_id),
                    conversation_id=str(conversation_id),
                    exc_info=True,
                )
                return

            draft_review_service.create_draft(
                db,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                query=query,
                result=result,
                created_by=None,
            )
    except Exception:  # noqa: BLE001 — best-effort, nunca bloquea la transcripción
        logger.error(
            "stt_rag_draft_dispatch_failed",
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            exc_info=True,
        )
        return

    logger.info(
        "stt_rag_draft_proposed",
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
    )


def _message_transcripcion_ok(db: Session, *, message_id: uuid.UUID) -> bool:
    """Guarda de idempotencia del sink `message` (RF-05 SPEC-056), MISMO
    criterio que `_transcript_exists` del sink `call`: consulta de solo
    lectura bajo RLS (ya con `app.tenant_id` fijado) para no repetir trabajo
    (transcribir de nuevo un audio ya procesado) en el camino feliz. Se
    invoca ANTES de la inferencia (no gastar cómputo) y se repite DENTRO de
    la transacción de escritura por si perdió una carrera con otro worker."""
    return (
        db.execute(
            sa.text(
                "SELECT 1 FROM messages "
                "WHERE id = :message_id AND transcripcion_estado = :estado_ok "
                "LIMIT 1"
            ),
            {"message_id": str(message_id), "estado_ok": _TRANSCRIPCION_ESTADO_OK},
        ).scalar_one_or_none()
        is not None
    )


def _sink_call(
    db: Session,
    job: SttTranscriptionJob,
    *,
    call_id: uuid.UUID,
    tenant_uuid: uuid.UUID,
    audio_bytes: bytes,
    redis_client: redis_asyncio.Redis | None,
    ai_client: AIClient | None,
) -> None:
    """Sink `call:{id}` (DEFAULT, SPEC-038/039) — EXACTAMENTE la lógica
    ANTERIOR a SPEC-056, extraída tal cual (sin ningún cambio de
    comportamiento observable, RNF-62): idempotencia por `call_id`,
    transcripción, persistencia de `CallTranscript` + `calls.estado`, y
    disparo best-effort del pipeline IA (SPEC-039) sobre el `Message` de voz
    materializado. `audio_bytes` ya viene descifrado/cargado por
    `process_job` (MISMO punto del flujo que antes de SPEC-056: la carga del
    audio ocurre ANTES de la guarda de idempotencia, sin cambio de orden
    observable)."""
    # Guarda de idempotencia PREVIA a la inferencia (RF-03): consulta de
    # solo lectura fuera de la transacción de escritura, bajo RLS, para
    # no gastar CPU/GPU transcribiendo un audio ya procesado. Se repite
    # la comprobación DENTRO de la transacción de escritura más abajo por
    # si perdió una carrera con otro worker mientras se transcribía (la
    # UNIQUE de BD es la garantía dura final).
    with db.begin():
        set_tenant_session(db, job.tenant_id)
        ya_existe = _transcript_exists(db, call_id=call_id)

    if ya_existe:
        logger.info(
            "stt_job_duplicate_call_id_skipped",
            call_id=job.call_id,
            tenant_id=job.tenant_id,
            job_id=job.job_id,
        )
        increment_stt_jobs(resultado="duplicado")
        return

    # Transcripción (potencialmente varios segundos/minutos, RNF-42)
    # FUERA de cualquier transacción de BD abierta — nunca se mantiene
    # una transacción larga bloqueando conexiones del pool mientras el
    # modelo STT infiere.
    try:
        resultado = transcribe_audio_bytes(audio_bytes)
    except SttEngineError:
        logger.error(
            "stt_job_transcription_failed",
            call_id=job.call_id,
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            exc_info=True,
        )
        increment_stt_jobs(resultado="error")
        return

    call_numero: str | None = None
    call_contact_id: uuid.UUID | None = None
    call_conversation_id: uuid.UUID | None = None
    call_activa = False

    try:
        with db.begin():
            set_tenant_session(db, job.tenant_id)

            if _transcript_exists(db, call_id=call_id):
                # RF-03: otro worker ganó la carrera mientras este
                # transcribía -> descarta el resultado ya calculado sin
                # persistir una segunda fila.
                logger.info(
                    "stt_job_duplicate_call_id_skipped_post_transcription",
                    call_id=job.call_id,
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                )
                increment_stt_jobs(resultado="duplicado")
                return

            transcript = CallTranscript(
                tenant_id=tenant_uuid,
                call_id=call_id,
                segmentos=resultado.segmentos_como_dicts(),
                idioma=resultado.idioma,
                modelo_stt=resultado.modelo_stt,
            )
            db.add(transcript)

            call = db.execute(
                sa.select(Call).where(Call.id == call_id)
            ).scalar_one_or_none()
            if call is not None:
                call.estado = _ESTADO_CALL_TRANSCRITA
                # Capturados ANTES de salir del `with` (la sesión puede
                # expirar los atributos del ORM al hacer commit) para el
                # enganche del pipeline IA (SPEC-039) que sigue abajo, en
                # su PROPIA transacción — mismo criterio que
                # `whatsapp_inbound_worker`, que reabre `set_tenant_session`
                # después de que la transacción de persistencia ya cerró.
                call_numero = call.numero
                call_contact_id = call.contact_id
                call_conversation_id = call.conversation_id
                call_activa = True
    except IntegrityError:
        # Condición de carrera entre workers/reintentos concurrentes
        # sobre el MISMO call_id: la restricción UNIQUE de BD
        # (uq_call_transcripts_call_id, SPEC-036) es la garantía dura de
        # idempotencia (ADR-007) cuando `_transcript_exists` pierde la
        # carrera.
        db.rollback()
        logger.info(
            "stt_job_duplicate_call_id_race_detected",
            call_id=job.call_id,
            tenant_id=job.tenant_id,
            job_id=job.job_id,
        )
        increment_stt_jobs(resultado="duplicado")
        return

    observe_stt_rtf(
        model=resultado.modelo_stt, device=resultado.device_usado, rtf=resultado.rtf
    )
    increment_stt_jobs(resultado="ok")

    logger.info(
        "stt_job_transcript_persisted",
        call_id=job.call_id,
        tenant_id=job.tenant_id,
        job_id=job.job_id,
        modelo_stt=resultado.modelo_stt,
        idioma=resultado.idioma,
        segmentos=len(resultado.segmentos),
        rtf=round(resultado.rtf, 3),
        fallback_aplicado=resultado.fallback_aplicado,
    )

    # SPEC-039: dispara el pipeline IA local (sentimiento SPEC-018 +
    # resumen + borrador RAG SPEC-017/019) sobre la transcripción YA
    # persistida arriba; best-effort/modo degradado (ver docstrings de
    # cada helper) — NUNCA revierte ni bloquea la transcripción ya
    # confirmada. Sin `call` resuelta (fila no encontrada) o transcripción
    # sin texto reconocible, no hay nada que enganchar.
    if call_activa:
        texto_transcripcion = _texto_completo_transcripcion(resultado)
        materializado = _materialize_transcript_message(
            db,
            tenant_id=tenant_uuid,
            call_id=call_id,
            call_numero=call_numero or "",
            call_contact_id=call_contact_id,
            call_conversation_id=call_conversation_id,
            texto=texto_transcripcion,
        )
        if materializado is not None:
            message_id, conversation_id = materializado
            effective_ai_client = ai_client or AIClient()
            # CORRECCIÓN (verificado contra Postgres real, con el rol owner
            # Y con el rol de aplicación `omnicore_app`): `_materialize_
            # transcript_message` ya NO devuelve el objeto ORM `Message`
            # (quedaría con sus atributos expirados tras el commit de su
            # propio `with db.begin():`, y reutilizarlo aquí fuera de
            # cualquier `app.tenant_id` fijado dispara un refresh implícito
            # que, bajo RLS real, ve 0 filas — `ObjectDeletedError` — y bajo
            # el rol owner deja a `db` en "autobegin", rompiendo el
            # siguiente `with db.begin():` con `InvalidRequestError`). Los
            # 3 campos que `schedule_sentiment_analysis`/`is_message_
            # elegible_para_sentimiento` necesitan (`id`, `tenant_id`,
            # `remitente`) ya se conocen sin tocar la BD: `remitente` es
            # SIEMPRE `_REMITENTE_CONTACTO` (constante, ver
            # `_materialize_transcript_message`) y `tenant_id` es el mismo
            # `tenant_uuid` de este sink.
            fake_message = SimpleNamespace(
                id=message_id, tenant_id=tenant_uuid, remitente=_REMITENTE_CONTACTO
            )
            _schedule_sentiment_best_effort(
                redis_client or get_redis_client(), message=fake_message
            )
            _generate_call_summary_best_effort(
                db,
                effective_ai_client,
                tenant_id=tenant_uuid,
                call_id=call_id,
                texto=texto_transcripcion,
            )
            _generate_rag_draft_best_effort(
                db,
                effective_ai_client,
                tenant_id=tenant_uuid,
                conversation_id=conversation_id,
                query=texto_transcripcion,
            )


def _sink_message(
    db: Session,
    job: SttTranscriptionJob,
    *,
    message_id: uuid.UUID,
    audio_bytes: bytes,
) -> None:
    """Sink `message:{id}` (NUEVO, SPEC-056) — actualiza el `Message(tipo=
    "audio")` YA existente (creado por SPEC-055) con la transcripción: NUNCA
    crea `CallTranscript`, NUNCA crea un `Message` nuevo, NUNCA toca `calls`
    (ADR-013). Reutiliza el ÚNICO motor STT (`stt_engine.py`, sin tocar) —
    misma ruta de inferencia y misma instrumentación RTF/latencia/error que
    el sink `call` (RNF-42). `audio_bytes` ya viene descifrado/cargado por
    `process_job`.

    El disparo del pipeline IA (sentimiento/RAG, SPEC-057) sobre el
    `Message` actualizado queda explícitamente FUERA de alcance aquí — este
    sink solo deja `contenido`/`transcripcion_estado="ok"` listos.
    """
    # Guarda de idempotencia PREVIA a la inferencia (RF-05 SPEC-056), MISMO
    # criterio que el sink `call`: no gastar cómputo transcribiendo un audio
    # ya procesado.
    with db.begin():
        set_tenant_session(db, job.tenant_id)
        ya_transcrito = _message_transcripcion_ok(db, message_id=message_id)

    if ya_transcrito:
        logger.info(
            "stt_job_message_already_transcribed_skipped",
            message_id=str(message_id),
            tenant_id=job.tenant_id,
            job_id=job.job_id,
        )
        increment_stt_jobs(resultado="duplicado")
        return

    # Transcripción FUERA de cualquier transacción de BD abierta — mismo
    # criterio que el sink `call` (RNF-42, nunca mantener una transacción
    # larga bloqueando el pool mientras el modelo STT infiere).
    try:
        resultado = transcribe_audio_bytes(audio_bytes)
    except SttEngineError:
        logger.error(
            "stt_job_transcription_failed",
            call_id=job.call_id,
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            exc_info=True,
        )
        increment_stt_jobs(resultado="error")
        return

    texto_transcripcion = _texto_completo_transcripcion(resultado)

    with db.begin():
        set_tenant_session(db, job.tenant_id)

        if _message_transcripcion_ok(db, message_id=message_id):
            # RF-05: otro worker ganó la carrera mientras este transcribía
            # -> descarta el resultado ya calculado sin re-escribir.
            logger.info(
                "stt_job_message_already_transcribed_skipped_post_transcription",
                message_id=str(message_id),
                tenant_id=job.tenant_id,
                job_id=job.job_id,
            )
            increment_stt_jobs(resultado="duplicado")
            return

        message = db.get(Message, message_id)
        if message is None:
            # Defensa: el `Message` referenciado por `destino` no existe (no
            # debería ocurrir en producción real, ver SPEC-055) — se audita
            # sin propagar.
            logger.error(
                "stt_job_message_not_found",
                message_id=str(message_id),
                tenant_id=job.tenant_id,
                job_id=job.job_id,
            )
            increment_stt_jobs(resultado="error")
            return

        message.contenido = texto_transcripcion
        message.transcripcion_estado = _TRANSCRIPCION_ESTADO_OK
        db.flush()

    observe_stt_rtf(
        model=resultado.modelo_stt, device=resultado.device_usado, rtf=resultado.rtf
    )
    increment_stt_jobs(resultado="ok")

    logger.info(
        "stt_job_message_transcript_persisted",
        message_id=str(message_id),
        tenant_id=job.tenant_id,
        job_id=job.job_id,
        modelo_stt=resultado.modelo_stt,
        idioma=resultado.idioma,
        segmentos=len(resultado.segmentos),
        rtf=round(resultado.rtf, 3),
        fallback_aplicado=resultado.fallback_aplicado,
    )


def process_job(
    job: SttTranscriptionJob,
    *,
    session_factory: Callable[[], Session] | None = None,
    enqueued_at_epoch_seconds: float | None = None,
    redis_client: redis_asyncio.Redis | None = None,
    ai_client: AIClient | None = None,
) -> None:
    """Procesa un job ya extraído de `stt:jobs`: lee el audio cifrado,
    transcribe local (una sola ruta de inferencia, `stt_engine.py` sin
    tocar) y despacha al sink que corresponda según `job.destino`
    (SPEC-056): `_sink_call` (DEFAULT, formato anterior o `destino` ausente
    — comportamiento IDÉNTICO a SPEC-038/039, RNF-62) o `_sink_message`
    (`destino="message:{id}"`, SPEC-055/056 — actualiza un `Message` de
    WhatsApp existente, ADR-013).

    `session_factory` es SOLO para pruebas (inyecta una `Session` sobre el
    `postgres_engine` de test en vez de la instancia real).
    `enqueued_at_epoch_seconds`: por defecto se toma de `job.
    enqueued_at_epoch_seconds` (el propio mensaje, poblado en el momento real
    de encolado por `enqueue_stt_job`/`SttTranscriptionJob`, corrección
    SPEC-038 post-revisión: antes NUNCA se poblaba en el camino real de
    producción). El parámetro explícito se mantiene SOLO para que las
    pruebas puedan fijar un instante determinista sin depender de
    temporizadores reales ni mutar el job.
    """
    if enqueued_at_epoch_seconds is None:
        enqueued_at_epoch_seconds = job.enqueued_at_epoch_seconds
    db = (session_factory or SessionLocal)()
    try:
        # Enrutado por sink (RF-01/RF-02 SPEC-056): `destino` SIEMPRE trae un
        # valor (default de fábrica `"call:{call_id}"`,
        # `SttTranscriptionJob.__post_init__`/`from_json`) — un job legacy
        # sin el campo en el JSON se comporta como `call` sin diferencia
        # observable. Solo el prefijo `"message:"` activa el sink nuevo;
        # cualquier otro valor (incluido `"call:"`) es el sink `call`. Se
        # resuelve el sink ANTES de tocar `call_id`/`tenant_id` porque el
        # sink `message` no requiere un `call_id` semánticamente válido.
        destino = job.destino or f"call:{job.call_id}"
        es_sink_message = destino.startswith(_DESTINO_MESSAGE_PREFIX)

        if es_sink_message:
            target_id_raw = destino[len(_DESTINO_MESSAGE_PREFIX):]
            try:
                message_id = uuid.UUID(target_id_raw)
            except ValueError:
                logger.warning(
                    "stt_job_invalid_message_id",
                    destino=destino,
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                )
                increment_stt_jobs(resultado="error")
                return
        else:
            try:
                call_id = uuid.UUID(job.call_id)
            except ValueError:
                logger.warning("stt_job_invalid_call_id", call_id=job.call_id)
                increment_stt_jobs(resultado="error")
                return

        try:
            tenant_uuid = uuid.UUID(job.tenant_id)
        except ValueError:
            logger.warning(
                "stt_job_invalid_tenant_id",
                call_id=job.call_id,
                tenant_id=job.tenant_id,
                job_id=job.job_id,
            )
            increment_stt_jobs(resultado="error")
            return

        try:
            audio_bytes = load_audio(audio_ref=job.audio_ref)
        except AudioStoreError:
            logger.error(
                "stt_job_audio_load_failed",
                call_id=job.call_id,
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                exc_info=True,
            )
            increment_stt_jobs(resultado="error")
            return

        if enqueued_at_epoch_seconds is not None:
            observe_stt_queue_latency(time.time() - enqueued_at_epoch_seconds)

        if es_sink_message:
            _sink_message(db, job, message_id=message_id, audio_bytes=audio_bytes)
            return

        _sink_call(
            db,
            job,
            call_id=call_id,
            tenant_uuid=tenant_uuid,
            audio_bytes=audio_bytes,
            redis_client=redis_client,
            ai_client=ai_client,
        )
    finally:
        db.close()


async def drain_one(
    redis_client: redis_asyncio.Redis,
    *,
    timeout_seconds: int = 0,
    session_factory: Callable[[], Session] | None = None,
    ai_client: AIClient | None = None,
) -> bool:
    """Extrae y procesa UN único job pendiente de `stt:jobs`.

    Devuelve `True` si procesó un job, `False` si la cola estaba vacía.

    `redis_client` (además de fuente de la cola `stt:jobs`) se reutiliza como
    cliente de encolado de sentimiento (SPEC-039/018): mismo Redis, sin abrir
    una segunda conexión — MISMO patrón que
    `whatsapp_inbound_worker.drain_one`.

    ADR-011 (GPU prioritaria para voz en vivo): antes de procesar un job
    batch, verifica si hay ≥1 llamada en vivo activa (clave Redis
    `voice:active_calls`). Si sí, pausa y retorna sin procesar (dejando el
    job en la cola para reintento). El batch es tolerante a cola por diseño
    (SPEC-038) y reanuda normalmente cuando `voice:active_calls` vuelve a 0.
    Sin GPU real o sin llamadas activas (default: contador en 0), el
    comportamiento es IDÉNTICO al anterior (SPEC-038 sin cambios).
    """
    # Mecanismo de prioridad de GPU (ADR-011): si hay llamadas en vivo activas,
    # pausa el batch. Fail-open (si Redis falla, asume sin llamadas activas).
    if await should_pause_batch_for_voice(redis_client):
        logger.debug(
            "stt_batch_paused_for_voice_priority",
            pause_duration=GPU_PRIORITY_BACKOFF_SECONDS,
        )
        await asyncio.sleep(GPU_PRIORITY_BACKOFF_SECONDS)
        return False  # No procesó nada; la cola y el job quedan intactos

    job = await dequeue_stt_job(redis_client, timeout_seconds=timeout_seconds)
    if job is None:
        return False
    process_job(
        job,
        session_factory=session_factory,
        redis_client=redis_client,
        ai_client=ai_client,
    )
    return True


async def run_worker_loop(
    redis_client: redis_asyncio.Redis | None = None,
    *,
    block_timeout_seconds: int = 5,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Loop principal del proceso worker (`stt_worker` en docker-compose).
    Consume `stt:jobs` con `BLPOP` (bloqueante, sin busy-waiting) — mismo
    patrón que `recording_ingest_worker`/`sentiment_worker`/`rag_ingest_worker`.

    Hardening (SPEC-032): cada iteración corre envuelta en
    `resilient_worker_loop` — ante una caída transitoria de Redis/Postgres,
    se loguea y se espera backoff exponencial en vez de dejar morir el
    proceso.
    """
    redis_client = redis_client or get_redis_client()
    stop_event = stop_event or asyncio.Event()

    async def _iteration() -> None:
        await drain_one(redis_client, timeout_seconds=block_timeout_seconds)

    logger.info("stt_worker_started", queue=STT_JOBS_QUEUE_KEY)
    await resilient_worker_loop(_iteration, stop_event=stop_event, worker_name="stt_worker")
    logger.info("stt_worker_stopped")


def _run_forever_with_signal_handling() -> None:
    """Punto de entrada del proceso worker independiente (`python -m
    app.workers.stt_worker`), usado por el servicio `stt_worker` de
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
