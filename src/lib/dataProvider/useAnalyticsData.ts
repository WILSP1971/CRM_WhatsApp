/**
 * Hook de datos de `AnalyticsPage` (SPEC-064): alterna mock/real según
 * `USE_REAL_API` (mismo patrón que `useConversationsData`/`useCallCenterData`,
 * SPEC-020).
 *
 * Con el flag OFF (default): no hace absolutamente nada (ni un `fetch`) —
 * `AnalyticsPage` sigue leyendo `src/mocks/kpis.json`/`analytics.json`/
 * `sales.json` exactamente como hoy (RF-04 SPEC-064: maqueta intacta).
 *
 * Con el flag ON: resuelve un rango de fechas (presets hoy/7d/30d + custom,
 * Q4) y consulta `GET /analytics/business` (SPEC-063) cada vez que el rango
 * cambia (on-demand, sin caché ni WebSocket).
 */

import { useEffect, useMemo, useState } from "react";
import { USE_REAL_API } from "@/lib/env";
import { fetchBusinessAnalytics } from "@/lib/api/analyticsApi";
import { ensureDevSession } from "@/lib/dataProvider/devSession";
import { ApiError } from "@/lib/api/httpClient";
import type { BackendBusinessAnalytics } from "@/lib/api/backendTypes";
import type { Channel } from "@/lib/types";

export type AnalyticsRangePreset = "hoy" | "7d" | "30d" | "custom";

export interface AnalyticsDateRange {
  preset: AnalyticsRangePreset;
  /** ISO YYYY-MM-DD, inclusive. */
  desde: string;
  /** ISO YYYY-MM-DD, inclusive. */
  hasta: string;
}

/** `null` = sin filtro de canal ("Todos los canales"). */
export type AnalyticsChannelFilter = Channel | null;

function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Calcula `[desde, hasta]` (inclusive, ISO) para un preset, en hora local. */
export function rangeForPreset(
  preset: Exclude<AnalyticsRangePreset, "custom">,
  now: Date = new Date(),
): { desde: string; hasta: string } {
  const hasta = toIsoDate(now);
  if (preset === "hoy") {
    return { desde: hasta, hasta };
  }
  const days = preset === "7d" ? 6 : 29; // rango inclusive de 7/30 días
  const desdeDate = new Date(now);
  desdeDate.setDate(desdeDate.getDate() - days);
  return { desde: toIsoDate(desdeDate), hasta };
}

export const DEFAULT_ANALYTICS_RANGE: AnalyticsDateRange = {
  preset: "7d",
  ...rangeForPreset("7d"),
};

export interface AnalyticsDataState {
  /** `true` solo cuando el flag está ON. */
  useRealApi: boolean;
  range: AnalyticsDateRange;
  setRange: (range: AnalyticsDateRange) => void;
  /** Filtro de canal activo; `null` = "Todos los canales". */
  canal: AnalyticsChannelFilter;
  setCanal: (canal: AnalyticsChannelFilter) => void;
  data: BackendBusinessAnalytics | null;
  loading: boolean;
  error: string | null;
  /** Reintenta la última consulta (mismo rango/canal). */
  retry: () => void;
}

export function useAnalyticsData(): AnalyticsDataState {
  const [range, setRange] = useState<AnalyticsDateRange>(DEFAULT_ANALYTICS_RANGE);
  const [canal, setCanal] = useState<AnalyticsChannelFilter>(null);
  const [data, setData] = useState<BackendBusinessAnalytics | null>(null);
  const [loading, setLoading] = useState(USE_REAL_API);
  const [error, setError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    if (!USE_REAL_API) return;
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);
        await ensureDevSession();
        const result = await fetchBusinessAnalytics({
          desde: range.desde,
          hasta: range.hasta,
          canal: canal ?? undefined,
        });
        if (cancelled) return;
        setData(result);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          setError("Sesión no autorizada: vuelve a iniciar sesión para ver la analítica.");
        } else if (err instanceof ApiError && err.status === 422) {
          setError(err.detail || "Rango de fechas inválido.");
        } else {
          setError(
            err instanceof Error
              ? err.message
              : "Error cargando la analítica de negocio.",
          );
        }
        setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [range, canal, retryToken]);

  const retry = useMemo(() => () => setRetryToken((t) => t + 1), []);

  return {
    useRealApi: USE_REAL_API,
    range,
    setRange,
    canal,
    setCanal,
    data,
    loading,
    error,
    retry,
  };
}
