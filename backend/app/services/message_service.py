"""Servicio de persistencia de mensajes — compartido por REST (SPEC-014) y
por el canal WebSocket (SPEC-015).

Centraliza la única forma de crear/actualizar un `Message` para que ambos
canales (API REST `app/api/messages.py` y WebSocket `app/api/ws_chat.py`)
apliquen exactamente las mismas reglas (tenant, borrado lógico C2, estado de
entrega inicial) sin duplicar la lógica de persistencia.

`schedule_sentiment_analysis` (SPEC-018) encola la clasificación de
sentimiento de un mensaje ENTRANTE (`remitente == "contacto"`) de forma
asíncrona (cola Redis, `app.core.sentiment_queue`) para no bloquear la
recepción/persistencia del mensaje (RF de SPEC-018): el mensaje ya está
persistido en este punto, así que encolar es un best-effort — si Redis no
está disponible, se loguea y se continúa sin romper el flujo de mensajería
(mismo espíritu de modo degradado que `AIClient`/`sentiment_service`).
"""

from __future__ import annotations

import uuid

import redis.asyncio as redis_asyncio
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.sentiment_queue import enqueue_sentiment_job
from app.models.conversation import Conversation
from app.models.message import ESTADO_ENTREGA_FAILED, ESTADOS_ENTREGA_VALIDOS, Message

logger = structlog.get_logger(__name__)

# Solo los mensajes ENTRANTES (del contacto) se clasifican por sentimiento
# (SPEC-018, "Análisis de sentimiento del mensaje entrante"): los mensajes de
# "agente"/"ia" quedan fuera de alcance.
_REMITENTE_ENTRANTE = "contacto"


def get_conversation_activa(
    db: Session, conversation_id: uuid.UUID
) -> Conversation | None:
    """Busca una conversación activa dentro del tenant de sesión (RLS)."""
    return db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.activo.is_(True)
        )
    )


def create_message(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    remitente: str,
    contenido: str,
    created_by: str | None = None,
) -> Message:
    """Persiste un mensaje nuevo con estado de entrega inicial "enviado".

    Reutilizada por `app/api/messages.py::create_message` (REST, SPEC-014) y
    por `app/api/ws_chat.py` (WebSocket, SPEC-015) para que la persistencia
    sea idéntica en ambos canales.
    """
    message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        remitente=remitente,
        contenido=contenido,
        estado_entrega="enviado",
        created_by=created_by,
    )
    db.add(message)
    db.flush()
    db.refresh(message)
    return message


def is_message_elegible_para_sentimiento(message: Message) -> bool:
    """Un mensaje es candidato a clasificación de sentimiento si es entrante
    (del contacto) — SPEC-018, fuera de alcance para "agente"/"ia"."""
    return message.remitente == _REMITENTE_ENTRANTE


async def schedule_sentiment_analysis(
    redis_client: redis_asyncio.Redis, *, message: Message
) -> None:
    """Encola la clasificación de sentimiento de `message` (SPEC-018, RF:
    "no bloquea la recepción del mensaje").

    Best-effort: si Redis no está disponible, se loguea la falla y se
    continúa SIN propagar la excepción — el mensaje ya quedó persistido por
    el flujo principal y una cola caída no debe romper la recepción.
    """
    if not is_message_elegible_para_sentimiento(message):
        return
    try:
        await enqueue_sentiment_job(
            redis_client, tenant_id=message.tenant_id, message_id=message.id
        )
    except Exception:  # noqa: BLE001 — best-effort, nunca bloquea mensajería
        logger.warning(
            "sentiment_analysis_enqueue_failed",
            message_id=str(message.id),
            tenant_id=str(message.tenant_id),
            exc_info=True,
        )


def get_message_activo(
    db: Session, conversation_id: uuid.UUID, message_id: uuid.UUID
) -> Message | None:
    return db.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
            Message.activo.is_(True),
        )
    )


def update_delivery_status(
    db: Session, message: Message, estado_entrega: str
) -> Message:
    """Actualiza el estado de entrega (enviado/entregado/leído).

    No permite retroceder el estado (p.ej. de "leido" a "entregado") ni
    valores fuera de `ESTADOS_ENTREGA_VALIDOS`.

    Hardening (SPEC-032, deuda SPEC-030/BLACK PANTHER): `failed` es TERMINAL
    (`ESTADO_ENTREGA_FAILED`) y esta función es un no-op si el mensaje YA
    está en ese estado — la terminalidad NO depende únicamente de que el
    caller (`whatsapp_inbound_worker::_process_status_event`) filtre antes de
    invocar; queda garantizada aquí también, en el único punto de escritura
    de la progresión monotónica, para que ningún caller futuro pueda
    "revivir" un mensaje ya marcado `failed`.
    """
    if estado_entrega not in ESTADOS_ENTREGA_VALIDOS:
        raise ValueError(f"estado_entrega inválido: {estado_entrega}")

    if message.estado_entrega == ESTADO_ENTREGA_FAILED:
        return message

    orden = {"enviado": 0, "entregado": 1, "leido": 2}
    if orden[estado_entrega] > orden.get(message.estado_entrega, 0):
        message.estado_entrega = estado_entrega
        db.flush()
        db.refresh(message)
    return message
