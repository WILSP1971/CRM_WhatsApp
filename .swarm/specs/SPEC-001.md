# SPEC-001 — Scaffolding, tooling y estructura del proyecto

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: WOLVERINE, BLACK WIDOW, HAWKEYE · Prioridad: ALTA · Tipo: FUNDACIONAL · Fase: F0
- Deriva de: PLAN-001 (F0) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Crear la base técnica del proyecto: SPA React 18 + Vite + TypeScript con Tailwind,
lint/format, estructura de carpetas, fixtures JSON base y un script que verifique
"cero dependencias/llamadas externas", habilitando el resto de las SPECs de UI.

## Contexto

Sin F0 ninguna otra SPEC puede desarrollarse (dependencia dura). El proyecto es
SENSIBLE: toda la maqueta es visual, con datos mock, sin backend ni terceros.

## Alcance

### IN

- Proyecto Vite + React 18 + TypeScript (SPA) ejecutable en `dev server`.
- Tailwind CSS configurado (base para tokens de SPEC-002).
- ESLint + Prettier con reglas de proyecto y scripts npm (`dev`, `build`, `lint`, `format`, `check:externos`).
- Estructura de carpetas: `src/` (components, pages, layout, hooks, lib, styles), `src/mocks/` (fixtures JSON).
- Fixtures JSON base ficticios (semilla mínima: conversaciones, contactos, llamadas, KPIs).
- Script `scripts/check-externos` que detecta URLs/CDN/fuentes remotas y falla si existen.
- README base con instrucciones de ejecución.

### OUT

- Design tokens y temas (SPEC-002), layout/navegación (SPEC-003), módulos funcionales, CI (SPEC-010).

## Dependencias

- Ninguna (SPEC raíz). Prerrequisito duro de SPEC-002 a SPEC-010.

## Requisitos funcionales

- RF Proyecto arranca con `npm run dev` sin errores y muestra una página vacía/placeholder.
- RF `npm run build` genera bundle de producción sin errores.
- RF `npm run lint` corre ESLint y `npm run format` aplica Prettier.
- RF `npm run check:externos` termina en exit 0 cuando no hay referencias externas.

## Requisitos no funcionales

- TypeScript en modo estricto (`strict: true`).
- Cero valores mágicos previstos (preparado para tokens de SPEC-002).
- Sin secretos en el repo (C3); ningún `.env` con credenciales reales.

## Criterios de aceptación (verificables)

- [ ] `npm install && npm run dev` levanta la SPA en local sin errores de consola.
- [ ] `npm run build` finaliza con exit 0.
- [ ] `npm run lint` finaliza con exit 0 (cero errores).
- [ ] Existen `src/`, `src/mocks/` y al menos 4 fixtures JSON ficticios versionados.
- [ ] `scripts/check-externos` existe, es ejecutable y da exit 0 en el estado inicial.
- [ ] `tsconfig` con `strict: true`.

## Accesibilidad (WCAG 2.2 AAA)

- Base HTML con `lang="es-CO"`, `<title>` y landmark raíz preparados para navegación por teclado.
- No introduce barreras (sin contenido interactivo aún); prepara el terreno para foco visible.

## Restricción SENSIBLE

- Cero llamadas externas: sin CDNs, sin fuentes remotas, sin analytics/telemetría de terceros.
- Cero PII real: fixtures explícitamente ficticios y marcados como tales.
- `scripts/puede-modelo-externo.sh` debe respetar la política; `check:externos` la refuerza.

## Riesgos

- R-01 (fuga a externos): mitigado por `check:externos` y revisión BLACK WIDOW.
- R-07 (deriva de consistencia): lint estricto desde el inicio.

## Checkpoints aplicables

- C3 (sin secretos en texto plano), C4 (criterios verificables), C8 (origen en prompt registrado).
