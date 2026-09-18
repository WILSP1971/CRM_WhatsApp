# SPEC-011 — Infraestructura base y Docker Compose on-prem + CI backend

- Estado: PROPUESTA · Responsable: QUICKSILVER · Colaboran: BLACK PANTHER, BLACK WIDOW, WOLVERINE, HAWKEYE · Prioridad: ALTA · Tipo: INFRA/DEVOPS · Fase: F0
- Deriva de: PLAN-002 (F0) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Levantar el esqueleto ejecutable on-prem con `docker compose up`: API FastAPI, PostgreSQL 16 + pgvector, Redis y contenedor de IA en **red interna sin egress**, más CI backend (lint + typecheck + test + `check-externos-backend.sh`).

## Contexto

Fase F0: habilita TODAS las demás fases (ninguna arranca sin infra + CI). El contenedor de IA queda conectado solo a una red Docker `internal: true`, sin puente a internet; los modelos se montan por volumen local. La API expone `/healthz` y OpenAPI en `/docs`. Base para CE-21 y CE-28 del PLAN-002.

## Alcance

### IN
- `docker-compose.yml` con servicios: `api` (FastAPI), `db` (PostgreSQL 16 + pgvector), `redis`, `ia` (Ollama/vLLM).
- Red Docker `internal: true` para el servicio `ia` (sin egress); red separada para API↔visitante/SPA.
- Esqueleto FastAPI async con `/healthz` y OpenAPI en `/docs`; estructura de carpetas backend.
- `.env.example` (sin valores reales) con todas las variables requeridas (C3).
- `check-externos-backend.sh`: escanea código/config del backend buscando URLs/dominios externos, SDKs de IA de terceros y endpoints de inferencia remota; falla el CI si aparece alguno.
- Pipeline CI backend (GitHub Actions): lint + typecheck + tests + `check-externos-backend.sh`.
- Healthchecks Docker para cada servicio; volúmenes persistentes para `db` y modelos de `ia`.

### OUT
- Migraciones y esquema de datos (SPEC-012).
- Modelos de IA cargados y pipeline de inferencia (SPEC-016).
- Deploy a producción (SPEC-023, con aprobación del Lead).

## Dependencias
- Ninguna previa (prerequisito duro de SPEC-012..SPEC-023).

## Requisitos funcionales
- RF `docker compose up` levanta API+db+redis+ia con health verdes, sin acceso a internet de inferencia.
- RF La API responde `200` en `/healthz` y publica OpenAPI en `/docs`.
- RF El contenedor `ia` no puede alcanzar internet (red `internal`).

## Requisitos no funcionales
- RNF-08 Portabilidad on-prem; arranque reproducible en host aislado.
- RNF-06 Observabilidad mínima base (`/healthz`, logs estructurados iniciales).
- Secretos SOLO en env (C3); `.env` fuera del repo; `.env.example` sin valores reales.

## Criterios de aceptación (verificables)
- [ ] `docker compose up` deja los 4 servicios en estado `healthy` sin internet de inferencia.
- [ ] `GET /healthz` devuelve `200` y `GET /docs` sirve la OpenAPI.
- [ ] El servicio `ia` está en red `internal: true`; `docker inspect` confirma que no tiene gateway a internet.
- [ ] Desde el contenedor `ia`, un `curl` a un dominio externo (p.ej. `api.openai.com`) **falla** (timeout/deny).
- [ ] `check-externos-backend.sh` corre en CI y **falla** si se introduce una URL/SDK externo de inferencia.
- [ ] CI backend ejecuta lint + typecheck + tests + `check-externos-backend.sh` en cada push/PR.
- [ ] `.env.example` presente, sin secretos reales; el repo no contiene secretos en texto plano.

## Notas de seguridad (C2/C3)
- C3: todas las credenciales (BD, JWT, Redis) vía variables de entorno; nunca en el repo.
- C2: no aplica directamente en F0 (sin entidades transaccionales todavía).

## Restricción SENSIBLE aplicable
- Contenedor IA sin egress (red `internal`); modelos montados localmente (nunca `pull` en runtime hacia internet). Base auditable de "cero externos de inferencia" (CE-21).

## Riesgos
- R-22 (fuga de egress IA): red `internal` + firewall host DROP + `check-externos-backend.sh`.
- R-26 (secretos en texto plano): `.env` fuera del repo, `.env.example` sin valores.

## Checkpoints aplicables
- C3 (sin secretos). C4 (criterios verificables). C8 (origen registrado en PLAN-002).
