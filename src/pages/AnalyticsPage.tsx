import { BarChart3 } from "lucide-react";
import { KpiCard } from "@/components/sectors/KpiCard";
import { RevenueBySectorChart } from "@/components/analytics/RevenueBySectorChart";
import { CsatTrendChart } from "@/components/analytics/CsatTrendChart";
import { PipelineDonutChart } from "@/components/analytics/PipelineDonutChart";
import { AnalyticsRangePicker } from "@/components/analytics/AnalyticsRangePicker";
import { ConversationsSeriesChart } from "@/components/analytics/ConversationsSeriesChart";
import { ChannelBreakdownTable } from "@/components/analytics/ChannelBreakdownTable";
import { AiAssistanceSection } from "@/components/analytics/AiAssistanceSection";
import kpisData from "@/mocks/kpis.json";
import analyticsData from "@/mocks/analytics.json";
import salesData from "@/mocks/sales.json";
import type { KpiData } from "@/lib/types";
import type { AnalyticsData, SalesData } from "@/lib/sectorTypes";
import { useAnalyticsData } from "@/lib/dataProvider/useAnalyticsData";
import { formatDuration } from "@/lib/format";
import { USE_REAL_API } from "@/lib/env";

const kpis = kpisData as KpiData;
const analytics = analyticsData as AnalyticsData;
const sales = salesData as SalesData;

function formatPercentTasa(tasa: number | null): string {
  return tasa === null ? "—" : `${(tasa * 100).toFixed(1)}%`;
}

function formatSegundos(seconds: number | null): string {
  return seconds === null ? "—" : formatDuration(seconds);
}

/**
 * Analítica multisectorial (SPEC-008): KPIs generales + gráficos Recharts
 * (barras, líneas, donut) con densidad de datos nítida. Datos 100% mock.
 */
function MockAnalyticsView() {
  return (
    <>
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
    </>
  );
}

/**
 * Vista de analítica de negocio con datos REALES del tenant (SPEC-064),
 * detrás de `VITE_USE_REAL_API`: KPIs de conversaciones/conversión/tiempos
 * de respuesta, serie diaria, desglose por canal y (opcional) asistencia IA,
 * con selector de rango hoy/7d/30d + custom (Q4) y estados carga/vacío/error
 * accesibles (AAA, SPEC-009).
 */
function RealAnalyticsView() {
  const { range, setRange, canal, setCanal, data, loading, error, retry } = useAnalyticsData();

  const isEmptyRange = !loading && !error && data !== null && data.conversaciones.total === 0;

  return (
    <>
      <AnalyticsRangePicker
        range={range}
        onChange={setRange}
        canal={canal}
        onCanalChange={setCanal}
      />

      <p role="status" aria-live="polite" className="sr-only">
        {loading
          ? "Cargando analítica de negocio…"
          : error
            ? "Error cargando la analítica de negocio."
            : "Analítica de negocio actualizada."}
      </p>

      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-state-danger-strong/40 bg-state-danger-strong/10 p-4 text-sm text-state-danger-strong"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={retry}
            className="rounded-md border border-state-danger-strong/40 px-3 py-1.5 font-medium hover:bg-state-danger-strong/15 focus-visible:shadow-focus focus-visible:outline-none"
          >
            Reintentar
          </button>
        </div>
      )}

      {loading && (
        <section
          aria-label="Cargando KPIs"
          className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4"
        >
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className="h-24 animate-pulse rounded-lg bg-bg-surface-raised motion-reduce:animate-none"
              aria-hidden
            />
          ))}
        </section>
      )}

      {!loading && !error && isEmptyRange && (
        <p className="rounded-lg border border-border-subtle bg-bg-surface p-4 text-sm text-text-secondary">
          Sin datos en este rango: no se registraron conversaciones entre {range.desde} y{" "}
          {range.hasta}.
        </p>
      )}

      {!loading && !error && data && (
        <>
          <section
            aria-label="KPIs de negocio"
            className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4"
          >
            <KpiCard
              label="Conversaciones totales"
              displayValue={data.conversaciones.total.toLocaleString("es-CO")}
              trend={null}
            />
            <KpiCard
              label="Abiertas / cerradas"
              displayValue={`${data.conversaciones.abiertas} / ${data.conversaciones.cerradas}`}
              trend={null}
            />
            <KpiCard
              label="Tasa de conversión"
              displayValue={formatPercentTasa(data.conversion.tasa)}
              trend={null}
            />
            <KpiCard
              label="Primera respuesta (prom.)"
              displayValue={formatSegundos(
                data.tiempos_respuesta.primera_respuesta_promedio_seg,
              )}
              trend={null}
            />
          </section>

          <section
            aria-label="Detalle de tiempos de respuesta"
            className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          >
            <KpiCard
              label="Respuesta promedio (todas las idas y vueltas)"
              displayValue={formatSegundos(data.tiempos_respuesta.respuesta_promedio_seg)}
              trend={null}
            />
            <KpiCard
              label="Conversaciones con respuesta"
              displayValue={data.tiempos_respuesta.conversaciones_con_respuesta.toLocaleString(
                "es-CO",
              )}
              trend={null}
            />
          </section>

          <section className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <ConversationsSeriesChart data={data.conversaciones.serie_diaria} />
            <ChannelBreakdownTable data={data.conversaciones.por_canal} />
          </section>

          {data.ia_asistencia && (
            <section aria-label="Asistencia IA">
              <AiAssistanceSection data={data.ia_asistencia} />
            </section>
          )}
        </>
      )}
    </>
  );
}

/**
 * Página de analítica (SPEC-008/SPEC-064). Con `VITE_USE_REAL_API=false`
 * (default), el contenido es EXACTAMENTE el mock del Entregable #1 (RF-04
 * SPEC-064: sin regresión). Con el flag ON, se reemplaza por KPIs/series/
 * desglose reales del tenant (SPEC-063), en la misma ruta/página.
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
            {USE_REAL_API
              ? "Dashboard de métricas de negocio reales del tenant (conversaciones, tiempos de respuesta, conversión)."
              : "Dashboard de KPIs y gráficos con densidad de datos nítida (mock)."}
          </p>
        </div>
      </header>

      {USE_REAL_API ? <RealAnalyticsView /> : <MockAnalyticsView />}
    </div>
  );
}
