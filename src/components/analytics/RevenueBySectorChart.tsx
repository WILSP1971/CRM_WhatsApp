import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { AccessibleChartFrame } from "@/components/sectors/AccessibleChartFrame";
import { formatCurrency } from "@/lib/format";
import type { KpiBySector } from "@/lib/types";

interface RevenueBySectorChartProps {
  data: KpiBySector[];
}

const SECTOR_LABEL: Record<string, string> = {
  comercial: "Comercial",
  servicios: "Servicios",
  manufactura: "Manufactura",
};

/** Ingresos estimados por sector (SPEC-008, analítica multisectorial). */
export function RevenueBySectorChart({ data }: RevenueBySectorChartProps) {
  const chartData = data.map((d) => ({
    ...d,
    sector: SECTOR_LABEL[d.sector] ?? d.sector,
  }));
  const top = [...data].sort((a, b) => b.ingresosEstimados - a.ingresosEstimados)[0];
  const trendSummary = `Ingresos estimados por sector: ${chartData
    .map((d) => `${d.sector} ${formatCurrency(d.ingresosEstimados)}`)
    .join(
      ", ",
    )}. El sector con mayores ingresos es ${SECTOR_LABEL[top.sector] ?? top.sector}.`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ingresos estimados por sector</CardTitle>
      </CardHeader>
      <CardContent>
        <AccessibleChartFrame
          title="Ingresos por sector"
          description="Comparativo de ingresos estimados entre Comercial, Servicios y Manufactura."
          trendSummary={trendSummary}
          chart={
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
              >
                <CartesianGrid
                  stroke="var(--color-border-subtle)"
                  strokeDasharray="3 3"
                />
                <XAxis
                  dataKey="sector"
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
                  dataKey="ingresosEstimados"
                  name="Ingresos estimados"
                  fill="var(--color-chart-indigo)"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          }
          table={
            <table className="w-full border-collapse text-sm">
              <caption className="sr-only">
                Ingresos estimados y tickets abiertos por sector
              </caption>
              <thead>
                <tr className="border-b border-border-subtle text-left text-xs text-text-muted">
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Sector
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Ingresos estimados
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Tickets abiertos
                  </th>
                </tr>
              </thead>
              <tbody>
                {chartData.map((row) => (
                  <tr
                    key={row.sector}
                    className="border-b border-border-subtle last:border-0"
                  >
                    <td className="py-1.5 pr-3 text-text-primary">{row.sector}</td>
                    <td className="py-1.5 pr-3 text-text-secondary">
                      {formatCurrency(row.ingresosEstimados)}
                    </td>
                    <td className="py-1.5 pr-3 text-text-secondary">
                      {row.ticketsAbiertos}
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
