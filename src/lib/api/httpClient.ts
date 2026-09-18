/**
 * Cliente HTTP tipado para las APIs reales del backend (SPEC-020).
 *
 * Solo se invoca cuando `VITE_USE_REAL_API=true` (ver `src/lib/env.ts`); con
 * el flag apagado, ningún módulo importa ni ejecuta este archivo en runtime
 * desde la ruta de datos (ver `src/lib/dataProvider.ts`), por lo que el
 * bundle mock no realiza llamadas de red.
 *
 * Maneja:
 *  - Prefijo de `API_BASE_URL` (configurable por env, SOLO localhost/red
 *    interna — restricción SENSIBLE .no-externo).
 *  - Header `Authorization: Bearer <token>` a partir de `authStore`.
 *  - Errores HTTP homogéneos vía `ApiError` (con status y detail del backend).
 */

import { API_BASE_URL } from "@/lib/env";
import { getAuthToken } from "@/lib/authStore";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`API error ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Query params opcionales, serializados como `?a=1&b=2`. */
  query?: Record<string, string | number | boolean | undefined>;
  /** Omite el header Authorization (solo usado por `/auth/login`). */
  skipAuth?: boolean;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(`${API_BASE_URL}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** Ejecuta una petición `fetch` tipada contra la API real; lanza `ApiError` en 4xx/5xx. */
export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, query, skipAuth = false } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!skipAuth) {
    const token = getAuthToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(buildUrl(path, query), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const detail =
      isJson && payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : String(payload);
    throw new ApiError(response.status, detail);
  }

  return payload as T;
}
