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
 * composer (SPEC-020 no está en alcance de aprobar/enviar el borrador desde
 * la Bandeja del Entregable #1: eso es `approve_draft_endpoint`, fuera de
 * este slice de UI, "Nuevas pantallas/UX no existentes" está en OUT).
 */

import { useEffect, useState } from "react";
import ragData from "@/mocks/rag.json";
import type { RagCitation, RagDraft, RagSuggestion } from "@/lib/types";
import { USE_REAL_API } from "@/lib/env";
import { createDraft } from "@/lib/api/ragApi";
import { adaptCitations, adaptDraft } from "@/lib/api/adapters";
import { ensureDevSession } from "@/lib/dataProvider/devSession";
import { ApiError } from "@/lib/api/httpClient";

const mockRagData = ragData as {
  citations: RagCitation[];
  drafts: RagDraft[];
  suggestions: RagSuggestion[];
  notaFicticia: string;
};

export interface RagDataState {
  citations: RagCitation[];
  draft: RagDraft | undefined;
  suggestions: RagSuggestion[];
  /** `true` mientras se genera el borrador real; en modo mock refleja el "generando…" simulado. */
  loading: boolean;
  /** Mensaje de error de la generación real (p.ej. IA local en modo degradado, 503). */
  error: string | null;
  notaFicticia: string;
}

const DEFAULT_DRAFT_QUERY =
  "Redacta una respuesta breve y útil para el último mensaje del contacto.";

export function useRagData(conversationId: string | null): RagDataState {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [realCitations, setRealCitations] = useState<RagCitation[]>([]);
  const [realDraft, setRealDraft] = useState<RagDraft | undefined>(undefined);

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
  }, [conversationId]);

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
  };
}
