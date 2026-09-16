import { Factory, RefreshCw } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { ManufacturingSectorView } from "@/components/sectors/ManufacturingSectorView";
import { ServicesSectorView } from "@/components/sectors/ServicesSectorView";
import manufacturingData from "@/mocks/manufacturing.json";
import servicesData from "@/mocks/services.json";
import type { ManufacturingData, ServicesData } from "@/lib/sectorTypes";

const manufacturing = manufacturingData as ManufacturingData;
const services = servicesData as ServicesData;

/**
 * Sectores de referencia (SPEC-008): Manufactura y Servicios/Consultoría,
 * navegables mediante un selector modular (Tabs) — vistas de alta fidelidad,
 * no completas como Comercial (SPEC-007). Datos 100% mock.
 */
export function ErpSyncPage() {
  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-center gap-3">
        <div
          className="bg-accent-indigo/15 flex h-10 w-10 items-center justify-center rounded-lg text-accent-indigo-strong"
          aria-hidden
        >
          <RefreshCw className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-text-primary">
            Sectores de referencia
          </h1>
          <p className="text-sm text-text-secondary">
            Manufactura y Servicios/Consultoría (vistas de referencia, datos ficticios).
          </p>
        </div>
      </header>

      <Tabs defaultValue="manufactura">
        <TabsList aria-label="Selector de sector de referencia">
          <TabsTrigger value="manufactura">
            <Factory className="mr-1.5 h-4 w-4" aria-hidden />
            Manufactura
          </TabsTrigger>
          <TabsTrigger value="servicios">Servicios / Consultoría</TabsTrigger>
        </TabsList>
        <TabsContent value="manufactura">
          <ManufacturingSectorView data={manufacturing} />
          <p className="mt-4 text-xs text-text-muted">{manufacturing.notaFicticia}</p>
        </TabsContent>
        <TabsContent value="servicios">
          <ServicesSectorView data={services} />
          <p className="mt-4 text-xs text-text-muted">{services.notaFicticia}</p>
        </TabsContent>
      </Tabs>
    </div>
  );
}
