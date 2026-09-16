import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { formatCurrency, formatDateTime } from "@/lib/format";
import type { EstadoPedido, Pedido } from "@/lib/sectorTypes";

const ESTADO_META: Record<
  EstadoPedido,
  { label: string; variant: "neutral" | "success" | "warning" | "danger" | "ai" }
> = {
  pendiente_pago: { label: "Pendiente de pago", variant: "warning" },
  confirmado: { label: "Confirmado", variant: "ai" },
  procesando: { label: "Procesando", variant: "neutral" },
  en_transito: { label: "En tránsito", variant: "ai" },
  entregado: { label: "Entregado", variant: "success" },
  cancelado: { label: "Cancelado", variant: "danger" },
};

interface OrderTrackingProps {
  pedidos: Pedido[];
}

/** Seguimiento de pedidos (SPEC-007, RF-07): estado, importe, fecha y canal. */
export function OrderTracking({ pedidos }: OrderTrackingProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Seguimiento de pedidos</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-sm">
            <caption className="sr-only">
              Tabla de pedidos con cliente, importe, fecha, canal y estado
            </caption>
            <thead>
              <tr className="border-b border-border-subtle text-left text-xs text-text-muted">
                <th scope="col" className="py-2 pr-3 font-medium">
                  Pedido
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Cliente
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Importe
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Fecha
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Canal
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Estado
                </th>
              </tr>
            </thead>
            <tbody>
              {pedidos.map((pedido) => {
                const meta = ESTADO_META[pedido.estado];
                return (
                  <tr
                    key={pedido.id}
                    className="border-b border-border-subtle last:border-0 hover:bg-bg-surface-raised"
                  >
                    <td className="py-2 pr-3 font-medium text-text-primary">
                      {pedido.id}
                    </td>
                    <td className="py-2 pr-3 text-text-secondary">{pedido.cliente}</td>
                    <td className="py-2 pr-3 text-text-secondary">
                      {formatCurrency(pedido.importe)}
                    </td>
                    <td className="py-2 pr-3 text-text-secondary">
                      {formatDateTime(pedido.fecha)}
                    </td>
                    <td className="py-2 pr-3 capitalize text-text-secondary">
                      {pedido.canal}
                    </td>
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
  );
}
