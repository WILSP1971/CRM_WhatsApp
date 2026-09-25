# PLAN-006 — Fase 5 (redefinida) "Voz asíncrona en WhatsApp" (Entregable #5): notas de voz del cliente descargadas + transcritas con STT LOCAL, respondidas con TEXTO (human-in-the-loop) — NO VoiceBot en vivo

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Fecha: 2026-09-25 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo` presente) — PROHIBIDO cualquier modelo/servicio EXTERNO de inferencia o de procesamiento de datos personales por un tercero.
> **DATO ESPECIAL DE ESTA FASE:** la **nota de voz de WhatsApp es dato personal (posible PHI)**, exactamente como el audio de llamadas del Entregable #4. El **STT es 100% LOCAL** (`faster-whisper`, mismo motor de SPEC-038): el audio **NUNCA** sale a terceros (Google STT, AWS Transcribe, OpenAI Whisper API, Deepgram, AssemblyAI, Azure Speech y equivalentes **PROHIBIDOS**). El `stt_worker` corre **SIN egress** en `ia_internal`, tal como ya está desplegado. Ver §3 y ADR-009 (heredado).
> **EXCEPCIÓN ACOTADA (descarga de media de Meta):** descargar el binario de la nota de voz desde la Graph API es **TRANSPORTE acotado** ya cubierto por ADR-006/SPEC-024: se hace **SOLO** dentro de `app/integrations/whatsapp/`, con **allowlist al host ya permitido `graph.facebook.com`**, **NUNCA** desde el `stt_worker`/IA. **NO hay egress nuevo**: es el mismo host y el mismo módulo que el canal WhatsApp ya usa para enviar. Ver §3.3.
> Origen: `prompt-lab/PROMPT-OPTIMIZADO-FASE5-NOTAS-VOZ-WHATSAPP.md` (🧠 XAVIER) · Estado: **PROPUESTA** (espera "APROBADO PLAN-006")
> Regla de oro: este PLAN **NO genera SPECs**. Las SPECs se crean SOLO tras la aprobación explícita del Lead ("APROBADO PLAN-006").
> Precedente directo reutilizable: **PLAN-004** (Entregable #4 — `stt_worker`, `stt_engine.py`, `audio_store.py` cifrado, retención SPEC-041, `check-externos-backend.sh`). **PLAN-005 ARCHIVADO** (VoiceBot telefónico en vivo — inviable sin GPU; SPEC-044 conservada, SPEC-045..052 archivadas): **este plan no lo retoma ni lo toca**.
> Precedente de patrón (no de entidad): el Entregable #4 modela una llamada como `call`/`call_transcript`. **Este plan NO crea `call`**: extiende `Message`/`Conversation` de WhatsApp (Entregable #3), que ya son reales. Solo se reutiliza el **patrón** de STT batch, cifrado y retención.
> Respuestas del Lead ya confirmadas (§12): **P1 = límite 10 min** (configurable por env). **P2 = solo respuesta en TEXTO**, sin TTS de salida en este slice.
> Contadores vigentes (`.swarm/specs.json`): `next_plan: 6`, `next_spec: 53`, `next_adr: 13`. (No se tocan hasta crear specs reales tras aprobación.)

---

## 1. Objetivo y contexto

### Objetivo

Construir el **Entregable #5 (redefinido)** como un **vertical slice de máximo valor / mínimo riesgo y máxima reutilización**: hacer que una **nota de voz enviada por el cliente por WhatsApp** deje de descartarse, se **descargue** desde la Graph API de Meta (transporte ya permitido), se **almacene cifrada** en el almacén on-prem ya existente (SPEC-035), se **transcriba con STT 100% LOCAL** reutilizando el motor `stt_engine.py` de SPEC-038, y quede como **`Message.contenido` (texto) dentro de la `Conversation` real de WhatsApp** — indistinguible, a partir de ese punto, de un mensaje de texto normal para el resto del pipeline. Sobre ese texto se dispara **sin cambios** el enriquecimiento IA local ya construido (sentimiento SPEC-018, resumen, borrador RAG con **≥3 citas** SPEC-017, **human-in-the-loop** SPEC-019), y el agente **responde con TEXTO** por el mecanismo de borrador ya existente. Proceso **ASÍNCRONO** (Redis + worker), **idempotente por `wamid`** (ADR-007), **sin GPU**, **sin latencia dura**, **sin egress nuevo**.

El **VoiceBot conversacional en vivo** (PLAN-005) queda fuera y archivado. La **respuesta en audio (TTS)** queda **explícitamente fuera** de este slice (§2 OUT, confirmado por el Lead P2). **Instagram** queda fuera (SUP-66).

### Contexto y relación con Entregables #3/#4 (qué se reutiliza tal cual)

- **El canal WhatsApp ya existe (Entregable #3):** webhook con firma HMAC (SPEC-026), `wa_inbound_worker` idempotente por `wamid` (SPEC-027, ADR-007), enrutado `phone_number_id → tenant_id` (SPEC-025), `Conversation`/`Message` con RLS efectiva (ADR-008), envío saliente por Graph API con human-in-the-loop (SPEC-029). **Lo único que falta:** que `inbound_parser` deje de descartar el tipo `audio` como placeholder, y una **función de descarga de media** (hoy `graph_client` solo envía).
- **El pipeline STT ya existe (Entregable #4):** `stt_worker` + `stt_engine.py` (`faster-whisper` es-CO local, sin egress, en `ia_internal`), `audio_store.py` (cifrado en reposo, SPEC-035), cola `stt:jobs` (contrato de SPEC-037/038), política de retención (SPEC-041), auditoría `check-externos-backend.sh`. Se reutiliza el **motor de transcripción como librería**; lo único nuevo es el **destino de escritura** de la transcripción (§3.4, punto crítico).
- **El pipeline IA local ya existe (Entregables #2/#3):** sentimiento (SPEC-018), resumen + borrador RAG ≥3 citas (SPEC-017), human-in-the-loop (SPEC-019). Una vez la nota de voz es texto en `Message.contenido`, **es el mismo camino que sigue hoy un WhatsApp de texto** (SPEC-028): **cero cambios** en enriquecimiento.
- **Multi-tenant, cifrado, retención, secretos, egress** heredados sin rediseño: RLS FORCE (ADR-004/008), C2/C3, `.no-externo`, `graph.facebook.com` ya en la allowlist de transporte (ADR-006/SPEC-024).

**Novedad estructural de esta fase (mínima y acotada):** (a) **descargar** el binario de la nota de voz desde `graph.facebook.com` (mismo host/módulo ya permitido — sin egress nuevo); (b) **enganchar** el `Message` de audio al pipeline STT existente de forma que la transcripción se escriba **de vuelta en `Message.contenido`** (no en una `call_transcript`); (c) **límite de duración** con descarte amable; (d) **extender** la política de retención/cifrado (SPEC-041) para cubrir también audio de mensajería.

---

## 2. Alcance IN / OUT

### IN — entra en el vertical slice #5

1. **`inbound_parser` extendido:** reconoce `type=="audio"` en el payload del webhook de WhatsApp (hoy lo descarta como placeholder), extrae `media_id`, `mime_type`, duración (si Meta la provee), `wamid` y metadatos. Crea el `Message` con tipo `audio` en la `Conversation` real (mismo flujo idempotente de SPEC-027).
2. **Descarga de media de WhatsApp (transporte, sin egress nuevo):** nueva función en `app/integrations/whatsapp/` (`graph_client` o módulo hermano `media_client`): resuelve la URL temporal del media (GET `graph.facebook.com/{media-id}`) y descarga el binario con el token de acceso (segundo GET a la URL temporal, host de Meta). **Mismo host ya permitido `graph.facebook.com`, mismo módulo ya autorizado** (ADR-006/SPEC-024) — **cero egress nuevo**.
3. **Almacenamiento cifrado (reutiliza SPEC-035):** el binario descargado se guarda en el **mismo `audio_store.py` cifrado on-prem** del Entregable #4; se persiste una referencia opaca `audio_ref` en el `Message` (mismo patrón que `call.audio_ref`).
4. **Modelo de datos = extensión aditiva mínima de `Message`** (NO entidad nueva): campo(s) nuevo(s) en `Message` para tipo de mensaje (`audio`) y `audio_ref` opcional. Migración Alembic **aditiva** (columnas nullable, sin romper #1–#4). Ver §3.5.
5. **Encolado al pipeline STT existente:** el `Message` de audio se encola en `stt:jobs` (**mismo contrato de SPEC-037/038**) con el `audio_ref`, `tenant_id`, `wamid` y un **destino** que indica "escribir en `Message`" (ver §3.4).
6. **Transcripción escrita en `Message.contenido`** (el enganche crítico, §3.4): el motor `stt_engine.py` transcribe (reutilizado tal cual como librería) y el texto se persiste en `Message.contenido`; a partir de ahí el mensaje es **indistinguible** de un texto normal.
7. **Enriquecimiento IA local REUTILIZADO sin cambios:** una vez el `Message` tiene texto, se dispara el mismo camino de SPEC-028 → sentimiento (SPEC-018) + resumen + borrador RAG ≥3 citas (SPEC-017) + **human-in-the-loop** (SPEC-019). **Respuesta SIEMPRE en TEXTO** (SPEC-029).
8. **Límite de duración configurable (10 min, P1 confirmado):** si la nota excede el límite, **descarte amable con auto-respuesta** ("nota muy larga, por favor resume o escribe tu consulta") por el mismo mecanismo de envío — **no error silencioso**. Se registra el descarte auditado.
9. **Retención/cifrado extendido (extiende SPEC-041, no crea política paralela):** la política configurable ya existente se **amplía** para cubrir también `audio_ref` de mensajería (mismo job de purga/anonimización, mismo cifrado en reposo, mismo acceso auditado).
10. **Idempotencia por `wamid` (ADR-007, sin nada nuevo):** reentrega del mismo `wamid` no re-descarga, no re-transcribe, no re-enriquece. Se confirma que **basta el mecanismo actual** (no se introduce `call_id`).
11. **(Frontend, mínimo/a confirmar con DAREDEVIL):** posible indicación visual "transcrito de audio" en la ficha de conversación y, según retención, un reproductor del clip. Si no aporta valor claro, queda como sub-tarea opcional; la bandeja ya muestra `Message.contenido`.
12. **Observabilidad + auditoría:** métricas de descargas de media, transcripciones de mensajería, descartes por límite, RTF reutilizado; `check-externos-backend.sh` sigue verde (cero STT/inferencia a terceros; descarga solo a `graph.facebook.com` desde el módulo WhatsApp).

### OUT — NO entra en este slice (fase futura / decisión aparte)

- **Respuesta en audio (TTS)** de cualquier tipo (Piper/Coqui): **explícitamente fuera** (P2 confirmado por el Lead). No por imposibilidad técnica (TTS local en CPU sería viable sin latencia dura), sino porque abre una pregunta de diseño no resuelta: **¿cómo aprueba un agente humano un audio antes de enviarlo** — escucha el clip generado, o aprueba solo la transcripción de lo que diría? Queda como **extensión futura explícita** (posible Entregable #6). Ver ADR recomendado ADR-013 (registra la decisión de aplazamiento).
- **Canal Instagram** (SUP-66): no existe como canal; añadirlo sería del tamaño de reconstruir el Entregable #3 para otra plataforma. Decisión de negocio aparte.
- **Cualquier diálogo en vivo / streaming / VoiceBot telefónico:** descartado por falta de GPU (motivo de esta redefinición). PLAN-005 archivado, no se retoma.
- **Media de WhatsApp que no sea audio** (imágenes, documentos, video, stickers): fuera de este slice; el `inbound_parser` puede seguir tratándolos como placeholder o registrarlos sin procesar. Solo se activa el tipo `audio`.
- **Entidad `call`/`call_transcript`:** NO se crea ni se reutiliza como modelo. La nota de voz vive en `Message`.
- **Diarización de la nota de voz:** innecesaria (una nota de voz es de un único locutor, el cliente). El motor puede omitir el paso de diarización de SPEC-038.

---

## 3. Arquitectura de referencia

### 3.1 Flujo end-to-end

```
recepción:  Cliente --nota de voz--> WhatsApp Cloud --webhook (firma HMAC, SPEC-026)--> [api]
            [wa_inbound_worker] --dedup por wamid (ADR-007)--> inbound_parser reconoce type=="audio"
            --> crea Message(tipo="audio", contenido=NULL) en la Conversation real [RLS por tenant]

