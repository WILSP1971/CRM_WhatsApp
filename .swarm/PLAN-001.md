# PLAN-001 — Maqueta de alta fidelidad "OmniCore AI" (Entregable #1)

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Fecha: 2026-09-16 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo` presente) — PROHIBIDO cualquier modelo/servicio externo.
> Origen: `prompt-lab/PROMPT-OPTIMIZADO.md` (🧠 XAVIER) · Estado: **PROPUESTA** (espera "APROBADO PLAN-001")
> Regla de oro: este PLAN NO genera SPECs. Las SPECs se crean SOLO tras la aprobación del Lead.

---

## 1. Objetivo y contexto

### Objetivo

Diseñar y construir una **maqueta de alta fidelidad, navegable (SPA) y desktop-first** del
dashboard del CRM omnicanal **"OmniCore AI"**, con **datos 100% mock (fixtures JSON)**, sin
backend, sin integraciones reales y sin IA/LLM real (la IA se **representa visualmente**). La
maqueta sirve como referencia visual/UX aprobable por el Lead y como base para la posterior
implementación funcional.

### Contexto

- Producto: CRM inteligente **omnicanal** multi-tenant, SaaS (WhatsApp/Instagram/Messenger/WebChat,
  VoiceBot + VoIP, RAG empresarial, ERP multisectorial).
- Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`, clasificado **SENSIBLE** (`.no-externo`).
- La seguridad se preserva porque el entregable #1 **no procesa datos reales ni contacta terceros**:
  todo es visual y ficticio. Verificable con `scripts/puede-modelo-externo.sh`.
- Supuestos vinculantes heredados de XAVIER: SUP-01..SUP-10 (maqueta navegable, mock, IA simulada,
  Inter self-hosted, desktop-first 1920x1080 con degradación a 1280px, ambos temas, es-CO,
  sector prioritario **Comercial/E-Commerce**).

---

## 2. Alcance

### IN (entra en el entregable #1)

1. **Sistema de diseño / design tokens:** paleta (azul marino/pizarra profundo, índigo eléctrico,
   cian de IA, gris neutro, estados esmeralda/ámbar/coral), tipografía **Inter self-hosted**, escala
   tipográfica, spacing, radios 12–16px, sombras suaves, glassmorphism, **modo oscuro (default) + claro**.
2. **Layout base:** sidebar plegable + header global (búsqueda semántica simulada, widget estado
   VoiceBot, selector de inquilino, notificaciones, perfil). Navegación SPA entre módulos.
3. **Módulo A — Bandeja unificada omnicanal:** lista de conversaciones con iconos de canal, etiquetas
   de sentimiento mock, vista de hilo, panel de contacto 360°.
4. **Módulo B — Panel lateral RAG en vivo (representación):** citas/fuentes, borrador sugerido,
   sugerencias de producto, acción visual "Insertar borrador".
5. **Módulo C — VoiceBot / VoIP:** webphone, visualizador de onda animado, transcripción simulada
   incremental, indicador de grabación, chip de intención detectada.
6. **Módulo D — Panel dinámico por sector:** **Comercial/E-Commerce completo** (embudo Kanban,
   seguimiento de pedidos, venta cruzada) + **Servicios/Consultoría** y **Manufactura** como vistas
   de referencia de alta fidelidad (placeholder navegable).
7. **Analítica multisectorial:** dashboard con KPIs y gráficos (mock, densidad de datos nítida).
8. **Ambos temas** conmutables sin parpadeo; navegación completa por teclado con foco visible.
9. Optimizado para **1920x1080**, degradación legible hasta **1280px**.
10. **Repo + tooling + CI de calidad** (lint, axe, Lighthouse) + **README/docs de tokens y componentes**.

### OUT (NO entra en el entregable #1)

- Backend, API, base de datos, autenticación real, multi-tenant con aislamiento real.
- Integraciones reales (WhatsApp Business API, IG/Messenger, VoIP/IP-PBX, ERP).
- Cualquier IA/LLM/embeddings/transcripción real (todo simulado con datos pre-grabados).
- Vistas nativas móvil/tablet (solo desktop + degradación básica a 1280px).
- Persistencia, envío de mensajes real, grabación de audio real, telemetría.
- i18n completo (solo textos centralizados en es-CO, sin catálogo de idiomas adicional).

---

## 3. Fases y entregables por fase

