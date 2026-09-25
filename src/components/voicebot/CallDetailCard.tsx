import { FileAudio, PhoneIncoming, PhoneOutgoing } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Badge,
} from "@/components/ui";
import { RagCitationList } from "@/components/rag/RagCitationList";
import { formatDuration } from "@/lib/format";
import type { RealCallDetail, Sentiment } from "@/lib/types";

interface CallDetailCardProps {
  detail: RealCallDetail | null;
  loading: boolean;
  audioUrl: string | null;
  error: string | null;
}

const SENTIMENT_BADGE: Record<Sentiment, "success" | "warning" | "danger"> = {
  positivo: "success",
  neutral: "warning",
  negativo: "danger",
};

const SENTIMENT_LABEL: Record<Sentiment, string> = {
  positivo: "Positivo",
  neutral: "Neutral",
  negativo: "Negativo",
};

/**
 * Ficha de llamada con datos REALES (SPEC-040): transcripción (segmentos +
 * timestamps + hablante), sentimiento, resumen y borrador citado (`≥3`
 * citas). Solo se renderiza con `VITE_USE_REAL_API=true` (ver
 * `CallCenterPage`); con el flag OFF este componente ni se importa en
 * runtime desde la ruta de datos mock.
 *
 * Reproductor de audio SEGÚN retención (RF-02 SPEC-040): se muestra solo si
 * `audioUrl` no es `null` (el backend respondió 404 en `GET /calls/{id}/audio`
 * cuando el audio nunca existió o ya fue purgado/anonimizado, SPEC-041 aún no
 * implementada); en ese caso se muestra solo la transcripción.
 */
export function CallDetailCard({ detail, loading, audioUrl, error }: CallDetailCardProps) {
  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Ficha de llamada</CardTitle>
          <CardDescription>Cargando datos reales de la llamada…</CardDescription>
        </CardHeader>
        <CardContent>
          <div
            className="h-40 animate-pulse rounded-lg bg-bg-surface-raised motion-reduce:animate-none"
            aria-hidden
          />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Ficha de llamada</CardTitle>
        </CardHeader>
        <CardContent>
          <p
            role="alert"
            className="border-state-danger-strong/40 bg-state-danger-strong/10 rounded-lg border p-3 text-sm text-state-danger-strong"
          >
            {error}
          </p>
        </CardContent>
      </Card>
    );
  }

  if (!detail) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Ficha de llamada</CardTitle>
          <CardDescription>
            Selecciona una llamada del historial para ver su transcripción real.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const { call, transcript, sentiment, sentimentScore, ragDraft } = detail;
  const DirectionIcon = call.direccion === "entrante" ? PhoneIncoming : PhoneOutgoing;

  return (
    <Card glass>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Ficha de llamada — {call.numero}</CardTitle>
          {sentiment && (
            <Badge variant={SENTIMENT_BADGE[sentiment]}>
              Sentimiento: {SENTIMENT_LABEL[sentiment]}
              {sentimentScore !== null ? ` (${Math.round(sentimentScore * 100)}%)` : ""}
            </Badge>
          )}
        </div>
        <CardDescription>
          <span className="inline-flex items-center gap-1.5">
            <DirectionIcon className="h-3.5 w-3.5" aria-hidden />
            {call.direccion === "entrante" ? "Entrante" : "Saliente"} · Estado: {call.estado}
            {call.duracionSeconds !== null && (
              <> · Duración: {formatDuration(call.duracionSeconds)}</>
            )}
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {call.resumen && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
              Resumen (IA local)
            </h3>
            <p className="rounded-lg border border-border-subtle bg-bg-surface p-3 text-sm text-text-secondary">
              {call.resumen}
            </p>
          </div>
        )}

        <div>
          <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
            <FileAudio className="h-3.5 w-3.5" aria-hidden />
            Audio de la llamada
          </h3>
          {audioUrl ? (
            // eslint-disable-next-line jsx-a11y/media-has-caption -- transcripción exacta se muestra debajo
            <audio controls src={audioUrl} className="w-full">
              Tu navegador no admite la reproducción de audio.
            </audio>
          ) : (
            <p className="rounded-lg border border-border-subtle bg-bg-surface p-3 text-sm text-text-muted">
              Audio no disponible (nunca existió, o fue purgado/anonimizado por la
              política de retención). Solo se muestra la transcripción.
            </p>
          )}
        </div>

        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Transcripción real
          </h3>
          {transcript ? (
            <ol
              aria-label="Transcripción real de la llamada, con timestamps"
              className="flex max-h-64 flex-col gap-2 overflow-y-auto rounded-lg border border-border-subtle bg-bg-surface p-3"
            >
              {transcript.segmentos.map((segmento, index) => (
                <li key={`${segmento.inicio}-${index}`} className="text-sm">
                  <span className="mr-2 font-mono text-xs text-text-muted">
                    {segmento.inicio.toFixed(1)}s–{segmento.fin.toFixed(1)}s
                  </span>
                  <span className="font-semibold text-accent-indigo-strong">
                    {segmento.hablante}:{" "}
                  </span>
                  <span className="text-text-secondary">{segmento.texto}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="rounded-lg border border-border-subtle bg-bg-surface p-3 text-sm text-text-muted">
              Transcripción aún no disponible para esta llamada.
            </p>
          )}
        </div>

        {ragDraft && (
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
              Borrador RAG citado (revisión humana, SPEC-019)
            </h3>
            <div className="mb-2 rounded-lg border border-border-subtle bg-bg-surface p-3 text-sm text-text-secondary">
              {ragDraft.content}
            </div>
            <RagCitationList
              citations={ragDraft.citations}
              loading={false}
              ariaLabel="Citas de la base de conocimiento (llamada real)"
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
