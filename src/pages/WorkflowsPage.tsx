import { Workflow } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { KpiCard } from "@/components/sectors/KpiCard";
import { SalesKanbanBoard } from "@/components/sales/SalesKanbanBoard";
import { OrderTracking } from "@/components/sales/OrderTracking";
import { CrossSellWidget } from "@/components/sales/CrossSellWidget";
import { SalesTrendChart } from "@/components/sales/SalesTrendChart";
import { formatCurrency } from "@/lib/format";
import salesData from "@/mocks/sales.json";
import type { SalesData } from "@/lib/sectorTypes";

const sales = salesData as SalesData;

function formatKpiValue(kpi: SalesData["kpis"][number]): string {
  if (kpi.format === "currency") return formatCurrency(kpi.value);
  if (kpi.format === "percent") return `${kpi.value.toFixed(1)}%`;
  return kpi.value.toLocaleString("es-CO");
}

/**
 * Sector Comercial / E-Commerce completo (SPEC-007): embudo Kanban con
 * drag & drop, seguimiento de pedidos, venta cruzada y KPIs comerciales.
 * Datos 100% mock (src/mocks/sales.json) — cero llamadas externas.
 */
export function WorkflowsPage() {
  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-center gap-3">
        <div
          className="bg-accent-indigo/15 flex h-10 w-10 items-center justify-center rounded-lg text-accent-indigo-strong"
          aria-hidden
        >
          <Workflow className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-text-primary">
            Comercial / E-Commerce
          </h1>
          <p className="text-sm text-text-secondary">
            Embudo de ventas, pedidos y venta cruzada (maqueta, datos ficticios).
          </p>
        </div>
      </header>

      <section
        aria-label="KPIs comerciales"
        className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4"
      >
        {sales.kpis.map((kpi) => (
          <KpiCard
            key={kpi.id}
            label={kpi.label}
            displayValue={formatKpiValue(kpi)}
            delta={kpi.delta}
            trend={kpi.trend}
          />
        ))}
      </section>

      <section aria-labelledby="kanban-heading" className="flex flex-col gap-3">
        <Card>
          <CardHeader>
            <CardTitle id="kanban-heading">Embudo de ventas</CardTitle>
          </CardHeader>
          <CardContent>
            <SalesKanbanBoard etapas={sales.etapas} oportunidades={sales.oportunidades} />
          </CardContent>
        </Card>
      </section>

      <section className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <OrderTracking pedidos={sales.pedidos} />
        </div>
        <CrossSellWidget sugerencias={sales.ventaCruzada} />
      </section>

      <section>
        <SalesTrendChart data={sales.ventasPorMes} />
      </section>

      <p className="text-xs text-text-muted">{sales.notaFicticia}</p>
    </div>
  );
}
