# PLAN-005 — Fase 5 "OmniCore AI" (Entregable #5): VoiceBot conversacional EN VIVO (STT streaming + TTS LOCAL + IVR de catálogo cerrado + barge-in) sobre GPU COMPARTIDA con el batch de #4

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Fecha: 2026-09-21 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo` presente) — PROHIBIDO cualquier modelo/servicio EXTERNO de inferencia o de procesamiento de datos personales por un tercero.
> **DATO ESPECIAL DE ESTA FASE:** el **AUDIO de llamadas EN VIVO es dato personal (posible PHI)** (heredado de #4, ADR-009) y ahora se suma un vector nuevo: la **voz sintética de salida (TTS) que habla en nombre de la empresa en tiempo real**. El **STT y el TTS son 100% LOCALES**: audio de entrada, inferencia y voz de salida **NUNCA** salen a terceros (Google STT/TTS, AWS Transcribe/Polly, OpenAI Whisper/TTS API, Deepgram, AssemblyAI, Azure Speech, ElevenLabs y equivalentes **PROHIBIDOS**). El servicio de voz en vivo corre **SIN egress** (en `ia_internal`, como los workers de IA). Ver §3 y ADR-011/012.
> **RESTRICCIÓN DURA DE CONTROL HUMANO (Lead 2026-09-21, P1 APROBADO):** el VoiceBot en vivo opera SOLO dentro de un **catálogo cerrado de intents pre-aprobado**; **NUNCA** usa un LLM de dominio abierto hablando en vivo. Cualquier intent fuera de catálogo, sentimiento negativo o petición explícita → **transferencia obligatoria a humano**. Esto NO es opcional ni condicional.
> **RESTRICCIÓN DURA DE GPU (Lead 2026-09-21, P3 vinculante):** NO hay presupuesto para GPU dedicada adicional. El VoiceBot en vivo **COMPARTE GPU** con el `stt_worker` batch del Entregable #4 (ya en producción). Esto invalida el supuesto de "GPU dedicada" (SUP-55/RNF-53 del prompt de XAVIER) y obliga a: modelo más liviano, límite duro de concurrencia, prioridad del VoiceBot en vivo sobre el batch, y degradación documentada. Ver §3.6 y ADR-011.
> Origen: `prompt-lab/PROMPT-OPTIMIZADO-FASE5.md` (🧠 XAVIER, con §8 respuestas VINCULANTES del Lead) · Estado: **PROPUESTA** (espera "APROBADO PLAN-005")
> Regla de oro: este PLAN **NO genera SPECs**. Las SPECs se crean SOLO tras la aprobación explícita del Lead ("APROBADO PLAN-005").
> Precedentes: Entregable #1 (maqueta SPA, incl. SPEC-006 VoiceBot visual) **COMPLETADO**; Entregable #2 (backend + IA local, PLAN-002 / SPEC-011..023) y Entregable #3 (canal WhatsApp, PLAN-003 / SPEC-024..034) **EN_VERIFICACION**; **Entregable #4 (PLAN-004 / SPEC-035..043, ADR-009/010) COMPLETO** — transcripción/análisis asíncrono de llamadas, STT local batch, retención/anonimización de audio, ficha de llamada real en la SPA.
> Contadores vigentes (`.swarm/specs.json`): `next_plan: 5`, `next_spec: 44`, `next_adr: 11`.

---

## 0. Lo que el Lead YA decidió (no re-preguntar) — arranque del PLAN

Antes de todo, dos decisiones del Lead (2026-09-21, `prompt-lab/PROMPT-OPTIMIZADO-FASE5.md` §8) son **vinculantes**
y estructuran TODO este plan. No se re-preguntan; se ejecutan:

1. **P1 → Control humano = "catálogo cerrado de intents pre-aprobado + escalación obligatoria".** El VoiceBot
   en vivo NUNCA usa un LLM de dominio abierto hablando en vivo. Restricción DURA (§3.6.2). El diseño concreto
   está en §3.4 (arquitectura del catálogo cerrado y de la escalación).
2. **P3 → SIN GPU dedicada adicional: GPU COMPARTIDA con el `stt_worker` batch de #4.** Restricción DURA que
   obliga a reducir el alcance técnico respecto a lo orientativo del prompt. El plan concreto de mitigación
   (modelo liviano, límite de concurrencia, prioridad sobre el batch, degradación documentada y alternativa
   de bajo cómputo) está en §3.6 — es la sección más crítica de este PLAN.

---

## 1. Objetivo y contexto

### Objetivo

Construir el **Entregable #5** como el **VoiceBot conversacional EN VIVO** que el Entregable #4 dejó
explícitamente fuera de alcance: **atender llamadas telefónicas en tiempo real dentro de un catálogo cerrado
de intents pre-aprobado** (IVR inteligente con NLU/RAG local, **NO** LLM de dominio abierto), con **STT
streaming de baja latencia + TTS 100% local + barge-in**, **transfiriendo de inmediato a un agente humano** ante
cualquier intent fuera de catálogo, sentimiento negativo o petición explícita — sobre una **GPU COMPARTIDA** con
el `stt_worker` batch de #4 (restricción del Lead), con un **presupuesto de latencia objetivo ≤700 ms p95** bajo
un **límite duro y conservador de concurrencia** (a validar por THOR). La llamada en vivo queda **transcrita y
persistida al colgar** reutilizando `call`/`call_transcript` de #4 (aparece en la ficha de llamada existente),
**sin enviar audio/inferencia/TTS a ningún tercero**. Se preserva el invariante de control humano reinterpretado
para voz: **catálogo pre-aprobado + escalación obligatoria fuera de él**, en lugar de aprobación turno-a-turno.

### Por qué esto NO es "Entregable #4 con streaming" (el riesgo central)

PLAN-004 (§2, OUT) difirió esto por razones que **siguen vigentes y se agravan**:

- **Latencia dura, no tolerante a cola.** El batch de #4 tolera picos (el mensaje tarda un poco más en aparecer).
  Un VoiceBot en vivo tiene un **presupuesto de latencia percibida ≤700 ms round-trip** (STT parcial + decisión
  NLU + TTS + red): un pico de GPU no es "más lento", es una **llamada rota** para el humano al otro lado.
- **El human-in-the-loop de #2/#3/#4 (SPEC-019, aprobación turno-a-turno) NO es trasladable a voz en vivo.** Un
  bot que habla en vivo no puede pausar cada frase a esperar aprobación humana. Por eso el Lead aprobó el modelo
  de **guardrails antes, no aprobación durante**: catálogo cerrado + escalación (§3.4).
- **GPU en línea crítica.** El batch de #4 escala horizontalmente (N workers, cola Redis) sin drama; el VoiceBot
  en vivo necesita VRAM **caliente y priorizada** por llamada concurrente. Y aquí NO hay GPU dedicada: **comparte**
  con el batch (§3.6).
- **Superficie SENSIBLE nueva: TTS de salida.** Voz sintética hablando en nombre de la empresa en tiempo real —
  vector nuevo de riesgo (voz clonable/falsificable si se usa mal; contenido que la empresa "dice" sin revisión).
  Mitigación: TTS 100% local (ADR-012) + declaración obligatoria de voz sintética al inicio de cada llamada.

### Qué se REUTILIZA del Entregable #4 (y no se reinventa)

- **Entidades `call` / `call_transcript`** (SPEC-036): la llamada en vivo también queda transcrita y persistida
  al colgar, igual que hoy. La transcripción en vivo se acumula en los mismos segmentos+timestamps.
- **Conector PBX / telefonía** (SPEC-037, `app/services/telefonia/`): se **extiende de grabación post-hoc a
  stream de media en vivo** (RTP/WebSocket bidireccional), no se crea uno nuevo.
- **Retención/anonimización de audio** (SPEC-041, ADR-009): aplica sin cambios al audio en vivo; se **extiende**
  al audio TTS de salida si se persiste, y a la retención de la transcripción en vivo.
- **RAG con citas** (SPEC-017) como **fuente del catálogo cerrado**: las respuestas del IVR se anclan a la base
  de conocimiento ya indexada por RAG (con citas trazables), NO se generan libremente.
- **Sentimiento local** (SPEC-018) sobre la transcripción parcial en vivo: dispara la escalación por frustración.
- **NLU por embeddings/pgvector** ya existentes (SPEC-014..017): el clasificador de intent contra el catálogo
  cerrado reutiliza el mismo motor de embeddings (`nomic-embed`), sin LLM generativo en el camino de voz.
- **`check-externos-backend.sh`** (SPEC-035/032): se **extiende a TTS de terceros** (mismo patrón que STT en #4).
- **Aislamiento `ia_internal internal:true`** (ADR-005), **RLS FORCE efectiva** (ADR-004/008), **secretos env
  fail-fast** (C3), **borrado lógico** (C2), **feature-flag SPA** (patrón `VITE_USE_REAL_API`, SPEC-020/031),
  **observabilidad** (`/metrics`, structlog, Locust).

**Novedad estructural de esta fase (única y acotada):** el **bucle de interacción en vivo** (STT streaming ↔ NLU
de catálogo ↔ TTS ↔ barge-in) sobre **GPU compartida y priorizada**, con **escalación obligatoria a humano** y
**voz sintética de salida** declarada. No se reinventa almacenamiento ni modelo de datos.

---

## 2. Alcance IN / OUT

### IN — entra en el vertical slice #5

1. **Catálogo cerrado de intents pre-aprobado** (definido/aprobado por el Lead antes de implementar; §7 P-C):
   consulta de estado de pedido/cita, agendar/reagendar/cancelar cita, FAQ desde la base de conocimiento RAG
   existente, y enrutamiento por intención a la cola humana correspondiente. **Fuera del catálogo → transferencia.**
2. **STT streaming de baja latencia** sobre el audio en vivo del PBX (WebSocket bidireccional, ventanas
   deslizantes), con **modelo liviano** (§3.6.1) por la restricción de GPU compartida. **Sin egress.**
3. **NLU/clasificación de intent contra el catálogo cerrado** por embeddings/pgvector (reutiliza SPEC-014..017),
   con **umbral de confianza**; por debajo del umbral o sin match → **transferencia inmediata**. **NO** generación
   libre de LLM en el camino de voz en vivo.
4. **TTS 100% local** (Piper es-CO, o voz más cercana disponible) para las respuestas del catálogo; con
   **modo de bajo cómputo por mensajes pregrabados/concatenados** como opción de degradación (§3.6.4).
   **Declaración de voz sintética al inicio de cada llamada** (RNF-55, ADR-012).
5. **Barge-in:** el usuario puede interrumpir la síntesis TTS en curso; el audio de salida se cancela y el turno
   vuelve a STT de inmediato. Exige TTS/STT en el mismo host de baja latencia y cancelación de síntesis en curso.
6. **Escalación a agente humano** con contexto: transferencia con **transcripción parcial + intent detectado +
   señal de urgencia/sentimiento** a la cola/agente correspondiente; el usuario nunca queda "colgado" sin humano.
7. **GPU compartida gestionada** (§3.6): límite duro de llamadas concurrentes en vivo, prioridad del VoiceBot
   sobre el `stt_worker` batch de #4, degradación documentada, y modo bajo-cómputo si <700 ms sigue en riesgo.
8. **Persistencia de la llamada en vivo:** reutiliza `call`/`call_transcript` de #4; la transcripción completa
   (+ intents detectados, transferencias) queda disponible en la ficha de llamada al terminar.
9. **Observabilidad de latencia real:** medición end-to-end por llamada (audio-in → STT parcial → NLU → TTS →
   audio-out), p95, tasa de barge-in, tasa de escalación, contención de GPU frente al batch; alertas si se supera
   el presupuesto de latencia o el límite de concurrencia.
10. **Auditoría de egress extendida:** TTS de terceros PROHIBIDO en `check-externos-backend.sh`, mismo patrón que
    STT en #4; el servicio de voz en vivo sin ruta a internet ni al PBX salvo el transporte de media acotado.
11. **Monitor de llamadas en vivo en la SPA** (feature-flag): estado de la llamada, intent detectado, botón de
    transferencia/toma de control por el agente; sin romper #1-#4 (flag OFF = maqueta/estado actual intacto).

### OUT — NO entra en este slice (Entregable #6+)

- **LLM de dominio abierto conversando libremente por voz** (fuera del catálogo cerrado) — PROHIBIDO por
  restricción dura del Lead (§3.6.2); posible fase posterior SOLO con decisión explícita distinta del Lead.
- **GPU dedicada adicional / dimensionamiento de alta concurrencia** — NO hay presupuesto (Lead P3). El piloto
  se dimensiona al **límite duro y conservador** de la GPU compartida (§3.6.2), no a 5-10 concurrentes.
- **Identificación biométrica de locutor** (verificación de identidad por voz).
- **Clonación/personalización avanzada de voz** más allá de una voz Piper es-CO estándar.
- **Multi-idioma** más allá de es-CO (heredado de #4); **emociones acústicas** más allá del sentimiento textual.
- **Despliegue completo de PBX** (dial-plan, colas ACD, troncales SIP): fuera; solo el conector de media en vivo
  extendido desde SPEC-037.
- **HA/K8s / autoescalado del servicio de voz** — un host Docker Compose con límite de concurrencia fijo.

---

## 3. Arquitectura de referencia

### 3.1 Flujo end-to-end del turno de voz en vivo

```
entrante:   PBX --stream media en vivo (RTP/WebSocket bidireccional, extiende SPEC-037)-->
            [voice_gateway en `app`: gestiona la sesión SIP/media, transporte acotado al PBX]
            --> declara "está hablando con un asistente virtual" (TTS pregrabado, ADR-012) --

