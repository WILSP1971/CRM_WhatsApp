import { Sparkles } from "lucide-react";
import type { VoiceBotIntent } from "@/lib/types";
import { Badge } from "@/components/ui";

interface IntentBadgeProps {
  intent: VoiceBotIntent | undefined;
}

/**
 * Chip de intención detectada por IA (mock, SPEC-006): estética
 * índigo/cian reservada para representaciones de IA en el sistema de
 * diseño. La confianza y la etiqueta provienen de fixtures locales.
 */
export function IntentBadge({ intent }: IntentBadgeProps) {
  if (!intent) {
    return (
      <Badge variant="neutral">
        <Sparkles className="h-3 w-3" aria-hidden />
        Sin intención detectada
      </Badge>
    );
  }

  const confidencePct = Math.round(intent.confidence * 100);

  return (
    <Badge
      variant="ai"
      aria-label={`Intención detectada: ${intent.label}, confianza ${confidencePct}%`}
    >
      <Sparkles className="h-3 w-3" aria-hidden />
      {intent.label}
      <span className="font-semibold">· {confidencePct}%</span>
    </Badge>
  );
}
