"""Router `rag` — Pipeline RAG local (ingesta, recuperación, borrador) — SPEC-017,
y revisión human-in-the-loop del borrador — SPEC-019.

Endpoints (bajo `/api/v1`, protegidos por JWT + tenant RLS, mismo patrón que
`documents.py`/`messages.py`, SPEC-013/014):

- `POST /rag/documents/{document_id}/ingest`: ENCOLA la ingesta (chunking +
  embeddings + pgvector) de un documento ya registrado (SPEC-014) en Redis
  (`app.core.rag_queue`, persistente vía `appendonly yes`) y responde de
  inmediato (RNF-06: no bloquea con documentos grandes). El procesamiento
  real lo ejecuta el proceso worker independiente (servicio `rag_worker` de
  `docker-compose.yml`, `app/workers/rag_ingest_worker.py`), NO la API: un
  reinicio de la API a mitad de ingesta no pierde el job (R-28).
- `POST /rag/draft`: recupera el top-k de chunks del tenant autenticado
  (pgvector, similitud coseno) y genera un borrador con el LLM local que
  incluye ≥3 citas trazables (`source`/`excerpt`/`similarityScore`). El
  borrador NO se envía automáticamente (SPEC-019 gestiona la aprobación
  humana); este endpoint solo lo produce para revisión (no lo persiste).
- `POST /rag/conversations/{conversation_id}/drafts`: genera Y PERSISTE un
  borrador (estado `propuesto`) asociado a la conversación (SPEC-019).
- `GET /rag/conversations/{conversation_id}/drafts/{draft_id}`: obtiene el
  borrador para revisión.
- `PATCH .../drafts/{draft_id}`: el agente edita el texto final (estado
  `editado`); NO envía nada.
- `POST .../drafts/{draft_id}/approve`: ÚNICA acción que envía el borrador —
  crea el `Message` saliente real y difunde por WebChat (SPEC-015).
- `POST .../drafts/{draft_id}/discard`: descarta el borrador; NO envía nada.

Respuesta de audio (TTS de salida, Entregable #6, SPEC-069/ADR-014):
- `PATCH .../drafts/{draft_id}/respuesta-modo`: opt-in (Q2-A) de `"texto"`
  (default)/`"audio"` ANTES de aprobar; NO genera ni envía nada.
- `POST .../drafts/{draft_id}/listen`: ruta OPCIONAL "escuchar antes de
  enviar" (Q1-C) — encola la síntesis del guion vigente BAJO DEMANDA, SIN
  enviar; el agente decide después si aprueba (envía el clip) o descarta.
- `GET .../drafts/{draft_id}/audio`: sirve el clip TTS YA generado (404 si no
  hay uno `listo`) para que el agente lo reproduzca antes de aprobar/
  descartar — contrato que consume la SPA (SPEC-070).
- `POST .../drafts/{draft_id}/approve` (extendido): si `respuesta_modo ==
  "audio"` y el canal es WhatsApp, ADEMÁS de enviar el texto de siempre,
  dispara la respuesta de voz — reutiliza el clip ya escuchado si existe, o
  encola la síntesis en background (`tts:jobs`, `app/workers/tts_worker.py`)
  que el propio worker envía tras terminar. **Ningún audio se envía sin
  aprobación humana** (del guion o del clip escuchado, ADR-014) — invariante
  verificado: el encolado de `tts:jobs` en modo "enviar" es INALCANZABLE sin
  que `approve_and_send` ya haya tenido éxito en esta misma request.

CHECKPOINT SENSIBLE (.no-externo): los endpoints de generación usan
EXCLUSIVAMENTE `AIClient` (SPEC-016, Ollama interno) vía `get_ai_client`.
Modo degradado (R-21): si el servicio de IA local no está disponible, se
devuelve `503 Service Unavailable` explícito (nunca un borrador/ingesta
fabricados).

RESTRICCIÓN DURA (SPEC-019, SENSIBLE): ningún endpoint de este router crea un
`Message` saliente salvo `approve_draft_endpoint`, que requiere una acción
humana explícita del agente autenticado (nunca se dispara automáticamente al
generar/editar un borrador).

RESTRICCIÓN DURA (SPEC-029, SENSIBLE, ADR-006): cuando `conversation.canal ==
"whatsapp"`, `approve_draft_endpoint` además ENCOLA el envío por Graph API
(`app.core.whatsapp_outbound_queue`, consumido por el worker
`wa_send_worker`) DESPUÉS de que `create_message` ya persistió el mensaje —
nunca antes ni de forma condicionada a otra cosa que la aprobación humana ya
ejecutada. El envío real (host de la Graph API de Meta, allowlist ADR-006,
ventana 24h/plantilla) vive fuera de este router, en
`app/integrations/whatsapp/graph_client.py` +
`app/workers/wa_send_worker.py` (separación transporte/orquestación).
"""

