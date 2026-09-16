import { useMemo, useState } from "react";
import { Mic } from "lucide-react";
import callsData from "@/mocks/calls.json";
import type { CallRecord } from "@/lib/types";
import { Badge } from "@/components/ui";
import { Tooltip } from "@/components/ui";

const calls = callsData as CallRecord[];

/** Widget de estado del VoiceBot (mock): resume llamadas activas/en espera. */
export function VoiceBotStatusWidget() {
  const [open, setOpen] = useState(false);

  const activeCalls = useMemo(
    () => calls.filter((c) => c.status === "en_llamada" || c.status === "en_espera"),
    [],
  );

  const isActive = activeCalls.length > 0;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label="Estado del VoiceBot"
        className="flex items-center gap-2 rounded-full border border-border-default bg-bg-surface-raised px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors duration-fast ease-standard hover:text-text-primary focus-visible:shadow-focus focus-visible:outline-none"
      >
        <Tooltip label={isActive ? "VoiceBot: llamadas en curso" : "VoiceBot: en espera"}>
          <span className="relative flex h-2.5 w-2.5" aria-hidden>
            {isActive && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-state-success opacity-75 motion-reduce:animate-none" />
            )}
            <span
              className={
                "relative inline-flex h-2.5 w-2.5 rounded-full " +
                (isActive ? "bg-state-success" : "bg-text-muted")
              }
            />
          </span>
        </Tooltip>
        <Mic className="h-4 w-4" aria-hidden />
        <span className="hidden sm:inline">VoiceBot</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Detalle de estado del VoiceBot"
          className="glass-surface absolute right-0 top-full z-overlay mt-2 w-72 rounded-lg p-3 shadow-lg"
        >
          <p className="mb-2 text-sm font-semibold text-text-primary">
            Estado del VoiceBot
          </p>
          {activeCalls.length === 0 ? (
            <p className="text-sm text-text-secondary">Sin llamadas activas.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {activeCalls.map((call) => (
                <li key={call.id} className="flex items-center justify-between text-sm">
                  <span className="text-text-secondary">
                    Intención: {call.detectedIntent}
                  </span>
                  <Badge variant={call.status === "en_llamada" ? "success" : "warning"}>
                    {call.status === "en_llamada" ? "En llamada" : "En espera"}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
