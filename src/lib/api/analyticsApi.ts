/**
 * Cliente REST de analítica de negocio real (SPEC-063) — SPEC-064.
 *
 * Ruta exacta del backend (`backend/app/api/analytics.py`, montada bajo
 * `/api/v1`):
 *   GET /analytics/business?desde=YYYY-MM-DD&hasta=YYYY-MM-DD[&canal=...]
 *
 * Solo se invoca cuando `VITE_USE_REAL_API=true` (ver `src/lib/env.ts`),
 * mismo patrón que `conversationsApi.ts`/`callsApi.ts` (SPEC-020).
 */

import { apiFetch } from "@/lib/api/httpClient";
import type { BackendBusinessAnalytics } from "@/lib/api/backendTypes";

export interface FetchBusinessAnalyticsParams {
  /** Fecha inicial del rango (inclusive), formato ISO YYYY-MM-DD. */
  desde: string;
  /** Fecha final del rango (inclusive), formato ISO YYYY-MM-DD. */
  hasta: string;
  /** Filtro opcional de canal (`CANALES_VALIDOS` del backend). */
  canal?: string;
}

export async function fetchBusinessAnalytics(
  params: FetchBusinessAnalyticsParams,
): Promise<BackendBusinessAnalytics> {
  return apiFetch<BackendBusinessAnalytics>("/analytics/business", {
    query: {
      desde: params.desde,
      hasta: params.hasta,
      canal: params.canal,
    },
  });
}