from __future__ import annotations

import uuid

import redis.asyncio as redis_asyncio
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_db
from app.core.rag_queue import enqueue_ingest_job
from app.core.rate_limit_general import rag_draft_rate_limiter
from app.core.redis_client import channel_name, get_redis_client
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.rag_draft import RagDraft
from app.models.user import User
from app.schemas.message import MessageOut
from app.schemas.rag import (
    CitationOut,
    DraftApproveOut,
    DraftCreateRequest,
    DraftEditRequest,
    DraftListenRequestedOut,
    DraftOut,
    DraftRespuestaModoRequest,
    IngestQueuedOut,
    IngestRequest,
    RagDraftOut,
    RagDraftRequest,
)
from app.core.tts_queue import (
    TTS_JOB_MODO_ENVIAR,
    TTS_JOB_MODO_ESCUCHAR,
    enqueue_tts_job,
)
from app.core.whatsapp_outbound_queue import enqueue_outbound_send
from app.schemas.ws_chat import WsOutgoingMessage
from app.services.ai_service import AIClient, AIServiceError, get_ai_client
from app.services.rag import draft_review_service
from app.services.rag.draft_service import InsufficientContextError, generate_rag_draft
from app.services.telefonia import audio_store
from app.workers.rag_ingest_worker import notify_new_job

_CANAL_WHATSAPP = "whatsapp"
_RESPUESTA_MODO_AUDIO = "audio"
_TTS_ESTADO_LISTO = "listo"
_AUDIO_MIME_TYPE = "audio/ogg; codecs=opus"

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/rag", tags=["RAG"])


def _get_document_activo_or_404(db: Session, document_id: uuid.UUID) -> Document:
    document = db.scalar(
        select(Document).where(Document.id == document_id, Document.activo.is_(True))
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado"
        )
    return document


def _get_conversation_activa_or_404(
    db: Session, conversation_id: uuid.UUID
) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.activo.is_(True)
        )
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversación no encontrada"
        )
    return conversation


def _get_draft_activo_or_404(
    db: Session, conversation_id: uuid.UUID, draft_id: uuid.UUID
) -> RagDraft:
    draft = draft_review_service.get_draft_activo(db, conversation_id, draft_id)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Borrador no encontrado"
        )
    return draft


