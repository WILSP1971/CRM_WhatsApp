/**
 * Cliente REST del panel RAG real (borrador human-in-the-loop, SPEC-017/019)
 * — SPEC-020. Extendido con la respuesta de audio (TTS de salida,
 * Entregable #6, SPEC-069/070/ADR-014) — SPEC-070.
 *
 * Rutas exactas de `backend/app/api/rag.py` (montadas bajo `/api/v1`):
 *   POST  /rag/conversations/{conversationId}/drafts
 *   POST  /rag/conversations/{conversationId}/drafts/{draftId}/approve
 *   PATCH /rag/conversations/{conversationId}/drafts/{draftId}/respuesta-modo
 *   POST  /rag/conversations/{conversationId}/drafts/{draftId}/listen
 *   GET   /rag/conversations/{conversationId}/drafts/{draftId}/audio (binario, ver `fetchDraftAudioObjectUrl`)
 */

import { apiFetch } from "@/lib/api/httpClient";
import { API_BASE_URL } from "@/lib/env";
import { getAuthToken } from "@/lib/authStore";
import type {
  BackendDraft,
  BackendRespuestaModo,
  BackendTtsEstado,
} from "@/lib/api/backendTypes";

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

/**
 * Opt-in explícito (Q2-A, RF-01 SPEC-070): fija `respuesta_modo` ANTES de
 * aprobar. NO genera ni envía nada — solo el modo que `approveDraft`
 * consultará al aprobar (ADR-014).
 */
export async function setRespuestaModo(
  conversationId: string,
  draftId: string,
  respuestaModo: BackendRespuestaModo,
): Promise<BackendDraft> {
  return apiFetch<BackendDraft>(
    `/rag/conversations/${conversationId}/drafts/${draftId}/respuesta-modo`,
    { method: "PATCH", body: { respuesta_modo: respuestaModo } },
  );
}

/**
 * Ruta OPCIONAL "escuchar antes de enviar" (Q1-C, RF-02 SPEC-070): encola
 * la síntesis del guion vigente BAJO DEMANDA (202), sin enviarlo. El
 * llamador debe seguir consultando `tts_estado` (`GET .../drafts/{id}`)
 * hasta `"listo"`/`"error"`.
 */
export async function requestDraftAudio(
  conversationId: string,
  draftId: string,
): Promise<{ draft_id: string; tts_estado: BackendTtsEstado }> {
  return apiFetch(`/rag/conversations/${conversationId}/drafts/${draftId}/listen`, {
    method: "POST",
  });
}

/** Refresca el borrador vigente (usado para hacer poll de `tts_estado`). */
export async function fetchDraft(
  conversationId: string,
  draftId: string,
): Promise<BackendDraft> {
  return apiFetch<BackendDraft>(`/rag/conversations/${conversationId}/drafts/${draftId}`);
}

/**
 * Descarga el clip TTS YA generado como `Blob` y devuelve una Object URL
 * local (`URL.createObjectURL`) lista para `<audio src=...>` — mismo patrón
 * que `fetchCallAudioObjectUrl` (`callsApi.ts`, SPEC-040): no se usa
 * `apiFetch` (JSON-only) porque este endpoint devuelve un binario
 * `audio/ogg`; el header `Authorization` se añade a mano con el mismo
 * token de `authStore` (JWT + RLS por tenant).
 *
 * Devuelve `null` si el clip no está listo (404: aún generando, error, o
 * nunca se solicitó) — el llamador debe entonces confiar en `tts_estado`
 * para decidir qué mostrar, nunca asumir que `null` es un error de red.
 */
export async function fetchDraftAudioObjectUrl(
  conversationId: string,
  draftId: string,
): Promise<string | null> {
  const token = getAuthToken();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(
    `${API_BASE_URL}/rag/conversations/${conversationId}/drafts/${draftId}/audio`,
    { headers },
  );
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`No se pudo cargar el audio del borrador (HTTP ${response.status}).`);
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}
