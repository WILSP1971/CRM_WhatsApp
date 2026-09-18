import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/** SPEC-020 — Cliente RAG real (SPEC-017/019): rutas exactas, `fetch` mockeado. */
describe("ragApi", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_API_BASE_URL", "http://localhost:9999/api/v1");
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.unstubAllEnvs();
  });

  it("createDraft llama a POST /rag/conversations/{id}/drafts con query y top_k", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "draft-1",
          citations: [{ source: "a" }, { source: "b" }, { source: "c" }],
        }),
        { status: 201, headers: { "content-type": "application/json" } },
      ),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { createDraft } = await import("@/lib/api/ragApi");
    await createDraft("conv-abc", { query: "¿Tienen stock?", topK: 3 });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "http://localhost:9999/api/v1/rag/conversations/conv-abc/drafts",
    );
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      query: "¿Tienen stock?",
      top_k: 3,
    });
  });

  it("approveDraft llama a POST /rag/conversations/{id}/drafts/{draftId}/approve", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ draft: {}, sent_message_id: "msg-1" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { approveDraft } = await import("@/lib/api/ragApi");
    await approveDraft("conv-abc", "draft-1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "http://localhost:9999/api/v1/rag/conversations/conv-abc/drafts/draft-1/approve",
    );
    expect(init.method).toBe("POST");
  });

  it("propaga 503 (modo degradado de IA local) como ApiError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "IA local no disponible" }), {
        status: 503,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { createDraft } = await import("@/lib/api/ragApi");
    await expect(createDraft("conv-abc", { query: "x" })).rejects.toMatchObject({
      status: 503,
    });
  });
});
