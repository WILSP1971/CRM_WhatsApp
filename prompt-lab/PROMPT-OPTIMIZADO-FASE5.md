# PROMPT OPTIMIZADO — Fase 5 "OmniCore AI" (Entregable #5): VoiceBot conversacional EN VIVO (STT streaming + TTS + IVR + barge-in)

> Autor: 🧠 XAVIER (Professor X) — Estratega de Prompts (Nivel 1) · skill `optimizar-prompt`
> Fecha: 2026-09-21 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo`) — el **audio de llamadas EN VIVO es dato personal** (posible PHI); además del riesgo ya conocido del Entregable #4, aquí se suma la **voz sintética hablando en nombre de la empresa en tiempo real**.
> Marco aplicado: **C.R.A.F.T.** (Contexto · Rol · Acción · Formato · Tests)
> Precedentes: Entregable #1 (maqueta SPA, SPEC-006 VoiceBot visual) **COMPLETO**; Entregable #2 (backend + IA local, PLAN-002) y Entregable #3 (WhatsApp, PLAN-003) **EN_VERIFICACION**; **Entregable #4 (PLAN-004, SPEC-035..043) COMPLETO** — transcripción/análisis asíncrono de llamadas, STT local batch, retención/anonimización de audio, ficha de llamada real en la SPA, CI con verificación RLS/idempotencia/egress.
> Contadores vigentes (`.swarm/specs.json`): `next_plan: 5`, `next_spec: 44`, `next_adr: 11`.
> Destino: este prompt alimenta a 🔮 DOCTOR STRANGE para el **PLAN-005** (NO genera specs por sí mismo).

---

## 0. Resumen del encargo (una frase)

Diseñar el **Entregable #5** como el **VoiceBot conversacional EN VIVO** que el Entregable #4 dejó explícitamente
fuera de alcance: **STT streaming + diálogo + TTS local + IVR + barge-in**, respondiendo llamadas en tiempo real
**sin romper el invariante human-in-the-loop** ya consolidado en #2/#3/#4, ni el invariante SENSIBLE de cero
egress de audio/inferencia.

---

## 1. Por qué esto NO es una extensión trivial de PLAN-004 (el riesgo central)

PLAN-004 (§2, OUT) ya identificó y difirió esto explícitamente, con razones que **siguen vigentes y se agravan**:

1. **Latencia dura, no tolerante a cola.** El Entregable #4 es batch: si el `stt_worker` se atrasa, el mensaje
   simplemente tarda más en aparecer en la ficha. Un VoiceBot en vivo tiene un **presupuesto de latencia
   percibida <700 ms round-trip** (STT parcial + decisión/LLM + TTS + red) — un pico de GPU no es "más lento",
   es una **llamada rota** para un humano al otro lado.
2. **Contradice literalmente el mecanismo actual de human-in-the-loop (SPEC-019).** Hoy el invariante es "nada
   se envía al cliente sin que un agente humano apruebe el borrador". Un bot que **habla en vivo** no puede
   pausar cada frase a esperar aprobación humana — el mecanismo de aprobación pieza-por-pieza que funciona para
   texto/borradores **no es trasladable tal cual** a voz en tiempo real. Esto exige un **rediseño explícito** del
   punto de control humano (ver §2 más abajo), no asumir que "ya lo tenemos resuelto".
3. **GPU en línea crítica 24/7**, no picos tolerados: el batch de #4 escala horizontalmente sin drama (N workers,
   cola Redis); un VoiceBot en vivo necesita VRAM **reservada y caliente** por cada llamada concurrente.
4. **Superficie SENSIBLE nueva:** además de audio de entrada (ya cubierto por ADR-009), aparece **voz sintética
   de salida (TTS)** — un vector nuevo de riesgo (voz clonada/falsificable si se usa mal, tono/contenido que la
   empresa "dice" sin revisión humana previa).

**Conclusión de XAVIER:** este NO es "Entregable #4 pero con streaming". Es un rediseño de la interacción
humano-IA para el canal de voz, con presupuesto de latencia y un nuevo mecanismo de control (no aprobación
turno-a-turno). PLAN-005 debe decidir esto explícitamente, no heredarlo por inercia de #4.

---

## 2. Ambigüedades detectadas y SUPUESTOS EXPLÍCITOS (⚠️ marcados)

- **⚠️ SUP-51 (el problema central — CÓMO se preserva control humano en voz en vivo):** dado que la aprobación
  turno-a-turno (SPEC-019) es incompatible con latencia conversacional, se propone un modelo de **"guardrails
  antes, no aprobación durante"**: el VoiceBot opera SOLO dentro de un **catálogo cerrado de intents/flujos
  pre-aprobados por un humano** (IVR inteligente: consulta de estado, agendar/reagendar cita, FAQ desde la base
  de conocimiento ya indexada por RAG, enrutamiento a cola humana) — **NUNCA** genera respuesta libre de un LLM
  sin acotar. Cualquier intent fuera del catálogo, o cualquier señal de frustración/urgencia (sentimiento
  negativo ya disponible de SPEC-018), **transfiere a un agente humano** en caliente. El "human-in-the-loop" se
  traslada de "aprobar cada frase" a "aprobar el catálogo de flujos permitidos + escalación obligatoria fuera de
  él" — más parecido a un IVR inteligente con NLU que a un LLM conversando libremente. **Esto es la decisión
  arquitectónica más importante del PLAN-005 y requiere confirmación explícita del Lead (§7 P1)**, no es un
  detalle de implementación.
- **⚠️ SUP-52 (TTS 100% local):** Piper o Coqui TTS self-hosted, es-CO o el acento más cercano disponible;
  **ningún** TTS de terceros (Google TTS, AWS Polly, ElevenLabs, Azure Speech, OpenAI TTS quedan PROHIBIDOS,
  mismo criterio que STT en ADR-009). Voz sintética debe declararse como tal al inicio de la llamada (evita
  engaño/deepfake regulatorio).
- **⚠️ SUP-53 (arquitectura de streaming STT):** se asume **WebSocket bidireccional** entre el PBX/gateway de
  media y un servicio de streaming (no HTTP chunk-based, que añade latencia de por sí) — `faster-whisper` en
  modo streaming (ventanas deslizantes) o alternativa optimizada para baja latencia (p. ej. `whisper.cpp`
  streaming, o un modelo más pequeño tipo `distil-whisper` si `large-v3` no cumple el presupuesto de <700ms).
- **⚠️ SUP-54 (barge-in):** el usuario puede interrumpir al bot a mitad de la síntesis TTS; el audio de salida
  se corta y el turno vuelve a STT inmediatamente. Esto exige que TTS/STT corran en el mismo proceso/host de baja
  latencia (no cola batch) y que el pipeline soporte cancelación de síntesis en curso.
- **⚠️ SUP-55 (GPU dedicada, no compartida con el batch de #4):** se asume que el VoiceBot en vivo necesita **su
  propia GPU reservada** (o partición de VRAM garantizada), separada del `stt_worker` batch de #4 — no deben
  competir por el mismo recurso bajo carga, o ambos degradan. Impacto directo en dimensionamiento/costo (§7 P3).
  Si no hay presupuesto para GPU dedicada adicional, el Entregable #5 **no es viable con el presupuesto de
  latencia actual** y debe replantearse el alcance (p. ej. IVR sin diálogo generativo, solo reconocimiento de
  comandos cortos).
- **⚠️ SUP-56 (reutilización de infraestructura de #4):** SÍ se reutiliza: entidades `call`/`call_transcript`
  (la llamada en vivo también queda transcrita y persistida al colgar, igual que hoy), retención/anonimización
  (SPEC-041), RLS multi-tenant, el conector de telefonía/PBX (SPEC-037, extendido para media en vivo no solo
  grabación post-hoc), y el catálogo RAG con citas (SPEC-017) como fuente de las respuestas del IVR inteligente
  — **NO** se reinventa el almacenamiento ni el modelo de datos, solo se añade el bucle de interacción en vivo.
- **⚠️ SUP-57 (alcance de fallback):** si el reconocimiento de intent falla, si el usuario pide explícitamente un
  humano, o si la latencia real supera el umbral de forma sostenida, el bot **transfiere de inmediato** — nunca
  reintenta indefinidamente ni "adivina" fuera de su catálogo cerrado.

---

## 3. PROMPT PROFESIONAL (para DOCTOR STRANGE → PLAN-005)

### 3.1 Objetivo (Acción — verbo único y medible)

**Construir** un VoiceBot conversacional en vivo que **atienda llamadas telefónicas dentro de un catálogo
cerrado de intents pre-aprobados** (IVR inteligente con NLU/RAG, no LLM de dominio abierto), con **STT
streaming + TTS 100% local + barge-in**, **transfiriendo a un agente humano** ante cualquier intent fuera de
catálogo, sentimiento negativo, o petición explícita — preservando el invariante de **cero envío autónomo sin
límites de control humano** (reinterpretado para voz en vivo como catálogo pre-aprobado + escalación
obligatoria) y **cero audio/inferencia/TTS a terceros**.

### 3.2 Rol (quién resuelve)

- Arquitectura/PLAN/SPECs → 🔮 DOCTOR STRANGE (incluye el rediseño del punto de control humano, §2 SUP-51).
- Backend/streaming STT-TTS/telefonía en vivo → 🐆 BLACK PANTHER + 🛡️ CAPTAIN AMERICA.
- UX del flujo de voz (guiones de IVR, mensajes de transferencia, declaración de bot) → 🕸️ SPIDER-MAN.
- Frontend (monitor de llamadas en vivo, transferencia a agente) → 😈 DAREDEVIL.
- Seguridad audio/TTS/egress/control humano → 🕷️ BLACK WIDOW (revisión reforzada dado el riesgo nuevo de TTS).
- Rendimiento/latencia <700ms, dimensionamiento GPU → ⚡ THOR (crítico en esta fase, no opcional como en #4).
- Pruebas/carga concurrente → 🏹 HAWKEYE.

### 3.3 Alcance IN — propuesto para el Entregable #5 (a validar/ajustar por DOCTOR STRANGE)

1. **Catálogo cerrado de intents pre-aprobado** (definido/aprobado por el Lead antes de implementar): consulta
   de estado de pedido/cita, agendar/reagendar/cancelar cita, FAQ desde base de conocimiento RAG existente,
   enrutamiento por intención a cola humana correspondiente.
2. **STT streaming de baja latencia** sobre el audio en vivo del PBX (WebSocket, ventanas deslizantes).
3. **NLU/clasificación de intent** contra el catálogo cerrado (no generación libre de LLM); si no matchea con
   confianza suficiente → transferencia inmediata.
4. **TTS 100% local** (Piper/Coqui) para las respuestas dentro del catálogo; declaración de voz sintética al
   inicio de la llamada.
5. **Barge-in:** cancelación de síntesis en curso ante interrupción del usuario.
6. **Escalación a agente humano:** transferencia con contexto (transcripción parcial + intent detectado) a la
   cola/agente correspondiente; nunca "cuelga" sin opción de humano.
7. **Persistencia de la llamada en vivo:** reutiliza `call`/`call_transcript` de #4; la transcripción completa
   queda disponible en la ficha de llamada al terminar (igual que hoy).
8. **Observabilidad de latencia real:** medición end-to-end (audio-in → STT → NLU → TTS → audio-out) por
   llamada, alertas si se supera el presupuesto.
9. **Auditoría de egress extendida:** TTS de terceros PROHIBIDO en `check-externos-backend.sh`, mismo patrón que
   STT en #4.

### 3.4 Alcance OUT — explícitamente fuera de este Entregable (a confirmar por el Lead)

- **LLM de dominio abierto conversando libremente por voz** (fuera del catálogo cerrado) — riesgo de
  alucinación/compromiso verbal sin revisión humana en tiempo real; posible fase posterior con guardrails más
  fuertes si el Lead lo pide explícitamente.
- **Identificación biométrica de locutor** (verificación de identidad por voz).
- **Multi-idioma** más allá de es-CO (heredado de #4).
- **Emociones acústicas avanzadas** (tono, estrés) más allá del sentimiento textual ya disponible sobre la
  transcripción parcial.

### 3.5 Requisitos NO funcionales críticos (RNF)

- RNF-51 **Latencia end-to-end ≤ 700 ms** percibida (p95) bajo carga concurrente objetivo (a dimensionar, §7 P3).
- RNF-52 **TTS/STT 100% local**, mismo invariante SENSIBLE que #4, extendido a voz de salida.
- RNF-53 **GPU dedicada** para el VoiceBot en vivo, aislada del batch de #4 (o degradación documentada si se
  comparte, con prioridad explícita).
- RNF-54 **Escalación obligatoria** medible: todo intent fuera de catálogo o sentimiento negativo transfiere en
  ≤ N segundos (a definir).
- RNF-55 **Multi-tenant RLS** y retención heredadas sin cambios de #4.

### 3.6 RESTRICCIONES DURAS (invariantes — rompen la build si se violan)

1. **STT/TTS 100% local/self-hosted**, sin excepción — mismo criterio que ADR-009, extendido a TTS.
2. **Catálogo cerrado, no LLM de dominio abierto hablando en vivo** — salvo decisión explícita distinta del
   Lead en §7 P1, documentada como cambio de riesgo aceptado.
3. **Escalación a humano siempre disponible** — el usuario puede pedir un humano en cualquier momento y debe
   obtenerlo.
4. **Egress cero** para audio/inferencia/TTS — mismo guardarraíl `check-externos-backend.sh`, extendido.
5. **No romper** Entregables #1-#4: feature-flag reversible; suites verdes; migraciones aditivas.

---

## 4. STACK LOCAL adicional propuesto (a validar por DOCTOR STRANGE/THOR)

| Componente | Elección propuesta | Justificación |
| ---------- | ------------------- | -------------- |
| **STT streaming** | `faster-whisper` en modo ventana deslizante, o modelo más pequeño (`distil-whisper`/`medium`) si `large-v3` no cumple latencia | Balance precisión/latencia bajo presupuesto <700ms |
| **NLU/intent matching** | Embeddings + clasificador ligero sobre el catálogo cerrado (reutiliza pgvector/RAG de #2), NO LLM generativo abierto | Determinismo, control, evita alucinación en vivo |
| **TTS** | Piper (voz es-CO o más cercana disponible) | Self-hosted, baja latencia, ya evaluado en PLAN-004 §4 como reservado para esta fase |
| **Transporte de media en vivo** | Extiende el conector PBX de SPEC-037 con soporte de stream RTP/WebSocket, no solo grabación post-hoc | Reutiliza integración PBX existente |
| **GPU** | Partición/reserva dedicada, separada del pool batch de #4 | Evita contención bajo carga concurrente |

---

## 5. CRITERIOS DE ÉXITO MEDIBLES (orientativos, a formalizar por DOCTOR STRANGE)

- **CE-51 — Latencia real:** p95 end-to-end ≤700ms bajo N llamadas concurrentes (THOR, carga real).
- **CE-52 — Cero egress de TTS/STT:** mismo patrón que CE-41/42 de #4, extendido a TTS.
- **CE-53 — Escalación funcional:** intent fuera de catálogo → transferencia con contexto en ≤N segundos,
  verificado con casos de prueba.
- **CE-54 — Barge-in funcional:** interrupción del usuario corta la síntesis TTS en curso de forma medible.
- **CE-55 — No regresión:** #1-#4 siguen en verde; la ficha de llamada de #4 muestra correctamente las llamadas
  en vivo una vez terminadas.

---

## 6. PREGUNTAS ABIERTAS AL LEAD (5) — el Entregable #5 NO debería arrancar sin resolver P1 y P3

1. **⚠️ P1 (CRÍTICA, bloqueante) — Modelo de control humano para voz en vivo (SUP-51):** ¿apruebas el modelo de
   **"catálogo cerrado de intents pre-aprobado + escalación obligatoria fuera de él"** como la reinterpretación
   del human-in-the-loop para voz en vivo, o prefieres una alternativa (p. ej. NO autorizar diálogo generativo en
   vivo en absoluto por ahora, y limitar el Entregable #5 a un IVR de comandos cortos sin síntesis de respuestas
   abiertas)? **Sin supuesto por defecto seguro aquí** — esta decisión define el riesgo regulatorio/reputacional
   de toda la fase y XAVIER no la asume unilateralmente.
2. **P2 (catálogo inicial):** ¿qué intents concretos quieres en el catálogo cerrado del piloto (consulta de
   estado, agendar cita, FAQ, otros)? **Supuesto por defecto:** el mínimo de 4 listados en §3.3.1, ampliable
   después de validar en producción.
3. **⚠️ P3 (CRÍTICA, bloqueante) — Presupuesto de GPU dedicada:** ¿hay presupuesto/infraestructura para una GPU
   reservada adicional (separada del batch de #4) para latencia en vivo? Si la respuesta es no, el alcance debe
   reducirse (§1 punto 3). **Sin supuesto por defecto** — es una decisión de inversión, no técnica.
4. **P4 (volumen/concurrencia objetivo):** ¿cuántas llamadas concurrentes en vivo debe soportar el piloto?
   **Supuesto por defecto:** escala piloto, 5-10 llamadas concurrentes.
5. **P5 (voz sintética — declaración legal/regulatoria):** ¿el marco legal aplicable (Colombia, Ley 1581 /
   eventual normativa de IA conversacional) exige una declaración explícita al usuario de que habla con un bot?
   **Supuesto por defecto:** sí, se declara siempre al inicio de la llamada, independiente de si la ley lo exige
   explícitamente (buena práctica + mitigación de riesgo reputacional).

---

> **Siguiente paso:** 🔮 DOCTOR STRANGE toma este prompt y genera el **PLAN-005** en `.swarm/PLAN-005.md`
> (alcance IN/OUT, fases, dependencias, riesgos, criterios), que IRON MAN presentará al Lead. **NO se crean
> specs** hasta "APROBADO PLAN-005", y **no se implementa** hasta "APROBADO SPEC-0XX". CHECKPOINT C8: prompt
> registrado en `prompt-lab/PROMPT-OPTIMIZADO-FASE5.md`.
>
> **Nota de XAVIER:** a diferencia de PLAN-004 (donde todas las preguntas abiertas tenían un supuesto por
> defecto seguro para no bloquear), en esta fase las preguntas **P1 y P3 no tienen supuesto por defecto** — son
> decisiones de riesgo/inversión que corresponden exclusivamente al Lead. Recomiendo que DOCTOR STRANGE presente
> el PLAN-005 con estas dos preguntas destacadas al inicio, antes de que IRON MAN lo lleve al Lead.

---

## 8. RESPUESTAS DEL LEAD (2026-09-21) — vinculantes para el PLAN-005

- **P1 → APROBADO: "Catálogo cerrado + escalación".** El VoiceBot en vivo opera SOLO dentro del catálogo
  cerrado de intents pre-aprobado (§3.3.1); NUNCA LLM de dominio abierto hablando en vivo. Cualquier intent
  fuera de catálogo, sentimiento negativo, o petición explícita de humano → transferencia obligatoria (RNF-54).
  Esto queda como **restricción dura** del PLAN-005 (§3.6 punto 2 deja de ser condicional).

- **P3 → SIN GPU dedicada adicional: hay que COMPARTIR recursos con el batch STT de #4.** Esto invalida el
  supuesto de "GPU dedicada" de RNF-53/SUP-55 y **obliga a reducir el alcance técnico** del PLAN-005 respecto a
  lo orientativo de este prompt. DOCTOR STRANGE debe resolver explícitamente, como parte del PLAN (no como
  detalle de implementación diferido), al menos:
  1. **Modelo STT/TTS más liviano** que `large-v3` (p. ej. `distil-whisper`/`medium` cuantizado, o modelo
     pequeño de Piper) para bajar el costo de VRAM por llamada en vivo.
  2. **Límite duro de llamadas concurrentes en vivo** (mucho menor que un dimensionamiento con GPU dedicada —
     el piloto de 5-10 concurrentes de P4 probablemente ya no es realista compartiendo GPU con el batch; XAVIER
     recomienda que el PLAN-005 proponga un número conservador, p. ej. 1-3 concurrentes, y lo valide con THOR).
  3. **Prioridad/aislamiento de recursos frente al batch de #4:** el VoiceBot en vivo debe tener prioridad sobre
     el `stt_worker` batch cuando compiten por GPU (una llamada en vivo degradada es peor que una transcripción
     batch que tarda unos segundos más) — el PLAN-005 debe definir el mecanismo (colas con prioridad, límite de
     memoria reservada, o pausar el batch mientras hay llamadas en vivo activas).
  4. **Degradación documentada y medible** si aun así no se cumple <700ms bajo el límite de concurrencia
     definido — igual criterio que "RTF ≤1.0 GPU o degradación CPU documentada" de #4, pero aplicado a latencia
     conversacional. Si ni con estas reducciones es viable un presupuesto de latencia conversacional aceptable,
     el PLAN-005 debe decirlo explícitamente y proponer alternativas (p. ej. IVR sin TTS generativo, solo
     mensajes pregrabados/concatenados para las respuestas del catálogo, que es mucho más barato en cómputo).

> Con esto, XAVIER considera el prompt para PLAN-005 completo y las dos preguntas bloqueantes resueltas.
> DOCTOR STRANGE puede proceder a generar `.swarm/PLAN-005.md`.
