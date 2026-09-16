import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { Card } from "@/components/ui";
import { cn } from "@/lib/cn";

export interface KpiCardProps {
  label: string;
  displayValue: string;
  delta: number;
  trend: "up" | "down" | "flat";
  /** Cuándo una tendencia "up" es negativa para el negocio (p. ej. tickets abiertos). */
  invertGoodDirection?: boolean;
}

const TREND_ICON = { up: ArrowUp, down: ArrowDown, flat: Minus };

/**
 * Tarjeta de KPI reutilizable para los paneles de sector (SPEC-007/008).
 * La tendencia se comunica con icono + texto (no solo color) para AAA.
 */
export function KpiCard({
  label,
  displayValue,
  delta,
  trend,
  invertGoodDirection = false,
}: KpiCardProps) {
  const TrendIcon = TREND_ICON[trend];
  const isGood = invertGoodDirection ? trend === "down" : trend === "up";
  const trendColorClass =
    trend === "flat"
      ? "text-text-muted"
      : isGood
        ? "text-state-success-strong"
        : "text-state-danger-strong";
  const trendLabel =
    trend === "flat" ? "sin cambio" : trend === "up" ? "en aumento" : "en descenso";

  return (
    <Card className="flex flex-col gap-2">
      <span className="text-sm text-text-secondary">{label}</span>
      <span className="text-2xl font-semibold text-text-primary">{displayValue}</span>
      <span
        className={cn(
          "inline-flex items-center gap-1 text-xs font-medium",
          trendColorClass,
        )}
      >
        <TrendIcon className="h-3.5 w-3.5" aria-hidden />
        {Math.abs(delta).toFixed(1)}% {trendLabel} vs. periodo anterior
      </span>
    </Card>
  );
}
