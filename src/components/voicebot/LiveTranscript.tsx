import { useEffect, useRef, useState } from "react";
import { Bot, Headset, User } from "lucide-react";
import type { TranscriptLine, TranscriptSpeaker } from "@/lib/types";
import { cn } from "@/lib/cn";

interface LiveTranscriptProps {
  lines: TranscriptLine[];
  /** Controla si la transcripción avanza (p.ej. solo cuando hay "llamada" activa). */
  playing: boolean;
}

const SPEAKER_META: Record<
  TranscriptSpeaker,
  { label: string; icon: typeof User; className: string }
> = {
  agente: { label: "Agente", icon: Headset, className: "text-accent-indigo-strong" },
  cliente: { label: "Cliente", icon: User, className: "text-text-secondary" },
  voicebot: { label: "VoiceBot", icon: Bot, className: "text-accent-cyan-strong" },
};

/**
 * Transcripción voz-a-texto en vivo (mock, SPEC-006). El texto proviene de
 * fixtures locales ficticias y se revela incrementalmente para simular STT
 * en tiempo real; no hay reconocimiento de voz real ni llamadas de red.
 */
export function LiveTranscript({ lines, playing }: LiveTranscriptProps) {
  const [visibleCount, setVisibleCount] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setVisibleCount(0);
  }, [lines]);

  useEffect(() => {
    if (!playing || visibleCount >= lines.length) return;
    const timer = setTimeout(
      () => setVisibleCount((prev) => prev + 1),
      900 + Math.random() * 700,
    );
    return () => clearTimeout(timer);
  }, [playing, visibleCount, lines.length]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [visibleCount]);

  const visibleLines = lines.slice(0, visibleCount);

  return (
    <div
      ref={scrollRef}
      role="log"
      aria-live="polite"
      aria-relevant="additions"
      aria-label="Transcripción en vivo de la llamada (simulada)"
      className="flex h-56 flex-col gap-2 overflow-y-auto rounded-lg border border-border-subtle bg-bg-surface p-3"
    >
      {visibleLines.length === 0 && (
        <p className="text-sm text-text-muted">
          La transcripción aparecerá aquí cuando la llamada esté en curso.
        </p>
      )}
      {visibleLines.map((line, index) => {
        const meta = SPEAKER_META[line.speaker];
        const Icon = meta.icon;
        return (
          <div key={`${line.speaker}-${index}`} className="flex items-start gap-2 text-sm">
            <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", meta.className)} aria-hidden />
            <p>
              <span className={cn("font-semibold", meta.className)}>{meta.label}: </span>
              <span className="text-text-secondary">{line.text}</span>
            </p>
          </div>
        );
      })}
      {playing && visibleCount < lines.length && (
        <div className="flex items-center gap-1 pl-6 text-text-muted" aria-hidden>
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.2s] motion-reduce:animate-none" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current motion-reduce:animate-none" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:0.2s] motion-reduce:animate-none" />
        </div>
      )}
    </div>
  );
}