bucle de turno (presupuesto ≤700 ms p95, GPU COMPARTIDA priorizada):
            audio-in --frames--> [voice_stt: faster-whisper LIVIANO streaming, ventana deslizante, SIN egress]
                     --transcripción parcial-->
            [NLU intent: embeddings/pgvector contra CATÁLOGO CERRADO (reutiliza SPEC-014..017), umbral de confianza]
                     |
                     ├── match en catálogo con confianza ≥ umbral -->
                     │      [respuesta del catálogo anclada a RAG con citas (SPEC-017)]
                     │      --> [voice_tts: Piper local  |  o mensajes PREGRABADOS/concatenados (bajo cómputo)]
                     │      --audio-out--> PBX --> usuario   (barge-in: usuario interrumpe -> cancela síntesis, vuelve a STT)
                     │
                     └── sin match / confianza < umbral / sentimiento negativo (SPEC-018) / "quiero un humano" -->
                            [ESCALACIÓN: transferir a cola/agente con contexto = transcripción parcial + intent + urgencia]

al colgar:  se persiste call/call_transcript (segmentos+timestamps, intents, transferencias) [RLS por tenant]
            --> (opcional) enriquecimiento batch de #4 sobre la transcripción completa (SPEC-039), SIN inferencia externa

retención:  política de #4 (ADR-009/SPEC-041) aplica al audio en vivo, a la transcripción y al audio TTS si se persiste
```

### 3.2 Componentes y DÓNDE está el límite de egress (diagrama ASCII)

```
                                   HOST ON-PREM (Docker Compose)
  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
  │                                                                                                │
  │   red `app` (bridge, CON egress restringido por allowlist SOLO al host del PBX de media/SIP)   │
  │   ┌──────────────────────────────────────────────────────────────────────────────────┐        │
  │   │  [reverse proxy TLS]──►[api FastAPI]──►[Redis colas+pubsub]──►[PostgreSQL/RLS]      │        │
  │   │                              │  ▲                 │                                  │        │
  │   │            [voice_gateway]───┘  │                 ▼                                  │        │
  │   │             (sesión SIP/media, transporte RTP/WS acotado al PBX, extiende SPEC-037)  │        │
  │   └──────────────────────────────┼──────────────────────────────────────────────────┼─┘        │
  │                                  │  ═════════ LÍMITE DE EGRESS (solo al host del PBX) ═│          │
  │                                  │  Solo `api`/`voice_gateway` salen, y SOLO al host    ▼          │
  │                                  │  del PBX de media/SIP (allowlist auditada, ADR-011) ►► PBX     │
  │                                  │                                                                │
  │   red `ia_internal` (bridge, internal: true — ⛔ SIN egress, NUNCA internet, NUNCA el PBX)         │
  │   ┌──────────────────────────────▼─────────────────────────────────────────────────┐           │
  │   │  [voice_stt = faster-whisper LIVIANO streaming]  ⛔ jamás alcanza PBX ni internet │           │
  │   │  [voice_tts = Piper local + banco de audios pregrabados]  ⛔ sin egress            │           │
  │   │  [NLU intent = embeddings nomic-embed contra catálogo cerrado] ⛔ sin egress       │           │
  │   │  [stt_worker BATCH de #4 = faster-whisper]  ⛔ sin egress                          │           │
  │   │  [ia = Ollama] LLM local (solo enriquecimiento batch, NUNCA camino de voz en vivo) │           │
  │   │                                                                                    │           │
  │   │  ┌──────────── GPU FÍSICA ÚNICA — COMPARTIDA Y PRIORIZADA (ADR-011) ────────────┐ │           │
  │   │  │  fracción reservada/prioritaria  ►  voz en vivo (voice_stt + voice_tts)       │ │           │
  │   │  │  resto, despriorizable/pausable  ►  stt_worker BATCH de #4                    │ │           │
  │   │  └───────────────────────────────────────────────────────────────────────────┘ │           │
  │   └──────────────────────────────────────────────────────────────────────────────┘           │
  └─────────────────────────────────────────────────────────────────────────────────────────────┘
   ⛔ = internal:true, sin ruta a internet   ►► = ÚNICO egress permitido (transporte de media al PBX, no inferencia)
```

### 3.3 DÓNDE está el LÍMITE DE LATENCIA y de GPU COMPARTIDA (diagrama ASCII)

```
  PRESUPUESTO DE LATENCIA END-TO-END ≤ 700 ms p95 (por turno de voz, bajo el límite de concurrencia)
  ┌──────────────────────────────────────────────────────────────────────────────────────────────┐
  │  usuario habla                                                                                  │
  │     │  (a) red/PBX in ~ .....ms                                                                   │
  │     ▼                                                                                            │
  │  [voice_stt streaming, ventana deslizante]  ── PRESUPUESTO PARCIAL STT ──►  transcripción parcial │
  │     │                                          (modelo LIVIANO por GPU compartida, §3.6.1)        │
  │     ▼                                                                                            │
  │  [NLU intent contra catálogo cerrado (embeddings)]  ── barato, determinista, sin LLM generativo ──►│
  │     │                                                                                            │
  │     ▼                                                                                            │
  │  [voice_tts]  ── Piper local  |  o AUDIO PREGRABADO (coste ~0 de GPU) ──►  audio-out              │
  │     │  (d) red/PBX out ~ .....ms                                                                   │
  │     ▼                                                                                            │
  │  usuario oye la respuesta      ◄── barge-in puede cortar aquí y devolver el turno a STT           │
  └──────────────────────────────────────────────────────────────────────────────────────────────┘
     ═════════════ LÍMITE DE GPU COMPARTIDA (ADR-011) — quién gana el recurso ═════════════
     Regla de prioridad: mientras haya ≥1 llamada en vivo ACTIVA, la voz en vivo tiene PRIORIDAD
     sobre el stt_worker batch de #4. El batch se DESPRIORIZA/PAUSA temporalmente (cola Redis sigue
     acumulando; el batch reanuda al liberarse la voz). Una llamada en vivo degradada es PEOR que
     una transcripción batch que tarda unos segundos más.
     Límite duro de concurrencia en vivo = C (conservador, p. ej. 1-3, a validar por THOR).
     Si al llegar una llamada nueva ya hay C activas -> NO se degrada a las activas: la nueva
     se enruta a IVR pregrabado mínimo + escalación a humano (nunca se rompe una llamada en curso).
