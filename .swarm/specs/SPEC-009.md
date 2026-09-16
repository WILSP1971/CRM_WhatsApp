# SPEC-009 — Accesibilidad, performance y QA

- Estado: PROPUESTA · Responsable: HAWKEYE · Colaboran: WOLVERINE, BLACK WIDOW, THOR, DAREDEVIL · Prioridad: ALTA · Tipo: CALIDAD · Fase: F7
- Deriva de: PLAN-001 (F7) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Auditar y certificar el conjunto: contraste WCAG AAA ≥7:1 en ambos temas, navegación por
teclado con foco visible, Lighthouse Accessibility ≥90 y Performance ≥90, carga <2.5s a
1920x1080, auditoría axe y cero errores de consola.

## Contexto

Fase transversal de calidad; depende de que SPEC-001 a SPEC-008 estén completas. Valida los
criterios de éxito CE-01, CE-02, CE-03, CE-06 y CE-07 del PLAN.

## Alcance

### IN

- Auditoría de contraste AAA ≥7:1 (texto normal) en tema claro y oscuro.
- Verificación de navegación por teclado completa y foco visible en los 6 módulos.
- Ejecución de axe-core (sin violaciones críticas/serias).
- Lighthouse: Accessibility ≥90 y Performance ≥90; carga <2.5s a 1920x1080.
- Verificación de ausencia de errores de consola en recorrido completo, ambos temas.
- Verificación responsive 1280–1920 (sin scroll horizontal ni solapamientos).

### OUT

- Nuevas funcionalidades de módulo; deploy (SPEC-010).

## Dependencias

- Depende de SPEC-001 a SPEC-008 (audita el conjunto).

## Requisitos funcionales

- RF Reporte de contraste por tema, reporte axe, reporte Lighthouse, evidencia de recorrido por teclado.
- RF Capturas 1920x1080 de cada módulo en oscuro y claro.

## Requisitos no funcionales

- RNF-01 (AAA), RNF-02 (Lighthouse ≥90, carga <2.5s), RNF-03 (responsive).

## Criterios de aceptación (verificables)

- [ ] Contraste ≥7:1 (texto normal) verificado en ambos temas en los 6 módulos.
- [ ] Recorrido completo por teclado con foco visible; sin trampas de foco.
- [ ] axe-core sin violaciones críticas ni serias.
- [ ] Lighthouse Accessibility ≥90 y Performance ≥90; carga <2.5s a 1920x1080.
- [ ] Cero errores de consola en el recorrido de los 6 módulos, ambos temas.
- [ ] Sin scroll horizontal ni solapamientos entre 1280px y 1920px.
- [ ] Capturas por módulo (oscuro/claro) entregadas.

## Accesibilidad (WCAG 2.2 AAA)

- Esta SPEC es la garante de AAA: verifica contraste, teclado, foco, ARIA, `prefers-reduced-motion`.

## Restricción SENSIBLE

- Cero llamadas externas: Lighthouse/axe corren en local sobre el build local.
- Cero PII real: verifica que las capturas no expongan datos reales (fixtures ficticios).

## Riesgos

- R-02 (glass vs AAA): ajustar tokens si algún elemento no alcanza 7:1.
- R-04 (performance de animaciones): recomendar optimizaciones a CAPTAIN AMERICA si <90.

## Checkpoints aplicables

- C4 (criterios verificables). C7 (verificación/pruebas en verde). C8 (origen registrado).
