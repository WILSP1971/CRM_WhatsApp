# PROMPT OPTIMIZADO — Entregable #5 (redefinido): Notas de voz asíncronas en WhatsApp

> Autor: 🧠 XAVIER (Professor X) — Estratega de Prompts (Nivel 1) · skill `optimizar-prompt`
> Fecha: 2026-09-25 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo`) — el audio de nota de voz es dato personal; se hereda el mismo
> criterio de audio de llamadas del Entregable #4 (posible PHI, cifrado en reposo, retención).
> Marco aplicado: **C.R.A.F.T.** (Contexto · Rol · Acción · Formato · Tests)
> Precedente directo: **PLAN-005 (VoiceBot conversacional en vivo por teléfono) queda ARCHIVADO**
> (`.swarm/specs.json`, `estado: PAUSADA`) — la máquina de producción **no tiene GPU**, lo que hace inviable
> el presupuesto de latencia <700ms de un diálogo en vivo. SPEC-044 (infra F0) quedó implementada/verificada y
> se conserva por si se retoma en el futuro con GPU disponible; SPEC-045..052 quedaron `ARCHIVADA` sin
> implementar. Este documento **reemplaza** el alcance del Entregable #5 con algo mucho más simple.
> Contadores vigentes (`.swarm/specs.json`): `next_plan: 6`, `next_spec: 53`, `next_adr: 13`.
> Destino: este prompt alimenta a 🔮 DOCTOR STRANGE para el **PLAN-006** (NO genera specs por sí mismo).

---

## 0. Resumen del encargo (una frase)

Extender el canal WhatsApp (Entregable #3, ya real) para que **reciba y transcriba notas de voz** del
cliente reutilizando el pipeline STT + enriquecimiento IA ya construido (Entregable #4, batch, sin presión de
latencia), respondiendo por el mismo hilo de chat con **texto** (human-in-the-loop ya existente) — sin
Instagram, sin GPU, sin diálogo en vivo.

---

## 1. Por qué este alcance es de bajo riesgo y alta reutilización

A diferencia de PLAN-005 (que necesitaba GPU dedicada/compartida, presupuesto de latencia <700ms, un nuevo
mecanismo de control humano, y un conector SIP/PBX en vivo), esto es una **extensión natural de dos
Entregables ya construidos y verificados**, no un producto nuevo:

1. **El canal ya existe** (Entregable #3): webhook, auth, envío/recepción, `Conversation`/`Message`, RLS
   multi-tenant. Solo falta que `inbound_parser.py` deje de descartar el tipo `audio` como placeholder.
2. **El pipeline de transcripción+enriquecimiento ya existe** (Entregable #4): `stt_worker` transcribe
   audio con `faster-whisper` 100% local, y ya dispara sentimiento + resumen + borrador RAG con ≥3 citas +
   human-in-the-loop (SPEC-039) — reutilizable **tal cual**, sin GPU dedicada, ya corre en batch/CPU-tolerante.
3. **Sin restricción de latencia**: al ser asíncrono (como cualquier mensaje de WhatsApp), no hay presupuesto
   de tiempo real que cumplir — el mismo mecanismo de cola Redis + worker que ya tolera cola perfectamente.
4. **El human-in-the-loop no necesita rediseño** (a diferencia de PLAN-005): el agente aprueba el borrador de
   texto antes de enviarlo, exactamente igual que ya hace con mensajes de texto normales.

**Lo único genuinamente nuevo**: (a) descargar el audio desde la Graph API de Meta (hoy `graph_client.py` solo
envía, no descarga), y (b) el "enganche" entre el mensaje de WhatsApp recibido y el pipeline STT existente.

---

## 2. Ambigüedades detectadas y SUPUESTOS EXPLÍCITOS (⚠️ marcados)

- **⚠️ SUP-61 (modelo de datos — la pregunta más importante):** la nota de voz **NO se modela** como `call`/
  `call_transcript` (esas entidades representan una llamada telefónica: `call_id`, dirección, duración de
  sesión — un concepto distinto). Se modela como una **extensión del `Message` ya existente** dentro de la
  `Conversation` de WhatsApp real: el `Message` recibido tiene `tipo="audio"` (o el enum que ya use el proyecto
  para tipos de mensaje), un `audio_ref` opcional (mismo patrón de referencia opaca a almacén cifrado que
  `call.audio_ref`, SPEC-035/037), y su `contenido` es la **transcripción** (texto), quedando indistinguible
  para el resto del pipeline (sentimiento/RAG/borrador) de un mensaje de texto normal una vez transcrito. Esto
  es la inversa exacta de lo que hizo SPEC-039 (que materializó una llamada como un `Message` sintético para
  reutilizar el pipeline) — aquí el `Message` ya es real, solo se le añade transcripción.
- **⚠️ SUP-62 (respuesta SOLO en texto, no audio, en este slice):** el Entregable #5 responde **siempre con
  texto** por el mismo mecanismo de borrador ya existente (SPEC-017/019). **NO se genera audio de respuesta
  (TTS)** en este slice — no por imposibilidad técnica (TTS local sin restricción de latencia sí sería viable
  en CPU), sino porque introduce una pregunta de diseño no trivial (¿cómo aprueba un agente humano un audio
  antes de enviarlo? ¿escucha el clip, o aprueba solo la transcripción de lo que diría el audio?) que no está
  resuelta y no es necesaria para entregar el valor central (que el cliente pueda mandar una nota de voz y
  reciba una respuesta con la misma calidad que si hubiera escrito texto). TTS de respuesta queda como
  **extensión futura explícita**, no como parte de este slice. Ver pregunta abierta P2.
- **⚠️ SUP-63 (límite de duración de la nota de voz):** se asume un límite configurable (por defecto, p. ej.
  10 minutos, mismo orden de magnitud que una llamada corta del Entregable #4) — una nota de voz que lo supere
  se descarta con una respuesta automática amable ("nota muy larga, por favor resume o escribe tu consulta") en
  vez de intentar transcribir contenido desproporcionado. Esto es distinto de "falla silenciosamente": el
  cliente recibe una respuesta clara.
- **⚠️ SUP-64 (descarga de media — pieza nueva, egress ya permitido):** se añade una función de descarga a
  `graph_client.py` (GET a `graph.facebook.com/{media-id}` para obtener la URL temporal, luego GET a esa URL
  con el token de acceso) — el host sigue siendo `graph.facebook.com`, ya permitido dentro de
  `app/integrations/whatsapp/` por el guardarraíl existente (ADR-006, SPEC-024) — **sin egress nuevo**, solo
  una función nueva en un módulo ya autorizado.
- **⚠️ SUP-65 (retención/cifrado del audio — reutiliza, no reinventa):** el audio de la nota de voz se cifra en
  reposo y se retiene según la MISMA política configurable ya construida en SPEC-041 (Entregable #4),
  extendida para cubrir también audio de mensajería (no solo de llamadas) — mismo `audio_store.py`, mismo job
  de purga, sin política nueva paralela.
- **⚠️ SUP-66 (Instagram, explícitamente fuera):** Instagram NO existe como canal en el proyecto — añadirlo
  sería del mismo tamaño que reconstruir el Entregable #3 completo para una plataforma distinta (webhook, auth,
  Graph API propia). Queda **completamente fuera** de este Entregable #5; es una decisión de negocio aparte, no
  una fase de este plan.
- **⚠️ SUP-67 (idempotencia):** reutiliza el mismo mecanismo de `wamid` (ADR-007) ya usado para deduplicar
  mensajes de WhatsApp — una nota de voz reentregada no debe re-transcribirse ni duplicar el enriquecimiento.

---

## 3. PROMPT PROFESIONAL (para DOCTOR STRANGE → PLAN-006)

### 3.1 Objetivo (Acción — verbo único y medible)

**Extender** el canal WhatsApp para que **reciba, descargue y transcriba** notas de voz del cliente
reutilizando 100% el pipeline STT + enriquecimiento del Entregable #4, y **responda con texto** por el
mecanismo de borrador human-in-the-loop ya existente — sin GPU, sin latencia dura, sin Instagram.

### 3.2 Rol (quién resuelve)

- Arquitectura/PLAN/SPECs → 🔮 DOCTOR STRANGE.
- Backend (descarga de media, enganche al pipeline STT) → 🐆 BLACK PANTHER + 🛡️ CAPTAIN AMERICA.
- Seguridad (audio como dato personal, retención, egress) → 🕷️ BLACK WIDOW.
- Pruebas → 🏹 HAWKEYE.
- (Frontend: probablemente sin cambios — la bandeja unificada ya muestra `Message.contenido`; a confirmar con
  DAREDEVIL si la ficha de conversación necesita alguna indicación visual de "mensaje transcrito de audio".)

### 3.3 Alcance IN

1. **Descarga de media de WhatsApp**: nueva función en `app/integrations/whatsapp/graph_client.py` (o módulo
   hermano) que resuelve la URL temporal del media y descarga el binario, dentro del host ya permitido
   `graph.facebook.com`.
2. **`inbound_parser.py` extendido**: reconoce `type=="audio"` (hoy lo descarta como placeholder), extrae
   `media_id`/duración/metadatos.
3. **Almacenamiento cifrado**: el audio descargado se guarda en el mismo almacén cifrado on-prem de SPEC-035
   (reutilizado, no reinventado), con `audio_ref` en el `Message`.
4. **Encolado al pipeline STT existente**: el mensaje de audio se encola en `stt:jobs` (mismo contrato de
   SPEC-037/038), el `stt_worker` transcribe y persiste el texto en `Message.contenido`.
5. **Enriquecimiento reutilizado sin cambios**: sentimiento (SPEC-018), resumen si aplica, borrador RAG con
   ≥3 citas (SPEC-017), human-in-the-loop (SPEC-019) — el mismo camino que ya sigue cualquier mensaje de
   WhatsApp de texto.
6. **Límite de duración configurable** con descarte amable (SUP-63).
7. **Retención/cifrado extendido** (SUP-65) para audio de mensajería, reutilizando SPEC-041.
8. **Idempotencia por `wamid`** (SUP-67), reutilizando ADR-007.

### 3.4 Alcance OUT

- Respuesta en audio (TTS) — SUP-62, extensión futura.
- Canal Instagram — SUP-66, decisión de negocio aparte.
- Cualquier forma de diálogo en vivo/streaming — ya descartado por falta de GPU (motivo original de esta
  redefinición).
- El VoiceBot telefónico de PLAN-005 (archivado, no se retoma aquí).

### 3.5 Requisitos NO funcionales

- RNF-61 Audio de nota de voz 100% local (STT, sin terceros) — mismo invariante de ADR-009, extendido a
  mensajería.
- RNF-62 Sin egress nuevo: la descarga de media usa el host ya permitido `graph.facebook.com` dentro del
  módulo ya autorizado.
- RNF-63 Multi-tenant RLS y borrado lógico heredados sin cambios.
- RNF-64 Sin regresión: mensajes de texto de WhatsApp siguen funcionando exactamente igual.

### 3.6 RESTRICCIONES DURAS

1. **STT 100% local**, sin excepción (hereda ADR-009).
2. **Solo texto de respuesta** en este slice (SUP-62) — no generar audio de salida.
3. **Sin egress nuevo** — la descarga de media vive dentro de `app/integrations/whatsapp/`, mismo host ya
   permitido.
4. **Human-in-the-loop intacto** — ningún borrador se envía sin aprobación humana, sea el mensaje original de
   texto o de audio transcrito.
5. **No romper** Entregables #1-#4: suites verdes, migraciones aditivas.

---

## 4. CRITERIOS DE ÉXITO MEDIBLES (orientativos)

- **CE-61** Una nota de voz ficticia enviada por WhatsApp se descarga, transcribe (segmentos no necesarios,
  solo texto), y aparece como `Message.contenido` en la conversación real.
- **CE-62** Recibe sentimiento + resumen/borrador RAG ≥3 citas, sin inferencia externa (cero egress nuevo).
- **CE-63** Reentrega del mismo `wamid` no duplica transcripción/enriquecimiento.
- **CE-64** Nota de voz que excede el límite configurado → respuesta automática de descarte, no error silencioso.
- **CE-65** Suites #1-#4 sin regresión; cobertura del código nuevo ≥80%.

---

## 5. PREGUNTAS ABIERTAS AL LEAD (2) — con supuesto por defecto

1. **P1 (límite de duración, SUP-63):** ¿qué límite máximo de duración de nota de voz prefieres?
   **Supuesto por defecto:** 10 minutos, configurable por env.
2. **P2 (respuesta en audio, SUP-62):** ¿confirmas que este Entregable #5 responde SOLO en texto (recomendado,
   sin ambigüedad de diseño de aprobación de audio), dejando TTS de respuesta como posible fase futura?
   **Supuesto por defecto:** sí, solo texto en este slice.

---

> **Siguiente paso:** 🔮 DOCTOR STRANGE toma este prompt y genera el **PLAN-006** en `.swarm/PLAN-006.md`,
> que IRON MAN presentará al Lead. **NO se crean specs** hasta "APROBADO PLAN-006", y **no se implementa**
> hasta "APROBADO SPEC-0XX". CHECKPOINT C8: prompt registrado en
> `prompt-lab/PROMPT-OPTIMIZADO-FASE5-NOTAS-VOZ-WHATSAPP.md`.
