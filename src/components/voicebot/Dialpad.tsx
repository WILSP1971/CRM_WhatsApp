import { Mic, MicOff, Pause, Phone, PhoneOff, Play } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { cn } from "@/lib/cn";

export type CallLineStatus = "colgado" | "en_llamada" | "en_espera";

interface DialpadProps {
  number: string;
  onNumberChange: (value: string) => void;
  status: CallLineStatus;
  muted: boolean;
  onToggleMute: () => void;
  onCall: () => void;
  onHangup: () => void;
  onToggleHold: () => void;
}

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

const STATUS_LABEL: Record<CallLineStatus, string> = {
  colgado: "Colgado",
  en_llamada: "En llamada",
  en_espera: "En espera",
};

/**
 * Webphone / marcador telefónico (SPEC-006). Representación visual: no
 * establece llamadas VoIP reales ni realiza peticiones de red.
 */
export function Dialpad({
  number,
  onNumberChange,
  status,
  muted,
  onToggleMute,
  onCall,
  onHangup,
  onToggleHold,
}: DialpadProps) {
  const inCall = status !== "colgado";

  const handleKeyPress = (key: string) => {
    onNumberChange(number + key);
  };

  return (
    <section aria-label="Webphone" className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <Input
          aria-label="Número a marcar"
          inputMode="tel"
          placeholder="Ingresa un número"
          value={number}
          onChange={(e) => onNumberChange(e.target.value)}
          className="text-center text-lg tracking-widest"
        />
      </div>

      <div
        role="status"
        aria-live="polite"
        className={cn(
          "flex items-center justify-center gap-2 rounded-md py-1.5 text-xs font-semibold uppercase tracking-wide",
          status === "en_llamada" && "text-state-success",
          status === "en_espera" && "text-state-warning",
          status === "colgado" && "text-text-muted",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "h-2 w-2 rounded-full",
            status === "en_llamada" && "bg-state-success",
            status === "en_espera" && "bg-state-warning",
            status === "colgado" && "bg-text-muted",
          )}
        />
        {STATUS_LABEL[status]}
      </div>

      <div className="grid grid-cols-3 gap-2" role="group" aria-label="Teclado numérico">
        {KEYS.map((key) => (
          <Button
            key={key}
            type="button"
            variant="secondary"
            size="lg"
            className="text-lg font-semibold"
            onClick={() => handleKeyPress(key)}
            aria-label={`Tecla ${key}`}
          >
            {key}
          </Button>
        ))}
      </div>

      <div className="flex items-center justify-center gap-3">
        {!inCall ? (
          <Button
            type="button"
            variant="primary"
            size="lg"
            className="bg-state-success hover:bg-state-success-strong"
            onClick={onCall}
            disabled={number.trim().length === 0}
          >
            <Phone className="h-5 w-5" aria-hidden />
            Llamar
          </Button>
        ) : (
          <>
            <Button
              type="button"
              variant={muted ? "danger" : "secondary"}
              size="icon"
              onClick={onToggleMute}
              aria-pressed={muted}
              aria-label={muted ? "Activar micrófono" : "Silenciar micrófono"}
            >
              {muted ? (
                <MicOff className="h-5 w-5" aria-hidden />
              ) : (
                <Mic className="h-5 w-5" aria-hidden />
              )}
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="icon"
              onClick={onToggleHold}
              aria-pressed={status === "en_espera"}
              aria-label={status === "en_espera" ? "Reanudar llamada" : "Poner en espera"}
            >
              {status === "en_espera" ? (
                <Play className="h-5 w-5" aria-hidden />
              ) : (
                <Pause className="h-5 w-5" aria-hidden />
              )}
            </Button>
            <Button
              type="button"
              variant="danger"
              size="lg"
              onClick={onHangup}
              aria-label="Colgar llamada"
            >
              <PhoneOff className="h-5 w-5" aria-hidden />
              Colgar
            </Button>
          </>
        )}
      </div>
    </section>
  );
}
