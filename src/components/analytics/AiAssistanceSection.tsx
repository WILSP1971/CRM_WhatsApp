import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import type { BackendAiAssistanceMetrics } from "@/lib/api/backendTypes";

interface AiAssistanceSectionProps {
  data: BackendAiAssistanceMetrics;
}

function formatPercent(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

/**
 * Sección opcional de asistencia IA (SPEC-064/RF-01): % de borradores RAG
 * aprobados + distribución de sentimiento. Se oculta por completo desde la
 * página cuando `ia_asistencia` es `null` (sin error, RF-04 SPEC-062/063).
 */
export function AiAssistanceSection({ data }: AiAssistanceSectionProps) {
  const { sentimiento } = data;
  const totalClasificado =
    sentimiento.positivo + sentimiento.neutral + sentimiento.negativo + sentimiento.sin_clasificar;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Asistencia IA</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <span className="text-sm text-text-secondary">
            Borradores RAG aprobados
          </span>
          <p className="text-2xl font-semibold text-text-primary">
            {formatPercent(data.pct_drafts_aprobados)}
          </p>
          <p className="text-xs text-text-muted">
            {data.conversaciones_con_draft_aprobado} de {data.conversaciones_total} conversaciones
            con al menos un borrador aprobado.
          </p>
        </div>

        <div>
          <span className="text-sm text-text-secondary">Distribución de sentimiento</span>
          {totalClasificado === 0 ? (
            <p className="text-sm text-text-muted">Sin mensajes clasificados en este rango.</p>
          ) : (
            <table className="mt-1 w-full border-collapse text-sm">
              <caption className="sr-only">Distribución de sentimiento de mensajes</caption>
              <thead>
                <tr className="border-b border-border-subtle text-left text-xs text-text-muted">
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Sentimiento
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Mensajes
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-border-subtle">
                  <td className="py-1.5 pr-3 text-text-primary">Positivo</td>
                  <td className="py-1.5 pr-3 text-text-secondary">{sentimiento.positivo}</td>
                </tr>
                <tr className="border-b border-border-subtle">
                  <td className="py-1.5 pr-3 text-text-primary">Neutral</td>
                  <td className="py-1.5 pr-3 text-text-secondary">{sentimiento.neutral}</td>
                </tr>
                <tr className="border-b border-border-subtle">
                  <td className="py-1.5 pr-3 text-text-primary">Negativo</td>
                  <td className="py-1.5 pr-3 text-text-secondary">{sentimiento.negativo}</td>
                </tr>
                <tr>
                  <td className="py-1.5 pr-3 text-text-primary">Sin clasificar</td>
                  <td className="py-1.5 pr-3 text-text-secondary">
                    {sentimiento.sin_clasificar}
                  </td>
                </tr>
              </tbody>
            </table>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
