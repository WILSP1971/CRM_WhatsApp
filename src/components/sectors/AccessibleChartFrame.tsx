import { useId, useState, type ReactNode } from "react";
import { Button } from "@/components/ui";

interface AccessibleChartFrameProps {
  title: string;
  description: string;
  /** Resumen textual de la tendencia, para lectores de pantalla y modo tabla. */
  trendSummary: string;
  chart: ReactNode;
  table: ReactNode;
}

/**
 * Envoltorio accesible para gráficos Recharts (SPEC-008, WCAG AAA):
 * expone `aria-label` con el resumen de tendencia y un botón para alternar
 * a una tabla de datos equivalente (alternativa textual, no depende del color).
 */
export function AccessibleChartFrame({
  title,
  description,
  trendSummary,
  chart,
  table,
}: AccessibleChartFrameProps) {
  const [showTable, setShowTable] = useState(false);
  const regionId = useId();

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-text-primary">{title}</h4>
          <p className="text-xs text-text-secondary">{description}</p>
        </div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          aria-pressed={showTable}
          onClick={() => setShowTable((v) => !v)}
        >
          {showTable ? "Ver gráfico" : "Ver tabla"}
        </Button>
      </div>
      <div id={regionId} role="img" aria-label={trendSummary} className="h-64 w-full">
        {showTable ? table : chart}
      </div>
      <p className="sr-only">{trendSummary}</p>
    </div>
  );
}
