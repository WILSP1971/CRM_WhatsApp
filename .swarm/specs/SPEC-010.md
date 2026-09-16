# SPEC-010 — Repo, CI y documentación

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: QUICKSILVER, BLACK WIDOW, WOLVERINE, HAWKEYE · Prioridad: ALTA · Tipo: DEVOPS/DOCS · Fase: F8
- Deriva de: PLAN-001 (F8) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Establecer repo local + GitHub (github.com/WILSP1971/CRM_WhatsApp), README, pipeline CI
(build + lint + verificación cero-externos + Lighthouse) y mantener `contexto/ESTADO.md`.

## Contexto

Fase transversal: la CI base se prepara en F0 y se cierra tras F7 con docs y capturas finales
y barrido de seguridad. Valida CE-04, CE-05 y CE-08 del PLAN.

## Alcance

### IN

- Repo local inicializado y remoto en github.com/WILSP1971/CRM_WhatsApp.
- README de ejecución + catálogo de tokens/componentes.
- CI (GitHub Actions): build + lint + `check:externos` + Lighthouse CI (umbrales A11y/Perf ≥90).
- Barrido BLACK WIDOW: sin PII real, sin secretos; `puede-modelo-externo.sh` respeta la política.
- `contexto/ESTADO.md` actualizado con el estado del entregable #1.

### OUT

- Deploy a infraestructura de producción (requiere aprobación del Lead aparte).

## Dependencias

- Prepara base en SPEC-001 (F0); se cierra tras SPEC-009 (F7). Documenta SPEC-001 a SPEC-009.

## Requisitos funcionales

- RF CI corre en cada push/PR y falla si lint, build, `check:externos` o Lighthouse no pasan.
- RF README explica cómo instalar/correr/construir la maqueta.
- RF Catálogo de tokens/componentes documentado.

## Requisitos no funcionales

- RNF-06 (documentación). Sin secretos en repo/CI (C3): tokens de CI vía secrets del repo.
- CI reproducible y determinista.

## Criterios de aceptación (verificables)

- [ ] Repo remoto en github.com/WILSP1971/CRM_WhatsApp con el proyecto versionado.
- [ ] README con pasos de instalación/ejecución/build verificados.
- [ ] Workflow CI ejecuta build + lint + `check:externos` + Lighthouse y falla ante incumplimiento.
- [ ] Umbrales Lighthouse en CI: Accessibility ≥90 y Performance ≥90.
- [ ] Barrido de seguridad sin PII real ni secretos; `puede-modelo-externo.sh` en verde.
- [ ] `contexto/ESTADO.md` refleja el estado del entregable #1.

## Accesibilidad (WCAG 2.2 AAA)

- CI incluye gate de Accessibility (Lighthouse ≥90) como control automatizado de AAA.

## Restricción SENSIBLE

- Cero llamadas externas en el build/artefacto; CI corre sobre el build local.
- Cero PII real: barrido de fixtures y capturas; sin secretos en texto plano (C3).

## Riesgos

- R-01 (fuga a externos): `check:externos` en CI como gate.
- R-05 (PII en repo): barrido BLACK WIDOW previo a publicar.

## Checkpoints aplicables

- C3 (sin secretos). C4 (criterios verificables). C6 (publicación/deploy: aprobación Lead). C8 (origen registrado).
