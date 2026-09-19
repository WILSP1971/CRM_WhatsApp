# PROMPT OPTIMIZADO — FASE 3 (Entregable #3) · "OmniCore AI"

> Autor: 🧠 XAVIER (Professor X) — Estratega de Prompts (Nivel 1)
> Fecha: 2026-09-18 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo` presente) — PROHIBIDO cualquier modelo/servicio EXTERNO de inferencia o de procesamiento de datos personales.
> IA (LLM, embeddings y ahora STT/TTS si aplica) **100% on-prem**. Canales externos (WhatsApp Business API, IG/Messenger, PBX/SIP) permitidos SOLO como **transporte**; datos e inferencia se quedan on-prem.
> Estado: **LISTO PARA DOCTOR STRANGE (PLAN-003)** · Cumple CHECKPOINT C8 (prompt registrado en `prompt-lab/`).
> Precedentes: Entregable #1 (maqueta SPA) COMPLETO · Entregable #2 (backend + IA local, PLAN-002) **IMPLEMENTADO / EN_VERIFICACION** (SPEC-011..023; ADR-003/004/005).

---

## 0. Prompt inicial del Lead (transcripción íntegra — NO perder)

> "continua fase 3"

Interpretación: iniciar el **Entregable #3** de "OmniCore AI" continuando lo diferido de PLAN-002
(sección OUT), sobre el backend + IA local ya construidos en el Entregable #2. El objetivo en bruto
NO especifica cuál de los candidatos diferidos abordar, por lo que XAVIER recomienda alcance abajo.

---

## 1. Diagnóstico: qué está construido y qué se puede reutilizar

El Entregable #2 dejó operativo (EN_VERIFICACION) un backend FastAPI + PostgreSQL16/pgvector + Redis +
Ollama (IA local), con piezas **directamente reutilizables** para la Fase 3:

- **Modelo de conversaciones/mensajes agnóstico de canal.** `conversations.canal` es un `String(50)`
  con default `"webchat"` (no un enum cerrado) → **añadir un canal nuevo (`whatsapp`) NO requiere
  rediseñar el dominio**, solo un adaptador de transporte + enrutado.
- **Pipeline RAG local end-to-end** con ≥3 citas trazables (cola Redis + `rag_ingest_worker`).
- **Sentimiento con LLM local** (`sentiment_worker`) sobre el mensaje entrante.
- **Human-in-the-loop** (`rag_draft`, transición atómica revisar/editar/aprobar).
- **Multi-tenant con RLS FORCE**, auth JWT, borrado lógico, secretos en env, egress IA bloqueado
  (`ia_internal internal:true`), observabilidad (`/metrics`, Locust), CI.
- **SPA con feature-flag** `VITE_USE_REAL_API` (flag OFF = maqueta intacta) y **módulo VoiceBot ya
  maquetado** (SPEC-006: webphone, onda, transcripción incremental, chip de intención, historial —
  todo mock, sin audio real).

**Conclusión:** el camino de mínimo riesgo / máximo valor es el que **reaprovecha** conversaciones +
RAG + sentimiento + human-in-the-loop y solo añade **un adaptador de canal de transporte**.

---

## 2. Comparación de los candidatos diferidos (a)-(e)

| Opción | Descripción | Valor de negocio | Riesgo | Encaje con lo construido | Dependencia externa dura |
| ------ | ----------- | ---------------- | ------ | ------------------------ | ------------------------ |
| **(b) WhatsApp Business API** | Canal real WhatsApp Cloud API (webhook entrante + envío) | **MUY ALTO** — el repo se llama `CRM_WhatsApp`; WhatsApp es el canal #1 de negocio en LATAM/es-CO | **MEDIO** — solo transporte; el contenido/IA quedan on-prem | **MÁXIMO** — reutiliza conversaciones/RAG/sentimiento/human-in-the-loop; solo adaptador de canal + webhook + envío | WABA/número + token (Cloud API o BSP). Meta solo transporta, NO infiere |
| **(a) VoiceBot local (STT+TTS+VoIP)** | Whisper self-hosted + TTS local + intención sobre PBX/SIP | ALTO — diferenciador; hay maqueta VoiceBot | **ALTO** — STT casi en vivo + TTS + telefonía real (PBX/SIP, RTP, barge-in) es un subsistema nuevo completo; latencia dura; exige GPU | MEDIO — reutiliza intención/sentimiento pero añade toda la capa de audio/telefonía | PBX/SIP o troncal SIP + hardware GPU para Whisper |
| **(c) IG DM / Messenger** | Más canales omnicanal | MEDIO — incremental sobre (b), mismo Graph API | BAJO-MEDIO — patrón idéntico a (b) | ALTO — mismo adaptador que WhatsApp | Cuentas Meta / Graph API |
| **(d) ERP real** | Sync bidireccional órdenes/inventario | MEDIO-ALTO (según cliente) | **ALTO** — integración a sistema externo heterogéneo, transaccional, sin API definida | BAJO — no reutiliza RAG/canales; es otro eje | ERP concreto + credenciales + esquema |
| **(e) Auto-respuesta autónoma** | IA responde sin humano (con guardarraíles) | ALTO pero **arriesgado** | **MUY ALTO** — quita el human-in-the-loop; riesgo reputacional/legal (HABEAS DATA) | Reutiliza RAG pero **elimina** el control humano ya construido | Ninguna, pero requiere guardarraíles maduros |

---

## 3. Recomendación de XAVIER — slice del Entregable #3

**SLICE RECOMENDADO: (b) Canal real WhatsApp Business API (Cloud API) end-to-end, como
vertical slice de UN solo canal, manteniendo human-in-the-loop.**

**Por qué (b) y no los otros:**

1. **On-brand y valor de negocio máximo.** El repositorio se llama `CRM_WhatsApp`; entregar WhatsApp
   real es el "para qué" del producto y el canal dominante en es-CO. Máximo valor demostrable.
2. **Mínimo riesgo por máxima reutilización.** El dominio ya es agnóstico de canal (`conversations.canal`
   string). WhatsApp entra como **adaptador de transporte** que alimenta el MISMO pipeline ya probado
   (persistencia → sentimiento → RAG con citas → borrador human-in-the-loop → envío). No se reinventa nada.
3. **Respeta `.no-externo` sin fricción.** Meta actúa **solo como transporte** del mensaje (igual que
   una operadora telefónica); LLM, embeddings, RAG y sentimiento siguen 100% on-prem. Es una integración
   de canal INEVITABLE explícitamente permitida por la política, no inferencia externa.
4. **(a) VoiceBot se descarta como primer slice por riesgo/latencia.** STT casi en vivo + TTS + PBX/SIP
   + barge-in es un subsistema nuevo completo con requisitos de latencia duros y dependencia fuerte de
   GPU; alto riesgo para un primer slice. Queda como **Entregable #4** (la maqueta VoiceBot ya lo prepara).
5. **(c) queda como extensión trivial de (b)** (Fase posterior, mismo patrón Graph API).
   **(d) ERP** es otro eje sin reutilización (Fase separada, depende de un ERP concreto).
   **(e) Auto-respuesta** es de alto riesgo y **contradice** el human-in-the-loop ya entregado; se
   difiere hasta tener métricas de calidad del borrador y guardarraíles maduros.

> **Regla del slice:** UN canal (WhatsApp), end-to-end, con human-in-the-loop intacto. NO se hace
> auto-respuesta autónoma, NI voz, NI ERP, NI IG/Messenger en este entregable.

---

## 4. Ambigüedades detectadas y supuestos resueltos (marcados)

Los ⚠️ son **críticos**: si el Lead no los confirma, deben resolverse ANTES del PLAN-003.

| #   | Ambigüedad | Supuesto adoptado (SUP-3x) | Criticidad |
| --- | ---------- | -------------------------- | ---------- |
| C1  | ¿Qué es "fase 3"? ¿todo lo diferido? | **SUP-31 ⚠️** El Entregable #3 es **UN vertical slice: canal WhatsApp Business API** end-to-end, reutilizando el pipeline del Entregable #2. VoiceBot(a), IG/Messenger(c), ERP(d) y auto-respuesta(e) → Fases 4+. | Crítica |
| C2  | ¿WhatsApp Cloud API (Meta directo) o BSP (Twilio/360dialog)? | **SUP-32 ⚠️** **WhatsApp Cloud API oficial de Meta** (webhook + Graph API de envío), sin BSP intermediario, para no añadir un tercero que "vea" el contenido. Si el Lead ya tiene BSP, se adapta el conector. | Crítica |
| C3  | ¿Hay WABA/número/token disponible? | **SUP-33 ⚠️** Se asume **WABA + número de prueba (o productivo) disponibles** y que el Lead provee `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN` y `WHATSAPP_APP_SECRET` como **secretos en env/secret manager** (nunca en repo). Sin ellos se entrega un **stub/simulador de webhook** verificable en local. | Crítica |
| C4  | ¿Se mantiene human-in-the-loop en WhatsApp? | **SUP-34** Sí. La IA genera **borrador con citas** y el agente aprueba/edita antes de enviar. Sin auto-respuesta autónoma en este slice. | Alta |
| C5  | ¿Ingreso de mensajes fuera de la ventana de 24 h? | **SUP-35** Dentro de la **ventana de servicio de 24 h** se responde con texto libre; fuera de ella se requieren **plantillas (templates) HSM aprobadas por Meta**. El slice soporta recepción siempre y **respuesta libre en ventana**; el envío por plantilla se incluye como capacidad mínima (1 plantilla utilitaria). | Alta |
| C6  | ¿Multimedia (imágenes/audio/docs de WhatsApp)? | **SUP-36** El slice #1 cubre **texto**; la descarga de media entrante se persiste como adjunto on-prem pero **NO se transcribe** (el audio de WhatsApp → STT es parte del Entregable #4 VoiceBot). Media saliente: opcional, fuera del núcleo. | Media |
| C7  | ¿La firma del webhook y la verificación son obligatorias? | **SUP-37** Sí, **duras**: verificación `hub.challenge` en el GET y validación de firma **HMAC-SHA256 `X-Hub-Signature-256`** con `WHATSAPP_APP_SECRET` en cada POST. Peticiones sin firma válida se rechazan (401). | Alta |
| C8  | ¿Cómo aparece en la SPA? | **SUP-38** La Bandeja omnicanal muestra las conversaciones de WhatsApp junto a WebChat (mismo contrato `conversations`, `channel: "whatsapp"`), tras el feature-flag `VITE_USE_REAL_API`. Sin romper el Entregable #1. | Media |
| C9  | ¿Multi-tenant: qué número mapea a qué tenant? | **SUP-39** Cada **`phone_number_id` de WhatsApp se mapea a un `tenant_id`** (tabla de enrutado). El webhook resuelve el tenant por el número receptor y aplica RLS. Sin mapeo → mensaje descartado y auditado. | Alta |
| C10 | ¿Volumen esperado? | **SUP-3A** Escala **piloto**: pocos tenants, decenas de agentes concurrentes, miles de mensajes/día, un host Docker Compose. HA/K8s se evalúa por volumen (Fase posterior). | Baja |

---

## 5. PROMPT PROFESIONAL (marco C.R.A.F.T.)

### 5.1 Objetivo (Acción — verbo único y medible)

**Integrar** el canal real **WhatsApp Business API (Cloud API de Meta)** como **vertical slice
end-to-end** del Entregable #3 de "OmniCore AI": recibir mensajes por webhook (firmados y verificados),
enrutarlos al tenant correcto bajo RLS, persistirlos, pasarlos por el pipeline **IA 100% local ya
existente** (sentimiento + RAG con ≥3 citas + **borrador human-in-the-loop**), y **enviar** la respuesta
aprobada por el agente a través de la Graph API — **sin ninguna inferencia en terceros**; Meta actúa
**solo como transporte**.

### 5.2 Rol (quién lo resuelve — flujo del enjambre)

- **DOCTOR STRANGE** → PLAN-003 y SPECs derivadas.
- **CAPTAIN AMERICA** → implementación (coordina backend + integración SPA).
- **BLACK PANTHER** → backend: conector WhatsApp (webhook + envío), enrutado tenant, colas, reutilización del pipeline RAG/sentimiento.
- **DAREDEVIL** → frontend: Bandeja mostrando canal `whatsapp`, indicadores de ventana 24 h/plantilla.
- **BLACK WIDOW** → seguridad: firma HMAC del webhook, tokens en secret manager, aislamiento cross-tenant, cero inferencia externa, HABEAS DATA.
- **HAWKEYE** → pruebas (unit/integración/e2e, simulador de webhook, cross-tenant). **THOR** → latencia de webhook/envío bajo carga. **WOLVERINE** → calidad.
- **QUICKSILVER** → despliegue on-prem + exposición HTTPS del webhook (con aprobación del Lead).

### 5.3 Contexto

- Producto: CRM omnicanal multi-tenant. Entregable #1 (SPA) COMPLETO; Entregable #2 (backend + IA local)
  IMPLEMENTADO/EN_VERIFICACION (FastAPI + PostgreSQL16/pgvector + Redis + Ollama; RLS FORCE; JWT; WebChat
  WebSocket; RAG local ≥3 citas; sentimiento LLM local; human-in-the-loop; feature-flag SPA).
- **Piezas reutilizables (NO reinventar):** modelo `conversations.canal` (string, ya soporta multi-canal),
  `messages` con estados de entrega, `rag_ingest_worker`/`rag_queue`, `sentiment_worker`/`sentiment_queue`,
  `rag_draft` (human-in-the-loop atómico), RLS, auth, observabilidad `/metrics`, contratos `src/lib/types.ts`.
- **Clasificación SENSIBLE** (`.no-externo`): PROHIBIDO OpenAI/Anthropic/Google/cualquier API de inferencia
  externa. Verificable con `scripts/puede-modelo-externo.sh` y `check-externos-backend.sh`.
- **Integración externa permitida SOLO como transporte:** WhatsApp Cloud API (recepción/envío del canal).
  Nunca se envía contenido a un servicio de inferencia de terceros.

### 5.4 Alcance del Entregable #3

**IN (vertical slice WhatsApp end-to-end):**

1. **Webhook de recepción WhatsApp:** endpoint público HTTPS con verificación `GET hub.challenge` y
   validación de **firma HMAC-SHA256 `X-Hub-Signature-256`** (`WHATSAPP_APP_SECRET`) en cada POST.
2. **Enrutado multi-tenant:** resolución `phone_number_id → tenant_id`; aplicación de RLS; mensajes sin
   mapeo se descartan y auditan.
3. **Persistencia:** conversación/contacto/mensaje con `channel = "whatsapp"`, estados de entrega
   (enviado/entregado/leído vía statuses del webhook), borrado lógico (C2), respetando el contrato existente.
4. **Pipeline IA local (reutilizado):** sentimiento del mensaje entrante + borrador RAG con **≥3 citas
   trazables** del tenant. **Sin inferencia externa.**
5. **Human-in-the-loop:** el agente revisa/edita/aprueba el borrador en la Bandeja antes de enviar.
6. **Envío saliente:** cliente de la **Graph API** para enviar el mensaje aprobado; manejo de la
   **ventana de servicio de 24 h** y **envío por plantilla (HSM)** mínimo (≥1 plantilla utilitaria)
   fuera de ventana.
7. **Deduplicación e idempotencia:** por `wamid`/message id (Meta reintenta webhooks); ACK 200 rápido +
   procesamiento asíncrono por cola Redis.
8. **Integración SPA:** la Bandeja muestra conversaciones WhatsApp junto a WebChat (feature-flag),
   con indicador de estado de ventana 24 h/plantilla. Sin romper el Entregable #1.
9. **Secretos:** tokens de WhatsApp en env/secret manager (C3), nunca en repo ni en logs.
10. **Observabilidad:** métricas de latencia de webhook y de envío, contadores de entrega/error, logs
    estructurados con `tenant_id`/`wamid`/`trace_id`; evidencia de "cero inferencia externa".

**OUT (Fases 4+ — fuera de este entregable):**

- **VoiceBot / VoIP:** STT local (Whisper self-hosted) + TTS local + PBX/SIP + transcripción de audios de WhatsApp (Entregable #4).
- **IG DM / Messenger** (extensión del mismo patrón Graph API).
- **ERP real** (sync inventario/pedidos/órdenes).
- **Auto-respuesta autónoma** sin aprobación humana (requiere guardarraíles + métricas de calidad).
- **Campañas / envíos masivos por plantilla**, analítica avanzada, HA/Kubernetes.
- **Multimedia saliente rica** y transcripción de media entrante (solo persistencia de adjunto en el slice).

### 5.5 Requisitos funcionales (RF)

- **RF-01** Un mensaje entrante de WhatsApp con firma válida se recibe, se enruta a su tenant y se persiste.
- **RF-02** El mensaje aparece en tiempo real en la Bandeja del agente del tenant correcto (mismo push que WebChat).
- **RF-03** El mensaje entrante recibe etiqueta de **sentimiento** (LLM local) y se genera **borrador RAG con ≥3 citas**.
- **RF-04** El agente edita/aprueba el borrador y **envía**; el mensaje llega al cliente por la Graph API y queda persistido.
- **RF-05** Los **statuses** (entregado/leído) del webhook actualizan el estado del mensaje.
- **RF-06** Fuera de la ventana de 24 h, el sistema exige/usa una **plantilla aprobada** para el primer envío.
- **RF-07** Webhooks duplicados (mismo `wamid`) no crean mensajes duplicados (idempotencia).
- **RF-08** La SPA muestra el canal WhatsApp en la Bandeja respetando los contratos de tipo (feature-flag).

### 5.6 Requisitos NO funcionales (RNF)

- **RNF-01 IA 100% local:** cero inferencia en terceros; Meta solo transporte. Verificable por egress IA
  bloqueado + `check-externos-backend.sh` (el conector WhatsApp es la ÚNICA salida permitida, y solo a
  `graph.facebook.com` para transporte, allowlist explícita y auditada).
- **RNF-02 Latencia de webhook:** **ACK 200 ≤ 500 ms p95** (recepción rápida + proceso asíncrono), para
  evitar reintentos de Meta. Entrega del borrador RAG mantiene el objetivo del Entregable #2 (**p95 ≤ 6 s** con GPU).
- **RNF-03 Seguridad de datos personales (HABEAS DATA / GDPR-like):** TLS; secretos en env/secret manager
  (C3); firma HMAC obligatoria; borrado lógico (C2); tokens jamás en logs; minimización/retención configurable.
- **RNF-04 Aislamiento multi-tenant:** enrutado por número y RLS; ningún mensaje cruza tenants; test que lo demuestre.
- **RNF-05 Escalabilidad:** API stateless; recepción por cola Redis; reintentos idempotentes; rate-limit de envío hacia Meta.
- **RNF-06 Observabilidad:** métricas de latencia webhook/envío, tasa de entrega/error, logs estructurados con `tenant_id`/`wamid`.
- **RNF-07 Portabilidad on-prem:** todo levanta con `docker compose up`; solo el webhook requiere exposición HTTPS entrante (reverse proxy).

### 5.7 Restricciones DURAS (obligatorias)

- **R-01 SENSIBLE / `.no-externo`:** ninguna inferencia externa. WhatsApp Cloud API permitido SOLO como
  transporte del canal (allowlist `graph.facebook.com`); el contenido se procesa on-prem. El contenedor de
  IA mantiene egress bloqueado.
- **R-02 Secretos:** `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`,
  `WHATSAPP_APP_SECRET` **solo** en env/secret manager (C3), nunca en texto plano, repo, docs ni logs.
- **R-03 Firma obligatoria:** validación HMAC-SHA256 del webhook; sin firma válida → rechazo (401).
- **R-04 Borrado lógico:** Activo/Inactivo (C2); sin DELETE físico en entidades transaccionales.
- **R-05 Multi-tenant aislado:** enrutado por número + RLS; sin fugas cross-tenant.
- **R-06 Human-in-the-loop:** nada se envía autónomamente al cliente; el agente aprueba (sin auto-respuesta).
- **R-07 No romper Entregables #1/#2:** SPA y backend actuales siguen verdes; el canal WhatsApp se añade sin regresiones; feature-flag reversible.
- **R-08 Flujo del enjambre:** PLAN-003 aprobado por el Lead antes de SPECs; cada SPEC con criterios verificables (C4); cambios sensibles con aprobación explícita (C6) y notificación a Telegram.

### 5.8 Formato de salida esperado

- Conector WhatsApp (webhook + envío) integrado al backend existente, ejecutable con `docker compose up`.
- OpenAPI actualizado con los endpoints del webhook + colección de ejemplos (con simulador de webhook firmado).
- Migración de BD para el enrutado `phone_number_id → tenant_id` y campos de WhatsApp (versionada).
- SPA mostrando el canal WhatsApp en la Bandeja tras feature-flag, sin romper el Entregable #1.
- Runbook de operación del canal (alta de WABA, verificación de webhook, plantillas, rotación de token) — con placeholders, sin secretos.
- Evidencia auditable: firma HMAC verificada, "cero inferencia externa", aislamiento cross-tenant, latencia de webhook p95.

---

## 6. Stack / piezas LOCALES adicionales propuestas (justificación)

| Capa | Recomendación | Justificación (respeta `.no-externo`) |
| ---- | ------------- | ------------------------------------- |
| **Conector de canal** | Cliente propio **httpx** contra **WhatsApp Cloud API / Graph API** (`graph.facebook.com`) — **transporte, no inferencia** | Evita BSP intermediario que vería el contenido; única salida permitida, en allowlist explícita y auditada. |
| **Webhook** | Endpoint FastAPI + verificación `hub.challenge` + **HMAC-SHA256** (`X-Hub-Signature-256`) | Seguridad dura del canal; rechaza tráfico no firmado. |
| **Cola / async** | **Redis** (ya presente) + worker de ingesta WhatsApp análogo a `rag_ingest_worker` | ACK 200 rápido, procesamiento asíncrono, idempotencia por `wamid`, reintentos. |
| **Enrutado tenant** | Tabla `whatsapp_accounts (phone_number_id, tenant_id, ...)` + resolución en el webhook | Multi-tenant con RLS; mapeo número→tenant explícito y auditado. |
| **Pipeline IA** | **Reutilizar** Ollama (Qwen2.5-7B + nomic-embed) + RAG + sentimiento existentes | Cero piezas nuevas de IA; cero salida de contenido a terceros. |
| **Exposición HTTPS entrante** | Reverse proxy (Caddy/Nginx/Traefik) para el webhook, con TLS | Meta necesita un endpoint HTTPS público; solo se expone el webhook, no la IA. |
| **Secret manager** | env / Docker secrets / vault del host | Tokens de WhatsApp fuera del repo (C3). |
| **Observabilidad** | Métricas Prometheus (`/metrics` ya existe) + logs structlog con `wamid`/`tenant_id` | Latencia webhook/envío, tasa de entrega, auditoría. |

> **NOTA sobre (a) VoiceBot (Entregable #4, NO ahora):** cuando se aborde, el stack local será
> **faster-whisper / whisper.cpp** self-hosted para STT, **Piper** (o Coqui) para TTS, y **Asterisk /
> FreeSWITCH** para VoIP/SIP — todo on-prem, con GPU recomendada para STT casi en vivo. Se documenta
> aquí solo como dirección futura; **no entra** en el Entregable #3.

---

## 7. Criterios de éxito MEDIBLES (Entregable #3)

| ID | Criterio | Cómo se verifica |
| -- | -------- | ---------------- |
| **CE-31** | **Recepción firmada e idempotente:** un webhook de WhatsApp con firma HMAC válida se procesa una sola vez; firma inválida → 401; duplicado por `wamid` no crea mensaje doble | Test e2e con simulador de webhook firmado (válido/ inválido/ duplicado); revisión BLACK WIDOW. |
| **CE-32** | **Enrutado multi-tenant sin fugas:** el mensaje entrante se asigna al tenant del `phone_number_id` receptor; ningún dato cruza tenants | Test cross-tenant (HAWKEYE) que **falla por RLS/enrutado**; mensaje sin mapeo descartado y auditado. |
| **CE-33** | **Pipeline IA local sobre WhatsApp:** el mensaje recibe sentimiento y se genera borrador RAG con **≥3 citas trazables**, **sin inferencia externa** | Prueba e2e; `check-externos-backend.sh` verde; captura de red muestra salida solo a `graph.facebook.com` (transporte), nunca a APIs de inferencia. |
| **CE-34** | **Ciclo human-in-the-loop end-to-end:** el agente aprueba/edita y el mensaje se **envía** por Graph API, con estados de entrega actualizados; **nada se envía autónomamente** | Prueba e2e cliente⇄agente por WhatsApp (o simulador); statuses entregado/leído reflejados en BD. |
| **CE-35** | **Latencia y seguridad de webhook:** ACK 200 **p95 ≤ 500 ms**; tokens ausentes del repo/logs; TLS activo | Medición THOR bajo carga; escaneo BLACK WIDOW (secretos), inspección de logs; borrador RAG mantiene p95 ≤ 6 s (GPU). |

> Se añaden como transversales (heredados del Entregable #2): **no romper** SPA/backend existentes
> (suites verdes), cobertura backend **≥ 80%**, `docker compose up` reproducible, y **aprobación
> explícita del Lead** del slice (equivalente a CE-29).

---

## 8. Preguntas abiertas clave para el Lead (5) — con supuesto por defecto

Si el Lead no responde, el PLAN-003 procede con el **supuesto por defecto** indicado.

1. **Slice del Entregable #3 (⚠️ SUP-31):** ¿confirmas **WhatsApp Business API** como el slice (por ser
   on-brand, alto valor y máxima reutilización), **o** prefieres **VoiceBot local (a)** desde ya?
   **Supuesto por defecto:** **WhatsApp Business API**; VoiceBot queda como Entregable #4.

2. **Proveedor y credenciales (⚠️ SUP-32/SUP-33):** ¿usamos **WhatsApp Cloud API oficial de Meta**
   (sin BSP) y **hay WABA + número + tokens** disponibles? ¿Quién los provee?
   **Supuesto por defecto:** **Cloud API oficial de Meta**; si aún no hay credenciales, se entrega el
   conector completo + **simulador de webhook firmado** verificable en local, listo para conectar el token real.

3. **Ventana de 24 h y plantillas (SUP-35):** ¿el negocio necesita **iniciar** conversaciones fuera de la
   ventana de 24 h (plantillas/HSM aprobadas) o basta **responder dentro de ventana**?
   **Supuesto por defecto:** foco en **respuesta dentro de ventana** + **1 plantilla utilitaria** mínima;
   campañas/envíos masivos quedan fuera del slice.

4. **Human-in-the-loop vs autonomía (SUP-34):** ¿mantenemos **aprobación humana obligatoria** antes de
   enviar por WhatsApp, o el Lead quiere explorar auto-respuesta con guardarraíles?
   **Supuesto por defecto:** **human-in-the-loop obligatorio**; auto-respuesta (e) se difiere hasta tener
   métricas de calidad del borrador y guardarraíles.

5. **Hardware / volumen / cumplimiento (SUP-3A + hereda SUP-24/SUP-26):** ¿sigue vigente **GPU ≥16 GB**
   (o fallback CPU Q4), escala **piloto** y cumplimiento **HABEAS DATA + GDPR-like** (no PHI)?
   **Supuesto por defecto:** **sí** a los tres; el envío/recepción WhatsApp no cambia el dimensionamiento
   de IA del Entregable #2; se mantiene un solo host Docker Compose para el piloto.

---

## 9. Siguiente paso en el flujo

Entregar este prompt a **🔮 DOCTOR STRANGE** para el **PLAN-003** (`.swarm/PLAN-003.md`), que el Lead
deberá aprobar ("APROBADO PLAN-003") antes de generar SPECs. Cumple CHECKPOINT **C8**.
