"""Worker de ingesta de Instagram DM — consume `ig:inbound` — SPEC-087,
ADR-007/008. Espejo EXACTO de `app.workers.whatsapp_inbound_worker`
(SPEC-027/028/030) adaptado al formato/routing de Instagram (SPEC-085/086).

`process_job` procesa UN evento crudo ya extraído de la cola
(`InboundInstagramJob`, encolado por el webhook de SPEC-086):

  1. Parsea el payload (`app.integrations.instagram.inbound_parser`) y
     extrae los mensajes entrantes (`entry[].messaging[]` con `message`,
     SPEC-086) — `InstagramMessageEvent` por cada uno.
  2. Por cada mensaje: RESUELVE `instagram_account_id (=recipient.id) ->
     tenant_id` con la función SQL `resolve_tenant_by_instagram_account_id`
     (SECURITY DEFINER, ADR-008) — SIN fijar `app.tenant_id` de sesión
     todavía (la función corre con los privilegios del owner, no necesita
     RLS fijado para leer `instagram_accounts`). Sin mapeo -> descarte
     auditado (log con SOLO metadatos), CERO escritura (RF-01, CE-116).
  3. Recién con el tenant resuelto, fija RLS (`set_tenant_session`) y opera
     bajo RLS el resto de la transacción (ADR-004/ADR-007).
  4. IDEMPOTENCIA por `mid` (RF-03, ADR-007): el `mid` de Instagram se
     persiste en la columna YA EXISTENTE `messages.wamid` (§3.4 de
     SPEC-085/087, "id de mensaje del canal externo" genérico — WhatsApp
     guarda su `wamid`, Instagram guarda su `mid`, sin renombrar ni añadir
     columnas). Antes de insertar, comprueba si ya existe un `message` con
     ese `mid` (en `wamid`) dentro del tenant resuelto; si existe, no-op
     (dedup). La restricción UNIQUE de BD (`messages.wamid`, SPEC-025) es la
     garantía dura ante condiciones de carrera entre workers (`except
     IntegrityError` -> duplicado, no propagar).
  5. Encuentra/crea el contacto (por el identificador de Instagram del
     remitente, `sender_id`, reutilizando el campo `telefono` de `Contact`
     con el MISMO criterio que `wa_id` de WhatsApp — sin añadir columnas
     nuevas, BLACK PANTHER) y la conversación (`canal="instagram"`), y
     persiste el mensaje entrante reutilizando
     `app.services.message_service.create_message`.
  6. Si el evento trae adjuntos (`event.attachments`, RF-01 SPEC-088):
     persiste la URL del CDN de Meta (`media_url`) y su `type` (`media_type`)
     TAL CUAL llegan, EN EL MISMO FLUJO SÍNCRONO de persistencia del mensaje
     (dentro de la misma transacción que fija `message.wamid`) — SIN
     descargar el binario y SIN abrir ninguna conexión hacia el CDN
     (SPEC-088, política de Meta `chatwoot#8583`). Antes de persistir, la
     URL se valida en FORMA (`https` + host EXACTO `lookaside.fbsbx.com` +
     sin userinfo, `media_url_validator.is_valid_instagram_media_url`); si
     no pasa la validación, se audita (solo metadatos) y NO se persiste la
     referencia — el mensaje de texto, si lo hay, se persiste igual. Si el
     evento trae varios adjuntos, esta V1 persiste SOLO EL PRIMERO válido
     (decisión de implementación acotada, SPEC-088: un DM típico de
     Instagram trae un único adjunto por mensaje; ver comentario en
     `_select_first_valid_attachment`). Ya NO se encola en `ig:media_pending`
     (esa cola queda OBSOLETA desde SPEC-088: no hay descarga asíncrona que
     hacer — el render de la media ocurre desde el cliente, consumiendo
     `media_url` directamente).

Disparo del pipeline IA (sentimiento/RAG) — SPEC-028, reutiliza SPEC-017/018
sin crear componentes de IA nuevos (RF-05, RNF-IA-REUTILIZADA):
  7. Tras persistir el mensaje entrante, se dispara sentimiento (SPEC-018,
     `app.services.message_service.schedule_sentiment_analysis`, mismo
     patrón best-effort que WhatsApp/WebChat: encola en Redis y jamás
     bloquea ni rompe la ingesta si Redis/el encolado fallan) y se genera Y
     PERSISTE (estado `propuesto`, SPEC-019) un borrador RAG con ≥3 citas
     trazables (SPEC-017, `generate_rag_draft` + `draft_review_service.
     create_draft`) para que el agente humano lo revise en la Bandeja —
     NADA se envía automáticamente al contacto (SPEC-019, aprobación humana
     explícita vía `POST .../drafts/{id}/approve`).
  8. Modo degradado (R-21, RNF-01 sin egress): si el LLM local no está
     disponible (`AIServiceError`) o no hay suficiente contexto para ≥3
     citas (`InsufficientContextError`), NO se genera el borrador — se
     loguea la condición y el mensaje YA PERSISTIDO en el paso 5 no se ve
     afectado; ningún error de IA revierte ni bloquea la ingesta.

Robustez (RNF-ROBUSTEZ, mismo criterio que WhatsApp SPEC-026/032): un fallo
procesando UN evento se loguea con `exc_info` y NO detiene el loop del
worker — el job ya salió de la cola (`BLPOP` es destructivo) así que un
evento que falle de forma persistente no bloquea a los siguientes.

RNF-IA-REUTILIZADA / RNF-NO-REGRESION: este módulo NO importa Ollama ni
`httpx` directamente (verificado por `check-externos-backend.sh`); invoca
exclusivamente los servicios de dominio YA EXISTENTES
(`schedule_sentiment_analysis`, `generate_rag_draft`,
`draft_review_service.create_draft`). La cola `ig:inbound` es DISTINTA de
`wa:inbound` (R-117, cero regresión del canal WhatsApp).
"""

