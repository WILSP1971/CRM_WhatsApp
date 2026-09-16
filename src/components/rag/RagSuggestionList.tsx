import { ShoppingBag } from "lucide-react";
import { formatCurrency } from "@/lib/format";
import type { RagSuggestion } from "@/lib/types";

interface RagSuggestionListProps {
  suggestions: RagSuggestion[];
  loading: boolean;
}

function SuggestionSkeleton() {
  return (
    <li className="animate-pulse rounded-lg border border-border-subtle bg-bg-surface-raised p-3 motion-reduce:animate-none">
      <div className="mb-2 h-3 w-1/2 rounded bg-border-subtle" />
      <div className="h-3 w-full rounded bg-border-subtle" />
    </li>
  );
}

/** Sugerencias de producto/servicio (mock) relacionadas con la conversación activa. */
export function RagSuggestionList({ suggestions, loading }: RagSuggestionListProps) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
        Sugerencias de producto/servicio
      </h3>
      <ul aria-label="Sugerencias de producto o servicio" className="flex flex-col gap-2">
        {loading ? (
          <>
            <SuggestionSkeleton />
            <SuggestionSkeleton />
          </>
        ) : suggestions.length === 0 ? (
          <li className="rounded-lg border border-border-subtle bg-bg-surface-raised p-3 text-sm text-text-muted">
            No hay sugerencias disponibles para esta conversación.
          </li>
        ) : (
          suggestions.map((suggestion) => (
            <li
              key={suggestion.id}
              className="rounded-lg border border-border-subtle bg-bg-surface-raised p-3"
            >
              <div className="flex items-start gap-2">
                <ShoppingBag
                  className="mt-0.5 h-4 w-4 flex-none text-accent-indigo-strong"
                  aria-hidden
                />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary">
                    {suggestion.name}
                  </p>
                  <p className="text-sm text-text-secondary">{suggestion.description}</p>
                  <p className="mt-1 text-xs font-semibold text-accent-cyan-strong">
                    {suggestion.price > 0
                      ? formatCurrency(suggestion.price)
                      : "Sin costo adicional"}
                  </p>
                </div>
              </div>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
