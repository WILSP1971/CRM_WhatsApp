/**
 * Sesión de desarrollo para el modo `VITE_USE_REAL_API=true` (SPEC-020).
 *
 * El Entregable #1 no tiene pantalla de login (fuera de alcance de esta
 * SPEC: "Nuevas pantallas/UX no existentes en el Entregable #1" está en
 * OUT). Para poder ejercitar la Bandeja/RAG reales sin añadir UI nueva, la
 * capa de datos hace un login "de desarrollo" transparente usando
 * credenciales configurables por env (`VITE_DEV_TENANT_SLUG`/
 * `VITE_DEV_USER_EMAIL`/`VITE_DEV_USER_PASSWORD`), documentado en
 * `.env.example`.
 *
 * CHECKPOINT C3: ninguna credencial se hardcodea aquí; si no están
 * configuradas, `ensureDevSession()` falla explícitamente (no hay fallback
 * silencioso a un usuario "adivinado"). Un despliegue real de la SPA con el
 * flag ON reemplazaría este módulo por un flujo de login de UI (fuera de
 * alcance de SPEC-020, ver notas del runbook).
 */

import { login } from "@/lib/api/authApi";
import { getAuthToken } from "@/lib/authStore";

let sessionPromise: Promise<void> | null = null;

function readDevCredentials() {
  const tenantSlug = import.meta.env.VITE_DEV_TENANT_SLUG as string | undefined;
  const email = import.meta.env.VITE_DEV_USER_EMAIL as string | undefined;
  const password = import.meta.env.VITE_DEV_USER_PASSWORD as string | undefined;
  if (!tenantSlug || !email || !password) {
    throw new Error(
      "VITE_USE_REAL_API=true requiere VITE_DEV_TENANT_SLUG, VITE_DEV_USER_EMAIL " +
        "y VITE_DEV_USER_PASSWORD (ver .env.example) para autenticarse contra " +
        "el backend real.",
    );
  }
  return { tenant_slug: tenantSlug, email, password };
}

/** Garantiza un token válido en `authStore` antes de llamar a la API real. */
export function ensureDevSession(): Promise<void> {
  if (getAuthToken()) return Promise.resolve();
  if (!sessionPromise) {
    sessionPromise = login(readDevCredentials())
      .then(() => undefined)
      .catch((err) => {
        sessionPromise = null;
        throw err;
      });
  }
  return sessionPromise;
}
