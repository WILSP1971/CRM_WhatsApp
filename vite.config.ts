import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// OmniCore AI — maqueta SPA. Proyecto SENSIBLE (.no-externo):
// sin proxies a servicios externos, sin variables de entorno con secretos.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "localhost",
    port: 5173,
  },
});
