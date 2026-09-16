import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Configuración de pruebas (SPEC-009 — HAWKEYE).
// Smoke tests de render + test de contraste de tokens. Corre 100% local,
// sin red ni navegador real (jsdom), acorde a la restricción SENSIBLE
// (.no-externo) del proyecto.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    css: false,
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
