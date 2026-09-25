# PROMPT OPTIMIZADO — Fase 4 "OmniCore AI" (Entregable #4): VoiceBot / telefonía VoIP con STT/TTS 100% local

> Autor: 🧠 XAVIER (Professor X) — Estratega de Prompts (Nivel 1) · skill `optimizar-prompt`
> Fecha: 2026-09-19 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo`) — el **audio de llamadas es dato personal** (posible PHI si el vertical es salud).
> Marco aplicado: **C.R.A.F.T.** (Contexto · Rol · Acción · Formato · Tests)
> Precedentes: Entregable #1 (maqueta SPA, incl. SPEC-006 VoiceBot visual) **COMPLETO**; Entregable #2 (backend + IA local, PLAN-002 / SPEC-011..023) y Entregable #3 (canal WhatsApp, PLAN-003 / SPEC-024..034) **EN_VERIFICACION**.
> Contadores vigentes (`.swarm/specs.json`): `next_plan: 4`, `next_spec: 35`, `next_adr: 9`.
> Destino: este prompt alimenta a 🔮 DOCTOR STRANGE para el **PLAN-004** (NO genera specs por sí mismo).

---

## 0. Resumen del encargo (una frase)

Diseñar el **Entregable #4** como **UN vertical slice end-to-end de máximo valor / mínimo riesgo**:
**transcripción y análisis asíncrono de llamadas** (grabación → STT local Whisper → transcripción persistida
multi-tenant → sentimiento + resumen/borrador RAG human-in-the-loop), **reutilizando el pipeline del #2/#3**
y dejando el **VoiceBot conversacional en vivo (STT streaming + TTS + IVR + barge-in) para una fase posterior**.

---

## 1. Ambigüedades detectadas y SUPUESTOS EXPLÍCITOS (⚠️ marcados)

El objetivo bruto ("VoiceBot con STT/TTS local sobre VoIP") mezcla, en realidad, **dos productos** de
riesgo y coste muy distintos. Se resuelven con supuestos explícitos; cada uno tiene una pregunta abierta (§7).

- **⚠️ SUP-41 (alcance del slice):** "VoiceBot" se interpreta como **NO** el bot conversacional en vivo, sino
  el **análisis asíncrono de llamadas grabadas**. Razón: el diálogo en vivo suma latencia dura (<700 ms
  round-trip percibido), dependencia de GPU en línea crítica, barge-in, gestión de turnos y de IVR/PBX en
  tiempo real; el análisis asíncrono entrega el 80% del valor (trazabilidad 100%, QA, sentimiento, resúmenes)
  con una fracción del riesgo, reutilizando el pipeline ya construido.
- **⚠️ SUP-42 (TTS fuera del slice #4):** como el slice recomendado es asíncrono, **TTS (Piper/Coqui) NO entra
  en el Entregable #4** (no hay diálogo hablado que sintetizar). Se deja evaluado/documentado para el
  Entregable #5 (VoiceBot en vivo). Esto reduce superficie sin perder valor.
- **⚠️ SUP-43 (origen del audio):** se asume que el PBX/telefonía **entrega la grabación** de la llamada
  (fichero WAV/OGG por webhook o carpeta de spool), NO un stream RTP en vivo. El PBX es **TRANSPORTE** del
  canal (integración inevitable, análoga a Meta en ADR-006), pero el **audio y la IA se quedan on-prem**.
- **⚠️ SUP-44 (idioma/modelo):** transcripción **es-CO** con `faster-whisper` modelo `large-v3` (o `medium`
  como fallback CPU/GPU pequeña), self-hosted, sin API de terceros.
- **⚠️ SUP-45 (dominio de datos):** se asume dominio **comercial/HABEAS DATA (Ley 1581) + GDPR-like**, NO
  salud/PHI, salvo confirmación del Lead. Si es salud → requisitos extra (cifrado de campo, retención estricta,
  registro de acceso reforzado). Ver §7 P4.
- **⚠️ SUP-46 (batch, no vivo):** latencia objetivo es de **procesamiento por lotes** (minutos), no de línea
  crítica. Se mide `factor de tiempo real` (RTF) del STT, no latencia interactiva.
- **⚠️ SUP-47 (STT/TTS NUNCA a terceros):** invariante duro heredado de la política SENSIBLE. Google STT,
  AWS Transcribe, OpenAI Whisper API, Deepgram, AssemblyAI y equivalentes están **PROHIBIDOS**. Whisper solo
  self-hosted (faster-whisper / whisper.cpp).
- **⚠️ SUP-48 (egress del PBX acotado):** si el PBX es externo (p. ej. Twilio como transporte), el egress se
  trata **exactamente como ADR-006**: allowlist por ruta a un único dominio de transporte, desde un único
  módulo/worker, con la IA sin ruta a internet. Si el PBX es propio on-prem (Asterisk/FreeSWITCH), no hay
  egress nuevo (preferible desde SENSIBLE).

---

## 2. Recomendación de alcance del Entregable #4 (comparativa de opciones)

| Opción | Descripción | Valor | Riesgo | GPU/Latencia | Reutiliza #2/#3 | Veredicto |
| ------ | ----------- | ----- | ------ | ------------ | --------------- | --------- |
| **(a) Transcripción + análisis asíncrono** | Grabación → STT local → transcripción persistida → sentimiento + resumen/borrador RAG human-in-the-loop | **Alto** (trazabilidad 100%, QA, cumplimiento) | **Bajo** (batch, sin latencia dura) | Batch, GPU tolerante a picos | **Máxima** (pipeline #2 tal cual) | ✅ **RECOMENDADA** |
| (b) VoiceBot conversacional en vivo | STT streaming + diálogo + TTS + barge-in + turnos | Muy alto potencial | **Muy alto** | GPU en línea crítica, <700 ms | Media (nuevo bucle en vivo) | ⛔ Diferir a Entregable #5 |
| (c) Integración PBX (captura/grabación) | Asterisk/FreeSWITCH o webhook de grabaciones | Habilitador | Medio (infra telefónica) | N/A | N/A | 🔶 **Sub-alcance mínimo dentro de (a)**: solo lo necesario para obtener la grabación |

**Recomendación justificada:** **Opción (a)** como Entregable #4, incluyendo de (c) **solo** el conector
mínimo para recibir la grabación (webhook de grabaciones o spool), **no** un despliegue completo de PBX.

**Por qué (a) y no (b) — el VoiceBot en vivo se difiere:**
1. **Latencia dura:** el diálogo en vivo exige STT streaming + LLM + TTS por debajo del umbral conversacional;
   cualquier pico de GPU degrada la experiencia y no es recuperable (a diferencia del batch, que reintenta).
2. **Contradice el human-in-the-loop ya entregado:** un bot que habla solo con el cliente elimina la aprobación
   humana que es invariante en #2/#3 (SPEC-019). El slice asíncrono la **preserva** (el agente recibe
   resumen/borrador y decide).
3. **Riesgo de privacidad/PHI en vivo:** el barge-in y el streaming complican la retención/anonimización;
   el batch permite aplicar retención y anonimización **antes** de exponer la transcripción.
4. **Dependencia dura de GPU en línea crítica:** el batch tolera cola/picos; el vivo exige VRAM reservada 24/7.
5. **Reutilización:** (a) enchufa la transcripción al pipeline existente (sentimiento SPEC-018 → RAG ≥3 citas
   SPEC-017 → borrador human-in-the-loop SPEC-019) casi sin reinvención; (b) exige un bucle de diálogo nuevo.

> Regla del enjambre: **un slice a la vez, el más valioso y de menor riesgo primero.** El VoiceBot en vivo se
> convierte en el **Entregable #5** una vez validados STT local, retención de audio y calidad es-CO en batch.

---

## 3. PROMPT PROFESIONAL (para DOCTOR STRANGE → PLAN-004)

### 3.1 Objetivo (Acción — verbo único y medible)

**Construir** un vertical slice end-to-end que **ingiera grabaciones de llamadas telefónicas**, las
**transcriba con STT 100% local (faster-whisper, es-CO)**, **persista** la transcripción bajo multi-tenant
RLS, y la **enriquezca reutilizando el pipeline IA local existente** (sentimiento + resumen/borrador RAG con
≥3 citas, human-in-the-loop), entregando al agente una **ficha de llamada** trazable — **sin enviar audio ni
inferencia a ningún tercero**.

### 3.2 Rol (quién resuelve)

- Arquitectura/PLAN/SPECs → 🔮 DOCTOR STRANGE.
- Backend/workers/STT → 🐆 BLACK PANTHER + 🛡️ CAPTAIN AMERICA.
- Frontend (ficha de llamada, integración SPA) → 😈 DAREDEVIL (reutiliza el módulo VoiceBot visual de SPEC-006).
- Seguridad audio/PHI/egress → 🕷️ BLACK WIDOW. Pruebas/carga (RTF STT) → 🏹 HAWKEYE / ⚡ THOR.

### 3.3 Alcance IN — entra en el Entregable #4

1. **Ingesta de grabación (conector mínimo de transporte):** webhook o watcher de spool que recibe el fichero
   de audio + metadatos (número, dirección, duración, `call_id`, `tenant`), con **idempotencia por `call_id`**
   (patrón `wamid` de ADR-007).
2. **Almacenamiento de audio on-prem:** volumen local o almacén de objetos on-prem (p. ej. MinIO),
   **cifrado en reposo**; nunca a un tercero.
3. **STT local batch:** worker que transcribe con `faster-whisper` es-CO, con **diarización básica** opcional
   (agente/cliente) y timestamps; cola Redis + worker (patrón `rag_ingest_worker`/`sentiment_worker`).
4. **Persistencia multi-tenant:** entidades `call` / `call_transcript` (segmentos con timestamps) con
   `tenant_id`, RLS FORCE (ADR-004/008), borrado lógico (C2), enlace a la conversación/contacto existente.
5. **Enriquecimiento IA local (REUTILIZA):** sentimiento (SPEC-018) sobre la transcripción + **resumen** y
   **borrador de seguimiento RAG con ≥3 citas trazables** (SPEC-017), **human-in-the-loop** (SPEC-019).
6. **Ficha de llamada en la SPA:** reutiliza el módulo VoiceBot visual (SPEC-006) mostrando transcripción real,
   sentimiento, resumen y borrador; tras **feature-flag** (patrón `VITE_USE_REAL_API`, SPEC-020/031).
7. **Retención/anonimización de grabaciones:** política configurable de retención y purga/anonimización del
   audio y/o transcripción (**enlaza con SPEC-021**); registro de acceso (HABEAS DATA).
8. **Auditoría de egress:** `check-externos-backend.sh` extendido — STT/TTS/IA sin egress; si el PBX es externo,
   allowlist por ruta a su único dominio de transporte (patrón ADR-006).
9. **Observabilidad:** métricas de RTF del STT, cola/latencia batch, errores de transcripción, contadores por
   tenant; logs estructurados con `tenant_id`/`call_id`/`trace_id`; evidencia "cero audio/inferencia a terceros".

### 3.4 Alcance OUT — NO entra (Entregable #5+)

- **VoiceBot conversacional en vivo:** STT streaming, TTS (Piper/Coqui), IVR, barge-in, gestión de turnos.
- **Síntesis de voz (TTS)** de cualquier tipo (⚠️ SUP-42).
- **Despliegue completo de PBX** (dial-plan, colas ACD, troncales): fuera; solo el conector de grabaciones.
- **Auto-respuesta autónoma por voz** sin aprobación humana (contradice human-in-the-loop).
- **Traducción/multi-idioma** más allá de es-CO; identificación biométrica de locutor.
- **Analítica avanzada de voz** (emociones acústicas, tono), scoring de agentes automatizado, HA/K8s.

### 3.5 Contexto (para el PLAN)

Reutiliza directamente: dominio agnóstico de canal (`conversations.canal` string → añadir `voz`/`telefonia`);
patrón cola Redis + worker; RLS FORCE (ADR-004) con rol app no-superusuario + SECURITY DEFINER (ADR-008);
sentimiento (SPEC-018), RAG ≥3 citas (SPEC-017), human-in-the-loop (SPEC-019); integración SPA con feature-flag
(SPEC-020/031); topología de egress acotado (ADR-006); SPEC-021 (retención/datos personales). El módulo VoiceBot
de la maqueta (SPEC-006) pasa de mock a **datos reales**.

### 3.6 Requisitos funcionales (RF)

- RF-41 Ingesta idempotente de grabación por `call_id` (reentrega no duplica llamada/transcripción).
- RF-42 STT local es-CO produce transcripción con segmentos y timestamps; diarización básica opcional.
- RF-43 Cada transcripción recibe sentimiento + resumen + borrador RAG ≥3 citas, **sin inferencia externa**.
- RF-44 El agente revisa/edita/aprueba el borrador antes de cualquier envío (human-in-the-loop intacto).
- RF-45 La SPA muestra la ficha de llamada (transcripción real, sentimiento, resumen, borrador) tras flag.
- RF-46 Retención configurable: audio y/o transcripción se purgan/anonimizan según política; acceso auditado.

### 3.7 Requisitos NO funcionales (RNF)

- RNF-41 **Privacidad del audio (dato personal / posible PHI):** audio nunca sale on-prem; STT/TTS 100% local.
- RNF-42 **Retención/anonimización** de grabaciones enlazada con SPEC-021 (política configurable + purga).
- RNF-43 **Latencia STT batch:** objetivo **RTF ≤ 1.0 en GPU** (transcribir ≤ duración real) con `large-v3`;
  degradación documentada en CPU/`medium`; el batch tolera cola.
- RNF-44 **Precisión es-CO:** WER objetivo documentado sobre un set de audios ficticios de prueba en es-CO.
- RNF-45 **Escalabilidad:** procesamiento asíncrono por cola; N workers STT escalables por volumen; un host
  Docker Compose para el piloto.
- RNF-46 **Observabilidad:** RTF, tamaño de cola, tasa de error de STT, métricas por tenant; evidencia egress.
- RNF-47 **Audio en reposo cifrado** (volumen/campo/objeto), como datos personales de SPEC-021.
- RNF-48 **Multi-tenant RLS** efectiva (ADR-004/008); **borrado lógico** (C2); **secretos en env** (C3).

### 3.8 RESTRICCIONES DURAS (invariantes — rompen la build si se violan)

1. **STT/TTS 100% local/self-hosted.** Whisper solo self-hosted (faster-whisper/whisper.cpp); Piper/Coqui si en
   el futuro hay TTS. **Audio NUNCA a un tercero.** Google/AWS/OpenAI Whisper API/Deepgram/AssemblyAI PROHIBIDOS.
2. **IA sin egress** (reafirma ADR-005): STT y LLM/embeddings en red `internal:true`, sin ruta a internet.
3. **Egress del PBX (si externo) acotado como ADR-006:** allowlist por ruta a un único dominio de transporte,
   desde un único módulo/worker; la IA jamás obtiene esa ruta. **Preferible PBX on-prem (sin egress nuevo).**
4. **Multi-tenant RLS** (ADR-004/008): toda entidad de voz lleva `tenant_id`; test cross-tenant que **falla**.
5. **Borrado lógico** (C2); **audio en reposo cifrado**; **secretos en env** fail-fast (C3), nunca en repo/logs.
6. **Human-in-the-loop** preservado: nada se envía al cliente sin aprobación del agente.
7. **No romper** Entregables #1/#2/#3: feature-flag reversible; suites verdes; migraciones aditivas.

---

## 4. STACK LOCAL adicional propuesto (justificado, respeta `.no-externo`)

| Componente | Elección propuesta | Justificación / reutilización |
| ---------- | ------------------ | ----------------------------- |
| **STT** | `faster-whisper` (CTranslate2) modelo `large-v3` es-CO; fallback `medium`/`whisper.cpp` en CPU | Self-hosted, rápido, buen es-CO; RTF ≤ 1 en GPU; sin API externa (SUP-47) |
| **Diarización (opcional)** | `pyannote`/VAD simple agente-vs-cliente | On-prem; segmenta turnos sin biometría avanzada |
| **TTS** | Piper (evaluado, **fuera del #4**) | Reservado para Entregable #5 (VoiceBot en vivo) — SUP-42 |
| **Origen de audio** | Webhook de grabaciones o watcher de spool; **Asterisk/FreeSWITCH on-prem preferido**; Twilio-como-transporte solo si el Lead lo exige (egress ADR-006) | El PBX es transporte; el audio queda on-prem |
| **Almacén de audio** | Volumen local o **MinIO on-prem**, cifrado en reposo | Sin objeto en la nube; cumple RNF-41/47 y SPEC-021 |
| **Cola/worker STT** | Redis + worker (patrón `rag_ingest_worker`/`sentiment_worker`) | Reutiliza la infra de colas del #2/#3; batch escalable |
| **Enriquecimiento IA** | Ollama (Qwen2.5-7B) + embeddings + pgvector **ya existentes** | Reutiliza SPEC-017/018/019 tal cual sobre la transcripción |
| **Persistencia** | PostgreSQL 16 + RLS (ADR-004/008), tablas `call`/`call_transcript` | Reutiliza el modelo multi-tenant + borrado lógico |
| **Auditoría egress** | `check-externos-backend.sh` extendido (STT/TTS sin egress; PBX allowlist por ruta si externo) | Reutiliza el guardarraíl de ADR-006 |

**Cómo reutiliza el pipeline existente:** la transcripción entra al mismo bus que un mensaje de texto —
`call_transcript` → sentimiento (SPEC-018) → resumen + borrador RAG ≥3 citas (SPEC-017) → human-in-the-loop
(SPEC-019) → ficha en la SPA (SPEC-006 real). La topología de egress acotado (ADR-006) se **replica**: si hay
PBX externo, su egress vive aislado del contenedor de IA (`ia_internal internal:true`).

---

## 5. CRITERIOS DE ÉXITO MEDIBLES (Tests — verificables por HAWKEYE/BLACK WIDOW/THOR)

- **CE-41 — STT local end-to-end:** una grabación es-CO ficticia se transcribe con `faster-whisper` local,
  con segmentos+timestamps; **cero** llamadas a STT de terceros (captura de red + `check-externos-backend.sh`
  en verde). WER documentado sobre el set de prueba.
- **CE-42 — Enriquecimiento reutilizado sin inferencia externa:** la transcripción recibe sentimiento + resumen
  + borrador RAG con **≥3 citas trazables**; egress público nulo desde IA/STT (prueba de egress vacío).
- **CE-43 — Aislamiento multi-tenant:** test cross-tenant sobre `call`/`call_transcript` que **falla por RLS**;
  ingesta sin mapeo de tenant → descarte auditado; idempotencia por `call_id` probada (reentrega no duplica).
- **CE-44 — Privacidad y retención del audio:** audio cifrado en reposo; política de retención purga/anonimiza
  según configuración; acceso a transcripción/audio registrado (auditoría HABEAS DATA, enlaza SPEC-021).
- **CE-45 — Latencia batch y no-regresión:** **RTF del STT ≤ 1.0 en GPU** (o degradación CPU documentada) bajo
  carga (THOR); human-in-the-loop intacto; SPA con ficha de llamada tras feature-flag **sin romper** #1/#2/#3
  (suites verdes); cobertura backend **≥ 80%**; `docker compose up` reproducible sin internet de inferencia.

> Transversales heredados: aprobación explícita del Lead; CHECKPOINTS C2/C3/C4/C6/C8; ADR de retención de audio
> y (si aplica) ADR de egress del PBX externo.

---

## 6. Mapa preliminar orientativo para el PLAN-004 (NO son specs — las crea DOCTOR STRANGE)

> Numeración a partir de `next_spec: 35`, `next_plan: 4`, `next_adr: 9`.

- Infra STT local + almacén de audio cifrado + auditoría egress (SPEC-035 aprox.).
- Datos de voz: `call`/`call_transcript` + RLS + idempotencia `call_id` (aprox. SPEC-036).
- Conector de ingesta de grabaciones (webhook/spool, transporte) (aprox. SPEC-037).
- Worker STT `faster-whisper` es-CO + diarización básica (aprox. SPEC-038).
- Enriquecimiento (reutiliza SPEC-017/018/019) sobre transcripción (aprox. SPEC-039).
- Integración SPA ficha de llamada (SPEC-006 real, feature-flag) (aprox. SPEC-040).
- Retención/anonimización de audio + seguridad (enlaza SPEC-021) (aprox. SPEC-041).
- Pruebas + carga (RTF) + observabilidad (aprox. SPEC-042).
- Docs + runbook + deploy on-prem (aprox. SPEC-043).
- ADR-009 (retención/anonimización de audio como dato personal/PHI) y, si PBX externo, ADR-010 (egress
  acotado del PBX, análogo a ADR-006).

---

## 7. PREGUNTAS ABIERTAS AL LEAD (5) — con SUPUESTO por defecto

Si el Lead no responde, el PLAN-004 procede con el supuesto por defecto indicado.

1. **Slice del Entregable #4 (⚠️ SUP-41):** ¿confirmas **transcripción + análisis asíncrono** como el slice
   (alto valor, bajo riesgo, máxima reutilización), o exiges **VoiceBot en vivo** desde ya?
   **Supuesto por defecto:** **transcripción asíncrona**; el VoiceBot en vivo (STT streaming + TTS + IVR +
   barge-in) queda como **Entregable #5**.

2. **PBX / proveedor y acceso (⚠️ SUP-43/SUP-48):** ¿el audio llega de un **PBX propio on-prem
   (Asterisk/FreeSWITCH)** con acceso, o de un **proveedor externo (p. ej. Twilio) como transporte**?
   ¿Entrega **grabación** (fichero) o **stream RTP en vivo**?
   **Supuesto por defecto:** PBX que entrega **grabación (fichero) por webhook/spool**; si es externo se aplica
   egress acotado ADR-006; si aún no hay PBX, se entrega el conector + **simulador de grabaciones** verificable
   en local. Preferido on-prem (sin egress nuevo).

3. **GPU/VRAM y modelo/idioma (⚠️ SUP-44/SUP-46):** ¿sigue vigente **GPU ≥16 GB** para `faster-whisper large-v3`
   es-CO, o dimensionamos para **CPU/`medium`**?
   **Supuesto por defecto:** **GPU ≥16 GB** con `large-v3` es-CO (RTF ≤ 1 batch); fallback **CPU `medium`** con
   RTF degradado documentado; modelo parametrizable por env.

4. **Dominio de datos: salud/PHI vs comercial (⚠️ SUP-45):** ¿el vertical es **salud (PHI)** o
   **comercial/HABEAS DATA**? Impacta retención, cifrado de campo y registro de acceso.
   **Supuesto por defecto:** **comercial/HABEAS DATA (Ley 1581) + GDPR-like**; si el Lead confirma **salud/PHI**
   se añaden RNF extra (cifrado de campo, retención estricta, registro de acceso reforzado, ADR-009 endurecido).

5. **Volumen y retención (dimensionamiento):** ¿cuántas **llamadas/día**, **duración media** y **política de
   retención** del audio (días) y de la transcripción?
   **Supuesto por defecto:** escala **piloto** (cientos de llamadas/día, ≤ 10 min media); retención de audio
   **configurable, por defecto 30 días** y luego anonimización/purga; transcripción retenida según SPEC-021;
   un host Docker Compose con N workers STT escalables.

---

> **Siguiente paso:** 🔮 DOCTOR STRANGE toma este prompt y genera el **PLAN-004** en `.swarm/PLAN-004.md`
> (alcance IN/OUT, fases, dependencias, riesgos, criterios), que IRON MAN presentará al Lead. **NO se crean
> specs** hasta "APROBADO PLAN-004", y **no se implementa** hasta "APROBADO SPEC-0XX". CHECKPOINT C8: prompt
> registrado en `prompt-lab/PROMPT-OPTIMIZADO-FASE4.md`.
