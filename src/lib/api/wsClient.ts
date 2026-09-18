/**
 * Cliente WebSocket del canal WebChat real (SPEC-015) — SPEC-020.
 *
 * Conecta a `GET/WS /api/v1/ws/chat/{conversationId}?token=<JWT>` (el
 * backend exige el JWT como query param en el handshake: los navegadores no
 * permiten headers custom en WebSocket, ver `backend/app/api/ws_chat.py`).
 *
 * Solo se instancia cuando el feature-flag está ON y hay una conversación
 * seleccionada (`useRealtimeConversation`, en `dataProvider.ts`).
 */

import { WS_BASE_URL } from "@/lib/env";
import { getAuthToken } from "@/lib/authStore";
import type { WsServerEvent } from "@/lib/api/backendTypes";

export interface WebChatSocketHandlers {
  onEvent: (event: WsServerEvent) => void;
  onOpen?: () => void;
  onClose?: (event: CloseEvent) => void;
  onError?: (event: Event) => void;
}

export interface WebChatSocketHandle {
  sendMessage: (remitente: "contacto" | "agente", contenido: string) => void;
  sendReadReceipt: (messageId: string) => void;
  close: () => void;
}

/** Abre el socket del WebChat para una conversación; `token` viene de `authStore`. */
export function connectWebChat(
  conversationId: string,
  handlers: WebChatSocketHandlers,
): WebChatSocketHandle {
  const token = getAuthToken() ?? "";
  const url = `${WS_BASE_URL}/ws/chat/${conversationId}?token=${encodeURIComponent(token)}`;
  const socket = new WebSocket(url);

  socket.onopen = () => handlers.onOpen?.();
  socket.onerror = (event) => handlers.onError?.(event);
  socket.onclose = (event) => handlers.onClose?.(event);
  socket.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data as string) as WsServerEvent;
      handlers.onEvent(parsed);
    } catch {
      handlers.onEvent({ type: "error", detail: "Evento WS malformado" });
    }
  };

  return {
    sendMessage(remitente, contenido) {
      socket.send(JSON.stringify({ type: "message", remitente, contenido }));
    },
    sendReadReceipt(messageId) {
      socket.send(JSON.stringify({ type: "read", message_id: messageId }));
    },
    close() {
      socket.close();
    },
  };
}
