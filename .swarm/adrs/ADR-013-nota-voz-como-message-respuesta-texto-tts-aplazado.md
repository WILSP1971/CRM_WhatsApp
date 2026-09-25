# ADR-013 — La nota de voz de WhatsApp se modela como extensión de `Message`/`Conversation` (no como `call`) y la respuesta es solo texto (TTS de salida aplazado)

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-006.md` (§1, §2 OUT, §3.4, §3.5, §11, R-62/R-65/R-66, CE-61..CE-65), `SPEC-053`, `SPEC-055`, `SPEC-056`, `SPEC-057`, `SPEC-058`

- **Estado:** Aceptada
- **Fecha:** 2026-09-25
- **Plan:** PLAN-006

---

## Contexto

El Entregable #5 (redefinido) hace que una **nota de voz enviada por el cliente por WhatsApp** se descargue,
se transcriba con STT **100% local** (`faster-whisper`, mismo motor de SPEC-038) y quede disponible como texto
en la conversación real, para que el agente responda **con human-in-the-loop**. Surgen tres decisiones de
modelado que condicionan todo el slice:

1. **¿Dónde vive la nota de voz en el modelo de datos?** El Entregable #4 ya modela el audio telefónico como
   `call`/`call_transcript` (SPEC-036). La tentación es reutilizar esas tablas. Pero la nota de voz de WhatsApp
   **no es una llamada**: es un mensaje dentro de una `Conversation` de WhatsApp que **ya existe** (Entregable #3),
   idempotente por `wamid` (ADR-007). Reutilizar `call` acoplaría dos conceptos de dominio distintos.

2. **¿Cómo se engancha al `stt_worker` existente sin acoplar la salida a `call`?** El `stt_worker` (SPEC-038)
   hoy persiste en `call_transcript` y materializa un `Message` de voz. Se necesita que la transcripción de una
   nota de voz de WhatsApp acabe en el `Message.contenido` de su `Message(tipo="audio")`, **sin duplicar el
   motor `stt_engine.py`** (coste real de cargar el modelo Whisper dos veces sin GPU) ni romper los jobs `call`
   del Entregable #4 (R-62).

3. **¿La respuesta puede ser en audio (TTS)?** Técnicamente un TTS local en CPU sería viable sin latencia dura,
   pero abre una **pregunta de diseño no resuelta**: ¿cómo aprueba un agente humano un audio antes de enviarlo
   — escucha el clip generado, o aprueba solo la transcripción de lo que diría? El Lead ya confirmó (P2) que en
   este slice la respuesta es **solo texto**.

La clasificación SENSIBLE (`.no-externo`) obliga además a que el audio (dato personal / posible PHI) y toda la
inferencia permanezcan on-prem (ADR-005/ADR-009), y a que la descarga de media use **solo** el host y módulo ya
autorizados para WhatsApp (`graph.facebook.com`, ADR-006/SPEC-024) — **sin egress nuevo**.

---

## Decisión

1. **La nota de voz se modela como extensión aditiva de `Message`/`Conversation`, NO como `call`.** Se añaden a
   `messages` (SPEC-053) columnas **aditivas y nullable**: un discriminador `tipo` que admite `"audio"`, un
   `audio_ref` opcional (referencia opaca al almacén cifrado, mismo patrón que `calls.audio_ref`) y campos
   opcionales de estado (`transcripcion_estado`, `audio_duracion_seg`); y `messages.contenido` pasa a
   **nullable** (un `Message(tipo="audio")` nace sin contenido hasta que el STT lo escribe). **NO se crean ni se
   tocan `call`/`call_transcript`.** La nota de voz vive en la `Conversation` real de WhatsApp bajo la misma RLS
   efectiva (ADR-008).

2. **El `stt_worker` se extiende con un "sink" parametrizado por el campo `destino` del job de `stt:jobs`, en
   vez de crear un worker paralelo.** El contrato de cola (`app/core/stt_queue.py`) se **extiende de forma
   aditiva** con `destino`: `"call:<uuid>"` (comportamiento actual de SPEC-038/039, **por defecto/ausente**) o
   `"message:<uuid>"` (nuevo). Tras transcribir con `stt_engine.py` (**sin tocar el motor**, invocado una sola
   vez, un solo modelo en memoria), el worker despacha al sink: el sink `call` escribe `call_transcript` + crea
   el `Message` de voz + dispara el pipeline IA (**exactamente igual que hoy**); el sink `message` **actualiza**
   el `Message.contenido` del `Message(tipo="audio")` ya existente (SPEC-055) — sin crear `Message` nuevo, sin
   crear `call_transcript`, sin tocar `calls`.

3. **La idempotencia usa el `wamid` existente (ADR-007), sin `call_id` nuevo.** El `Message` de audio ya se
   deduplica por `wamid` en `wa_inbound_worker` (SPEC-027). No se introduce ningún identificador nuevo: guardas
   adicionales (no re-descargar si `audio_ref` existe; no re-transcribir si `contenido`/`transcripcion_estado==ok`)
   completan la idempotencia end-to-end.

4. **La respuesta en este slice es SOLO texto por el borrador human-in-the-loop; el TTS de respuesta se aplaza.**
   La transcripción entra al mismo pipeline que un WhatsApp de texto (SPEC-028/057) y el agente responde con
   texto (SPEC-029). **El TTS de salida NO se implementa en ninguna SPEC de este slice** (P2). Queda como
   extensión futura explícita (posible Entregable #6), sujeta a resolver antes la pregunta de aprobación humana
   de un audio.

5. **Sin egress nuevo.** La descarga del binario (SPEC-054) usa **solo** `graph.facebook.com` desde el módulo
   `app/integrations/whatsapp/` ya autorizado (ADR-006/SPEC-024); el `stt_worker`/IA jamás descarga (recibe del
   almacén cifrado, ADR-009). No se requiere un ADR de egress nuevo (a diferencia de ADR-010 en PLAN-004).

---

## Alternativas consideradas

| Alternativa | Por qué se descartó |
| ----------- | ------------------- |
| **Modelar la nota de voz como `call`/`call_transcript`** (reutilizar el Entregable #4) | `call` modela una **sesión telefónica** — concepto distinto de un mensaje de WhatsApp. Acoplaría dos dominios, obligaría a inventar un `call_id` para algo que ya tiene `wamid`, y sacaría la nota de voz de su `Conversation` real (donde el agente ya trabaja). Duplica dominio sin beneficio. Rechazada a favor de extender `Message`. |
| **Crear un `stt_worker` paralelo dedicado a mensajería** | Duplicaría la carga del modelo Whisper en memoria (coste real sin GPU), la lógica de reintentos, la instrumentación RTF y el punto de aislamiento `ia_internal`; introduce riesgo de divergencia entre dos workers. Rechazada a favor de **un solo worker con sink parametrizado** (DRY, un único punto de aislamiento, un solo modelo). |
| **Modificar `stt_engine.py` para que conozca el destino** | El motor es una **librería pura** (audio → texto/segmentos) y debe seguir siéndolo; acoplarlo al destino rompería su reutilización y aumentaría el riesgo de regresión en #4. Lo que acopla al destino es el **sink de persistencia**, no el motor. El motor **no se toca**. |
| **Introducir un `call_id`/identificador nuevo para la nota de voz** | Innecesario: el `wamid` (ADR-007) ya es la clave de idempotencia estable del mensaje. Añadir otro identificador duplicaría el mecanismo y abriría inconsistencias. Rechazada. |
| **Implementar TTS de respuesta (audio) ya en este slice** | Introduce una ambigüedad de aprobación no resuelta (¿el humano aprueba el clip generado o la transcripción de lo que diría?) que no aporta al valor central (que la nota de voz deje de descartarse y se pueda responder). Se **aplaza** explícitamente (P2). |
| **`destino` obligatorio en el job (sin default)** | Rompería los jobs `call` del Entregable #4 en vuelo/en tests. Se elige `destino` **aditivo con default `call`** para garantizar cero regresión (R-62). |

---

## Consecuencias

**Pros**
- La nota de voz vive donde el agente ya trabaja (la `Conversation` de WhatsApp): a partir de la transcripción es
  **indistinguible de un WhatsApp de texto**, por lo que el enriquecimiento (SPEC-057) reutiliza el pipeline
  existente **sin lógica nueva**.
- Un solo `stt_worker`, un solo modelo en memoria, un solo punto de aislamiento `ia_internal`: sin duplicación.
- Cero egress nuevo, cero identificador nuevo, migración aditiva: mínima superficie de cambio y de riesgo.
- Los jobs `call` del Entregable #4 quedan **intactos** (default `call`, motor sin tocar).

**Cons / mitigaciones**
- El campo `destino` añade una rama en el `stt_worker` (R-62) → default `call` + test de no-regresión que corre
  la suite de SPEC-038 **sin modificar asserts** (SPEC-056/060).
- `messages.contenido` pasa a nullable (relajación de constraint) → los mensajes de texto siguen poblando
  `contenido`; test de no-regresión del canal texto (R-70, SPEC-053/060).
- El TTS aplazado deja una necesidad de negocio abierta → registrada como extensión futura explícita (posible
  Entregable #6), no como deuda oculta.

**Criterio de verificación (objetivo y verificable)**
- La suite de SPEC-038 pasa **sin modificar sus asserts**; un job `call`/sin `destino` sigue escribiendo
  `call_transcript` + `Message` de voz igual (CE-65, SPEC-056/060).
- Un job `destino="message:{id}"` escribe la transcripción en `messages.contenido` y **no** crea
  `call`/`call_transcript` ni `Message` nuevo (SPEC-056/060).
- La nota de voz se descarga solo desde `graph.facebook.com` (módulo WhatsApp); prueba de egress vacío desde
  `stt_worker`/IA; `check-externos-backend.sh` en verde (CE-61/CE-62, SPEC-054/060).
- Idempotencia por `wamid` sin `call_id`: reentrega no re-descarga/re-transcribe/duplica (CE-63, SPEC-055/060).
- **Cero TTS de respuesta** en el slice: verificación de ausencia de audio de salida (SPEC-057/060).

---

## Referencias

- `PLAN-006.md` — §1 (objetivo), §2 OUT (TTS/`call` fuera), §3.4 (sink parametrizado), §3.5 (extensión de
  `Message`), §11 (ADR-013), R-62/R-65/R-66, CE-61..CE-65, DoD.
- `SPEC-053` — Extensión aditiva de `Message` (tipo `audio` + `audio_ref`).
- `SPEC-055` — `inbound_parser` extendido + límite de duración + encolado con `destino="message:{id}"`.
- `SPEC-056` — Enganche STT: sink parametrizado por `destino` (sink `message` escribe en `Message.contenido`).
- `SPEC-057` — Enriquecimiento IA local sobre la transcripción (reutiliza SPEC-028/039, respuesta solo texto).
- `SPEC-058` — Retención/cifrado extendido al `audio_ref` de mensajería (extiende SPEC-041).
- Relacionado: **ADR-006** (transporte WhatsApp, `graph.facebook.com`), **ADR-007** (idempotencia `wamid`),
  **ADR-008** (RLS efectiva), **ADR-009** (STT local + cifrado/retención del audio), **ADR-005** (IA sin egress).
