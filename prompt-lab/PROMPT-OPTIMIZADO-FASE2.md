# PROMPT OPTIMIZADO — FASE FUNCIONAL (Entregable #2) · "OmniCore AI"

> Autor: 🧠 XAVIER (Professor X) — Estratega de Prompts (Nivel 1)
> Fecha: 2026-09-16 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo` presente) — PROHIBIDO cualquier modelo/servicio EXTERNO de inferencia o de datos personales.
> Estado: **LISTO PARA DOCTOR STRANGE (PLAN-002)** · Cumple CHECKPOINT C8 (prompt registrado en `prompt-lab/`).
> Precedente: Entregable #1 COMPLETADO (maqueta SPA, Lighthouse Perf 100 / A11y 98, 10 SPECs cerradas de PLAN-001).

---

## 0. Prompt inicial del Lead (transcripción íntegra — NO perder)

> "La fase funcional (backend/IA con modelos locales self-hosted, respetando `.no-externo`)."
>
> Es decir: convertir la maqueta de alta fidelidad ya construida en un **sistema funcional** con
> **backend real** e **IA local** que dé vida a los módulos ya diseñados (bandeja omnicanal, RAG,
> VoiceBot/VoIP, sectores comercial/servicios/manufactura, ERP sync).

---

## 1. Diagnóstico: por qué NO se implementa "todo a la vez"

El objetivo en bruto ("la fase funcional") abarca ~5 subsistemas (omnicanal real, RAG con LLM,
VoiceBot STT/TTS, ERP bidireccional, multi-tenant/auth) cada uno con integraciones externas
inevitables (WhatsApp Business API, SIP/PBX, ERP) y riesgo alto por ser **SENSIBLE**. Intentarlos
juntos maximiza el riesgo y retrasa el primer valor demostrable.

**Recomendación de XAVIER:** entregar un **vertical slice funcional end-to-end** —el camino más
corto que atraviesa TODAS las capas (auth → API → BD → IA local → SPA)— para probar la arquitectura
completa con **1 canal real** y **RAG local** antes de escalar. El resto (VoiceBot STT/TTS, ERP real,
más canales, flujos automatizados) queda planificado como **Fases 3+**.

---

## 2. Ambigüedades detectadas y supuestos resueltos (marcados)

Los ⚠️ son **críticos**: si el Lead no los confirma, deben resolverse ANTES del PLAN-002.

| #   | Ambigüedad                                         | Supuesto adoptado (SUP-2x)                                                                                                                                                                                                          | Criticidad |
| --- | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| B1  | ¿"Fase funcional" = todo el backend + toda la IA?  | **SUP-21 ⚠️** El Entregable #2 es un **vertical slice** end-to-end: Bandeja omnicanal (1 canal real) + RAG local + persistencia + auth multi-tenant aislado. VoiceBot, ERP real y canales extra → Fases 3+.                        | Crítica    |
| B2  | ¿Qué canal real primero?                           | **SUP-22 ⚠️** Se implementa **WebChat propio** (widget embebible, WebSocket) como canal #1 por ser 100% self-hosted y sin dependencia de aprobación de Meta. WhatsApp Business API se integra en Fase 3 (necesita cuenta/WABA/BSP). | Crítica    |
| B3  | ¿IA local realmente sin ningún externo?            | **SUP-23 ⚠️** LLM y embeddings **100% self-hosted** (Ollama/vLLM + modelo abierto). Cero llamadas de inferencia a terceros. WhatsApp/SIP se permiten solo como CANAL de transporte, nunca para procesar/inferir contenido.         | Crítica    |
| B4  | ¿Hardware para el LLM local?                        | **SUP-24 ⚠️** Se asume **GPU disponible on-prem** (≥16 GB VRAM) o, en su defecto, CPU con modelo cuantizado 7–8B (Q4). El modelo por defecto será **Qwen2.5-7B-Instruct** (o Llama-3.1-8B) y embeddings **nomic-embed-text**.     | Crítica    |
| B5  | ¿Multi-tenant: fila compartida o BD por tenant?    | **SUP-25** Aislamiento por **`tenant_id` + Row-Level Security (RLS) de PostgreSQL** (pool-model). BD-por-tenant queda como opción futura para clientes enterprise. Todo query lleva `tenant_id`; RLS lo fuerza a nivel de motor.    | Media      |
| B6  | ¿PHI/datos clínicos?                                | **SUP-26** No es un CRM clínico; los datos personales son de contacto/comercial (nombre, teléfono, historial de conversación). Aplica **HABEAS DATA (Ley 1581 Col.)** y buenas prácticas GDPR, no HIPAA/PHI.                        | Media      |
| B7  | ¿Se reescribe la SPA o se conecta la existente?    | **SUP-27** Se **conserva** la SPA del Entregable #1 y se **reemplazan progresivamente los mocks** (`src/mocks/*.json`) por endpoints reales, respetando los contratos de tipos ya definidos en `src/lib/types.ts`.                  | Media      |
| B8  | ¿Envío/recepción real de mensajes en el slice?     | **SUP-28** Sí: el WebChat permite conversación bidireccional real (cliente ⇄ agente/IA) con persistencia y borrador RAG "human-in-the-loop" (el agente aprueba antes de enviar). Auto-respuesta autónoma → Fase posterior.         | Media      |
| B9  | ¿Sentimiento/intención en el slice?                | **SUP-29** El análisis de sentimiento del slice se hace con el **LLM local** (clasificación) sobre el mensaje entrante; detección de intención avanzada y VoiceBot quedan en Fase 3.                                                | Baja       |
| B10 | ¿Despliegue?                                        | **SUP-2A** Empaquetado **on-prem con Docker Compose** (un solo host para el slice); Kubernetes/HA se evalúa cuando el volumen lo justifique (Fase 3+).                                                                              | Baja       |

---

## 3. PROMPT PROFESIONAL (marco C.R.A.F.T.)

### 3.1 Objetivo (Acción — verbo único y medible)

**Construir** un **vertical slice funcional end-to-end** de "OmniCore AI" que dé vida real a la
maqueta: un backend self-hosted con persistencia, autenticación multi-tenant aislada, un canal de
mensajería real (WebChat) y **RAG con IA 100% local**, reemplazando los mocks de la SPA existente por
APIs reales — **sin ninguna llamada de inferencia a servicios externos** (política SENSIBLE).

### 3.2 Rol (quién lo resuelve — flujo del enjambre)

- **DOCTOR STRANGE** → PLAN-002 y SPECs derivadas.
- **CAPTAIN AMERICA** → implementación (coordina backend + integración SPA).
- **BLACK PANTHER** → backend/API, BD, RAG, orquestación del LLM local.
- **DAREDEVIL** → integración frontend (reemplazo de mocks por clientes de API en la SPA).
- **WOLVERINE** → calidad · **HAWKEYE** → pruebas (unit/integración/e2e) · **THOR** → performance del LLM/RAG.
- **BLACK WIDOW** → seguridad: aislamiento multi-tenant, cero externos de inferencia, secretos, HABEAS DATA.
- **QUICKSILVER** → empaquetado Docker Compose y despliegue on-prem (con aprobación del Lead).

### 3.3 Contexto

- Producto: CRM omnicanal multi-tenant. Entregable #1 (maqueta SPA React/Vite/TS) **ya publicado**
  en GitHub con datos mock y Lighthouse Perf 100 / A11y 98.
- **Contratos existentes a respetar** (no romper la SPA): `src/lib/types.ts`, y las formas de
  `src/mocks/*.json` — p.ej. `tenants` (`id`, `sector`, `name`, `initials`, `planLabel`),
  `conversations` (`id`, `contactId`, `channel`, `sentiment`, `status`, `unreadCount`, `messages[]`
  con `direction`/`text`/`sentAt`/`status`), `rag.citations` (`source`, `excerpt`, `similarityScore`,
  `conversationId`). Los endpoints reales deben **emitir estas mismas formas** (o versionarlas en un
  contrato OpenAPI y adaptar la SPA de forma controlada).
- **Clasificación SENSIBLE** (`.no-externo`): PROHIBIDO OpenAI/Anthropic/Google/cualquier API de
  inferencia de terceros. La IA y el procesamiento de datos personales/mensajería son **on-prem**.
  Verificable con `scripts/puede-modelo-externo.sh` y `check-externos.sh`.
- Integraciones externas permitidas SOLO como **canal de transporte** del negocio (WhatsApp Business
  API, PBX/SIP) — nunca para inferencia. En el slice #1 se evita incluso eso usando **WebChat propio**.

### 3.4 Alcance del Entregable #2

**IN (vertical slice funcional):**

1. **Auth + Multi-tenant:** login/JWT (o sesión), usuarios por tenant, aislamiento por `tenant_id`
   con **RLS de PostgreSQL**. Toda entidad transaccional lleva `tenant_id`.
2. **Persistencia (PostgreSQL):** tenants, usuarios, contactos, conversaciones, mensajes, documentos
   RAG y embeddings. **Borrado lógico** (Activo/Inactivo) en entidades transaccionales (CHECKPOINT C2).
3. **Canal real — WebChat propio:** widget embebible + WebSocket; recepción y envío bidireccional de
   mensajes con persistencia; la Bandeja omnicanal de la SPA muestra conversaciones **reales**.
4. **RAG local end-to-end:** ingesta de documentos (PDF/MD/DOCX/TXT) → chunking → **embeddings
   locales** → vector store local → recuperación top-k → **generación de borrador con LLM local**,
   con **citas trazables** (source + excerpt + score) idénticas al contrato `rag.json`.
5. **IA local self-hosted:** LLM abierto vía Ollama/vLLM para (a) borrador de respuesta RAG y
   (b) clasificación de sentimiento del mensaje entrante. Embeddings locales. **Cero red externa de inferencia.**
6. **Human-in-the-loop:** el borrador RAG se muestra al agente ("Insertar borrador"); el agente
   aprueba/edita antes de enviar. Nada se envía autónomamente al cliente en este slice.
7. **Integración con la SPA existente:** reemplazo progresivo de mocks por un cliente de API tipado;
   contrato **OpenAPI** publicado; feature-flag para alternar mock/real durante la transición.
8. **Observabilidad mínima:** logs estructurados, health-checks, métricas de latencia RAG y trazas
   de "cero salida externa" (evidencia auditable).
9. **Empaquetado on-prem:** `docker-compose.yml` con API, PostgreSQL(+pgvector), Redis, Ollama/vLLM.

**OUT (Fases 3+ — fuera de este entregable):**

- **VoiceBot / VoIP:** STT local (Whisper self-hosted) + TTS local + SIP/PBX. (Solo se menciona; no es el slice #1.)
- **ERP real** (sincronización bidireccional inventario/pedidos/órdenes).
- **Canales adicionales:** WhatsApp Business API, Instagram DM, Messenger (WABA/BSP en Fase 3).
- **Auto-respuesta autónoma** de la IA sin aprobación humana.
- **Flujos automatizados / workflows**, campañas, y analítica avanzada en tiempo real.
- **HA/Kubernetes**, escalado horizontal multi-nodo (se evalúa por volumen).

### 3.5 Requisitos funcionales (RF)

- **RF-01** Un usuario se autentica y solo ve datos de **su** tenant (aislamiento verificable).
- **RF-02** Un visitante escribe en el **WebChat**; el mensaje se persiste y aparece en tiempo real en la Bandeja del agente del tenant correspondiente.
- **RF-03** El agente responde desde la Bandeja; el mensaje llega al visitante por WebSocket y queda persistido.
- **RF-04** Al abrir una conversación, el **panel RAG** consulta documentos del tenant y devuelve un borrador con **≥3 citas** (source + excerpt + `similarityScore`).
- **RF-05** El agente puede **insertar/editar** el borrador antes de enviarlo (human-in-the-loop).
- **RF-06** Se pueden **ingerir documentos** por tenant (upload) y quedan disponibles para RAG tras indexarse.
- **RF-07** El mensaje entrante recibe una etiqueta de **sentimiento** calculada por el LLM local.
- **RF-08** La SPA consume APIs reales (no mocks) para bandeja, hilo, contacto 360°, RAG y tenants, respetando los contratos de tipo.
- **RF-09** Existe **contrato OpenAPI** navegable y un cliente tipado en la SPA.

### 3.6 Requisitos NO funcionales (RNF)

- **RNF-01 Seguridad de datos personales (HABEAS DATA / GDPR-like):** cifrado en tránsito (TLS) y en
  reposo para datos personales; **secretos en variables de entorno / secret manager**, nunca en texto
  plano ni en el repo (CHECKPOINT C3); **borrado lógico** (C2); minimización y retención configurable.
- **RNF-02 Aislamiento multi-tenant:** RLS activo; ningún query cruza tenants; test automatizado que lo demuestre.
- **RNF-03 IA 100% local:** cero llamadas de inferencia a terceros; verificable por bloqueo de red de
  egress en el contenedor de IA + `check-externos.sh` + prueba de red vacía hacia dominios externos.
- **RNF-04 Rendimiento RAG:** respuesta de borrador RAG **p95 ≤ 6 s** (con GPU) / degradación documentada
  en CPU; recuperación vectorial **p95 ≤ 300 ms**; API REST no-IA **p95 ≤ 200 ms**.
- **RNF-05 Escalabilidad:** arquitectura stateless en la API (estado en BD/Redis) para permitir réplicas; colas para ingesta/indexado asíncrono.
- **RNF-06 Observabilidad:** logs estructurados con `tenant_id`/`trace_id`, health-checks (`/healthz`), métricas de latencia IA/RAG.
- **RNF-07 Mantenibilidad:** contrato OpenAPI como fuente de verdad; migraciones versionadas de BD; código tipado.
- **RNF-08 Portabilidad on-prem:** todo levanta con `docker compose up` sin acceso a internet para inferencia.

### 3.7 Restricciones DURAS (obligatorias)

- **R-01 SENSIBLE / `.no-externo`:** ningún modelo/servicio EXTERNO de inferencia ni de procesamiento
  de datos personales. WhatsApp/SIP permitidos SOLO como canal de transporte (y quedan fuera del slice #1).
- **R-02 Secretos:** cero secretos en texto plano; variables de entorno / secret manager (C3).
- **R-03 Borrado lógico:** nada de DELETE físico en entidades transaccionales; Activo/Inactivo (C2).
- **R-04 Multi-tenant aislado:** todo dato pertenece a un tenant; RLS obligatorio; sin fugas cross-tenant.
- **R-05 No romper el Entregable #1:** la SPA sigue compilando/pasando su suite; la migración mock→real es progresiva y reversible por feature-flag.
- **R-06 Flujo del enjambre:** PLAN-002 aprobado por el Lead antes de SPECs; cada SPEC con criterios verificables (C4); cambios sensibles con aprobación explícita (C6).

### 3.8 Formato de salida esperado

- Servicio backend ejecutable con `docker compose up` (API + PostgreSQL/pgvector + Redis + Ollama/vLLM).
- **OpenAPI** (`/docs`) + colección de ejemplos.
- Migraciones de BD versionadas y seed de datos ficticios por tenant.
- SPA existente conectada a las APIs reales (mocks reemplazados, feature-flag documentado).
- README de operación on-prem (variables de entorno, modelos a descargar localmente, cómo levantar).
- Evidencia de "cero externos de inferencia" (logs/egress bloqueado + script) y de aislamiento multi-tenant.

---

## 4. Stack LOCAL recomendado (self-hosted / on-prem) — justificación

| Capa                  | Recomendación                                                    | Justificación breve                                                                                             |
| --------------------- | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Backend/API**       | **FastAPI (Python 3.12)**                                        | Ecosistema de IA/RAG nativo (transformers, sentence-transformers, LangChain/LlamaIndex si se usa), async, OpenAPI automático. Alternativa: NestJS si el equipo es TS-first. |
| **Base de datos**     | **PostgreSQL 16**                                               | Robusto, transaccional, **RLS nativo** para aislamiento multi-tenant, borrado lógico trivial.                  |
| **Vector store**      | **pgvector** (extensión de PostgreSQL)                          | Mantiene vectores y datos en **un solo motor** → menos piezas, backups unificados, joins tenant-aware con RLS. Qdrant self-hosted como alternativa si el volumen vectorial crece mucho. |
| **LLM local**         | **Ollama** (o **vLLM** para más throughput) + **Qwen2.5-7B-Instruct** / Llama-3.1-8B (cuantizado Q4 en CPU) | Self-hosted, API HTTP local sencilla, modelos abiertos con buena calidad en español; vLLM si se necesita concurrencia alta con GPU. |
| **Embeddings**        | **nomic-embed-text** vía Ollama (o `sentence-transformers` local, p.ej. `multilingual-e5`) | 100% local, buen rendimiento multilingüe (es-CO), sin salir a internet.                                         |
| **RAG**               | Pipeline propio (ingesta→chunking→embeddings→pgvector→top-k→LLM) o **LlamaIndex** self-hosted | Control total, trazabilidad de citas (contrato `rag.json`), sin dependencias SaaS.                             |
| **Colas/eventos**     | **Redis** (+ RQ/Celery o arq)                                   | Ingesta/indexado asíncrono, pub/sub para WebChat en tiempo real, rate-limit.                                    |
| **Tiempo real**       | **WebSocket** (nativo FastAPI) + Redis pub/sub                  | WebChat bidireccional y push a la Bandeja sin polling.                                                          |
| **Auth**              | **JWT + RLS**; hashing Argon2/bcrypt                            | Multi-tenant aislado; secretos en env (C3).                                                                    |
| **Contenedores**      | **Docker Compose**                                              | Despliegue on-prem reproducible en un host; base para K8s futuro.                                              |
| **Egress control**    | Red Docker sin salida para el contenedor de IA/BD               | Garantía técnica de "cero externos de inferencia" (RNF-03).                                                    |
| **Observabilidad**    | Logs estructurados (structlog) + `/healthz` + métricas Prometheus (local) | Latencia RAG/IA, trazas por tenant, health.                                                                    |

**Conexión con la SPA existente:** se publica **OpenAPI**; la SPA reemplaza cada archivo de
`src/mocks/*.json` por un fetch tipado que devuelve la **misma forma** definida en `src/lib/types.ts`
(o un adaptador). Se usa un **feature-flag** (`VITE_USE_REAL_API`) para alternar mock/real y migrar
módulo por módulo sin romper la maqueta ni su suite de tests.

---

## 5. Criterios de éxito MEDIBLES (Entregable #2)

| ID        | Criterio                                                                                                | Cómo se verifica                                                                                     |
| --------- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **CE-21** | **Cero llamadas salientes de inferencia a terceros** (auditable)                                        | Contenedor de IA con egress bloqueado + `check-externos.sh` + captura de red sin dominios externos.  |
| **CE-22** | **Aislamiento multi-tenant probado**: ningún dato/consulta cruza tenants                                 | Test automatizado (HAWKEYE) que intenta acceso cross-tenant y falla por RLS; revisión BLACK WIDOW.   |
| **CE-23** | **RAG end-to-end funcional**: borrador con ≥3 citas trazables (source+excerpt+score) desde docs del tenant | Prueba e2e: ingesta de doc → pregunta → borrador citado; latencia **p95 ≤ 6 s** (GPU).               |
| **CE-24** | **WebChat real bidireccional**: mensaje del visitante persiste y aparece en la Bandeja; respuesta llega  | Prueba e2e cliente⇄agente con persistencia verificada en BD.                                          |
| **CE-25** | **Seguridad de datos personales**: secretos fuera del código (C3), borrado lógico (C2), TLS             | Escaneo BLACK WIDOW (sin secretos), verificación de flags Activo/Inactivo y de cifrado en tránsito.  |
| **CE-26** | **SPA conectada** a APIs reales sin romper el Entregable #1                                              | Suite del front verde + recorrido con `VITE_USE_REAL_API=true`; contrato OpenAPI válido.             |
| **CE-27** | **Cobertura de tests** ≥ 80% en backend (dominio + RAG + auth/RLS)                                       | Reporte de cobertura (HAWKEYE); tests unit+integración+e2e.                                           |
| **CE-28** | **Despliegue on-prem reproducible**: `docker compose up` levanta todo el slice sin internet de inferencia | Arranque limpio en host aislado; health-checks verdes.                                                |
| **CE-29** | **Aprobación explícita del Lead** del slice funcional                                                    | Revisión del Lead.                                                                                    |

---

## 6. Preguntas abiertas clave para el Lead (5)

1. **Hardware para el LLM local (⚠️ SUP-24):** ¿hay **GPU on-prem** disponible y con cuánta **VRAM**
   (p.ej. ≥16 GB permite 7–8B fluido; sin GPU trabajaríamos con modelo cuantizado en CPU y latencias mayores)?
2. **Canal real #1 (⚠️ SUP-22):** ¿confirmas **WebChat propio** como primer canal (self-hosted, sin
   dependencia de Meta), o el negocio exige **WhatsApp Business API** desde el slice #1 (requiere WABA/BSP y aprobación)?
3. **Volumen esperado:** ¿cuántos **tenants**, **agentes concurrentes** y **mensajes/día** debemos
   dimensionar? Esto define GPU vs CPU, réplicas y si pgvector basta o conviene Qdrant.
4. **Cumplimiento (SUP-26):** ¿basta **HABEAS DATA (Ley 1581 Colombia) + buenas prácticas GDPR**, o hay
   requisitos adicionales (retención, ubicación del dato, derecho al olvido, auditoría) que deban entrar como RNF?
5. **Modelo abierto preferido:** ¿alguna preferencia/veto de **modelo** (Qwen2.5 vs Llama-3.1 vs Mistral)
   o de licencia, y hay ya infraestructura on-prem definida (SO, orquestador, backups) para el despliegue?

---

## 7. Siguiente paso en el flujo

Entregar este prompt a **🔮 DOCTOR STRANGE** para el **PLAN-002** (`.swarm/PLAN-002.md`), que el Lead
deberá aprobar ("APROBADO PLAN-002") antes de generar SPECs. Cumple CHECKPOINT **C8**.
