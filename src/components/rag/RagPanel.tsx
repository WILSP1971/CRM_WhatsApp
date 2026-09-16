import { useEffect, useMemo, useState } from "react";
import { Sparkles } from "lucide-react";
import { Badge } from "@/components/ui";
import ragData from "@/mocks/rag.json";
import type { RagCitation, RagDraft, RagSuggestion } from "@/lib/types";
import { RagCitationList } from "@/components/rag/RagCitationList";
import { RagDraftCard } from "@/components/rag/RagDraftCard";
import { RagSuggestionList } from "@/components/rag/RagSuggestionList";

const typedRagData = ragData as {
  citations: RagCitation[];
  drafts: RagDraft[];
  suggestions: RagSuggestion[];
  notaFicticia: string;
};

interface RagPanelProps {
  conversationId: string | null;
  onUseDraft: (text: string) => void;
}

/**
 * Panel lateral RAG en vivo (SPEC-005) — representación visual, sin ninguna
 * llamada a LLM/embeddings/base vectorial real. Todo el contenido proviene
 * de src/mocks/rag.json (datos pre-grabados ficticios).
 */
export function RagPanel({ conversationId, onUseDraft }: RagPanelProps) {
  const [loading, setLoading] = useState(false);

  // Simula "generando…" al cambiar de conversación (representación visual,
  // sin ninguna petición de red — cumple RNF de estado "generando" simulado).
  useEffect(() => {
    if (!conversationId) return;
    setLoading(true);
    const timeout = window.setTimeout(() => setLoading(false), 550);
    return () => window.clearTimeout(timeout);
  }, [conversationId]);

  const citations = useMemo(
    () =>
      typedRagData.citations.filter(
        (c) => c.conversationId === conversationId || c.conversationId === "default",
      ),
    [conversationId],
  );
  const draft = useMemo(
    () =>
      typedRagData.drafts.find((d) => d.conversationId === conversationId) ??
      typedRagData.drafts.find((d) => d.conversationId === "default"),
    [conversationId],
  );
  const suggestions = useMemo(
    () =>
      typedRagData.suggestions.filter(
        (s) => s.conversationId === conversationId || s.conversationId === "default",
      ),
    [conversationId],
  );

  if (!conversationId) {
    return (
      <section
        aria-label="Asistente RAG"
        className="flex h-full flex-col items-center justify-center gap-2 rounded-xl border border-border-subtle bg-bg-card p-6 text-center"
      >
        <Sparkles className="h-6 w-6 text-accent-cyan-strong" aria-hidden />
        <p className="text-sm text-text-secondary">
          Selecciona una conversación para activar el asistente RAG.
        </p>
      </section>
    );
  }

  return (
    <section
      aria-label="Asistente RAG"
      className="flex h-full flex-col gap-4 overflow-y-auto rounded-xl border border-border-subtle bg-bg-card p-4"
    >
      <header className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2.5 w-2.5" aria-hidden>
            <span
              className={
                loading
                  ? "absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-cyan opacity-75 motion-reduce:animate-none"
                  : "hidden"
              }
            />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent-cyan" />
          </span>
          <h2 className="text-sm font-semibold text-text-primary">RAG activo</h2>
        </div>
        <Badge variant="ai">Representación · mock local</Badge>
      </header>

      <p role="status" aria-live="polite" className="sr-only">
        {loading
          ? "Generando sugerencias del asistente RAG…"
          : "Sugerencias del asistente RAG actualizadas."}
      </p>

      <RagCitationList citations={citations} loading={loading} />
      <RagDraftCard draft={draft} loading={loading} onUseDraft={onUseDraft} />
      <RagSuggestionList suggestions={suggestions} loading={loading} />

      <p className="mt-auto border-t border-border-subtle pt-3 text-xs text-text-muted">
        {typedRagData.notaFicticia}
      </p>
    </section>
  );
}
