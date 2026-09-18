/**
 * Configuración de entorno de la SPA (SPEC-020).
 *
 * Único punto de lectura de `import.meta.env` para el feature-flag y las
 * URLs del backend. Con `VITE_USE_REAL_API` apagado (por defecto), NINGÚN
 * otro módulo de `src/` hace una llamada de red: todo sigue viniendo de los
 * fixtures mock (Entregable #1 intacto).
 *
 * CHECKPOINT C3 (sin secretos en el bundle): estas variables son SOLO
 * configuración de endpoint (URLs), nunca credenciales. El token JWT se
 * obtiene en tiempo de ejecución vía `POST /auth/login` (ver `authStore.ts`)
 * y no se embebe aquí.
 *
 * Restricción SENSIBLE (.no-externo): los defaults SOLO apuntan a localhost.
 * `npm run check:externos` audita que no haya dominios de terceros
 * hardcodeados en el código fuente.
 */

function readBooleanFlag(value: string | undefined): boolean {
  return value === "true" || value === "1";
}

/** Feature-flag global (SPEC-020). Default OFF: maqueta 100% mock. */
export const USE_REAL_API: boolean = readBooleanFlag(
  import.meta.env.VITE_USE_REAL_API as string | undefined,
);

/** Base de la API REST (`/api/v1/...`, SPEC-014). Solo se usa si el flag está ON. */
export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://localhost:8000/api/v1";

/** Base del WebSocket del WebChat (SPEC-015). Solo se usa si el flag está ON. */
export const WS_BASE_URL: string =
  (import.meta.env.VITE_WS_BASE_URL as string | undefined) ??
  "ws://localhost:8000/api/v1";
