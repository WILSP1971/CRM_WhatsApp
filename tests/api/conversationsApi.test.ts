import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * SPEC-020 — Cliente de conversaciones/mensajes reales (SPEC-014). Verifica
 * que se llaman las rutas EXACTAS del backend, con `fetch` mockeado.
 */
describe("conversationsApi", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_API_BASE_URL", "http://localhost:9999/api/v1");
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.unstubAllEnvs();
  });

  it("fetchConversations llama a GET /conversations con paginación", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 50 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { fetchConversations } = await import("@/lib/api/conversationsApi");
    await fetchConversations({ pageSize: 50 });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://localhost:9999/api/v1/conversations?page_size=50");
    expect(init.method ?? "GET").toBe("GET");
  });

  it("fetchMessages llama a GET /conversations/{id}/messages", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 100 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { fetchMessages } = await import("@/lib/api/conversationsApi");
    await fetchMessages("conv-abc", { pageSize: 100 });

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "http://localhost:9999/api/v1/conversations/conv-abc/messages?page_size=100",
    );
  });

  it("sendMessage llama a POST /conversations/{id}/messages con el payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "msg-1" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { sendMessage } = await import("@/lib/api/conversationsApi");
    await sendMessage("conv-abc", { remitente: "agente", contenido: "Hola" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "http://localhost:9999/api/v1/conversations/conv-abc/messages",
    );
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      remitente: "agente",
      contenido: "Hola",
    });
  });
});
