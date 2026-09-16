# ADR-001 — Elección del stack tecnológico de la maqueta "OmniCore AI"

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-001.md` (F0–F8), `prompt-lab/PROMPT-OPTIMIZADO.md` (sección 3)

- **Estado:** Aceptada
- **Fecha:** 2026-09-16

---

## Contexto

El entregable #1 es una **maqueta de alta fidelidad, navegable (SPA), desktop-first** del
dashboard del CRM omnicanal "OmniCore AI", con **datos 100% mock (fixtures JSON)**, sin backend,
sin integraciones reales y con la IA **representada visualmente** (SUP-01/02/03).

La maqueta debe cumplir criterios exigentes y verificables:

- Densidad de datos alta (6 módulos, Kanban, gráficos, onda de voz, transcripción incremental).
- **WCAG 2.2 AAA** en contraste (≥7:1 texto normal) en tema oscuro y claro (RNF-01 / CE-02).
- **Lighthouse Performance y Accessibility ≥ 90**, carga < 2.5 s a 1920x1080 (RNF-02 / CE-03).
- **100% de estilos desde design tokens**, cero valores mágicos (RNF-04 / CE-04).
- Componentes reutilizables, tipados y accesibles por teclado (RNF-05 / CE-06).

**Restricción dominante (R-01 / riesgo R-01):** el proyecto es **SENSIBLE** (`.no-externo`). Está
**prohibido** cualquier modelo, API, servicio, CDN de datos, fuente remota o telemetría de
terceros **en tiempo de ejecución**. La política se verifica con
`scripts/puede-modelo-externo.sh` y con inspección de red (DevTools Network sin terceros).

Se requiere elegir un stack que maximice velocidad de maquetado y calidad (accesibilidad,
performance, consistencia) **sin introducir dependencias externas en runtime**.

---

## Decisión

Se adopta el siguiente stack para la maqueta:

| Capa               | Elección                                          | Rol                                                              |
| ------------------ | ------------------------------------------------- | ---------------------------------------------------------------- |
| Framework UI       | **React 18 + Vite + TypeScript**                  | SPA de alta fidelidad, HMR, tipado seguro                        |
| Estilos            | **Tailwind CSS + design tokens en CSS variables** | Tokens centralizados, temas oscuro/claro, cero hardcode (RNF-04) |
| Primitivas         | **Radix UI + shadcn/ui**                          | Componentes accesibles (ARIA/teclado) sin servicios externos     |
| Iconos             | **lucide-react** (self-host)                      | Set coherente, ligero, local                                     |
| Animación          | **Framer Motion**                                 | Transiciones 60 fps (sidebar, paneles, onda de voz)              |
| Gráficos           | **Recharts**                                      | KPIs y analítica multisectorial                                  |
| Kanban / drag&drop | **dnd-kit**                                       | Embudo Comercial accesible (fallback teclado)                    |
| Tipografía         | **Inter self-hosted** (`@fontsource/inter`)       | Jerarquía pedida sin fuente remota (R-01/R-03)                   |
| Datos              | **Fixtures JSON locales**                         | Mock 100% local, cero backend, cero red externa                  |
| Calidad / CI       | **ESLint + Prettier + axe-core + Lighthouse CI**  | Verifica CE-02/CE-03/CE-04 de forma automática                   |

Todas las dependencias se instalan y **empaquetan en build-time**; en runtime la aplicación no
resuelve ni descarga recursos de terceros (fuentes, iconos, datos y assets son locales).

---

## Alternativas consideradas

| Alternativa                                     | Por qué se descartó                                                                                                                                                                                                                                           |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Next.js**                                     | Orientado a SSR/servidor y fetch de datos; introduce runtime de servidor y patrones de red que exceden una maqueta estática mock y añaden superficie para llamadas externas. Vite SPA es más simple y directo para el objetivo.                               |
| **Vue 3 / Nuxt**                                | Ecosistema válido, pero el enjambre y las primitivas accesibles seleccionadas (Radix/shadcn) están consolidadas en React; menor fricción y mayor catálogo de componentes accesibles.                                                                          |
| **Angular**                                     | Peso y curva de arranque mayores para una maqueta; menos ágil para iterar UX de alta fidelidad.                                                                                                                                                               |
| **MUI (Material UI)**                           | Sistema de diseño opinado que choca con la estética propia (glassmorphism, paleta índigo/cian) y con "100% tokens propios"; más difícil de tematizar a AAA sin luchar contra sus estilos. Radix+shadcn deja el estilo totalmente en manos de nuestros tokens. |
| **Chart.js**                                    | Canvas-based, menos accesible y menos componible con React que Recharts (SVG declarativo, integrable con tokens).                                                                                                                                             |
| **HTML + CSS + Alpine.js**                      | Rápido para prototipo, pero se pierde el sistema de componentes reutilizable y tipado necesario para la densidad de este dashboard (descartado ya en el prompt optimizado).                                                                                   |
| **Fuente SF Pro**                               | Licencia Apple restringida y no distribuible (riesgo R-03). Se usa **Inter (OFL)** self-hosted.                                                                                                                                                               |
| **Fuentes/iconos vía CDN (Google Fonts, etc.)** | Viola R-01 (`.no-externo`): recurso remoto en runtime. Todo self-host.                                                                                                                                                                                        |

---

## Consecuencias

**Pros**

- Cumple la restricción SENSIBLE: **cero recursos externos en runtime**; todo es build-time y local.
- Radix/shadcn dan accesibilidad (ARIA + teclado) de base, facilitando CE-02 y CE-06.
- Tailwind + CSS variables permiten temas oscuro/claro y "cero hardcode" (RNF-04 / CE-04).
- Vite ofrece build rápido y code-splitting, apoyando la meta de performance (CE-03).
- Stack ampliamente conocido → mantenibilidad y velocidad de iteración (RNF-05).

**Cons / mitigaciones**

- Framer Motion + blur + onda animada pueden degradar performance (riesgo R-04) → animaciones
  GPU-friendly, blur limitado, lazy-loading de gráficos, medición en F7 (CE-03).
- shadcn/ui copia componentes al repo (no es dependencia versionada) → se documentan en el catálogo
  de componentes y quedan bajo revisión de WOLVERINE.
- dnd-kit requiere cuidado de accesibilidad por teclado en el Kanban (riesgo R-08) → fallback de
  estados por teclado y prueba de HAWKEYE.
- Recharts (SVG) puede ser costoso con muchos puntos → datasets mock acotados y memoización.

**Cumplimiento de la restricción SENSIBLE (`.no-externo`)**

- Fuentes (Inter), iconos (lucide), datos (fixtures JSON) y assets: **100% locales**.
- Sin CDN de datos, sin analytics/telemetría de terceros, sin fuentes remotas, sin IA/LLM real.
- Verificación: `scripts/puede-modelo-externo.sh` (exit 0) + DevTools Network sin terceros
  (CE-04/CE-05, barrido de BLACK WIDOW en F8).

---

## Referencias

- `PLAN-001.md` — Fases F0–F8, riesgos R-01/R-03/R-04/R-08, criterios CE-02..CE-05.
- `prompt-lab/PROMPT-OPTIMIZADO.md` — sección 3 (stack) y 2.7 (restricciones R-01..R-04).
- Relacionado: **ADR-002** (glassmorphism vs WCAG AAA).
