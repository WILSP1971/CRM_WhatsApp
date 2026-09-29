import { AlertTriangle, CheckCircle2, Loader2, Volume2, Wand2 } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import type { RagDraft } from "@/lib/types";
import type { BackendRespuestaModo } from "@/lib/api/backendTypes";

interface RagDraftCardProps {
  draft: RagDraft | undefined;
  loading: boolean;
  onUseDraft: (text: string) => void;
  /**
   * Controles de audio (SPEC-069/070, ADR-014, Entregable #6): SOLO se
   * pasan/usan cuando `VITE_USE_REAL_API` está ON (RNF-FLAG). Con el flag
   * OFF, `RagPanel` no los pasa y esta tarjeta se comporta EXACTAMENTE
   * como antes de esta SPEC (sin ningún control de audio visible).
   */
  useRealApi?: boolean;
  approving?: boolean;
  settingRespuestaModo?: boolean;
  requestingAudio?: boolean;
  audioUrl?: string | null;
  audioError?: string | null;
  onSetRespuestaModo?: (mode: BackendRespuestaModo) => void;
  onRequestListen?: () => void;
  onApprove?: () => void;
}

/** Borrador de respuesta autogenerado (mock) con acción "Insertar borrador". */
export function RagDraftCard({
  draft,
  loading,
  onUseDraft,
  useRealApi = false,
  approving = false,
  settingRespuestaModo = false,
  requestingAudio = false,
  audioUrl = null,
  audioError = null,
  onSetRespuestaModo,
  onRequestListen,
  onApprove,
}: RagDraftCardProps) {
  // Opt-in (Q2-A): ausente/"texto" = comportamiento actual (RF-01/RNF-FLAG).
  const respuestaModoAudio = useRealApi && draft?.respuestaModo === "audio";
  const ttsEstado = draft?.ttsEstado ?? "no_solicitado";

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

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => onUseDraft(draft.text)}
            >
              <Wand2 className="h-3.5 w-3.5" aria-hidden />
              Usar borrador
            </Button>

            {useRealApi && (
              <label className="flex items-center gap-2 text-xs font-medium text-text-secondary">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-border-default accent-accent-cyan focus-visible:shadow-focus focus-visible:outline-none"
                  checked={respuestaModoAudio}
                  disabled={settingRespuestaModo || approving}
                  onChange={(event) =>
                    onSetRespuestaModo?.(event.target.checked ? "audio" : "texto")
                  }
                  aria-describedby={respuestaModoAudio ? "rag-audio-disclaimer" : undefined}
                />
                Responder con audio
              </label>
            )}

            {useRealApi && (
              <Button
                type="button"
                variant="primary"
                size="sm"
                onClick={() => onApprove?.()}
                disabled={approving}
              >
                {approving ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
                )}
                {approving ? "Aprobando…" : "Aprobar y enviar"}
              </Button>
            )}
          </div>

          {respuestaModoAudio && (
            <div className="mt-3 border-t border-border-subtle pt-3">
              <p
                id="rag-audio-disclaimer"
                className="mb-2 inline-flex items-center gap-1.5 text-xs font-semibold text-badge-ai-text"
              >
                <Volume2 className="h-3.5 w-3.5" aria-hidden />
                🔊 Respuesta de voz asistida — se informará al cliente que la voz es sintética.
              </p>

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => onRequestListen?.()}
                  disabled={requestingAudio || ttsEstado === "generando"}
                >
                  {requestingAudio || ttsEstado === "generando" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
                  ) : (
                    <Volume2 className="h-3.5 w-3.5" aria-hidden />
                  )}
                  {requestingAudio || ttsEstado === "generando"
                    ? "Generando audio…"
                    : "Escuchar antes de enviar"}
                </Button>

                {ttsEstado === "listo" && <Badge variant="success">Audio listo</Badge>}
                {(requestingAudio || ttsEstado === "generando") && (
                  <Badge variant="ai">Generando…</Badge>
                )}
                {ttsEstado === "error" && !audioError && (
                  <Badge variant="danger">Error al generar el audio</Badge>
                )}
              </div>

              <p role="status" aria-live="polite" className="sr-only">
                {requestingAudio || ttsEstado === "generando"
                  ? "Generando el clip de audio de la respuesta…"
                  : ttsEstado === "listo"
                    ? "Clip de audio listo para reproducir."
                    : ttsEstado === "error"
                      ? "No se pudo generar el clip de audio."
                      : ""}
              </p>

              {ttsEstado === "listo" && audioUrl && (
                <div className="mt-2">
                  <label htmlFor="rag-audio-player" className="mb-1 block text-xs text-text-muted">
                    Reproductor del clip generado (aprobación explícita requerida para enviarlo)
                  </label>
                  {/* eslint-disable-next-line jsx-a11y/media-has-caption -- clip TTS sin pista de subtítulos aplicable */}
                  <audio id="rag-audio-player" controls className="w-full">
                    <source src={audioUrl} type="audio/ogg" />
                  </audio>
                </div>
              )}

              {(ttsEstado === "error" || audioError) && (
                <div
                  role="alert"
                  className="border-state-danger-strong/40 bg-state-danger-strong/10 mt-2 flex flex-wrap items-center gap-2 rounded-lg border p-2 text-xs text-state-danger-strong"
                >
                  <AlertTriangle className="h-3.5 w-3.5 flex-none" aria-hidden />
                  <span className="min-w-0 flex-1">
                    {audioError ?? "No se pudo generar el clip de audio."}
                  </span>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => onRequestListen?.()}
                  >
                    Reintentar
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => onSetRespuestaModo?.("texto")}
                  >
                    Responder con texto
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <p className="rounded-lg border border-border-subtle bg-bg-surface-raised p-3 text-sm text-text-muted">
          No hay un borrador disponible para esta conversación.
        </p>
      )}
    </div>
  );
}
