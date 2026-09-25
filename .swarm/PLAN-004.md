# PLAN-004 — Fase 4 "OmniCore AI" (Entregable #4): transcripción + análisis ASÍNCRONO de llamadas con STT LOCAL (NO VoiceBot en vivo)

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Fecha: 2026-09-19 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo` presente) — PROHIBIDO cualquier modelo/servicio EXTERNO de inferencia o de procesamiento de datos personales por un tercero.
> **DATO ESPECIAL DE ESTA FASE:** el **AUDIO de llamadas es dato personal (posible PHI)**. El **STT (y cualquier TTS futuro) es 100% LOCAL**: el audio **NUNCA** sale a terceros (Google STT, AWS Transcribe, OpenAI Whisper API, Deepgram, AssemblyAI y equivalentes **PROHIBIDOS**). El worker STT corre **SIN egress** (en `ia_internal`, como los workers de IA). Ver §3 y ADR-009.
> **EXCEPCIÓN ACOTADA (solo si el PBX es externo):** descargar la grabación desde un PBX externo es **TRANSPORTE acotado** (análogo a ADR-006): SOLO por `api`/un worker dedicado de descarga, con **allowlist del host del PBX**, **NUNCA** desde el worker STT/IA. Ver §3.3 y ADR-010.
> Origen: `prompt-lab/PROMPT-OPTIMIZADO-FASE4.md` (🧠 XAVIER) · Estado: **PROPUESTA** (espera "APROBADO PLAN-004")
> Regla de oro: este PLAN **NO genera SPECs**. Las SPECs se crean SOLO tras la aprobación explícita del Lead ("APROBADO PLAN-004").
> Precedentes: Entregable #1 (maqueta SPA, incl. SPEC-006 VoiceBot visual) **COMPLETADO**; Entregable #2 (backend + IA local, PLAN-002 / SPEC-011..023) y Entregable #3 (canal WhatsApp, PLAN-003 / SPEC-024..034) **EN_VERIFICACION**.
> Contadores vigentes (`.swarm/specs.json`): `next_plan: 4`, `next_spec: 35`, `next_adr: 9`.

---

## 1. Objetivo y contexto

### Objetivo

Construir el **Entregable #4** como **un vertical slice end-to-end de máximo valor / mínimo riesgo**:
**ingerir grabaciones de llamadas telefónicas** (fichero entregado por el PBX vía webhook/spool),
**transcribirlas con STT 100% LOCAL** (`faster-whisper` `large-v3` es-CO, fallback CPU/`medium`),
**persistir** la transcripción bajo **multi-tenant RLS efectiva** (ADR-008), y **enriquecerla
REUTILIZANDO el pipeline IA local existente** (sentimiento SPEC-018 + resumen + borrador RAG con **≥3
citas trazables** SPEC-017, **human-in-the-loop** SPEC-019), entregando al agente una **ficha de llamada**
trazable en la SPA — **sin enviar el audio ni la inferencia a ningún tercero**. Procesamiento **ASÍNCRONO**
(Redis + worker), **idempotente por `call_id`**. El módulo VoiceBot de la maqueta (SPEC-006) pasa de mock a
**datos reales** por **feature-flag**.

El **VoiceBot conversacional en vivo** (STT streaming + TTS + IVR + barge-in) **queda fuera** de esta fase
(→ Entregable #5): suma latencia dura (<700 ms round-trip), GPU en línea crítica y contradice el
human-in-the-loop; el análisis asíncrono entrega ~80% del valor (trazabilidad 100%, QA, sentimiento,
resúmenes) con una fracción del riesgo, reutilizando el pipeline ya construido.

### Contexto y relación con Entregables #2/#3 (qué se reutiliza)

- **Dominio agnóstico de canal.** `conversations.canal` es `String(50)` (no enum) → añadir `voz`/`telefonia`
  NO requiere rediseñar el dominio; la transcripción se enchufa al mismo bus que un mensaje de texto.
- **Patrón cola Redis + worker** (`rag_ingest_worker`, `sentiment_worker`, `wa_inbound_worker`): se replica
  para un **`stt_worker`** (transcripción batch) y, si el PBX es externo, un **`recording_fetch_worker`**
  (descarga acotada del audio).
- **Pipeline IA local REUTILIZADO tal cual** sobre la transcripción: sentimiento (SPEC-018) → resumen +
  borrador RAG con ≥3 citas (SPEC-017) → human-in-the-loop atómico (SPEC-019).
- **RLS FORCE por `tenant_id`** (ADR-004) **efectiva** con rol app no-superusuario + `SECURITY DEFINER`
  (ADR-008); **auth JWT** (SPEC-013); **borrado lógico** (C2); **secretos en env fail-fast** `${VAR:?}` (C3);
  **observabilidad** (`/metrics`, structlog, Locust); **CI** (`check-externos-backend.sh`).
- **Idempotencia** (patrón `wamid` de ADR-007) aplicada por **`call_id`**.
- **Egress acotado como TRANSPORTE** (ADR-006): mismo patrón allowlist-por-ruta si el PBX es externo.
- **SPA con feature-flag** (patrón `VITE_USE_REAL_API`, SPEC-020/031): el módulo VoiceBot visual (SPEC-006)
  pasa de mock a **datos reales**; flag OFF = maqueta intacta.
- **Retención/datos personales** (SPEC-021, HABEAS DATA/GDPR-like): esta fase la **extiende** al audio.

**Novedad estructural de esta fase (única y acotada):** aparece **audio como dato personal (posible PHI)**
que exige (a) **STT local sin egress**, (b) **audio en reposo cifrado**, (c) **retención/anonimización** y
**acceso auditado**, y (d) —solo si el PBX es externo— un **egress de transporte acotado** para descargar la
grabación, aislado del STT/IA. Ver §3.

---

## 2. Alcance IN / OUT

### IN — entra en el vertical slice #4

1. **Ingesta de grabación (conector mínimo de transporte):** webhook o watcher de spool que recibe el
   fichero de audio (WAV/OGG) + metadatos (número, dirección, duración, `call_id`, `tenant`), con
   **idempotencia por `call_id`** (patrón `wamid`, ADR-007). Si el PBX solo notifica una URL, la descarga la
   hace un **worker de descarga dedicado** con egress acotado al host del PBX (ADR-010), **nunca** el STT/IA.
2. **Almacenamiento de audio on-prem, cifrado en reposo:** volumen local o almacén de objetos on-prem
   (p. ej. MinIO). El audio **nunca** va a un tercero (RNF-41/47; enlaza SPEC-021).
3. **STT local batch:** **`stt_worker`** que transcribe con `faster-whisper` es-CO (`large-v3`, fallback
   `medium`/`whisper.cpp` en CPU), con **segmentos + timestamps** y **diarización básica opcional**
   (agente/cliente por VAD). Cola Redis + worker (patrón `rag_ingest_worker`/`sentiment_worker`). **Sin egress.**
4. **Persistencia multi-tenant:** entidades `call` / `call_transcript` (segmentos con timestamps) con
   `tenant_id`, **RLS FORCE efectiva** (ADR-004/008), **borrado lógico** (C2), enlace a la
   conversación/contacto existente (`conversations.canal = "voz"/"telefonia"`).
5. **Enriquecimiento IA local (REUTILIZA):** sentimiento (SPEC-018) sobre la transcripción + **resumen** y
   **borrador de seguimiento RAG con ≥3 citas trazables** (SPEC-017), **human-in-the-loop** (SPEC-019),
   **sin inferencia externa**.
6. **Ficha de llamada en la SPA:** reutiliza el módulo VoiceBot visual (SPEC-006) mostrando transcripción
   real, sentimiento, resumen y borrador; tras **feature-flag** (patrón `VITE_USE_REAL_API`, SPEC-020/031).
7. **Retención/anonimización de grabaciones:** política configurable de retención y purga/anonimización del
   audio y/o transcripción (**enlaza y extiende SPEC-021**); **acceso auditado** (HABEAS DATA).
8. **Auditoría de egress:** `check-externos-backend.sh` extendido — STT/TTS/IA **sin egress**; si el PBX es
   externo, allowlist **por ruta** al único host del PBX en el módulo del conector de descarga (patrón ADR-006).
9. **Observabilidad:** métricas de **RTF** del STT, tamaño/latencia de cola batch, tasa de error de
   transcripción, contadores por tenant; logs estructurados con `tenant_id`/`call_id`/`trace_id`; evidencia
   "cero audio/inferencia a terceros".

### OUT — NO entra en este slice (Entregable #5+)

- **VoiceBot conversacional en vivo:** STT streaming, diálogo, IVR, barge-in, gestión de turnos.
- **Síntesis de voz (TTS)** de cualquier tipo (Piper/Coqui): reservada para el Entregable #5.
- **Despliegue completo de PBX** (dial-plan, colas ACD, troncales SIP): fuera; solo el conector de grabaciones.
- **Auto-respuesta autónoma por voz** sin aprobación humana (contradice el human-in-the-loop entregado).
- **Traducción/multi-idioma** más allá de es-CO; **identificación biométrica** de locutor.
- **Analítica avanzada de voz** (emociones acústicas, tono), scoring automatizado de agentes, HA/K8s.
- **Transcripción de audios de WhatsApp** (multimedia) más allá del alcance del conector de llamadas (si se
  requiere, reutiliza este pipeline en una fase posterior).

---

## 3. Arquitectura de referencia

### 3.1 Flujo end-to-end

```
ingesta:    PBX --webhook/spool (fichero WAV/OGG + call_id, número, dirección, duración, tenant)-->
            [api/watcher] --ACK rápido--> dedup por call_id
            (si PBX externo y solo llega URL) --> [recording_fetch_worker] --httpx allowlist host PBX--> descarga
            --> almacena audio CIFRADO on-prem (volumen/MinIO) --> encola trabajo STT
            --> [Redis cola stt:jobs] --> [stt_worker: faster-whisper es-CO, batch, SIN egress]
            --> persiste call/call_transcript (segmentos+timestamps, diarización opcional) [RLS por tenant]
            --> encola sentimiento (SPEC-018) + resumen + borrador RAG ≥3 citas (SPEC-017) [TODO on-prem]

