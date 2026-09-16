import { useEffect, useRef, useState } from "react";
import { Circle, Pause, Play, Square } from "lucide-react";
import { Button } from "@/components/ui";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";

interface RecordingControlsProps {
  /** Habilita la grabación (representación); requiere llamada en curso. */
  enabled: boolean;
}

/**
 * Controles/indicador de grabación de llamada (SPEC-006). Representación
 * visual: no accede al micrófono ni persiste audio real.
 */
export function RecordingControls({ enabled }: RecordingControlsProps) {
  const [recording, setRecording] = useState(false);
  const [paused, setPaused] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!enabled) {
      setRecording(false);
      setPaused(false);
      setElapsed(0);
    }
  }, [enabled]);

  useEffect(() => {
    if (recording && !paused) {
      intervalRef.current = setInterval(() => setElapsed((prev) => prev + 1), 1000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [recording, paused]);

  const start = () => {
    setRecording(true);
    setPaused(false);
    setElapsed(0);
  };

  const stop = () => {
    setRecording(false);
    setPaused(false);
    setElapsed(0);
  };

  return (
    <section
      aria-label="Grabación de llamada (simulada)"
      className="flex items-center justify-between gap-3 rounded-lg border border-border-subtle bg-bg-surface p-3"
    >
      <div className="flex items-center gap-2">
        <Circle
          aria-hidden
          className={cn(
            "h-3 w-3",
            recording && !paused
              ? "animate-pulse fill-state-danger text-state-danger motion-reduce:animate-none"
              : "fill-text-muted text-text-muted",
          )}
        />
        <span
          role="status"
          aria-live="polite"
          className="text-sm font-medium text-text-secondary"
        >
          {recording ? (paused ? "Grabación en pausa" : "Grabando") : "Sin grabar"}{" "}
          <span className="font-mono text-text-primary">{formatDuration(elapsed)}</span>
        </span>
      </div>

      <div className="flex items-center gap-2">
        {!recording ? (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={start}
            disabled={!enabled}
          >
            <Circle
              className="h-3.5 w-3.5 fill-state-danger text-state-danger"
              aria-hidden
            />
            Iniciar
          </Button>
        ) : (
          <>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setPaused((prev) => !prev)}
              aria-pressed={paused}
            >
              {paused ? (
                <Play className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <Pause className="h-3.5 w-3.5" aria-hidden />
              )}
              {paused ? "Reanudar" : "Pausar"}
            </Button>
            <Button type="button" variant="danger" size="sm" onClick={stop}>
              <Square className="h-3.5 w-3.5" aria-hidden />
              Detener
            </Button>
          </>
        )}
      </div>
    </section>
  );
}