from __future__ import annotations

import asyncio
import signal
import uuid
from types import SimpleNamespace
from typing import Callable

import redis.asyncio as redis_asyncio
import sqlalchemy as sa
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.async_utils import run_coroutine_best_effort
from app.core.instagram_queue import (
    INBOUND_QUEUE_KEY,
    InboundInstagramJob,
    dequeue_inbound_instagram_event,
)
from app.core.redis_client import get_redis_client
from app.core.worker_resilience import resilient_worker_loop
from app.db.session import SessionLocal, set_tenant_session
from app.integrations.instagram.inbound_parser import (
    InboundEventParseError,
    InstagramMessageEvent,
    parse_inbound_instagram_events,
)
from app.integrations.instagram.media_url_validator import (
    is_valid_instagram_media_url,
)
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.services.ai_service import AIClient, AIServiceError
from app.services.message_service import create_message, schedule_sentiment_analysis
from app.services.rag import draft_review_service
from app.services.rag.draft_service import InsufficientContextError, generate_rag_draft

logger = structlog.get_logger(__name__)

_CANAL_INSTAGRAM = "instagram"
_REMITENTE_CONTACTO = "contacto"


def _resolve_tenant_id(db: Session, *, instagram_account_id: str) -> uuid.UUID | None:
    """Invoca la función SQL `resolve_tenant_by_instagram_account_id`
    (SECURITY DEFINER, ADR-008) — NUNCA un SELECT directo sobre
    `instagram_accounts`, que devolvería 0 filas bajo RLS sin
    `app.tenant_id` fijado todavía (la resolución es, por definición,
    PRE-tenant). Se ejecuta en su propia transacción de solo lectura, sin
    fijar RLS."""
    try:
        tenant_id = db.execute(
            sa.text(
                "SELECT resolve_tenant_by_instagram_account_id(:iaid) AS tenant_id"
            ),
            {"iaid": instagram_account_id},
        ).scalar_one_or_none()
    finally:
        db.rollback()  # cierra la transacción de solo lectura sin efectos
    return tenant_id


