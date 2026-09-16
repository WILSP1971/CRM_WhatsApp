# OmniCore AI — Maqueta de alta fidelidad (CRM omnicanal)

Maqueta SPA de alta fidelidad y navegable del dashboard "OmniCore AI", construida con
**React 18 + Vite + TypeScript + Tailwind CSS**. Todos los datos son **mock** (fixtures
JSON ficticios en `src/mocks/`); no hay backend, ni integraciones reales, ni IA/LLM real.

> Proyecto **SENSIBLE** (`.no-externo`): prohibido cualquier CDN, fuente remota,
> telemetría o llamada de red en tiempo de ejecución. Ver `scripts/check-externos.sh`.

## Requisitos

- Node.js 20+
- npm 10+

## Ejecución

```bash
npm install
npm run dev       # servidor de desarrollo (http://localhost:5173)
npm run build     # build de producción (tsc -b && vite build)
npm run preview   # sirve el build de producción localmente
```

## Scripts

```bash
npm run dev             # Servidor de desarrollo (http://localhost:5173)
npm run build           # Build de producción: tsc -b && vite build
npm run preview         # Sirve el build de producción localmente
npm run lint            # ESLint (incluye reglas jsx-a11y, sin console.error)
npm run format          # Prettier (escribe)
npm run format:check    # Prettier (solo verifica)
npm run test            # Vitest: contraste WCAG AAA (32 tests) + smoke-render
npm run check:externos  # Verifica cero URLs http(s) externas en código
```

## Calidad y verificación

- **Lint sin errores** (ESLint + jsx-a11y).
- **Tests vitest: 32/32** (contraste WCAG AAA de tokens + smoke-render de las 8 páginas).
- **Cero URLs externas** en runtime (`check:externos` ✓).
- **Accesibilidad AAA** verificada: contraste ≥7:1, motion-reduce, roles ARIA, foco visible.
- **Lighthouse CI** en pipeline (GitHub Actions): Accessibility ≥90, Performance ≥90.

## Módulos (6 espacios omnicanal)

1. **Bandeja unificada** — Conversaciones, llamadas, mensajes en un feed único (SPEC-004).
2. **Contactos 360°** — Ficha completa con histórico de interacciones (SPEC-004).
3. **Centro RAG** — Búsqueda semántica + documentos (SPEC-005, representación).
4. **VoiceBot** — Integración VoIP + transcripción simulada (SPEC-006, representación).
5. **Sync ERP** — Sincronización de datos con sistemas externos (SPEC-008).
6. **Flujos automatizados** — Reglas y automatización de conversaciones (SPEC-008).
7. **Analítica multisectorial** — Dashboard de KPIs por sector (SPEC-008).

Todos los datos son **100% mock** (fixtures JSON en `src/mocks/`). Ningún módulo realiza llamadas
externas. Tema claro/oscuro con toggle en el menú de perfil (header).

## Sensibilidad del proyecto

Proyecto clasificado **SENSIBLE** (`.no-externo`):
- Cero CDN, cero telemetría, cero recurso externo en runtime.
- Datos ficticios; sin PII real, sin backend real, sin IA/LLM real.
- Tipografía Inter self-hosted vía `@font-face` (fallback `system-ui` si `.woff2` no se
  agregó localmente; ver `public/fonts/README.md`).
- Verificación: `npm run check:externos` (exit 0 = verde, script `scripts/check-externos.sh`).
- Build CI: nunca descarga dependencias externas en runtime ni en tiempo de compilación.

## Estructura del proyecto

```
src/
  components/ui/    Primitivas accesibles: Button, Card, Badge, Input, Tabs, Tooltip
  layout/            Sidebar, Header, TenantSwitcher, NotificationsCenter, UserMenu...
  pages/             Páginas de cada módulo (placeholder hasta sus SPECs funcionales)
  routes/            AppRouter (react-router-dom)
  hooks/             Hooks compartidos (p. ej. estado del sidebar)
  lib/               Utilidades: theme, cn, tipos, navegación, búsqueda mock
  mocks/             Fixtures JSON ficticias (contactos, conversaciones, llamadas, KPIs...)
  styles/            tokens.css (design tokens), fonts.css (Inter self-hosted), globals.css
public/
  fonts/             Aquí se copian los .woff2 de Inter (ver public/fonts/README.md)
scripts/
  check-externos.sh  Verificación "cero llamadas externas"
```

## Sistema de diseño (resumen — SPEC-002)

Los tokens viven como CSS variables en `src/styles/tokens.css` y se exponen a Tailwind
en `tailwind.config.ts` (cero color/spacing/radio hardcodeado en componentes).

- **Paleta:** fondo azul marino/pizarra profundo, acentos índigo eléctrico y cian
  (estados de IA), tarjetas gris claro/neutro, estados esmeralda/ámbar/coral.
- **Tipografía:** Inter, self-hosted vía `@font-face` en `src/styles/fonts.css`
  (fallback a `system-ui` si los `.woff2` locales aún no se agregaron; ver
  `public/fonts/README.md`). Prohibido Google Fonts / CDN.
- **Radios:** 12–16px (`--radius-md` a `--radius-xl`).
- **Sombras:** suaves, para profundidad sutil (`--shadow-sm/md/lg`).
- **Glassmorphism:** clase utilitaria `.glass-surface` — SIEMPRE con una capa de fondo
  casi opaca (`--surface-glass-solid`) detrás del `backdrop-filter: blur(...)`, para
  garantizar contraste WCAG AAA (≥7:1) incluso bajo el vidrio (checkpoint R-02).
- **Temas:** oscuro (por defecto) y claro, alternables con el toggle del menú de
  perfil (header). Persisten en `localStorage` y se aplican antes del primer paint
  (script inline en `index.html`) para evitar parpadeo (FOUC).
- **Primitivas UI:** `Button`, `Card`, `Badge`, `Input`, `Tabs`, `Tooltip` en
  `src/components/ui/`, construidas sobre Radix UI (dependencia de build local, sin
  llamadas de red en runtime), con foco visible y roles ARIA.

## Layout y navegación (resumen — SPEC-003)

- Sidebar plegable (persistente durante la sesión) con los 7 espacios: Bandeja
  unificada, Contactos 360°, Centro de llamadas VoiceBot, Centro RAG, Sync ERP,
  Flujos automatizados y Analítica multisectorial.
- Header con búsqueda semántica simulada (categorías: Contactos, Conversaciones,
  Documentos RAG), widget de estado del VoiceBot, selector de inquilino/empresa,
  centro de notificaciones y menú de perfil (incluye el toggle de tema).
- Routing SPA con `react-router-dom`; cada módulo aún no implementado muestra una
  página de marcador de posición que indica en qué SPEC se desarrollará.

## Próximos pasos (fuera de alcance de SPEC-001/002/003)

- SPEC-004: Bandeja unificada omnicanal (lista, hilo, contacto 360°).
- SPEC-005: Panel lateral RAG en vivo.
- SPEC-006: VoiceBot / VoIP (webphone, onda, transcripción simulada).
- SPEC-007/008: Panel por sector (Comercial completo + referencias) y analítica.
- SPEC-009: Accesibilidad AAA, performance y QA.
- SPEC-010: Repo, CI y documentación final (incluye despliegue, a cargo de QUICKSILVER).
