import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "@/layout/AppLayout";
import { InboxPage } from "@/pages/InboxPage";
import { ContactsPage } from "@/pages/ContactsPage";
import { CallCenterPage } from "@/pages/CallCenterPage";
import { RagCenterPage } from "@/pages/RagCenterPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

// Páginas con gráficos Recharts/dnd-kit (SPEC-007/008): lazy-load para
// performance (R-04 del PLAN-001), el bundle de charts solo se descarga
// al entrar a estas rutas.
const ErpSyncPage = lazy(() =>
  import("@/pages/ErpSyncPage").then((m) => ({ default: m.ErpSyncPage })),
);
const WorkflowsPage = lazy(() =>
  import("@/pages/WorkflowsPage").then((m) => ({ default: m.WorkflowsPage })),
);
const AnalyticsPage = lazy(() =>
  import("@/pages/AnalyticsPage").then((m) => ({ default: m.AnalyticsPage })),
);

function SectorPageFallback() {
  return (
    <p role="status" className="text-sm text-text-secondary">
      Cargando panel del sector…
    </p>
  );
}

/** Router SPA (SPEC-003): navegación entre módulos sin recargar. */
export function AppRouter() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/bandeja" replace />} />
        <Route path="/bandeja" element={<InboxPage />} />
        <Route path="/contactos" element={<ContactsPage />} />
        <Route path="/llamadas" element={<CallCenterPage />} />
        <Route path="/rag" element={<RagCenterPage />} />
        <Route
          path="/erp"
          element={
            <Suspense fallback={<SectorPageFallback />}>
              <ErpSyncPage />
            </Suspense>
          }
        />
        <Route
          path="/flujos"
          element={
            <Suspense fallback={<SectorPageFallback />}>
              <WorkflowsPage />
            </Suspense>
          }
        />
        <Route
          path="/analitica"
          element={
            <Suspense fallback={<SectorPageFallback />}>
              <AnalyticsPage />
            </Suspense>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
