import { FileText } from "lucide-react";
import type { RagCitation } from "@/lib/types";

interface RagCitationListProps {
  citations: RagCitation[];
  loading: boolean;
}

function CitationSkeleton() {
  return (
    <li className="animate-pulse rounded-lg border border-border-subtle bg-bg-surface-raised p-3 motion-reduce:animate-none">
      <div className="mb-2 h-3 w-2/3 rounded bg-border-subtle" />
      <div className="h-3 w-full rounded bg-border-subtle" />
    </li>
  );
}

/** Fragmentos de citas de "base vectorial" (mock) con fuente y score de similitud. */
export function RagCitationList({ citations, loading }: RagCitationListProps) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
        Citas de la base de conocimiento
      </h3>
      <ul
        aria-label="Citas de la base de conocimiento (mock vectorial)"
        className="flex flex-col gap-2"
      >
        {loading ? (
          <>
            <CitationSkeleton />
            <CitationSkeleton />
            <CitationSkeleton />
          </>
        ) : citations.length === 0 ? (
          <li className="rounded-lg border border-border-subtle bg-bg-surface-raised p-3 text-sm text-text-muted">
            No hay citas disponibles para esta conversación.
          </li>
        ) : (
          citations.map((citation) => (
            <li
              key={citation.id}
              className="border-accent-indigo/25 bg-accent-indigo/5 rounded-lg border p-3"
            >
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-1.5 truncate text-xs font-medium text-accent-indigo-strong">
                  <FileText className="h-3.5 w-3.5 flex-none" aria-hidden />
                  <span className="truncate">{citation.source}</span>
                </span>
                <span
                  className="flex-none text-xs font-semibold text-accent-cyan-strong"
                  aria-label={`Similitud ${Math.round(citation.similarityScore * 100)} por ciento`}
                >
                  {Math.round(citation.similarityScore * 100)}%
                </span>
              </div>
              <p className="text-sm text-text-secondary">{citation.excerpt}</p>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
