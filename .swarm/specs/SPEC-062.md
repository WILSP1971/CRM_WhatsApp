# SPEC-062 — Capa de servicio de agregación de métricas de NEGOCIO (`analytics_service`): conversaciones, tiempos de respuesta y conversión bajo RLS efectiva 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: BLACK PANTHER · Colaboran: CAPTAIN AMERICA, THOR, HAWKEYE, BLACK WIDOW, WOLVERINE · Prioridad: ALTA · Tipo: BACKEND/DATOS · Fase: F0
- Deriva de: PLAN-007 (F0, §3.3) · Clasificación: SENSIBLE (`.no-externo`) · ADR-004/ADR-008/ADR-003/ADR-005
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Construir una **capa de servicio de agregación** (`analytics_service`) con funciones **puras y testeables de forma aislada** que calculen, **para un único tenant y un rango de fechas**, las métricas de negocio del dashboard: **(a) volumen de conversaciones** (total, por canal, abiertas/cerradas, serie diaria), **(b) tiempos de respuesta** (primera respuesta y respuesta promedio, derivados de `messages`), y **(c) tasa de conversión** (`cerradas/totales`, Q1(a) — cero dominio nuevo). Opcionalmente, **(d) asistencia IA** (% de conversaciones con borrador RAG aprobado + distribución de sentimiento), leídas de columnas ya persistidas. Todas las consultas se ejecutan **bajo RLS efectiva** (rol `omnicore_app`, `SET LOCAL app.tenant_id` ya fijado por `get_tenant_db`), **sin bypass de RLS**, excluyendo registros soft-deleted (C2) y respetando `anonymized_at` (HABEAS DATA). Sin IA nueva ni egress.

## Contexto

El modelo real (verificado): `Conversation` (`app/models/conversation.py`) tiene `canal` (`CANALES_VALIDOS`), `estado` (`"abierta"`/`"cerrada"` — únicos valores hoy), `created_at`/`updated_at`, soft-delete, RLS por `tenant_id`. `Message` (`app/models/message.py`) tiene `created_at`, `remitente` (`"contacto"`/`"agente"`/`"ia"`), `contenido`, `sentimiento`/`sentimiento_score` (SPEC-018), `estado_entrega`. `rag_draft` tiene la máquina de estados de SPEC-019. **No existe hoy servicio de analytics de negocio.** Los tiempos de respuesta **son derivables** cruzando `created_at` de un entrante (`remitente="contacto"`) con el siguiente saliente (`remitente` in `"agente"`/`"ia"`) de la misma conversación.

**Patrón de RLS (crítico — hallazgo de bug recurrente muy documentado):** este servicio es invocado desde un **endpoint HTTP** (SPEC-063), donde el `tenant_id` ya viene fijado por `get_tenant_db` (`SET LOCAL app.tenant_id` con el `tenant_id` del JWT). A diferencia de los jobs de mantenimiento (`retention_service.run_retention_job` / `call_retention_service.run_call_retention_job`), este servicio **NO** recorre tenants ni fija sesión por su cuenta: recibe una `Session` ya con tenant fijado. **PROHIBIDO** usar rol owner/superusuario o una sesión "de plataforma" sin `tenant_id` — eso reintroduciría el bug de bypass de RLS ya documentado en `app/services/retention_service.py`. `conversations`/`messages`/`rag_draft` están en `TENANT_SCOPED_TABLES` con RLS ENABLE+FORCE; el rol `omnicore_app` es NOSUPERUSER NOBYPASSRLS → una sesión sin tenant ve **cero** filas (fail-closed).

## Alcance

### IN
- **Función(es) de agregación de conversaciones:** total, por `canal`, por `estado` (abiertas/cerradas) y **serie diaria** (`date_trunc('day', created_at)`) dentro de `[desde, hasta]`; solo conversaciones **activas** (soft-delete excluido, C2); ventana definida sobre `Conversation.created_at`.
- **Función(es) de tiempos de respuesta:** **TPR** (primera respuesta: primer saliente `remitente` in `agente`/`ia` posterior al primer entrante `remitente="contacto"`) y **respuesta promedio** (media de las diferencias entrante→siguiente-saliente a lo largo de cada conversación), derivadas de `messages`. Reportan promedio (y opcionalmente mediana/p95). **Casos límite** (implementados y documentados): conversación sin respuesta → **excluida** del promedio (no cuenta como 0); respuesta de IA vs agente → ambas cuentan como saliente (opcionalmente desglosable); múltiples entrantes seguidos → se toma el primer entrante del bloque; conversación con solo salientes → excluida.
- **Función de conversión:** `tasa = cerradas / totales` en el rango (Q1(a)); con `totales=0` → `0` o `null` (documentado), **sin división por cero**.
- **(Opcional) Asistencia IA:** % de conversaciones con al menos un `rag_draft` aprobado (SPEC-019) y distribución de `messages.sentimiento` (positivo/neutral/negativo). Leídas de columnas existentes, **sin IA nueva**. Se incluye si no añade coste/riesgo; se pospone si complica (no bloquea el core).
- **Parámetros:** `desde`/`hasta` (fecha), `canal` opcional. Agregación hecha **en SQL** (no en Python) donde sea razonable, para performance (THOR).
- **Índices** necesarios (o verificación de que existen) para `messages(conversation_id, created_at, remitente)` y `conversations(created_at, canal, estado)` — coordinado con THOR/BLACK PANTHER; migración aditiva si falta alguno.
- Funciones **puras/testeables**: reciben una `Session` (con tenant ya fijado) + parámetros, devuelven estructuras de datos; sin efectos de request/HTTP.

