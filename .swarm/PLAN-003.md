# PLAN-003 — Fase 3 "OmniCore AI" (Entregable #3): canal real WhatsApp Business Cloud API (Meta) end-to-end con human-in-the-loop

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Fecha: 2026-09-18 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo` presente) — PROHIBIDO cualquier modelo/servicio EXTERNO de inferencia o de procesamiento de datos personales por un tercero.
> **EXCEPCIÓN ACOTADA (esta fase):** se permite **egress externo real SOLO para el TRANSPORTE** del canal WhatsApp hacia `graph.facebook.com` (Meta). La **IA (LLM/embeddings/RAG/sentimiento) sigue 100% local y SIN egress**. Ver §3.3 y ADR-006.
> Origen: `prompt-lab/PROMPT-OPTIMIZADO-FASE3.md` (🧠 XAVIER) · Estado: **PROPUESTA** (espera "APROBADO PLAN-003")
> Regla de oro: este PLAN **NO genera SPECs**. Las SPECs se crean SOLO tras la aprobación explícita del Lead ("APROBADO PLAN-003").
> Precedentes: Entregable #1 (maqueta SPA) **COMPLETADO**; Entregable #2 (backend + IA local, PLAN-002) **IMPLEMENTADO / EN_VERIFICACION** (SPEC-011..023; ADR-003/004/005).

---

## 1. Objetivo y contexto

### Objetivo

Integrar el canal real **WhatsApp Business Cloud API (Meta)** como **vertical slice end-to-end** del
Entregable #3, **reutilizando el pipeline del Entregable #2** sin reinventarlo: recibir mensajes por
webhook firmado y verificado, enrutarlos al **tenant** correcto bajo **RLS**, persistirlos con el
contrato existente (`conversations` / `messages`), pasarlos por el **pipeline IA 100% local** (sentimiento
SPEC-018 + borrador RAG con ≥3 citas SPEC-017), someterlos a **human-in-the-loop** (SPEC-019) y **enviar**
la respuesta aprobada por el agente a través de la **Graph API** (transporte), gestionando statuses
(sent/delivered/read/failed), la **ventana de servicio de 24 h** y una **plantilla (HSM) mínima** —
**sin ninguna inferencia en terceros**. Meta actúa **solo como transporte del canal**.

### Contexto y relación con el Entregable #2 (qué se reutiliza)

El Entregable #2 dejó operativo (EN_VERIFICACION) un backend FastAPI + PostgreSQL 16/pgvector + Redis +
Ollama (IA local) con piezas **directamente reutilizables**:

- **Dominio agnóstico de canal.** `conversations.canal` es `String(50)` (no enum) → añadir `whatsapp` NO
  requiere rediseñar el dominio, solo un adaptador de transporte + enrutado.
- **`messages`** ya modela `remitente` (contacto/agente/ia), `sentimiento`/`sentimiento_score` (SPEC-018),
  `estado_entrega` (enviado/entregado/leido, SPEC-015) y `SoftDeleteMixin`/`TenantMixin`/`TimestampMixin`.
  El slice #3 **extiende** este modelo con la identidad del mensaje de WhatsApp (`wamid`) y estados de
  transporte, sin romper el contrato existente.
- **Patrón cola Redis + worker** (`rag_ingest_worker`, `sentiment_worker`; `app.core.rag_queue`,
  `app.core.sentiment_queue`): se replica para la **ingesta idempotente de webhooks** y el **envío saliente**.
- **RAG local con ≥3 citas** (SPEC-017), **sentimiento LLM local** (SPEC-018) y **human-in-the-loop atómico**
  (SPEC-019, transición revisar/editar/aprobar sin doble envío): se reutilizan **tal cual**.
- **RLS FORCE por `tenant_id`** (SPEC-012, ADR-004), **auth JWT** (SPEC-013), **borrado lógico** (C2),
  **secretos en env fail-fast** (`${VAR:?}`, C3), **observabilidad** (`/metrics`, structlog, Locust) y
  **CI** (`check-externos-backend.sh`).
- **SPA con feature-flag** `VITE_USE_REAL_API` (SPEC-020): la Bandeja mostrará `whatsapp` junto a WebChat
  con el mismo contrato; flag OFF = maqueta intacta.

**Novedad estructural de esta fase (única y acotada):** aparece **egress externo real** hacia Meta
(`graph.facebook.com`) para el transporte. Esto es una **EXCEPCIÓN documentada a `.no-externo`** que
NO afecta a la IA: el contenedor `ia` (Ollama) mantiene `internal: true` y jamás alcanza internet. Ver §3.

---

## 2. Alcance IN / OUT

### IN — entra en el vertical slice #3

1. **Webhook de recepción WhatsApp (FastAPI):** endpoint HTTPS con (a) verificación del **challenge GET**
   de Meta (`hub.mode`/`hub.verify_token`/`hub.challenge`) y (b) validación de **firma HMAC-SHA256**
   `X-Hub-Signature-256` con `WHATSAPP_APP_SECRET` en cada POST. Sin firma válida → **401**.
2. **ACK rápido + proceso asíncrono:** el webhook responde **200 en p95 ≤ 500 ms** y encola el evento
   (cola Redis persistente) para procesarlo en un **worker**, evitando reintentos de Meta.
3. **Idempotencia por `wamid`:** el id de mensaje de WhatsApp deduplica; un webhook reentregado no crea
   mensaje/borrador/envío duplicados.
4. **Enrutado multi-tenant:** tabla de routing `phone_number_id → tenant_id`; el webhook resuelve el tenant
   del número receptor, **fija el `tenant_id` de sesión (RLS)** y nunca cruza tenants; sin mapeo → descarte
   auditado.
5. **Persistencia (reutiliza SPEC-012/014):** contacto/conversación/mensaje con `canal = "whatsapp"`,
   `wamid`, estado de transporte; borrado lógico (C2).
6. **Pipeline IA local (reutiliza SPEC-017/018):** sentimiento del entrante + borrador RAG con **≥3 citas
   trazables**, **sin inferencia externa**.
7. **Human-in-the-loop (reutiliza SPEC-019):** el agente revisa/edita/aprueba el borrador antes de enviar;
   **nada se envía autónomamente**.
8. **Envío saliente (transporte Graph API):** cliente **httpx** SOLO a `graph.facebook.com` para enviar el
   mensaje aprobado; manejo de la **ventana de 24 h** y **≥1 plantilla (HSM) utilitaria** fuera de ventana.
9. **Statuses:** los callbacks de estado del webhook (`sent`/`delivered`/`read`/`failed`) actualizan
   `estado_entrega` del mensaje.
10. **Allowlist de transporte auditada:** `check-externos-backend.sh` distingue IA (prohibida) de transporte
    (permite `graph.facebook.com` SOLO en el módulo del conector WhatsApp). Ver §3.4.
11. **Secretos (C3):** `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`,
    `WHATSAPP_APP_SECRET` solo en env/secret manager, nunca en repo/logs.
12. **Integración SPA (reutiliza SPEC-020):** la Bandeja muestra `whatsapp` junto a WebChat tras el
    feature-flag, con indicador de ventana 24 h/plantilla; sin romper el Entregable #1.
13. **Observabilidad:** métricas de latencia de webhook y de envío, contadores de entrega/error, logs
    estructurados con `tenant_id`/`wamid`/`trace_id`; evidencia de "cero inferencia externa".

### OUT — NO entra en este slice (Fases 4+)

- **VoiceBot / VoIP:** STT local (Whisper) + TTS local + PBX/SIP + transcripción de audios de WhatsApp → **Entregable #4**.
- **IG DM / Messenger** (misma Graph API, extensión posterior del mismo patrón).
- **ERP real** (sync inventario/pedidos/órdenes).
- **Auto-respuesta autónoma** sin aprobación humana (contradice el human-in-the-loop ya entregado).
- **Campañas / envíos masivos por plantilla**, analítica avanzada, HA/Kubernetes.
- **Multimedia entrante transcrita / multimedia saliente rica:** en el slice solo se **persiste el adjunto**
  (metadato/descarga on-prem opcional); no se transcribe (eso es Entregable #4).

---

## 3. Arquitectura de referencia

### 3.1 Flujo end-to-end

```
recepción:  Meta (graph.facebook.com) --POST firmado HMAC--> [Webhook FastAPI] --ACK 200 ≤500ms-->
            --encola evento--> [Redis cola wa:inbound] --> [wa_inbound_worker]
            --> dedup por wamid --> resuelve phone_number_id→tenant_id (fija RLS)
            --> persiste conversation/message (canal="whatsapp") --> encola sentimiento (SPEC-018)
            --> encola/solicita borrador RAG ≥3 citas (SPEC-017)  [TODO on-prem, sin egress]

