"""Worker de ingesta de WhatsApp — consume `wa:inbound` — SPEC-027, ADR-007/008.
Procesa también los callbacks de estado (`value.statuses[]`) del mismo
evento — SPEC-030 (ver `_process_status_event` más abajo).

`process_job` procesa UN evento crudo ya extraído de la cola (`InboundWebhookJob`,
encolado por el webhook de SPEC-026):

  1. Parsea el payload (`app.integrations.whatsapp.inbound_parser`) y extrae
     los mensajes ENTRANTES (`value.messages[]`, SPEC-027) y los callbacks de
     estado (`value.statuses[]`, SPEC-030) por separado.
  2. Por cada mensaje: RESUELVE `phone_number_id -> tenant_id` con la función
     SQL `resolve_tenant_by_phone_number_id` (SECURITY DEFINER, ADR-008) —
     SIN fijar `app.tenant_id` de sesión todavía (la función corre con los
     privilegios del owner, no necesita RLS fijado para leer
     `whatsapp_accounts`). Sin mapeo -> descarte auditado (log), CERO
     escritura (RF-04).
  3. Recién con el tenant resuelto, fija RLS (`set_tenant_session`) y opera
     bajo RLS el resto de la transacción (ADR-004/ADR-007).
  4. IDEMPOTENCIA por `wamid` (RF-01/RF-02, ADR-007): antes de insertar,
     comprueba si ya existe un `message` con ese `wamid` dentro del tenant
     resuelto; si existe, no-op (dedup). La restricción UNIQUE de BD
     (SPEC-025, `messages.wamid`) es la garantía dura ante condiciones de
     carrera entre workers; esta comprobación evita además trabajo
     redundante (crear contacto/conversación) en el camino feliz.
  5. Encuentra/crea el contacto (por `wa_id` dentro del tenant) y la
     conversación (`canal="whatsapp"`), y persiste el mensaje entrante
     reutilizando `app.services.message_service.create_message` +
     actualización de `wamid`/`estado_entrega` inicial ("enviado", mismo
     vocabulario que SPEC-015, ver `app/models/message.py`).

Disparo del pipeline IA (sentimiento/RAG) — SPEC-028, reutiliza SPEC-017/018
sin crear componentes de IA nuevos:
  6. Tras persistir el mensaje entrante, se dispara sentimiento (SPEC-018,
     `app.services.message_service.schedule_sentiment_analysis`, mismo
     patrón best-effort que WebChat/REST: encola en Redis y jamás bloquea ni
     rompe la ingesta si Redis/el encolado fallan) y se genera Y PERSISTE
     (estado `propuesto`, SPEC-019) un borrador RAG con ≥3 citas trazables
     (SPEC-017, `generate_rag_draft` + `draft_review_service.create_draft`)
     para que el agente humano lo revise en la Bandeja — NADA se envía
     automáticamente al contacto (SPEC-019/RF-03 de SPEC-028, aprobación
     humana explícita vía `POST .../drafts/{id}/approve`).
  7. Modo degradado (R-21, RNF-01 sin egress): si el LLM local no está
     disponible (`AIServiceError`) o no hay suficiente contexto para ≥3
     citas (`InsufficientContextError`), NO se genera el borrador — se
     loguea la condición y el mensaje YA PERSISTIDO en el paso 5 no se ve
     afectado; ningún error de IA revierte ni bloquea la ingesta.

Robustez (hallazgo M-1 de BLACK WIDOW en SPEC-026, RNF-05): un fallo
procesando UN evento se loguea con `exc_info` y NO detiene el loop del
worker ni se reintenta en bucle infinito dentro del mismo proceso — el job ya
salió de la cola (`BLPOP` es destructivo) así que un evento que falle de
forma persistente no bloquea a los siguientes; queda auditado en logs para
investigación manual (mismo criterio de "no reventar el proceso" que
`rag_ingest_worker`/`sentiment_worker`, que capturan sus propios casos
degradados sin propagar excepciones fuera de `process_job` salvo el caso
explícito de `TenantMismatchError`, que aquí no aplica porque el tenant se
resuelve DENTRO de `process_job`, nunca se recibe de un job forjado).

Statuses de entrega (SPEC-030, ADR-007) — `_process_status_event`:
  1. Parsea `value.statuses[]` (`inbound_parser.parse_status_events`), un
     callback por cada `wamid` de un mensaje SALIENTE (SPEC-029).
  2. RESUELVE tenant por `phone_number_id` con la MISMA función SECURITY
     DEFINER que los mensajes entrantes (`_resolve_tenant_id`); sin mapeo,
     descarte auditado, cero escritura (mismo criterio que RF-04 de SPEC-027).
  3. Fija RLS (`set_tenant_session`) y busca el mensaje por `wamid` DENTRO
     del tenant resuelto (RNF-04, aislamiento): un `wamid` que no pertenece a
     ese tenant (o que no existe) no aparece en la consulta (RLS lo filtra) y
     el status se ignora/loguea sin romper (RF-03/R-34).
  4. Mapea `sent/delivered/read` -> `estado_entrega` interno
     (`enviado/entregado/leido`) y reutiliza `update_delivery_status`
     (SPEC-015), que ya es monotónica (no retrocede) e idempotente ante
     duplicados/reentregas (R-33): aplicarla dos veces con el mismo status,
     o en cualquier orden, deja el mensaje en el estado más avanzado visto.
  5. `failed` es terminal (mismo vocabulario que `wa_send_worker`,
     `ESTADO_ENTREGA_FAILED`): se asigna directamente (fuera de la
     progresión monotónica, igual que en el envío) y el motivo (`errors[].
     title` de Meta, nunca contenido del mensaje ni datos del contacto, C2/C3)
     se registra SOLO en el log estructurado, no en una columna nueva.
"""

