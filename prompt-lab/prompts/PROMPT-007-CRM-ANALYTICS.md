# PROMPT-007 — CRM Analytics: dashboard de métricas de negocio

> Prompt optimizado por XAVIER (Professor X) a partir del objetivo en bruto del Lead.
> Paso 0 del flujo del enjambre. Entrada para DOCTOR STRANGE (PLAN-007).
> Objetivo verbatim del Lead: *"CRM Analytics: dashboard de métricas de negocio
> (conversaciones, conversión, tiempos de respuesta)"*.

---

## Contexto

CRM_WhatsApp — OmniCore AI. Plataforma omnicanal multi-tenant on-prem, clasificación
SENSIBLE. Stack: backend FastAPI + PostgreSQL (RLS estricto por `tenant_id`, ADR-004) +
Redis; IA 100% local self-hosted (ADR-003/005); frontend SPA React/Vite (design system
propio WCAG AAA). Deploy Docker Compose on-prem, CPU-only (sin GPU, ver MEMORY).

Estado actual **verificado en código** (no asunciones), relevante para este objetivo:

- **Conversaciones** (`backend/app/models/conversation.py`): `Conversation` tiene
  `canal` (whatsapp/webchat/instagram/messenger), `estado` (solo toma **"abierta"** /
  **"cerrada"** en el código actual — no hay más estados definidos), `contact_id`,
  timestamps (`created_at`/`updated_at`) y soft-delete. Multi-tenant con RLS.
- **Mensajes** (`backend/app/models/message.py`): `Message` tiene `created_at`,
  `remitente` (**"contacto" | "agente" | "ia"**), `contenido`, `tipo` (texto/audio),
  `sentimiento` (positivo/neutral/negativo, SPEC-018) + `sentimiento_score`,
  `estado_entrega` (enviado/entregado/leido/failed). → **Los tiempos de respuesta son
  derivables** cruzando `created_at` de un mensaje entrante (`remitente="contacto"`) con
  el siguiente mensaje saliente (`remitente` in "agente"/"ia") de la misma conversación.
- **Contactos** (`contacts`): `nombre`/`telefono`/`email`, `anonymized_at` (HABEAS DATA).
- **RAG drafts** (`rag_draft`): máquina de estados propuesto→editado→aprobado/descartado
  (human-in-the-loop, SPEC-019) — proxy de "asistencia IA usada/aceptada", no de venta.
- **Llamadas** (`calls`): `direccion`, `duracion`, `estado`, `resumen` (transcripción
  asíncrona STT local, PLAN-004).
- **NO EXISTE hoy ningún concepto de "conversión"/venta/oportunidad/won en el dominio
  real.** El único pipeline comercial visible es **mock** (`src/mocks/sales.json`,
  `PipelineDonutChart`, SPEC-007/008). → definir "conversión" tiene impacto de alcance
  grande (ver Preguntas abiertas Q1).
- **Frontend**: ya existe `src/pages/AnalyticsPage.tsx` — dashboard "Analítica
  multisectorial" (SPEC-008) **100% mock** (`kpis.json`, `analytics.json`, `sales.json`),
  con `KpiCard`, `RevenueBySectorChart`, `CsatTrendChart`, `PipelineDonutChart`. → este
  objetivo probablemente **conecta/reemplaza esta página con datos reales**, no crea SPA
  desde cero (ver Q3).
- **NO existen endpoints API de analytics/métricas de negocio** (`backend/app/api/`
  tiene conversations, messages, contacts, calls, rag, etc. — ninguno agregado/KPI).
- **Prometheus** (`backend/app/core/metrics.py`, SPEC-022) es observabilidad **técnica**
  (latencia HTTP, RTF STT, IA) para DevOps/THOR — **distinto** de este dashboard de
  negocio para agentes/supervisores. No se toca ni se reutiliza como fuente.
- Patrón establecido de integración SPA↔API real por **feature-flag** (SPEC-020/031).

## Rol (qué experto/agente lo resuelve)

- **DOCTOR STRANGE** — redacta PLAN-007 y las SPEC a partir de este prompt.
- **BLACK PANTHER** — diseño de las consultas de agregación SQL eficientes con RLS por
  tenant (índices, ventanas de tiempo, agregados por canal).
- **CAPTAIN AMERICA** — implementación de endpoints API de métricas + integración SPA.
- **DAREDEVIL** — cableado del frontend (conectar `AnalyticsPage` a datos reales,
  gráficos, estados de carga/vacío/error, accesibilidad AAA).
- **THOR** — verificar que las agregaciones no degraden performance (consultas sobre
  `messages` pueden ser pesadas).
