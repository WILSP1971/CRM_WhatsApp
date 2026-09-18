/**
 * Cliente REST del panel RAG real (borrador human-in-the-loop, SPEC-017/019)
 * — SPEC-020.
 *
 * Rutas exactas de `backend/app/api/rag.py` (montadas bajo `/api/v1`):
 *   POST /rag/conversations/{conversationId}/drafts
 *   POST /rag/conversations/{conversationId}/drafts/{draftId}/approve
 */

import { apiFetch } from "@/lib/api/httpClient";
import type { BackendDraft } from "@/lib/api/backendTypes";

export async function createDraft(
  conversationId: string,
  payload: { query: string; topK?: number },
): Promise<BackendDraft> {
  return apiFetch<BackendDraft>(`/rag/conversations/${conversationId}/drafts`, {
    method: "POST",
    body: { query: payload.query, top_k: payload.topK },
  });
}

export async function approveDraft(
  conversationId: string,
  draftId: string,
): Promise<{ draft: BackendDraft; sent_message_id: string }> {
  return apiFetch(`/rag/conversations/${conversationId}/drafts/${draftId}/approve`, {
    method: "POST",
  });
}