```

**Regla de oro de la topología (invariante de seguridad de esta fase):**

- El **`voice_stt`, `voice_tts` y el NLU de intent** viven **SOLO** en `ia_internal` (`internal: true`): **NUNCA**
  se les añade la red `app` ni ruta a internet ni al PBX. Reciben/entregan audio a través del `voice_gateway`
  por la red interna, no por red externa.
- El **`voice_gateway`** (sesión SIP/media) vive en `app` (que tiene egress) y su salida se **restringe por
  allowlist al único host del PBX** de media/SIP (ADR-011, patrón ADR-006/010). Si el PBX es **on-prem**
  (Asterisk/FreeSWITCH), **no hay egress nuevo** (topología preferida).
- El **límite de egress** es exactamente ese borde: lo único que sale es el **transporte de media/SIP al PBX**.
  El **audio, el STT, el TTS y la inferencia jamás salen** del host.
- El **LLM de dominio abierto (Ollama)** existe en `ia_internal` pero **NUNCA está en el camino de voz en vivo**
  (solo enriquecimiento batch post-llamada, SPEC-039). El camino de voz usa **solo** STT + NLU de catálogo + TTS.

### 3.4 Modelo de control humano: CATÁLOGO CERRADO + ESCALACIÓN (P1 vinculante — decisión arquitectónica central)

El human-in-the-loop de #2/#3/#4 (aprobar cada frase, SPEC-019) **no es trasladable** a voz en vivo. El Lead
aprobó (P1) reemplazarlo por **"guardrails antes, no aprobación durante"**. Diseño concreto:

**(a) Catálogo cerrado de intents (guardrail "antes").**
- El catálogo es un **artefacto de configuración versionado y pre-aprobado por un humano** (no editable en
  runtime por el bot). Cada intent declara: nombre, ejemplos de frases (para embeddings), respuesta permitida
  (anclada a RAG con citas, SPEC-017, o a un mensaje pregrabado), y acción (responder / consultar dato / agendar
  / **transferir**). Cambiar el catálogo = cambio de config revisado, no decisión del bot.
- **NLU determinista sin generación libre:** la clasificación de intent se hace por **similitud de embeddings**
  (`nomic-embed`, reutiliza SPEC-014..017) entre la transcripción parcial y los ejemplos del catálogo, con un
  **umbral de confianza**. NO hay un LLM generando texto libre en el camino de voz en vivo (restricción dura
  §3.6.2). Las respuestas son plantillas del catálogo rellenadas con datos consultados (estado de cita, etc.),
  ancladas a citas RAG cuando aplique.

**(b) Escalación obligatoria a humano (guardrail de salida).** El VoiceBot transfiere **de inmediato** cuando:
- la confianza de intent está **por debajo del umbral** o **no hay match** en el catálogo cerrado;
- el **sentimiento es negativo/frustración** (SPEC-018 sobre la transcripción parcial);
- el usuario **pide explícitamente un humano** (intent reservado "hablar con una persona", siempre disponible);
- la **latencia real supera el presupuesto** de forma sostenida o se alcanza el **límite de concurrencia** C.
- **Transferencia con contexto:** al escalar, se entrega al agente/cola la **transcripción parcial + intent
  detectado (o "sin intent") + señal de urgencia/sentimiento**, para que el humano retome sin que el cliente
  repita. El usuario **nunca** queda colgado ni el bot "adivina" fuera del catálogo.
- **RNF-53:** la escalación ocurre en **≤ N segundos** (a fijar en la SPEC de escalación, valor conservador),
  medible y probado con casos de prueba (HAWKEYE).

### 3.5 Voz sintética de salida (TTS) — vector SENSIBLE nuevo

- **TTS 100% local** (Piper es-CO, o voz más cercana disponible; Coqui como alternativa evaluada por THOR).
  **Ningún** TTS de terceros (Google TTS, AWS Polly, ElevenLabs, Azure Speech, OpenAI TTS) — PROHIBIDOS en CI
  (mismo criterio que STT en ADR-009), extendido en `check-externos-backend.sh`.
- **Declaración de voz sintética** (ADR-012, RNF-55): al inicio de **cada** llamada, un mensaje pregrabado declara
  que el interlocutor es un asistente virtual. Buena práctica anti-deepfake/regulatoria (Ley 1581 / normativa de
  IA conversacional; §7 P-L). Se declara siempre, independientemente de si la ley lo exige explícitamente.
- **Retención del audio TTS:** si se persiste el audio de salida (para auditoría/ficha), aplica la política de
  retención/anonimización de #4 (SPEC-041); por defecto se prefiere **no persistir** el audio TTS (se persiste la
  transcripción textual), reduciendo superficie.

### 3.6 GPU COMPARTIDA — plan concreto de mitigación (P3 vinculante — sección más crítica del PLAN)

El Lead confirmó que **NO hay GPU dedicada adicional**: el VoiceBot en vivo **comparte la GPU física** con el
`stt_worker` batch de #4 (en producción). Esto invalida SUP-55/RNF-53 del prompt (que asumían GPU dedicada) y se
resuelve aquí como parte del PLAN (no como detalle diferido), con cuatro palancas:

**3.6.1 — Modelo STT/TTS MÁS LIVIANO (bajar VRAM por llamada en vivo).**
- STT en vivo con un modelo **mucho más liviano que `large-v3`**: `distil-whisper` o `faster-whisper` `small`/
  `medium` **cuantizado** (int8/int8_float16), en modo streaming de ventana deslizante. Se acepta un WER algo
  mayor porque el **camino de voz solo necesita clasificar intent contra un catálogo cerrado** (no transcripción
  perfecta): el NLU tolera transcripción parcial imperfecta mejor que un resumen legal. La transcripción "de
  calidad" para la ficha puede recomputarse en batch al colgar con el `large-v3` de #4 (reúso, sin coste en vivo).
- TTS con **Piper** (modelo pequeño, muy barato en cómputo) — o, en el modo de bajo cómputo (3.6.4), **audios
  pregrabados** con coste de GPU ~0.
- El modelo en vivo se elige **parametrizable por env** y se fija tras medición de THOR (F6).

**3.6.2 — LÍMITE DURO de llamadas concurrentes en vivo (conservador).**
- Se define un **límite duro `C`** de llamadas en vivo simultáneas, **mucho menor** que el piloto de 5-10 que
  asumía GPU dedicada. **Propuesta de arranque: `C = 1-3`, a validar por THOR** bajo carga real compartiendo GPU
  con el batch (F6). El valor final se fija por medición, no por deseo.
- Al llegar la llamada **C+1**, **NO se degrada** ninguna llamada activa: la nueva se atiende con un **IVR mínimo
  pregrabado + escalación a humano** (o cola), nunca rompiendo una conversación en curso. El límite es un
  invariante de calidad, no un "best effort".

**3.6.3 — PRIORIDAD/AISLAMIENTO frente al batch de #4 (ADR-011).**
- **Regla:** mientras haya **≥1 llamada en vivo activa**, la voz en vivo tiene **prioridad** sobre el `stt_worker`
  batch. Una llamada en vivo degradada es peor que una transcripción batch que tarda unos segundos más.
- **Mecanismo (a fijar en la SPEC de infra/THOR, dos opciones combinables):**
  1. **Pausa/despriorización del batch:** una señal (Redis/lock) hace que el `stt_worker` batch **suspenda o
     reduzca** su consumo de GPU mientras haya llamadas en vivo; la cola Redis del batch **sigue acumulando** y
     el batch **reanuda** al liberarse la voz (el batch es tolerante a cola por diseño de #4).
  2. **Fracción de VRAM reservada** exclusiva para el proceso de voz en vivo (el resto se comparte con el batch),
     para que la voz siempre tenga memoria caliente y no compita por asignación bajo carga.
- Se instrumenta la **contención GPU** (tiempo de espera de GPU de la voz, backlog del batch inducido) para
  evidenciar que la prioridad funciona y cuantificar el impacto en el SLA del batch de #4 (que se documenta).

**3.6.4 — DEGRADACIÓN documentada + alternativa de BAJO CÓMPUTO (si <700 ms sigue en riesgo).**
- Igual criterio que "RTF ≤1.0 GPU o degradación CPU documentada" de #4, aplicado a latencia conversacional: si
  bajo el límite `C` no se cumple **≤700 ms p95**, se **documenta la degradación medida** y se activa la
  alternativa de bajo cómputo:
- **Alternativa explícita (sugerida por XAVIER, aprobada como plan B en este PLAN):** **IVR con mensajes
  pregrabados/concatenados** para las respuestas del catálogo cerrado (sin TTS **generativo** en el camino
  caliente). Como el catálogo es cerrado y las respuestas son plantillas, gran parte puede resolverse con audios
  pregrabados por frase/dato, concatenados en runtime — coste de GPU ~0 en TTS, dejando la GPU para el STT en
  vivo. El TTS generativo Piper se reserva **solo** para respuestas que lo justifiquen (p. ej. datos variables
  no pregrabables).
- **Decisión de diseño:** el TTS se implementa detrás de una **interfaz conmutable** (Piper generativo ↔ banco
  de audios pregrabados) por feature-flag/env, de modo que pasar al modo bajo-cómputo **no** requiere rediseño.
- Si **ni con el modo bajo-cómputo** y `C=1` se logra un presupuesto conversacional aceptable compartiendo GPU,
  el PLAN lo declara explícitamente y el alcance se recorta a **IVR de comandos cortos pregrabados sin diálogo
  fluido** (decisión del Lead), documentando la limitación — nunca se sirve una experiencia de voz rota.

### 3.7 Aislamiento del STT/TTS/IA en vivo (cómo queda garantizado sin egress)

- Se **conserva** ADR-005/ADR-009 sin debilitarlos: `ia_internal internal:true`, firewall host DROP saliente para
  los contenedores de IA/voz, DNS interno/vacío, **pesos de Whisper/Piper montados por volumen** (sin `pull` en
  runtime), banco de audios pregrabados montado por volumen.
- `voice_stt`, `voice_tts` y NLU **se añaden a `ia_internal`** (no a `app`): comparten el aislamiento de la IA.
  El audio en vivo se les entrega desde el `voice_gateway` por la **red interna**, nunca desde internet ni el PBX.
- El **egress de media/SIP** lo tiene **solo** `voice_gateway` en `app`, y **solo** al host del PBX (allowlist,
  ADR-011). Si el PBX es **on-prem**, **no hay egress nuevo**. Prueba de egress vacío desde voice_stt/voice_tts/NLU.
- **Evidencia:** captura de red durante un e2e de llamada muestra salida pública **solo** desde `voice_gateway`
  y **solo** al host del PBX (si externo); el intento de egress desde `voice_stt`/`voice_tts`/NLU/`ia` **falla**.

### 3.8 Auditoría "cero audio/inferencia/TTS a terceros" (evolución de `check-externos-backend.sh`)

1. **Se mantiene** `FORBIDDEN_URLS`/`FORBIDDEN_SDKS` de #2/#3/#4 (APIs de inferencia + STT de terceros) y se
   **añaden explícitamente** las APIs de **TTS de terceros** (Google TTS, AWS Polly, ElevenLabs, Azure Speech,
   OpenAI TTS, Coqui-cloud, etc.): PROHIBIDAS en todo el código.
2. **Allowlist de transporte de media** (solo si PBX externo): el host del PBX de media/SIP se permite **solo**
   dentro del módulo del `voice_gateway` (`app/services/telefonia/`). Fuera de ese módulo → **FALLA**.
3. **Prohíbe** que `voice_stt`/`voice_tts`/NLU/módulos de IA importen el cliente de transporte de media o alcancen
   el host del PBX, y que el `voice_gateway` importe/llame STT/TTS/IA directamente (solo por la red interna/cola).
4. **Prohíbe** cualquier dominio/host en los manifiestos de `ia_internal` y en la config de los servicios de voz.
5. Mantiene la verificación de `ia_internal: internal:true` y de que el **LLM de dominio abierto no está en el
   camino de voz en vivo** (solo enriquecimiento batch).

---

## 4. Fases y entregables

| Fase   | Nombre                                                        | Entregables clave                                                                                                                                                                                                                                                                              |
| ------ | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **F0** | Infra voz en vivo + GPU compartida priorizada + auditoría + ADRs | `docker-compose` con `voice_stt`/`voice_tts`/NLU en `ia_internal` (sin egress) y `voice_gateway` en `app` con allowlist al host del PBX de media; **mecanismo de prioridad de GPU** frente al `stt_worker` batch de #4 (pausa/despriorización + fracción de VRAM reservada); pesos Whisper liviano + Piper + banco de audios pregrabados por volumen; `check-externos-backend.sh` extendido (TTS de terceros prohibido); `.env.example` con vars (modelo, `C`, umbrales, PBX); ADR-011/012; reverse proxy TLS/WSS. |
| **F1** | Catálogo cerrado de intents + NLU determinista (sin LLM libre) | Esquema y artefacto versionado del **catálogo cerrado** (intents, ejemplos, respuestas ancladas a RAG/pregrabadas, acción); **NLU por embeddings/pgvector** (reutiliza SPEC-014..017) con umbral de confianza; intent reservado "hablar con una persona"; validación de que **ningún** LLM generativo entra al camino de voz en vivo. |
| **F2** | Conector de media en vivo (extiende SPEC-037 de grabación a stream) | `voice_gateway`: sesión SIP/media, stream RTP/WebSocket bidireccional con el PBX (transporte acotado, allowlist), declaración de voz sintética al inicio (ADR-012), enrutado de tenant desde metadatos de la llamada; sin mapeo → escalación/descarte auditado. Reutiliza el conector PBX de #4. |
| **F3** | STT streaming liviano en vivo (GPU compartida)               | `voice_stt`: `distil-whisper`/`faster-whisper` liviano cuantizado en ventana deslizante, transcripción parcial de baja latencia, **prioridad de GPU** activa frente al batch, instrumentación de latencia parcial; sin egress. |
| **F4** | Bucle de diálogo: NLU→respuesta de catálogo (RAG/pregrabada)→TTS + barge-in | Orquestador de turno: clasifica intent, rellena plantilla anclada a RAG con citas (SPEC-017) o selecciona audio pregrabado, sintetiza con Piper **o** modo bajo-cómputo (interfaz conmutable §3.6.4); **barge-in** (cancelación de síntesis en curso, vuelta a STT); presupuesto de latencia por turno instrumentado. |
| **F5** | Escalación a humano con contexto + monitor SPA (feature-flag) | Escalación obligatoria (fuera de catálogo / sentimiento negativo SPEC-018 / petición explícita / latencia sostenida / límite `C`) con transcripción parcial + intent + urgencia a la cola/agente; **monitor de llamadas en vivo** en la SPA (estado, intent, transferir/tomar control) tras feature-flag; sin romper #1-#4. |
| **F6** | Latencia/GPU compartida (THOR) + límite de concurrencia + degradación | Medición end-to-end **p95 ≤700 ms** bajo concurrencia; **fijación empírica de `C`** (1-3) compartiendo GPU con el batch; verificación de la **prioridad** (voz gana, batch se despriorza/reanuda, backlog del batch cuantificado); si <700 ms no se cumple → **degradación documentada** + activación del **modo bajo-cómputo pregrabado**. THOR + HAWKEYE. |
| **F7** | Seguridad/egress + persistencia de la llamada + retención (reutiliza #4) | Barrido BLACK WIDOW del vector TTS/voz sintética; `check-externos-backend.sh` verde (TTS de terceros prohibido); prueba de egress vacío desde voz/IA; persistencia de la llamada en vivo en `call`/`call_transcript` (SPEC-036) al colgar; retención/anonimización (SPEC-041/ADR-009) aplicada a audio en vivo/transcripción/TTS. |
| **F8** | Docs + runbook + simulador de llamada en vivo + deploy on-prem | Runbook (integración PBX de media/SIP, modelos STT/TTS, catálogo de intents, `C`, prioridad de GPU, política de degradación) con placeholders; OpenAPI/AsyncAPI del gateway; **simulador de llamada en vivo** verificable en local (sin PBX real); deploy on-prem (QUICKSILVER, con aprobación del Lead). |

---

## 5. Dependencias entre fases y ruta crítica

- **F0** habilita todo (infra de voz + GPU compartida priorizada + auditoría + ADRs). Ninguna fase de voz en vivo
  arranca sin F0. Es donde se resuelve la restricción dura de GPU (§3.6.3).
- **F1** (catálogo cerrado + NLU) depende de F0 y del RAG/embeddings ya existentes (SPEC-014..017); es la puerta
  del control humano (P1) — sin catálogo cerrado no hay diálogo permitido.
- **F2** (media en vivo) depende de F0 y extiende SPEC-037; es la puerta de entrada de audio en vivo.
- **F3** (STT streaming liviano) depende de F0 (GPU priorizada) y F2 (media en vivo). Es núcleo técnico y de riesgo.
- **F4** (bucle de diálogo + barge-in) depende de F1 (catálogo/NLU), F3 (STT parcial) y del RAG (SPEC-017).
- **F5** (escalación + monitor SPA) depende de F4 (turno funcional) y reutiliza SPEC-018 (sentimiento) y SPEC-020.
- **F6** (latencia/GPU/THOR + `C` + degradación) depende de que F3–F5 estén completas; es la **puerta de
  viabilidad** — aquí se confirma si <700 ms es alcanzable compartiendo GPU, o se activa el modo bajo-cómputo.
- **F7** transversal (seguridad/egress/persistencia/retención): se diseña desde F0 y se **cierra** auditando todo.
- **F8** cierra: runbook/simulador/deploy tras F6/F7.

**Ruta crítica:** `F0 → F2 → F3 → F4 → F6 → F8` (F1 en paralelo desde F0; F5 solapa el final de F4; F7 transversal).
La **ruta crítica dura** es la **tripleta F3 (STT streaming liviano) + F4 (bucle+barge-in) + F6 (latencia/GPU
compartida)**: el presupuesto ≤700 ms sobre GPU compartida es el mayor riesgo técnico y la puerta de viabilidad.

---

## 6. Riesgos y mitigaciones

| #        | Riesgo                                                                                                            | Impacto                          | Mitigación                                                                                                                                                                                                                                            |
| -------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R-51** | **Presupuesto de latencia ≤700 ms NO alcanzable sobre GPU compartida** con el batch de #4.                        | **Crítico** (viabilidad de la fase) | Modelo STT/TTS liviano (§3.6.1); **límite duro `C`** conservador validado por THOR (§3.6.2); **prioridad de GPU** sobre el batch (§3.6.3); **degradación documentada + modo bajo-cómputo pregrabado** (§3.6.4). F6 es la puerta de viabilidad; si ni así, alcance recortado a IVR de comandos cortos. |
| **R-52** | **Contención de GPU entre voz en vivo y batch de #4** (ambos degradan bajo carga).                                | **Crítico** (SLA voz Y batch)    | **Prioridad explícita** de la voz (pausa/despriorización del batch + fracción de VRAM reservada, ADR-011); el batch es tolerante a cola (reanuda al liberarse la voz); backlog del batch inducido **cuantificado y documentado**; instrumentación de contención. |
| **R-53** | **El bot habla fuera del catálogo cerrado** (alucinación/compromiso verbal sin revisión) — rompe P1.              | **Crítico** (regulatorio/reputacional) | **NLU determinista por embeddings** contra catálogo cerrado con umbral (§3.4); **NINGÚN LLM generativo en el camino de voz en vivo** (restricción dura §3.6.2, verificada en CI §3.8.5); fuera de catálogo/baja confianza → **transferencia obligatoria**. |
| **R-54** | **Audio/inferencia/TTS enviados a un tercero** (STT/TTS de terceros, o egress de media que abra ruta a la IA).    | **Crítico** (rompe SENSIBLE, PHI) | Invariante de topología (§3.2): voz/IA solo en `ia_internal internal:true`; egress solo `voice_gateway`→host PBX de media; STT **y TTS** de terceros PROHIBIDOS en CI (§3.8); firewall host DROP; prueba de egress vacío. ADR-011/012. |
| **R-55** | **Voz sintética engañosa / riesgo deepfake regulatorio** (usuario cree que habla con un humano).                  | Alto (legal/reputacional)        | **Declaración obligatoria de voz sintética** al inicio de cada llamada (ADR-012, RNF-55); TTS 100% local (no clonación de voz de terceros); voz Piper estándar, no clonada; §7 P-L confirma marco legal. |
| **R-56** | **Barge-in no funciona / latencia percibida rota** (el bot no se calla al ser interrumpido).                      | Alto (UX de voz)                 | STT/TTS en el mismo host de baja latencia; pipeline con **cancelación de síntesis en curso** (§3.6.4 interfaz conmutable); test de barge-in medible (CE-54); VAD para detectar habla del usuario durante la síntesis. |
| **R-57** | **Escalación tardía o sin contexto** (el cliente frustrado repite todo al humano).                                | Alto (UX/cumplimiento P1)        | Escalación en **≤ N s** (RNF-53) con **transcripción parcial + intent + urgencia**; intent reservado "hablar con una persona" siempre disponible; sentimiento negativo (SPEC-018) dispara escalación; casos de prueba (HAWKEYE). |
| **R-58** | **WER alto del modelo liviano** degrada la clasificación de intent.                                               | Medio (calidad de NLU)           | El camino de voz solo clasifica contra catálogo cerrado (tolera transcripción imperfecta mejor que un resumen); umbral de confianza + escalación ante baja confianza (no adivina); transcripción "de calidad" recomputada en batch (`large-v3` de #4) para la ficha. |
| **R-59** | **Egress del PBX de media** (si externo: allowlist mal acotada o la IA obtiene ruta al PBX).                       | Crítico (política)               | Allowlist **por ruta** al único host del PBX de media/SIP en el `voice_gateway` (ADR-011, patrón ADR-006/010); voz/IA jamás importan ese transporte; preferible PBX on-prem (sin egress nuevo); test negativo que **falla** la build. |
| **R-60** | **Fuga cross-tenant** de la llamada en vivo / transcripción.                                                      | Alto (privacidad, PHI)           | `call`/`call_transcript` con `tenant_id` + **RLS FORCE efectiva** (ADR-004/008); resolución de tenant desde metadatos de la llamada + escalación/descarte auditado sin mapeo; **test cross-tenant que FALLA por RLS** (HAWKEYE). |
| **R-61** | **Regresión en Entregables #1-#4** (en particular, degradar el batch STT de #4 en producción).                    | Medio-Alto                       | Feature-flag reversible (flag OFF = estado actual intacto); migraciones **aditivas**; el batch de #4 **reanuda** tras la voz (tolerante a cola); suites #1-#4 verdes; medición de backlog inducido documentada como impacto aceptado. |

**Top-3:** **R-51/R-52 (latencia ≤700 ms y contención de GPU compartida — la puerta de viabilidad de toda la
fase)**, **R-53 (el bot fuera del catálogo cerrado — rompe P1)**, **R-54 (audio/inferencia/TTS a terceros —
rompe SENSIBLE/PHI)**. R-55 (voz sintética/deepfake) y R-57 (escalación con contexto) inmediatamente detrás.

---

## 7. Criterios de éxito verificables (mapeo con CE-51..CE-55 de XAVIER)

| ID        | Criterio                                                                                                                                                          | Cómo se verifica                                                                                                                                                            | Fase        |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| **CE-51** | **Latencia real sobre GPU compartida:** p95 end-to-end **≤ 700 ms** bajo el límite de concurrencia `C` compartiendo GPU con el batch de #4, **o degradación documentada + modo bajo-cómputo activado**. | Medición end-to-end bajo carga (THOR) con el batch de #4 corriendo en paralelo; `C` fijado empíricamente; si no se cumple, evidencia de degradación + IVR pregrabado.        | F3/F4/F6    |
| **CE-52** | **Prioridad de GPU verificada:** con ≥1 llamada en vivo activa, la voz gana GPU y el `stt_worker` batch se despriorza/pausa y **reanuda** al liberarse; backlog del batch inducido cuantificado. | Test de contención (THOR): llamada en vivo + batch simultáneos; medición de latencia de voz estable y de backlog/recuperación del batch. ADR-011.                            | F0/F6       |
| **CE-53** | **Control humano (catálogo cerrado + escalación):** intent fuera de catálogo / baja confianza / sentimiento negativo / "quiero un humano" → **transferencia con contexto en ≤ N s**; **ningún** LLM generativo en el camino de voz en vivo. | Casos de prueba de escalación (HAWKEYE); verificación en CI de que el LLM generativo no está en el camino de voz (§3.8.5); transferencia entrega transcripción+intent+urgencia. | F1/F4/F5    |
| **CE-54** | **Barge-in funcional:** la interrupción del usuario **corta** la síntesis TTS en curso de forma medible y devuelve el turno a STT.                                | Test de barge-in con audio simulado que interrumpe a mitad de síntesis; medición del tiempo de corte.                                                                        | F4          |
| **CE-55** | **Cero egress + persistencia + no regresión:** cero audio/inferencia/**TTS** a terceros (`check-externos-backend.sh` verde + captura de red); la llamada en vivo queda en `call`/`call_transcript` y aparece en la ficha de #4 al colgar; #1-#4 siguen en verde; retención aplicada; `docker compose up` reproducible sin internet. | `check-externos-backend.sh` verde; prueba de egress vacío desde voz/IA; e2e de persistencia de llamada en vivo; suites #1-#4 verdes; cobertura backend ≥ 80%.                 | F5/F7       |

> Transversales heredados: **aprobación explícita del Lead**; CHECKPOINTS C2 (borrado lógico) / C3 (secretos) /
> C4 (criterios verificables) / C6 (cambio sensible → notificación Telegram) / C8 (prompt registrado en
> `prompt-lab/PROMPT-OPTIMIZADO-FASE5.md`).

---

## 8. Mapa preliminar de SPECs propuestas (SOLO el mapa — NO son las specs)

> Continúa la numeración desde `specs.json` (`next_spec: 44`). Se crearán únicamente tras "APROBADO PLAN-005".
> Cada SPEC llevará criterios verificables (C4). `next_spec`/`next_adr` NO se tocan hasta crear las specs reales.

- **SPEC-044** — Infra de voz en vivo + GPU compartida priorizada + auditoría de egress: `voice_stt`/`voice_tts`/
  NLU en `ia_internal` sin egress; `voice_gateway` en `app` con allowlist al host del PBX de media; **mecanismo de
  prioridad de GPU** frente al `stt_worker` batch de #4 (pausa/despriorización + fracción de VRAM reservada);
  pesos STT liviano + Piper + banco de audios pregrabados por volumen; `check-externos-backend.sh` extendido (TTS
  de terceros prohibido); `.env.example`; reverse proxy TLS/WSS (F0).
- **SPEC-045** — Catálogo cerrado de intents + NLU determinista (sin LLM generativo en vivo): artefacto versionado
  del catálogo (intents/ejemplos/respuestas ancladas a RAG o pregrabadas/acción), NLU por embeddings/pgvector
  (reutiliza SPEC-014..017) con umbral de confianza, intent reservado "hablar con una persona" (F1).
- **SPEC-046** — Conector de media en vivo (extiende SPEC-037): `voice_gateway` con sesión SIP/media, stream
  RTP/WebSocket bidireccional acotado al PBX, declaración de voz sintética al inicio (ADR-012), resolución de
  tenant desde metadatos, sin mapeo → escalación/descarte auditado (F2).
- **SPEC-047** — STT streaming liviano en vivo sobre GPU compartida: `voice_stt` `distil-whisper`/`faster-whisper`
  liviano cuantizado, ventana deslizante, transcripción parcial de baja latencia, prioridad de GPU activa,
  instrumentación de latencia parcial, sin egress (F3).
- **SPEC-048** — Bucle de diálogo (NLU→respuesta de catálogo RAG/pregrabada→TTS) + barge-in: orquestador de turno,
  plantilla anclada a RAG con citas (SPEC-017) o audio pregrabado, TTS Piper **o** modo bajo-cómputo (interfaz
  conmutable), barge-in con cancelación de síntesis, presupuesto de latencia por turno (F4).
- **SPEC-049** — Escalación a humano con contexto + monitor de llamadas en vivo en la SPA (feature-flag):
  escalación obligatoria (fuera de catálogo / sentimiento negativo SPEC-018 / petición explícita / latencia
  sostenida / límite `C`) con transcripción parcial+intent+urgencia; monitor SPA (estado/intent/transferir);
  reutiliza SPEC-020, sin romper #1-#4 (F5).
- **SPEC-050** — Latencia/GPU compartida (THOR) + fijación de `C` + política de degradación/bajo-cómputo:
  medición p95 ≤700 ms bajo concurrencia con el batch en paralelo, fijación empírica de `C` (1-3), verificación
  de prioridad y backlog del batch, activación documentada del modo pregrabado si no se cumple (F6).
- **SPEC-051** — Seguridad del vector voz/TTS + persistencia de la llamada en vivo + retención (reutiliza #4):
  barrido BLACK WIDOW del TTS/voz sintética, `check-externos-backend.sh` verde, egress vacío desde voz/IA,
  persistencia en `call`/`call_transcript` (SPEC-036) al colgar, retención/anonimización (SPEC-041/ADR-009)
  del audio en vivo/transcripción/TTS (F7).
- **SPEC-052** — Documentación, runbook de voz en vivo, **simulador de llamada en vivo** y deploy on-prem:
  integración PBX de media/SIP, modelos STT/TTS, catálogo de intents, `C`, prioridad de GPU, política de
  degradación; OpenAPI/AsyncAPI del gateway; simulador sin PBX real; deploy (F8).

> Total preliminar: **9 SPECs (SPEC-044..SPEC-052)** → `next_spec` pasaría a **53** al crearlas (no ahora).

---

## 9. Entregables finales del Entregable #5

- `voice_gateway` (sesión SIP/media, extiende el conector PBX de SPEC-037 de grabación a stream en vivo) en `app`
  con egress acotado al host del PBX de media, ejecutable con `docker compose up`.
- `voice_stt` (STT streaming liviano) + `voice_tts` (Piper local + banco de audios pregrabados) + NLU de catálogo,
  **sin egress**, en `ia_internal`.
- **Catálogo cerrado de intents pre-aprobado** versionado + NLU determinista por embeddings (sin LLM generativo en
  el camino de voz en vivo).
- **Mecanismo de GPU compartida priorizada** (voz gana al batch de #4; batch reanuda al liberarse), con `C`
  fijado empíricamente por THOR.
- Bucle de diálogo con **barge-in** + **escalación obligatoria a humano** con contexto (transcripción+intent+urgencia).
- **Declaración de voz sintética** al inicio de cada llamada; **TTS 100% local**, nunca a terceros.
- SPA con **monitor de llamadas en vivo** (transferir/tomar control) tras feature-flag, sin romper #1-#4.
- Persistencia de la llamada en vivo en `call`/`call_transcript` (SPEC-036) visible en la ficha de #4 al colgar;
  retención/anonimización (SPEC-041/ADR-009) aplicada.
- `check-externos-backend.sh` evolucionado (TTS de terceros prohibido) en verde en CI.
- **Evidencia auditable:** cero audio/inferencia/TTS a terceros; egress público nulo (o solo al host del PBX de
  media); prioridad de GPU verificada + backlog del batch cuantificado; latencia p95 (≤700 ms o degradación
  documentada + modo bajo-cómputo); escalación con contexto; aislamiento cross-tenant.
- OpenAPI/AsyncAPI del gateway + **simulador de llamada en vivo** verificable en local; runbook de voz en vivo con
  placeholders, sin secretos.
- **ADR-011** (GPU compartida priorizada + egress acotado del PBX de media en vivo) y **ADR-012** (TTS 100% local
  + declaración de voz sintética) aceptados.

## 10. Definition of Done (Entregable #5)

1. CE-51..CE-55 cumplidos y evidenciados.
2. **Control humano (P1):** el VoiceBot opera SOLO dentro del catálogo cerrado; **ningún** LLM generativo en el
   camino de voz en vivo (verificado en CI); escalación obligatoria con contexto en ≤ N s ante fuera de
   catálogo / baja confianza / sentimiento negativo / petición explícita.
3. **STT y TTS 100% locales:** llamada en vivo transcrita por `voice_stt` local y respondida por `voice_tts`
   local; **cero** STT/TTS de terceros; captura de red + `check-externos-backend.sh` verde.
4. **GPU compartida priorizada (P3):** con ≥1 llamada en vivo, la voz gana GPU y el batch de #4 se despriorza/pausa
   y **reanuda**; `C` fijado empíricamente; backlog del batch inducido cuantificado y documentado.
5. **Latencia:** p95 end-to-end **≤ 700 ms** bajo `C` compartiendo GPU, **o degradación documentada + modo
   bajo-cómputo pregrabado activado** (nunca una experiencia de voz rota).
6. **Barge-in** funcional y medible; el usuario puede interrumpir la síntesis en cualquier momento.
7. **Voz sintética declarada** al inicio de cada llamada (ADR-012).
8. **Cero egress** de audio/inferencia/TTS: voz/IA sin ruta a internet ni al PBX (prueba de egress vacío); si el
   PBX de media es externo, egress público **solo** al host del PBX desde `voice_gateway`.
9. **Aislamiento multi-tenant** probado con rol app no-superusuario (ADR-008): test cross-tenant que **falla** por
   RLS; sin mapeo → escalación/descarte auditado.
10. **Persistencia + retención:** la llamada en vivo queda en `call`/`call_transcript` (SPEC-036) y aparece en la
    ficha de #4 al colgar; retención/anonimización (SPEC-041/ADR-009) aplicada al audio/transcripción/TTS.
11. SPA con **monitor de llamadas en vivo** tras feature-flag **sin romper** #1-#4; cobertura backend **≥ 80%**;
    `docker compose up` reproducible sin internet de inferencia; el batch de #4 sigue en verde.
12. Secretos fuera del código/logs (C3); borrado lógico (C2); TLS/WSS activo en el gateway.
13. Runbook + OpenAPI/AsyncAPI + simulador de llamada en vivo entregados; **ADR-011/012** aceptados; deploy on-prem
    con **aprobación del Lead** (cambio sensible → notificación Telegram, C6).
14. **Aprobación explícita del Lead**. Ninguna SPEC se cierra sin cumplir los CHECKPOINTS aplicables (C2/C3/C4/C6/C8).

---

## 11. ADRs recomendados (a abrir desde ADR-011)

- **ADR-011 — GPU COMPARTIDA priorizada para el VoiceBot en vivo + egress acotado del PBX de media en vivo.**
  Decide: (a) el VoiceBot en vivo **comparte** la GPU física con el `stt_worker` batch de #4 (NO hay GPU
  dedicada — decisión del Lead P3), con **prioridad de la voz en vivo** sobre el batch (pausa/despriorización del
  batch + fracción de VRAM reservada para la voz); el batch reanuda al liberarse la voz; **límite duro `C`** de
  llamadas concurrentes, fijado empíricamente por THOR; **degradación documentada + modo bajo-cómputo pregrabado**
  si <700 ms no se cumple; (b) el transporte de **media/SIP en vivo** al PBX es egress acotado (transporte, no
  inferencia): permitido **solo** desde `voice_gateway` en `app`, **solo** al host del PBX de media (allowlist por
  ruta, patrón ADR-006/010); voz/STT/TTS/IA jamás obtienen esa ruta. Si el PBX es on-prem, sin egress nuevo.
  Alternativas: GPU dedicada (descartada por el Lead, sin presupuesto); compartir sin prioridad (descartada:
  ambos degradan); LLM generativo en vivo (descartada por P1). Reafirma ADR-005/009.
- **ADR-012 — TTS 100% local (Piper/Coqui) + declaración obligatoria de voz sintética.** Decide: (a) la síntesis
  de voz es **self-hosted** (Piper es-CO, o Coqui como alternativa evaluada por THOR); **TTS de terceros
  PROHIBIDO** (Google TTS, AWS Polly, ElevenLabs, Azure Speech, OpenAI TTS…), mismo criterio que STT en ADR-009,
  verificado en `check-externos-backend.sh`; el `voice_tts` vive en `ia_internal internal:true`, sin egress;
  (b) al inicio de **cada** llamada se **declara que el interlocutor es un asistente virtual** (anti-deepfake,
  buena práctica regulatoria Ley 1581 / normativa de IA conversacional), se aplique o no obligatoriamente por ley;
  (c) preferencia por **no persistir** el audio TTS (solo la transcripción textual); si se persiste, aplica la
  retención/anonimización de SPEC-041/ADR-009. Alternativas: TTS en la nube (descartada: voz a un tercero, rompe
  SENSIBLE); no declarar voz sintética (descartada: riesgo legal/reputacional). Extiende ADR-009 al vector TTS.

---

## 12. PREGUNTAS ABIERTAS AL LEAD — con supuesto por defecto (P1 y P3 YA resueltas, no se re-preguntan)

> P1 (control humano = catálogo cerrado + escalación) y P3 (GPU compartida, sin GPU dedicada) están **resueltas y
> son vinculantes** (§0, `prompt-lab/PROMPT-OPTIMIZADO-FASE5.md` §8). Estas son preguntas **genuinamente nuevas**.
> Si el Lead no responde, el PLAN-005 procede con el **supuesto por defecto** indicado.

1. **P-C (catálogo inicial de intents concretos):** ¿qué intents concretos quieres en el catálogo cerrado del
   piloto? **Supuesto por defecto:** el mínimo de 4 — (i) consulta de estado de pedido/cita, (ii)
   agendar/reagendar/cancelar cita, (iii) FAQ desde la base de conocimiento RAG existente, (iv) intent reservado
   "hablar con una persona" (escalación) siempre disponible; ampliable tras validar en producción. Todo lo demás
   → transferencia a humano.

2. **P-K (límite de concurrencia `C` del piloto sobre GPU compartida):** dado que NO hay GPU dedicada (P3), el
   piloto de 5-10 concurrentes ya no es realista. ¿aceptas un límite duro conservador validado empíricamente?
   **Supuesto por defecto:** `C = 1-3` llamadas en vivo simultáneas, **fijado por THOR** en F6 midiendo con el
   batch de #4 en paralelo; la llamada `C+1` recibe IVR pregrabado mínimo + escalación, nunca se degrada una
   llamada activa.

3. **P-D (impacto aceptado en el SLA del batch de #4):** la prioridad de la voz en vivo hará que el `stt_worker`
   batch de #4 se despriorze/pause mientras haya llamadas activas, aumentando su backlog temporalmente. ¿aceptas
   ese impacto como coste de la GPU compartida? **Supuesto por defecto:** sí, se acepta y se **documenta/cuantifica**
   el backlog inducido; el batch es tolerante a cola por diseño (#4) y reanuda al liberarse la voz. Si el Lead
   fija un SLA duro para el batch, se ajusta `C` a la baja.

4. **P-L (declaración legal de voz sintética):** ¿el marco legal aplicable (Colombia, Ley 1581 / normativa de IA
   conversacional) exige declarar explícitamente al usuario que habla con un bot? **Supuesto por defecto:** sí,
   se declara siempre al inicio de la llamada (ADR-012), independientemente de si la ley lo exige explícitamente
   (buena práctica anti-deepfake + mitigación de riesgo reputacional).

5. **P-M (PBX de media en vivo: on-prem vs externo, y protocolo):** ¿el audio en vivo llega de un PBX **on-prem**
   (Asterisk/FreeSWITCH, sin egress nuevo) o de un **proveedor externo** (transporte acotado, ADR-011)? ¿por
   **SIP/RTP** o **WebSocket de media**? **Supuesto por defecto:** **PBX on-prem preferido** (sin egress nuevo);
   si es externo se aplica egress acotado (allowlist al host del PBX de media, ADR-011); si aún no hay PBX, se
   entrega el gateway + **simulador de llamada en vivo** verificable en local.

6. **P-N (persistencia del audio TTS de salida):** ¿se debe persistir el audio sintetizado (para auditoría/ficha)
   o basta con la transcripción textual? **Supuesto por defecto:** **no persistir** el audio TTS (menor superficie
   SENSIBLE); se persiste la transcripción textual de lo que dijo el bot; si se persiste el audio, aplica la
   retención/anonimización de SPEC-041/ADR-009.

---

> **Siguiente paso:** IRON MAN presenta este PLAN-005 al Lead. El Lead debe responder **"APROBADO PLAN-005"**
> (o "Ajusta PLAN-005: …") antes de que DOCTOR STRANGE genere las SPEC-044..SPEC-052 y los ADR-011/012.
> Cumple CHECKPOINT C8 (prompt registrado en `prompt-lab/PROMPT-OPTIMIZADO-FASE5.md`). Las dos restricciones
> duras del Lead (P1 catálogo cerrado, P3 GPU compartida) ya están incorporadas y **no** se re-preguntan.