- **BLACK WIDOW** — confirmar que ninguna métrica filtre datos entre tenants (RLS) ni
  exponga PII agregable indebidamente.
- **HAWKEYE** — pruebas de exactitud de los cálculos (fixtures deterministas).

## Acción (verbo único y medible)

**CONSTRUIR** un dashboard de métricas de **negocio** (para el equipo de atención/ventas
y supervisores) que exponga, **por tenant** y con **filtro de rango de fechas**, las
métricas de: (a) **volumen de conversaciones** (totales, por canal, abiertas vs cerradas,
tendencia en el tiempo), (b) **tiempos de respuesta** (primera respuesta y respuesta
promedio, derivados de `messages`), y (c) **conversión** (según la definición que
resuelva Q1). Alimentado por endpoints API de agregación reales (no mock), respetando
RLS estricto por tenant.

## Restricciones (CHECKPOINTS aplicables)

- **Multi-tenant / RLS (ADR-004)**: toda agregación filtra por `tenant_id`; cada tenant
  ve SOLO sus métricas. Ninguna consulta puede cruzar tenants. Asunción explícita.
- **IA local / cero egress (ADR-003/005)**: si alguna métrica usa señales de IA
  (sentimiento, drafts), se leen de columnas ya persistidas; no se hacen llamadas nuevas
  a IA para calcular métricas.
- **C2 (borrado lógico) / HABEAS DATA (SPEC-021)**: las métricas deben excluir o tratar
  correctamente registros soft-deleted y contactos `anonymized_at`; no reintroducir PII
  en agregados exportables.
- **Performance (THOR)**: consultas de agregación sobre `messages`/`conversations` con
  índices adecuados; definir objetivo de latencia (p.ej. p95 del endcoint de KPIs).
- **No romper Prometheus/observabilidad técnica**: este dashboard es de negocio; no se
  mezcla con `/metrics` ni con SPEC-022.
- **Reutilización SPA**: seguir el patrón feature-flag (SPEC-020) y el design system
  existente; no duplicar componentes de gráficos si `AnalyticsPage` ya los tiene.

## Formato de salida esperado

El PLAN/SPEC resultante y su implementación deben producir:

1. **Endpoint(s) API de métricas de negocio** (REST, bajo el contrato OpenAPI existente),
   con respuesta agregada JSON: KPIs de conversaciones, tiempos de respuesta y conversión,
   parametrizados por rango de fechas y opcionalmente por canal.
2. **Capa de servicio de agregación** en el backend (consultas SQL con RLS), testeable de
   forma aislada.
3. **Dashboard en la SPA**: `AnalyticsPage` (o sección nueva) conectada a datos reales por
   feature-flag, con KPIs numéricos, series temporales y desglose por canal; estados de
   carga / vacío / error accesibles (AAA).
4. **Definición documentada de "conversión"** (en un ADR si introduce un campo/evento
   nuevo de dominio) — según resolución de Q1.
5. **Pruebas** con fixtures deterministas que verifiquen la exactitud de cada métrica.
6. Alcance **IN/OUT preliminar** claro (abajo) para que DOCTOR STRANGE no re-investigue.

### Alcance IN/OUT preliminar (para DOCTOR STRANGE)

**IN (probable):**
- Métricas de conversaciones: total, por canal, abiertas/cerradas, tendencia temporal.
- Tiempos de respuesta: primera respuesta y promedio, derivados de `messages` existentes.
- Filtro por rango de fechas (presets + rango custom, ver Q4) y por canal.
- Endpoint(s) API agregados con RLS + servicio + tests + conexión de la SPA por flag.
- Métricas de asistencia IA (opcional/derivado): % de conversaciones con draft aprobado,
  distribución de sentimiento — ya persistidas, bajo costo.

**OUT (probable, salvo que el Lead lo mueva a IN):**
- Definir un pipeline comercial/CRM de ventas completo (etapas, oportunidades, montos)
  si "conversión" resulta requerir un modelo de dominio nuevo grande → sería su propio
  PLAN posterior. Este PLAN-007 se limitaría a una definición mínima de conversión (Q1).
- Sustituir/eliminar la analítica multisectorial mock (SPEC-008) si el Lead la quiere
  conservar en paralelo (Q3).
- Exportación a PDF/CSV, alertas/umbrales, dashboards en tiempo real vía WebSocket
  (salvo que Q2 lo pida) — candidatos a fase posterior.
- Cualquier métrica que requiera datos que hoy no se capturan (p.ej. CSAT real,
  ingresos) sin una fuente definida.

## Criterios de éxito (verificables)

