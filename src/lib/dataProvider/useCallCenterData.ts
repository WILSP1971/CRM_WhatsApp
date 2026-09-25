/**
 * Hook de datos del Centro de llamadas VoiceBot (SPEC-040): alterna mock/real
 * según `USE_REAL_API` (mismo patrón que `useConversationsData`/`useRagData`,
 * SPEC-020).
 *
 * Con el flag OFF (default): no hace absolutamente nada (ni un `fetch`) —
 * `CallCenterPage` sigue leyendo `src/mocks/calls.json`/`voicebot.json`
 * exactamente como hoy (RF-03 SPEC-040: maqueta intacta).
 *
 * Con el flag ON: carga el listado real de llamadas (`GET /calls`,
 * `backend/app/api/calls.py`) y, para la llamada seleccionada, su ficha
 * completa (`GET /calls/{id}`: transcripción real, sentimiento, resumen,
 * borrador citado) + el audio si está disponible (`GET /calls/{id}/audio`).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { USE_REAL_API } from "@/lib/env";
import { fetchCallAudioObjectUrl, fetchCallDetail, fetchCalls } from "@/lib/api/callsApi";
import { adaptCall, adaptCallDetail } from "@/lib/api/adapters";
import { ensureDevSession } from "@/lib/dataProvider/devSession";
import { ApiError } from "@/lib/api/httpClient";
import type { RealCallDetail, RealCallRecord } from "@/lib/types";

export interface CallCenterDataState {
  /** `true` solo cuando el flag está ON (permite a la UI decidir si muestra
   * la ficha real o la maqueta mock, sin duplicar la lectura de `env.ts`). */
  useRealApi: boolean;
  calls: RealCallRecord[];
  /** `true` mientras se resuelve el listado inicial en modo real. */
  loadingCalls: boolean;
  /** Ficha completa de la llamada seleccionada (`null` mientras carga o sin selección). */
  selectedCallDetail: RealCallDetail | null;
  loadingDetail: boolean;
  /** Object URL local del audio (revocada automáticamente al cambiar de llamada/desmontar). */
  audioUrl: string | null;
  error: string | null;
  selectCall: (callId: string | null) => void;
}

export function useCallCenterData(): CallCenterDataState {
  const [calls, setCalls] = useState<RealCallRecord[]>([]);
  const [loadingCalls, setLoadingCalls] = useState(USE_REAL_API);
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);
  const [selectedCallDetail, setSelectedCallDetail] = useState<RealCallDetail | null>(
    null,
  );
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const audioUrlRef = useRef<string | null>(null);

  // Carga inicial real: login de dev -> listado de llamadas.
  useEffect(() => {
    if (!USE_REAL_API) return;
    let cancelled = false;

    async function load() {
      try {
        setLoadingCalls(true);
        setError(null);
        await ensureDevSession();
        const page = await fetchCalls({ pageSize: 50 });
        if (cancelled) return;
        setCalls(page.items.map(adaptCall));
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Error cargando las llamadas reales.",
          );
        }
      } finally {
        if (!cancelled) setLoadingCalls(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Ficha + audio de la llamada seleccionada.
  useEffect(() => {
    if (!USE_REAL_API || !selectedCallId) return;
    let cancelled = false;

    async function loadDetail() {
      try {
        setLoadingDetail(true);
        setError(null);
        await ensureDevSession();
        const detail = await fetchCallDetail(selectedCallId!);
        if (cancelled) return;
        const adapted = adaptCallDetail(detail);
        setSelectedCallDetail(adapted);

        if (audioUrlRef.current) {
          URL.revokeObjectURL(audioUrlRef.current);
          audioUrlRef.current = null;
          setAudioUrl(null);
        }
        if (adapted.call.audioDisponible) {
          const url = await fetchCallAudioObjectUrl(selectedCallId!);
          if (cancelled) {
            if (url) URL.revokeObjectURL(url);
            return;
          }
          audioUrlRef.current = url;
          setAudioUrl(url);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setError("Llamada no encontrada.");
        } else {
          setError(
            err instanceof Error ? err.message : "Error cargando la ficha de la llamada.",
          );
        }
        setSelectedCallDetail(null);
      } finally {
        if (!cancelled) setLoadingDetail(false);
      }
    }

    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedCallId]);

  // Limpieza de la Object URL del audio al desmontar el hook.
  useEffect(() => {
    return () => {
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    };
  }, []);

  const selectCall = useMemo(
    () => (callId: string | null) => setSelectedCallId(callId),
    [],
  );

  return {
    useRealApi: USE_REAL_API,
    calls,
    loadingCalls,
    selectedCallDetail,
    loadingDetail,
    audioUrl,
    error,
    selectCall,
  };
}
