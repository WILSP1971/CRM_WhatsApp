# SPEC-023 — Documentación, runbook operativo y deploy on-prem (Docker Compose)

- Estado: PROPUESTA · Responsable: QUICKSILVER · Colaboran: BLACK PANTHER, BLACK WIDOW, WOLVERINE, HAWKEYE · Prioridad: ALTA · Tipo: DOCS/DEVOPS/DEPLOY · Fase: F9
- Deriva de: PLAN-002 (F9) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Entregar la **documentación** y el **runbook operativo** y realizar el **deploy on-prem** con Docker Compose: README de operación (variables de entorno, modelos locales a descargar, arranque de modelos), runbook de incidentes y colección de ejemplos OpenAPI.

## Contexto

Fase F9 (cierre; deploy requiere aprobación explícita del Lead). Depende de F7/F8 cerradas. Documenta cómo levantar el slice sin internet de inferencia (`docker compose up`), qué modelos locales descargar/montar y cómo arrancar Ollama/vLLM. Base de CE-28 (despliegue on-prem reproducible) y CE-29 (aprobación del Lead).

## Alcance

### IN
- README de operación on-prem: variables de entorno (`.env`), modelos locales a descargar/montar, `docker compose up`.
- Instrucciones de arranque de modelos locales (Ollama/vLLM: modelo por defecto, quant, fallback CPU Q4).
- Runbook operativo/incidentes (arranque, salud, backups del volumen PostgreSQL, rotación de secretos, respuesta a incidentes).
- Colección de ejemplos OpenAPI (requests/responses) para la SPA y consumidores.
- Guía de verificación de "cero externos" (egress vacío + `check-externos-backend.sh`) para operación.
- Deploy on-prem en host aislado (QUICKSILVER, **con aprobación del Lead**).

### OUT
- Implementación de features y pruebas (SPEC-011..022).
- HA/Kubernetes/escalado multi-nodo (Fase 3+).
- Despliegue a infraestructura de producción externa al repo sin aprobación.

## Dependencias
- Depende de SPEC-021 (seguridad) y SPEC-022 (pruebas/carga) cerradas. Cierra el Entregable #2.

## Requisitos funcionales
- RF `docker compose up` levanta el slice completo sin internet de inferencia (host aislado).
- RF El README documenta env, modelos locales y arranque; el runbook cubre incidentes/backups.
- RF La colección OpenAPI ejecuta requests de ejemplo válidos.

## Requisitos no funcionales
- RNF-08 Despliegue on-prem reproducible; health-checks verdes.
- RNF-06 Runbook operativo claro (arranque, backups, incidentes, rotación de secretos).
- Secretos SOLO en env (C3); `.env.example` como referencia sin valores reales.

## Criterios de aceptación (verificables)
- [ ] Arranque limpio en host aislado con `docker compose up`; los 4 servicios `healthy` sin internet de inferencia — CE-28.
- [ ] README documenta todas las variables de entorno, modelos locales a descargar/montar y arranque de modelos.
- [ ] Runbook cubre salud, backups del volumen PostgreSQL, rotación de secretos y respuesta a incidentes.
- [ ] Colección OpenAPI con ejemplos ejecutables (requests/responses reales).
- [ ] Guía de verificación de "cero externos" documentada y reproducible.
- [ ] **Aprobación explícita del Lead** para el deploy — CE-29.

## Notas de seguridad (C2/C3)
- C3: la documentación no incluye secretos reales; solo `.env.example`.
- C2: el runbook respeta el borrado lógico (backups/purga según retención).

## Restricción SENSIBLE aplicable
- Deploy 100% on-prem; modelos descargados/montados localmente; sin internet de inferencia. Evidencia auditable de "cero externos" (CE-21/CE-28).

## Riesgos
- R-21 (GPU/VRAM): documentar fallback CPU Q4 y degradación de latencia.
- R-26 (secretos): documentación sin secretos; solo `.env.example`.
- Deploy sensible: requiere aprobación del Lead (no se despliega sin ella).

## Checkpoints aplicables
- C2 (borrado lógico en backups). C3 (sin secretos). C4 (criterios verificables). C6 (deploy sensible → aprobación Lead). C8 (origen PLAN-002).

## Nota de aprobación
- **SPEC con deploy sensible:** el despliegue on-prem requiere aprobación explícita del Lead y notificación (`.claude/hooks/notify.sh`).
