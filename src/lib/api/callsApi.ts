/**
 * Cliente REST de la ficha de llamada real (canal de voz, SPEC-040).
 *
 * Rutas exactas del backend (`backend/app/api/calls.py`, montadas bajo
 * `/api/v1`):
 *   GET /calls
 *   GET /calls/{id}
 *   GET /calls/{id}/audio (binario `audio/wav`, no JSON)
 */

import { apiFetch } from "@/lib/api/httpClient";
import { API_BASE_URL } from "@/lib/env";
import { getAuthToken } from "@/lib/authStore";
import type {
  BackendCall,
  BackendCallDetail,
  BackendPage,
} from "@/lib/api/backendTypes";

export async function fetchCalls(params?: {
  page?: number;
  pageSize?: number;
}): Promise<BackendPage<BackendCall>> {
  return apiFetch<BackendPage<BackendCall>>("/calls", {
    query: { page: params?.page, page_size: params?.pageSize },
  });
}

export async function fetchCallDetail(callId: string): Promise<BackendCallDetail> {
  return apiFetch<BackendCallDetail>(`/calls/${callId}`);
}

/**
 * Descarga el audio DESCIFRADO de la llamada como `Blob` y devuelve una
 * Object URL local (`URL.createObjectURL`) lista para `<audio src=...>`.
 *
 * No se usa `apiFetch` (JSON-only): este endpoint devuelve un binario
 * `audio/*`. El header `Authorization` se añade igual que en `apiFetch`
 * (mismo token de `authStore`) para respetar JWT + RLS por tenant (RNF-47).
 * Devuelve `null` si el audio no está disponible (404: nunca hubo audio, o
 * fue purgado/anonimizado por retención — SPEC-041, aún no implementada);
 * el llamador debe entonces mostrar solo la transcripción, sin reproductor
 * (RF-02 SPEC-040).
 */
export async function fetchCallAudioObjectUrl(callId: string): Promise<string | null> {
  const token = getAuthToken();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${API_BASE_URL}/calls/${callId}/audio`, { headers });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`No se pudo cargar el audio de la llamada (HTTP ${response.status}).`);
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}