### OUT
- Endpoint HTTP y contrato REST (SPEC-063).
- SPA / feature-flag (SPEC-064).
- Pruebas (SPEC-065) y docs/deploy (SPEC-066).
- Cualquier modelo/campo/evento nuevo de "conversión" (Q1(a): cero dominio nuevo).
- Tiempo real / WebSocket (Q2, fuera).
- Uso de Prometheus / `/metrics` como fuente (es observabilidad técnica, ajena).

## Dependencias
- Depende de SPEC-012 (esquema/RLS), SPEC-025 (contrato `messages`), SPEC-014 (patrón de servicios/endpoints) y del patrón `get_tenant_db` de `app/api/deps.py`. Se ancla en ADR-004/ADR-008 (RLS efectiva) y ADR-003/ADR-005 (IA local — solo se leen columnas ya persistidas). Prerequisito duro de SPEC-063/064/065.

## Requisitos funcionales
- RF-01 El servicio calcula conversaciones total/por canal/por estado/serie diaria dentro del rango, solo del tenant, activas.
- RF-02 El servicio calcula TPR y respuesta promedio derivados de `messages`, tratando correctamente los casos límite (§Alcance IN).
- RF-03 El servicio calcula la tasa de conversión = `cerradas/totales` (Q1(a)), sin división por cero.
- RF-04 (Opcional) El servicio calcula % de drafts aprobados y distribución de sentimiento de columnas existentes, sin IA nueva.
- RF-05 Las funciones son puras/testeables: reciben `Session` (tenant fijado) + parámetros; no fijan sesión ni recorren tenants.

## Requisitos no funcionales
- RNF-47 **RLS efectiva:** toda consulta corre bajo el rol app `omnicore_app` (NOSUPERUSER NOBYPASSRLS) con `app.tenant_id` fijado por `get_tenant_db`; **prohibido** rol owner/superusuario o sesión sin tenant. Cada tenant ve solo sus filas (fail-closed).
- RNF-73 **Performance:** agregación en SQL con índices adecuados; consultas acotadas por rango; preparadas para cumplir el objetivo de latencia p95 que fija THOR en SPEC-065.
- RNF-C2 Soft-delete excluido de todos los conteos; `anonymized_at` respetado (sin reintroducir PII).
- RNF-01 Sin egress; sin inferencia IA nueva (señales de IA leídas de columnas persistidas).

## Criterios de aceptación (verificables)
- [ ] Dada una `Session` con tenant fijado y un rango, el servicio devuelve: conversaciones total/por canal/por estado/serie diaria, coincidentes con la BD (verificable con fixtures).
- [ ] TPR y respuesta promedio se calculan correctamente incluyendo casos límite: sin respuesta (excluida), IA vs agente (ambas salientes), múltiples entrantes seguidos (primer entrante del bloque), solo salientes (excluida).
- [ ] Tasa de conversión = `cerradas/totales`; con `totales=0` no hay división por cero (devuelve 0/`null` documentado).
- [ ] (Opcional) % drafts aprobados y distribución de sentimiento leídos de columnas existentes, sin IA nueva.
- [ ] **RLS efectiva:** con el rol app no-superusuario, una `Session` de tenant A no agrega filas de tenant B (test cross-tenant que falla por RLS, verificado en SPEC-065); el servicio **no** usa rol owner ni sesión sin tenant.
- [ ] Soft-delete excluido; `anonymized_at` respetado; ningún agregado contiene PII individual.
- [ ] Las funciones son invocables de forma aislada (unit test) recibiendo `Session` + parámetros.
- [ ] Índices requeridos existen (o se añaden por migración aditiva); consultas ejecutan en SQL.

## Notas de seguridad (C2/C3)
- C2: todos los conteos excluyen registros inactivos (soft-delete); ningún agregado los cuenta.
- C3: sin secretos en el servicio; configuración (si la hubiera) solo por env.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (sin egress): SQL local sobre PostgreSQL on-prem; cero llamadas externas; cero IA nueva (ADR-003/005). El aislamiento cross-tenant se sostiene en la **RLS efectiva** (ADR-004/008): el `tenant_id` viene del JWT vía `get_tenant_db`; el servicio nunca hace bypass.

## Riesgos
- R-71 (fuga cross-tenant / bypass RLS): el servicio solo corre bajo `get_tenant_db`/rol `omnicore_app`; prohibido rol owner o sesión sin tenant; test cross-tenant (SPEC-065). **Riesgo top-1.**
- R-72 (tiempos de respuesta en casos límite): definición precisa + fixtures deterministas por caso (SPEC-065).
- R-73 (performance sobre `messages`): agregación en SQL + índices; objetivo de latencia THOR (SPEC-065).
- R-75 (PII en agregados): solo agregados; soft-delete/`anonymized_at` respetados; revisión BLACK WIDOW (SPEC-065).
- R-77 (división por cero / rango vacío): manejado (0/`null` documentado).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-007 / `prompt-lab/prompts/PROMPT-007-CRM-ANALYTICS.md`).
