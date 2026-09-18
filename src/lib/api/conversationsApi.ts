/**
 * Cliente REST de conversaciones/mensajes reales (SPEC-014) — SPEC-020.
 *
 * Rutas exactas del backend (`backend/app/api/conversations.py` y
 * `messages.py`, montadas bajo `/api/v1`):
 *   GET  /conversations
 *   GET  /conversations/{id}/messages
 *   POST /conversations/{id}/messages
 */

import { apiFetch } from "@/lib/api/httpClient";
import type {
  BackendConversation,
  BackendMessage,
  BackendPage,
} from "@/lib/api/backendTypes";

export async function fetchConversations(params?: {
  page?: number;
  pageSize?: number;
}): Promise<BackendPage<BackendConversation>> {
  return apiFetch<BackendPage<BackendConversation>>("/conversations", {
    query: { page: params?.page, page_size: params?.pageSize },
  });
}

export async function fetchMessages(
  conversationId: string,
  params?: { page?: number; pageSize?: number },
): Promise<BackendPage<BackendMessage>> {
  return apiFetch<BackendPage<BackendMessage>>(
    `/conversations/${conversationId}/messages`,
    { query: { page: params?.page, page_size: params?.pageSize } },
  );
}

export async function sendMessage(
  conversationId: string,
  payload: { remitente: "contacto" | "agente" | "ia"; contenido: string },
): Promise<BackendMessage> {
  return apiFetch<BackendMessage>(`/conversations/${conversationId}/messages`, {
    method: "POST",
    body: payload,
  });
}