def _draft_out(draft: RagDraft) -> DraftOut:
    return DraftOut(
        id=draft.id,
        tenant_id=draft.tenant_id,
        conversation_id=draft.conversation_id,
        query=draft.query,
        content=draft.content,
        content_original=draft.content_original,
        model=draft.model,
        citations=[CitationOut(**c) for c in draft.citations],
        estado=draft.estado,
        edited_by=draft.edited_by,
        approved_by=draft.approved_by,
        sent_message_id=draft.sent_message_id,
        respuesta_modo=draft.respuesta_modo,
        tts_estado=draft.tts_estado,
        audio_listo=draft.tts_estado == _TTS_ESTADO_LISTO,
        activo=draft.activo,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


@router.post(
    "/documents/{document_id}/ingest",
    response_model=IngestQueuedOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={404: {"description": "Documento no encontrado"}},
)
async def ingest_document_endpoint(
    document_id: uuid.UUID,
    payload: IngestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    redis_client: redis_asyncio.Redis = Depends(get_redis_client),
) -> IngestQueuedOut:
    """Encola la ingesta de un documento del tenant autenticado (RNF-06/R-28).

    Valida que el documento exista y esté activo DENTRO del tenant (RLS)
    antes de encolar, para no crear trabajo huérfano ni filtrar por timing si
    el documento pertenece a otro tenant (404 homogéneo, igual que el resto
    de la API). El job (con el texto y los parámetros de chunking) se
    persiste en Redis (`enqueue_ingest_job`, namespaced por tenant, R-23) y
    se notifica al worker (`notify_new_job`); el procesamiento real corre en
    el proceso `rag_worker` (`app/workers/rag_ingest_worker.py`), no aquí.
    """
    document = _get_document_activo_or_404(db, document_id)

    job = await enqueue_ingest_job(
        redis_client,
        tenant_id=current_user.tenant_id,
        document_id=document.id,
        text=payload.text,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
    )
    await notify_new_job(redis_client, job.tenant_id)

    return IngestQueuedOut(document_id=document.id, estado=document.estado)


@router.post(
    "/draft",
    response_model=RagDraftOut,
    responses={
        404: {"description": "Sin contexto suficiente para citas trazables"},
        503: {"description": "Servicio de IA local no disponible (modo degradado)"},
    },
)
def generate_draft_endpoint(
    payload: RagDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    ai_client: AIClient = Depends(get_ai_client),
    _rate_limit: None = Depends(rag_draft_rate_limiter),
) -> RagDraftOut:
    """Genera un borrador RAG con ≥3 citas trazables para el tenant autenticado.

    No envía nada al contacto (human-in-the-loop es SPEC-019): solo produce
    el borrador para que un agente humano lo revise/edite/apruebe después.

    CHECKPOINT (SPEC-081, RF-01): rate-limit GENERAL por IP
    (`rag_draft_rate_limiter`, más bajo que el default de la API porque
    invoca el LLM local en el camino síncrono — ver
    `app/core/rate_limit_general.py` para el razonamiento completo). Se
    aplica vía `Depends()` (dependencia de FastAPI), NO vía el decorador
    `@limiter.limit(...)` de `slowapi`: ese decorador rompe la resolución de
    forward refs de `RagDraftRequest` en este módulo (usa
    `from __future__ import annotations`) — ver docstring de
    `rate_limit_general.py` para el detalle verificado del incidente.
    """
    try:
        result = generate_rag_draft(
            db, ai_client, query=payload.query, top_k=payload.top_k
        )
    except InsufficientContextError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except AIServiceError as exc:
        # Modo degradado (R-21): no se genera un borrador a medias ni se
        # fabrican citas — se informa explícitamente que el LLM local no
        # respondió, para que el agente humano use un flujo manual.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return RagDraftOut(
        content=result.content,
        model=result.model,
        citations=[
            CitationOut(
                source=c.source,
                excerpt=c.excerpt,
                similarityScore=c.similarity_score,
                chunk_id=uuid.UUID(c.chunk_id),
                document_id=uuid.UUID(c.document_id),
            )
            for c in result.citations
        ],
    )


# ---------------------------------------------------------------------------
# Borrador human-in-the-loop persistido — SPEC-019
# ---------------------------------------------------------------------------


@router.post(
    "/conversations/{conversation_id}/drafts",
    response_model=DraftOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Conversación no encontrada o sin contexto suficiente"},
        503: {"description": "Servicio de IA local no disponible (modo degradado)"},
    },
)
def create_draft_endpoint(
    conversation_id: uuid.UUID,
    payload: DraftCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    ai_client: AIClient = Depends(get_ai_client),
) -> DraftOut:
    """Genera Y PERSISTE (estado `propuesto`) el borrador RAG para que el
    agente lo revise/edite/apruebe (SPEC-019, RF-07).

    NO crea ni envía ningún mensaje al contacto: solo dispara la generación
    de SPEC-017 (`generate_rag_draft`) y guarda el resultado con sus citas.
    """
    _get_conversation_activa_or_404(db, conversation_id)
    try:
        result = generate_rag_draft(
            db, ai_client, query=payload.query, top_k=payload.top_k
        )
    except InsufficientContextError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except AIServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    draft = draft_review_service.create_draft(
        db,
        tenant_id=current_user.tenant_id,
        conversation_id=conversation_id,
        query=payload.query,
        result=result,
        created_by=current_user.email,
    )
    return _draft_out(draft)


