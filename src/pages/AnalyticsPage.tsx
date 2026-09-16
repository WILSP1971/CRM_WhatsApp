import { BarChart3 } from "lucide-react";
import { KpiCard } from "@/components/sectors/KpiCard";
import { RevenueBySectorChart } from "@/components/analytics/RevenueBySectorChart";
import { CsatTrendChart } from "@/components/analytics/CsatTrendChart";
import { PipelineDonutChart } from "@/components/analytics/PipelineDonutChart";
import kpisData from "@/mocks/kpis.json";
import analyticsData from "@/mocks/analytics.json";
import salesData from "@/mocks/sales.json";
import type { KpiData } from "@/lib/types";
import type { AnalyticsData, SalesData } from "@/lib/sectorTypes";

const kpis = kpisData as KpiData;
const analytics = analyticsData as AnalyticsData;
const sales = salesData as SalesData;

/**
 * Analítica multisectorial (SPEC-008): KPIs generales + gráficos Recharts
 * (barras, líneas, donut) con densidad de datos nítida. Datos 100% mock.
 */
export function AnalyticsPage() {
  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-center gap-3">
        <div
          className="bg-accent-indigo/15 flex h-10 w-10 items-center justify-center rounded-lg text-accent-indigo-strong"
          aria-hidden
        >
          <BarChart3 className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-text-primary">
            Analítica multisectorial
          </h1>
          <p className="text-sm text-text-secondary">
            Dashboard de KPIs y gráficos con densidad de datos nítida (mock).
          </p>
        </div>
      </header>

      <section
        aria-label="KPIs generales"
        className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4"
      >
        {kpis.resumen.map((kpi) => (
          <KpiCard
            key={kpi.id}
            label={kpi.label}
            displayValue={kpi.value.toLocaleString("es-CO")}
            delta={kpi.delta}
            trend={kpi.trend}
          />
        ))}
      </section>

      <section className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <RevenueBySectorChart data={kpis.porSector} />
        <PipelineDonutChart etapas={sales.etapas} oportunidades={sales.oportunidades} />
      </section>

      <section>
        <CsatTrendChart data={analytics.csatMensual} />
      </section>

      <p className="text-xs text-text-muted">
        {kpis.notaFicticia} {analytics.notaFicticia}
      </p>
    </div>
  );
}