human-in-the-loop:  [Bandeja SPA] <-- borrador citado -- agente revisa/edita/APRUEBA (SPEC-019, atómico)

envío:      aprobación --> [wa_send_worker] --httpx allowlist--> graph.facebook.com (transporte)
            <-- statuses (sent/delivered/read/failed) por webhook --> actualiza estado_entrega
```

### 3.2 Componentes y DÓNDE está el límite de egress (diagrama ASCII)

```
                                   HOST ON-PREM (Docker Compose)
  ┌───────────────────────────────────────────────────────────────────────────────────────┐
  │                                                                                          │
  │   red `app` (bridge, CON egress restringido por allowlist a graph.facebook.com)          │
  │   ┌──────────────────────────────────────────────────────────────────────────────┐      │
  │   │  [reverse proxy TLS]──►[api FastAPI]──►[Redis colas+pubsub]──►[PostgreSQL/RLS]  │      │
  │   │        (webhook)          │  ▲                 │                                 │      │
  │   │                           │  │                 ▼                                 │      │
  │   │                           │  │        [wa_inbound_worker]                        │      │
  │   │                           │  └────────[wa_send_worker]───httpx allowlist────────┐ │      │
  │   └───────────────────────────┼───────────────────────────────────────────────────┼─┘      │
  │                               │  ══════════ LÍMITE DE EGRESS ══════════            │        │
  │                               │  Solo `api`/`wa_send_worker` salen, y SOLO a       ▼        │
  │                               │  graph.facebook.com (allowlist auditada, ADR-006)  ►► Meta  │
  │                               │                                                             │
  │   red `ia_internal` (bridge, internal: true — ⛔ SIN egress, NUNCA internet)                 │
  │   ┌───────────────────────────▼──────────────────────────────────────────────────┐        │
  │   │  [ia = Ollama] LLM local (Qwen2.5-7B) + embeddings (nomic-embed)               │        │
  │   │  [rag_worker] [sentiment_worker]  ⛔ jamás alcanzan Meta ni internet            │        │
  │   └──────────────────────────────────────────────────────────────────────────────┘        │
  └───────────────────────────────────────────────────────────────────────────────────────┘
   ⛔ = internal:true, sin ruta a internet   ►► = ÚNICO egress permitido (transporte, no inferencia)