| Fase   | Nombre                           | Entregables clave                                                                                                                                                                                               |
| ------ | -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **F0** | Scaffolding + tooling            | Proyecto Vite+React18+TS; ESLint/Prettier; Tailwind; estructura `src/` y `src/mocks/`; `.no-externo` respetado; scripts npm; `README` base.                                                                     |
| **F1** | Design system + tokens + temas   | Design tokens (CSS variables) paleta/tipografía/spacing/radios/sombras; Inter self-hosted; temas oscuro/claro; primitivos glassmorphism; documento de tokens; catálogo base de componentes (shadcn/ui + Radix). |
| **F2** | Layout + navegación              | Sidebar plegable persistente; header global (búsqueda simulada, estado VoiceBot, selector inquilino, notificaciones, perfil); router SPA; estados hover/activo; toggle de tema.                                 |
| **F3** | Bandeja unificada omnicanal      | Lista de conversaciones (canal/sentimiento/no-leídos/estado); vista de hilo; panel de contacto 360°; fixtures de conversaciones.                                                                                |
| **F4** | Panel lateral RAG                | Panel en vivo: ≥3 citas con fuente, borrador sugerido, ≥2 sugerencias de producto; acción "Insertar borrador"; fixtures RAG.                                                                                    |
| **F5** | VoiceBot / VoIP                  | Webphone con estados; onda animada; transcripción incremental simulada; indicador de grabación; chip de intención; fixtures de llamada.                                                                         |
| **F6** | Panel por sector                 | Comercial completo (Kanban dnd-kit, pedidos, venta cruzada) + Servicios y Manufactura de referencia; analítica multisectorial (Recharts).                                                                       |
| **F7** | Accesibilidad + performance + QA | Auditoría WCAG AAA (contraste ≥7:1), teclado/foco, axe; Lighthouse Perf/A11y ≥90; carga <2.5s; sin scroll horizontal 1280–1920; capturas oscuro/claro por módulo.                                               |
| **F8** | Repo / CI / docs                 | CI de calidad (lint+axe+Lighthouse); verificación `puede-modelo-externo.sh`; README de ejecución + catálogo de componentes/tokens; barrido BLACK WIDOW (sin PII/secretos).                                      |

---

## 4. Dependencias entre fases

- **F0** habilita todo (base técnica). Ninguna fase de UI arranca sin F0.
- **F1** depende de F0 y es **prerequisito duro** de F2–F6 (todo componente usa tokens; sin tokens no
  hay consistencia RNF-04 ni cumplimiento de contraste RNF-01).
- **F2** depende de F1; es **prerequisito** de F3–F6 (todos los módulos viven dentro del layout/router).
- **F3, F4, F5, F6** dependen de F2 y pueden desarrollarse en **paralelo** entre sí una vez cerrado el
  layout. Nota: F4 (RAG) se acopla visualmente a F3 (bandeja), por lo que conviene F3 antes o junto a F4.
- **F7** depende de que F1–F6 estén completas (audita el conjunto).
- **F8** transversal: se prepara en F0 (CI base) y se cierra tras F7 (docs/capturas finales + barrido seguridad).

Ruta crítica: **F0 → F1 → F2 → {F3→F4, F5, F6} → F7 → F8**.

---

## 5. Riesgos y mitigaciones

| #        | Riesgo                                                                                                | Impacto                        | Mitigación                                                                                                                                                                 |
| -------- | ----------------------------------------------------------------------------------------------------- | ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R-01** | **SENSIBLE / sin externos:** fuga a CDN, fuente remota, telemetría o servicio de terceros.            | Alto (rompe política SENSIBLE) | Inter **self-hosted** (`@fontsource`); iconos/lib locales; sin analytics; CI que ejecuta `puede-modelo-externo.sh` y verifica DevTools Network sin terceros (CE-04/CE-05). |
| **R-02** | **Glassmorphism vs WCAG AAA:** transparencias/blur reducen contraste bajo 7:1.                        | Alto (choca CE-02)             | Tokens con **capa de fondo sólida mínima** bajo el vidrio; contraste calculado sobre el color efectivo; auditoría axe por tema; fallback de opacidad si no alcanza 7:1.    |
| **R-03** | **Licencias de fuentes:** SF Pro no es distribuible.                                                  | Medio (legal)                  | Adoptar **Inter (OFL)** self-hosted (SUP-05); prohibido empaquetar SF Pro.                                                                                                 |
| **R-04** | **Performance con animaciones** (Framer Motion, onda, blur) puede bajar Lighthouse <90 y carga >2.5s. | Medio (CE-03)                  | Animaciones GPU-friendly; blur limitado; code-splitting por módulo; lazy de gráficos; medir en F7.                                                                         |
| **R-05** | **Datos mock que parezcan PII real** (nombres/teléfonos reales por accidente).                        | Medio (CE-05)                  | Fixtures explícitamente ficticios y marcados; barrido BLACK WIDOW; sin secretos/tokens en repo (C3).                                                                       |
| **R-06** | **Alcance del panel por sector** se expande (3 sectores completos).                                   | Medio (cronograma)             | SUP-04: solo Comercial completo; Servicios/Manufactura como referencia navegable.                                                                                          |
| **R-07** | **Deriva de consistencia** (valores mágicos fuera de tokens).                                         | Medio (CE-04/RNF-04)           | Lint de tokens/revisión WOLVERINE; regla "cero hardcode" de color/spacing/radio.                                                                                           |
| **R-08** | **Accesibilidad de Kanban drag-and-drop** (dnd-kit) por teclado.                                      | Bajo/Medio (CE-06)             | dnd-kit accesible + fallback de estados por teclado; prueba HAWKEYE.                                                                                                       |