human-in-the-loop:  [Ficha de llamada SPA] <-- transcripción+sentimiento+resumen+borrador citado --
                    agente revisa/edita/APRUEBA (SPEC-019, atómico) antes de cualquier envío

retención:  política configurable --> purga/anonimización de audio y/o transcripción; acceso auditado (SPEC-021)
```

### 3.2 Componentes y DÓNDE está el límite de egress (diagrama ASCII)

```
                                   HOST ON-PREM (Docker Compose)
  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
  │                                                                                                │
  │   red `app` (bridge, CON egress restringido por allowlist SOLO al host del PBX si es externo)  │
  │   ┌──────────────────────────────────────────────────────────────────────────────────┐        │
  │   │  [reverse proxy TLS]──►[api FastAPI]──►[Redis colas+pubsub]──►[PostgreSQL/RLS]      │        │
  │   │       (webhook/spool)        │  ▲                 │                                  │        │
  │   │                              │  │                 ▼                                  │        │
  │   │                              │  └──[recording_fetch_worker]──httpx allowlist───────┐ │        │
  │   └──────────────────────────────┼──────────────────────────────────────────────────┼─┘        │
  │                                  │  ═════════ LÍMITE DE EGRESS (solo si PBX externo) ═│          │
  │                                  │  Solo `api`/`recording_fetch_worker` salen, y SOLO  ▼          │
  │                                  │  al host del PBX (allowlist auditada, ADR-010)  ►► PBX externo │
  │                                  │                                                                │
  │   [almacén de audio CIFRADO on-prem: volumen local / MinIO]  (nunca a un tercero)               │
  │                                  │                                                                │
  │   red `ia_internal` (bridge, internal: true — ⛔ SIN egress, NUNCA internet)                      │
  │   ┌──────────────────────────────▼─────────────────────────────────────────────────┐           │
  │   │  [stt_worker = faster-whisper es-CO]  ⛔ jamás alcanza el PBX ni internet          │           │
  │   │  [ia = Ollama] LLM local (Qwen2.5-7B) + embeddings (nomic-embed)                  │           │
  │   │  [rag_worker] [sentiment_worker]  ⛔ jamás alcanzan internet                       │           │
  │   └──────────────────────────────────────────────────────────────────────────────┘           │
  └─────────────────────────────────────────────────────────────────────────────────────────────┘
   ⛔ = internal:true, sin ruta a internet   ►► = ÚNICO egress permitido (transporte de descarga, no inferencia, no audio-a-terceros)