descarga:   [worker/servicio WhatsApp en `app`] --GET graph.facebook.com/{media-id}--> URL temporal
            --GET {url temporal} (token)--> binario  [host ya permitido, módulo ya autorizado — SIN egress nuevo]
            --> guarda en audio_store.py CIFRADO on-prem (SPEC-035) --> Message.audio_ref = ref opaca
            --> chequeo de duración: si > límite (10 min) --> DESCARTE AMABLE (auto-respuesta) + audit, FIN
            --> si OK --> encola en Redis `stt:jobs` (contrato SPEC-037/038) con destino="message:{id}"

transcripción (SIN egress, en `ia_internal`):
            [Redis stt:jobs] --> [stt_worker] --usa stt_engine.py (faster-whisper es-CO, mismo motor SPEC-038)-->
            texto --> ESCRIBE Message.contenido = transcripción  (NO crea call_transcript)  [RLS por tenant]
            --> a partir de aquí el Message es indistinguible de un texto normal

enriquecimiento (REUTILIZA, sin cambios — mismo camino que SPEC-028):
            Message con texto --> sentimiento (SPEC-018) + resumen + borrador RAG ≥3 citas (SPEC-017)
            --> [human-in-the-loop SPEC-019] agente revisa/edita/APRUEBA
            --> responde con TEXTO por Graph API (SPEC-029)   [TTS de salida = FUERA, P2]

