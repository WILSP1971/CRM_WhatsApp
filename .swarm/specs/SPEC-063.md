# SPEC-063 — Endpoint(s) API REST de métricas de NEGOCIO: router `analytics` (JWT + RLS), parametrizado por rango de fechas y canal 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, THOR, HAWKEYE, BLACK WIDOW, WOLVERINE · Prioridad: ALTA · Tipo: BACKEND/API · Fase: F1
- Deriva de: PLAN-007 (F1, §3.4) · Clasificación: SENSIBLE (`.no-externo`) · ADR-004/ADR-008
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Exponer la capa de servicio de agregación (SPEC-062) mediante **endpoint(s) API REST** bajo el contrato OpenAPI existente: un `GET` autenticado (JWT) que, usando `get_tenant_db` (RLS efectiva), devuelve la **respuesta agregada JSON** con KPIs de conversaciones, tiempos de respuesta y tasa de conversión, **parametrizado por rango de fechas** (`desde`/`hasta`) y **opcionalmente por canal**. Modo **on-demand** (Q2): calcula al vuelo sobre el rango pedido; **sin** tiempo real / WebSocket. La respuesta contiene **solo agregados** (sin PII individual) y **no toca** `/metrics` (Prometheus, SPEC-022).

## Contexto

`app/api/` ya tiene routers para conversations, messages, contacts, calls, rag, etc., todos con el patrón JWT + `get_tenant_db` (`app/api/deps.py`), listados sin inactivos por defecto (C2) y schemas Pydantic. **No existe hoy** ningún endpoint de analytics/KPI de negocio. Este endpoint sigue ese mismo patrón: el `tenant_id` viene firmado en el JWT y `get_tenant_db` lo fija (`SET LOCAL app.tenant_id`) ANTES del handler → RLS efectiva automática (rol `omnicore_app`). El handler delega toda la lógica en `analytics_service` (SPEC-062) — es un router delgado (validación + orquestación + serialización).

## Alcance

### IN
- **Router `analytics`** montado en la app (p.ej. `app/api/analytics.py`), con dependencia JWT (`get_current_user`) + `get_tenant_db` (RLS).
- **Endpoint `GET`** (p.ej. `/analytics/business`) parametrizado por query params: `desde` (fecha), `hasta` (fecha), `canal` (opcional, validado contra `CANALES_VALIDOS`). Recomendación: **un** endpoint parametrizado que devuelve todo el bloque agregado (§3.4 del plan); THOR puede separar la serie temporal en un sub-endpoint solo si la latencia lo exige (SPEC-065).
- **Validación de rango:** `desde <= hasta`; límite superior razonable del rango (para acotar coste, configurable por env); rango vacío/sin datos → **ceros** (no error 4xx/5xx).
- **Respuesta agregada JSON** (schema Pydantic): conversaciones (total/abiertas/cerradas/por_canal/serie_diaria), conversión (tasa/cerradas/totales), tiempos_respuesta (primera_respuesta_promedio_seg/respuesta_promedio_seg/conversaciones_con_respuesta) y (opcional) ia_asistencia (pct_drafts_aprobados/sentimiento). **Solo agregados, sin PII individual.**
- **Documentación OpenAPI** del endpoint (descripción, params, schema de respuesta, ejemplos sin datos reales).
- Manejo de errores coherente con el resto de la API (401 sin JWT, 422 rango inválido).

### OUT
- La lógica de agregación en sí (SPEC-062).
- SPA / feature-flag (SPEC-064).
- Pruebas (SPEC-065) y docs/deploy (SPEC-066).
- Cualquier escritura/mutación (es solo lectura agregada).
- Tiempo real / WebSocket / push (Q2, fuera).
- Tocar `/metrics` o `app/core/metrics.py` (ajeno; es observabilidad técnica).

## Dependencias
- Depende de SPEC-062 (capa de servicio) y del patrón `get_tenant_db`/JWT de SPEC-013/014 y `app/api/deps.py`. Se ancla en ADR-004/ADR-008 (RLS efectiva). Prerequisito de SPEC-064/065.

## Requisitos funcionales
- RF-01 `GET /analytics/business?desde&hasta[&canal]` autenticado devuelve el bloque agregado JSON del tenant del JWT.
- RF-02 El endpoint valida el rango (`desde<=hasta`, límite superior) y el `canal`; rango sin datos → ceros, no error.
- RF-03 El endpoint delega toda la agregación en `analytics_service` (SPEC-062); es un router delgado.
- RF-04 La respuesta contiene solo agregados; sin PII individual.

## Requisitos no funcionales
- RNF-47 **RLS efectiva:** el handler usa `get_tenant_db` (rol `omnicore_app`, `app.tenant_id` del JWT); cada request agrega solo datos del tenant autenticado; sin bypass.
- RNF-73 **Performance:** on-demand; preparado para cumplir el objetivo de latencia p95 (THOR, SPEC-065); considerar cache/ETag si THOR lo recomienda (opcional).
- RNF-07 No modifica `/metrics` ni otros endpoints; contrato OpenAPI aditivo (no rompe clientes existentes).

## Criterios de aceptación (verificables)
- [ ] `GET /analytics/business?desde&hasta` con JWT válido devuelve 200 + bloque agregado JSON coincidente con la BD del tenant.
- [ ] Sin JWT → 401; rango inválido (`desde>hasta`) → 422; `canal` inválido → 422.
- [ ] Rango sin datos → respuesta con ceros (no error), sin división por cero en conversión.
- [ ] La respuesta contiene **solo agregados** (sin PII individual, verificado).
- [ ] Un tenant recibe **solo** sus métricas (RLS efectiva vía `get_tenant_db`); test cross-tenant (SPEC-065).
- [ ] El endpoint aparece documentado en OpenAPI con ejemplos sin datos reales.
- [ ] `/metrics` (Prometheus) y demás endpoints intactos (no-regresión, SPEC-065).

## Notas de seguridad (C2/C3)
- C2: los agregados excluyen inactivos (heredado de SPEC-062).
- C3: sin secretos en el router; config (límite de rango, cache) solo por env.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (sin egress): endpoint de solo lectura sobre BD on-prem; cero llamadas externas; cero IA nueva. Aislamiento por RLS efectiva (ADR-004/008): `tenant_id` del JWT vía `get_tenant_db`, nunca bypass.

## Riesgos
- R-71 (fuga cross-tenant): handler siempre con `get_tenant_db`; sin rol owner; test cross-tenant (SPEC-065).
- R-73 (performance): on-demand + agregación en SQL (SPEC-062); objetivo p95 (THOR); cache opcional.
- R-75 (PII en respuesta): schema de solo agregados; revisión BLACK WIDOW (SPEC-065).
- R-76 (confusión con Prometheus): router/servicio separados; `/metrics` intacto.
- R-77 (rango vacío): manejado (ceros, sin error).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-007 / `prompt-lab/prompts/PROMPT-007-CRM-ANALYTICS.md`).
