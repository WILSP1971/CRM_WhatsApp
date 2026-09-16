import { Wand2 } from "lucide-react";
import { Button } from "@/components/ui";
import type { RagDraft } from "@/lib/types";

interface RagDraftCardProps {
  draft: RagDraft | undefined;
  loading: boolean;
  onUseDraft: (text: string) => void;
}

/** Borrador de respuesta autogenerado (mock) con acción "Insertar borrador". */
export function RagDraftCard({ draft, loading, onUseDraft }: RagDraftCardProps) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
        Borrador sugerido
      </h3>
      {loading ? (
        <div className="animate-pulse rounded-lg border border-border-subtle bg-bg-surface-raised p-3 motion-reduce:animate-none">
          <div className="mb-2 h-3 w-full rounded bg-border-subtle" />
          <div className="h-3 w-4/5 rounded bg-border-subtle" />
        </div>
      ) : draft ? (
        <div className="border-accent-cyan/30 bg-accent-cyan/5 rounded-lg border p-3">
          <p className="text-sm text-text-secondary">{draft.text}</p>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="mt-3"
            onClick={() => onUseDraft(draft.text)}
          >
            <Wand2 className="h-3.5 w-3.5" aria-hidden />
            Usar borrador
          </Button>
        </div>
      ) : (
        <p className="rounded-lg border border-border-subtle bg-bg-surface-raised p-3 text-sm text-text-muted">
          No hay un borrador disponible para esta conversación.
        </p>
      )}
    </div>
  );
}