**Top-3:** R-01 (sin externos/SENSIBLE), R-02 (glassmorphism vs AAA), R-04 (performance de animaciones).

---

## 6. Criterios de éxito verificables (mapeo con CE de XAVIER)

| ID        | Criterio                                                                  | Verificación                               | Fase     |
| --------- | ------------------------------------------------------------------------- | ------------------------------------------ | -------- |
| **CE-01** | 6 módulos navegables en oscuro y claro sin errores de consola             | Recorrido + consola (HAWKEYE)              | F2–F6/F7 |
| **CE-02** | Contraste WCAG AAA ≥7:1 (texto normal) en ambos temas                     | axe / Lighthouse A11y ≥90 + checker        | F1/F7    |
| **CE-03** | Lighthouse Performance ≥90 y carga <2.5s a 1920x1080                      | Reporte Lighthouse                         | F7       |
| **CE-04** | 100% estilos desde design tokens; cero llamadas de red externas           | Grep/DevTools Network + revisión WOLVERINE | F1/F8    |
| **CE-05** | Cero PII real, cero secretos; `puede-modelo-externo.sh` no rompe política | Escaneo BLACK WIDOW + script               | F8       |
| **CE-06** | Navegación completa por teclado con foco visible                          | Prueba de teclado (HAWKEYE)                | F7       |
| **CE-07** | Sin scroll horizontal ni solapamientos entre 1280px y 1920px              | Prueba responsive                          | F7       |
| **CE-08** | Aprobación visual/UX explícita del Lead                                   | Revisión del Lead                          | F7/F8    |

---

## 7. Mapa preliminar de SPECs propuestas (SOLO el mapa — NO son las specs)

> Se crearán únicamente tras "APROBADO PLAN-001". Cada SPEC llevará criterios verificables (C4).

- **SPEC-001** — Scaffolding, tooling y estructura del proyecto (F0): Vite+React18+TS, lint/prettier, `src/` y mocks, política sin externos.
- **SPEC-002** — Design system: design tokens, temas oscuro/claro, glassmorphism y tipografía Inter self-hosted (F1).
- **SPEC-003** — Layout y navegación: sidebar plegable, header global y router SPA con toggle de tema (F2).
- **SPEC-004** — Bandeja unificada omnicanal: lista, hilo, sentimiento y contacto 360° (F3).
- **SPEC-005** — Panel lateral RAG en vivo: citas, borrador e insertar, sugerencias de producto (F4).
- **SPEC-006** — VoiceBot / VoIP: webphone, onda, transcripción simulada, grabación e intención (F5).
- **SPEC-007** — Panel por sector Comercial/E-Commerce: Kanban, pedidos, venta cruzada (F6, prioritario).
- **SPEC-008** — Sectores de referencia (Servicios y Manufactura) + analítica multisectorial (F6).
- **SPEC-009** — Accesibilidad WCAG AAA, performance y QA (contraste, teclado, Lighthouse) (F7).
- **SPEC-010** — Repo/CI/docs: pipeline de calidad, verificación sin externos, README y catálogo (F8).

---

## 8. Entregables finales del entregable #1

- SPA navegable ejecutable en local (`dev server`) con los 6 módulos.
- Sistema de diseño documentado (tokens: paleta, tipografía, spacing, radios, sombras) + catálogo de componentes.
- Fixtures JSON ficticios en `src/mocks/`.
- Capturas 1920x1080 de cada módulo en oscuro y claro.
- README de ejecución + documentación de tokens/componentes.
- Reportes de Lighthouse y axe; evidencia de barrido de seguridad (sin PII/secretos/externos).

## 9. Definition of Done (entregable #1)

1. CE-01..CE-08 cumplidos y evidenciados.
2. `scripts/puede-modelo-externo.sh` respeta la política SENSIBLE (sin externos) y DevTools Network sin terceros.
3. Cero errores de consola en recorrido completo de los 6 módulos, ambos temas.
4. Lighthouse Performance ≥90 y Accessibility ≥90; carga <2.5s a 1920x1080.
5. Contraste ≥7:1 (texto normal) verificado en oscuro y claro; navegación por teclado con foco visible.
6. 100% de estilos desde design tokens (cero hardcode de color/spacing/radio).
7. Sin PII real ni secretos en el repo; fixtures explícitamente ficticios.
8. README + catálogo de tokens/componentes + capturas entregados.
9. **Aprobación explícita del Lead** (CE-08). Ninguna SPEC se cierra sin cumplir los CHECKPOINTS aplicables.
