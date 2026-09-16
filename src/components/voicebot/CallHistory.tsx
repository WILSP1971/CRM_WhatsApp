import { Disc3, PhoneIncoming, PhoneMissed, PhoneOutgoing } from "lucide-react";
import type { CallRecord, VoiceBotIntent } from "@/lib/types";
import contactsData from "@/mocks/contacts.json";
import type { Contact } from "@/lib/types";
import { Badge } from "@/components/ui";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";

const contacts = contactsData as Contact[];

interface CallHistoryProps {
  calls: CallRecord[];
  intentsById: Record<string, VoiceBotIntent>;
  callIntentMap: Record<string, string>;
}

const STATUS_META: Record<
  CallRecord["status"],
  { label: string; badge: "success" | "warning" | "danger" | "neutral" }
> = {
  finalizada: { label: "Finalizada", badge: "success" },
  en_espera: { label: "En espera", badge: "warning" },
  en_llamada: { label: "En llamada", badge: "success" },
  perdida: { label: "Perdida", badge: "danger" },
};

function formatStartedAt(iso: string): string {
  return new Intl.DateTimeFormat("es-CO", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

/** Historial de llamadas (fixtures) — SPEC-006. */
export function CallHistory({ calls, intentsById, callIntentMap }: CallHistoryProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border-subtle">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <caption className="sr-only">
          Historial de llamadas del VoiceBot (datos ficticios)
        </caption>
        <thead>
          <tr className="border-b border-border-subtle bg-bg-surface text-left text-xs uppercase tracking-wide text-text-muted">
            <th scope="col" className="px-3 py-2 font-semibold">
              Contacto
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Dirección
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Estado
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Duración
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Intención
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Grabación
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Inicio
            </th>
          </tr>
        </thead>
        <tbody>
          {calls.map((call) => {
            const contact = contacts.find((c) => c.id === call.contactId);
            const intent = intentsById[callIntentMap[call.id]];
            const statusMeta = STATUS_META[call.status];
            const DirectionIcon =
              call.status === "perdida"
                ? PhoneMissed
                : call.direction === "entrante"
                  ? PhoneIncoming
                  : PhoneOutgoing;

            return (
              <tr
                key={call.id}
                className="border-b border-border-subtle last:border-0 hover:bg-bg-surface-raised"
              >
                <td className="px-3 py-2 text-text-primary">
                  {contact?.name ?? "Contacto desconocido"}
                </td>
                <td className="px-3 py-2 text-text-secondary">
                  <span className="inline-flex items-center gap-1.5">
                    <DirectionIcon
                      className={cn(
                        "h-3.5 w-3.5",
                        call.status === "perdida" && "text-state-danger",
                      )}
                      aria-hidden
                    />
                    {call.direction === "entrante" ? "Entrante" : "Saliente"}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <Badge variant={statusMeta.badge}>{statusMeta.label}</Badge>
                </td>
                <td className="px-3 py-2 font-mono text-text-secondary">
                  {formatDuration(call.durationSeconds)}
                </td>
                <td className="px-3 py-2">
                  {intent ? (
                    <Badge variant="ai">{intent.label}</Badge>
                  ) : (
                    <span className="text-text-muted">—</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  {call.recordingSimulated ? (
                    <span className="inline-flex items-center gap-1.5 text-text-secondary">
                      <Disc3
                        className="h-3.5 w-3.5 text-accent-cyan-strong"
                        aria-hidden
                      />
                      Disponible
                    </span>
                  ) : (
                    <span className="text-text-muted">No disponible</span>
                  )}
                </td>
                <td className="px-3 py-2 text-text-secondary">
                  {formatStartedAt(call.startedAt)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
