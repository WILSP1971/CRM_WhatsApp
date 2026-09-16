# ADR-002 — Glassmorphism compatible con WCAG AAA (contraste ≥ 7:1)

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-001.md` (riesgo R-02, CE-02), `prompt-lab/PROMPT-OPTIMIZADO.md` (RNF-01)

- **Estado:** Aceptada
- **Fecha:** 2026-09-16

---

## Contexto

El sistema de diseño de "OmniCore AI" pide **glassmorphism** (superficies translúcidas con blur,
sombras suaves, esquinas 12–16px) como parte de la estética minimalista de última generación.

Al mismo tiempo, el objetivo de accesibilidad es **WCAG 2.2 AAA**: contraste de texto **≥ 7:1**
para texto normal (≥ 4.5:1 para texto grande) en **ambos temas** (oscuro y claro) — RNF-01 / CE-02.

Existe una tensión directa, formalizada como **riesgo R-02** en `PLAN-001.md`:

> Las transparencias/blur reducen el contraste efectivo del texto por debajo de 7:1, porque el
> color de fondo real bajo el vidrio depende de lo que haya detrás (contenido variable), haciendo
> el contraste **impredecible** y frecuentemente insuficiente para AAA.

Se necesita una decisión que **conserve el efecto glass** sin sacrificar el cumplimiento AAA, y que
sea **verificable** de forma objetiva.

---

## Decisión

Se adopta un **glassmorphism con base sólida garantizada**:

1. **Capa de fondo sólida mínima bajo el vidrio:** todo panel/tarjeta glass que contenga texto
   lleva, debajo de la capa translúcida, una **capa de color sólido** (token de superficie) con
   opacidad suficiente para que el color **efectivo** de fondo sea determinista y conocido.
2. **Contraste calculado sobre el color efectivo:** el contraste ≥ 7:1 se calcula contra ese color
   sólido resultante (no contra la transparencia), garantizando AAA independientemente del contenido
   que haya detrás del vidrio.
3. **Blur limitado:** se acota el `backdrop-filter: blur()` a un rango moderado (apoya también el
   performance, riesgo R-04) — el blur es decorativo, no la base de contraste.
4. **Tokens dedicados:** el efecto glass se expresa mediante design tokens (superficie sólida base +
   capa translúcida + borde + sombra), nunca con valores hardcodeados (RNF-04 / CE-04).
5. **Auditoría por tema:** se audita con **axe** y checker de contraste en tema **claro y oscuro**;
   si algún estado no alcanza 7:1, se aumenta la opacidad de la capa sólida (fallback) hasta cumplir.

---

## Alternativas consideradas

| Alternativa                                          | Por qué se descartó                                                                                                                                                                                                                                                         |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Sin glassmorphism (superficies 100% opacas)**      | Cumple AAA trivialmente pero renuncia a la estética "última generación" solicitada por el Lead. Innecesario: se puede tener glass Y AAA con base sólida.                                                                                                                    |
| **Glass solo decorativo, sin texto encima**          | Válido para bordes/overlays sin contenido, pero demasiado restrictivo: buena parte de tarjetas, panel RAG y bandeja necesitan texto sobre superficies glass. Se adopta como sub-regla (glass puramente decorativo puede tener menos base sólida), no como solución general. |
| **Contraste medido "a ojo" / sin base determinista** | No verificable ni reproducible; el contraste dependería del contenido detrás del vidrio, incumpliendo AAA de forma intermitente.                                                                                                                                            |
| **Blur alto sin base sólida**                        | Degrada contraste (AAA) y performance (R-04) sin garantía; descartado.                                                                                                                                                                                                      |

---

## Consecuencias

**Pros**

- Se conserva la estética glassmorphism pedida **y** se garantiza WCAG AAA (≥ 7:1) de forma
  determinista en ambos temas.
- El contraste es **predecible y auditable** (calculado sobre color sólido efectivo).
- El blur limitado favorece también el rendimiento (apoya CE-03 / riesgo R-04).
- Todo queda expresado en tokens → consistencia y "cero hardcode" (RNF-04 / CE-04).

**Cons / mitigaciones**

- El efecto glass es algo **menos translúcido** que un vidrio puro (por la base sólida mínima) →
  se ajusta finamente la opacidad para maximizar el efecto sin bajar de 7:1.
- Requiere una **doble auditoría** (tema claro y oscuro) → integrada en axe/Lighthouse en F7 (CE-02).
- Los estados hover/activo/seleccionado también deben verificarse → incluidos en el set de pruebas.

**Criterio de verificación (objetivo y verificable)**

- Todo texto sobre superficie glass alcanza **contraste ≥ 7:1** (texto normal) y **≥ 4.5:1**
  (texto grande) medido contra el **color sólido efectivo** de la superficie, en **tema claro y
  oscuro**.
- **axe-core sin violaciones de contraste** por tema; **Lighthouse Accessibility ≥ 90** (CE-02).
- `backdrop-filter: blur()` dentro del rango acotado definido por los tokens.
- Verificación por HAWKEYE (recorrido) y WOLVERINE (revisión de tokens) en F7; barrido en F1/F7.

---

## Referencias

- `PLAN-001.md` — riesgo **R-02** (glassmorphism vs AAA), criterio **CE-02**, fase F1/F7.
- `prompt-lab/PROMPT-OPTIMIZADO.md` — RNF-01 (accesibilidad AAA), sección 1 (estética/glass).
- Relacionado: **ADR-001** (stack: Tailwind + CSS variables como soporte de estos tokens).
