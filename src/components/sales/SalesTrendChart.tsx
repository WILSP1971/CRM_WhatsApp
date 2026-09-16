import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { AccessibleChartFrame } from "@/components/sectors/AccessibleChartFrame";
import { formatCurrency } from "@/lib/format";
import type { VentaMensual } from "@/lib/sectorTypes";

interface SalesTrendChartProps {
  data: VentaMensual[];
}

/** Gráfico de ventas vs. meta mensual (SPEC-007 KPIs comerciales, Recharts). */
export function SalesTrendChart({ data }: SalesTrendChartProps) {
  const last = data[data.length - 1];
  const first = data[0];
  const cambio = last.ventas - first.ventas;
  const trendSummary = `Ventas mensuales de ${first.mes} a ${last.mes}: iniciaron en ${formatCurrency(
    first.ventas,
  )} y cerraron en ${formatCurrency(last.ventas)}, una variación de ${formatCurrency(cambio)}. Meta del último mes: ${formatCurrency(last.meta)}.`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ventas vs. meta mensual</CardTitle>
      </CardHeader>
      <CardContent>
        <AccessibleChartFrame
          title="Ventas mensuales"
          description="Barras: ventas reales. Línea: meta mensual."
          trendSummary={trendSummary}
          chart={
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={data}
                margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
              >
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
                  stroke="var(--color-text-secondary)"
                  tick={{ fill: "var(--color-text-secondary)", fontSize: 12 }}
                  tickFormatter={(value: number) => `${Math.round(value / 1_000_000)}M`}
                />
                <RechartsTooltip
                  formatter={(value) => formatCurrency(Number(value))}
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
                <Bar
                  dataKey="ventas"
                  name="Ventas reales"
                  fill="var(--color-chart-indigo)"
                  radius={[4, 4, 0, 0]}
                />
                <Line
                  type="monotone"
                  dataKey="meta"
                  name="Meta"
                  stroke="var(--color-chart-cyan)"
                  strokeWidth={2}
                  strokeDasharray="6 3"
                  dot={{ r: 4, strokeWidth: 1 }}
                />
              </ComposedChart>
            </ResponsiveContainer>
          }
          table={
            <div className="h-full overflow-y-auto">
              <table className="w-full border-collapse text-sm">
                <caption className="sr-only">Ventas y meta por mes</caption>
                <thead>
                  <tr className="border-b border-border-subtle text-left text-xs text-text-muted">
                    <th scope="col" className="py-1.5 pr-3 font-medium">
                      Mes
                    </th>
                    <th scope="col" className="py-1.5 pr-3 font-medium">
                      Ventas
                    </th>
                    <th scope="col" className="py-1.5 pr-3 font-medium">
                      Meta
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
                      <td className="py-1.5 pr-3 text-text-secondary">
                        {formatCurrency(row.ventas)}
                      </td>
                      <td className="py-1.5 pr-3 text-text-secondary">
                        {formatCurrency(row.meta)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          }
        />
      </CardContent>
    </Card>
  );
}
