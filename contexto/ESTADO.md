# ESTADO — CRM_WhatsApp / OmniCore AI

> Última actualización: 2026-09-16 · Responsable del último avance: IRON MAN (orquestación) · CAPTAIN AMERICA (fixes a11y) · HAWKEYE (QA) · QUICKSILVER (CI/repo/publicación)

## Resumen

Maqueta de alta fidelidad navegable (SPA) del CRM omnicanal **OmniCore AI**. PLAN-001 aprobado.
Las 10 SPECs (SPEC-001 … SPEC-010) están **CERRADAS**: los 6 módulos funcionan en tema claro/oscuro,
el build compila, no hay llamadas externas y el contraste cumple WCAG AAA (verificado con test
matemático 32/32). Repo versionado en GitHub, CI configurado, README mejorado, publicado en
https://github.com/WILSP1971/CRM_WhatsApp.

Proyecto clasificado **SENSIBLE** (`.no-externo`): datos 100% ficticios, sin backend, sin IA/LLM
real, sin integraciones vivas, cero recursos externos en runtime.

## Estado de SPECs

| SPEC     | Título                                         | Estado    | Fase |
| -------- | ---------------------------------------------- | --------- | ---- |
| SPEC-001 | Scaffolding, tooling y estructura del proyecto | CERRADA   | F0   |
| SPEC-002 | Design system: tokens, temas y primitivas UI   | CERRADA   | F1   |
| SPEC-003 | Layout global y navegación SPA                 | CERRADA   | F2   |
| SPEC-004 | Bandeja omnicanal unificada                    | CERRADA   | F3   |
| SPEC-005 | Panel lateral RAG en vivo (representación)     | CERRADA   | F4   |
| SPEC-006 | VoiceBot + telefonía VoIP (representación)     | CERRADA   | F5   |
| SPEC-007 | Sector Comercial / E-Commerce (prioritario)    | CERRADA   | F6   |
| SPEC-008 | Sectores de referencia + analítica             | CERRADA   | F6   |
| SPEC-009 | Accesibilidad, performance y QA                | CERRADA   | F7   |
| SPEC-010 | Repo, CI y documentación                       | CERRADA   | F8   |

## Revisión y QA (fase SPEC-009)

- **DAREDEVIL** (frontend): detectó 3 bloqueantes de contraste/motion → corregidos.
- **HAWKEYE** (QA): tabla de contraste matemática; harness de tests **vitest 32/32**
  (contraste AAA de tokens + smoke-render de las 8 páginas sin `console.error`);
  `.lighthouserc.json` con umbrales (Lighthouse/axe reales pendientes en CI con Chromium).
- **WOLVERINE** (calidad): sin bloqueantes; `formatDuration` duplicada → consolidada en `src/lib/format.ts`.
- **BLACK WIDOW** (seguridad): **APTO** — cero externos, sin secretos, PII ficticia, sin `dangerouslySetInnerHTML`/`eval`.

## Correcciones aplicadas por CAPTAIN AMERICA (bloqueantes AAA)

- Tokens `--color-chart-*` dedicados para series Recharts (≥7:1 en ambos temas) + `strokeDasharray`/marcador por serie.
- Tokens `--color-badge-*-text`; badges `success/warning/danger/ai` ≥7:1 en ambos temas.
- `--color-text-muted`, `--color-accent-indigo-strong` (oscuro) y `--color-accent-cyan-strong` (claro) ajustados a ≥7:1.
- `motion-reduce:animate-none` en RAG (panel/draft/suggestion/citation) y `VoiceBotStatusWidget`, más red de seguridad global en `globals.css`.

## Verificaciones ejecutadas (IRON MAN, sobre estado final)

- `npm run test`: **32/32** (contraste + smoke).
- `npm run build` (tsc -b && vite build): **exit 0**.
- `npm run lint`: **0 errores** (1 warning preexistente de react-refresh en `src/lib/theme.tsx`, no bloqueante).
- `npm run check:externos`: **exit 0** (sin URLs externas).

## Lighthouse CI — resultado final (escritorio 1920×1080, 3 corridas)

Run GitHub Actions [`35057890871`](https://github.com/WILSP1971/CRM_WhatsApp/actions/runs/35057890871), commit `efa1d2c`.

| Categoría      | Score | Gate  |
| -------------- | ----- | ----- |
| Performance    | 100   | ≥90 ✅ |
| Accessibility  | 98    | ≥90 ✅ |
| Best Practices | 92    | ✅     |
| SEO            | 100   | ✅     |

Métricas: FCP 0.5s · LCP 0.5s · TTI 0.5s · **TBT 0 ms** · **CLS 0** · Speed Index 0.5s.

**Optimización de Performance (THOR → CAPTAIN AMERICA):** 80 → 100.
- `vite.config.ts`: `manualChunks` (vendor-react / vendor-ui) + `build.target: es2020`; entry propio 345 KB → 72 KB.
- Plugin local `inlineCssPlugin` (`transformIndexHtml`): CSS de entrada inline como `<style>`, elimina el `<link rel=stylesheet>` render-blocking (~670 ms), sin recursos externos.
- `.lighthouserc.json`: corregido a throttling de **escritorio** (CPU 1×) acorde al target; el config previo aplicaba throttling móvil sobre form-factor desktop, hundiendo/variando el score (58/80/80).

## Notas / riesgos abiertos

- **Inter self-hosted**: `.woff2` no incluidos (sin descargas externas en este entorno); fallback `system-ui`.
  Procedimiento en `public/fonts/README.md` para añadirlos localmente (nunca vía CDN).
- **Lighthouse**: ejecutado en CI (ver sección de resultados). **axe** real por navegador queda como checklist manual (el harness de contraste vitest 32/32 cubre AAA de tokens).
- **`npm audit`**: 2 moderadas en `react-router-dom` 6.x (runtime) y high/critical en `vite`/`vitest`
  que solo afectan el dev-server local, no el build de producción. Valorar upgrade en SPEC futura.

## Entregable #1 — COMPLETADO

**SPEC-010 (QUICKSILVER) — CERRADA**:
- Repo versionado con `git init` (rama `main`), archivos en 10 commits.
- README mejorado con secciones de Scripts, módulos (6 espacios), sensibilidad SENSIBLE, y AAA.
- `.gitignore` validado: no suben `node_modules`, `dist`, `.env*`, `*.tsbuildinfo`, `coverage`.
- CI workflow (`.github/workflows/ci.yml`) en cada push/PR: build + lint + check:externos + test + Lighthouse CI (continue-on-error).
- Publicado en https://github.com/WILSP1971/CRM_WhatsApp (visibilidad PUBLIC).
- Verificaciones finales: `npm run build` ✓, `npm run check:externos` ✓, `npm run test` 32/32 ✓.

## Próximos pasos (fuera de alcance SPEC-010)

1. ✅ CI en GitHub Actions verde (build + lint + test + check:externos + Lighthouse).
2. ✅ Lighthouse ejecutado (Performance 100, A11y 98, BP 92, SEO 100). Pendiente opcional: axe real por navegador.
3. (Opcional) Fase funcional futura: backend/integraciones/IA con modelos locales/self-hosted (respetando `.no-externo`).