@router.get(
    "/conversations/{conversation_id}/drafts/{draft_id}",
    response_model=DraftOut,
    responses={404: {"description": "Conversación o borrador no encontrados"}},
)
def get_draft_endpoint(
    conversation_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> DraftOut:
    """Obtiene el borrador vigente de una conversación del tenant autenticado."""
    _get_conversation_activa_or_404(db, conversation_id)
    draft = _get_draft_activo_or_404(db, conversation_id, draft_id)
    return _draft_out(draft)


@router.patch(
    "/conversations/{conversation_id}/drafts/{draft_id}",
    response_model=DraftOut,
    responses={
        404: {"description": "Conversación o borrador no encontrados"},
        409: {"description": "El borrador ya no admite edición (estado terminal)"},
    },
)
def edit_draft_endpoint(
    conversation_id: uuid.UUID,
    draft_id: uuid.UUID,
    payload: DraftEditRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> DraftOut:
    """El agente edita el texto final del borrador (estado -> `editado`).

    NO envía nada: el texto editado solo se convierte en mensaje si luego se
    llama explícitamente al endpoint de aprobación.
    """
    _get_conversation_activa_or_404(db, conversation_id)
    draft = _get_draft_activo_or_404(db, conversation_id, draft_id)
    try:
        draft = draft_review_service.edit_draft(
            db, draft, content=payload.content, edited_by=current_user.email
        )
    except draft_review_service.DraftNotMutableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _draft_out(draft)


# ---------------------------------------------------------------------------
# Respuesta de audio (TTS de salida, Entregable #6, SPEC-069/ADR-014)
# ---------------------------------------------------------------------------


@router.patch(
    "/conversations/{conversation_id}/drafts/{draft_id}/respuesta-modo",
    response_model=DraftOut,
    responses={
        404: {"description": "Conversación o borrador no encontrados"},
        409: {"description": "El borrador ya no admite este cambio (estado terminal)"},
    },
)
def set_respuesta_modo_endpoint(
    conversation_id: uuid.UUID,
    draft_id: uuid.UUID,
    payload: DraftRespuestaModoRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> DraftOut:
    """Opt-in explícito (Q2-A, ADR-014): el agente elige `"texto"` (default)
    o `"audio"` ANTES de aprobar. NO genera ni envía nada — solo fija el modo
    que `approve_draft_endpoint` consultará al aprobar (RF-03 SPEC-069)."""
    _get_conversation_activa_or_404(db, conversation_id)
    draft = _get_draft_activo_or_404(db, conversation_id, draft_id)
    try:
        draft = draft_review_service.set_respuesta_modo(
            db, draft, respuesta_modo=payload.respuesta_modo
        )
    except draft_review_service.DraftNotMutableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _draft_out(draft)


@router.post(
    "/conversations/{conversation_id}/drafts/{draft_id}/listen",
    response_model=DraftListenRequestedOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"description": "Conversación o borrador no encontrados"},
    },
)
async def request_draft_audio_endpoint(
    conversation_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    redis_client: redis_asyncio.Redis = Depends(get_redis_client),
) -> DraftListenRequestedOut:
    """Ruta OPCIONAL "escuchar antes de enviar" (Q1-C, ADR-014, RF-04
    SPEC-069): genera el clip TTS del guion vigente BAJO DEMANDA, SIN
    enviarlo — el agente lo reproduce (SPA, SPEC-070, vía
    `GET .../drafts/{id}/audio`) y decide después si lo aprueba
    (`POST .../drafts/{id}/approve`, que reutiliza el clip ya generado sin
    resintetizar) o lo descarta.

    NO requiere que el borrador esté en un estado terminal ni cambia su
    `estado`/`respuesta_modo` — es ortogonal a la máquina de estados del
    guion (puede pedirse escuchar sobre un borrador `propuesto`/`editado`).
    El guion que se sintetiza es el `content` VIGENTE en este instante
    (snapshot congelado al encolar, ver `TtsSynthesisJob`); si el agente edita
    el texto DESPUÉS de pedir escuchar, debe pedir escuchar de nuevo.
    """
    _get_conversation_activa_or_404(db, conversation_id)
    draft = _get_draft_activo_or_404(db, conversation_id, draft_id)

    await enqueue_tts_job(
        redis_client,
        draft_id=draft.id,
        tenant_id=current_user.tenant_id,
        conversation_id=conversation_id,
        texto=draft.content,
        modo=TTS_JOB_MODO_ESCUCHAR,
    )

    return DraftListenRequestedOut(draft_id=draft.id, tts_estado="generando")


@router.get(
    "/conversations/{conversation_id}/drafts/{draft_id}/audio",
    responses={
        404: {"description": "Conversación/borrador no encontrados o sin clip listo"},
    },
)
def get_draft_audio_endpoint(
    conversation_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> Response:
    """Sirve el clip TTS YA generado (RF-04, ruta "escuchar antes de
    enviar") para que el agente lo reproduzca antes de aprobar/descartar —
    contrato que consume la SPA (SPEC-070, fuera de este alcance).

    404 si el borrador no tiene un clip `tts_estado == "listo"` (aún
    generando, falló, o nunca se solicitó) — nunca se sirve un binario a
    medias. El binario se lee bajo RLS (el borrador ya se resolvió dentro
    del tenant autenticado) del almacén cifrado transitorio
    (`audio_store.py`, SPEC-035) y se descifra SOLO en memoria de proceso
    para esta respuesta, nunca se reescribe a disco sin cifrar.
    """
    _get_conversation_activa_or_404(db, conversation_id)
    draft = _get_draft_activo_or_404(db, conversation_id, draft_id)
    if draft.tts_estado != _TTS_ESTADO_LISTO or not draft.audio_salida_ref:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El borrador no tiene un clip de audio listo para reproducir",
        )
    try:
        audio_bytes = audio_store.load_audio(audio_ref=draft.audio_salida_ref)
    except audio_store.AudioStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El clip de audio ya no está disponible (posible purga tras envío)",
        ) from exc
    return Response(content=audio_bytes, media_type=_AUDIO_MIME_TYPE)