```

**Regla de oro de la topología (invariante de seguridad de esta fase):**

- El **conector/worker que habla con Meta** (`api` webhook + `wa_send_worker`) vive en la red **`app`**
  (que tiene egress) y su salida se **restringe por allowlist a `graph.facebook.com`**.
- El **contenedor `ia` y los workers de IA** (`rag_worker`, `sentiment_worker`) viven **SOLO** en
  `ia_internal` (`internal: true`): **NUNCA** se les añade la red `app` ni ruta a internet. **Prohibido**
  conectar `ia`/workers de IA a `app`, y **prohibido** que el conector WhatsApp corra en `ia_internal`.
- El **límite de egress** es exactamente ese borde: los datos que van a Meta son solo el **texto de la
  respuesta ya aprobada por el agente** (transporte del canal), no una llamada de inferencia.

### 3.3 Aislamiento de la IA (cómo la IA queda garantizada sin egress)

- Se **conserva** ADR-005 sin cambios: `ia_internal internal: true`, firewall host DROP saliente para el
  contenedor de IA, DNS interno/vacío, pesos montados por volumen (sin `pull` en runtime).
- Los **workers de IA** (`rag_worker`, `sentiment_worker`) **hoy están conectados a `app` e `ia_internal`**
  en `docker-compose.yml`. Como ahora `app` gana egress hacia Meta, el PLAN **endurece** esto: los workers
  de IA **no deben** tener egress. Se resolverá en la SPEC de infra (§8, SPEC-024) por una de estas vías,
  a decidir en ADR-006: (a) que los workers de IA hablen con Postgres/Redis por una red intermedia sin
  egress y **queden fuera de `app`**; o (b) mantener el firewall host que ya hace DROP del tráfico saliente
  de IA a rangos públicos, verificado con **prueba de egress vacío** (heredada de ADR-005). La IA **jamás**
  obtiene ruta a `graph.facebook.com`.
- **Evidencia:** captura de red durante un e2e muestra salida pública **solo** desde `api`/`wa_send_worker`
  y **solo** a `graph.facebook.com`; el intento de egress desde `ia`/workers de IA **falla** (timeout/deny).

### 3.4 Auditoría "cero inferencia externa + transporte permitido" (evolución de `check-externos-backend.sh`)

Propuesta concreta para que el script **distinga IA (prohibida) de transporte (permitido y acotado)**:

1. **Se mantiene** la lista `FORBIDDEN_URLS`/`FORBIDDEN_SDKS` de APIs de **inferencia** (OpenAI, Anthropic,
   Google, Cohere, Groq, HuggingFace, etc.): siguen **prohibidas en todo el código**.
2. **Nueva allowlist de transporte** con un único dominio permitido: `graph.facebook.com`, restringido a
   una **ruta de módulo** concreta (p. ej. `app/services/whatsapp/` o `app/integrations/whatsapp/`). El
   script **permite** `graph.facebook.com` **solo** si aparece dentro de ese módulo; si aparece en cualquier
   otro sitio del backend → **FALLA** (transporte fuera del conector = fuga).
3. **Prohíbe** que el módulo del conector WhatsApp importe/llame a Ollama o a servicios de IA (separación de
   responsabilidades: el transporte no infiere) y que módulos de IA importen el cliente httpx de transporte.
4. **Prohíbe** `graph.facebook.com` (y cualquier dominio) en manifiestos de la red/servicio `ia_internal`
   y en la config de `ia`/`rag_worker`/`sentiment_worker`.
5. Mantiene la verificación de `ia_internal: internal: true` y de `OLLAMA_BASE_URL` a host interno.

> El diseño exacto del matcher (allowlist por ruta) se especifica en SPEC-024/030 y se ancla en ADR-006.

### 3.5 Exposición HTTPS entrante

- Meta requiere un endpoint HTTPS público para el webhook. Se expone **solo** el path del webhook a través
  del **reverse proxy TLS** (Caddy/Nginx/Traefik), nunca la IA ni la BD. Certificado y `verify_token`
  gestionados como config/secreto (C3). El resto del backend permanece detrás del proxy.

---

## 4. Fases y entregables

| Fase   | Nombre                                       | Entregables clave                                                                                                                                                            |
| ------ | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **F0** | Infra egress acotado + auditoría + ADRs      | `docker-compose` con `wa_send_worker` en `app` y aislamiento reforzado de IA; allowlist `graph.facebook.com` en `check-externos-backend.sh`; `.env.example` con las 4 vars WhatsApp (placeholders); ADR-006/007; reverse proxy TLS del webhook. |
| **F1** | Datos: routing tenant + campos WhatsApp      | Migración Alembic versionada: tabla `whatsapp_accounts (phone_number_id, tenant_id, ...)` con RLS y `wamid`/estado de transporte en `messages`; borrado lógico (C2); seed de routing ficticio.                                             |
| **F2** | Webhook: challenge GET + firma HMAC + ACK    | Endpoint FastAPI: verificación `hub.challenge`, validación HMAC-SHA256 `X-Hub-Signature-256`, ACK 200 ≤500 ms p95, encolado del evento; rechazo 401 sin firma válida.                                                                        |
| **F3** | Ingesta idempotente + enrutado tenant        | `wa_inbound_worker`: dedup por `wamid`, resolución `phone_number_id→tenant_id`, fijado RLS, persistencia `canal="whatsapp"`, disparo de sentimiento (SPEC-018) y borrador RAG (SPEC-017); descarte auditado sin mapeo.                       |
| **F4** | Envío saliente (transporte Graph API)        | `wa_send_worker` + cliente httpx allowlist a `graph.facebook.com`; envío del mensaje aprobado (SPEC-019); ventana 24 h + ≥1 plantilla HSM; rate-limit hacia Meta; manejo de errores/reintentos.                                              |
| **F5** | Statuses + ciclo de entrega                  | Procesamiento de callbacks `sent/delivered/read/failed` → actualización de `estado_entrega`; conciliación con el mensaje enviado.                                                                                                            |
| **F6** | Integración SPA (feature-flag)               | Bandeja muestra canal `whatsapp` junto a WebChat; indicador de ventana 24 h/plantilla; contratos `types.ts` respetados; sin romper el Entregable #1 (flag OFF intacto).                                                                       |
| **F7** | Seguridad + política de egress               | Firma HMAC obligatoria, tokens en env (C3, nunca en logs), TLS, aislamiento cross-tenant, **evidencia** de "cero inferencia externa" y de que el ÚNICO egress es transporte a `graph.facebook.com`; barrido BLACK WIDOW.                     |
| **F8** | Pruebas + carga (THOR) + observabilidad      | Simulador de webhook firmado (válido/ inválido/ duplicado); tests cross-tenant (fallan por RLS/enrutado); e2e cliente⇄agente por WhatsApp/simulador; latencia webhook p95 ≤500 ms (THOR); métricas de entrega/error.                       |
| **F9** | Docs + runbook + deploy                      | Runbook del canal (alta WABA, verificación de webhook, plantillas, rotación de token) con placeholders sin secretos; OpenAPI del webhook; colección de ejemplos; deploy on-prem (QUICKSILVER, con aprobación del Lead).                     |

---

## 5. Dependencias entre fases y ruta crítica

- **F0** habilita todo (egress acotado + auditoría + ADRs). Ninguna fase de canal arranca sin F0.
- **F1** depende de F0 y es prerequisito duro de F2–F5 (sin routing tenant ni `wamid` no hay ingesta ni idempotencia).
- **F2** depende de F1 (necesita fijar tenant y persistir `wamid`); es la puerta de recepción.
- **F3** depende de F2 (evento encolado) y reutiliza SPEC-017/018; habilita el borrador para el human-in-the-loop.
- **F4** depende de F3 (mensaje persistido) y de SPEC-019 (aprobación); es la puerta de envío. Puede avanzar
  en **paralelo** a F5 una vez definido el contrato de statuses.
- **F5** depende de F4 (mensaje enviado con `wamid` de Meta) para conciliar statuses.
- **F6** depende de F3 y F4 (necesita conversaciones WhatsApp reales y estados) y reutiliza SPEC-020.
- **F7** transversal: se diseña desde F0/F2 (firma, egress, secretos) y se **cierra** auditando el conjunto.
- **F8** depende de que F2–F6 estén completas (prueba el slice completo, incluida carga THOR del webhook).
- **F9** cierra: runbook/docs/deploy tras F7/F8.

**Ruta crítica:** `F0 → F1 → F2 → F3 → {F4 ‖ F5} → F6 → F7/F8 → F9`
(F4/F5 parcialmente en paralelo; F7 transversal y consolidada al final).

---

## 6. Riesgos y mitigaciones

| #        | Riesgo                                                                                                   | Impacto                          | Mitigación                                                                                                                                                                       |
| -------- | ------------------------------------------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **R-31** | **Fuga de egress hacia la IA** (que el egress a Meta abra ruta del contenedor de IA a internet → rompe SENSIBLE). | **Crítico** (rompe política)     | **Invariante de topología** (§3.2): IA solo en `ia_internal internal:true`; el egress lo tiene SOLO `api`/`wa_send_worker` en `app`, y SOLO a `graph.facebook.com`. Firewall host DROP para IA (ADR-005). `check-externos-backend.sh` con allowlist por ruta (§3.4). Prueba de egress vacío desde IA + captura de red. ADR-006. |
| **R-32** | **Firma HMAC mal validada** (aceptar tráfico no firmado o falsear origen).                                | Alto (seguridad canal)           | HMAC-SHA256 `X-Hub-Signature-256` con `WHATSAPP_APP_SECRET` sobre el **raw body**; comparación en tiempo constante; sin firma válida → **401**; test con firma válida/ inválida/ ausente (BLACK WIDOW/HAWKEYE). |
| **R-33** | **Idempotencia insuficiente** (Meta reintrega → mensajes/borradores/envíos duplicados).                  | Alto (datos/UX)                  | Dedup por **`wamid`** con restricción única a nivel BD + guarda en el worker; procesamiento idempotente; test de webhook duplicado que **no** crea doble mensaje. ADR-007.        |
| **R-34** | **Fuga cross-tenant** (mensaje enrutado al tenant equivocado).                                            | Alto (privacidad, HABEAS DATA)   | Tabla `phone_number_id→tenant_id` + fijado RLS FORCE (ADR-004); sin mapeo → descarte auditado; **test cross-tenant que FALLA por RLS/enrutado** (HAWKEYE). ADR-007.               |
| **R-35** | **Rate limits / errores de Meta** en el envío (429/errores transitorios).                                 | Medio (entrega)                  | Rate-limit propio hacia Meta; reintentos con backoff idempotentes; cola de envío; estados `failed` reflejados; alertas en métricas.                                              |
| **R-36** | **Ventana de 24 h** vencida → mensaje libre rechazado por Meta.                                           | Medio (negocio)                  | Detección de ventana; fuera de ventana exigir/usar **plantilla HSM** aprobada (≥1 utilitaria); indicador en la SPA; documentado en runbook.                                     |
| **R-37** | **Tokens de WhatsApp expuestos** (en repo/logs/docs).                                                     | Alto (C3)                        | Secretos SOLO en env/secret manager con fail-fast `${VAR:?}`; jamás en logs (redacción); `.env.example` con placeholders; barrido BLACK WIDOW; runbook con placeholders.         |
| **R-38** | **Latencia del webhook > 500 ms** → Meta reintenta y amplifica carga.                                     | Medio (RNF-02)                   | ACK 200 inmediato + proceso 100% asíncrono por cola Redis; nada de IA/SQL pesado en el request del webhook; medición p95 bajo carga (THOR).                                     |
| **R-39** | **Regresión en Entregables #1/#2** al añadir el canal.                                                    | Medio (R-07)                     | Feature-flag reversible; dominio agnóstico de canal (`conversations.canal` string); suites #1/#2 verdes; migraciones aditivas no destructivas.                                  |

**Top-3:** **R-31 (fuga de egress hacia la IA — EXCEPCIÓN de egress y su mitigación)**, R-32 (firma HMAC),
R-34 (fuga cross-tenant). R-33 (idempotencia por `wamid`) inmediatamente detrás.

---

## 7. Criterios de éxito verificables (mapeo con CE-31..CE-35 de XAVIER)

| ID        | Criterio                                                                                                                            | Cómo se verifica                                                                                                                              | Fase     |
| --------- | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| **CE-31** | **Recepción firmada e idempotente:** webhook con firma HMAC válida se procesa una sola vez; firma inválida → 401; duplicado por `wamid` no crea mensaje doble. | Test e2e con simulador de webhook firmado (válido/ inválido/ duplicado); revisión BLACK WIDOW.                                               | F2/F3/F8 |
| **CE-32** | **Enrutado multi-tenant sin fugas:** el entrante se asigna al tenant del `phone_number_id`; ningún dato cruza tenants.             | Test cross-tenant (HAWKEYE) que **falla por RLS/enrutado**; mensaje sin mapeo descartado y auditado.                                          | F1/F3/F8 |
| **CE-33** | **Pipeline IA local sobre WhatsApp:** el mensaje recibe sentimiento y borrador RAG con **≥3 citas trazables**, **sin inferencia externa**. | e2e; `check-externos-backend.sh` verde; captura de red: salida pública SOLO a `graph.facebook.com` (transporte), nunca a APIs de inferencia. | F3/F7    |
| **CE-34** | **Ciclo human-in-the-loop end-to-end:** el agente aprueba/edita y el mensaje se **envía** por Graph API con statuses actualizados; **nada autónomo**. | e2e cliente⇄agente por WhatsApp/simulador; statuses entregado/leído reflejados en BD.                                                        | F4/F5/F8 |
| **CE-35** | **Latencia y seguridad de webhook:** ACK 200 **p95 ≤ 500 ms**; tokens ausentes del repo/logs; TLS activo.                         | Medición THOR bajo carga; escaneo BLACK WIDOW (secretos), inspección de logs; borrador RAG mantiene p95 ≤ 6 s (GPU).                          | F7/F8    |

> Transversales heredados del Entregable #2: **no romper** SPA/backend (suites verdes), cobertura backend
> **≥ 80%**, `docker compose up` reproducible, y **aprobación explícita del Lead** del slice.

---

## 8. Mapa preliminar de SPECs propuestas (SOLO el mapa — NO son las specs)

> Continúa la numeración desde `specs.json` (`next_spec: 24`). Se crearán únicamente tras "APROBADO PLAN-003".
> Cada SPEC llevará criterios verificables (C4).

- **SPEC-024** — Infra de egress acotado + auditoría de transporte: `wa_send_worker` en red `app`, aislamiento reforzado de IA, allowlist `graph.facebook.com` por ruta en `check-externos-backend.sh`, `.env.example` con vars WhatsApp (F0).
- **SPEC-025** — Datos del canal WhatsApp: tabla de routing `whatsapp_accounts (phone_number_id, tenant_id)` con RLS + campos `wamid`/estado de transporte en `messages`, migración Alembic y borrado lógico (F1).
- **SPEC-026** — Webhook de recepción: challenge GET + validación de firma HMAC-SHA256 + ACK 200 ≤500 ms + encolado asíncrono (F2).
- **SPEC-027** — Ingesta idempotente + enrutado multi-tenant: `wa_inbound_worker`, dedup por `wamid`, resolución `phone_number_id→tenant_id`, fijado RLS y persistencia `canal="whatsapp"` (F3).
- **SPEC-028** — Disparo del pipeline IA local sobre WhatsApp: reutiliza sentimiento (SPEC-018) y borrador RAG con ≥3 citas (SPEC-017) para el entrante, sin inferencia externa (F3).
- **SPEC-029** — Envío saliente por Graph API (transporte): cliente httpx allowlist a `graph.facebook.com`, ventana 24 h + ≥1 plantilla HSM, rate-limit y reintentos (F4).
- **SPEC-030** — Statuses de entrega: procesamiento de callbacks `sent/delivered/read/failed` → actualización de `estado_entrega` y conciliación (F5).
- **SPEC-031** — Integración SPA del canal WhatsApp (feature-flag): Bandeja con `whatsapp`, indicador de ventana 24 h/plantilla, contratos respetados sin romper el Entregable #1 (F6).
- **SPEC-032** — Seguridad del canal + política de egress: firma HMAC obligatoria, tokens en env (C3), TLS, aislamiento cross-tenant, evidencia "cero inferencia externa" y egress solo-transporte (F7).
- **SPEC-033** — Pruebas + carga (THOR) + observabilidad del canal: simulador de webhook firmado, cross-tenant, e2e human-in-the-loop, latencia webhook p95, métricas de entrega/error (F8).
- **SPEC-034** — Documentación, runbook del canal WhatsApp y deploy on-prem: alta WABA, verificación de webhook, plantillas, rotación de token (placeholders, sin secretos) (F9).

---

## 9. Entregables finales del Entregable #3

- Conector WhatsApp (webhook + envío) integrado al backend existente, ejecutable con `docker compose up`.
- Migración de BD versionada para el routing `phone_number_id → tenant_id` y campos WhatsApp (`wamid`, estado transporte).
- OpenAPI actualizado con el/los endpoint(s) del webhook + colección de ejemplos con **simulador de webhook firmado**.
- SPA mostrando el canal WhatsApp en la Bandeja tras feature-flag, sin romper el Entregable #1.
- `check-externos-backend.sh` evolucionado (allowlist de transporte por ruta) en verde en CI.
- Runbook de operación del canal (alta WABA, verificación de webhook, plantillas, rotación de token) con placeholders, sin secretos.
- **Evidencia auditable:** firma HMAC verificada, "cero inferencia externa", egress público SOLO a `graph.facebook.com`, aislamiento cross-tenant, latencia de webhook p95.
- ADR-006 (excepción `.no-externo` para transporte) y ADR-007 (idempotencia por `wamid` + enrutado tenant) aceptados.

## 10. Definition of Done (Entregable #3)

1. CE-31..CE-35 cumplidos y evidenciados.
2. Webhook con **firma HMAC obligatoria** (401 sin firma válida) y **ACK 200 p95 ≤ 500 ms** (THOR).
3. **Idempotencia por `wamid`** probada (webhook duplicado no crea doble mensaje/borrador/envío).
4. **Enrutado multi-tenant** probado: test cross-tenant que **falla** por RLS/enrutado; sin mapeo → descarte auditado.
5. Pipeline IA **100% local** sobre WhatsApp (sentimiento + borrador RAG ≥3 citas); `check-externos-backend.sh` verde con allowlist de transporte por ruta.
6. **Egress público únicamente** desde `api`/`wa_send_worker` y **solo** a `graph.facebook.com`; IA sin ruta a internet (prueba de egress vacío + captura de red).
7. **Human-in-the-loop** intacto: nada se envía autónomamente; el agente aprueba antes del envío.
8. Statuses `sent/delivered/read/failed` reflejados en `estado_entrega`.
9. Secretos WhatsApp fuera del código/logs (C3); TLS activo; borrado lógico (C2).
10. SPA con canal WhatsApp tras feature-flag **sin romper** el Entregable #1; cobertura backend **≥ 80%**; `docker compose up` reproducible.
11. Runbook + OpenAPI entregados; ADR-006/007 aceptados; deploy on-prem con **aprobación del Lead** (cambio sensible → notificación Telegram, C6).
12. **Aprobación explícita del Lead**. Ninguna SPEC se cierra sin cumplir los CHECKPOINTS aplicables (C2/C3/C4/C6/C8).

---

## 11. ADRs recomendados (a abrir desde ADR-006)

- **ADR-006 — Excepción acotada a `.no-externo` para el TRANSPORTE del canal WhatsApp/Meta.** Decide que el
  egress a `graph.facebook.com` es transporte (no inferencia), permitido SOLO en el módulo del conector,
  con allowlist por ruta en `check-externos-backend.sh`, mientras la IA permanece en `ia_internal internal:true`
  sin egress (invariante de topología §3.2). Alternativas: BSP intermediario (descartado: ve el contenido);
  prohibir todo egress (descartado: imposibilita el canal real). Reafirma ADR-005 para la IA.
- **ADR-007 — Idempotencia por `wamid` + enrutado `phone_number_id → tenant_id`.** Decide la clave de
  deduplicación (`wamid`, unicidad en BD) y el mecanismo de resolución de tenant y fijado RLS para el webhook,
  con descarte auditado sin mapeo. Alternativas: dedup por hash de payload (descartada: frágil); tenant por
  cabecera (descartada: no fiable/spoofable).

> (Opcional, evaluar en implementación) **ADR-008 — Estrategia de ventana de 24 h y plantillas HSM** si el
> manejo de plantillas resulta lo bastante complejo como para requerir una decisión formal separada.

---

## 12. PREGUNTAS ABIERTAS AL LEAD (5) — con supuesto por defecto

Si el Lead no responde, el PLAN-003 procede con el **supuesto por defecto** indicado (heredadas de XAVIER §8).

1. **Slice del Entregable #3 (⚠️ SUP-31):** ¿confirmas **WhatsApp Business API** como el slice (on-brand,
   alto valor, máxima reutilización), o prefieres **VoiceBot local (a)** desde ya?
   **Supuesto por defecto:** **WhatsApp Business API**; VoiceBot queda como Entregable #4.

2. **Proveedor y credenciales (⚠️ SUP-32/SUP-33):** ¿usamos **WhatsApp Cloud API oficial de Meta** (sin BSP)
   y **hay WABA + número + tokens** disponibles? ¿Quién los provee?
   **Supuesto por defecto:** **Cloud API oficial de Meta**; si aún no hay credenciales, se entrega el conector
   completo + **simulador de webhook firmado** verificable en local, listo para conectar el token real.

3. **Ventana de 24 h y plantillas (SUP-35):** ¿el negocio necesita **iniciar** conversaciones fuera de la
   ventana de 24 h (plantillas/HSM), o basta **responder dentro de ventana**?
   **Supuesto por defecto:** foco en **respuesta dentro de ventana** + **1 plantilla utilitaria** mínima;
   campañas/envíos masivos quedan fuera del slice.

4. **Human-in-the-loop vs autonomía (SUP-34):** ¿mantenemos **aprobación humana obligatoria** antes de enviar
   por WhatsApp, o explorar auto-respuesta con guardarraíles?
   **Supuesto por defecto:** **human-in-the-loop obligatorio**; auto-respuesta (e) se difiere hasta tener
   métricas de calidad del borrador y guardarraíles.

5. **Hardware / volumen / cumplimiento (SUP-3A):** ¿sigue vigente **GPU ≥16 GB** (o fallback CPU Q4), escala
   **piloto** y cumplimiento **HABEAS DATA + GDPR-like** (no PHI)?
   **Supuesto por defecto:** **sí** a los tres; el envío/recepción WhatsApp no cambia el dimensionamiento de
   IA del Entregable #2; se mantiene un solo host Docker Compose para el piloto.

---

> **Siguiente paso:** IRON MAN presenta este PLAN-003 al Lead. El Lead debe responder **"APROBADO PLAN-003"**
> (o "Ajusta PLAN-003: …") antes de que DOCTOR STRANGE genere las SPEC-024..SPEC-034 y los ADR-006/007.
> Cumple CHECKPOINT C8 (prompt registrado en `prompt-lab/PROMPT-OPTIMIZADO-FASE3.md`).
