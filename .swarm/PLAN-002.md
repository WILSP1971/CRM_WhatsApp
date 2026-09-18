# PLAN-002 — Fase funcional "OmniCore AI" (Entregable #2): backend real + IA LOCAL self-hosted

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Fecha: 2026-09-16 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo` presente) — PROHIBIDO cualquier modelo/servicio EXTERNO de inferencia o de procesamiento de datos personales.
> Origen: `prompt-lab/PROMPT-OPTIMIZADO-FASE2.md` (🧠 XAVIER) · Estado: **PROPUESTA** (espera "APROBADO PLAN-002")
> Regla de oro: este PLAN **NO genera SPECs**. Las SPECs se crean SOLO tras la aprobación explícita del Lead.
> Precedente: Entregable #1 (maqueta SPA) **COMPLETADO y publicado** (Lighthouse Perf 100 / A11y 98, 10 SPECs cerradas de PLAN-001).

---

## 1. Objetivo y contexto

### Objetivo

Construir un **vertical slice funcional end-to-end** de "OmniCore AI" que dé vida real a la maqueta:
un **backend self-hosted** con persistencia y autenticación **multi-tenant aislada**, un **canal de
mensajería real (WebChat propio)** y **RAG con IA 100% local**, reemplazando progresivamente los mocks
de la SPA existente por APIs reales — **sin ninguna llamada de inferencia a servicios externos**
(política SENSIBLE). El slice atraviesa TODAS las capas (auth → API → BD → IA local → SPA) con **1 canal
real** para validar la arquitectura completa antes de escalar.

### Contexto y relación con el Entregable #1

- El Entregable #1 es una **maqueta SPA** (React/Vite/TS) navegable con datos 100% mock (`src/mocks/*.json`),
  publicada en GitHub, con contratos de tipo ya definidos en `src/lib/types.ts` y IA **representada
  visualmente** (no real). PLAN-001 cerró SPEC-001..SPEC-010.
- El Entregable #2 **conserva** esa SPA y **reemplaza los mocks por APIs reales** de forma progresiva y
  reversible (feature-flag `VITE_USE_REAL_API`), respetando los contratos existentes (`tenants`,
  `conversations`, `messages[]`, `rag.citations` con `source`/`excerpt`/`similarityScore`). La maqueta
  **no se rompe**: sigue compilando y pasando su suite en modo mock.
- Clasificación **SENSIBLE** (`.no-externo`): la IA (LLM, embeddings; y STT/TTS a futuro) y el
  procesamiento de datos personales/mensajería son **100% on-prem**. Se prohíbe OpenAI/Anthropic/Google/
  cualquier API de inferencia de terceros. Los datos son de contacto/comercial (HABEAS DATA — Ley 1581
  Colombia + buenas prácticas GDPR-like), **no** PHI/HIPAA.
- Supuestos vinculantes heredados de XAVIER: SUP-21..SUP-2A (ver §11 "Preguntas abiertas al Lead").

---

## 2. Alcance IN / OUT

### IN — entra en el vertical slice #2

1. **Auth + Multi-tenant aislado:** login/JWT, usuarios por tenant, aislamiento por `tenant_id` con
   **Row-Level Security (RLS) de PostgreSQL 16**. Toda entidad transaccional lleva `tenant_id`; el motor
   fuerza el aislamiento (pool-model, no BD-por-tenant).
2. **Persistencia (PostgreSQL 16 + pgvector):** tenants, usuarios, contactos, conversaciones, mensajes,
   documentos RAG, chunks y embeddings. **Borrado lógico** Activo/Inactivo (C2) en entidades transaccionales.
3. **Canal real — WebChat propio self-hosted:** widget embebible + **WebSocket bidireccional**; recepción
   y envío en tiempo real con **persistencia**; la Bandeja omnicanal de la SPA muestra conversaciones **reales**.
4. **RAG local end-to-end:** ingesta de documentos (PDF/MD/DOCX/TXT) → chunking → **embeddings locales** →
   **pgvector** → recuperación top-k → **generación de borrador con LLM local**, con **citas trazables**
   (`source` + `excerpt` + `similarityScore`) en el mismo contrato que `rag.json`.
5. **IA local self-hosted:** LLM abierto vía **Ollama/vLLM** para (a) borrador de respuesta RAG y
   (b) **clasificación de sentimiento** del mensaje entrante; **embeddings locales**. **Cero red externa de inferencia.**
6. **Human-in-the-loop:** el borrador RAG se muestra al agente; el agente **revisa/edita/aprueba** antes
   de enviar. Nada se envía autónomamente al cliente en este slice.
7. **Integración con la SPA existente:** reemplazo progresivo de mocks por cliente de API tipado; contrato
   **OpenAPI** publicado; **feature-flag** para alternar mock/real por módulo, sin romper el Entregable #1.
8. **Seguridad de datos personales:** TLS en tránsito, cifrado en reposo de datos personales, secretos en
   env/secret manager (C3), minimización y retención configurable, HABEAS DATA/GDPR-like.
9. **Observabilidad mínima:** logs estructurados (`tenant_id`/`trace_id`), `/healthz`, métricas de latencia
   RAG/IA y **evidencia auditable de "cero salida externa"**.
10. **Empaquetado on-prem:** `docker-compose.yml` con API + PostgreSQL(+pgvector) + Redis + Ollama/vLLM;
    **contenedor de IA con egress de red bloqueado** y auditable.

### OUT — NO entra en este slice (Fases 3+)

- **VoiceBot / VoIP:** STT local (Whisper self-hosted) + TTS local + SIP/PBX. (Solo se menciona.)
- **ERP real:** sincronización bidireccional inventario/pedidos/órdenes.
- **Canales adicionales:** WhatsApp Business API, Instagram DM, Messenger (WABA/BSP en Fase 3).
- **Auto-respuesta autónoma** de la IA sin aprobación humana.
- **Flujos/workflows automatizados**, campañas, analítica avanzada en tiempo real.
- **HA/Kubernetes**, escalado horizontal multi-nodo (se evalúa por volumen).
- **Detección de intención avanzada** más allá del sentimiento básico del mensaje.

> **Muy claro:** el slice #2 entrega **1 canal real (WebChat)**, **RAG local con citas** y **multi-tenant
> con RLS**. Todo lo demás (voz, ERP, más canales, automatización) es explícitamente Fase 3+.

---

## 3. Arquitectura de referencia

### 3.1 Componentes y comunicación

```
                          ┌───────────────────────────────────────────────────────┐
   Visitante WebChat      │                   HOST ON-PREM (Docker Compose)        │
   (widget embebible)     │                                                        │
        │  WSS/HTTPS       │   ┌──────────────┐        ┌───────────────────────┐   │
        └─────────────────┼──►│  API FastAPI  │◄──────►│  Redis (colas+pubsub) │   │
                          │   │  (stateless)  │        └───────────────────────┘   │
   SPA OmniCore AI        │   │  REST+WS      │              ▲   ▲                  │
   (Entregable #1)        │   │  OpenAPI /docs│              │   │ pub/sub WebChat  │
        │  HTTPS + JWT     │   └───┬──────┬────┘      cola ingesta/indexado         │
        └─────────────────┼──────►│      │                  │                       │
                          │       │      │ SQL (RLS)        │  jobs asíncronos     │
                          │       │   ┌──▼───────────────────────────────────┐     │
                          │       │   │ PostgreSQL 16 + pgvector              │     │
                          │       │   │ RLS por tenant_id · borrado lógico    │     │
                          │       │   │ tenants/users/contacts/conversations/ │     │
                          │       │   │ messages/documents/chunks/embeddings  │     │
                          │       │   └───────────────────────────────────────┘     │
                          │       │                                                  │
                          │       │  HTTP local (127.0.0.1 / red interna)            │
                          │   ┌───▼─────────────────────────────────────────┐       │
                          │   │  CONTENEDOR IA (Ollama/vLLM)                 │       │
                          │   │  LLM local (Qwen2.5-7B / Llama-3.1-8B)       │       │
                          │   │  Embeddings (nomic-embed / e5)               │       │
                          │   │  ⛔ EGRESS DE RED BLOQUEADO (internal only)  │       │
                          │   └─────────────────────────────────────────────┘       │
                          │                                                        │
                          │   Observabilidad: structlog + /healthz + Prometheus    │
                          └───────────────────────────────────────────────────────┘
                          ⛔ = sin salida a internet; solo red interna Docker
```

- **API FastAPI (stateless):** expone REST (OpenAPI en `/docs`) + WebSocket. Estado en PostgreSQL/Redis
  para permitir réplicas. Valida JWT, inyecta `tenant_id` en el contexto de sesión de BD (RLS).
- **PostgreSQL 16 + pgvector:** único motor para datos y vectores; **RLS** fuerza aislamiento por tenant;
  borrado lógico Activo/Inactivo; migraciones versionadas.
- **Redis:** colas para ingesta/indexado asíncrono y **pub/sub** para push del WebChat a la Bandeja.
- **Contenedor IA (Ollama/vLLM):** LLM + embeddings locales; **red interna sin egress**; la API le habla
  por HTTP interno. Es el único que ejecuta inferencia y **no puede salir a internet**.
- **SPA (Entregable #1):** consume REST+WS reales tras el feature-flag; contratos de `types.ts` respetados.

### 3.2 Bloqueo de egress del contenedor de IA (garantía técnica de "cero externos")

- El contenedor de IA se conecta **solo** a una **red Docker interna** (`internal: true`), **sin** puente
  a la red por defecto ni acceso a internet. No expone ni consume puertos hacia el exterior.
- Reglas de firewall a nivel host (iptables/nftables) que **DROP** cualquier tráfico saliente originado
  por el contenedor de IA hacia rangos no privados (defensa en profundidad, por si la red Docker cambiara).
- Sin variables de proxy/DNS que apunten a resolutores externos para ese contenedor; DNS interno o vacío.
- Los modelos se **descargan y montan localmente** (volumen), nunca se hace `pull` en runtime hacia internet.

### 3.3 Auditoría "cero externos" del lado backend (equivalente a `check:externos` del front)

- **`check-externos-backend.sh`** (nuevo, análogo al `check:externos` de la SPA): escanea código/config
  del backend buscando URLs/dominios externos, SDKs de IA de terceros y endpoints de inferencia remota;
  falla el CI si aparece cualquiera. Reutiliza el criterio de `scripts/puede-modelo-externo.sh`.
- **Prueba de egress vacío (HAWKEYE):** desde el contenedor de IA se intenta alcanzar dominios externos
  (p.ej. `api.openai.com`, `8.8.8.8`) y **debe fallar** (timeout/deny); evidencia registrada en CI.
- **Captura de red / trazas:** durante una corrida RAG e2e, se verifica (netstat/pcap o log de conexiones)
  que **no** hay conexiones salientes del contenedor de IA a IPs públicas.
- **Revisión BLACK WIDOW:** confirma egress bloqueado, ausencia de SDKs externos y secretos en env (C3).

---

## 4. Fases y entregables

| Fase   | Nombre                                   | Entregables clave                                                                                                                                                                    |
| ------ | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **F0** | Infra base + Docker Compose + CI         | `docker-compose.yml` (API, PostgreSQL/pgvector, Redis, IA); red interna sin egress para IA; esqueleto FastAPI; `/healthz`; CI backend (lint+typecheck+test+`check-externos-backend.sh`); `.env.example`. |
| **F1** | Datos: esquema + RLS + migraciones       | Modelo de datos multi-tenant; migraciones versionadas (Alembic); **políticas RLS** por `tenant_id`; borrado lógico Activo/Inactivo (C2); `pgvector` habilitado; seed ficticio por tenant. |
| **F2** | Auth + multi-tenant                      | Login/JWT, hashing Argon2/bcrypt; middleware que inyecta `tenant_id` en la sesión (fuerza RLS); usuarios/roles por tenant; secretos en env (C3).                                     |
| **F3** | API core + WebChat WebSocket             | Endpoints REST (tenants, contactos, conversaciones, mensajes, contacto 360°); **WebSocket bidireccional** + Redis pub/sub; persistencia de mensajes; OpenAPI publicado.             |
| **F4** | IA local: Ollama + embeddings + RAG      | Ollama/vLLM operativo con modelo local; embeddings locales; ingesta→chunking→pgvector→top-k; **pipeline RAG** que genera borrador con **≥3 citas trazables**; egress IA verificado. |
| **F5** | Sentimiento + borrador human-in-the-loop | Clasificación de **sentimiento** del mensaje entrante con LLM local; endpoint de borrador RAG; flujo de **revisar/editar/aprobar** antes de enviar (nada autónomo).                 |
| **F6** | Integración SPA (feature-flag)           | Cliente de API tipado en la SPA; **feature-flag** `VITE_USE_REAL_API`; reemplazo módulo a módulo de mocks por endpoints reales respetando contratos; adaptadores donde haga falta.  |
| **F7** | Seguridad + datos personales             | TLS; cifrado en reposo de datos personales; retención/minimización; HABEAS DATA/GDPR-like; barrido BLACK WIDOW (secretos, cross-tenant, egress); evidencia auditable.               |
| **F8** | Pruebas + carga (THOR) + observabilidad  | Tests unit/integración/e2e (auth/RLS/RAG/WebChat); **test cross-tenant que falla por RLS**; carga/latencia RAG (THOR, p95); logs estructurados, `/healthz`, métricas Prometheus.    |
| **F9** | Docs + runbook + deploy                  | README on-prem (env, modelos a descargar localmente, `docker compose up`); runbook de operación/incidentes; colección de ejemplos OpenAPI; deploy on-prem (QUICKSILVER, con aprobación). |

---

## 5. Dependencias entre fases y ruta crítica

- **F0** habilita todo (infra + CI). Ninguna fase arranca sin F0.
- **F1** depende de F0 y es **prerequisito duro** de F2–F5 (sin esquema/RLS no hay auth aislada ni persistencia).
- **F2** depende de F1; prerequisito de F3–F5 (todo endpoint opera bajo un tenant autenticado).
- **F3** depende de F2; habilita el canal real y la persistencia de mensajes (base de F5 y F6).
- **F4** depende de F1 (pgvector/esquema) y F0 (contenedor IA); es prerequisito de F5 (borrador RAG).
  Puede avanzar en **paralelo** a F3 una vez cerrada F2 (comparten solo el esquema/tenant).
- **F5** depende de F3 (conversaciones/mensajes) y F4 (RAG + LLM); integra sentimiento y human-in-the-loop.
- **F6** depende de F3 y F5 (necesita endpoints reales y borradores) para reemplazar mocks sin romper la SPA.
- **F7** transversal: se diseña desde F1/F2 (RLS, secretos, borrado lógico) y se **cierra** auditando el conjunto.
- **F8** depende de que F2–F6 estén completas (prueba el slice completo, incluida carga THOR).
- **F9** cierra: docs/runbook/deploy tras F7/F8.

**Ruta crítica:** `F0 → F1 → F2 → F3 → {F4} → F5 → F6 → F7/F8 → F9`
(con F4 en paralelo a F3 tras F2; F7 transversal y consolidada al final).

---

## 6. Riesgos y mitigaciones

| #        | Riesgo                                                                                          | Impacto                         | Mitigación                                                                                                                                                          |
| -------- | ---------------------------------------------------------------------------------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **R-21** | **Hardware GPU/VRAM insuficiente** para el LLM local (7–8B).                                    | Alto (bloquea IA / latencia)    | **Fallback a CPU con modelo cuantizado Q4** (Qwen2.5-7B/Llama-3.1-8B Q4); dimensionar por volumen; documentar degradación de latencia; parametrizar modelo por env. |
| **R-22** | **Fuga de egress del contenedor de IA** (rompe SENSIBLE / `.no-externo`).                       | Alto (rompe política)           | Red Docker `internal`; firewall host DROP saliente; **`check-externos-backend.sh`** + prueba de egress vacío en CI; revisión BLACK WIDOW; modelos montados localmente. |
| **R-23** | **RLS mal configurado** → fuga cross-tenant.                                                    | Alto (privacidad / R-04)        | RLS `FORCE`; `tenant_id` obligatorio en toda tabla transaccional; **test automatizado cross-tenant que DEBE fallar** por RLS (CE-22); revisión BLACK WIDOW/HAWKEYE.   |
| **R-24** | **Latencia RAG** por encima del objetivo (recuperación + generación).                          | Medio (UX / CE-23)              | Índice pgvector adecuado (HNSW/IVF); top-k acotado; caché de embeddings; medición p95 (THOR); degradación documentada en CPU; prompts concisos.                       |
| **R-25** | **Migración de mocks rompe la SPA** (Entregable #1).                                            | Medio (R-05)                    | **Feature-flag** `VITE_USE_REAL_API` reversible; migración módulo a módulo; contratos de `types.ts` respetados o adaptadores; suite del front verde en modo mock.     |
| **R-26** | **Secretos en texto plano** (JWT secret, credenciales BD).                                      | Medio (C3)                      | Secretos SOLO en env/secret manager; `.env` fuera del repo; escaneo BLACK WIDOW; `.env.example` sin valores reales.                                                   |
| **R-27** | **Calidad del modelo abierto en es-CO** (borradores/sentimiento pobres).                        | Medio (CE-23/RF-07)             | Qwen2.5-7B (buen español) por defecto; prompts y few-shots afinados; permitir cambiar modelo por env; evaluación cualitativa con seed por tenant.                     |
| **R-28** | **Ingesta/indexado bloqueante** de documentos grandes.                                          | Bajo/Medio (UX ingesta)         | Ingesta **asíncrona** por colas Redis; estados de documento (pendiente/indexado/error); reintentos idempotentes.                                                      |

**Top-3:** R-21 (GPU/VRAM insuficiente → fallback CPU Q4), R-22 (fuga de egress del contenedor IA),
R-23 (RLS mal configurado → fuga cross-tenant).

---

## 7. Criterios de éxito verificables (mapeo con CE-21..CE-29 de XAVIER)

| ID        | Criterio                                                                                                       | Cómo se verifica                                                                                              | Fase   |
| --------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------ |
| **CE-21** | **Cero llamadas salientes de inferencia a terceros** (auditable)                                               | Contenedor IA con egress bloqueado + `check-externos-backend.sh` + prueba de egress vacío + captura de red sin dominios externos. | F0/F4/F7 |
| **CE-22** | **Aislamiento multi-tenant probado**: ningún dato/consulta cruza tenants                                       | **Test automatizado (HAWKEYE) que intenta acceso cross-tenant y FALLA por RLS**; revisión BLACK WIDOW.       | F1/F8  |
| **CE-23** | **RAG end-to-end**: borrador con **≥3 citas trazables** (source+excerpt+score); **p95 latencia** documentado  | Prueba e2e: ingesta de doc → pregunta → borrador citado; latencia RAG **p95 ≤ 6 s** (GPU) / degradación CPU.  | F4/F8  |
| **CE-24** | **WebChat real bidireccional persistido**: mensaje del visitante persiste y aparece en la Bandeja; respuesta llega | Prueba e2e cliente⇄agente por WebSocket con persistencia verificada en BD.                                    | F3/F8  |
| **CE-25** | **Seguridad de datos personales**: secretos fuera del código (C3), borrado lógico (C2), TLS/cifrado en reposo | Escaneo BLACK WIDOW (sin secretos), flags Activo/Inactivo, cifrado en tránsito verificado.                    | F7     |
| **CE-26** | **SPA conectada** a APIs reales sin romper el Entregable #1                                                    | Suite del front verde + recorrido con `VITE_USE_REAL_API=true`; contrato OpenAPI válido.                      | F6     |
| **CE-27** | **Cobertura de tests ≥ 80%** en backend (dominio + RAG + auth/RLS)                                             | Reporte de cobertura (HAWKEYE); unit+integración+e2e.                                                         | F8     |
| **CE-28** | **Despliegue on-prem reproducible**: `docker compose up` levanta el slice sin internet de inferencia           | Arranque limpio en host aislado; health-checks verdes.                                                        | F0/F9  |
| **CE-29** | **Aprobación explícita del Lead** del slice funcional                                                          | Revisión del Lead.                                                                                            | F9     |

---

## 8. Mapa preliminar de SPECs propuestas (SOLO el mapa — NO son las specs)

> Continúa la numeración desde `specs.json` (`next_spec: 11`; Entregable #1 usó SPEC-001..010).
> Se crearán únicamente tras "APROBADO PLAN-002". Cada SPEC llevará criterios verificables (C4).

- **SPEC-011** — Infra base y Docker Compose on-prem: API FastAPI + PostgreSQL/pgvector + Redis + contenedor IA con red interna sin egress + CI backend (F0).
- **SPEC-012** — Modelo de datos multi-tenant: esquema, migraciones versionadas, **RLS por `tenant_id`**, borrado lógico (C2) y pgvector (F1).
- **SPEC-013** — Autenticación y multi-tenant: login/JWT, hashing, inyección de `tenant_id` que fuerza RLS, roles y secretos en env (F2).
- **SPEC-014** — API core REST + contrato OpenAPI: tenants, contactos, conversaciones, mensajes y contacto 360° (F3).
- **SPEC-015** — Canal WebChat propio: widget embebible + **WebSocket bidireccional** + Redis pub/sub + persistencia (F3).
- **SPEC-016** — IA local self-hosted: Ollama/vLLM + modelo abierto + embeddings locales + verificación de **egress bloqueado/auditoría** (F4).
- **SPEC-017** — Pipeline RAG local: ingesta→chunking→pgvector→top-k→borrador con **≥3 citas trazables** (F4).
- **SPEC-018** — Análisis de sentimiento con LLM local del mensaje entrante (F5).
- **SPEC-019** — Borrador RAG **human-in-the-loop**: revisar/editar/aprobar antes de enviar (F5).
- **SPEC-020** — Integración SPA con **feature-flag** `VITE_USE_REAL_API`: reemplazo de mocks respetando contratos, sin romper el Entregable #1 (F6).
- **SPEC-021** — Seguridad y datos personales: TLS, cifrado en reposo, retención/minimización, HABEAS DATA/GDPR-like, secretos (C3) (F7).
- **SPEC-022** — Pruebas + carga (THOR) + observabilidad: unit/integración/e2e, **cross-tenant que falla por RLS**, latencia RAG p95, logs/health/métricas (F8).
- **SPEC-023** — Documentación, runbook operativo y deploy on-prem (F9).

---

## 9. Entregables finales del Entregable #2

- Servicio backend ejecutable con `docker compose up` (API + PostgreSQL/pgvector + Redis + Ollama/vLLM), IA sin egress.
- **OpenAPI** (`/docs`) + colección de ejemplos.
- Migraciones de BD versionadas + seed de datos ficticios por tenant.
- SPA existente conectada a las APIs reales (mocks reemplazados, feature-flag documentado) sin romper el Entregable #1.
- README de operación on-prem (env, modelos locales a descargar, cómo levantar) + runbook.
- **Evidencia auditable** de "cero externos de inferencia" (egress bloqueado + `check-externos-backend.sh` + captura de red) y de **aislamiento multi-tenant** (test cross-tenant que falla por RLS).

## 10. Definition of Done (Entregable #2)

1. CE-21..CE-29 cumplidos y evidenciados.
2. Contenedor de IA con **egress bloqueado y auditable**; `check-externos-backend.sh` en verde; prueba de egress vacío.
3. **RLS activo y probado**: test cross-tenant que **falla** por RLS; sin fugas de datos entre tenants.
4. RAG end-to-end con **≥3 citas trazables** y **p95 de latencia** dentro del objetivo (o degradación CPU documentada).
5. WebChat bidireccional **persistido** (cliente⇄agente) verificado en e2e.
6. Secretos fuera del código (C3); borrado lógico (C2); TLS/cifrado en reposo de datos personales.
7. SPA conectada a APIs reales con feature-flag, **sin romper** el Entregable #1 (suite front verde).
8. Cobertura de tests backend **≥ 80%**; `docker compose up` reproducible sin internet de inferencia.
9. README + runbook + OpenAPI entregados; deploy on-prem con **aprobación del Lead**.
10. **Aprobación explícita del Lead** (CE-29). Ninguna SPEC se cierra sin cumplir los CHECKPOINTS aplicables (C2/C3/C4/C6/C8).

---

## 11. PREGUNTAS ABIERTAS AL LEAD (5) — con supuesto por defecto

Si el Lead no responde, el PLAN procede con el **supuesto por defecto** indicado.

1. **Hardware para el LLM local (⚠️ SUP-24):** ¿hay **GPU on-prem** y con cuánta **VRAM**?
   **Supuesto por defecto:** se asume **GPU ≥16 GB VRAM**; si no hay, **fallback a CPU con modelo
   cuantizado Q4** (Qwen2.5-7B/Llama-3.1-8B Q4), aceptando mayor latencia (documentada). El modelo es
   parametrizable por variable de entorno.

2. **Canal real #1 (⚠️ SUP-22):** ¿**WebChat propio** como primer canal, o WhatsApp Business API desde ya?
   **Supuesto por defecto:** **WebChat propio self-hosted** (WebSocket), sin dependencia de Meta.
   WhatsApp/IG/Messenger quedan para Fase 3 (requieren WABA/BSP y aprobación).

3. **Volumen esperado (dimensionamiento):** ¿cuántos **tenants**, **agentes concurrentes** y **mensajes/día**?
   **Supuesto por defecto:** escala **piloto** (pocos tenants, ~10–50 agentes concurrentes,
   miles de mensajes/día), **un solo host** con Docker Compose y **pgvector**; Qdrant/K8s/HA se
   evalúan cuando el volumen lo justifique (Fase 3+).

4. **Cumplimiento (SUP-26):** ¿basta **HABEAS DATA (Ley 1581 Colombia) + buenas prácticas GDPR-like**?
   **Supuesto por defecto:** **sí**; datos de contacto/comercial (no PHI/HIPAA). Se implementa cifrado,
   secretos en env, borrado lógico y retención configurable. Requisitos extra (derecho al olvido físico,
   ubicación del dato, auditoría formal) entrarían como RNF adicionales si el Lead lo pide.

5. **Modelo abierto e infraestructura:** ¿preferencia/veto de **modelo** (Qwen2.5 vs Llama-3.1 vs Mistral)
   e **infra on-prem** ya definida (SO, orquestador, backups)?
   **Supuesto por defecto:** **Qwen2.5-7B-Instruct** (bueno en español) + embeddings **nomic-embed-text**,
   parametrizables por env; despliegue **on-prem con Docker Compose** en un host Linux; backups del
   volumen de PostgreSQL a cargo de la operación del Lead.

---

> **Siguiente paso:** IRON MAN presenta este PLAN-002 al Lead. El Lead debe responder **"APROBADO PLAN-002"**
> (o "Ajusta PLAN-002: …") antes de que DOCTOR STRANGE genere las SPEC-011..SPEC-023. Cumple CHECKPOINT C8.