retención:  política configurable (SPEC-041 EXTENDIDA a audio de mensajería) --> purga/anonimización de
            audio_ref y/o transcripción; acceso auditado (HABEAS DATA/PHI)
```

### 3.2 Componentes y DÓNDE está el límite de egress (diagrama ASCII)

```
                                   HOST ON-PREM (Docker Compose) — topología YA desplegada
  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
  │                                                                                                │
  │   red `app` (bridge, egress restringido por allowlist SOLO a graph.facebook.com — ADR-006)     │
  │   ┌──────────────────────────────────────────────────────────────────────────────────┐        │
  │   │  [reverse proxy TLS]──►[api FastAPI]──►[Redis colas+pubsub]──►[PostgreSQL/RLS]      │        │
  │   │     (webhook WhatsApp)       │  ▲                 │                                  │        │
  │   │                              │  │                 ▼                                  │        │
  │   │          [wa_inbound_worker] │  └──[app/integrations/whatsapp: graph/media_client]─┐ │        │
  │   │                              │        (envío YA existente + DESCARGA de media NUEVA) │ │        │
  │   └──────────────────────────────┼───────────────────────────────────────────────────┼─┘        │
  │                                  │  ═════════ LÍMITE DE EGRESS (ya existente) ════════│           │
  │                                  │  Solo el módulo WhatsApp sale, y SOLO a            ▼           │
  │                                  │  graph.facebook.com (allowlist ADR-006)  ►► Meta Graph API      │
  │                                  │                                                                │
  │   [almacén de audio CIFRADO on-prem: audio_store.py / volumen-MinIO]  (nunca a un tercero)       │
  │                                  │                                                                │
  │   red `ia_internal` (bridge, internal: true — ⛔ SIN egress, NUNCA internet)                      │
  │   ┌──────────────────────────────▼─────────────────────────────────────────────────┐           │
  │   │  [stt_worker + stt_engine.py = faster-whisper es-CO]  ⛔ jamás alcanza internet    │           │
  │   │  [ia = Ollama] LLM local + embeddings   [rag_worker] [sentiment_worker]  ⛔        │           │
  │   └──────────────────────────────────────────────────────────────────────────────┘           │
  └─────────────────────────────────────────────────────────────────────────────────────────────┘
   ⛔ = internal:true, sin ruta a internet   ►► = ÚNICO egress permitido (transporte de media WhatsApp, YA autorizado)
