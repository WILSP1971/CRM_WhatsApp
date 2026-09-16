import { useMemo, useState } from "react";
import { PhoneCall } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";
import { AudioWaveform } from "@/components/voicebot/AudioWaveform";
import { Dialpad, type CallLineStatus } from "@/components/voicebot/Dialpad";
import { LiveTranscript } from "@/components/voicebot/LiveTranscript";
import { RecordingControls } from "@/components/voicebot/RecordingControls";
import { IntentBadge } from "@/components/voicebot/IntentBadge";
import { CallHistory } from "@/components/voicebot/CallHistory";
import callsData from "@/mocks/calls.json";
import voiceBotData from "@/mocks/voicebot.json";
import type { CallRecord, VoiceBotData, VoiceBotIntent } from "@/lib/types";

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
    </div>
  );
}
