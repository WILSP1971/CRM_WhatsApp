import { AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import type {
  AlertaInventario,
  ManufacturingData,
  OrdenTrabajo,
} from "@/lib/sectorTypes";

const OT_BADGE: Record<
  OrdenTrabajo["estado"],
  { label: string; variant: "success" | "warning" | "danger" | "neutral" | "ai" }
> = {
  planificada: { label: "Planificada", variant: "neutral" },
  en_produccion: { label: "En producción", variant: "ai" },
  control_calidad: { label: "Control de calidad", variant: "warning" },
  completada: { label: "Completada", variant: "success" },
  detenida: { label: "Detenida", variant: "danger" },
};

const INVENTORY_BADGE: Record<
  AlertaInventario["nivel"],
  { label: string; variant: "success" | "warning" | "danger" }
> = {
  normal: { label: "Normal", variant: "success" },
  bajo: { label: "Stock bajo", variant: "warning" },
  critico: { label: "Crítico", variant: "danger" },
};

const SYNC_BADGE: Record<
  string,
  { label: string; variant: "success" | "warning" | "danger" | "neutral" }
> = {
  sincronizado: { label: "Sincronizado", variant: "success" },
  con_advertencias: { label: "Con advertencias", variant: "warning" },
  pendiente: { label: "Pendiente", variant: "neutral" },
  error: { label: "Error", variant: "danger" },
};

interface ManufacturingSectorViewProps {
  data: ManufacturingData;
}

/**
 * Vista de referencia Manufactura (SPEC-008): órdenes de trabajo, alertas de
 * inventario y panel de estado de sincronización ERP (visual, sin ERP real).
 */
export function ManufacturingSectorView({ data }: ManufacturingSectorViewProps) {
  const criticas = data.alertasInventario.filter((a) => a.nivel === "critico").length;
  const bajas = data.alertasInventario.filter((a) => a.nivel === "bajo").length;

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Órdenes de trabajo</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-sm">
              <caption className="sr-only">
                Órdenes de trabajo con producto, cantidad, avance y entrega
              </caption>
              <thead>
                <tr className="border-b border-border-subtle text-left text-xs text-text-muted">
                  <th scope="col" className="py-2 pr-3 font-medium">
                    Orden
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium">
                    Producto
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium">
                    Cantidad
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium">
                    Avance
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium">
                    Entrega
                  </th>
                  <th scope="col" className="py-2 pr-3 font-medium">
                    Estado
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.ordenesTrabajo.map((ot) => {
                  const meta = OT_BADGE[ot.estado];
                  return (
                    <tr
                      key={ot.id}
                      className="border-b border-border-subtle last:border-0"
                    >
                      <td className="py-2 pr-3 font-medium text-text-primary">{ot.id}</td>
                      <td className="py-2 pr-3 text-text-secondary">{ot.producto}</td>
                      <td className="py-2 pr-3 text-text-secondary">
                        {ot.cantidad.toLocaleString("es-CO")}
                      </td>
                      <td className="py-2 pr-3 text-text-secondary">{ot.avance}%</td>
                      <td className="py-2 pr-3 text-text-secondary">{ot.fechaEntrega}</td>
                      <td className="py-2 pr-3">
                        <Badge variant={meta.variant}>{meta.label}</Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <AlertTriangle
                  className="h-4 w-4 text-state-warning-strong"
                  aria-hidden
                />
                <CardTitle>Alertas de inventario</CardTitle>
              </div>
              <span className="text-xs text-text-muted">
                {criticas} críticas · {bajas} bajas
              </span>
            </div>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-2">
              {data.alertasInventario.map((alerta) => {
                const meta = INVENTORY_BADGE[alerta.nivel];
                return (
                  <li
                    key={alerta.id}
                    className="flex items-center justify-between gap-2 rounded-md border border-border-subtle p-2.5"
                  >
                    <div>
                      <p className="text-sm text-text-primary">{alerta.insumo}</p>
                      <p className="text-xs text-text-muted">
                        {alerta.stockActual.toLocaleString("es-CO")} / mínimo{" "}
                        {alerta.stockMinimo.toLocaleString("es-CO")} {alerta.unidad}
                      </p>
                    </div>
                    <Badge variant={meta.variant}>{meta.label}</Badge>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <RefreshCw className="h-4 w-4 text-accent-cyan-strong" aria-hidden />
              <CardTitle>Sincronización ERP (cadena de suministro)</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-state-success-strong" aria-hidden />
              <span className="text-sm text-text-secondary">
                Última sincronización: {formatDateTime(data.syncErp.ultimaSincronizacion)}
              </span>
            </div>
            <ul className="flex flex-col gap-2">
              {data.syncErp.modulos.map((mod) => {
                const meta = SYNC_BADGE[mod.estado];
                return (
                  <li
                    key={mod.id}
                    className="flex items-center justify-between gap-2 rounded-md border border-border-subtle p-2.5"
                  >
                    <div>
                      <p className="text-sm text-text-primary">{mod.nombre}</p>
                      <p className="text-xs text-text-muted">
                        {mod.registros.toLocaleString("es-CO")} registros ·{" "}
                        {formatDateTime(mod.ultimaActualizacion)}
                      </p>
                    </div>
                    <Badge variant={meta.variant}>{meta.label}</Badge>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
