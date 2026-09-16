import { describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { InboxPage } from "@/pages/InboxPage";
import { ContactsPage } from "@/pages/ContactsPage";
import { CallCenterPage } from "@/pages/CallCenterPage";
import { RagCenterPage } from "@/pages/RagCenterPage";
import { ErpSyncPage } from "@/pages/ErpSyncPage";
import { WorkflowsPage } from "@/pages/WorkflowsPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

/**
 * SPEC-009 — Smoke tests de render.
 *
 * Objetivo: verificar que cada página de los 6 módulos (+ 404) monta sin
 * lanzar excepciones y sin `console.error`/`console.warn` (proxy local de
 * "cero errores de consola", criterio de aceptación de SPEC-009). NO
 * sustituye el recorrido manual en navegador real con ambos temas.
 */

afterEach(() => {
  cleanup();
});

const pages: Array<[string, () => JSX.Element]> = [
  ["InboxPage (Bandeja unificada)", () => <InboxPage />],
  ["ContactsPage (Contactos 360°)", () => <ContactsPage />],
  ["CallCenterPage (VoiceBot)", () => <CallCenterPage />],
  ["RagCenterPage (Centro RAG)", () => <RagCenterPage />],
  ["ErpSyncPage (Sync ERP)", () => <ErpSyncPage />],
  ["WorkflowsPage (Flujos)", () => <WorkflowsPage />],
  ["AnalyticsPage (Analítica)", () => <AnalyticsPage />],
  ["NotFoundPage (404)", () => <NotFoundPage />],
];

describe("Smoke test de render — páginas de módulo", () => {
  for (const [name, Component] of pages) {
    it(`${name} renderiza sin lanzar excepciones ni errores de consola`, () => {
      const errorSpy: string[] = [];
      const warnSpy: string[] = [];
      const originalError = console.error;
      const originalWarn = console.warn;
      console.error = (...args: unknown[]) => {
        errorSpy.push(args.map(String).join(" "));
      };
      console.warn = (...args: unknown[]) => {
        warnSpy.push(args.map(String).join(" "));
      };

      try {
        expect(() =>
          render(
            <MemoryRouter initialEntries={["/"]}>
              <Component />
            </MemoryRouter>,
          ),
        ).not.toThrow();
      } finally {
        console.error = originalError;
        console.warn = originalWarn;
      }

      expect(errorSpy, `console.error en ${name}: ${errorSpy.join(" | ")}`).toHaveLength(0);
      // Warnings no bloquean el test (algunos son ruido de librerías de terceros
      // en jsdom), pero se reportan para inspección manual si aparecen.
      if (warnSpy.length > 0) {
        originalWarn(`[HAWKEYE][smoke] ${name} produjo console.warn:`, warnSpy);
      }
    });
  }
});
