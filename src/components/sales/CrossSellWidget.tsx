import { Sparkles } from "lucide-react";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { formatCurrency } from "@/lib/format";
import type { VentaCruzada } from "@/lib/sectorTypes";

interface CrossSellWidgetProps {
  sugerencias: VentaCruzada[];
}

/** Indicadores de venta cruzada (SPEC-007, RF-07): sugerencias/oportunidades mock. */
export function CrossSellWidget({ sugerencias }: CrossSellWidgetProps) {
  return (
    <Card glass>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-accent-cyan-strong" aria-hidden />
          <CardTitle>Venta cruzada sugerida</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-3">
          {sugerencias.map((item) => (
            <li
              key={item.id}
              className="flex flex-col gap-1 rounded-lg border border-border-subtle bg-bg-surface p-3"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-text-primary">
                  {item.cliente}
                </span>
                <Badge variant="ai">+{formatCurrency(item.impactoEstimado)}</Badge>
              </div>
              <p className="text-sm text-text-secondary">{item.sugerencia}</p>
              <p className="text-xs text-text-muted">{item.motivo}</p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
