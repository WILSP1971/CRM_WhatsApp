import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import type { BackendConversacionesPorCanal } from "@/lib/api/backendTypes";

interface ChannelBreakdownTableProps {
  data: BackendConversacionesPorCanal[];
}

const CANAL_LABEL: Record<string, string> = {
  whatsapp: "WhatsApp",
  webchat: "WebChat",
  instagram: "Instagram",
  messenger: "Messenger",
  voz: "Voz",
};

/** Desglose de conversaciones por canal (SPEC-064/RF-01), datos reales. */
export function ChannelBreakdownTable({ data }: ChannelBreakdownTableProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Desglose por canal</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="text-sm text-text-muted">
            Sin conversaciones por canal en este rango.
          </p>
        ) : (
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">Conversaciones por canal</caption>
            <thead>
              <tr className="border-b border-border-subtle text-left text-xs text-text-muted">
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Canal
                </th>
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Total
                </th>
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Abiertas
                </th>
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Cerradas
                </th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.canal} className="border-b border-border-subtle last:border-0">
                  <td className="py-1.5 pr-3 text-text-primary">
                    {CANAL_LABEL[row.canal] ?? row.canal}
                  </td>
                  <td className="py-1.5 pr-3 text-text-secondary">{row.total}</td>
                  <td className="py-1.5 pr-3 text-text-secondary">{row.abiertas}</td>
                  <td className="py-1.5 pr-3 text-text-secondary">{row.cerradas}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}
