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

  /** SPEC-070 (RF-01, ADR-014) — opt-in de audio ANTES de aprobar. */
  it("setRespuestaModo llama a PATCH .../drafts/{id}/respuesta-modo con el body correcto", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "draft-1", respuesta_modo: "audio" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { setRespuestaModo } = await import("@/lib/api/ragApi");
    await setRespuestaModo("conv-abc", "draft-1", "audio");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "http://localhost:9999/api/v1/rag/conversations/conv-abc/drafts/draft-1/respuesta-modo",
    );
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ respuesta_modo: "audio" });
  });

  /** SPEC-070 (RF-02, Q1-C) — "escuchar antes de enviar": encola bajo demanda. */
  it("requestDraftAudio llama a POST .../drafts/{id}/listen", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ draft_id: "draft-1", tts_estado: "generando" }), {
        status: 202,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { requestDraftAudio } = await import("@/lib/api/ragApi");
    const result = await requestDraftAudio("conv-abc", "draft-1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "http://localhost:9999/api/v1/rag/conversations/conv-abc/drafts/draft-1/listen",
    );
    expect(init.method).toBe("POST");
    expect(result).toEqual({ draft_id: "draft-1", tts_estado: "generando" });
  });

  it("fetchDraft llama a GET .../drafts/{id} (usado para el poll de tts_estado)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "draft-1", tts_estado: "listo" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { fetchDraft } = await import("@/lib/api/ragApi");
    await fetchDraft("conv-abc", "draft-1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "http://localhost:9999/api/v1/rag/conversations/conv-abc/drafts/draft-1",
    );
    expect(init.method ?? "GET").toBe("GET");
  });

  /**
   * SPEC-070 — fetch autenticado del binario de audio (mismo patrón que
   * `fetchCallAudioObjectUrl`, SPEC-040): header Authorization manual (no
   * `apiFetch`, JSON-only), `Blob` -> Object URL.
   */
  it("fetchDraftAudioObjectUrl agrega Authorization y devuelve una Object URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Blob(["clip"], { type: "audio/ogg" }), {
        status: 200,
        headers: { "content-type": "audio/ogg" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;
    const createObjectURLMock = vi.fn().mockReturnValue("blob:mock-audio-url");
    vi.stubGlobal("URL", { ...URL, createObjectURL: createObjectURLMock, revokeObjectURL: vi.fn() });

    const { setAuthToken } = await import("@/lib/authStore");
    setAuthToken("token-de-prueba");
    const { fetchDraftAudioObjectUrl } = await import("@/lib/api/ragApi");

    const result = await fetchDraftAudioObjectUrl("conv-abc", "draft-1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "http://localhost:9999/api/v1/rag/conversations/conv-abc/drafts/draft-1/audio",
    );
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer token-de-prueba",
    );
    expect(result).toBe("blob:mock-audio-url");
    vi.unstubAllGlobals();
  });

  it("fetchDraftAudioObjectUrl devuelve null en 404 (sin clip listo)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 404 }));
    global.fetch = fetchMock as unknown as typeof fetch;

    const { fetchDraftAudioObjectUrl } = await import("@/lib/api/ragApi");
    const result = await fetchDraftAudioObjectUrl("conv-abc", "draft-1");

    expect(result).toBeNull();
  });
});
