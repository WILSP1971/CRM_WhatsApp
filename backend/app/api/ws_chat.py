"""Endpoint WebSocket del canal WebChat propio — SPEC-015.

`GET/WS /api/v1/ws/chat/{conversation_id}?token=<JWT>`

Handshake autenticado (RESTRICCIÓN DURA, SENSIBLE):
  1. El cliente (widget WebChat o Bandeja del agente) abre el WebSocket
     pasando el JWT de acceso (mismo formato que SPEC-013) como query param
     `token` — los navegadores no permiten fijar headers custom en el
     handshake de WebSocket, por lo que el query param es el mecanismo
     estándar para JWT en WS (alternativa: subprotocolo `Sec-WebSocket-
     Protocol`, no usado aquí para mantener un único mecanismo simple).
  2. El token se valida con el MISMO decodificador que la API REST
     (`app.security.jwt.decode_access_token`); si es inválido/ausente/
     expirado, la conexión se RECHAZA (close code 4401) ANTES del `accept()`
     -> nunca se acepta una conexión sin auth (criterio de aceptación).
  3. Se fija `SET LOCAL app.tenant_id = <tenant_id del token>` en la sesión
     de BD (`app/db/session.py::set_tenant_session`, igual que
     `get_tenant_db`) para que RLS aísle todo acceso a `conversations` y
     `messages` durante la vida del socket.
  4. Se resuelve la conversación por id DENTRO de esa sesión con tenant
     fijado: si la conversación no existe o pertenece a otro tenant, RLS la
     oculta -> 404 lógico -> se cierra el socket (4404), igual que el REST.

Persistencia y fan-out:
  - Cada mensaje entrante (`type: "message"`) se persiste con
    `app.services.message_service.create_message` (MISMA función que usa el
    REST de SPEC-014: no se duplica lógica de persistencia) y se publica en
    el canal Redis `chat:{tenant_id}:{conversation_id}`
    (`app.core.redis_client.channel_name`) para que TODOS los workers/
    conexiones suscritos a esa conversación (fan-out) lo reciban, incluida
    la propia conexión emisora (para confirmar persistencia con `MessageOut`
    completo, incluido `estado_entrega`).
  - Un mensaje se marca "entregado" (persistido + propagado) tan pronto se
    publica con éxito en Redis; queda "leído" cuando el otro extremo envía
    `{"type": "read", "message_id": ...}`. Ambos cambios se persisten
    (`update_delivery_status`) y se difunden como evento `delivery_status`.

Aislamiento por tenant (riesgo R-23): el canal Redis se deriva SIEMPRE del
`tenant_id` del JWT (nunca de un parámetro del cliente), así que un socket
del tenant B jamás se suscribe al canal del tenant A aunque intente abrir el
mismo `conversation_id` (que además RLS le ocultaría con 404 lógico).

Reconexión: al conectar, el cliente puede pedir el backlog persistido vía el
REST existente (`GET /conversations/{id}/messages`, SPEC-014); el WebSocket
en sí es sin estado (RNF-05) y no pierde mensajes ya persistidos.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.db.session import SessionLocal, set_tenant_session
from app.core.redis_client import channel_name, get_redis_client
from app.security.jwt import InvalidTokenError, TokenPayload, decode_access_token
from app.services.message_service import (
    create_message,
    get_conversation_activa,
    get_message_activo,
    schedule_sentiment_analysis,
    update_delivery_status,
)
from app.schemas.message import MessageOut
from app.schemas.ws_chat import (
    WsDeliveryStatus,
    WsErrorEvent,
    WsIncomingMessage,
    WsOutgoingMessage,
    WsReadReceipt,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["WebChat"])

# Close codes propios (rango privado 4000-4999 de RFC 6455).
WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_NOT_FOUND = 4404
WS_CLOSE_INTERNAL_ERROR = 4500


def _authenticate(token: str | None) -> TokenPayload | None:
    """Valida el JWT del query param; `None` si es inválido/ausente."""
    if not token:
        return None
    try:
        return decode_access_token(token)
    except InvalidTokenError:
        return None


@contextlib.contextmanager
def _tenant_session(tenant_id: str):
    """Sesión de BD con `app.tenant_id` fijado (mismo mecanismo que
    `app.api.deps.get_tenant_db`, reutilizado aquí fuera del ciclo de
    Depends porque el WS gestiona su propio ciclo de vida de conexión)."""
    db = SessionLocal()
    try:
        with db.begin():
            set_tenant_session(db, tenant_id)
            yield db
    finally:
        db.close()


@router.websocket("/ws/chat/{conversation_id}")
async def websocket_chat(websocket: WebSocket, conversation_id: uuid.UUID) -> None:
    token = websocket.query_params.get("token")
    payload = _authenticate(token)

    # CRITERIO DE ACEPTACIÓN: nunca aceptar conexiones sin credencial válida.
    if payload is None:
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED, reason="No autenticado")
        return

    tenant_id = payload.tenant_id

    # Resolver la conversación DENTRO del tenant fijado (RLS); si no existe o
    # es de otro tenant, RLS la oculta -> tratamos como 404 lógico.
    with _tenant_session(tenant_id) as db:
        conversation = get_conversation_activa(db, conversation_id)
        if conversation is None:
            await websocket.close(
                code=WS_CLOSE_NOT_FOUND, reason="Conversación no encontrada"
            )
            return

    await websocket.accept()

    redis_client = get_redis_client()
    channel = channel_name(tenant_id, conversation_id)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)

    async def _forward_redis_to_socket() -> None:
        """Tarea de fan-out: reenvía al socket todo lo publicado en el canal
        Redis de esta conversación/tenant (de esta u otras conexiones/workers)."""
        async for item in pubsub.listen():
            if item.get("type") != "message":
                continue
            with contextlib.suppress(RuntimeError):
                await websocket.send_text(item["data"])

    forward_task = asyncio.create_task(_forward_redis_to_socket())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload_dict = json.loads(raw)
            except (TypeError, ValueError):
                await _send_error(websocket, "JSON inválido")
                continue

            event_type = payload_dict.get("type", "message")
            if event_type == "read":
                await _handle_read_receipt(
                    websocket, tenant_id, conversation_id, payload_dict, redis_client
                )
            else:
                await _handle_incoming_message(
                    websocket,
                    tenant_id,
                    conversation_id,
                    payload_dict,
                    redis_client,
                    channel,
                )
    except WebSocketDisconnect:
        logger.info(
            "ws_chat.disconnect",
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
        )
    finally:
        forward_task.cancel()
        with contextlib.suppress(Exception):
            await forward_task
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel)
        with contextlib.suppress(Exception):
            await pubsub.close()


async def _send_error(websocket: WebSocket, detail: str) -> None:
    with contextlib.suppress(RuntimeError):
        await websocket.send_text(WsErrorEvent(detail=detail).model_dump_json())


async def _handle_incoming_message(
    websocket: WebSocket,
    tenant_id: str,
    conversation_id: uuid.UUID,
    payload_dict: dict,
    redis_client,
    channel: str,
) -> None:
    try:
        incoming = WsIncomingMessage.model_validate(payload_dict)
    except ValidationError as exc:
        await _send_error(websocket, f"Mensaje inválido: {exc.errors()[0]['msg']}")
        return

    with _tenant_session(tenant_id) as db:
        conversation = get_conversation_activa(db, conversation_id)
        if conversation is None:
            await _send_error(websocket, "Conversación no encontrada")
            return

        message = create_message(
            db,
            tenant_id=uuid.UUID(str(tenant_id)),
            conversation_id=conversation_id,
            remitente=incoming.remitente,
            contenido=incoming.contenido,
            created_by=None,
        )
        message_out = MessageOut.model_validate(message)

    # Sentimiento (SPEC-018): encolado asíncrono, no bloquea la persistencia
    # ni el fan-out del mensaje (RF: "no bloquea la recepción del mensaje").
    await schedule_sentiment_analysis(redis_client, message=message)

    # Fan-out a todos los suscriptores del canal namespaced por tenant
    # (incluida esta misma conexión, que recibe la confirmación persistida).
    envelope = WsOutgoingMessage(message=message_out)
    await redis_client.publish(channel, envelope.model_dump_json())

    # "entregado": se logró persistir y publicar en el bus de fan-out.
    with _tenant_session(tenant_id) as db:
        stored = get_message_activo(db, conversation_id, message_out.id)
        if stored is not None:
            update_delivery_status(db, stored, "entregado")
            status_event = WsDeliveryStatus(
                message_id=stored.id,
                conversation_id=conversation_id,
                estado_entrega=stored.estado_entrega,
            )
    await redis_client.publish(channel, status_event.model_dump_json())


async def _handle_read_receipt(
    websocket: WebSocket,
    tenant_id: str,
    conversation_id: uuid.UUID,
    payload_dict: dict,
    redis_client,
) -> None:
    try:
        receipt = WsReadReceipt.model_validate(payload_dict)
    except ValidationError as exc:
        await _send_error(
            websocket, f"Evento de lectura inválido: {exc.errors()[0]['msg']}"
        )
        return

    with _tenant_session(tenant_id) as db:
        message = get_message_activo(db, conversation_id, receipt.message_id)
        if message is None:
            await _send_error(websocket, "Mensaje no encontrado")
            return
        update_delivery_status(db, message, "leido")
        status_event = WsDeliveryStatus(
            message_id=message.id,
            conversation_id=conversation_id,
            estado_entrega=message.estado_entrega,
        )

    channel = channel_name(tenant_id, conversation_id)
    await redis_client.publish(channel, status_event.model_dump_json())
