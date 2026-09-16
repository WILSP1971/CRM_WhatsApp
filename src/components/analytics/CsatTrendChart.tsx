import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { AccessibleChartFrame } from "@/components/sectors/AccessibleChartFrame";
import type { CsatMensual } from "@/lib/sectorTypes";

interface CsatTrendChartProps {
  data: CsatMensual[];
}

/** Tendencia de CSAT por sector (SPEC-008, analítica multisectorial, Recharts). */
export function CsatTrendChart({ data }: CsatTrendChartProps) {
  const last = data[data.length - 1];
  const trendSummary = `CSAT en ${last.mes}: Comercial ${last.comercial}%, Servicios ${last.servicios}%, Manufactura ${last.manufactura}%. Los tres sectores muestran tendencia estable a la alza desde ${data[0].mes}.`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Tendencia de satisfacción (CSAT) por sector</CardTitle>
      </CardHeader>
      <CardContent>
        <AccessibleChartFrame
          title="CSAT mensual"
          description="Porcentaje de satisfacción del cliente por sector, últimos 6 meses."
          trendSummary={trendSummary}
          chart={
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid
                  stroke="var(--color-border-subtle)"
                  strokeDasharray="3 3"
                />
                <XAxis
                  dataKey="mes"
                  stroke="var(--color-text-secondary)"
                  tick={{ fill: "var(--color-text-secondary)", fontSize: 12 }}
                />
                <YAxis
                  domain={[80, 100]}
                  stroke="var(--color-text-secondary)"
                  tick={{ fill: "var(--color-text-secondary)", fontSize: 12 }}
                  tickFormatter={(value: number) => `${value}%`}
                />
                <RechartsTooltip
                  formatter={(value) => `${value}%`}
                  contentStyle={{
                    background: "var(--color-bg-surface-raised)",
                    border: "1px solid var(--color-border-default)",
                    borderRadius: 8,
                    color: "var(--color-text-primary)",
                  }}
                />
                <Legend
                  wrapperStyle={{ color: "var(--color-text-secondary)", fontSize: 12 }}
                />
                <Line
                  type="monotone"
                  dataKey="comercial"
                  name="Comercial"
                  stroke="var(--color-chart-indigo)"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
                <Line
                  type="monotone"
                  dataKey="servicios"
                  name="Servicios"
                  stroke="var(--color-chart-cyan)"
                  strokeWidth={2}
                  strokeDasharray="6 2"
                  dot={{ r: 3, strokeWidth: 1 }}
                />
                <Line
                  type="monotone"
                  dataKey="manufactura"
                  name="Manufactura"
                  stroke="var(--color-chart-warning)"
                  strokeWidth={2}
                  strokeDasharray="2 2"
                  dot={{ r: 4, strokeWidth: 1 }}
                />
              </LineChart>
            </ResponsiveContainer>
          }
          table={
            <table className="w-full border-collapse text-sm">
              <caption className="sr-only">CSAT mensual por sector</caption>
              <thead>
                <tr className="border-b border-border-subtle text-left text-xs text-text-muted">
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Mes
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Comercial
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Servicios
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Manufactura
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.map((row) => (
                  <tr
                    key={row.mes}
                    className="border-b border-border-subtle last:border-0"
                  >
                    <td className="py-1.5 pr-3 text-text-primary">{row.mes}</td>
                    <td className="py-1.5 pr-3 text-text-secondary">{row.comercial}%</td>
                    <td className="py-1.5 pr-3 text-text-secondary">{row.servicios}%</td>
                    <td className="py-1.5 pr-3 text-text-secondary">
                      {row.manufactura}%
                    </td>
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
