import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/** SPEC-020 — Login real (SPEC-013): guarda el token en `authStore` tras éxito. */
describe("authApi.login", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_API_BASE_URL", "http://localhost:9999/api/v1");
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.unstubAllEnvs();
  });

  it("llama a POST /auth/login sin Authorization y guarda el access_token", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            access_token: "jwt-123",
            token_type: "bearer",
            expires_in: 1800,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { login } = await import("@/lib/api/authApi");
    const { getAuthToken } = await import("@/lib/authStore");

    const result = await login({
      tenant_slug: "demo",
      email: "agente@demo.local",
      password: "secreto",
    });

    expect(result.access_token).toBe("jwt-123");
    expect(getAuthToken()).toBe("jwt-123");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://localhost:9999/api/v1/auth/login");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
    expect(JSON.parse(init.body as string)).toEqual({
      tenant_slug: "demo",
      email: "agente@demo.local",
      password: "secreto",
    });
  });

  it("propaga ApiError en credenciales inválidas sin tocar el authStore", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Credenciales inválidas" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { login } = await import("@/lib/api/authApi");
    const { getAuthToken } = await import("@/lib/authStore");

    await expect(
      login({ tenant_slug: "demo", email: "x@x.com", password: "mala" }),
    ).rejects.toMatchObject({ status: 401 });
    expect(getAuthToken()).toBeNull();
  });
});
