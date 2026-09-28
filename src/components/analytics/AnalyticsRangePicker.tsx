import { Button, Input } from "@/components/ui";
import {
  rangeForPreset,
  type AnalyticsChannelFilter,
  type AnalyticsDateRange,
  type AnalyticsRangePreset,
} from "@/lib/dataProvider/useAnalyticsData";
import { CHANNEL_META } from "@/lib/channels";
import type { Channel } from "@/lib/types";
import { cn } from "@/lib/cn";

interface AnalyticsRangePickerProps {
  range: AnalyticsDateRange;
  onChange: (range: AnalyticsDateRange) => void;
  canal: AnalyticsChannelFilter;
  onCanalChange: (canal: AnalyticsChannelFilter) => void;
}

const PRESET_OPTIONS: { id: Exclude<AnalyticsRangePreset, "custom">; label: string }[] = [
  { id: "hoy", label: "Hoy" },
  { id: "7d", label: "7 días" },
  { id: "30d", label: "30 días" },
];

// Mismo vocabulario/labels que el resto de la SPA (`CHANNEL_META`,
// `CANALES_VALIDOS` del backend, `app/schemas/conversation.py`).
const CHANNEL_OPTIONS: { id: Channel; label: string }[] = (
  Object.keys(CHANNEL_META) as Channel[]
).map((id) => ({ id, label: CHANNEL_META[id].label }));

/**
 * Selector de rango de fechas + canal de `AnalyticsPage` (SPEC-064, RF-02):
 * presets hoy/7d/30d + rango custom (date pickers nativos) y filtro de canal
 * (`CANALES_VALIDOS` del backend). Cambiar cualquier control invoca
 * `onChange`/`onCanalChange` de inmediato (re-consulta on-demand).
 */
export function AnalyticsRangePicker({
  range,
  onChange,
  canal,
  onCanalChange,
}: AnalyticsRangePickerProps) {
  const handlePreset = (preset: Exclude<AnalyticsRangePreset, "custom">) => {
    onChange({ preset, ...rangeForPreset(preset) });
  };

  const handleCustomChange = (field: "desde" | "hasta", value: string) => {
    if (!value) return;
    onChange({
      preset: "custom",
      desde: field === "desde" ? value : range.desde,
      hasta: field === "hasta" ? value : range.hasta,
    });
  };

  const handleCanalChange = (value: string) => {
    onCanalChange(value === "" ? null : (value as Channel));
  };

  return (
    <fieldset className="flex flex-wrap items-end gap-3">
      <legend className="sr-only">Rango de fechas y canal de la analítica</legend>

      <div
        role="group"
        aria-label="Presets de rango"
        className="flex items-center gap-1 rounded-lg border border-border-subtle bg-bg-surface p-1"
      >
        {PRESET_OPTIONS.map((option) => (
          <Button
            key={option.id}
            type="button"
            variant="secondary"
            size="sm"
            aria-pressed={range.preset === option.id}
            className={cn(
              range.preset === option.id &&
                "bg-accent-indigo text-text-inverse hover:bg-accent-indigo",
            )}
            onClick={() => handlePreset(option.id)}
          >
            {option.label}
          </Button>
        ))}
      </div>

      <div className="flex items-end gap-2">
        <div className="flex flex-col gap-1 text-xs text-text-secondary">
          <label htmlFor="analytics-range-desde">Desde</label>
          <Input
            id="analytics-range-desde"
            type="date"
            value={range.desde}
            max={range.hasta}
            onChange={(e) => handleCustomChange("desde", e.target.value)}
            className="h-9 w-36"
          />
        </div>
        <div className="flex flex-col gap-1 text-xs text-text-secondary">
          <label htmlFor="analytics-range-hasta">Hasta</label>
          <Input
            id="analytics-range-hasta"
            type="date"
            value={range.hasta}
            min={range.desde}
            onChange={(e) => handleCustomChange("hasta", e.target.value)}
            className="h-9 w-36"
          />
        </div>
      </div>

      <div className="flex flex-col gap-1 text-xs text-text-secondary">
        <label htmlFor="analytics-range-canal">Canal</label>
        <select
          id="analytics-range-canal"
          value={canal ?? ""}
          onChange={(e) => handleCanalChange(e.target.value)}
          className={cn(
            "h-9 w-40 rounded-md border border-border-default bg-bg-surface-raised px-2 text-sm text-text-primary",
            "transition-colors duration-fast ease-standard",
            "focus-visible:border-accent-cyan focus-visible:shadow-focus focus-visible:outline-none",
          )}
        >
          <option value="">Todos los canales</option>
          {CHANNEL_OPTIONS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {range.preset === "custom" && (
        <span className="text-xs text-text-muted" aria-live="polite">
          Rango personalizado: {range.desde} a {range.hasta}
        </span>
      )}
    </fieldset>
  );
}
