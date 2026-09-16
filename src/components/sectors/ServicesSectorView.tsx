import { CalendarClock } from "lucide-react";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { formatCurrency, formatDateTime } from "@/lib/format";
import type { IndicadorSla, ServicesData } from "@/lib/sectorTypes";

const SLA_BADGE: Record<
  IndicadorSla["estado"],
  { label: string; variant: "success" | "warning" | "danger" }
> = {
  cumplido: { label: "Cumplido", variant: "success" },
  en_riesgo: { label: "En riesgo", variant: "warning" },
  incumplido: { label: "Incumplido", variant: "danger" },
};

const HITO_BADGE: Record<
  string,
  { label: string; variant: "success" | "warning" | "neutral" }
> = {
  completado: { label: "Completado", variant: "success" },
  en_curso: { label: "En curso", variant: "neutral" },
  en_riesgo: { label: "En riesgo", variant: "warning" },
};

interface ServicesSectorViewProps {
  data: ServicesData;
}

/**
 * Vista de referencia Servicios/Consultoría (SPEC-008): hitos de proyecto,
 * horas facturables, SLA (semáforo con etiqueta) y reservas.
 */
export function ServicesSectorView({ data }: ServicesSectorViewProps) {
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Hitos de proyecto</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="flex flex-col gap-3">
            {data.hitos.map((hito) => {
              const meta = HITO_BADGE[hito.estado];
              return (
                <li key={hito.id} className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium text-text-primary">
                        {hito.nombre}
                      </p>
                      <p className="text-xs text-text-muted">{hito.proyecto}</p>
                    </div>
                    <Badge variant={meta.variant}>{meta.label}</Badge>
                  </div>
                  <div
                    role="progressbar"
                    aria-valuenow={hito.avance}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`Avance de ${hito.nombre}: ${hito.avance}%`}
                    className="h-2 w-full overflow-hidden rounded-full bg-bg-surface-raised"
                  >
                    <div
                      className="h-full rounded-full bg-accent-indigo"
                      style={{ width: `${hito.avance}%` }}
                    />
                  </div>
                  <span className="text-xs text-text-secondary">
                    {hito.avance}% — límite {hito.fechaLimite}
                  </span>
                </li>
              );
            })}
          </ul>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Horas facturables (semana actual)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] border-collapse text-sm">
                <caption className="sr-only">
                  Horas facturables por consultor y proyecto
                </caption>
                <thead>
                  <tr className="border-b border-border-subtle text-left text-xs text-text-muted">
                    <th scope="col" className="py-2 pr-3 font-medium">
                      Consultor
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      Proyecto
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      Horas
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      Valor
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.horasFacturables.map((hf) => (
                    <tr
                      key={hf.id}
                      className="border-b border-border-subtle last:border-0"
                    >
                      <td className="py-2 pr-3 text-text-primary">{hf.consultor}</td>
                      <td className="py-2 pr-3 text-text-secondary">{hf.proyecto}</td>
                      <td className="py-2 pr-3 text-text-secondary">{hf.horas} h</td>
                      <td className="py-2 pr-3 text-text-secondary">
                        {formatCurrency(hf.horas * hf.tarifaHora)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Indicadores de SLA</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-2">
              {data.sla.map((sla) => {
                const meta = SLA_BADGE[sla.estado];
                return (
                  <li
                    key={sla.id}
                    className="flex items-center justify-between gap-2 rounded-md border border-border-subtle p-2.5"
                  >
                    <div>
                      <p className="text-sm text-text-primary">{sla.cliente}</p>
                      <p className="text-xs text-text-muted">
                        {sla.indicador} — objetivo {sla.objetivo}, actual {sla.actual}
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

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-accent-cyan-strong" aria-hidden />
            <CardTitle>Reservas de servicio</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {data.reservas.map((res) => (
              <li
                key={res.id}
                className="flex flex-col gap-1 rounded-lg border border-border-subtle bg-bg-surface p-3"
              >
                <span className="text-sm font-medium text-text-primary">
                  {res.servicio}
                </span>
                <span className="text-xs text-text-secondary">{res.cliente}</span>
                <span className="text-xs text-text-muted">
                  {formatDateTime(res.fecha)}
                </span>
                <Badge
                  variant={res.estado === "confirmada" ? "success" : "warning"}
                  className="mt-1 w-fit"
                >
                  {res.estado === "confirmada" ? "Confirmada" : "Pendiente"}
                </Badge>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
