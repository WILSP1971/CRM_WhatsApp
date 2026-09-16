import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// OmniCore AI — maqueta SPA. Proyecto SENSIBLE (.no-externo):
// sin proxies a servicios externos, sin variables de entorno con secretos.

/**
 * Plugin LOCAL (sin dependencias externas) que inlinea el/los CSS de entrada
 * en el <head> del HTML final, eliminando el <link rel="stylesheet">
 * render-blocking. El CSS de entrada de este proyecto es pequeño
 * (~25KB / ~6KB gzip): inlinearlo COMPLETO evita el bloqueo de render sin
 * riesgo de FOUC (a diferencia del patrón media="print" + onload, que sí
 * puede provocar un flash de estilos sin aplicar).
 *
 * Solo actúa en build (`apply: 'build'`) y después de que Vite ya inyectó
 * sus propios tags (`enforce: 'post'`), para poder localizar los <link>
 * de CSS generados y reemplazarlos por <style> equivalentes.
 */
function inlineCssPlugin(): Plugin {
  return {
    name: "inline-css-in-head",
    enforce: "post",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(html, ctx) {
        const bundle = ctx.bundle;
        if (!bundle) return html;

        // Mapa fileName -> contenido CSS, para todos los assets CSS emitidos.
        const cssByFileName = new Map<string, string>();
        for (const [fileName, chunk] of Object.entries(bundle)) {
          if (chunk.type === "asset" && fileName.endsWith(".css")) {
            const source = chunk.source;
            cssByFileName.set(
              fileName,
              typeof source === "string" ? source : Buffer.from(source).toString("utf-8"),
            );
          }
        }
        if (cssByFileName.size === 0) return html;

        // Reemplaza cada <link rel="stylesheet" ... href="/assets/xxx.css">
        // (preservando el orden en que aparecen en el HTML) por <style>.
        const linkRegex =
          /<link[^>]*rel=["']stylesheet["'][^>]*href=["']([^"']+)["'][^>]*>/gi;

        const usedFileNames = new Set<string>();
        const newHtml = html.replace(linkRegex, (fullMatch, href: string) => {
          const fileName = href.replace(/^\//, "");
          const css = cssByFileName.get(fileName);
          if (css === undefined) return fullMatch;
          usedFileNames.add(fileName);
          return `<style>${css}</style>`;
        });

        // El asset CSS ya está inline en el HTML: se elimina del bundle para
        // no emitir un .css duplicado y sin referencias.
        for (const fileName of usedFileNames) {
          delete bundle[fileName];
        }

        return newHtml;
      },
    },
  };
}

export default defineConfig({
  plugins: [react(), inlineCssPlugin()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "localhost",
    port: 5173,
  },
  build: {
    target: "es2020",
    cssCodeSplit: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules")) {
            if (
              id.includes("node_modules/react/") ||
              id.includes("node_modules/react-dom/") ||
              id.includes("node_modules/react-router-dom/") ||
              id.includes("node_modules/react-router/") ||
              id.includes("node_modules/scheduler/")
            ) {
              return "vendor-react";
            }
            if (
              id.includes("node_modules/@radix-ui/") ||
              id.includes("node_modules/lucide-react/") ||
              id.includes("node_modules/clsx/") ||
              id.includes("node_modules/class-variance-authority/") ||
              id.includes("node_modules/tailwind-merge/")
            ) {
              return "vendor-ui";
            }
          }
          return undefined;
        },
      },
    },
  },
});
