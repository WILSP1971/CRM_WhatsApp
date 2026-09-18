import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * SPEC-020 — Cliente HTTP tipado. Pruebas con `fetch` MOCKEADO (no requieren
 * backend vivo): verifican rutas, base URL configurable por env y manejo de
 * `Authorization`/errores. Ejecutable en CI sin red real.
 */
describe("apiFetch (cliente HTTP real)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_API_BASE_URL", "http://localhost:9999/api/v1");
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.unstubAllEnvs();
  });

  it("llama a la URL construida a partir de VITE_API_BASE_URL, sin auth si no hay token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { apiFetch } = await import("@/lib/api/httpClient");
    const result = await apiFetch<{ ok: boolean }>("/conversations");

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://localhost:9999/api/v1/conversations");
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("agrega el header Authorization: Bearer <token> cuando hay sesión activa", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { apiFetch } = await import("@/lib/api/httpClient");
    const { setAuthToken } = await import("@/lib/authStore");
    setAuthToken("token-de-prueba");

    await apiFetch("/auth/me");

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer token-de-prueba",
    );
  });

  it("serializa query params y omite los undefined", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { apiFetch } = await import("@/lib/api/httpClient");
    await apiFetch("/conversations", { query: { page: 1, page_size: undefined } });

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://localhost:9999/api/v1/conversations?page=1");
  });

  it("lanza ApiError con status y detail del backend en respuestas 4xx/5xx", async () => {
    const makeResponse = () =>
      new Response(JSON.stringify({ detail: "Credenciales inválidas" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      });
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(makeResponse()));
    global.fetch = fetchMock as unknown as typeof fetch;

    const { apiFetch, ApiError } = await import("@/lib/api/httpClient");

    await expect(apiFetch("/auth/me")).rejects.toMatchObject({
      status: 401,
      detail: "Credenciales inválidas",
    });
    await expect(apiFetch("/auth/me")).rejects.toBeInstanceOf(ApiError);
  });

  it("no intenta parsear JSON en respuestas 204 (No Content)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    global.fetch = fetchMock as unknown as typeof fetch;

    const { apiFetch } = await import("@/lib/api/httpClient");
    const result = await apiFetch("/conversations/abc/messages/xyz", {
      method: "DELETE",
    });
    expect(result).toBeUndefined();
  });
});
