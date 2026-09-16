# PROMPT OPTIMIZADO — Dashboard UI/UX "OmniCore AI" (CRM Inteligente Omnicanal)

> Autor: 🧠 XAVIER (Professor X) — Estratega de Prompts (Nivel 1)
> Fecha: 2026-09-16 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo` presente) — PROHIBIDO cualquier modelo/servicio externo.
> Estado: LISTO PARA DOCTOR STRANGE (SPEC) · Cumple CHECKPOINT C8 (prompt registrado en `prompt-lab/`).

---

## 0. Prompt inicial del Lead (transcripción íntegra — NO perder)

> Diseña una interfaz de panel (dashboard) de UI/UX moderna, fluida, elegante y de última generación para un sistema CRM inteligente omnicanal empresarial llamado "OmniCore AI".
>
> 1. **Sistema de diseño y estética:** jerarquía visual minimalista con modo oscuro/claro, glassmorphism, sombras suaves, esquinas redondeadas (12–16px). Paleta: fondo azul pizarra/marino profundo, acentos índigo eléctrico y cian para estados activos de IA, tarjetas gris claro neutro, indicadores de estado vivos (verde esmeralda, ámbar, coral). Tipografía SF Pro o Inter, WCAG AAA, escala tipográfica clara.
> 2. **Arquitectura/layout:** barra lateral plegable (bandeja unificada, contactos vista 360°, centro de llamadas con VoiceBot, centro de conocimiento RAG, sincronización ERP, flujos automatizados, análisis multisectoriales). Encabezado: búsqueda semántica global, widget estado VoiceBot, selector de inquilino/empresa, notificaciones, perfil.
> 3. **Módulos:** (a) Bandeja unificada omnicanal (WhatsApp Business API, Instagram DM, Messenger, WebChat) con etiquetas de sentimiento en tiempo real e iconos de canal; (b) Panel lateral RAG empresarial en vivo (bases vectoriales, citas, borradores de respuesta, sugerencias de producto); (c) VoiceBot y telefonía VoIP (webphone, visualizador de onda, transcripción voz-a-texto, grabación en vivo, detección de intención IA); (d) Panel dinámico por sector: Comercial/E-Commerce (embudo Kanban, seguimiento de pedidos, venta cruzada), Servicios/Consultoría (hitos de proyecto, horas facturables, SLA, reservas), Manufactura (órdenes de trabajo, alertas de inventario, sincronización ERP cadena de suministro).
> 4. **Salida visual:** maqueta UI de alta fidelidad, cuadrícula limpia, densidad de datos nítida, escritorio 1920x1080, diseño SaaS moderno.
>
> Fundamentos: omnicanalidad unificada y Social CRM; telefonía VoIP+VoiceBot interoperable con IP PBX; RAG empresarial con LLM (datos first-party); adaptabilidad multisectorial e integración back-office ERP; arquitectura microservicios/SaaS cloud escalable.

---

## 1. Ambigüedades detectadas y supuestos resueltos

Cada supuesto está **marcado** y es explícito. Los marcados con ⚠️ son críticos: si el Lead
no está de acuerdo, deben confirmarse ANTES de que DOCTOR STRANGE arme el PLAN.

| #   | Ambigüedad                                      | Supuesto adoptado (SUP-xx)                                                                                                                                                                                                                                                                                               | Criticidad |
| --- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------- |
| A1  | ¿Maqueta visual o sistema funcional?            | **SUP-01 ⚠️** El primer entregable es una **MAQUETA/PROTOTIPO de ALTA FIDELIDAD navegable** (front-end estático, datos simulados/mock, sin backend real ni integraciones vivas). NO es un sistema funcional.                                                                                                             | Crítica    |
| A2  | ¿Datos reales o simulados?                      | **SUP-02 ⚠️** Todos los datos son **ficticios/mock** generados localmente (fixtures JSON). No se conecta a WhatsApp/IG/Messenger/VoIP/ERP reales ni se procesan datos personales reales. Esto mantiene el proyecto seguro pese a ser SENSIBLE.                                                                           | Crítica    |
| A3  | ¿IA real (LLM/RAG/transcripción) en la maqueta? | **SUP-03 ⚠️** La IA (RAG, sentimiento, transcripción, intención) se representa **visualmente con datos pre-grabados**; NO se invoca ningún LLM ni servicio de IA. Cuando llegue la fase funcional, todo modelo será **local/self-hosted** (política `.no-externo`).                                                      | Crítica    |
| A4  | Alcance de módulos en la v1 de la maqueta       | **SUP-04** La maqueta cubre **las 4 áreas** (Bandeja, RAG, VoiceBot/VoIP, Panel por sector) en pantallas de alta fidelidad, pero el **Panel dinámico por sector** entrega **1 sector completo (Comercial/E-Commerce)** + los otros dos (Servicios, Manufactura) como vistas de referencia/placeholder de alta fidelidad. | Media      |
| A5  | Fuente tipográfica                              | **SUP-05** Se usa **Inter** (open source, self-host vía `@fontsource`), no SF Pro (licencia Apple restringida y no distribuible). Se conserva la jerarquía tipográfica pedida.                                                                                                                                           | Baja       |
| A6  | Responsive / breakpoints                        | **SUP-06** Diseño **desktop-first** optimizado para 1920x1080; se entregan breakpoints degradados legibles hasta 1280px. Tablet/móvil quedan fuera de la v1 (ver Out of scope).                                                                                                                                          | Media      |
| A7  | Modo oscuro/claro                               | **SUP-07** Se entregan **ambos temas** (oscuro por defecto + claro), conmutables con un toggle, compartiendo tokens de diseño.                                                                                                                                                                                           | Baja       |
| A8  | Idioma de la interfaz                           | **SUP-08** UI en **español (es-CO)** como idioma primario; textos centralizados para facilitar i18n futura.                                                                                                                                                                                                              | Baja       |
| A9  | Multi-tenant                                    | **SUP-09** El selector de inquilino/empresa es **visual** (cambia branding/nombre/mock), sin aislamiento de datos real (eso es fase backend).                                                                                                                                                                            | Baja       |
| A10 | Navegabilidad                                   | **SUP-10** Prototipo **navegable** (rutas entre módulos, estados hover/activo, paneles que abren/cierran), no solo imágenes estáticas.                                                                                                                                                                                   | Media      |

### Preguntas abiertas para el Lead (máx. 3)

1. ¿Confirmas **SUP-01** (maqueta de alta fidelidad navegable como primer entregable, sin backend)?
2. ¿Confirmas **SUP-02/SUP-03** (todo con datos mock, cero integraciones y cero IA real en esta fase)?
3. ¿El sector prioritario para desarrollar completo es **Comercial/E-Commerce** (SUP-04), o prefieres Servicios o Manufactura?

---

## 2. PROMPT PROFESIONAL (marco C.R.A.F.T.)

### 2.1 Objetivo (Acción — verbo único y medible)

**Diseñar y construir** una **maqueta de alta fidelidad, navegable y responsiva-desktop** del
dashboard del CRM omnicanal **"OmniCore AI"**, que sirva como referencia visual y de UX aprobable
por el Lead y como base para la posterior implementación funcional.

### 2.2 Rol (quién lo resuelve)

- **SPIDER-MAN** (UX/UI) lidera el diseño y el sistema de diseño.
- **DAREDEVIL** (frontend) implementa la maqueta.
- **WOLVERINE** (calidad) + **HAWKEYE** (pruebas) verifican accesibilidad, consistencia y criterios.
- **BLACK WIDOW** (seguridad) valida que NO haya datos reales, secretos ni llamadas externas.

### 2.3 Contexto

- Producto: CRM inteligente **omnicanal** empresarial multi-tenant, SaaS.
- Proyecto en: `/home/swarm/proyectos/CRM_WhatsApp` (ya creado).
- **Clasificación SENSIBLE** (`.no-externo`): datos personales, mensajería, grabaciones de voz, ERP.
  → PROHIBIDO cualquier modelo/servicio externo, CDN de terceros para datos, o telemetría externa.
- Fundamentos de producto: omnicanalidad unificada / Social CRM; VoIP + VoiceBot con IP-PBX;
  RAG empresarial con LLM sobre datos first-party; adaptabilidad multisectorial; integración ERP;
  arquitectura microservicios/SaaS cloud escalable. (Estos fundamentos guían la UX; la maqueta los
  **representa**, no los implementa.)

### 2.4 Alcance

**IN (incluido en esta v1 — la maqueta):**

1. **Sistema de diseño / Design tokens:** paleta (fondo azul pizarra/marino profundo, acentos
   índigo eléctrico + cian para IA activa, tarjetas gris claro neutro; estados verde esmeralda /
   ámbar / coral), tipografía Inter con escala definida, radios 12–16px, sombras suaves,
   glassmorphism, modo oscuro (default) + claro. Documentado como tokens reutilizables.
2. **Layout base:** barra lateral plegable + encabezado global (búsqueda semántica _simulada_,
   widget estado VoiceBot, selector de inquilino/empresa, notificaciones, perfil).
3. **Módulo A — Bandeja unificada omnicanal:** lista de conversaciones con iconos de canal
   (WhatsApp/IG/Messenger/WebChat), etiquetas de sentimiento (positivo/neutral/negativo) _mock_,
   vista de conversación, panel de contacto 360°.
4. **Módulo B — Panel lateral RAG en vivo (representación):** fuentes/citas, borrador de respuesta
   sugerido, sugerencias de producto — todo con contenido pre-cargado.
5. **Módulo C — VoiceBot / VoIP:** webphone, visualizador de onda (animación), transcripción
   voz-a-texto _pre-grabada_, indicador de grabación en vivo, chip de intención detectada.
6. **Módulo D — Panel dinámico por sector:** Comercial/E-Commerce **completo** (embudo Kanban,
   seguimiento de pedidos, venta cruzada); Servicios/Consultoría y Manufactura como **vistas de
   referencia** de alta fidelidad (SUP-04).
7. **Analítica multisectorial:** dashboard con KPIs, gráficos y densidad de datos nítida (mock).
8. **Ambos temas** (oscuro/claro) conmutables; navegación entre todos los módulos.
9. Entregable optimizado para **1920x1080**, degradación legible hasta **1280px**.

**OUT (fuera de esta v1):**

- Backend, API, base de datos, autenticación real, multi-tenant con aislamiento real.
- Integraciones reales (WhatsApp Business API, IG/Messenger, VoIP/IP-PBX, ERP).
- Cualquier IA/LLM/embeddings/transcripción real (se simula).
- Vistas móvil/tablet nativas (solo desktop + degradación básica).
- Persistencia, envío de mensajes real, grabación de audio real.

### 2.5 Requisitos funcionales (RF)

- **RF-01** El usuario navega entre los 6 espacios del sidebar sin recargar (SPA), con estado
  activo/hover visible.
- **RF-02** El sidebar se pliega/despliega y persiste su estado durante la sesión.
- **RF-03** Toggle de tema oscuro/claro aplica los tokens en toda la UI sin parpadeo.
- **RF-04** La bandeja omnicanal muestra, por conversación: canal, sentimiento, último mensaje,
  no-leídos y estado; al abrir una, se ve el hilo + panel 360° del contacto.
- **RF-05** El panel RAG muestra ≥3 citas con fuente, un borrador sugerido y ≥2 sugerencias de
  producto (mock), con acción visual "Insertar borrador".
- **RF-06** El webphone VoiceBot muestra estados (en llamada / en espera / colgado), onda animada,
  transcripción incremental _simulada_ y chip de intención.
- **RF-07** El panel por sector Comercial muestra un Kanban de embudo con tarjetas arrastrables
  (o al menos con estados visuales) + seguimiento de pedidos + módulo de venta cruzada.
- **RF-08** La búsqueda global despliega resultados _mock_ categorizados (contactos, conversaciones,
  documentos RAG).
- **RF-09** El selector de inquilino/empresa cambia el branding/nombre visible.
- **RF-10** Todos los datos provienen de **fixtures locales** (JSON), claramente ficticios.

### 2.6 Requisitos no funcionales (RNF)

- **RNF-01 Accesibilidad:** objetivo **WCAG 2.2 AAA** en contraste de texto (≥7:1 texto normal,
  ≥4.5:1 texto grande) en ambos temas; navegación por teclado completa; roles/labels ARIA; foco visible.
- **RNF-02 Rendimiento:** carga inicial < 2.5 s en desktop de referencia; interacciones < 100 ms;
  animaciones a 60 fps; Lighthouse (Performance y Accessibility) ≥ 90.
- **RNF-03 Responsive desktop:** correcto a 1920x1080; sin scroll horizontal ni solapamientos hasta 1280px.
- **RNF-04 Consistencia:** 100% de colores/espaciados/radios/tipografías provienen de design tokens
  (cero valores mágicos hardcodeados en componentes).
- **RNF-05 Mantenibilidad:** componentes reutilizables, tipados, y un componente = una responsabilidad.
- **RNF-06 Documentación:** README con cómo correr la maqueta + catálogo de componentes/tokens.

### 2.7 Restricciones (obligatorias)

- **R-01 SENSIBLE / `.no-externo`:** ningún modelo, API o servicio externo. Sin CDNs de datos, sin
  fuentes remotas (Inter **self-hosted**), sin analytics/telemetría de terceros. Verificable con
  `scripts/puede-modelo-externo.sh`.
- **R-02 Sin datos reales:** solo mocks ficticios; ningún PII real, ningún secreto/token en el repo
  (CHECKPOINT C3).
- **R-03 Alineación con enjambre:** el objetivo parte de este prompt registrado (C8); toda SPEC debe
  tener criterios verificables (C4); cambios sensibles requieren aprobación del Lead (C6).
- **R-04 Marca:** producto se muestra como "OmniCore AI"; no usar logotipos con copyright de terceros.

### 2.8 Formato de salida esperado

- Aplicación front-end (SPA) navegable ejecutable en local (`dev server`).
- Estructura: `src/` (componentes, páginas, tokens), `src/mocks/` (fixtures JSON), `README.md`.
- Capturas de referencia 1920x1080 de cada módulo, en oscuro y claro.
- Documento de design tokens (paleta, tipografía, spacing, radios, sombras).

### 2.9 Criterios de éxito (medibles y verificables — Tests)

| ID        | Criterio                                                                            | Cómo se verifica                                                                |
| --------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| **CE-01** | Los 6 módulos del sidebar están navegables en oscuro y claro sin errores de consola | Recorrido manual + revisión de consola (HAWKEYE)                                |
| **CE-02** | Contraste WCAG AAA (≥7:1 texto normal) en ambos temas                               | Auditoría axe / Lighthouse Accessibility ≥ 90 y checker de contraste            |
| **CE-03** | Lighthouse Performance ≥ 90 y carga < 2.5 s en 1920x1080                            | Reporte Lighthouse                                                              |
| **CE-04** | 100% de estilos derivan de design tokens; cero llamadas de red externas             | Grep de red/DevTools Network vacío de terceros + revisión de tokens (WOLVERINE) |
| **CE-05** | Cero PII real, cero secretos, `puede-modelo-externo.sh` no rompe la política        | Escaneo BLACK WIDOW + ejecución del script                                      |
| **CE-06** | Navegación completa por teclado con foco visible                                    | Prueba de teclado (HAWKEYE)                                                     |
| **CE-07** | Sin scroll horizontal ni solapamientos entre 1280px y 1920px                        | Prueba responsive                                                               |
| **CE-08** | Aprobación visual/UX explícita del Lead                                             | Revisión del Lead                                                               |

---

## 3. Stack tecnológico recomendado (maqueta de alta fidelidad)

| Capa             | Recomendación                                    | Justificación breve                                                                  |
| ---------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------ |
| Framework UI     | **React 18 + Vite + TypeScript**                 | Ecosistema maduro, HMR rápido, tipado seguro; ideal para SPA de alta fidelidad.      |
| Estilos          | **Tailwind CSS + CSS variables (design tokens)** | Tokens centralizados, temas oscuro/claro triviales, consistencia y velocidad.        |
| Componentes base | **shadcn/ui + Radix UI**                         | Accesibles por diseño (ARIA/teclado), personalizables, sin dependencia de servicios. |
| Iconos           | **lucide-react**                                 | Open source, ligero, coherente, self-host.                                           |
| Animación        | **Framer Motion**                                | Transiciones fluidas 60 fps (sidebar, paneles, onda de voz).                         |
| Gráficos         | **Recharts** (o visx)                            | KPIs/analítica multisectorial con buena densidad de datos.                           |
| Kanban / drag    | **dnd-kit**                                      | Accesible y ligero para el embudo Comercial.                                         |
| Tipografía       | **Inter self-hosted** (`@fontsource/inter`)      | Cumple R-01 (sin fuentes remotas); jerarquía pedida.                                 |
| Datos            | **Fixtures JSON locales** (opcional MSW)         | Mock 100% local, cero backend, cero llamadas externas.                               |
| Calidad          | **ESLint + Prettier + axe-core + Lighthouse CI** | Verifica CE-02/CE-03/CE-04 automáticamente.                                          |

> Alternativa si el Lead prefiere velocidad de maquetado puro: **HTML + CSS + Alpine.js**, pero se
> pierde el sistema de componentes reutilizable; **no recomendado** para un dashboard de esta densidad.

---

## 4. Alcance recomendado (entregable #1)

**Recomendación de XAVIER:** entregar primero la **MAQUETA DE ALTA FIDELIDAD NAVEGABLE** (SUP-01),
con datos mock y sin IA/integraciones reales. Es el mayor valor con el menor riesgo: permite validar
UX, sistema de diseño y flujos con el Lead **antes** de invertir en backend, integraciones VoIP/ERP
y modelos locales (que en un proyecto SENSIBLE exigen mucho más rigor). Una vez aprobada la maqueta,
DOCTOR STRANGE derivará las SPEC funcionales por módulo.

---

## 5. Siguiente paso en el flujo

Entregar este prompt a **🔮 DOCTOR STRANGE** para el **PLAN profesional** (`.swarm/PLAN-XXX.md`),
que el Lead deberá aprobar ("APROBADO PLAN-XXX") antes de generar SPECs. Cumple CHECKPOINT **C8**.