```

**Regla de oro de la topología (invariante de seguridad, YA vigente — no se toca):**

- El **`stt_worker`/IA** vive **SOLO** en `ia_internal` (`internal: true`): **NUNCA** descarga media ni alcanza `graph.facebook.com`. Recibe el audio desde el **almacén cifrado on-prem** (mismo `audio_ref`), no por red externa. La descarga la hizo antes el módulo WhatsApp en `app`.
- La **descarga de media** vive **solo** en `app/integrations/whatsapp/` (mismo módulo que ya envía), con salida **solo** a `graph.facebook.com`. **No es egress nuevo**: es el host y el módulo ya permitidos por ADR-006/SPEC-024. `check-externos-backend.sh` no necesita una allowlist nueva — solo verificar que la descarga siga **dentro** de ese módulo.
- El **límite de egress no cambia**: sigue siendo `graph.facebook.com` desde el módulo WhatsApp. **El audio y la inferencia jamás salen** del host.

### 3.3 Por qué NO hay egress nuevo (diferencia clave con PLAN-004)

En PLAN-004, si el PBX era externo, había que **abrir** un egress nuevo a un host de PBX (ADR-010). **Aquí no**: la nota de voz llega por el canal WhatsApp que **ya** tiene autorizado `graph.facebook.com` (ADR-006/SPEC-024) para enviar mensajes. Descargar media es el **mismo host, mismo módulo, mismo token** — solo un verbo GET adicional. Por eso este plan **no requiere un ADR de egress nuevo** (a diferencia de ADR-010). La única verificación de CI es negativa: que la función de descarga **no** se importe ni ejecute desde el `stt_worker`/IA (el STT no descarga: recibe del almacén).

### 3.4 El enganche crítico al `stt_worker` existente (punto técnico central — decisión y justificación)

**Problema:** el `stt_worker` de SPEC-038 hoy transcribe y **persiste en `call_transcript`** ligado a una `call`. Aquí la transcripción debe ir a **`Message.contenido`** dentro de una `Conversation` de WhatsApp. Necesitamos reutilizar el motor sin acoplar el resultado a la entidad `call`.

**Decisión: NO se crea un worker nuevo separado. Se refactoriza el `stt_worker` existente para que sea agnóstico del destino, extrayendo `stt_engine.py` como librería pura de transcripción (que YA lo es) y parametrizando el "sink" de escritura por el `job`.** Es decir: **una rama nueva del worker existente gobernada por el campo `destino` del job**, no un worker paralelo duplicado.

Justificación:

1. **`stt_engine.py` ya es una librería de transcripción pura** (entra audio → sale texto/segmentos); no conoce `call` ni `Message`. Reutilizarlo tal cual es correcto y ya está diseñado así en el Entregable #4. **No se toca el motor.**
2. **Lo que acopla al destino es el "sink" de persistencia**, no el motor. El contrato de `stt:jobs` (SPEC-037/038) se **extiende de forma aditiva** con un campo `destino` (o `sink`): `call:{id}` (comportamiento actual, intacto) o `message:{id}` (nuevo). El worker, tras transcribir con `stt_engine.py`, **despacha al sink correspondiente**: escribir `call_transcript` (existente) o escribir `Message.contenido` (nuevo).
3. **Un worker paralelo duplicaría** la carga del modelo Whisper en memoria (coste real sin GPU), la lógica de reintentos, la instrumentación RTF y el aislamiento `ia_internal` — **duplicación innecesaria y riesgo de divergencia**. Un solo worker con un sink parametrizado es DRY, mantiene un único punto de aislamiento y no cambia la topología.
4. **No hay riesgo de regresión** si el `destino` por defecto/ausente sigue siendo `call` (los jobs de #4 no cambian). Es una extensión aditiva del contrato de cola, igual que la migración de datos es aditiva.

Consecuencia para las SPECs: habrá una SPEC de "extensión del `stt_worker` con sink parametrizado + sink `message`" (destino de escritura), no una SPEC de "worker nuevo". El motor `stt_engine.py` **no** se modifica; se añade el sink y el enrutado por `destino`.

### 3.5 Modelo de datos: extensión aditiva mínima de `Message` (NO entidad nueva)

- **NO se crea `call`/`call_transcript`.** La nota de voz es un `Message` real dentro de la `Conversation` real de WhatsApp (Entregable #3).
- **Campos nuevos en `Message` (aditivos, nullable):**
  - un discriminador de **tipo de mensaje** que admita `audio` (si el proyecto ya tiene un campo de tipo/`kind` en `Message`, se **reutiliza** ese enum/columna añadiendo el valor `audio`; si no existe, se añade columna `tipo` nullable con default `texto`). A confirmar el nombre exacto en la SPEC leyendo el modelo real.
  - `audio_ref` **opcional** (nullable), referencia opaca al almacén cifrado (mismo patrón que `call.audio_ref`, SPEC-035). NULL para mensajes de texto.
  - (opcional) `audio_duracion_seg` / `transcripcion_estado` (`pendiente`/`ok`/`descartada_por_duracion`/`error`) para observabilidad del estado de transcripción, nullable.
- **`Message.contenido`** guarda la **transcripción** una vez el `stt_worker` la escribe; antes es NULL/placeholder. Para el resto del pipeline, tras la transcripción, es un mensaje de texto normal.
- **Migración Alembic aditiva** (columnas nullable, sin backfill destructivo): no rompe #1–#4, mensajes de texto siguen exactamente igual (RNF-64).
- **Idempotencia por `wamid`** (ADR-007, ya existente): el `Message` de audio ya se deduplica por `wamid` en `wa_inbound_worker` (SPEC-027). **No se necesita `call_id` ni ningún identificador nuevo.** Basta con guardas adicionales: no re-descargar si `audio_ref` ya existe, no re-transcribir si `contenido` ya está poblado / `transcripcion_estado == ok`.

### 3.6 Retención/cifrado: extiende SPEC-041, no crea política paralela

- El `audio_ref` de mensajería se cifra en reposo con el **mismo `audio_store.py`** (SPEC-035) y se rige por la **misma política configurable de SPEC-041** (mismo job de purga/anonimización, mismo cifrado, mismo acceso auditado). Se **amplía** el alcance de la política para que su selector cubra también audio cuyo origen es `Message`/WhatsApp, no solo `call`. **Un solo régimen de retención**, no dos.

---

## 4. Fases y entregables

| Fase   | Nombre                                                    | Entregables clave                                                                                                                                                                                                                                                     |
| ------ | -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **F0** | Modelo de datos: extensión aditiva de `Message`          | Migración Alembic **aditiva** (nullable): tipo de mensaje admite `audio`, `audio_ref` opcional, `transcripcion_estado`/`audio_duracion_seg` opcionales; RLS heredada intacta; borrado lógico (C2); seed ficticio de nota de voz. **NO crea `call`/`call_transcript`.** |
| **F1** | Descarga de media de WhatsApp (transporte, sin egress nuevo) | Función de descarga en `app/integrations/whatsapp/` (resuelve URL temporal `graph.facebook.com/{media-id}` + descarga binario con token); almacenamiento cifrado en `audio_store.py` (SPEC-035) → `Message.audio_ref`; idempotencia (no re-descarga si `audio_ref` ya existe); errores de descarga auditados. **Mismo host/módulo ya permitido — cero egress nuevo.** |
| **F2** | `inbound_parser` extendido + límite de duración          | `inbound_parser` reconoce `type=="audio"` (deja de descartar el placeholder), crea el `Message(tipo="audio")` idempotente por `wamid` (SPEC-027); chequeo de límite de duración (10 min, env) con **descarte amable + auto-respuesta** (SPEC-029) y audit; encolado en `stt:jobs` con `destino="message:{id}"`. |
| **F3** | Enganche STT: sink parametrizado por `destino` (rama del worker existente) | Extensión **aditiva** del contrato `stt:jobs` con `destino`; refactor del `stt_worker` para despachar a un **sink** (`call` existente / `message` nuevo) reutilizando `stt_engine.py` **sin tocar el motor**; el sink `message` escribe la transcripción en `Message.contenido`; reintentos idempotentes; sin egress; **jobs de #4 (`call`) intactos**. Núcleo técnico de esta fase (§3.4). |
| **F4** | Enriquecimiento IA local (REUTILIZA, cero cambios)       | Tras poblar `Message.contenido`, se dispara el mismo camino de SPEC-028: sentimiento (SPEC-018) + resumen + borrador RAG ≥3 citas (SPEC-017) + **human-in-the-loop** (SPEC-019); **respuesta SIEMPRE en TEXTO** (SPEC-029). Sin inferencia externa. Idealmente **cero código nuevo** salvo el disparo del pipeline al completar la transcripción. |
| **F5** | Retención/cifrado extendido (extiende SPEC-041)          | Ampliar el selector de la política de retención/purga/anonimización para cubrir `audio_ref` de mensajería; cifrado en reposo verificado; acceso auditado (HABEAS DATA/PHI); **una sola política**, sin régimen paralelo. |
| **F6** | (Opcional) SPA: indicación "transcrito de audio" + reproductor | Con DAREDEVIL: badge/indicador visual de mensaje transcrito de audio en la ficha de conversación y, según retención, reproductor del clip; tras feature-flag si aplica; sin romper #1–#4. Puede omitirse si no aporta valor claro (la bandeja ya muestra `Message.contenido`). |
| **F7** | Pruebas + seguridad + observabilidad                     | Nota de voz ficticia e2e (descarga→transcripción→`Message.contenido`→enriquecimiento); reentrega por `wamid` no duplica; nota que excede límite → auto-respuesta (no error silencioso); cross-tenant (falla por RLS); prueba de egress vacío desde `stt_worker`; `check-externos-backend.sh` verde; barrido BLACK WIDOW; cobertura del código nuevo **≥80%**; suites #1–#4 sin regresión. |
| **F8** | Docs + runbook + deploy on-prem                          | Actualización de runbook (descarga de media, límite de duración configurable, extensión de retención a mensajería), OpenAPI/notas del parser, **simulador de nota de voz** verificable en local; deploy on-prem (QUICKSILVER, con aprobación del Lead). |

---

## 5. Dependencias entre fases y ruta crítica

- **F0** (extensión de `Message`) habilita todo: sin `audio_ref`/tipo `audio` no hay dónde persistir. Prerequisito duro de F1–F5.
- **F1** (descarga) depende de F0 (necesita `audio_ref`) — puede solaparse con F2.
- **F2** (`inbound_parser` + límite) depende de F0 y de F1 (necesita el audio descargado/almacenado para encolar); es la puerta de ingesta.
- **F3** (enganche STT, sink `message`) depende de F2 (job encolado con `destino=message`); **es el núcleo técnico** (§3.4).
- **F4** (enriquecimiento) depende de F3 (transcripción persistida en `Message.contenido`); reutiliza SPEC-017/018/019/028/029 — mínimo código nuevo.
- **F5** (retención) transversal: se diseña desde F0/F1 (cifrado) y se **cierra** ampliando SPEC-041 al final.
- **F6** (SPA) opcional, depende de F3/F4 (necesita transcripción real); puede solaparse o descartarse.
- **F7** depende de que F1–F5 estén completas (prueba el slice completo).
- **F8** cierra: runbook/docs/simulador/deploy tras F5/F7.

**Ruta crítica:** `F0 → F1 → F2 → F3 → F4 → F7 → F8` (F5 transversal, F6 opcional). La **ruta crítica dura** es **F3 (enganche STT con sink parametrizado)**: es el único punto donde se refactoriza código del Entregable #4, y el que debe garantizar cero regresión en los jobs `call` existentes.

---

## 6. Riesgos y mitigaciones

| #        | Riesgo                                                                                                             | Impacto                           | Mitigación                                                                                                                                                                                                                              |
| -------- | ---------------------------------------------------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R-61** | **Audio o inferencia a un tercero** (STT de terceros, o que la descarga abra ruta al `stt_worker`/IA → rompe SENSIBLE, expone PHI). | **Crítico** (rompe política, PHI) | Invariante de topología **ya vigente** (§3.2): STT/IA solo en `ia_internal internal:true`; descarga solo desde el módulo WhatsApp a `graph.facebook.com`. STT de terceros PROHIBIDOS en CI. **El STT no descarga** (recibe del almacén). Prueba de egress vacío desde `stt_worker`. Hereda ADR-005/006/009. |
| **R-62** | **Regresión en los jobs `call` del Entregable #4** al refactorizar el `stt_worker` para sink parametrizado.        | Alto (rompe #4)                   | `destino` por defecto/ausente = `call` (comportamiento actual intacto); extensión **aditiva** del contrato de cola; el motor `stt_engine.py` **no se toca**; test de no-regresión de un job `call` existente que sigue escribiendo `call_transcript`. |
| **R-63** | **Cifrado/almacenamiento del audio de mensajería** (audio en claro, o fuga por permisos).                          | Alto (PHI/HABEAS DATA)            | Reutiliza `audio_store.py` cifrado (SPEC-035) sin excepción; permisos mínimos; almacén sin exposición pública; barrido BLACK WIDOW; extiende SPEC-041 (misma política). |
| **R-64** | **Retención/PHI** (audio/transcripción de mensajería retenidos de más, o acceso no auditado).                      | Alto (cumplimiento)               | **Extender SPEC-041** al `audio_ref` de mensajería (un solo régimen); purga/anonimización configurable; acceso auditado (HABEAS DATA). Sin política paralela que pueda quedar desincronizada. |
| **R-65** | **Idempotencia por `wamid` insuficiente** (reentrega del webhook → re-descarga/re-transcripción/enriquecimiento duplicado). | Alto (datos/UX/coste)             | Reutiliza `wamid` (ADR-007, SPEC-027) **sin nada nuevo**; guardas: no re-descargar si `audio_ref` existe, no re-transcribir si `contenido`/`transcripcion_estado==ok`; test de reentrega que no duplica. **Se confirma que NO hace falta `call_id`.** |
| **R-66** | **Nota de voz muy larga** (transcribir contenido desproporcionado, coste CPU sin GPU, o timeout).                  | Medio (coste/UX)                  | Límite configurable **10 min** (P1); si excede → **descarte amable con auto-respuesta** (no error silencioso, no se encola STT); chequeo antes de encolar. |
| **R-67** | **URL de media temporal expira** entre resolución y descarga (Meta la caduca rápido).                              | Medio (fallo de descarga)         | Descargar el binario inmediatamente tras resolver la URL; reintento acotado con backoff dentro del módulo WhatsApp; si falla definitivo → estado `error` auditado, sin bloquear el hilo. |
| **R-68** | **`Message` sin campo de tipo previo** (si el modelo real no tiene discriminador de tipo, la migración es mayor de lo previsto). | Bajo/Medio                        | La SPEC de F0 **lee el modelo real** antes de decidir: reutiliza el enum/columna existente si la hay, o añade columna `tipo` nullable con default `texto`. Migración aditiva en ambos casos. |
| **R-69** | **Latencia/coste de STT sin GPU** (transcripción batch en CPU para notas de varios minutos).                       | Medio (throughput)                | Asíncrono, sin latencia dura (como cualquier WhatsApp); RTF instrumentado reutilizado de #4; N `stt_worker` escalables; límite de 10 min acota el peor caso; VAD del motor salta silencios. |
| **R-70** | **Regresión en el canal WhatsApp de texto** (#3) al extender `inbound_parser`.                                     | Medio                             | La rama `type=="audio"` es **aditiva**; los tipos texto siguen el camino actual sin cambios (RNF-64); test de no-regresión de un WhatsApp de texto. |

**Top-3:** **R-61 (audio/inferencia a terceros — PROHIBIDO)**, **R-62 (regresión en jobs `call` de #4 al parametrizar el sink del `stt_worker`)**, **R-63/R-64 (cifrado y retención/PHI del audio de mensajería)**. R-65 (idempotencia `wamid`) y R-70 (regresión canal texto) inmediatamente detrás.

---

## 7. Criterios de éxito verificables (mapeo con CE-61..CE-65 de XAVIER)

| ID        | Criterio                                                                                                                                            | Cómo se verifica                                                                                                                          | Fase        |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| **CE-61** | **Nota de voz end-to-end:** una nota de voz ficticia por WhatsApp se descarga, transcribe con `faster-whisper` local, y aparece como `Message.contenido` (texto) en la conversación real; **cero** STT de terceros. | Test e2e con nota de voz ficticia + captura de red (cero salida a STT de terceros; descarga solo a `graph.facebook.com`) + `check-externos-backend.sh` verde. | F1/F3/F7    |
| **CE-62** | **Enriquecimiento reutilizado sin inferencia externa:** la transcripción recibe sentimiento + resumen + borrador RAG **≥3 citas**; egress público nulo desde STT/IA; respuesta **en texto** con human-in-the-loop. | e2e; prueba de egress vacío desde `stt_worker`/`ia`; borrador con ≥3 citas trazables; envío por SPEC-029 tras aprobación humana.          | F4/F5/F7    |
| **CE-63** | **Idempotencia por `wamid` + aislamiento:** reentrega del mismo `wamid` no re-descarga/re-transcribe/duplica enriquecimiento; test cross-tenant sobre `Message`/`audio_ref` que **falla por RLS**. | Test de reentrega idempotente por `wamid` (ADR-007); test cross-tenant (HAWKEYE) con rol app no-superusuario (ADR-008).                    | F0/F2/F7    |
| **CE-64** | **Límite de duración con descarte amable:** nota de voz que excede 10 min → **auto-respuesta clara**, no error silencioso, no se encola STT; descarte auditado. | Test con nota > límite: verifica auto-respuesta (SPEC-029), ausencia de job STT, registro de descarte.                                     | F2/F7       |
| **CE-65** | **Privacidad/retención + no-regresión:** audio de mensajería **cifrado en reposo** y regido por SPEC-041 extendida; **jobs `call` de #4 intactos**; suites #1–#4 verdes; cobertura código nuevo **≥80%**. | Inspección de cifrado; test de purga por política; test de no-regresión de job `call`; suites #1–#4; cobertura; `docker compose up` reproducible sin internet de inferencia. | F3/F5/F7    |

> Transversales heredados: **aprobación explícita del Lead**; CHECKPOINTS C2 (borrado lógico) / C3 (secretos) / C4 (criterios verificables) / C6 (cambio sensible → notificación Telegram) / C8 (prompt registrado en `prompt-lab/PROMPT-OPTIMIZADO-FASE5-NOTAS-VOZ-WHATSAPP.md`).

---

## 8. Mapa preliminar de SPECs propuestas (SOLO el mapa — NO son las specs)

> Continúa la numeración desde `specs.json` (`next_spec: 53`). Se crearán únicamente tras "APROBADO PLAN-006". Cada SPEC llevará criterios verificables (C4).

- **SPEC-053** — Modelo de datos: extensión **aditiva** de `Message` para nota de voz (tipo `audio`, `audio_ref` opcional, `transcripcion_estado`/`audio_duracion_seg` opcionales); migración Alembic aditiva, RLS heredada, borrado lógico (C2), seed ficticio. **NO crea `call`/`call_transcript`** (F0).
- **SPEC-054** — Descarga de media de WhatsApp (transporte, sin egress nuevo): función en `app/integrations/whatsapp/` que resuelve URL temporal `graph.facebook.com/{media-id}` y descarga el binario con token; almacenamiento cifrado en `audio_store.py` (SPEC-035) → `Message.audio_ref`; idempotencia y errores auditados; reintento por URL expirada (F1).
- **SPEC-055** — `inbound_parser` extendido + límite de duración: reconoce `type=="audio"`, crea `Message(tipo="audio")` idempotente por `wamid` (SPEC-027), chequeo de límite 10 min con **descarte amable + auto-respuesta** (SPEC-029) y audit, encolado en `stt:jobs` con `destino="message:{id}"` (F2).
- **SPEC-056** — Enganche STT (sink parametrizado): extensión **aditiva** del contrato `stt:jobs` con `destino`; refactor del `stt_worker` a **sink** (`call` existente / `message` nuevo) reutilizando `stt_engine.py` **sin tocar el motor**; el sink `message` escribe en `Message.contenido`; reintentos idempotentes; sin egress; jobs `call` de #4 intactos (F3).
- **SPEC-057** — Enriquecimiento IA local sobre la transcripción de nota de voz: reutiliza SPEC-028 (sentimiento SPEC-018, resumen + borrador RAG ≥3 citas SPEC-017, human-in-the-loop SPEC-019), respuesta **solo texto** (SPEC-029), sin inferencia externa; mínimo código nuevo (F4).
- **SPEC-058** — Retención/cifrado extendido a audio de mensajería: **extiende SPEC-041** (mismo `audio_store.py`, mismo job de purga/anonimización, mismo acceso auditado) al `audio_ref` de `Message`; una sola política (F5).
- **SPEC-059** — (Opcional) SPA: indicación "transcrito de audio" + reproductor según retención en la ficha de conversación (feature-flag si aplica); sin romper #1–#4 (F6). Puede fusionarse o descartarse.
- **SPEC-060** — Pruebas + seguridad + observabilidad: nota de voz ficticia e2e (cero terceros), reentrega por `wamid` no duplica, límite→auto-respuesta, cross-tenant (falla por RLS), no-regresión de jobs `call` y de WhatsApp texto, egress vacío desde `stt_worker`, cobertura ≥80% (F7).
- **SPEC-061** — Documentación, runbook (descarga de media, límite configurable, retención extendida), **simulador de nota de voz** y deploy on-prem (F8).

> Total preliminar: **9 SPECs (SPEC-053..SPEC-061)** → `next_spec` pasaría a **62** al crearlas (no ahora). Si F6 se descarta o fusiona, serían 8.

---

## 9. Entregables finales del Entregable #5

- `inbound_parser` que reconoce y procesa notas de voz de WhatsApp (deja de descartar `type=="audio"`).
- Función de **descarga de media** en `app/integrations/whatsapp/` (mismo host/módulo ya permitido — **cero egress nuevo**).
- Nota de voz **almacenada cifrada** en `audio_store.py` (SPEC-035) con `audio_ref` en el `Message`.
- Migración de BD **aditiva** que extiende `Message` (tipo `audio` + `audio_ref` opcional), **sin** crear `call`/`call_transcript`.
- `stt_worker` **extendido con sink parametrizado** que escribe la transcripción en `Message.contenido` reutilizando `stt_engine.py` sin tocar el motor; **jobs `call` de #4 intactos**.
- Transcripción enriquecida (sentimiento + resumen + borrador RAG ≥3 citas) por el pipeline IA **100% local**, con **respuesta en texto** y **human-in-the-loop**.
- **Límite de duración (10 min)** con **descarte amable + auto-respuesta**.
- Política de **retención/cifrado extendida** (SPEC-041) al audio de mensajería — **un solo régimen**.
- **Idempotencia por `wamid`** confirmada (sin `call_id` nuevo).
- `check-externos-backend.sh` **verde** (cero STT/inferencia a terceros; descarga solo a `graph.facebook.com` desde el módulo WhatsApp).
- (Opcional) SPA con indicación "transcrito de audio" + reproductor según retención.
- **Simulador de nota de voz** verificable en local; runbook actualizado con placeholders, sin secretos.
- **Evidencia auditable:** cero audio/inferencia a terceros, egress público sin cambios (solo `graph.facebook.com`), aislamiento cross-tenant, cifrado en reposo, no-regresión de #1–#4.
- **ADR-013** (aplazamiento explícito de TTS de respuesta + confirmación de que la nota de voz se modela como `Message`, no como `call`) aceptado.

## 10. Definition of Done (Entregable #5)

1. CE-61..CE-65 cumplidos y evidenciados.
2. Nota de voz ficticia por WhatsApp: descargada, transcrita **100% local** (`faster-whisper`), persistida como `Message.contenido`; **cero** STT de terceros.
3. **Cero audio/inferencia a terceros:** captura de red y `check-externos-backend.sh` verde; STT/IA sin ruta a internet (prueba de egress vacío); descarga **solo** a `graph.facebook.com` desde el módulo WhatsApp (sin egress nuevo).
4. **Audio de mensajería cifrado en reposo**; política de **retención/anonimización SPEC-041 extendida** aplicada; **acceso auditado** (HABEAS DATA/PHI).
5. **Idempotencia por `wamid`** probada (reentrega no re-descarga/re-transcribe/duplica); **sin `call_id`**.
6. **Límite de duración (10 min)** probado: nota excedida → **auto-respuesta clara**, no error silencioso, no se encola STT.
7. **No-regresión probada:** jobs `call` del Entregable #4 siguen escribiendo `call_transcript` (sink `call` intacto); WhatsApp de **texto** (#3) sigue igual; suites #1–#4 verdes.
8. Enriquecimiento **100% local** (sentimiento + resumen + borrador RAG ≥3 citas); **respuesta solo en TEXTO**; **human-in-the-loop** intacto (nada se envía autónomamente).
9. **Aislamiento multi-tenant** probado con rol app no-superusuario (ADR-008): test cross-tenant que **falla** por RLS sobre `Message`/`audio_ref`.
10. Cobertura del código nuevo **≥80%**; `docker compose up` reproducible sin internet de inferencia.
11. Secretos fuera del código/logs (C3); borrado lógico (C2); TLS activo en el webhook.
12. Runbook + simulador de nota de voz entregados; **ADR-013** aceptado; deploy on-prem con **aprobación del Lead** (cambio sensible → notificación Telegram, C6).
13. **Aprobación explícita del Lead**. Ninguna SPEC se cierra sin cumplir los CHECKPOINTS aplicables (C2/C3/C4/C6/C8).

---

## 11. ADRs recomendados

> **No se requiere un ADR de egress nuevo** (a diferencia de ADR-010 en PLAN-004): la descarga de media usa el host `graph.facebook.com` y el módulo WhatsApp **ya autorizados** por ADR-006/SPEC-024. Se **hereda** ADR-005 (aislamiento IA), ADR-006 (transporte WhatsApp), ADR-007 (idempotencia `wamid`), ADR-009 (STT local + cifrado/retención del audio como PHI).

- **ADR-013 — La nota de voz de WhatsApp se modela como extensión de `Message` (no como `call`) y la respuesta es solo texto (TTS de salida aplazado).**
  Decide: (a) la nota de voz es un `Message` real dentro de la `Conversation` de WhatsApp con `tipo="audio"` + `audio_ref` opcional; **NO** se crea `call`/`call_transcript` (esas modelan una sesión telefónica, concepto distinto); (b) el `stt_worker` se **extiende con un sink parametrizado por `destino`** (`call` existente / `message` nuevo) reutilizando `stt_engine.py` sin tocar el motor, en vez de crear un worker paralelo; (c) la idempotencia usa el **`wamid` existente** (ADR-007), sin `call_id` nuevo; (d) la respuesta en este slice es **solo texto** por el borrador human-in-the-loop; **TTS de respuesta se aplaza** por la pregunta de diseño no resuelta de "cómo aprueba un humano un audio antes de enviarlo" (posible Entregable #6). Alternativas descartadas: modelar como `call` (concepto equivocado, duplica dominio); worker STT paralelo (duplica carga del modelo y aislamiento); TTS ya en este slice (introduce ambigüedad de aprobación no necesaria para el valor central).

---

## 12. PREGUNTAS ABIERTAS AL LEAD — con supuesto por defecto

**Ya respondidas por el Lead (de XAVIER §5):**
- **P1 (límite de duración):** **RESUELTA → 10 minutos**, configurable por env. Adoptado en §2.8, F2, R-66, CE-64.
- **P2 (respuesta en audio/TTS):** **RESUELTA → solo texto** en este slice; TTS de respuesta aplazado a fase futura. Adoptado en §2 OUT, ADR-013.

**Nuevas preguntas detectadas por DOCTOR STRANGE (con supuesto por defecto):**

1. **P3 (indicación visual en la SPA — F6/SPEC-059):** ¿quieres que la ficha de conversación **muestre explícitamente** que un mensaje fue transcrito de audio (badge "transcrito de audio" y/o reproductor del clip según retención), o basta con que la transcripción aparezca como texto normal en la bandeja?
   **Supuesto por defecto:** añadir un **badge discreto "transcrito de audio"** (bajo esfuerzo, mejora la trazabilidad para el agente) y **posponer el reproductor** a menos que la política de retención garantice la disponibilidad del clip. Si el Lead prefiere mínimo esfuerzo, **F6 se descarta** (la transcripción se ve como texto normal) y quedan 8 SPECs.

2. **P4 (retención del audio de la nota de voz vs. su transcripción):** ¿el `audio_ref` de la nota de voz debe purgarse con el **mismo plazo** que el audio de llamadas de #4 (por defecto 30 días, SPEC-041), o la mensajería tiene un plazo distinto?
   **Supuesto por defecto:** **mismo plazo que SPEC-041** (30 días de audio → purga/anonimización; transcripción retenida como el resto del `Message`), un solo régimen configurable. Ajustable por env si el Lead pide un plazo específico para mensajería.

3. **P5 (formato/transcodificación del media de WhatsApp):** las notas de voz de WhatsApp llegan en **OGG/Opus**; ¿`stt_engine.py`/`faster-whisper` ya ingiere OGG/Opus directamente, o hace falta un paso de decodificación (p. ej. ffmpeg, ya presente en muchas imágenes de STT)?
   **Supuesto por defecto:** el motor decodifica OGG/Opus vía ffmpeg (dependencia ya habitual del stack STT); si no, la SPEC-054/056 añade un **paso de transcodificación local** (sin egress) antes de encolar/transcribir. Se verifica al leer el motor real en la fase de SPEC.

---

> **Siguiente paso:** IRON MAN presenta este PLAN-006 al Lead. El Lead debe responder **"APROBADO PLAN-006"** (o "Ajusta PLAN-006: …") antes de que DOCTOR STRANGE genere las SPEC-053..SPEC-061 y el ADR-013. Cumple CHECKPOINT C8 (prompt registrado en `prompt-lab/PROMPT-OPTIMIZADO-FASE5-NOTAS-VOZ-WHATSAPP.md`).
