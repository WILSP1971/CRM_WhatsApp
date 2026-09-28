import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { AccessibleChartFrame } from "@/components/sectors/AccessibleChartFrame";
import type { BackendSerieDiariaPunto } from "@/lib/api/backendTypes";

interface ConversationsSeriesChartProps {
  data: BackendSerieDiariaPunto[];
}

/**
 * Serie temporal de conversaciones por día (SPEC-064/RF-01), datos reales
 * de `GET /analytics/business`. Reutiliza el mismo envoltorio accesible
 * (`AccessibleChartFrame`, WCAG AAA) que `CsatTrendChart` (SPEC-008) en vez
 * de duplicar un componente de gráfico nuevo.
 */
export function ConversationsSeriesChart({ data }: ConversationsSeriesChartProps) {
  const total = data.reduce((sum, punto) => sum + punto.total, 0);
  const trendSummary =
    data.length === 0
      ? "Sin datos de conversaciones en el rango seleccionado."
      : `Conversaciones por día en el rango: ${total} en total entre ${data[0].fecha} y ${data[data.length - 1].fecha}.`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Conversaciones por día</CardTitle>
      </CardHeader>
      <CardContent>
        <AccessibleChartFrame
          title="Serie diaria de conversaciones"
          description="Número de conversaciones creadas por día en el rango seleccionado."
          trendSummary={trendSummary}
          chart={
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="var(--color-border-subtle)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="fecha"
                  stroke="var(--color-text-secondary)"
                  tick={{ fill: "var(--color-text-secondary)", fontSize: 12 }}
                />
                <YAxis
                  allowDecimals={false}
                  stroke="var(--color-text-secondary)"
                  tick={{ fill: "var(--color-text-secondary)", fontSize: 12 }}
                />
                <RechartsTooltip
                  contentStyle={{
                    background: "var(--color-bg-surface-raised)",
                    border: "1px solid var(--color-border-default)",
                    borderRadius: 8,
                    color: "var(--color-text-primary)",
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="total"
                  name="Conversaciones"
                  stroke="var(--color-chart-indigo)"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          }
          table={
            <table className="w-full border-collapse text-sm">
              <caption className="sr-only">Conversaciones por día</caption>
              <thead>
                <tr className="border-b border-border-subtle text-left text-xs text-text-muted">
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Fecha
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Conversaciones
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.map((row) => (
                  <tr key={row.fecha} className="border-b border-border-subtle last:border-0">
                    <td className="py-1.5 pr-3 text-text-primary">{row.fecha}</td>
                    <td className="py-1.5 pr-3 text-text-secondary">{row.total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          }
        />
      </CardContent>
    </Card>
  );
}
