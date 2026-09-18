/**
 * Almacén del token JWT en memoria de proceso (SPEC-020).
 *
 * CHECKPOINT C3 (sin secretos en el bundle / sin secretos en claro): el
 * token NUNCA se hardcodea ni se embebe en el bundle; se obtiene en tiempo
 * de ejecución llamando a `POST /auth/login` (SPEC-013) y se conserva solo
 * en memoria de JS (variable de módulo). No se persiste en `localStorage`
 * ni `document.cookie` para reducir superficie de robo por XSS; como
 * contrapartida, se pierde al recargar la página (aceptable para este
 * slice: el login se repite en cada sesión de pestaña).
 *
 * Este módulo NO hace ninguna llamada de red por sí mismo: solo guarda/lee
 * el valor que le pase `apiClient`/quien invoque `login()`.
 */

let currentToken: string | null = null;

export function getAuthToken(): string | null {
  return currentToken;
}

export function setAuthToken(token: string | null): void {
  currentToken = token;
}

export function clearAuthToken(): void {
  currentToken = null;
}
