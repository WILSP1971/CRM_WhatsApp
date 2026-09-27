# PLAN-007 — CRM Analytics: dashboard de métricas de NEGOCIO (conversaciones, tiempos de respuesta, tasa de conversión) sobre datos REALES por tenant (RLS), on-demand con filtro de fechas — reemplaza el mock de `AnalyticsPage`

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Fecha: 2026-09-27 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo` presente) — multi-tenant con RLS estricto por `tenant_id` (ADR-004/ADR-008). Toda agregación se ejecuta bajo el **rol app `omnicore_app` (NOSUPERUSER NOBYPASSRLS)**, con el `tenant_id` del JWT ya fijado por `get_tenant_db` (`SET LOCAL app.tenant_id`, SPEC-012). **Prohibido** cualquier consulta con rol owner/superusuario que haga bypass de RLS. Este es un hallazgo de bug recurrente y muy documentado en este proyecto (ver `app/services/retention_service.py` y `app/services/telefonia/call_retention_service.py`).
> Origen: `prompt-lab/prompts/PROMPT-007-CRM-ANALYTICS.md` (🧠 XAVIER) · Estado: **PROPUESTA** (espera "APROBADO PLAN-007")
> Regla de oro: este PLAN **NO genera SPECs aprobadas**. Las SPEC se redactan como PROPUESTA y solo pasan a implementación tras la aprobación explícita del Lead ("APROBADO PLAN-007" y luego "APROBADO SPEC-XXX").
> Contadores vigentes (`.swarm/specs.json`): `next_plan: 7`, `next_spec: 62`, `next_adr: 14`. Este plan crea **SPEC-062..SPEC-066** (5 SPECs) → `next_spec` pasa a **67**. **No se recomienda ADR nuevo** (la definición de "conversión" NO introduce dominio nuevo — decisión del Lead Q1(a); ver §11).

---

## 1. Objetivo y contexto

### Objetivo

Construir un **dashboard de métricas de NEGOCIO** (para agentes/supervisores de un tenant) que exponga, **por tenant** y con **filtro de rango de fechas**, tres familias de métricas calculadas sobre los **datos reales** ya persistidos:

- **(a) Volumen de conversaciones:** total, desglose por canal (`whatsapp`/`webchat`/`instagram`/`messenger`/`voz` según `CANALES_VALIDOS`), abiertas vs cerradas, y **tendencia temporal** (serie por día en el rango).
- **(b) Tiempos de respuesta:** **tiempo de primera respuesta** (TPR) y **tiempo de respuesta promedio**, **derivados de `messages`** cruzando el `created_at` de un mensaje entrante (`remitente="contacto"`) con el siguiente saliente (`remitente` in `"agente"`/`"ia"`) de la misma conversación.
- **(c) Tasa de conversión:** **conversaciones cerradas / conversaciones totales** en el rango (decisión Q1(a) del Lead — `Conversation.estado="cerrada"`, **cero dominio nuevo**).

Alimentado por **endpoint(s) API de agregación reales** (no mock), con una **capa de servicio testeable de forma aislada**, respetando **RLS estricto por tenant**, y conectando la **SPA `AnalyticsPage`** (hoy 100% mock) a esos datos por **feature-flag** (`VITE_USE_REAL_API`, patrón SPEC-020/031). Modo **on-demand** (se calcula al vuelo sobre el rango pedido; **sin** tiempo real / WebSocket — decisión Q2). Presets **hoy / 7 días / 30 días + rango custom** (decisión Q4).

### Decisiones del Lead ya VINCULANTES (del prompt, §"Respuestas del Lead")

| # | Decisión | Consecuencia de alcance |
|---|----------|-------------------------|
| **Q1 — Conversión** | **(a)** Conversación cerrada (`estado="cerrada"`). Tasa = cerradas/totales en el rango. **Cero dominio nuevo.** | NO se crea campo/evento/modelo comercial. NO aplica el punto 4 del formato ("ADR de conversión") salvo documentarla en la SPEC. El modelo comercial completo (opción c) queda **fuera** y no abre PLAN futuro. |
| **Q2 — Modo de datos** | **on-demand con filtro de fecha** (no tiempo real / WebSocket). | Endpoint calcula al vuelo; **sin** infraestructura de push nueva; sin cambios en `/metrics` (Prometheus). |
| **Q3 — `AnalyticsPage`** | **reemplazar** el contenido mock (`kpis.json`/`analytics.json`/`sales.json`, SPEC-008) por datos reales, por feature-flag. | Misma ruta/página; con flag ON → datos reales; flag OFF → mock intacto (sin regresión). No convive maqueta ni se crea página separada. |
| **Q4 — Presets de fecha** | **hoy / 7 días / 30 días + rango custom** (sin mes/trimestre/año). | Selector con esos 3 presets + rango libre; sin periodos adicionales. |

### Estado verificado en código (fuente de verdad, no asunciones)

- **`Conversation`** (`app/models/conversation.py`): `canal`, `estado` (solo `"abierta"`/`"cerrada"` hoy), `contact_id`, `created_at`/`updated_at`, soft-delete, RLS por `tenant_id`.
- **`Message`** (`app/models/message.py`): `created_at`, `remitente` (`"contacto"`/`"agente"`/`"ia"`), `contenido`, `tipo` (`texto`/`audio`, SPEC-053), `sentimiento`/`sentimiento_score` (SPEC-018), `estado_entrega`. → **los tiempos de respuesta son derivables** de `created_at` + `remitente`.
- **`rag_draft`**: máquina de estados propuesto→editado→aprobado/descartado (SPEC-019) — proxy de "asistencia IA aceptada" (métrica opcional/derivada, bajo costo).
- **NO existe hoy** ningún endpoint de analytics/KPI de negocio en `app/api/` (solo conversations, messages, contacts, calls, rag, etc.).
- **`AnalyticsPage.tsx`** (`src/pages/`) es 100% mock (`kpis.json`/`analytics.json`/`sales.json`, `KpiCard`, `RevenueBySectorChart`, `CsatTrendChart`, `PipelineDonutChart`).
- **Prometheus** (`app/core/metrics.py`, SPEC-022) es observabilidad **técnica** (latencia HTTP, RTF STT). **Este dashboard es de NEGOCIO** — distinto: no se toca, no se reutiliza como fuente, no se mezcla con `/metrics`.
- **Patrón de acceso a BD en endpoints HTTP** (`app/api/deps.py::get_tenant_db`): fija `SET LOCAL app.tenant_id` con el `tenant_id` firmado en el JWT ANTES del handler → **RLS efectiva** con rol `omnicore_app`. Para este dashboard (endpoint HTTP normal) **NO** hace falta recorrer tenants como en los jobs de retención/purga: el `tenant_id` ya viene fijado. El aislamiento es automático y fail-closed (una sesión sin tenant ve cero filas).

---

## 2. Alcance IN / OUT

### IN — entra en PLAN-007

1. **Capa de servicio de agregación** (backend, testeable aislada): consultas SQL parametrizadas por rango de fechas y canal, **bajo RLS efectiva** (rol `omnicore_app`), que producen: volumen de conversaciones (total, por canal, abiertas/cerradas, serie temporal por día), TPR y tiempo de respuesta promedio (derivados de `messages`), y tasa de conversión (cerradas/totales).
2. **Endpoint(s) API REST de métricas de negocio** bajo el contrato OpenAPI existente, con respuesta agregada JSON, parametrizado por rango de fechas (`desde`/`hasta`) y opcionalmente por `canal`; autenticado (JWT) y con `get_tenant_db` (RLS). Validación de rango; manejo de rango vacío (devuelve ceros, no error).
3. **Conexión de `AnalyticsPage`** a datos reales por **feature-flag** (`VITE_USE_REAL_API`), **reemplazando** el mock (Q3): KPIs numéricos, series temporales y desglose por canal; selector de rango con presets **hoy/7d/30d + custom** (Q4); estados **carga / vacío / error accesibles (AAA)**; flag OFF = mock intacto.
4. **Métrica opcional/derivada de asistencia IA** (bajo costo, ya persistida): % de conversaciones con **borrador RAG aprobado** (SPEC-019) y **distribución de sentimiento** (SPEC-018) en el rango. Se incluye si no añade coste ni riesgo; si complica, se pospone (no bloquea el core).
5. **Pruebas con fixtures deterministas** (HAWKEYE): exactitud de cada métrica (incl. casos límite de tiempos de respuesta), **aislamiento cross-tenant que DEBE fallar por RLS** (rol app no-superusuario, ADR-008), objetivo de latencia (THOR) sobre volumen representativo, y **no-regresión de Entregables #1–#6** (incl. `/metrics` Prometheus intacto).

### OUT — NO entra en PLAN-007 (fase futura / decisión aparte)

- **Modelo comercial/CRM de ventas completo** (etapas, oportunidades, montos, "won"): fuera por decisión Q1(a). No abre PLAN futuro por ahora; solo se menciona como posible evolución si el Lead lo pide después.
- **Campo/etiqueta/evento nuevo de "conversión"** en `Conversation` (opción Q1(b)): fuera; la conversión es `estado="cerrada"`, cero dominio nuevo.
- **Tiempo real / WebSocket / push** del dashboard (Q2): fuera.
- **Exportación PDF/CSV, alertas/umbrales, dashboards programados**: candidatos a fase posterior; fuera de este slice.
- **CSAT real / ingresos / cualquier métrica sin fuente de datos hoy**: fuera (no hay dato que la respalde).
- **Sustituir/tocar Prometheus (`/metrics`, SPEC-022)**: fuera; es observabilidad técnica, ajena a este dashboard.
- **Nuevos periodos de fecha** (este mes/trimestre/año): fuera (Q4).

---

## 3. Arquitectura de referencia

### 3.1 Flujo end-to-end (on-demand)

```
supervisor  --abre AnalyticsPage (flag VITE_USE_REAL_API ON), elige rango (hoy/7d/30d/custom) + canal-->
            [SPA] --GET /analytics/... ?desde&hasta&canal (JWT)--> [api FastAPI]
            [get_tenant_db] SET LOCAL app.tenant_id = <tenant del JWT>  (RLS efectiva, rol omnicore_app)
            --> [analytics_service] ejecuta agregaciones SQL SOLO del tenant (RLS FORCE, fail-closed)
                 · conversaciones: COUNT total / por canal / por estado / serie por día
                 · tiempos de respuesta: TPR + promedio derivados de messages (contacto -> siguiente saliente)
                 · conversión: cerradas / totales
                 · (opcional) % drafts aprobados + distribución de sentimiento
            --> JSON agregado (sin PII individual; solo agregados) --> [SPA] KPIs + series + desglose
