import { useMemo, useState } from "react";
import { PhoneCall } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Badge,
} from "@/components/ui";
import { AudioWaveform } from "@/components/voicebot/AudioWaveform";
import { Dialpad, type CallLineStatus } from "@/components/voicebot/Dialpad";
import { LiveTranscript } from "@/components/voicebot/LiveTranscript";
import { RecordingControls } from "@/components/voicebot/RecordingControls";
import { IntentBadge } from "@/components/voicebot/IntentBadge";
import { CallHistory } from "@/components/voicebot/CallHistory";
import { CallDetailCard } from "@/components/voicebot/CallDetailCard";
import callsData from "@/mocks/calls.json";
import voiceBotData from "@/mocks/voicebot.json";
import type { CallRecord, VoiceBotData, VoiceBotIntent } from "@/lib/types";
import { useCallCenterData } from "@/lib/dataProvider/useCallCenterData";

const calls = callsData as CallRecord[];
const voiceBot = voiceBotData as VoiceBotData;

const intentsById: Record<string, VoiceBotIntent> = Object.fromEntries(
  voiceBot.intents.map((intent) => [intent.id, intent]),
);

/**
 * Centro de llamadas VoiceBot (SPEC-006). Representación visual completa
 * de un webphone con onda de audio, transcripción y detección de intención
 * simuladas: no hay VoIP, captura de micrófono ni STT reales.
 */
export function CallCenterPage() {
  const [number, setNumber] = useState("");
  const [status, setStatus] = useState<CallLineStatus>("colgado");
  const [muted, setMuted] = useState(false);
  const [activeCallId, setActiveCallId] = useState<string>(voiceBot.activeCallId);

  const inCall = status !== "colgado";
  const transcriptLines = voiceBot.transcripts[activeCallId] ?? [];
  const currentIntent = intentsById[voiceBot.callIntentMap[activeCallId]];

  const historyCalls = useMemo(
    () => [...calls].sort((a, b) => (a.startedAt < b.startedAt ? 1 : -1)),
    [],
  );

  // Ficha de llamada con datos REALES (SPEC-040), tras el feature-flag
  // `VITE_USE_REAL_API`. Con el flag OFF, `useRealApi` es `false` y nada de
  // lo de abajo hace una sola llamada de red: la maqueta de arriba (webphone/
  // onda/transcripción simulada/historial mock) permanece exactamente igual
  // que en el Entregable #1 (RF-03 SPEC-040).
  const {
    useRealApi,
    calls: realCalls,
    loadingCalls: loadingRealCalls,
    selectedCallDetail,
    loadingDetail,
    audioUrl,
    error: realCallsError,
    selectCall,
  } = useCallCenterData();
  const [selectedRealCallId, setSelectedRealCallId] = useState<string | null>(null);

  const handleSelectRealCall = (callId: string) => {
    setSelectedRealCallId(callId);
    selectCall(callId);
  };

  const handleCall = () => {
    setStatus("en_llamada");
    // Representa una llamada saliente simulada usando la última fixture
    // disponible para dar contenido a la transcripción/intención.
    setActiveCallId(voiceBot.activeCallId);
  };

  const handleHangup = () => {
    setStatus("colgado");
    setMuted(false);
    setNumber("");
  };

  const handleToggleHold = () => {
    setStatus((prev) => (prev === "en_espera" ? "en_llamada" : "en_espera"));
  };

  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-center gap-3">
        <div
          className="bg-accent-indigo/15 flex h-10 w-10 items-center justify-center rounded-lg text-accent-indigo-strong"
          aria-hidden
        >
          <PhoneCall className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-text-primary">
            Centro de llamadas VoiceBot
          </h1>
          <p className="text-sm text-text-secondary">
            Webphone, onda de audio, transcripción y detección de intención — todo
            simulado (SPEC-006), sin VoIP ni captura de micrófono real.
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <Card glass>
          <CardHeader>
            <CardTitle>Webphone</CardTitle>
            <CardDescription>
              Marcador telefónico web (representación visual).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Dialpad
              number={number}
              onNumberChange={setNumber}
              status={status}
              muted={muted}
              onToggleMute={() => setMuted((prev) => !prev)}
              onCall={handleCall}
              onHangup={handleHangup}
              onToggleHold={handleToggleHold}
            />
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Onda de audio en vivo</CardTitle>
              <CardDescription>
                Visualización sintética (mock); no se captura audio del micrófono.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <AudioWaveform active={inCall && status !== "en_espera"} />
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between gap-2">
                  <CardTitle>Transcripción en vivo</CardTitle>
                  <IntentBadge intent={currentIntent} />
                </div>
                <CardDescription>
                  Voz-a-texto simulada a partir de fixtures ficticias.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <LiveTranscript
                  lines={transcriptLines}
                  playing={inCall && status !== "en_espera"}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Grabación de llamada</CardTitle>
                <CardDescription>
                  Indicador y controles (representación visual).
                </CardDescription>
              </CardHeader>
              <CardContent>
                <RecordingControls enabled={inCall} />
              </CardContent>
            </Card>
          </div>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Historial de llamadas</CardTitle>
          <CardDescription>
            Datos ficticios de referencia (fixtures locales).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <CallHistory
            calls={historyCalls}
            intentsById={intentsById}
            callIntentMap={voiceBot.callIntentMap}
          />
        </CardContent>
      </Card>

      {useRealApi && (
        <>
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle>Llamadas reales (canal de voz)</CardTitle>
                <Badge variant="ai">Conectado · API real</Badge>
              </div>
              <CardDescription>
                Datos reales del pipeline de voz (SPEC-036..039): selecciona una
                llamada para ver su ficha completa.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {realCallsError && !selectedCallDetail && (
                <p
                  role="alert"
                  className="border-state-danger-strong/40 bg-state-danger-strong/10 mb-3 rounded-lg border p-3 text-sm text-state-danger-strong"
                >
                  {realCallsError}
                </p>
              )}
              {loadingRealCalls ? (
                <div
                  className="h-24 animate-pulse rounded-lg bg-bg-surface-raised motion-reduce:animate-none"
                  aria-hidden
                />
              ) : realCalls.length === 0 ? (
                <p className="text-sm text-text-muted">
                  Aún no hay llamadas reales registradas para este tenant.
                </p>
              ) : (
                <ul className="flex flex-col gap-2" aria-label="Llamadas reales del tenant">
                  {realCalls.map((call) => (
                    <li key={call.id}>
                      <button
                        type="button"
                        onClick={() => handleSelectRealCall(call.id)}
                        aria-pressed={selectedRealCallId === call.id}
                        className="flex w-full items-center justify-between gap-2 rounded-lg border border-border-subtle bg-bg-surface p-3 text-left text-sm hover:bg-bg-surface-raised aria-pressed:border-accent-indigo-strong"
                      >
                        <span className="text-text-primary">{call.numero}</span>
                        <span className="text-text-muted">{call.estado}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <CallDetailCard
            detail={selectedCallDetail}
            loading={loadingDetail}
            audioUrl={audioUrl}
            error={selectedRealCallId ? realCallsError : null}
          />
        </>
      )}
    </div>
  );
}