from __future__ import annotations

import asyncio
import signal
import uuid
from typing import Callable

import redis.asyncio as redis_asyncio
import sqlalchemy as sa
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis_client
from app.core.whatsapp_queue import (
    INBOUND_QUEUE_KEY,
    InboundWebhookJob,
    dequeue_inbound_webhook_event,
)
from app.core.worker_resilience import resilient_worker_loop
from app.db.session import SessionLocal, set_tenant_session
from app.integrations.whatsapp.inbound_parser import (
    InboundEventParseError,
    InboundMessageEvent,
    StatusEvent,
    parse_inbound_message_events,
    parse_status_events,
)
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.message import ESTADO_ENTREGA_FAILED, Message
from app.services.ai_service import AIClient, AIServiceError
from app.services.message_service import (
    create_message,
    schedule_sentiment_analysis,
    update_delivery_status,
)
from app.services.rag import draft_review_service
from app.services.rag.draft_service import InsufficientContextError, generate_rag_draft

logger = structlog.get_logger(__name__)

_CANAL_WHATSAPP = "whatsapp"
_REMITENTE_CONTACTO = "contacto"

# Mapeo de status de Meta (SPEC-030) -> vocabulario interno de
# `messages.estado_entrega` (SPEC-015/025). `failed` se maneja aparte
# (estado terminal, `ESTADO_ENTREGA_FAILED`, fuera de la progresión
# monotónica de `update_delivery_status`).
_STATUS_TO_ESTADO_ENTREGA = {
    "sent": "enviado",
    "delivered": "entregado",
    "read": "leido",
}
_STATUS_FAILED = "failed"


def _resolve_tenant_id(db: Session, *, phone_number_id: str) -> uuid.UUID | None:
    """Invoca la función SQL `resolve_tenant_by_phone_number_id` (SECURITY
    DEFINER, ADR-008) — NUNCA un SELECT directo sobre `whatsapp_accounts`,
    que devolvería 0 filas bajo RLS sin `app.tenant_id` fijado todavía (la
    resolución es, por definición, PRE-tenant). Se ejecuta en su propia
    transacción de solo lectura, sin fijar RLS."""
    try:
        tenant_id = db.execute(
            sa.text("SELECT resolve_tenant_by_phone_number_id(:pni) AS tenant_id"),
            {"pni": phone_number_id},
        ).scalar_one_or_none()
    finally:
        db.rollback()  # cierra la transacción de solo lectura sin efectos
    return tenant_id


def _message_wamid_exists(db: Session, *, wamid: str) -> bool:
    """Dedup por `wamid` (RF-02, ADR-007): consulta previa bajo RLS (ya con
    `app.tenant_id` fijado) para no rehacer contacto/conversación en el
    camino feliz. La restricción UNIQUE de BD (SPEC-025) es la garantía dura
    ante condiciones de carrera; esta consulta es una optimización/guarda
    adicional del worker, no el único mecanismo."""
    return (
        db.execute(
            sa.text("SELECT 1 FROM messages WHERE wamid = :wamid LIMIT 1"),
            {"wamid": wamid},
        ).scalar_one_or_none()
        is not None
    )