```

### 3.2 Dónde vive el aislamiento (invariante de seguridad, YA vigente — no se rediseña)

- Es un **endpoint HTTP normal**: el `tenant_id` viene firmado en el JWT y `get_tenant_db` lo fija con `SET LOCAL app.tenant_id` ANTES del handler. Todas las tablas tocadas (`conversations`, `messages`, `rag_draft`) están en `TENANT_SCOPED_TABLES` con RLS **ENABLE + FORCE** (ADR-004/ADR-008) y el rol de app `omnicore_app` es **NOSUPERUSER NOBYPASSRLS**. Por tanto cada consulta ve **solo** las filas del tenant autenticado — automático y fail-closed (sesión sin tenant → cero filas).
- **NO se recorren tenants** (a diferencia de `run_retention_job`/`run_call_retention_job`, que son jobs de mantenimiento sin request): aquí hay un único tenant por request. La SPEC de servicio (F0) documenta explícitamente que **no debe** usar rol owner/superusuario ni ninguna sesión "de plataforma" sin `tenant_id`, para no reintroducir el bug recurrente de bypass de RLS.
- Sin egress: todo es SQL local sobre PostgreSQL on-prem; **cero** llamadas externas, **cero** IA nueva (las señales de IA se leen de columnas ya persistidas, ADR-003/005).

### 3.3 Definición precisa de las métricas (para que HAWKEYE/BLACK PANTHER no reinterpreten)

- **Conversaciones totales:** `COUNT(conversations)` con `created_at` dentro de `[desde, hasta]`, activas (soft-delete excluido, C2), del tenant. (La ventana se define sobre `created_at` de la conversación; documentar y fijar en la SPEC para evitar ambigüedad con `updated_at`.)
- **Por canal:** el mismo conteo agrupado por `canal` (`CANALES_VALIDOS`).
- **Abiertas / cerradas:** agrupado por `estado` (`"abierta"`/`"cerrada"`).
- **Serie temporal:** conteo por día (`date_trunc('day', created_at)`) en el rango; días sin datos = 0 (relleno en servicio o front, a fijar en SPEC).
- **Tasa de conversión** = `cerradas / totales` en el rango (Q1(a)). Si `totales=0` → conversión = 0 (o `null` documentado), sin división por cero.
- **Tiempo de primera respuesta (TPR):** por conversación, `min(created_at)` de un mensaje saliente (`remitente` in `agente`/`ia`) posterior al **primer** mensaje entrante (`remitente="contacto"`); TPR = diferencia; se reporta el **promedio** (y opcionalmente mediana/p95) sobre las conversaciones del rango que tuvieron respuesta.
- **Tiempo de respuesta promedio:** promedio de las diferencias entrante→siguiente-saliente a lo largo de cada conversación (múltiples idas y vueltas). **Casos límite** que las pruebas DEBEN cubrir: conversación sin respuesta (se excluye del promedio, no cuenta como 0), respuesta de IA vs agente (ambas cuentan como saliente; opcionalmente desglosable), varios entrantes seguidos antes de una respuesta (se toma el primer entrante del bloque), conversación con solo salientes (se excluye).
- **(Opcional) % drafts aprobados:** conversaciones con al menos un `rag_draft` en estado aprobado / conversaciones del rango. **Distribución de sentimiento:** conteo de `messages.sentimiento` (positivo/neutral/negativo) en el rango. Ambas leídas de columnas existentes, sin IA nueva.

### 3.4 Contrato de respuesta (orientativo — la SPEC F1 lo fija)

```
GET /analytics/business?desde=YYYY-MM-DD&hasta=YYYY-MM-DD[&canal=whatsapp]
{
  "rango": { "desde": "...", "hasta": "..." },
  "conversaciones": {
    "total": N, "abiertas": N, "cerradas": N,
    "por_canal": [{ "canal": "whatsapp", "total": N, "abiertas": N, "cerradas": N }, ...],
    "serie_diaria": [{ "fecha": "YYYY-MM-DD", "total": N }, ...]
  },
  "conversion": { "tasa": 0.0, "cerradas": N, "totales": N },
  "tiempos_respuesta": { "primera_respuesta_promedio_seg": N, "respuesta_promedio_seg": N, "conversaciones_con_respuesta": N },
  "ia_asistencia": { "pct_drafts_aprobados": 0.0, "sentimiento": { "positivo": N, "neutral": N, "negativo": N } }  // opcional
}
```

> Se decide en la SPEC F1 si es **un** endpoint con toda la agregación o varios sub-endpoints (KPIs / series / desglose). Recomendación: **un endpoint** parametrizado (menos round-trips, on-demand, cachea trivialmente) salvo que THOR encuentre motivo para separar la serie temporal.

---

## 4. Fases y entregables

| Fase | Nombre | Entregables clave | SPEC |
|------|--------|-------------------|------|
| **F0** | Capa de servicio de agregación (backend, RLS efectiva) | `analytics_service` con funciones puras testeables: conversaciones (total/canal/estado/serie), TPR + respuesta promedio (derivados de `messages`, casos límite §3.3), conversión (cerradas/totales), (opcional) drafts aprobados + sentimiento. Consultas SQL parametrizadas por rango+canal, **bajo `get_tenant_db`/rol `omnicore_app`** (RLS FORCE, sin bypass). Soft-delete excluido (C2). Índices adecuados (THOR). | **SPEC-062** |
| **F1** | Endpoint(s) API REST de métricas | Router `analytics` (JWT + `get_tenant_db`), `GET` parametrizado por `desde`/`hasta`/`canal`; validación de rango; respuesta agregada JSON (§3.4); documentado en OpenAPI; sin PII individual (solo agregados); no toca `/metrics`. | **SPEC-063** |
| **F2** | SPA: `AnalyticsPage` a datos reales por feature-flag (reemplaza mock, Q3) | `AnalyticsPage` consume el endpoint bajo `VITE_USE_REAL_API`: KPIs, series temporales, desglose por canal; selector de rango (hoy/7d/30d + custom, Q4); estados carga/vacío/error **AAA**; design system reutilizado (sin duplicar gráficos). Flag OFF = mock #1 intacto. | **SPEC-064** |
| **F3** | Pruebas + seguridad + performance + no-regresión | Fixtures deterministas: exactitud de cada métrica (incl. casos límite de tiempos de respuesta §3.3); **cross-tenant que falla por RLS** (rol app no-superusuario, ADR-008); latencia p95 del endpoint (THOR) sobre volumen representativo; **cero regresión** de #1–#6 y de `/metrics` (Prometheus). Cobertura del código nuevo ≥80%. | **SPEC-065** |
| **F4** | Documentación + runbook + deploy on-prem | Doc de las métricas y su definición (incl. "conversión = cerradas/totales", Q1(a)); notas OpenAPI; guía de la feature-flag; runbook; deploy on-prem (QUICKSILVER, con aprobación del Lead). | **SPEC-066** |

---

## 5. Dependencias entre fases y ruta crítica

- **F0 (SPEC-062)** es prerequisito duro: sin la capa de servicio no hay qué exponer ni qué probar. Es el **núcleo técnico** (correctitud de tiempos de respuesta + RLS efectiva).
- **F1 (SPEC-063)** depende de F0 (expone el servicio por HTTP).
- **F2 (SPEC-064)** depende de F1 (consume el endpoint); reutiliza SPEC-020/031 (feature-flag) y el design system de SPEC-008.
- **F3 (SPEC-065)** depende de F0/F1/F2 (prueba el slice completo, incl. exactitud, RLS, latencia, no-regresión).
- **F4 (SPEC-066)** cierra: docs/runbook/deploy tras F3.

**Ruta crítica:** `F0 → F1 → F2 → F3 → F4`. La **ruta crítica dura** es **F0**: la correctitud de los tiempos de respuesta (casos límite §3.3) y el **cumplimiento de RLS efectiva** (no reintroducir el bug de bypass) son los puntos de mayor riesgo.

---

## 6. Riesgos y mitigaciones

| # | Riesgo | Impacto | Mitigación |
|---|--------|---------|------------|
| **R-71** | **Fuga cross-tenant en las agregaciones** (una consulta que use rol owner/superusuario o sesión sin `tenant_id` → ve todos los tenants; bug recurrente muy documentado). | **Crítico** (rompe SENSIBLE/RLS) | El servicio corre SOLO bajo `get_tenant_db` (rol `omnicore_app` NOSUPERUSER NOBYPASSRLS, `SET LOCAL app.tenant_id`, ADR-008); **prohibido** rol owner o sesión de plataforma. Test cross-tenant que **falla** por RLS (SPEC-065). Documentado explícito en SPEC-062. |
| **R-72** | **Tiempos de respuesta mal calculados** en casos límite (sin respuesta, IA vs agente, múltiples idas y vueltas, solo salientes). | Alto (métrica engañosa) | Definición precisa §3.3; fixtures deterministas que cubren cada caso límite (SPEC-065); conversaciones sin respuesta se EXCLUYEN del promedio (no cuentan como 0). |
| **R-73** | **Performance de agregación sobre `messages`** (tabla grande; serie temporal + joins de tiempos de respuesta pueden ser pesados). | Medio/Alto | Índices adecuados (`created_at`, `conversation_id`, `remitente`); objetivo de latencia p95 acordado (THOR, SPEC-065); consultas acotadas por rango; considerar agregación por SQL (no en Python) y `date_trunc` con índice. |
| **R-74** | **Regresión de la maqueta `AnalyticsPage` (#1)** al reemplazar el mock. | Medio | Cambio gobernado por feature-flag `VITE_USE_REAL_API` (OFF = mock intacto, reversible); reutiliza SPEC-020/031; suites de #1 verdes (SPEC-065). |
| **R-75** | **PII reintroducida en agregados** o registros soft-deleted/anonimizados contados. | Medio (HABEAS DATA) | La respuesta es **solo agregados** (conteos/promedios), sin PII individual; se excluyen soft-deleted (C2) y se respeta `anonymized_at` (SPEC-021); revisión BLACK WIDOW (SPEC-065). |
| **R-76** | **Confusión con Prometheus** (mezclar métricas de negocio con `/metrics` técnico). | Bajo/Medio | Router/servicio separados; **no** se toca `app/core/metrics.py` ni `/metrics`; test de no-regresión de `/metrics` (SPEC-065). |
| **R-77** | **División por cero / rango vacío** (tasa de conversión con 0 conversaciones; rango sin datos). | Bajo | Rango vacío → ceros/`null` documentado, no error; conversión con `totales=0` → 0/`null` (fijado en §3.3 y SPEC-062). |

**Top-3:** **R-71 (fuga cross-tenant / bypass RLS)**, **R-72 (tiempos de respuesta en casos límite)**, **R-73 (performance sobre `messages`)**.

---

## 7. Criterios de éxito verificables (mapeo con los del prompt CE-71..CE-77)

| ID | Criterio | Cómo se verifica | Fase |
|----|----------|------------------|------|
| **CE-71** | Un supervisor ve, para un rango elegido: nº de conversaciones (total y por canal), % abiertas/cerradas, TPR y respuesta promedio, y tasa de conversión — **cifras que coinciden con la BD real de ese tenant**. | Test contra BD con fixtures deterministas: los agregados igualan el conteo esperado (SPEC-065). | F0/F1/F3 |
| **CE-72** | Un tenant **NUNCA** ve datos de otro tenant. | Test de aislamiento cross-tenant que **falla** por RLS con rol app no-superusuario (ADR-008), SPEC-065. | F0/F3 |
| **CE-73** | Los tiempos de respuesta son correctos en casos límite (sin respuesta, IA vs agente, múltiples idas/vueltas). | Fixtures deterministas por caso (§3.3), SPEC-065. | F0/F3 |
| **CE-74** | El endpoint cumple el objetivo de latencia acordado (THOR) sobre volumen representativo. | Medición de p95 sobre dataset representativo (SPEC-065). | F1/F3 |
| **CE-75** | La SPA muestra estados carga/vacío/error **accesibles (AAA)** y respeta el design system; flag OFF = mock intacto. | Revisión DAREDEVIL + a11y; test de feature-flag (SPEC-064/065). | F2/F3 |
| **CE-76** | "Conversión" definida y documentada (= cerradas/totales, Q1(a)) y validada por pruebas; **sin dominio nuevo / sin ADR de dominio**. | Doc en SPEC-062/066 + test de la fórmula (SPEC-065). | F0/F4 |
| **CE-77** | **Cero regresión** en `/metrics` (Prometheus) y en features #1–#6. | `/metrics` intacto; suites #1–#6 verdes (SPEC-065). | F3 |

> Transversales heredados: **aprobación explícita del Lead**; CHECKPOINTS C2 (borrado lógico) / C3 (secretos) / C4 (criterios verificables) / C6 (cambio sensible → notificación Telegram) / C8 (prompt registrado en `prompt-lab/prompts/PROMPT-007-CRM-ANALYTICS.md`).

---

## 8. Mapa de SPECs propuestas (SOLO el mapa — se redactan como PROPUESTA, se implementan tras "APROBADO PLAN-007")

> Continúa la numeración desde `specs.json` (`next_spec: 62`). Cada SPEC lleva criterios verificables (C4).

- **SPEC-062** — Capa de servicio de agregación de métricas de negocio (`analytics_service`): conversaciones (total/canal/estado/serie), TPR + respuesta promedio (derivados de `messages`, casos límite), conversión (cerradas/totales), (opcional) drafts aprobados + sentimiento; consultas SQL parametrizadas por rango+canal **bajo RLS efectiva** (rol `omnicore_app`, sin bypass); soft-delete excluido; testeable aislada (F0).
- **SPEC-063** — Endpoint(s) API REST de métricas de negocio: router `analytics` (JWT + `get_tenant_db`), `GET` parametrizado por `desde`/`hasta`/`canal`, respuesta agregada JSON, OpenAPI, sin PII individual, no toca `/metrics` (F1).
- **SPEC-064** — SPA `AnalyticsPage` a datos reales por feature-flag (reemplaza mock, Q3): KPIs + series + desglose por canal; selector de rango hoy/7d/30d + custom (Q4); estados carga/vacío/error AAA; flag OFF = mock intacto (F2).
- **SPEC-065** — Pruebas + seguridad + performance + no-regresión: fixtures deterministas de exactitud (incl. casos límite de tiempos), cross-tenant que falla por RLS, latencia p95 (THOR), cero regresión de #1–#6 y `/metrics`, cobertura ≥80% (F3).
- **SPEC-066** — Documentación (definición de métricas y de "conversión = cerradas/totales"), runbook, notas OpenAPI, guía de feature-flag y deploy on-prem (F4).

> Total: **5 SPECs (SPEC-062..SPEC-066)** → `next_spec` pasa a **67** al crearlas.

---

## 9. Entregables finales de PLAN-007

- `analytics_service` (backend) con agregaciones correctas bajo RLS efectiva.
- Endpoint(s) REST de métricas de negocio parametrizado por rango+canal, documentado en OpenAPI.
- `AnalyticsPage` conectada a datos reales por feature-flag, con presets de fecha y estados AAA; mock intacto con flag OFF.
- Suite de pruebas deterministas (exactitud, casos límite de tiempos, cross-tenant RLS, latencia, no-regresión) + cobertura ≥80%.
- Definición documentada de "conversión = cerradas/totales" (Q1(a), sin dominio nuevo).
- **Evidencia auditable:** cifras que coinciden con la BD del tenant; aislamiento cross-tenant; sin PII en agregados; `/metrics` intacto; sin egress.

## 10. Definition of Done (PLAN-007)

1. CE-71..CE-77 cumplidos y evidenciados.
2. Métricas (conversaciones, tiempos de respuesta, conversión) calculadas sobre datos reales del tenant, coincidentes con la BD; on-demand con filtro de fechas (hoy/7d/30d/custom).
3. **RLS efectiva** en toda agregación (rol `omnicore_app`, sin bypass); test cross-tenant que **falla** por RLS.
4. Tiempos de respuesta correctos en casos límite (fixtures deterministas).
5. Latencia p95 del endpoint dentro del objetivo THOR sobre volumen representativo.
6. SPA con datos reales por feature-flag; estados carga/vacío/error AAA; **mock intacto con flag OFF** (sin regresión #1).
7. Sin PII individual en agregados; soft-delete/anonimizados respetados (C2/HABEAS DATA).
8. **`/metrics` (Prometheus) intacto**; suites #1–#6 verdes; cobertura código nuevo ≥80%.
9. Secretos fuera del código/logs (C3).
10. Docs/runbook entregados; deploy on-prem con **aprobación del Lead** (cambio sensible → notificación Telegram, C6).
11. **Aprobación explícita del Lead**. Ninguna SPEC se cierra sin cumplir los CHECKPOINTS aplicables (C2/C3/C4/C6/C8).

---

## 11. ADRs recomendados

> **No se requiere ADR nuevo.** La definición de "conversión = conversaciones cerradas / totales" (Q1(a)) **no introduce dominio nuevo** (usa `Conversation.estado="cerrada"` existente) — el propio Lead confirmó que no aplica el punto 4 del formato salvo documentarla en la SPEC (SPEC-062/066). Se **heredan**: ADR-003/005 (IA local / cero egress — las señales de IA se leen de columnas ya persistidas, sin inferencia nueva), ADR-004/008 (RLS efectiva multi-tenant con rol app no-superusuario — base del aislamiento de todas las agregaciones). Si en el futuro el Lead pide el modelo comercial completo (opción Q1(c)), ESE sería su propio PLAN + ADR de dominio; fuera de aquí.

---

## 12. PREGUNTAS ABIERTAS AL LEAD

**Ninguna de alcance.** Las 4 decisiones (Q1–Q4) están resueltas en el prompt y adoptadas en este plan. Puntos menores que se fijan en la SPEC (no requieren decisión del Lead, con supuesto por defecto):

1. **Ventana temporal de "conversación total":** se cuenta por `created_at` de la conversación dentro del rango. *Supuesto por defecto adoptado; se fija en SPEC-062.*
2. **Un endpoint vs varios:** un endpoint parametrizado por defecto; THOR puede separar la serie temporal si la latencia lo exige. *Se fija en SPEC-063 tras medir.*
3. **Métrica opcional de asistencia IA** (% drafts aprobados + distribución de sentimiento): se incluye si no añade coste/riesgo; se pospone si complica. *No bloquea el core; se decide en SPEC-062.*

---

> **Siguiente paso:** IRON MAN presenta este PLAN-007 al Lead. El Lead debe responder **"APROBADO PLAN-007"** (o "Ajusta PLAN-007: …") antes de que DOCTOR STRANGE (ya redactadas como PROPUESTA) habilite la implementación de SPEC-062..SPEC-066. Cumple CHECKPOINT C8 (prompt registrado en `prompt-lab/prompts/PROMPT-007-CRM-ANALYTICS.md`).
