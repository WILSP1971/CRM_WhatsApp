/**
 * Cliente de autenticación real (SPEC-013) — SPEC-020.
 *
 * `login()` es la ÚNICA vía por la que la SPA obtiene un JWT: nunca hay un
 * token hardcodeado en el bundle (C3). El resultado se guarda en
 * `authStore` (memoria de proceso) para que `httpClient`/`wsClient` lo usen.
 */

import { apiFetch } from "@/lib/api/httpClient";
import type { LoginRequestBody, LoginResponseBody } from "@/lib/api/backendTypes";
import { setAuthToken, clearAuthToken } from "@/lib/authStore";

export async function login(credentials: LoginRequestBody): Promise<LoginResponseBody> {
  const result = await apiFetch<LoginResponseBody>("/auth/login", {
    method: "POST",
    body: credentials,
    skipAuth: true,
  });
  setAuthToken(result.access_token);
  return result;
}

export async function logout(): Promise<void> {
  try {
    await apiFetch<void>("/auth/logout", { method: "POST" });
  } finally {
    clearAuthToken();
  }
}
