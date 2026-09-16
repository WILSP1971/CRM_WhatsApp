import { useEffect, useRef } from "react";

interface AudioWaveformProps {
  /** Si la "llamada" está activa: controla si la onda se anima o queda plana. */
  active: boolean;
  /** Cantidad de barras del visualizador. */
  barCount?: number;
  className?: string;
}

/**
 * Visualizador de onda de audio (mock, SPEC-006).
 *
 * No captura micrófono ni reproduce audio real: genera alturas sintéticas
 * mediante una combinación de senoides con fase aleatoria por barra y las
 * anima con requestAnimationFrame (GPU-friendly: solo transform/opacity vía
 * CSS custom properties). Respeta `prefers-reduced-motion` deteniendo la
 * animación y mostrando una onda estática.
 */
export function AudioWaveform({ active, barCount = 32, className }: AudioWaveformProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const phasesRef = useRef<number[]>([]);

  if (phasesRef.current.length !== barCount) {
    phasesRef.current = Array.from(
      { length: barCount },
      (_, i) => (i / barCount) * Math.PI * 2,
    );
  }

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const prefersReducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    const bars = Array.from(container.children) as HTMLElement[];

    if (!active || prefersReducedMotion) {
      // Onda estática de baja amplitud: sin animación, GPU en reposo.
      bars.forEach((bar, i) => {
        const base = 0.18 + 0.12 * Math.abs(Math.sin(phasesRef.current[i]));
        bar.style.transform = `scaleY(${base})`;
      });
      return;
    }

    let start: number | null = null;

    const tick = (timestamp: number) => {
      if (start === null) start = timestamp;
      const elapsed = (timestamp - start) / 1000;

      bars.forEach((bar, i) => {
        const phase = phasesRef.current[i];
        // Combinación de dos senoides con velocidades distintas -> patrón
        // orgánico sintético, sin datos reales de audio.
        const wave =
          Math.sin(elapsed * 3.2 + phase) * 0.5 +
          Math.sin(elapsed * 5.1 + phase * 1.7) * 0.35;
        const scale = 0.22 + Math.abs(wave) * 0.78;
        bar.style.transform = `scaleY(${scale})`;
      });

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [active, barCount]);

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={
        active
          ? "Visualizador de onda de audio: llamada en curso (simulado)"
          : "Visualizador de onda de audio: sin actividad (simulado)"
      }
      className={
        "flex h-16 items-center justify-center gap-[3px] rounded-lg border border-border-subtle bg-bg-surface px-3 " +
        (className ?? "")
      }
    >
      {phasesRef.current.map((_, i) => (
        <span
          key={i}
          aria-hidden
          className={
            "w-[3px] flex-1 rounded-full will-change-transform " +
            (active ? "bg-accent-cyan" : "bg-text-muted/50")
          }
          style={{ height: "100%", transform: "scaleY(0.2)", transformOrigin: "center" }}
        />
      ))}
    </div>
  );
}
