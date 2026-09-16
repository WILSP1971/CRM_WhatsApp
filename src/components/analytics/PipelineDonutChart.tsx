import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { AccessibleChartFrame } from "@/components/sectors/AccessibleChartFrame";
import { formatCurrency } from "@/lib/format";
import type { EtapaEmbudo, Oportunidad } from "@/lib/sectorTypes";

interface PipelineDonutChartProps {
  etapas: EtapaEmbudo[];
  oportunidades: Oportunidad[];
}

const STAGE_TOKEN_COLOR: Record<EtapaEmbudo["color"], string> = {
  muted: "var(--color-chart-muted)",
  cyan: "var(--color-chart-cyan)",
  warning: "var(--color-chart-warning)",
  indigo: "var(--color-chart-indigo)",
  success: "var(--color-chart-success)",
  danger: "var(--color-chart-danger)",
};

/** Distribución del pipeline comercial por etapa (SPEC-008, donut Recharts). */
export function PipelineDonutChart({ etapas, oportunidades }: PipelineDonutChartProps) {
  const chartData = etapas
    .map((etapa) => ({
      etapa: etapa.label,
      color: STAGE_TOKEN_COLOR[etapa.color],
      monto: oportunidades
        .filter((op) => op.etapaId === etapa.id)
        .reduce((sum, op) => sum + op.monto, 0),
    }))
    .filter((row) => row.monto > 0);

  const total = chartData.reduce((sum, row) => sum + row.monto, 0);
  const trendSummary = `Distribución del pipeline comercial por etapa, total ${formatCurrency(total)}: ${chartData
    .map((row) => `${row.etapa} ${formatCurrency(row.monto)}`)
    .join(", ")}.`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Distribución del pipeline por etapa</CardTitle>
      </CardHeader>
      <CardContent>
        <AccessibleChartFrame
          title="Pipeline por etapa"
          description="Monto acumulado de oportunidades por etapa del embudo comercial."
          trendSummary={trendSummary}
          chart={
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={chartData}
                  dataKey="monto"
                  nameKey="etapa"
                  innerRadius="55%"
                  outerRadius="80%"
                  paddingAngle={2}
                  label={(entry) =>
                    `${entry.name} ${(((entry.percent as number | undefined) ?? 0) * 100).toFixed(0)}%`
                  }
                >
                  {chartData.map((row) => (
                    <Cell
                      key={row.etapa}
                      fill={row.color}
                      stroke="var(--color-bg-card)"
                    />
                  ))}
                </Pie>
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
              </PieChart>
            </ResponsiveContainer>
          }
          table={
            <table className="w-full border-collapse text-sm">
              <caption className="sr-only">Monto de pipeline por etapa</caption>
              <thead>
                <tr className="border-b border-border-subtle text-left text-xs text-text-muted">
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Etapa
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Monto
                  </th>
                </tr>
              </thead>
              <tbody>
                {chartData.map((row) => (
                  <tr
                    key={row.etapa}
                    className="border-b border-border-subtle last:border-0"
                  >
                    <td className="py-1.5 pr-3 text-text-primary">{row.etapa}</td>
                    <td className="py-1.5 pr-3 text-text-secondary">
                      {formatCurrency(row.monto)}
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
