"""Router `calls` — ficha de llamada del canal de voz — SPEC-040.

Expone al frontend (módulo VoiceBot, SPEC-006, tras el feature-flag
`VITE_USE_REAL_API`) los datos YA persistidos por el pipeline de voz
(SPEC-036 datos, SPEC-037 ingesta, SPEC-038 transcripción, SPEC-039
enriquecimiento): este router es de SOLO LECTURA (+ streaming de audio) y no
introduce ninguna lógica de negocio nueva sobre `Call`/`CallTranscript`.

Mismo patrón de seguridad que el resto de la API (`app/api/conversations.py`,
`app/api/contacts.py`, SPEC-013/014): JWT (`get_current_user`) + sesión con
`app.tenant_id` ya fijado (`get_tenant_db`) -> RLS (ADR-004) aísla las
llamadas de otros tenants a nivel de motor, además del filtro explícito
`Call.tenant_id`/`activo=True` (defensa en profundidad, C2).

Auditoría (RNF-44 SPEC-040, HABEAS DATA SPEC-021): el audio/transcripción de
una llamada es PHI potencial (ADR-009) — cada lectura de detalle y cada
streaming de audio quedan registrados vía `log_personal_data_access`, igual
que el resto de accesos a datos personales de la API.

CHECKPOINT SENSIBLE (C3): `GET /calls/{id}/audio` NUNCA expone la ruta física
del almacén ni la clave de cifrado — descifra en memoria
(`app.services.telefonia.audio_store.load_audio`) y transmite los bytes ya
en claro como `audio/*`; el cliente solo conoce el `id` (UUID) de la llamada,
nunca `audio_ref`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_db
from app.api.pagination import paginate
from app.core.audit_log import log_personal_data_access
from app.core.request_id import get_request_id
from app.models.call import Call
from app.models.call_transcript import CallTranscript
from app.models.message import Message
from app.models.rag_draft import RagDraft
from app.models.user import User
from app.schemas.call import (
    CallDetailOut,
    CallOut,
    CallRagDraftOut,
    CallSentimentOut,
    CallTranscriptOut,
)
from app.schemas.common import Page
from app.schemas.rag import CitationOut
from app.services.telefonia.audio_store import AudioStoreError, load_audio

router = APIRouter(prefix="/calls", tags=["Calls"])

# Tipo MIME por defecto si no se puede inferir del `audio_ref` (los ficheros
# de audio de telefonía casi siempre son wav/pcm en este dominio, SPEC-035).
_DEFAULT_AUDIO_MEDIA_TYPE = "audio/wav"


def _call_out(call: Call) -> CallOut:
    return CallOut(
        id=call.id,
        tenant_id=call.tenant_id,
        call_id=call.call_id,
        numero=call.numero,
        direccion=call.direccion,
        duracion=call.duracion,
        estado=call.estado,
        contact_id=call.contact_id,
        conversation_id=call.conversation_id,
        resumen=call.resumen,
        audio_disponible=call.audio_ref is not None,
        activo=call.activo,
        created_at=call.created_at,
        updated_at=call.updated_at,
    )


def _get_call_activa_or_404(db: Session, call_id: uuid.UUID) -> Call:
    """Busca una llamada activa dentro del tenant de sesión (RLS ya acota).

    RLS (ADR-004) ya impide que aparezca una fila de otro tenant; el filtro
    explícito por `activo=True` es el borrado lógico (C2). 404 homogéneo:
    no distingue "no existe" de "es de otro tenant"/"está inactiva".
    """
    call = db.scalar(select(Call).where(Call.id == call_id, Call.activo.is_(True)))
    if call is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Llamada no encontrada"
        )
    return call


def _transcript_out(call: Call, db: Session) -> CallTranscriptOut | None:
    transcript = db.scalar(
        select(CallTranscript).where(
            CallTranscript.call_id == call.id, CallTranscript.activo.is_(True)
        )
    )
    if transcript is None:
        return None
    return CallTranscriptOut.model_validate(transcript)


def _sentiment_out(call: Call, db: Session) -> CallSentimentOut:
    """El sentimiento de la llamada vive en el `Message` sintético que la
    materializa (`stt_worker`, SPEC-039, RF reutiliza SPEC-018): se toma el
    último mensaje activo de la conversación enlazada con sentimiento ya
    calculado. `None`/`None` si aún no hay conversación o el análisis
    (best-effort, asíncrono) todavía no corrió.

    Desempate explícito por `id` (preventivo, revisión BLACK PANTHER):
    SPEC-041 (retención) podría añadir más eventos a la misma conversación
    de voz en el futuro, y sin desempate el resultado no sería determinista
    ante un empate exacto de `created_at`."""
    if call.conversation_id is None:
        return CallSentimentOut(sentimiento=None, sentimiento_score=None)

    message = db.scalar(
        select(Message)
        .where(
            Message.conversation_id == call.conversation_id,
            Message.activo.is_(True),
            Message.sentimiento.is_not(None),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
    )
    if message is None:
        return CallSentimentOut(sentimiento=None, sentimiento_score=None)
    return CallSentimentOut(
        sentimiento=message.sentimiento,
        sentimiento_score=(
            float(message.sentimiento_score)
            if message.sentimiento_score is not None
            else None
        ),
    )


def _rag_draft_out(call: Call, db: Session) -> CallRagDraftOut | None:
    """Borrador RAG vigente más reciente de la conversación de la llamada
    (SPEC-019/039) — MISMA entidad `RagDraft` que gestionan los endpoints de
    `app/api/rag.py`; aquí solo se expone en modo lectura para la ficha.

    Desempate explícito por `id` (preventivo, revisión BLACK PANTHER): igual
    razón que en `_sentiment_out` — sin desempate el resultado no sería
    determinista ante un empate exacto de `created_at`."""
    if call.conversation_id is None:
        return None

    draft = db.scalar(
        select(RagDraft)
        .where(
            RagDraft.conversation_id == call.conversation_id,
            RagDraft.activo.is_(True),
        )
        .order_by(RagDraft.created_at.desc(), RagDraft.id.desc())
        .limit(1)
    )
    if draft is None:
        return None

    return CallRagDraftOut(
        id=draft.id,
        conversation_id=draft.conversation_id,
        content=draft.content,
        content_original=draft.content_original,
        model=draft.model,
        citations=[CitationOut(**c) for c in draft.citations],
        estado=draft.estado,
        edited_by=draft.edited_by,
        approved_by=draft.approved_by,
        sent_message_id=draft.sent_message_id,
    )


@router.get("", response_model=Page[CallOut])
def list_calls(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    contact_id: uuid.UUID
    | None = Query(default=None, description="Filtro por contacto"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> Page[CallOut]:
    """Lista llamadas del tenant autenticado (paginado; excluye inactivas)."""
    stmt = select(Call).where(Call.activo.is_(True)).order_by(Call.created_at.desc())
    if contact_id is not None:
        stmt = stmt.where(Call.contact_id == contact_id)
    page_result = paginate(db, stmt, page=page, page_size=page_size, schema=CallOut)

    log_personal_data_access(
        action="list",
        resource="calls",
        resource_id=None,
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
        user_email=current_user.email,
        request_id=get_request_id(request),
        extra={"count": len(page_result.items)},
    )
    return page_result


@router.get("/{call_id}", response_model=CallDetailOut)
def get_call_detail(
    call_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> CallDetailOut:
    """Ficha completa de la llamada: transcripción + sentimiento + resumen +
    borrador citado (RF-01/RF-02 SPEC-040)."""
    call = _get_call_activa_or_404(db, call_id)

    detail = CallDetailOut(
        call=_call_out(call),
        transcript=_transcript_out(call, db),
        sentiment=_sentiment_out(call, db),
        rag_draft=_rag_draft_out(call, db),
    )

    log_personal_data_access(
        action="read",
        resource="calls",
        resource_id=str(call.id),
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
        user_email=current_user.email,
        request_id=get_request_id(request),
    )
    return detail


@router.get(
    "/{call_id}/audio",
    responses={
        404: {"description": "Llamada no encontrada, o sin audio disponible "
              "(nunca hubo audio, o fue purgado/anonimizado por retención, "
              "SPEC-041)"},
    },
)
def stream_call_audio(
    call_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> Response:
    """Sirve el audio DESCIFRADO de la llamada, on-prem, al cliente autenticado
    del mismo tenant (RF-02 SPEC-040, C3, RNF-47).

    NUNCA expone `audio_ref` (ruta interna del almacén) ni la clave de
    cifrado: el cliente solo conoce el `id` (UUID) de la llamada. Si
    `audio_ref` es `None` (nunca hubo audio, o ya fue purgado por la política
    de retención de SPEC-041 —
    `app.services.telefonia.call_retention_service.run_call_retention_job`,
    que limpia `audio_ref` y marca `Call.audio_purged_at` al purgar el blob)
    responde 404 explícito: el frontend debe mostrar solo la transcripción,
    sin reproductor (RF-02).
    """
    call = _get_call_activa_or_404(db, call_id)

    if call.audio_ref is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio no disponible para esta llamada (inexistente o purgado "
            "por política de retención).",
        )

    try:
        audio_bytes = load_audio(audio_ref=call.audio_ref)
    except AudioStoreError as exc:
        # El audio_ref existe en BD pero el fichero cifrado no se pudo leer/
        # descifrar (p.ej. seed de demo sin binario real, o purga física ya
        # ejecutada sin limpiar aún la referencia en BD) — 404 explícito, NUNCA
        # un 500 que sugiera un fallo del servidor ni filtre detalles de
        # infraestructura (C3).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio no disponible para esta llamada.",
        ) from exc

    # `audio_ref` es un identificador opaco cifrado (`.enc`, `build_audio_ref`)
    # sin extensión real de audio: se sirve siempre con el tipo MIME por
    # defecto del dominio de telefonía (RNF: sin inferencia de contenido
    # sobre datos potencialmente PHI, C3).
    log_personal_data_access(
        action="read",
        resource="calls_audio",
        resource_id=str(call.id),
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
        user_email=current_user.email,
        request_id=get_request_id(request),
    )

    return Response(content=audio_bytes, media_type=_DEFAULT_AUDIO_MEDIA_TYPE)