1. Un supervisor de un tenant abre el dashboard y ve, para un rango de fechas elegido:
   nº de conversaciones (total y por canal), % abiertas/cerradas, tiempo de primera
   respuesta y respuesta promedio, y la métrica de conversión definida — **con cifras
   que coinciden con los datos reales de ese tenant** (verificable contra la BD).
2. Un tenant NUNCA ve datos de otro tenant (test de aislamiento RLS que lo demuestra).
3. Los tiempos de respuesta se calculan correctamente sobre casos límite (conversación
   sin respuesta, respuesta de IA vs agente, múltiples idas y vueltas) — cubierto por
   fixtures deterministas en las pruebas de HAWKEYE.
4. El/los endpoint(s) de agregación cumplen el objetivo de latencia acordado (THOR) sobre
   un volumen representativo de mensajes.
5. La SPA muestra estados de carga/vacío/error accesibles (AAA) y respeta el design system.
6. La definición de "conversión" queda documentada (y si añade dominio, en un ADR) y las
   pruebas la validan.
7. Cero regresión en `/metrics` (Prometheus) y en las features previas (#1–#5).

## Preguntas abiertas para el Lead

**Q1 (crítica — define el alcance).** ¿Qué significa **"conversión"** en este CRM hoy?
Opciones que veo, de menor a mayor esfuerzo:
  - (a) **Conversación cerrada** = conversión (usar `estado="cerrada"` que ya existe). Cero
    cambios de dominio, disponible ya. ¿Suficiente como v1?
  - (b) Un **estado/etiqueta nuevo** de conversación (p.ej. "ganada"/"convertida") que el
    agente marca manualmente → añade un campo y UI de marcado (esfuerzo medio).
  - (c) Un **modelo comercial completo** (oportunidad/venta con monto) → esfuerzo grande,
    probablemente su propio PLAN. El pipeline de ventas actual es **solo mock**.
  Recomendación de XAVIER: empezar por (a) o (b) en PLAN-007 y dejar (c) para después.

**Q2.** ¿El dashboard debe ser **tiempo real** (WebSocket, como la bandeja) o basta un
**reporte on-demand / recalculado periódicamente** (más simple y barato)? Recomendación:
on-demand con filtro de fecha para v1.

**Q3.** Ya existe `AnalyticsPage` con analítica **multisectorial mock** (SPEC-008).
¿Este dashboard **reemplaza** esa página con datos reales, la **extiende** (una sección
nueva "Métricas de negocio"), o convive como una **página nueva** separada?

> Asunción explícita (no la dejo implícita): dado que TODO el proyecto es multi-tenant con
> RLS estricto, se asume **por tenant** (cada tenant ve solo sus métricas). Filtros de
> rango de fechas asumidos: presets **hoy / 7 días / 30 días** + **rango custom**
> (confirmar en Q4 si se desea otro set).

**Q4 (menor, confirmable).** ¿Los presets de rango hoy/7d/30d + custom son suficientes, o
se requiere algún periodo adicional (este mes, trimestre, año)?

---

## Respuestas del Lead (vinculantes, resuelven el alcance para DOCTOR STRANGE)

- **Q1 — Conversión:** opción **(a) Conversación cerrada** (`Conversation.estado="cerrada"`).
  Cero cambios de dominio nuevo. La "tasa de conversión" del dashboard = conversaciones
  cerradas / conversaciones totales en el rango elegido. Sin ADR de dominio nuevo (no
  aplica el punto 4 del "Formato de salida esperado" salvo para dejarlo documentado en la
  SPEC misma). El modelo comercial completo (opción c) queda **fuera de alcance**, no se
  abre un PLAN futuro todavía — solo se menciona como posible evolución si el Lead lo pide
  después.
- **Q2 — Modo de datos:** **on-demand con filtro de fecha** (no tiempo real / WebSocket).
  El endpoint de agregación se calcula al vuelo sobre el rango pedido; sin infraestructura
  de push nueva.
- **Q3 — `AnalyticsPage`:** **reemplazar** el contenido mock (`kpis.json`/`analytics.json`/
  `sales.json`, SPEC-008) por datos reales del nuevo endpoint, por feature-flag (mismo
  patrón SPEC-020). No convive con la maqueta ni se crea página separada — la vista final
  es la MISMA ruta/página, con datos reales cuando el flag está ON.
- **Q4 — Presets de fecha:** **hoy / 7 días / 30 días + rango custom** (sin mes/trimestre/
  año adicional por ahora).

Con esto, el alcance IN/OUT de la sección anterior queda CONFIRMADO tal cual (sin el punto
"modelo comercial completo" de OUT, que ya no es candidato a moverse a IN en absoluto para
este PLAN). DOCTOR STRANGE puede proceder a redactar PLAN-007 sin preguntas de alcance
pendientes.
