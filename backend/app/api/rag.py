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
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_db
from app.core.rag_queue import enqueue_ingest_job
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
    DraftOut,
    IngestQueuedOut,
    IngestRequest,
    RagDraftOut,
    RagDraftRequest,
)
from app.core.whatsapp_outbound_queue import enqueue_outbound_send
from app.schemas.ws_chat import WsOutgoingMessage
from app.services.ai_service import AIClient, AIServiceError, get_ai_client
from app.services.rag import draft_review_service
from app.services.rag.draft_service import InsufficientContextError, generate_rag_draft
from app.workers.rag_ingest_worker import notify_new_job

_CANAL_WHATSAPP = "whatsapp"

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
) -> RagDraftOut:
    """Genera un borrador RAG con ≥3 citas trazables para el tenant autenticado.

    No envía nada al contacto (human-in-the-loop es SPEC-019): solo produce
    el borrador para que un agente humano lo revise/edite/apruebe después.
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
