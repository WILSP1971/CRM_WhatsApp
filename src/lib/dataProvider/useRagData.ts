/**
 * Hook de datos del panel RAG dentro de la Bandeja (SPEC-020): alterna
 * mock/real según `USE_REAL_API`.
 *
 * Con el flag OFF (default): mismo comportamiento que hoy en `RagPanel`
 * (fixtures de `src/mocks/rag.json`, sin red). `RagSuggestion` permanece
 * SIEMPRE en modo mock (nota 7 de `adapters.ts`: sin contraparte backend,
 * fuera de alcance de SPEC-017/019 — reemplazo módulo a módulo, no
 * big-bang).
 *
 * Con el flag ON: genera un borrador real con citas trazables
 * (`POST /rag/conversations/{id}/drafts`, SPEC-017/019) para la
 * conversación seleccionada. `onUseDraft` sigue siendo un cambio local del
 * composer.
 *
 * Extendido (SPEC-069/070, ADR-014, Entregable #6): expone las acciones
 * "responder con audio" (opt-in, RF-01), "escuchar antes de enviar" (RF-02,
 * con poll de `tts_estado` hasta `listo`/`error`) y "aprobar" (envía el
 * guion — y, en modo audio, dispara/reenvía el TTS — vía
 * `approve_draft_endpoint`, SIN cambiar su lógica). Con el flag OFF ninguna
 * de estas acciones existe ni ejecuta fetch (RNF-FLAG): `RagDraftCard`
 * jamás las invoca en modo mock.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import ragData from "@/mocks/rag.json";
import type { RagCitation, RagDraft, RagSuggestion } from "@/lib/types";
import { USE_REAL_API } from "@/lib/env";
import {
  approveDraft as approveDraftRequest,
  createDraft,
  fetchDraft,
  fetchDraftAudioObjectUrl,
  requestDraftAudio,
  setRespuestaModo as setRespuestaModoRequest,
} from "@/lib/api/ragApi";
import { adaptCitations, adaptDraft } from "@/lib/api/adapters";
import { ensureDevSession } from "@/lib/dataProvider/devSession";
import { ApiError } from "@/lib/api/httpClient";
import type { BackendRespuestaModo } from "@/lib/api/backendTypes";

const mockRagData = ragData as {
  citations: RagCitation[];
  drafts: RagDraft[];
  suggestions: RagSuggestion[];
  notaFicticia: string;
};

/** Intervalo de poll de `tts_estado` mientras está "generando" (RF-02). */
const TTS_POLL_INTERVAL_MS = 1500;
/** Techo defensivo de poll (ADR-014 Q4: ≤5-10s de síntesis en background;
 * se deja margen amplio para no cortar antes de que el worker responda). */
const TTS_POLL_TIMEOUT_MS = 30_000;

export interface RagDataState {
  citations: RagCitation[];
  draft: RagDraft | undefined;
  suggestions: RagSuggestion[];
  /** `true` mientras se genera el borrador real; en modo mock refleja el "generando…" simulado. */
  loading: boolean;
  /** Mensaje de error de la generación real (p.ej. IA local en modo degradado, 503). */
  error: string | null;
  notaFicticia: string;
  /** `true` solo cuando el flag está ON — permite a la UI decidir si muestra los controles de audio. */
  useRealApi: boolean;
  /** `true` mientras se aprueba/envía el borrador vigente. */
  approving: boolean;
  /** `true` mientras se resuelve `PATCH .../respuesta-modo`. */
  settingRespuestaModo: boolean;
  /** `true` mientras se pide/hace poll de la síntesis ("escuchar antes de enviar"). */
  requestingAudio: boolean;
  /** Object URL local del clip listo para `<audio src=...>` (revocada al cambiar/desmontar). */
  audioUrl: string | null;
  /** Mensaje de error de la ruta de audio (opt-in/escuchar/aprobar), separado de `error` (generación del guion). */
  audioError: string | null;
  /** Cambia `respuesta_modo` ("texto" default / "audio", RF-01 opt-in). No-op en modo mock. */
  setRespuestaModo: (mode: BackendRespuestaModo) => Promise<void>;
  /** Dispara "escuchar antes de enviar" (RF-02): encola la síntesis y hace poll hasta `listo`/`error`. No-op en modo mock. */
  requestListen: () => Promise<void>;
  /** Aprueba y envía el borrador vigente (guion; si `respuesta_modo==="audio"`, además dispara/reenvía el TTS). No-op en modo mock. */
  approve: () => Promise<void>;
}