def _message_mid_exists(db: Session, *, mid: str) -> bool:
    """Dedup por `mid` (RF-03, ADR-007): consulta previa bajo RLS (ya con
    `app.tenant_id` fijado) para no rehacer contacto/conversación en el
    camino feliz. Reutiliza la columna YA EXISTENTE `messages.wamid` (§3.4,
    "id de mensaje del canal externo" genérico, sin renombrar). La
    restricción UNIQUE de BD (SPEC-025) es la garantía dura ante
    condiciones de carrera; esta consulta es una optimización/guarda
    adicional del worker, no el único mecanismo."""
    return (
        db.execute(
            sa.text("SELECT 1 FROM messages WHERE wamid = :mid LIMIT 1"),
            {"mid": mid},
        ).scalar_one_or_none()
        is not None
    )


def _get_or_create_contact(
    db: Session, *, tenant_id: uuid.UUID, sender_id: str
) -> Contact:
    """Busca un contacto activo por `telefono == sender_id` dentro del
    tenant (RLS ya fijado); si no existe, lo crea. `sender_id` es el
    identificador de Instagram del remitente, reutilizado como `telefono`
    (MISMO campo/criterio que `wa_id` en el worker de WhatsApp — `Contact`
    no tiene un campo genérico de "id de canal externo" propio, así que se
    reutiliza `telefono` sin añadir columnas nuevas, BLACK PANTHER)."""
    contact = db.scalar(
        sa.select(Contact).where(Contact.telefono == sender_id, Contact.activo.is_(True))
    )
    if contact is not None:
        return contact

    contact = Contact(
        tenant_id=tenant_id,
        nombre=sender_id,
        telefono=sender_id,
    )
    db.add(contact)
    db.flush()
    db.refresh(contact)
    return contact