def _get_or_create_contact(
    db: Session, *, tenant_id: uuid.UUID, wa_id: str, contact_name: str | None
) -> Contact:
    """Busca un contacto activo por `telefono == wa_id` dentro del tenant
    (RLS ya fijado); si no existe, lo crea. `wa_id` es el identificador de
    WhatsApp del remitente, reutilizado como `telefono` (mismo campo que ya
    usa el resto del dominio, sin añadir columnas nuevas)."""
    contact = db.scalar(
        sa.select(Contact).where(Contact.telefono == wa_id, Contact.activo.is_(True))
    )
    if contact is not None:
        return contact

    contact = Contact(
        tenant_id=tenant_id,
        nombre=contact_name or wa_id,
        telefono=wa_id,
    )
    db.add(contact)
    db.flush()
    db.refresh(contact)
    return contact


def _get_or_create_conversation(
    db: Session, *, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> Conversation:
    """Busca una conversación activa de canal WhatsApp para el contacto; si
    no existe, la crea. Reutiliza el mismo hilo para mensajes sucesivos del
    mismo contacto en vez de crear una conversación por mensaje."""
    conversation = db.scalar(
        sa.select(Conversation).where(
            Conversation.contact_id == contact_id,
            Conversation.canal == _CANAL_WHATSAPP,
            Conversation.activo.is_(True),
        )
    )
    if conversation is not None:
        return conversation

    conversation = Conversation(
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal=_CANAL_WHATSAPP,
        estado="abierta",
    )
    db.add(conversation)
    db.flush()
    db.refresh(conversation)
    return conversation


def _schedule_sentiment_best_effort(
    redis_client: redis_asyncio.Redis, *, message
) -> None:
    """Wrapper sync -> async para disparar sentimiento (SPEC-018) desde este
    worker síncrono, MISMO patrón que `app/api/messages.py::
    _run_schedule_sentiment_analysis`: `asyncio.run` crea/cierra su propio
    loop porque `_process_message_event` no corre dentro de un loop activo
    (es una llamada sync ordinaria, incluso cuando el llamador raíz es
    `drain_one`/`run_worker_loop`, que están *await*-eando `process_job` de
    forma bloqueante, no ejecutándolo concurrentemente).

    Best-effort (SPEC-018 RF): `schedule_sentiment_analysis` ya captura sus
    propias excepciones de encolado (Redis caído, etc.) y jamás las propaga;
    aquí solo se añade una defensa adicional para que un fallo inesperado en
    el propio wrapper (p.ej. el loop de asyncio) tampoco tumbe la ingesta.
    """
    try:
        asyncio.run(schedule_sentiment_analysis(redis_client, message=message))
    except Exception:  # noqa: BLE001 — best-effort, nunca bloquea la ingesta
        logger.warning(
            "whatsapp_inbound_sentiment_dispatch_failed",
            message_id=str(message.id),
            tenant_id=str(message.tenant_id),
            exc_info=True,
        )


def _generate_rag_draft_best_effort(
    db: Session,
    ai_client: AIClient,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    query: str,
) -> None:
    """Genera Y PERSISTA (estado `propuesto`, SPEC-019) el borrador RAG con
    ≥3 citas trazables (SPEC-017) para que el agente humano lo revise en la
    Bandeja. MISMO flujo que `app/api/rag.py::create_draft_endpoint`
    (`generate_rag_draft` + `draft_review_service.create_draft`), reutilizado
    aquí sin duplicar lógica de generación/persistencia.

    RESTRICCIÓN DURA (SPEC-019, heredada): esta función NUNCA llama a
    `create_message`/`approve_and_send` — el borrador queda en `propuesto`,
    a la espera de que un agente humano lo apruebe explícitamente.

    Modo degradado (R-21, RNF-01 IA sin egress): si el LLM local no está
    disponible (`AIServiceError`, incluye timeouts/errores de conexión) o no
    hay suficiente contexto recuperado para garantizar ≥3 citas
    (`InsufficientContextError`), NO se genera el borrador — se loguea la
    condición (sin contenido del mensaje, C2/C3) y se retorna sin propagar:
    el mensaje entrante YA quedó persistido por `_process_message_event`
    antes de llegar aquí, así que un fallo de IA nunca revierte la ingesta.

    RLS (ADR-004): `SET LOCAL app.tenant_id` fijado por `_process_message_
    event` para insertar el mensaje solo vive dentro de ESA transacción (ya
    cerrada, commit, al llegar aquí) — por eso esta función abre su propia
    transacción y vuelve a fijar `app.tenant_id` ANTES de recuperar contexto
    (`generate_rag_draft` lee `chunks`/`embeddings` bajo RLS) y de persistir
    el borrador, mismo criterio que el resto de workers (`sentiment_worker`).
    """
    try:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            try:
                result = generate_rag_draft(db, ai_client, query=query)
            except InsufficientContextError:
                logger.info(
                    "whatsapp_inbound_rag_draft_insufficient_context",
                    tenant_id=str(tenant_id),
                    conversation_id=str(conversation_id),
                )
                return
            except AIServiceError:
                logger.warning(
                    "whatsapp_inbound_rag_draft_ai_unavailable_degraded",
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
    except Exception:  # noqa: BLE001 — best-effort, nunca bloquea la ingesta
        logger.error(
            "whatsapp_inbound_rag_draft_dispatch_failed",
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            exc_info=True,
        )
        return

    logger.info(
        "whatsapp_inbound_rag_draft_proposed",
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
    )


def _process_message_event(
    db: Session,
    event: InboundMessageEvent,
    *,
    event_id: str,
    redis_client: redis_asyncio.Redis | None = None,
    ai_client: AIClient | None = None,
) -> None:
    """Procesa UN mensaje entrante ya parseado: resuelve tenant, fija RLS,
    deduplica por `wamid` y persiste contacto/conversación/mensaje.

    Sin mapeo de `phone_number_id` -> descarte auditado, CERO escritura
    (RF-04): se loguea `phone_number_id`/`wamid`/`event_id` (metadatos de
    enrutado), NUNCA el contenido del mensaje (C2/C3, minimización de
    datos ante un evento no enrutable).

    `redis_client`/`ai_client` son SOLO para pruebas (inyectan dobles en vez
    de `get_redis_client()`/`AIClient()` reales); en producción ambos se
    resuelven perezosamente (factories reales) para no abrir conexiones
    innecesarias en el camino de descarte/duplicado (arriba de este docstring).
    """
    tenant_id = _resolve_tenant_id(db, phone_number_id=event.phone_number_id)
    if tenant_id is None:
        logger.warning(
            "whatsapp_inbound_unmapped_phone_number_id_discarded",
            phone_number_id=event.phone_number_id,
            wamid=event.wamid,
            event_id=event_id,
        )
        return

    try:
        with db.begin():
            set_tenant_session(db, str(tenant_id))

            if _message_wamid_exists(db, wamid=event.wamid):
                # RF-02: reentrega de Meta con el mismo wamid -> no-op idempotente.
                logger.info(
                    "whatsapp_inbound_duplicate_wamid_skipped",
                    wamid=event.wamid,
                    tenant_id=str(tenant_id),
                    event_id=event_id,
                )
                return

            contact = _get_or_create_contact(
                db,
                tenant_id=tenant_id,
                wa_id=event.wa_id,
                contact_name=event.contact_name,
            )
            conversation = _get_or_create_conversation(
                db, tenant_id=tenant_id, contact_id=contact.id
            )
            message = create_message(
                db,
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                remitente=_REMITENTE_CONTACTO,
                contenido=(
                    event.texto if event.texto is not None else f"[{event.tipo}]"
                ),
            )
            message.wamid = event.wamid
            db.flush()
    except IntegrityError:
        # Condición de carrera entre workers/reintentos concurrentes sobre el
        # MISMO wamid: la restricción UNIQUE de BD (SPEC-025) es la garantía
        # dura de idempotencia (ADR-007) cuando la comprobación previa
        # (`_message_wamid_exists`) pierde la carrera. Se trata igual que un
        # duplicado detectado por la guarda: no-op, sin propagar el error.
        db.rollback()
        logger.info(
            "whatsapp_inbound_duplicate_wamid_race_detected",
            wamid=event.wamid,
            tenant_id=str(tenant_id),
            event_id=event_id,
        )
        return

    logger.info(
        "whatsapp_inbound_message_persisted",
        tenant_id=str(tenant_id),
        wamid=event.wamid,
        conversation_id=str(conversation.id),
        event_id=event_id,
    )

    # SPEC-028: dispara el pipeline IA local (sentimiento SPEC-018 + borrador
    # RAG SPEC-019) sobre el mensaje YA persistido; ambos son best-effort/
    # modo degradado (ver docstrings) y NUNCA revierten ni bloquean la
    # ingesta ya confirmada arriba.
    _schedule_sentiment_best_effort(redis_client or get_redis_client(), message=message)
    _generate_rag_draft_best_effort(
        db,
        ai_client or AIClient(),
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        query=message.contenido,
    )


def _get_message_by_wamid(db: Session, *, wamid: str) -> Message | None:
    """Busca el mensaje SALIENTE conciliado por `wamid` DENTRO del tenant de
    la sesión (RLS ya fijado, `set_tenant_session`). Un `wamid` de otro
    tenant simplemente no aparece (RLS lo filtra a nivel de fila) — se trata
    igual que un `wamid` desconocido (RF-03/RNF-04, R-34)."""
    return db.scalar(sa.select(Message).where(Message.wamid == wamid))


def _process_status_event(
    db: Session,
    event: StatusEvent,
    *,
    event_id: str,
) -> None:
    """Procesa UN callback de estado (`sent/delivered/read/failed`, SPEC-030):
    resuelve tenant, fija RLS, concilia el mensaje SALIENTE por `wamid` y
    actualiza `estado_entrega`.

    Sin mapeo de `phone_number_id` -> descarte auditado, cero escritura
    (mismo criterio RF-04 que `_process_message_event`): se loguean solo
    metadatos de enrutado (`phone_number_id`/`wamid`/`status`/`event_id`),
    NUNCA contenido de mensajes ni datos del contacto (C2/C3).
    """
    tenant_id = _resolve_tenant_id(db, phone_number_id=event.phone_number_id)
    if tenant_id is None:
        logger.warning(
            "whatsapp_status_unmapped_phone_number_id_discarded",
            phone_number_id=event.phone_number_id,
            wamid=event.wamid,
            status=event.status,
            event_id=event_id,
        )
        return

    with db.begin():
        set_tenant_session(db, str(tenant_id))

        message = _get_message_by_wamid(db, wamid=event.wamid)
        if message is None:
            # `wamid` desconocido para este tenant (mensaje no nuestro, o de
            # otro tenant filtrado por RLS): no-op auditado, RF-03/R-34.
            logger.info(
                "whatsapp_status_unknown_wamid_skipped",
                tenant_id=str(tenant_id),
                wamid=event.wamid,
                status=event.status,
                event_id=event_id,
            )
            return

        if event.status == _STATUS_FAILED:
            # Estado TERMINAL (mismo vocabulario que `wa_send_worker`, fuera
            # de la progresión monotónica de `update_delivery_status`): se
            # asigna directamente, igual que en el envío (RF-02).
            message.estado_entrega = ESTADO_ENTREGA_FAILED
            db.flush()
            logger.warning(
                "whatsapp_status_failed_recorded",
                tenant_id=str(tenant_id),
                wamid=event.wamid,
                message_id=str(message.id),
                # Motivo de Meta (título de error), NUNCA contenido del
                # mensaje ni datos del contacto (C2/C3).
                error_titles=event.error_titles,
                event_id=event_id,
            )
            return

        estado_entrega = _STATUS_TO_ESTADO_ENTREGA.get(event.status)
        if estado_entrega is None:
            # Status de Meta no reconocido (futuro valor no documentado):
            # se ignora sin romper, mismo criterio de robustez que un
            # mensaje entrante malformado.
            logger.info(
                "whatsapp_status_unrecognized_value_skipped",
                tenant_id=str(tenant_id),
                wamid=event.wamid,
                status=event.status,
                event_id=event_id,
            )
            return

        if message.estado_entrega == ESTADO_ENTREGA_FAILED:
            # `failed` es TERMINAL (RF-02): un status de progresión reentregado
            # fuera de orden (p.ej. un `delivered` tardío tras un `failed`) NO
            # debe revivir el mensaje ni corromper el estado (R-33, idempotencia
            # ante reentregas/desorden de Meta).
            logger.info(
                "whatsapp_status_ignored_after_failed",
                tenant_id=str(tenant_id),
                wamid=event.wamid,
                status=event.status,
                event_id=event_id,
            )
            return

        estado_anterior = message.estado_entrega
        update_delivery_status(db, message, estado_entrega)
        logger.info(
            "whatsapp_status_delivery_updated",
            tenant_id=str(tenant_id),
            wamid=event.wamid,
            message_id=str(message.id),
            status=event.status,
            estado_anterior=estado_anterior,
            estado_actual=message.estado_entrega,
            event_id=event_id,
        )


def process_job(
    job: InboundWebhookJob,
    *,
    session_factory: Callable[[], Session] | None = None,
    redis_client: redis_asyncio.Redis | None = None,
    ai_client: AIClient | None = None,
) -> None:
    """Procesa un job ya extraído de `wa:inbound` (un evento crudo de Meta,
    que puede contener varios mensajes y/o varios callbacks de estado). Un
    fallo procesando un mensaje o un status individual se loguea y NO
    interrumpe el procesamiento de los demás elementos del mismo evento
    (RNF-05, robustez/hallazgo M-1 BLACK WIDOW).

    `session_factory` es SOLO para pruebas (inyecta una `Session` sobre el
    `postgres_engine` de test en vez del `SessionLocal` cacheado).
    `redis_client`/`ai_client` (SPEC-028) son SOLO para pruebas (inyectan
    dobles de sentimiento/RAG en vez de instancias reales).
    """
    try:
        events = parse_inbound_message_events(job.raw_body)
        status_events = parse_status_events(job.raw_body)
    except InboundEventParseError:
        logger.warning(
            "whatsapp_inbound_payload_parse_error",
            event_id=job.event_id,
            exc_info=True,
        )
        return

    if not events and not status_events:
        logger.info(
            "whatsapp_inbound_no_message_events", event_id=job.event_id
        )  # payload sin mensajes ni statuses reconocibles (otros campos)
        return

    db = (session_factory or SessionLocal)()
    try:
        for event in events:
            try:
                _process_message_event(
                    db,
                    event,
                    event_id=job.event_id,
                    redis_client=redis_client,
                    ai_client=ai_client,
                )
            except Exception:  # noqa: BLE001 — robustez: un mensaje no tumba el worker
                db.rollback()
                logger.error(
                    "whatsapp_inbound_message_processing_failed",
                    event_id=job.event_id,
                    wamid=event.wamid,
                    exc_info=True,
                )

        for status_event in status_events:
            try:
                _process_status_event(db, status_event, event_id=job.event_id)
            except Exception:  # noqa: BLE001 — robustez: un status no tumba el worker
                db.rollback()
                logger.error(
                    "whatsapp_status_processing_failed",
                    event_id=job.event_id,
                    wamid=status_event.wamid,
                    status=status_event.status,
                    exc_info=True,
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
    """Extrae y procesa UN único job pendiente de `wa:inbound`.

    Devuelve `True` si procesó un job, `False` si la cola estaba vacía.

    `redis_client` (además de fuente de la cola `wa:inbound`) se reutiliza
    como cliente de encolado de sentimiento (SPEC-028/018): mismo Redis, sin
    abrir una segunda conexión.
    """
    job = await dequeue_inbound_webhook_event(
        redis_client, timeout_seconds=timeout_seconds
    )
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
    """Loop principal del proceso worker (`whatsapp_inbound_worker` en
    docker-compose). Consume `wa:inbound` con `BLPOP` (bloqueante, sin
    busy-waiting) — mismo patrón que `rag_ingest_worker`/`sentiment_worker`,
    pero sin namespacing por tenant en la cola (el tenant AÚN no se conoce al
    encolar, ADR-007): cada `BLPOP` extrae directamente el siguiente evento
    de `wa:inbound` (cola global) y `process_job` resuelve el tenant.

    Hardening (SPEC-032, deuda SPEC-027/BLACK PANTHER): cada iteración corre
    envuelta en `resilient_worker_loop` — ante una caída transitoria de
    Redis/Postgres, se loguea y se espera backoff exponencial en vez de
    dejar morir el proceso (evita crash-loop de `restart: unless-stopped`).
    """
    redis_client = redis_client or get_redis_client()
    stop_event = stop_event or asyncio.Event()

    async def _iteration() -> None:
        await drain_one(redis_client, timeout_seconds=block_timeout_seconds)

    logger.info("whatsapp_inbound_worker_started", queue=INBOUND_QUEUE_KEY)
    await resilient_worker_loop(
        _iteration, stop_event=stop_event, worker_name="whatsapp_inbound_worker"
    )
    logger.info("whatsapp_inbound_worker_stopped")


def _run_forever_with_signal_handling() -> None:
    """Punto de entrada del proceso worker independiente (`python -m
    app.workers.whatsapp_inbound_worker`), usado por el servicio
    `whatsapp_inbound_worker` de `docker-compose.yml`. Se apaga limpiamente
    ante SIGTERM/SIGINT."""

    async def _main() -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)
        await run_worker_loop(stop_event=stop_event)

    asyncio.run(_main())


if __name__ == "__main__":
    _run_forever_with_signal_handling()