const DEFAULT_DRAFT_QUERY =
  "Redacta una respuesta breve y útil para el último mensaje del contacto.";

export function useRagData(conversationId: string | null): RagDataState {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [realCitations, setRealCitations] = useState<RagCitation[]>([]);
  const [realDraft, setRealDraft] = useState<RagDraft | undefined>(undefined);
  const [approving, setApproving] = useState(false);
  const [settingRespuestaModo, setSettingRespuestaModo] = useState(false);
  const [requestingAudio, setRequestingAudio] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioError, setAudioError] = useState<string | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const revokeAudioUrl = useCallback(() => {
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    setAudioUrl(null);
  }, []);

  const clearPoll = useCallback(() => {
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
  }, []);

  // Modo mock: simula "generando…" igual que el `RagPanel` original (sin red).
  useEffect(() => {
    if (USE_REAL_API || !conversationId) return;
    setLoading(true);
    const timeout = window.setTimeout(() => setLoading(false), 550);
    return () => window.clearTimeout(timeout);
  }, [conversationId]);

  // Modo real: genera+persiste un borrador RAG con citas trazables.
  useEffect(() => {
    if (!USE_REAL_API || !conversationId) return;
    let cancelled = false;
    clearPoll();
    revokeAudioUrl();
    setAudioError(null);

    async function loadDraft() {
      try {
        setLoading(true);
        setError(null);
        await ensureDevSession();
        const draft = await createDraft(conversationId!, { query: DEFAULT_DRAFT_QUERY });
        if (cancelled) return;
        setRealCitations(adaptCitations(conversationId!, draft.citations));
        setRealDraft(adaptDraft(draft));
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 503) {
          setError("Servicio de IA local no disponible (modo degradado).");
        } else if (err instanceof ApiError && err.status === 404) {
          setError("Sin contexto suficiente para generar citas trazables.");
        } else {
          setError(
            err instanceof Error ? err.message : "Error generando el borrador RAG.",
          );
        }
        setRealCitations([]);
        setRealDraft(undefined);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadDraft();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- clearPoll/revokeAudioUrl son estables (useCallback sin deps)
  }, [conversationId]);

  // Limpieza al desmontar: cancela cualquier poll pendiente y revoca la Object URL del audio.
  useEffect(() => {
    return () => {
      clearPoll();
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setRespuestaModo = useCallback(
    async (mode: BackendRespuestaModo) => {
      if (!USE_REAL_API || !conversationId || !realDraft) return;
      try {
        setSettingRespuestaModo(true);
        setAudioError(null);
        await ensureDevSession();
        const updated = await setRespuestaModoRequest(conversationId, realDraft.id, mode);
        setRealDraft(adaptDraft(updated));
        if (mode === "texto") {
          clearPoll();
          revokeAudioUrl();
        }
      } catch (err) {
        setAudioError(
          err instanceof Error ? err.message : "Error cambiando el modo de respuesta.",
        );
      } finally {
        setSettingRespuestaModo(false);
      }
    },
    [conversationId, realDraft, clearPoll, revokeAudioUrl],
  );

  const requestListen = useCallback(async () => {
    if (!USE_REAL_API || !conversationId || !realDraft) return;
    const draftId = realDraft.id;
    clearPoll();
    revokeAudioUrl();
    setAudioError(null);
    setRequestingAudio(true);

    try {
      await ensureDevSession();
      await requestDraftAudio(conversationId, draftId);
      setRealDraft((prev) =>
        prev && prev.id === draftId ? { ...prev, ttsEstado: "generando" } : prev,
      );

      const deadline = Date.now() + TTS_POLL_TIMEOUT_MS;

      const poll = async () => {
        try {
          const latest = await fetchDraft(conversationId, draftId);
          const adapted = adaptDraft(latest);
          setRealDraft((prev) => (prev && prev.id === draftId ? adapted : prev));

          if (adapted.ttsEstado === "listo") {
            const url = await fetchDraftAudioObjectUrl(conversationId, draftId);
            audioUrlRef.current = url;
            setAudioUrl(url);
            setRequestingAudio(false);
            return;
          }
          if (adapted.ttsEstado === "error") {
            setAudioError(
              "No se pudo generar el clip de audio. Puedes reintentar o responder con texto.",
            );
            setRequestingAudio(false);
            return;
          }
          if (Date.now() >= deadline) {
            setAudioError(
              "La generación del audio está tardando más de lo esperado. Puedes reintentar o responder con texto.",
            );
            setRequestingAudio(false);
            return;
          }
          pollTimeoutRef.current = setTimeout(poll, TTS_POLL_INTERVAL_MS);
        } catch (err) {
          setAudioError(
            err instanceof Error ? err.message : "Error consultando el estado del audio.",
          );
          setRequestingAudio(false);
        }
      };

      pollTimeoutRef.current = setTimeout(poll, TTS_POLL_INTERVAL_MS);
    } catch (err) {
      setAudioError(
        err instanceof Error ? err.message : "Error solicitando la generación del audio.",
      );
      setRequestingAudio(false);
    }
  }, [conversationId, realDraft, clearPoll, revokeAudioUrl]);

  const approve = useCallback(async () => {
    if (!USE_REAL_API || !conversationId || !realDraft) return;
    try {
      setApproving(true);
      setAudioError(null);
      await ensureDevSession();
      const result = await approveDraftRequest(conversationId, realDraft.id);
      setRealDraft(adaptDraft(result.draft));
    } catch (err) {
      setAudioError(
        err instanceof Error ? err.message : "Error aprobando y enviando el borrador.",
      );
    } finally {
      setApproving(false);
    }
  }, [conversationId, realDraft]);

  if (!USE_REAL_API) {
    const citations = mockRagData.citations.filter(
      (c) => c.conversationId === conversationId || c.conversationId === "default",
    );
    const draft =
      mockRagData.drafts.find((d) => d.conversationId === conversationId) ??
      mockRagData.drafts.find((d) => d.conversationId === "default");
    const suggestions = mockRagData.suggestions.filter(
      (s) => s.conversationId === conversationId || s.conversationId === "default",
    );
    return {
      citations,
      draft,
      suggestions,
      loading,
      error: null,
      notaFicticia: mockRagData.notaFicticia,
      useRealApi: false,
      approving: false,
      settingRespuestaModo: false,
      requestingAudio: false,
      audioUrl: null,
      audioError: null,
      setRespuestaModo: async () => undefined,
      requestListen: async () => undefined,
      approve: async () => undefined,
    };
  }

  // Sugerencias de venta cruzada: SIEMPRE mock (sin contraparte backend, nota 7).
  const suggestions = mockRagData.suggestions.filter(
    (s) => s.conversationId === conversationId || s.conversationId === "default",
  );

  return {
    citations: realCitations,
    draft: realDraft,
    suggestions,
    loading,
    error,
    notaFicticia: mockRagData.notaFicticia,
    useRealApi: true,
    approving,
    settingRespuestaModo,
    requestingAudio,
    audioUrl,
    audioError,
    setRespuestaModo,
    requestListen,
    approve,
  };
}
