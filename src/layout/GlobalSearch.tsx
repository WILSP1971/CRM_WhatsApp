import { useId, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui";
import { searchMock } from "@/lib/search";

/** Búsqueda semántica global simulada (SPEC-003 RF-08). */
export function GlobalSearch() {
  const [query, setQuery] = useState("");
  const listboxId = useId();
  const results = useMemo(() => searchMock(query), [query]);
  const showResults = query.trim().length > 0;

  return (
    <div className="relative w-full max-w-xl">
      <label htmlFor="global-search" className="sr-only">
        Buscar cliente, ticket o consultar al RAG empresarial
      </label>
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
          aria-hidden
        />
        <Input
          id="global-search"
          role="combobox"
          aria-expanded={showResults}
          aria-controls={listboxId}
          aria-autocomplete="list"
          autoComplete="off"
          placeholder="Buscar cliente, ticket o consultar al RAG empresarial..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="pl-9"
        />
      </div>

      {showResults && (
        <div
          id={listboxId}
          role="listbox"
          aria-label="Resultados de búsqueda"
          className="glass-surface absolute left-0 top-full z-overlay mt-2 max-h-96 w-full overflow-y-auto rounded-lg p-2 shadow-lg"
        >
          {results.length === 0 ? (
            <p className="p-2 text-sm text-text-secondary">
              Sin resultados para “{query}”.
            </p>
          ) : (
            results.map((group) => (
              <div key={group.category} className="mb-2 last:mb-0">
                <p className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
                  {group.category}
                </p>
                <ul>
                  {group.items.map((item) => (
                    <li key={item.id} role="option" aria-selected={false}>
                      <button
                        type="button"
                        className="flex w-full flex-col items-start rounded-md px-2 py-1.5 text-left text-sm text-text-secondary hover:bg-bg-surface-raised hover:text-text-primary focus-visible:shadow-focus focus-visible:outline-none"
                      >
                        <span className="font-medium text-text-primary">
                          {item.title}
                        </span>
                        <span className="truncate text-xs text-text-muted">
                          {item.subtitle}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