def _get_or_create_conversation(
    db: Session, *, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> Conversation:
    """Busca una conversación activa de canal Instagram para el contacto; si
    no existe, la crea. Reutiliza el mismo hilo para mensajes sucesivos del
    mismo contacto en vez de crear una conversación por mensaje."""
    conversation = db.scalar(
        sa.select(Conversation).where(
            Conversation.contact_id == contact_id,
            Conversation.canal == _CANAL_INSTAGRAM,
            Conversation.activo.is_(True),
        )
    )
    if conversation is not None:
        return conversation

    conversation = Conversation(
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal=_CANAL_INSTAGRAM,
        estado="abierta",
    )
    db.add(conversation)
    db.flush()
    db.refresh(conversation)
    return conversation


def _select_first_valid_attachment(
    attachments: list[dict[str, str | None]],
    *,
    tenant_id: uuid.UUID,
    mid: str,
    event_id: str,
) -> dict[str, str | None] | None:
    """Selecciona el PRIMER adjunto cuya URL pasa la validación de forma
    (SPEC-088 RF-03), o `None` si ninguno la pasa.

    Decisión de implementación acotada (SPEC-088 §Alcance IN, dejada
    explícitamente al implementador): si un mensaje trae VARIOS adjuntos,
    esta V1 persiste SOLO EL PRIMERO válido en una columna única
    (`media_url`/`media_type`), en vez de introducir una tabla hija para
    multiplicidad. Se opta por esto porque un DM típico de Instagram trae un
    único adjunto por mensaje (la UI nativa de Instagram no permite adjuntar
    más de un archivo por envío) — una tabla hija añadiría complejidad de
    esquema sin un caso de uso real que la justifique hoy; si una SPEC
    futura requiere exponer múltiples adjuntos por mensaje, se puede
    introducir sin romper esta columna (aditivo).

    Cada URL inválida encontrada en el recorrido se audita individualmente
    (RF-03): host distinto, esquema no-https o userinfo embebido -> se
    loguea SOLO metadatos (`tenant_id`/`mid`/`event_id`, NUNCA la URL con su
    `signature`, C2/RNF-C2) y se sigue probando con el siguiente adjunto."""
    for attachment in attachments:
        url = attachment.get("url")
        if is_valid_instagram_media_url(url):
            return attachment
        logger.warning(
            "instagram_inbound_media_url_invalid_discarded",
            tenant_id=str(tenant_id),
            mid=mid,
            event_id=event_id,
        )
    return None


def _schedule_sentiment_best_effort(
    redis_client: redis_asyncio.Redis, *, message
) -> None:
    """Wrapper sync -> async para disparar sentimiento (SPEC-018) desde este
    worker síncrono, MISMO patrón EXACTO que
    `whatsapp_inbound_worker._schedule_sentiment_best_effort`:
    `run_coroutine_best_effort` funciona con o sin loop activo en el hilo
    actual (`process_job` se invoca en producción real desde
    `drain_one`/`run_worker_loop`, que YA corren dentro de un event loop
    activo).

    Best-effort (SPEC-018 RF): `schedule_sentiment_analysis` ya captura sus
    propias excepciones de encolado (Redis caído, etc.) y jamás las
    propaga; aquí solo se añade una defensa adicional para que un fallo
    inesperado en el propio wrapper tampoco tumbe la ingesta.
    """
    try:
        run_coroutine_best_effort(
            schedule_sentiment_analysis(redis_client, message=message)
        )
    except Exception:  # noqa: BLE001 — best-effort, nunca bloquea la ingesta
        logger.warning(
            "instagram_inbound_sentiment_dispatch_failed",
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
    """Genera Y PERSISTE (estado `propuesto`, SPEC-019) el borrador RAG con
    ≥3 citas trazables (SPEC-017) para que el agente humano lo revise en la
    Bandeja. MISMO flujo EXACTO que
    `whatsapp_inbound_worker._generate_rag_draft_best_effort`
    (`generate_rag_draft` + `draft_review_service.create_draft`),
    reutilizado aquí sin duplicar lógica de generación/persistencia.

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
    y de persistir el borrador, mismo criterio que el resto de workers.
    """
    try:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            try:
                result = generate_rag_draft(db, ai_client, query=query)
            except InsufficientContextError:
                logger.info(
                    "instagram_inbound_rag_draft_insufficient_context",
                    tenant_id=str(tenant_id),
                    conversation_id=str(conversation_id),
                )
                return
            except AIServiceError:
                logger.warning(
                    "instagram_inbound_rag_draft_ai_unavailable_degraded",
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
            "instagram_inbound_rag_draft_dispatch_failed",
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            exc_info=True,
        )
        return

    logger.info(
        "instagram_inbound_rag_draft_proposed",
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
    )


def _process_message_event(
    db: Session,
    event: InstagramMessageEvent,
    *,
    event_id: str,
    redis_client: redis_asyncio.Redis | None = None,
    ai_client: AIClient | None = None,
) -> None:
    """Procesa UN DM entrante ya parseado: resuelve tenant, fija RLS,
    deduplica por `mid` y persiste contacto/conversación/mensaje.

    Sin mapeo de `instagram_account_id` -> descarte auditado, CERO
    escritura (RF-01): se loguea `instagram_account_id`/`mid`/`event_id`
    (metadatos de enrutado), NUNCA el contenido del mensaje (C2/C3,
    minimización de datos ante un evento no enrutable).

    `redis_client`/`ai_client` son SOLO para pruebas (inyectan dobles en vez
    de `get_redis_client()`/`AIClient()` reales); en producción ambos se
    resuelven perezosamente (factories reales) para no abrir conexiones
    innecesarias en el camino de descarte/duplicado.
    """
    tenant_id = _resolve_tenant_id(db, instagram_account_id=event.instagram_account_id)
    if tenant_id is None:
        logger.warning(
            "instagram_inbound_unmapped_account_id_discarded",
            instagram_account_id=event.instagram_account_id,
            mid=event.mid,
            event_id=event_id,
        )
        return

    contenido = event.texto if event.texto is not None else f"[{event.tipo}]"

    try:
        with db.begin():
            set_tenant_session(db, str(tenant_id))

            if _message_mid_exists(db, mid=event.mid):
                # RF-03: reentrega de Meta con el mismo mid -> no-op idempotente.
                logger.info(
                    "instagram_inbound_duplicate_mid_skipped",
                    mid=event.mid,
                    tenant_id=str(tenant_id),
                    event_id=event_id,
                )
                return

            contact = _get_or_create_contact(
                db, tenant_id=tenant_id, sender_id=event.sender_id
            )
            conversation = _get_or_create_conversation(
                db, tenant_id=tenant_id, contact_id=contact.id
            )
            message = create_message(
                db,
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                remitente=_REMITENTE_CONTACTO,
                contenido=contenido,
            )
            message.wamid = event.mid

            # SPEC-088 RF-01: si el evento trae adjuntos, persiste la
            # referencia (URL del CDN de Meta + type) EN ESTE MISMO FLUJO
            # SÍNCRONO, tras validar su FORMA (sin abrir conexión, RF-03) —
            # ya NO se encola en `ig:media_pending` (cola obsoleta, ver
            # docstring del módulo). Un adjunto inválido se audita y no se
            # persiste, sin afectar el mensaje de texto ya construido arriba.
            if event.attachments:
                selected = _select_first_valid_attachment(
                    event.attachments,
                    tenant_id=tenant_id,
                    mid=event.mid,
                    event_id=event_id,
                )
                if selected is not None:
                    message.media_url = selected.get("url")
                    message.media_type = selected.get("type")

            db.flush()
            # Capturados DENTRO de la transacción (con el tenant fijado):
            # los objetos ORM `message`/`conversation` quedan con sus
            # atributos expirados al salir de este `with` (commit,
            # `expire_on_commit=True` por defecto). Reutilizarlos después,
            # fuera de cualquier `app.tenant_id` fijado, dispara un refresh
            # implícito que bajo RLS real (`omnicore_app`, ADR-008) ve 0
            # filas (`ObjectDeletedError`, fail-closed) y bajo el rol owner
            # deja a `db` en "autobegin", rompiendo el siguiente `with
            # db.begin():` con `InvalidRequestError` — mismo hallazgo
            # confirmado contra Postgres real en `whatsapp_inbound_worker`.
            # `contenido` ya es una variable plana capturada arriba, así
            # que no hace falta releerla de `message`.
            message_id = message.id
            conversation_id = conversation.id
    except IntegrityError:
        # Condición de carrera entre workers/reintentos concurrentes sobre el
        # MISMO mid: la restricción UNIQUE de BD (`messages.wamid`, SPEC-025)
        # es la garantía dura de idempotencia (ADR-007) cuando la
        # comprobación previa (`_message_mid_exists`) pierde la carrera. Se
        # trata igual que un duplicado detectado por la guarda: no-op, sin
        # propagar el error.
        db.rollback()
        logger.info(
            "instagram_inbound_duplicate_mid_race_detected",
            mid=event.mid,
            tenant_id=str(tenant_id),
            event_id=event_id,
        )
        return

    logger.info(
        "instagram_inbound_message_persisted",
        tenant_id=str(tenant_id),
        mid=event.mid,
        conversation_id=str(conversation_id),
        event_id=event_id,
    )

    # SPEC-028 (reutilizado tal cual, sin crear IA nueva): dispara el
    # pipeline IA local (sentimiento SPEC-018 + borrador RAG SPEC-019) sobre
    # el mensaje YA persistido; ambos son best-effort/modo degradado (ver
    # docstrings) y NUNCA revierten ni bloquean la ingesta ya confirmada
    # arriba. Usa los valores PLANOS capturados dentro de la transacción de
    # arriba (`message_id`/`conversation_id`/`contenido`), no los objetos
    # ORM `message`/`conversation` (ver comentario junto a su captura).
    fake_message = SimpleNamespace(
        id=message_id, tenant_id=tenant_id, remitente=_REMITENTE_CONTACTO
    )
    _schedule_sentiment_best_effort(
        redis_client or get_redis_client(), message=fake_message
    )
    _generate_rag_draft_best_effort(
        db,
        ai_client or AIClient(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        query=contenido,
    )


def process_job(
    job: InboundInstagramJob,
    *,
    session_factory: Callable[[], Session] | None = None,
    redis_client: redis_asyncio.Redis | None = None,
    ai_client: AIClient | None = None,
) -> None:
    """Procesa un job ya extraído de `ig:inbound` (un evento crudo de Meta,
    que puede contener varios DMs entrantes). Un fallo procesando UN mensaje
    se loguea y NO interrumpe el procesamiento de los demás elementos del
    mismo evento (RNF-ROBUSTEZ, mismo criterio que WhatsApp SPEC-026/032).

    `session_factory` es SOLO para pruebas (inyecta una `Session` sobre el
    `postgres_engine` de test en vez del `SessionLocal` cacheado).
    `redis_client`/`ai_client` son SOLO para pruebas (inyectan dobles de
    sentimiento/RAG en vez de instancias reales).
    """
    try:
        events = parse_inbound_instagram_events(job.raw_body)
    except InboundEventParseError:
        logger.warning(
            "instagram_inbound_payload_parse_error",
            event_id=job.event_id,
            exc_info=True,
        )
        return

    if not events:
        logger.info(
            "instagram_inbound_no_message_events", event_id=job.event_id
        )  # payload sin mensajes entrantes reconocibles (echo/status/otros campos)
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
                    "instagram_inbound_message_processing_failed",
                    event_id=job.event_id,
                    mid=event.mid,
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
    """Extrae y procesa UN único job pendiente de `ig:inbound`.

    Devuelve `True` si procesó un job, `False` si la cola estaba vacía.

    `redis_client` (además de fuente de la cola `ig:inbound`) se reutiliza
    como cliente de encolado de sentimiento/media-pending (SPEC-028/018):
    mismo Redis, sin abrir una segunda conexión.
    """
    job = await dequeue_inbound_instagram_event(
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
    """Loop principal del proceso worker (`instagram_inbound_worker` en
    docker-compose). Consume `ig:inbound` con `BLPOP` (bloqueante, sin
    busy-waiting) — mismo patrón que `whatsapp_inbound_worker`, pero sin
    namespacing por tenant en la cola (el tenant AÚN no se conoce al
    encolar, ADR-007): cada `BLPOP` extrae directamente el siguiente evento
    de `ig:inbound` (cola global) y `process_job` resuelve el tenant.

    Hardening (mismo patrón que SPEC-032/`whatsapp_inbound_worker`): cada
    iteración corre envuelta en `resilient_worker_loop` — ante una caída
    transitoria de Redis/Postgres, se loguea y se espera backoff exponencial
    en vez de dejar morir el proceso (evita crash-loop de `restart:
    unless-stopped`).
    """
    redis_client = redis_client or get_redis_client()
    stop_event = stop_event or asyncio.Event()

    async def _iteration() -> None:
        await drain_one(redis_client, timeout_seconds=block_timeout_seconds)

    logger.info("instagram_inbound_worker_started", queue=INBOUND_QUEUE_KEY)
    await resilient_worker_loop(
        _iteration, stop_event=stop_event, worker_name="instagram_inbound_worker"
    )
    logger.info("instagram_inbound_worker_stopped")


def _run_forever_with_signal_handling() -> None:
    """Punto de entrada del proceso worker independiente (`python -m
    app.workers.instagram_inbound_worker`), usado por el servicio
    `instagram_inbound_worker` de `docker-compose.yml`. Se apaga limpiamente
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