@router.post(
    "/conversations/{conversation_id}/drafts/{draft_id}/approve",
    response_model=DraftApproveOut,
    responses={
        404: {"description": "Conversación o borrador no encontrados"},
        409: {"description": "El borrador ya no admite aprobación (estado terminal)"},
    },
)
async def approve_draft_endpoint(
    conversation_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    redis_client: redis_asyncio.Redis = Depends(get_redis_client),
) -> DraftApproveOut:
    """ÚNICA acción que envía el borrador: crea el `Message` saliente real.

    RESTRICCIÓN DURA (SPEC-019): requiere la acción humana explícita de este
    endpoint (JWT del agente autenticado); ningún otro endpoint de este
    router crea un mensaje saliente. El texto enviado es `draft.content`
    (editado si el agente lo cambió). Tras persistir, se difunde por el
    mismo canal Redis pub/sub del WebChat (SPEC-015) para que la Bandeja/el
    widget lo reciban en tiempo real, igual que cualquier otro mensaje.

    Concurrencia (revisión BLACK PANTHER, BLOQUEANTE): `approve_and_send`
    hace el UPDATE de estado + `create_message` de forma atómica; si dos
    requests concurrentes aprueban el MISMO borrador, solo una gana (la otra
    recibe 409 aquí, sin haber creado un segundo `Message`).

    Manejo de publish (MENOR, revisión BLACK PANTHER): el mensaje YA quedó
    persistido en `db` en este punto (commit del `get_tenant_db`, al salir
    del endpoint). Si el `publish` a Redis falla, el envío NO se revierte
    (el criterio de aceptación es que el mensaje se persista; el fan-out en
    vivo es best-effort, igual que `schedule_sentiment_analysis` de
    SPEC-018) — se loguea la falla para poder reconciliar, y el cliente
    puede recuperar el mensaje vía `GET /conversations/{id}/messages`
    (backlog persistido, mismo mecanismo de reconexión de SPEC-015).
    """
    conversation = _get_conversation_activa_or_404(db, conversation_id)
    draft = _get_draft_activo_or_404(db, conversation_id, draft_id)
    try:
        draft, message = draft_review_service.approve_and_send(
            db, draft, approved_by=current_user.email
        )
    except draft_review_service.DraftNotMutableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    # SPEC-029/RF-02 (SENSIBLE, ADR-006): SOLO tras la aprobación humana de
    # arriba (`approve_and_send` ya persistió `message`) y SOLO si el canal
    # de la conversación es WhatsApp, se encola el transporte real por Graph
    # API. Ningún otro path del backend encola este job (allowlist de
    # llamadores: únicamente este endpoint). Best-effort de encolado (igual
    # criterio que el `publish` de WebChat de abajo): si Redis falla aquí, el
    # mensaje YA quedó persistido — se loguea para reconciliar manualmente en
    # vez de revertir la aprobación ya confirmada.
    if conversation.canal == _CANAL_WHATSAPP:
        try:
            await enqueue_outbound_send(
                redis_client,
                tenant_id=current_user.tenant_id,
                conversation_id=conversation_id,
                message_id=message.id,
            )
        except Exception:  # noqa: BLE001 — best-effort, no revierte la aprobación
            logger.error(
                "rag_draft_approve_whatsapp_enqueue_failed",
                draft_id=str(draft.id),
                message_id=str(message.id),
                conversation_id=str(conversation_id),
                tenant_id=str(current_user.tenant_id),
                exc_info=True,
            )

        # SPEC-069/RF-03 (SENSIBLE, ADR-014): SOLO tras la aprobación humana
        # del GUION (arriba, `approve_and_send` ya persistió `message`) y
        # SOLO si el agente eligió opt-in de audio (`respuesta_modo ==
        # "audio"`, Q2-A), se dispara la respuesta de voz. Ningún otro path
        # del backend encola `tts:jobs` en modo "enviar" (allowlist: SOLO
        # este bloque, tras una aprobación ya confirmada) — el invariante
        # "ningún audio se envía sin aprobación humana" se cumple porque
        # este código es INALCANZABLE sin que `approve_and_send` de arriba
        # ya haya tenido éxito.
        if draft.respuesta_modo == _RESPUESTA_MODO_AUDIO:
            try:
                if draft.tts_estado == _TTS_ESTADO_LISTO and draft.audio_salida_ref:
                    # Ruta "escuchar antes de enviar" (Q1-C): el agente YA
                    # generó y escuchó el clip ANTES de aprobar (RF-04) — se
                    # reutiliza el clip existente, se envía DIRECTO por
                    # `wa:outbound` sin volver a pasar por `tts:jobs`
                    # (idempotencia: nunca se sintetiza dos veces el mismo
                    # guion aprobado).
                    await enqueue_outbound_send(
                        redis_client,
                        tenant_id=current_user.tenant_id,
                        conversation_id=conversation_id,
                        message_id=message.id,
                        tipo="audio",
                        audio_ref=draft.audio_salida_ref,
                        audio_mime_type=_AUDIO_MIME_TYPE,
                    )
                else:
                    # Ruta por defecto (RF-03): nadie escuchó el clip antes
                    # de aprobar — se encola la síntesis; el propio
                    # `tts_worker`, tras sintetizar con éxito, encola el
                    # envío por `wa:outbound` (ver
                    # `app/workers/tts_worker.py::_dispatch_send_best_effort`).
                    await enqueue_tts_job(
                        redis_client,
                        draft_id=draft.id,
                        tenant_id=current_user.tenant_id,
                        conversation_id=conversation_id,
                        texto=draft.content,
                        modo=TTS_JOB_MODO_ENVIAR,
                    )
            except Exception:  # noqa: BLE001 — best-effort, no revierte la aprobación
                logger.error(
                    "rag_draft_approve_audio_enqueue_failed",
                    draft_id=str(draft.id),
                    message_id=str(message.id),
                    conversation_id=str(conversation_id),
                    tenant_id=str(current_user.tenant_id),
                    exc_info=True,
                )

    message_out = MessageOut.model_validate(message)
    envelope = WsOutgoingMessage(message=message_out)
    channel = channel_name(current_user.tenant_id, conversation_id)
    try:
        await redis_client.publish(channel, envelope.model_dump_json())
    except Exception:  # noqa: BLE001 — best-effort: el envío ya está persistido
        logger.warning(
            "rag_draft_approve_publish_failed",
            draft_id=str(draft.id),
            message_id=str(message.id),
            conversation_id=str(conversation_id),
            tenant_id=str(current_user.tenant_id),
            exc_info=True,
        )

    return DraftApproveOut(draft=_draft_out(draft), sent_message_id=message.id)


@router.post(
    "/conversations/{conversation_id}/drafts/{draft_id}/discard",
    response_model=DraftOut,
    responses={
        404: {"description": "Conversación o borrador no encontrados"},
        409: {"description": "El borrador ya no admite descarte (estado terminal)"},
    },
)
def discard_draft_endpoint(
    conversation_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> DraftOut:
    """El agente descarta el borrador: NUNCA se envía ni se persiste mensaje."""
    _get_conversation_activa_or_404(db, conversation_id)
    draft = _get_draft_activo_or_404(db, conversation_id, draft_id)
    try:
        draft = draft_review_service.discard_draft(db, draft)
    except draft_review_service.DraftNotMutableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _draft_out(draft)