```

**Regla de oro de la topología (invariante de seguridad de esta fase):**

- El **`stt_worker`** (y toda la IA) vive **SOLO** en `ia_internal` (`internal: true`): **NUNCA** se le añade
  la red `app` ni ruta a internet. **PROHIBIDO** que el STT/IA descargue del PBX o alcance cualquier host
  público. El audio se le entrega desde el **almacén cifrado on-prem** (volumen/MinIO), nunca por red externa.
- El **worker de descarga** (`recording_fetch_worker`) —**solo necesario si el PBX es externo**— vive en `app`
  (que tiene egress) y su salida se **restringe por allowlist al único host del PBX**. Si el PBX es **on-prem**
  (Asterisk/FreeSWITCH), **no hay egress nuevo** (topología preferida desde SENSIBLE).
- El **límite de egress** es exactamente ese borde: lo único que sale es la **petición de descarga de la
  grabación al PBX** (transporte del canal). El **audio y la inferencia jamás salen** del host.

### 3.3 Aislamiento del STT/IA (cómo queda garantizado sin egress)

- Se **conserva** ADR-005/ADR-006 sin debilitarlos: `ia_internal internal: true`, firewall host DROP saliente
  para el contenedor STT/IA, DNS interno/vacío, **pesos de Whisper montados por volumen** (sin `pull`/descarga
  de modelos en runtime).
- El **`stt_worker` se añade a `ia_internal`** (no a `app`): comparte el aislamiento de la IA. Recibe el audio
  desde el **almacén on-prem** (volumen compartido / MinIO en red interna), **no** desde internet.
- Si el PBX es **externo**, el egress lo tiene **solo** `api`/`recording_fetch_worker` en `app`, y **solo** al
  host del PBX (allowlist). Se **endurece** igual que en ADR-006: los workers STT/IA quedan fuera de `app` y/o
  firewall host DROP para ellos, verificado con **prueba de egress vacío**.
- **Evidencia:** captura de red durante un e2e muestra salida pública **solo** desde `api`/`recording_fetch_worker`
  y **solo** al host del PBX (si externo); el intento de egress desde `stt_worker`/`ia`/workers de IA **falla**
  (timeout/deny). Si el PBX es on-prem, **cero** egress público.

### 3.4 Auditoría "cero audio/inferencia a terceros + descarga acotada" (evolución de `check-externos-backend.sh`)

1. **Se mantiene** la lista `FORBIDDEN_URLS`/`FORBIDDEN_SDKS` de APIs de **inferencia** (OpenAI, Anthropic,
   Google, Cohere, Groq, HuggingFace, etc.) y se **añaden explícitamente** las APIs de **STT/TTS de terceros**
   (Google STT, AWS Transcribe, OpenAI Whisper API, Deepgram, AssemblyAI, Azure Speech, etc.): **prohibidas en
   todo el código**.
2. **Nueva allowlist de transporte** (solo si PBX externo): el **host del PBX** se permite **solo** dentro del
   módulo del conector de descarga (p. ej. `app/services/telefonia/` o `app/integrations/pbx/`). Fuera de ese
   módulo → **FALLA** (transporte fuera del conector = fuga). Si el PBX es on-prem, **no** se habilita ninguna
   allowlist pública.
3. **Prohíbe** que el `stt_worker`/módulos de IA importen el cliente httpx de descarga o alcancen el host del
   PBX (el STT no descarga: recibe del almacén on-prem), y que el conector de descarga importe/llame IA/STT.
4. **Prohíbe** cualquier dominio/host en los manifiestos de `ia_internal` y en la config de
   `stt_worker`/`ia`/`rag_worker`/`sentiment_worker`.
5. Mantiene la verificación de `ia_internal: internal: true` y de rutas internas (Ollama, almacén de audio).

> El diseño exacto del matcher (allowlist por ruta al host del PBX) se especifica en SPEC-035/041 y se ancla
> en ADR-010 (si aplica). El invariante duro es: **audio y STT/IA nunca salen; solo la descarga sale, y solo
> al PBX.**

### 3.5 Exposición HTTPS entrante (webhook/spool)

- Si la ingesta es por **webhook**, se expone **solo** el path del webhook de grabaciones tras el **reverse
  proxy TLS**, nunca el STT/IA ni la BD. Si es por **spool** (carpeta compartida), un **watcher** local lee el
  directorio sin exponer puerto. `verify_token`/firma (si el PBX lo soporta) y certificado como config/secreto (C3).

---

## 4. Fases y entregables

| Fase   | Nombre                                            | Entregables clave                                                                                                                                                                                                    |
| ------ | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **F0** | Infra STT local + almacén cifrado + auditoría + ADRs | `docker-compose` con `stt_worker` en `ia_internal` (sin egress) y, si PBX externo, `recording_fetch_worker` en `app` con allowlist al host del PBX; almacén de audio cifrado (volumen/MinIO); pesos Whisper por volumen; `check-externos-backend.sh` extendido (STT/TTS prohibidos, allowlist host PBX por ruta); `.env.example` con vars (placeholders); ADR-009/010; reverse proxy TLS del webhook. |
| **F1** | Datos de voz: `call`/`call_transcript` + RLS + idempotencia | Migración Alembic versionada aditiva: `call` (metadatos, `call_id`, `tenant_id`, estado, enlace conversación) y `call_transcript` (segmentos + timestamps + hablante) con **RLS FORCE efectiva** (ADR-008), unicidad por `call_id`, borrado lógico (C2); seed ficticio. |
| **F2** | Conector de ingesta de grabaciones (transporte)   | Webhook o watcher de spool: recepción del fichero + metadatos, **idempotencia por `call_id`**, almacenamiento cifrado on-prem, encolado del trabajo STT; (si PBX externo) `recording_fetch_worker` con descarga acotada; sin mapeo de tenant → descarte auditado.                          |
| **F3** | Worker STT `faster-whisper` es-CO + diarización    | `stt_worker` batch: transcribe es-CO con `large-v3` (fallback CPU/`medium`), produce segmentos+timestamps, **diarización básica opcional** (VAD agente/cliente), persiste `call_transcript`; RTF instrumentado; reintentos idempotentes; **sin egress**.                                     |
| **F4** | Enriquecimiento IA local (reutiliza)              | Disparo del pipeline sobre la transcripción: sentimiento (SPEC-018) + **resumen** + borrador RAG con **≥3 citas** (SPEC-017), **human-in-the-loop** (SPEC-019); sin inferencia externa.                                                                                                     |
| **F5** | Integración SPA: ficha de llamada (feature-flag)  | El módulo VoiceBot visual (SPEC-006) pasa de mock a datos reales tras el flag: transcripción real, sentimiento, resumen, borrador citado, reproductor de audio (según retención); contratos `types.ts` respetados; sin romper Entregables #1/#2/#3 (flag OFF intacto).                        |
| **F6** | Retención/anonimización de audio + seguridad      | Política configurable de retención (por defecto audio 30 días) + purga/anonimización de audio y/o transcripción; **acceso auditado** (HABEAS DATA/PHI); cifrado en reposo verificado; barrido BLACK WIDOW; extiende SPEC-021. |
| **F7** | Pruebas + carga (RTF/THOR) + observabilidad       | Set de audios ficticios es-CO; test STT e2e (segmentos+timestamps, cero terceros); cross-tenant (falla por RLS); idempotencia por `call_id`; **RTF ≤ 1.0 en GPU** bajo carga (THOR) o degradación CPU documentada; WER documentado; métricas de cola/error por tenant. |
| **F8** | Docs + runbook + deploy on-prem                   | Runbook (integración PBX/spool, modelos Whisper, política de retención, rotación de secretos) con placeholders; OpenAPI del webhook; **simulador de grabaciones** verificable en local; deploy on-prem (QUICKSILVER, con aprobación del Lead). |

---

## 5. Dependencias entre fases y ruta crítica

- **F0** habilita todo (STT local + almacén cifrado + auditoría + ADRs). Ninguna fase de voz arranca sin F0.
- **F1** depende de F0 y es prerequisito duro de F2–F4 (sin `call`/`call_transcript` ni `call_id` no hay
  ingesta ni idempotencia ni persistencia de transcripción).
- **F2** depende de F1 (necesita `call_id`, tenant y almacenamiento) y es la puerta de ingesta.
- **F3** depende de F2 (audio almacenado + trabajo encolado); produce la transcripción. Es el núcleo técnico.
- **F4** depende de F3 (transcripción persistida) y reutiliza SPEC-017/018/019; habilita el human-in-the-loop.
- **F5** depende de F3 y F4 (necesita transcripción real + enriquecimiento) y reutiliza SPEC-020/006.
- **F6** transversal: se diseña desde F0/F1 (cifrado, retención) y se **cierra** auditando el conjunto.
- **F7** depende de que F2–F5 estén completas (prueba el slice completo, incluida carga RTF del STT — THOR).
- **F8** cierra: runbook/docs/simulador/deploy tras F6/F7.

**Ruta crítica:** `F0 → F1 → F2 → F3 → F4 → F5 → F7 → F8`
(F6 transversal y consolidada al final; F5 puede solaparse con el final de F4 una vez fijado el contrato de la
ficha). La **ruta crítica dura** es **F3 (STT)**: RTF/GPU y precisión es-CO son el mayor riesgo técnico.

---

## 6. Riesgos y mitigaciones

| #        | Riesgo                                                                                                       | Impacto                        | Mitigación                                                                                                                                                                                                             |
| -------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R-41** | **Audio o inferencia enviados a un tercero** (STT/TTS de terceros, o egress del PBX que abra ruta al STT/IA → rompe SENSIBLE, expone PHI). | **Crítico** (rompe política, PHI) | **Invariante de topología** (§3.2): STT/IA solo en `ia_internal internal:true`; el egress (si lo hay) lo tiene SOLO `api`/`recording_fetch_worker` en `app`, y SOLO al host del PBX. STT/TTS de terceros PROHIBIDOS en CI (§3.4). Firewall host DROP para STT/IA. Prueba de egress vacío + captura de red. ADR-009/010. |
| **R-42** | **RTF/latencia del STT y presión de GPU** (transcribir supera la duración real; VRAM insuficiente para `large-v3`). | Alto (SLA batch, coste)        | Batch tolerante a cola; **RTF ≤ 1.0 objetivo en GPU** con `large-v3`; **fallback CPU/`medium`** con RTF degradado documentado; modelo parametrizable por env; N `stt_worker` escalables; medición bajo carga (THOR); VAD para saltar silencios. |
| **R-43** | **Cifrado/almacenamiento de audio** (audio en claro en disco/objeto, o fuga por permisos).                   | Alto (PHI/HABEAS DATA)         | **Cifrado en reposo** (volumen cifrado / cifrado de objeto MinIO / cifrado de campo si aplica PHI); permisos mínimos; almacén sin exposición pública; secretos de cifrado en env (C3); barrido BLACK WIDOW. Enlaza SPEC-021.                     |
| **R-44** | **Retención/PHI** (audio/transcripción retenidos más de lo permitido; acceso no auditado).                    | Alto (cumplimiento legal)      | Política de retención **configurable** (por defecto audio 30 días → purga/anonimización); **registro de acceso** a audio/transcripción (HABEAS DATA); si el Lead confirma PHI → retención estricta + cifrado de campo + acceso reforzado (ADR-009 endurecido). |
| **R-45** | **Egress del PBX** (si externo: allowlist mal acotada o el STT/IA obtiene ruta al PBX).                       | Crítico (política)             | Allowlist **por ruta** al único host del PBX en el módulo del conector de descarga (ADR-010, patrón ADR-006); STT/IA jamás importan ese cliente; **preferible PBX on-prem (sin egress nuevo)**; test negativo (descarga fuera del conector) **falla** la build. |
| **R-46** | **Idempotencia insuficiente por `call_id`** (reentrega del PBX → llamada/transcripción/borrador duplicados). | Alto (datos/UX)                | Dedup por **`call_id`** con restricción única en BD + guarda en el worker; procesamiento idempotente; test de reentrega que **no** crea doble llamada/transcripción. ADR-007 (patrón `wamid`).                          |
| **R-47** | **Fuga cross-tenant** (llamada/transcripción asignada al tenant equivocado o visible a otro).                | Alto (privacidad, PHI)         | `call`/`call_transcript` con `tenant_id` + **RLS FORCE efectiva** (ADR-004/008, rol app no-superusuario); resolución de tenant desde metadatos + descarte auditado sin mapeo; **test cross-tenant que FALLA por RLS** (HAWKEYE). |
| **R-48** | **Precisión es-CO baja** (WER alto degrada sentimiento/resumen/borrador).                                     | Medio (calidad)                | `large-v3` es-CO como base; WER **documentado** sobre set ficticio es-CO; diarización básica para separar turnos; el human-in-the-loop **absorbe** errores (el agente revisa/edita antes de enviar).                    |
| **R-49** | **Regresión en Entregables #1/#2/#3** al añadir el canal de voz.                                              | Medio                          | Feature-flag reversible; dominio agnóstico de canal (`conversations.canal` string); migraciones **aditivas** no destructivas; suites #1/#2/#3 verdes.                                                                    |

**Top-3:** **R-41 (audio/inferencia a terceros — PROHIBIDO, y fuga de egress al STT/IA)**, **R-42 (RTF/latencia
STT y GPU)**, **R-43/R-44 (cifrado y retención/PHI del audio)**. R-46 (idempotencia por `call_id`) y R-47
(aislamiento cross-tenant) inmediatamente detrás.

---

## 7. Criterios de éxito verificables (mapeo con CE-41..CE-45 de XAVIER)

| ID        | Criterio                                                                                                                                             | Cómo se verifica                                                                                                                                            | Fase        |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| **CE-41** | **STT local end-to-end:** una grabación es-CO ficticia se transcribe con `faster-whisper` local, con segmentos+timestamps; **cero** llamadas a STT de terceros; WER documentado. | Test e2e con audio ficticio + captura de red (cero salida a STT/IA de terceros) + `check-externos-backend.sh` verde; WER sobre set de prueba.               | F3/F7       |
| **CE-42** | **Enriquecimiento reutilizado sin inferencia externa:** la transcripción recibe sentimiento + resumen + borrador RAG con **≥3 citas trazables**; egress público nulo desde STT/IA. | e2e; `check-externos-backend.sh` verde; prueba de egress vacío desde `stt_worker`/`ia`/workers de IA.                                                        | F4/F6       |
| **CE-43** | **Aislamiento multi-tenant + idempotencia:** test cross-tenant sobre `call`/`call_transcript` que **falla por RLS**; ingesta sin mapeo → descarte auditado; reentrega por `call_id` no duplica. | Test cross-tenant (HAWKEYE) con rol app no-superusuario (ADR-008); test de reentrega idempotente por `call_id`.                                             | F1/F2/F7    |
| **CE-44** | **Privacidad y retención del audio:** audio **cifrado en reposo**; política de retención purga/anonimiza según configuración; acceso a audio/transcripción **registrado** (HABEAS DATA/PHI). | Inspección de cifrado en reposo; test de purga/anonimización por política; auditoría de accesos; barrido BLACK WIDOW (secretos/PHI). Enlaza SPEC-021.        | F6          |
| **CE-45** | **Latencia batch y no-regresión:** **RTF del STT ≤ 1.0 en GPU** (o degradación CPU documentada) bajo carga; human-in-the-loop intacto; SPA con ficha de llamada tras feature-flag **sin romper** #1/#2/#3; cobertura backend **≥ 80%**; `docker compose up` reproducible sin internet de inferencia. | Medición RTF bajo carga (THOR); suites #1/#2/#3 verdes; cobertura; `docker compose up` reproducible; borrador RAG mantiene p95 ≤ 6 s (GPU).                   | F5/F7       |

> Transversales heredados: **aprobación explícita del Lead**; CHECKPOINTS C2 (borrado lógico) / C3 (secretos) /
> C4 (criterios verificables) / C6 (cambio sensible → notificación Telegram) / C8 (prompt registrado).

---

## 8. Mapa preliminar de SPECs propuestas (SOLO el mapa — NO son las specs)

> Continúa la numeración desde `specs.json` (`next_spec: 35`). Se crearán únicamente tras "APROBADO PLAN-004".
> Cada SPEC llevará criterios verificables (C4).

- **SPEC-035** — Infra STT local + almacén de audio cifrado + auditoría de egress: `stt_worker` en `ia_internal` sin egress, almacén cifrado (volumen/MinIO), pesos Whisper por volumen, `check-externos-backend.sh` extendido (STT/TTS de terceros prohibidos; allowlist host PBX por ruta si externo), `.env.example` (F0).
- **SPEC-036** — Datos de voz: entidades `call` / `call_transcript` (segmentos+timestamps+hablante) con RLS FORCE efectiva (ADR-008), unicidad e idempotencia por `call_id`, migración Alembic aditiva, borrado lógico (C2) (F1).
- **SPEC-037** — Conector de ingesta de grabaciones (transporte): webhook/watcher de spool, recepción de fichero+metadatos, almacenamiento cifrado, descarte auditado sin mapeo; (si PBX externo) `recording_fetch_worker` con descarga acotada al host del PBX (F2).
- **SPEC-038** — Worker STT `faster-whisper` es-CO + diarización básica: transcripción batch con segmentos+timestamps, fallback CPU/`medium`, diarización opcional (VAD), reintentos idempotentes, instrumentación RTF, sin egress (F3).
- **SPEC-039** — Enriquecimiento IA local sobre la transcripción: reutiliza sentimiento (SPEC-018), resumen + borrador RAG ≥3 citas (SPEC-017) y human-in-the-loop (SPEC-019), sin inferencia externa (F4).
- **SPEC-040** — Integración SPA ficha de llamada (feature-flag): módulo VoiceBot visual (SPEC-006) de mock a datos reales; transcripción, sentimiento, resumen, borrador y reproductor según retención; reutiliza SPEC-020, sin romper #1/#2/#3 (F5).
- **SPEC-041** — Retención/anonimización de audio + seguridad: política configurable, purga/anonimización, cifrado en reposo, acceso auditado (HABEAS DATA/PHI); extiende SPEC-021 (F6).
- **SPEC-042** — Pruebas + carga (RTF/THOR) + observabilidad: set de audios ficticios es-CO, STT e2e (cero terceros), cross-tenant (falla por RLS), idempotencia `call_id`, RTF bajo carga, WER documentado, métricas por tenant (F7).
- **SPEC-043** — Documentación, runbook de voz, **simulador de grabaciones** y deploy on-prem: integración PBX/spool, modelos Whisper, política de retención, rotación de secretos (placeholders), deploy (F8).

> Total preliminar: **9 SPECs (SPEC-035..SPEC-043)** → `next_spec` pasaría a **44** al crearlas (no ahora).

---

## 9. Entregables finales del Entregable #4

- `stt_worker` (`faster-whisper` es-CO) integrado al backend existente, **sin egress**, ejecutable con `docker compose up`.
- Conector de ingesta de grabaciones (webhook/watcher de spool) + (si PBX externo) worker de descarga acotado.
- Almacén de audio **cifrado en reposo** on-prem (volumen/MinIO); nunca a un tercero.
- Migración de BD versionada **aditiva** para `call` / `call_transcript` con RLS efectiva e idempotencia por `call_id`.
- Transcripción enriquecida (sentimiento + resumen + borrador RAG ≥3 citas) por el pipeline IA **100% local**, human-in-the-loop.
- SPA con **ficha de llamada** (módulo VoiceBot SPEC-006 con datos reales) tras feature-flag, sin romper #1/#2/#3.
- Política de **retención/anonimización** + **acceso auditado** del audio/transcripción (extiende SPEC-021).
- `check-externos-backend.sh` evolucionado (STT/TTS de terceros prohibidos; allowlist host PBX por ruta si externo) en verde en CI.
- OpenAPI del webhook + **simulador de grabaciones** verificable en local; runbook de operación de voz con placeholders, sin secretos.
- **Evidencia auditable:** cero audio/inferencia a terceros, egress público nulo (o solo al host del PBX), aislamiento cross-tenant, cifrado en reposo, RTF del STT, WER es-CO.
- **ADR-009** (STT local + aislamiento del worker + retención/anonimización del audio como dato personal/PHI) y, si el PBX es externo, **ADR-010** (egress acotado del PBX, análogo a ADR-006) aceptados.

## 10. Definition of Done (Entregable #4)

1. CE-41..CE-45 cumplidos y evidenciados.
2. STT **100% local** (`faster-whisper` es-CO): grabación ficticia transcrita con segmentos+timestamps; **cero** STT/TTS de terceros; WER documentado.
3. **Cero audio/inferencia a terceros:** captura de red y `check-externos-backend.sh` verde; STT/IA sin ruta a internet (prueba de egress vacío). Si el PBX es externo, egress público **solo** al host del PBX desde `api`/`recording_fetch_worker`.
4. **Audio cifrado en reposo**; política de **retención/anonimización** aplicada; **acceso auditado** (HABEAS DATA/PHI).
5. **Idempotencia por `call_id`** probada (reentrega no crea doble llamada/transcripción/borrador).
6. **Aislamiento multi-tenant** probado con rol app no-superusuario (ADR-008): test cross-tenant que **falla** por RLS; sin mapeo → descarte auditado.
7. Enriquecimiento **100% local** (sentimiento + resumen + borrador RAG ≥3 citas); **human-in-the-loop** intacto (nada se envía autónomamente).
8. **RTF del STT ≤ 1.0 en GPU** (o degradación CPU documentada) bajo carga (THOR).
9. SPA con **ficha de llamada** tras feature-flag **sin romper** #1/#2/#3; cobertura backend **≥ 80%**; `docker compose up` reproducible sin internet de inferencia.
10. Secretos fuera del código/logs (C3); borrado lógico (C2); TLS activo en el webhook.
11. Runbook + OpenAPI + simulador de grabaciones entregados; **ADR-009** (y ADR-010 si PBX externo) aceptados; deploy on-prem con **aprobación del Lead** (cambio sensible → notificación Telegram, C6).
12. **Aprobación explícita del Lead**. Ninguna SPEC se cierra sin cumplir los CHECKPOINTS aplicables (C2/C3/C4/C6/C8).

---

## 11. ADRs recomendados (a abrir desde ADR-009)

- **ADR-009 — STT 100% local + aislamiento del worker STT + retención/anonimización del audio (dato personal/posible PHI).**
  Decide: (a) `faster-whisper` self-hosted (`large-v3` es-CO, fallback `medium`/`whisper.cpp`) — STT/TTS de
  terceros PROHIBIDOS; (b) el `stt_worker` vive en `ia_internal internal:true` (comparte el aislamiento de la
  IA), recibe el audio del almacén cifrado on-prem, **nunca** alcanza internet ni el PBX; (c) el **audio se
  cifra en reposo**, con **política de retención configurable** (por defecto 30 días → purga/anonimización) y
  **acceso auditado** (HABEAS DATA; endurecido si el Lead confirma PHI). Alternativas: STT en la nube
  (descartado: audio a un tercero, rompe SENSIBLE/PHI); STT en la red `app` con egress (descartado: superficie
  innecesaria). Reafirma ADR-005 para el aislamiento.
- **ADR-010 — Egress acotado del PBX externo para descarga de grabaciones (análogo a ADR-006). (SOLO si el PBX
  es externo.)** Decide que descargar la grabación de un PBX externo es **transporte** (no inferencia, no
  audio-a-terceros): permitido **solo** desde `api`/`recording_fetch_worker` en `app`, **solo** al host del
  PBX, con **allowlist por ruta** en `check-externos-backend.sh`; el STT/IA jamás obtiene esa ruta. Si el PBX
  es on-prem, **este ADR no aplica** (sin egress nuevo, topología preferida). Alternativas: dar egress a toda
  `app` (descartado: superficie); STT descargando directo (descartado: rompe el aislamiento).

---

## 12. PREGUNTAS ABIERTAS AL LEAD (5) — con supuesto por defecto

Si el Lead no responde, el PLAN-004 procede con el **supuesto por defecto** indicado (heredadas de XAVIER §7).

1. **Slice del Entregable #4 (⚠️ SUP-41):** ¿confirmas **transcripción + análisis asíncrono** como el slice
   (alto valor, bajo riesgo, máxima reutilización), o exiges **VoiceBot en vivo** desde ya?
   **Supuesto por defecto:** **transcripción asíncrona**; el VoiceBot en vivo (STT streaming + TTS + IVR +
   barge-in) queda como **Entregable #5**.

2. **PBX / proveedor y acceso (⚠️ SUP-43/SUP-48):** ¿el audio llega de un **PBX propio on-prem
   (Asterisk/FreeSWITCH)** con acceso, o de un **proveedor externo (p. ej. Twilio) como transporte**? ¿Entrega
   **grabación (fichero)** o **stream RTP en vivo**?
   **Supuesto por defecto:** PBX que entrega **grabación (fichero) por webhook/spool**; si es externo se aplica
   egress acotado (ADR-010); si aún no hay PBX, se entrega el conector + **simulador de grabaciones** verificable
   en local. **Preferido on-prem** (sin egress nuevo).

3. **GPU/VRAM y modelo/idioma (⚠️ SUP-44/SUP-46):** ¿sigue vigente **GPU ≥16 GB** para `faster-whisper large-v3`
   es-CO, o dimensionamos para **CPU/`medium`**?
   **Supuesto por defecto:** **GPU ≥16 GB** con `large-v3` es-CO (RTF ≤ 1 batch); fallback **CPU `medium`** con
   RTF degradado documentado; modelo parametrizable por env.

4. **Dominio de datos: salud/PHI vs comercial (⚠️ SUP-45):** ¿el vertical es **salud (PHI)** o
   **comercial/HABEAS DATA**? Impacta retención, cifrado de campo y registro de acceso.
   **Supuesto por defecto:** **comercial/HABEAS DATA (Ley 1581) + GDPR-like**; si el Lead confirma **salud/PHI**
   se añaden RNF extra (cifrado de campo, retención estricta, registro de acceso reforzado, **ADR-009 endurecido**).

5. **Volumen y retención (dimensionamiento):** ¿cuántas **llamadas/día**, **duración media** y **política de
   retención** del audio (días) y de la transcripción?
   **Supuesto por defecto:** escala **piloto** (cientos de llamadas/día, ≤ 10 min media); retención de audio
   **configurable, por defecto 30 días** y luego anonimización/purga; transcripción retenida según SPEC-021;
   un host Docker Compose con **N `stt_worker` escalables**.

---

> **Siguiente paso:** IRON MAN presenta este PLAN-004 al Lead. El Lead debe responder **"APROBADO PLAN-004"**
> (o "Ajusta PLAN-004: …") antes de que DOCTOR STRANGE genere las SPEC-035..SPEC-043 y los ADR-009/010.
> Cumple CHECKPOINT C8 (prompt registrado en `prompt-lab/PROMPT-OPTIMIZADO-FASE4.md`).
