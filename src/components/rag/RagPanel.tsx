import { Sparkles } from "lucide-react";
import { Badge } from "@/components/ui";
import { RagCitationList } from "@/components/rag/RagCitationList";
import { RagDraftCard } from "@/components/rag/RagDraftCard";
import { RagSuggestionList } from "@/components/rag/RagSuggestionList";
import { useRagData } from "@/lib/dataProvider/useRagData";
import { USE_REAL_API } from "@/lib/env";

interface RagPanelProps {
  conversationId: string | null;
  onUseDraft: (text: string) => void;
}

/**
 * Panel lateral RAG en vivo (SPEC-005), conectado por feature-flag a la
 * generación real de borradores (SPEC-017/019) vía `useRagData` (SPEC-020).
 * Con `VITE_USE_REAL_API=false` (default) el comportamiento es idéntico al
 * Entregable #1: representación visual sin ninguna llamada a LLM/embeddings/
 * base vectorial real, contenido de `src/mocks/rag.json`.
 */
export function RagPanel({ conversationId, onUseDraft }: RagPanelProps) {
  const { citations, draft, suggestions, loading, error, notaFicticia } =
    useRagData(conversationId);

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
        <Badge variant="ai">
          {USE_REAL_API ? "Conectado · API real" : "Representación · mock local"}
        </Badge>
      </header>

      <p role="status" aria-live="polite" className="sr-only">
        {loading
          ? "Generando sugerencias del asistente RAG…"
          : "Sugerencias del asistente RAG actualizadas."}
      </p>

      {error && (
        <p
          role="alert"
          className="border-state-danger-strong/40 bg-state-danger-strong/10 rounded-lg border p-3 text-sm text-state-danger-strong"
        >
          {error}
        </p>
      )}

      <RagCitationList citations={citations} loading={loading} />
      <RagDraftCard draft={draft} loading={loading} onUseDraft={onUseDraft} />
      <RagSuggestionList suggestions={suggestions} loading={loading} />

      <p className="mt-auto border-t border-border-subtle pt-3 text-xs text-text-muted">
        {notaFicticia}
      </p>
    </section>
  );
}
