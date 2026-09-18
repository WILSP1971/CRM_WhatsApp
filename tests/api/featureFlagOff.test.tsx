import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

/**
 * SPEC-020 — Criterio CENTRAL (sensible, Entregable #1): con
 * `VITE_USE_REAL_API` apagado (default), la SPA no debe hacer NINGUNA
 * llamada de red al montar la Bandeja (InboxPage) — ni `fetch` ni
 * `WebSocket`. Se verifica con espías globales, no solo leyendo el flag.
 */
describe("Feature-flag OFF — cero llamadas de red", () => {
  const originalFetch = global.fetch;
  const originalWebSocket = global.WebSocket;

  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_USE_REAL_API", "false");
  });

  afterEach(() => {
    cleanup();
    global.fetch = originalFetch;
    global.WebSocket = originalWebSocket;
    vi.unstubAllEnvs();
  });

  it("InboxPage no llama a fetch ni abre WebSocket con el flag apagado", async () => {
    const fetchSpy = vi.fn();
    const wsSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;
    // @ts-expect-error -- espía simple para detectar cualquier intento de conexión
    global.WebSocket = wsSpy;

    const { InboxPage } = await import("@/pages/InboxPage");

    render(
      <MemoryRouter initialEntries={["/"]}>
        <InboxPage />
      </MemoryRouter>,
    );

    expect(await screen.findByLabelText(/Hilo de conversación/i)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(wsSpy).not.toHaveBeenCalled();
  });
});
