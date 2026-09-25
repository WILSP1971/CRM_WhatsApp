# SPEC-056 — Enganche STT: sink parametrizado por `destino` en el `stt_worker` existente (sink `message` escribe en `Message.contenido`) 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, THOR, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: **CRÍTICA** · Tipo: IA/BACKEND · Fase: F3
- Deriva de: PLAN-006 (F3, §3.4 — núcleo técnico y ruta crítica dura) · Clasificación: SENSIBLE (`.no-externo`) · ADR-009/ADR-013
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

**Extender de forma aditiva** el `stt_worker` existente (SPEC-038) para que sea **agnóstico del destino de escritura** de la transcripción, gobernado por un campo **`destino`** del job de `stt:jobs`. El sink actual (`call:{id}`, comportamiento de SPEC-038/039: crea un `Message` en la conversación de voz y dispara el pipeline IA) queda **exactamente intacto**; se añade un sink nuevo (`message:{id}`) que escribe la transcripción **de vuelta en el `Message.contenido` del `Message(tipo="audio")` ya existente** (creado por SPEC-055) dentro de su `Conversation` de WhatsApp — **sin crear un `Message` nuevo** y **sin crear `call`/`call_transcript`** (ADR-013). El motor `stt_engine.py` **NO se toca** ni se carga dos veces: un solo worker, un solo modelo en memoria, un sink parametrizado. **Cero regresión** en los jobs `call` de #4.

## Contexto

`stt_worker.process_job` (SPEC-038) hoy: (1) lee el job `SttTranscriptionJob {call_id, audio_ref, tenant_id, enqueued_at_epoch_seconds}`; (2) descifra el audio del almacén on-prem (`audio_store.load_audio`); (3) idempotencia por `call_id` (`_transcript_exists` + UNIQUE `uq_call_transcripts_call_id`); (4) transcribe con `stt_engine.transcribe_audio_bytes` (`faster-whisper` es-CO, fallback CPU) **fuera de transacción**; (5) persiste `CallTranscript` + `calls.estado="transcrita"`; (6) **materializa la transcripción como un `Message` NUEVO** (`_materialize_transcript_message` → `create_message`) en una conversación de canal `voz`, y dispara sentimiento (SPEC-018) + resumen (SPEC-039) + borrador RAG (SPEC-017/019) best-effort. Vive en `ia_internal internal:true`, **sin egress**, y **no importa** `httpx` ni el cliente de descarga (ADR-009). El contrato de cola (`app/core/stt_queue.py`) es `{call_id, audio_ref, tenant_id, enqueued_at_epoch_seconds}` **sin campo `destino`**.

**Diferencia esencial del sink nuevo:** para la nota de voz de WhatsApp **el `Message` YA existe** (lo creó SPEC-055 con `tipo="audio"`, `contenido=NULL`); el sink `message` **actualiza** ese `Message.contenido` con la transcripción — no crea uno nuevo (a diferencia del sink `call`, que sí crea el `Message` de voz). A partir de ahí el `Message` es indistinguible de un texto normal para el resto del pipeline (SPEC-057).

## Alcance

### IN
- **Extensión aditiva del contrato de cola (`app/core/stt_queue.py`):** `SttTranscriptionJob` gana un campo `destino: str` con **default de compatibilidad `"call:{call_id}"`**. Formato exacto: `destino = "call:<uuid>"` (sink existente) | `destino = "message:<uuid>"` (sink nuevo). Un job **sin** `destino` (formato anterior, tolerado por robustez como ya hace `from_json` con `enqueued_at_epoch_seconds`) se interpreta como `"call:<call_id>"` → **comportamiento idéntico a SPEC-038**. El `enqueue_stt_job` gana un parámetro `destino` opcional (default `call`).
  - Contrato del campo `destino` (documentado en `stt_queue.py`): `"<sink>:<uuid>"`. `<sink>` ∈ {`call`, `message`}. `<uuid>` es la fila objetivo (`calls.id` o `messages.id`). Para `message`, el job **no** lleva `call_id` semánticamente (se reutiliza el campo de transporte o se añade un campo `target_id`; a fijar en implementación sin romper el default `call`).
- **Refactor del `stt_worker` a "sink parametrizado" (aditivo, DRY):** tras transcribir con `stt_engine.py` (paso 4, **sin tocar el motor**), el worker **despacha** al sink según `destino`:
  - **sink `call`** = la lógica ACTUAL EXACTA (persistir `CallTranscript`, `calls.estado`, `_materialize_transcript_message` → `Message` nuevo de voz, pipeline IA best-effort). **Ni una línea de comportamiento observable cambia** para `destino=call`.
  - **sink `message`** (NUEVO): idempotencia por `messages.id`/`wamid` (no re-escribir si `transcripcion_estado=="ok"`/`contenido` ya poblado); bajo RLS del tenant (`set_tenant_session`, ADR-004) **actualiza** `messages.contenido = <texto transcrito>` y `messages.transcripcion_estado="ok"` del `Message(tipo="audio")` existente (SPEC-053); **no** crea `CallTranscript`, **no** crea `Message` nuevo, **no** toca `calls`.
- **Reutilización única del motor:** `stt_engine.py` **no se modifica** y se invoca **una sola vez** por job; **un solo modelo Whisper en memoria**; un solo punto de aislamiento `ia_internal`; misma instrumentación RTF/latencia/errores exportada a `/metrics`.
- **Idempotencia y reintentos** del sink `message` análogos al sink `call`: reprocesar un job `message:{id}` no duplica ni sobrescribe una transcripción ya escrita (`transcripcion_estado=="ok"`).
- El **disparo del pipeline IA** sobre el `Message` de audio actualizado se deja explícitamente para SPEC-057 (F4), reutilizando el mismo camino que hoy usa el sink `call` — el sink `message` deja el `Message` con texto listo para ese disparo.

### OUT
- Cambios en `stt_engine.py` (PROHIBIDO tocar el motor).
- Descarga/almacenamiento (SPEC-054); parser/encolado/límite (SPEC-055); enriquecimiento IA sobre el `Message` de audio (SPEC-057); retención (SPEC-058).
- Cualquier `call`/`call_transcript` para la nota de voz de WhatsApp (ADR-013).

## Dependencias
- Depende de SPEC-055 (job encolado con `destino="message:{id}"` y `audio_ref`) y SPEC-053 (`Message` tipo `audio` con `contenido` nullable). Reutiliza SPEC-038 (worker/motor) sin tocar el motor. Habilita SPEC-057 (enriquecimiento). Se ancla en ADR-009 (STT local sin egress) y ADR-013 (sink parametrizado, no worker paralelo).

## Requisitos funcionales
- RF-01 El contrato de `stt:jobs` admite `destino` de forma **aditiva**; un job **sin** `destino` se comporta como `call` (igual que SPEC-038).
- RF-02 Con `destino="message:{id}"`, la transcripción se escribe en `messages.contenido` del `Message` existente y `transcripcion_estado="ok"`, bajo RLS del tenant.
- RF-03 El sink `message` **no** crea `Message` nuevo, **no** crea `CallTranscript`, **no** toca `calls`.
- RF-04 `stt_engine.py` no se modifica; el modelo se carga/invoca **una sola vez** por job (un solo worker, sin duplicar carga del modelo).
- RF-05 Reprocesar un job `message:{id}` con la transcripción ya escrita (`transcripcion_estado=="ok"`) es **no-op** (idempotencia).

## Requisitos no funcionales
- RNF-41 STT 100% local en `ia_internal internal:true`; sin egress; audio desde el almacén on-prem (ADR-009). El worker no importa `httpx` ni el cliente de descarga (invariante intacto).
- RNF-62 **Cero regresión** del sink `call`: la suite de SPEC-038 (y SPEC-039/042 en lo que aplique) pasa **sin modificar sus asserts**; los jobs `call` siguen escribiendo `CallTranscript` y creando el `Message` de voz exactamente igual.
- RNF-42 RTF/latencia/error se siguen instrumentando igual para ambos sinks (una sola ruta de inferencia).

## Criterios de aceptación (verificables)
- [ ] **Cero regresión (criterio duro):** la suite existente de SPEC-038 corre **en verde sin modificar sus asserts**; un job `call` (o sin `destino`) sigue escribiendo `CallTranscript` + `Message` de voz + pipeline IA **exactamente igual** que antes de esta SPEC (test de no-regresión explícito).
- [ ] Un job con `destino="message:{id}"` escribe la transcripción en `messages.contenido` del `Message(tipo="audio")` existente y marca `transcripcion_estado="ok"`; **no** crea `CallTranscript`, **no** crea `Message` nuevo, **no** toca `calls` (asserts explícitos).
- [ ] Un job **sin** `destino` (formato anterior) se procesa como `call` sin error (compatibilidad hacia atrás, `from_json`).
- [ ] Reprocesar el mismo job `message:{id}` con `transcripcion_estado=="ok"` es **no-op** (test de idempotencia).
- [ ] `stt_engine.py` no aparece en el diff (motor intacto); un solo `stt_worker`/un solo modelo (no hay worker paralelo ni segunda carga de modelo).
- [ ] **Cero** llamadas a STT de terceros ni a internet: prueba de egress vacío desde `stt_worker`; `check-externos-backend.sh` en verde; el worker no importa el cliente de descarga.
- [ ] RTF/latencia de cola/tasa de error se exportan a `/metrics` para ambos sinks.

## Notas de seguridad (C2/C3)
- C2: el `Message` de audio respeta borrado lógico; sin DELETE físico (purga por retención en SPEC-058).
- C3: config de modelo/pesos/cifrado/cola SOLO en env; nunca en repo/logs.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (sin egress): el STT es 100% local en `ia_internal internal:true` (ADR-009). El audio (posible PHI) y la inferencia **jamás salen** del host. STT/TTS de terceros PROHIBIDOS. El sink parametrizado **no** abre ninguna ruta nueva: sigue leyendo del almacén cifrado on-prem y escribiendo en BD bajo RLS. La prueba de egress vacío desde el `stt_worker` es evidencia obligatoria del DoD.

## Riesgos
- R-62 (**regresión en jobs `call` de #4** — top-3): `destino` por defecto = `call`; extensión **aditiva** del contrato de cola; `stt_engine.py` no se toca; test de no-regresión de un job `call` que sigue escribiendo `CallTranscript`; la suite de SPEC-038 corre sin modificar asserts.
- R-61 (audio/inferencia a terceros): worker en `ia_internal`; prueba de egress vacío; no importa el cliente de descarga (SPEC-060).
- R-65 (idempotencia): sink `message` idempotente por `messages.id`/`transcripcion_estado`; reprocesar no duplica.
- R-69 (latencia/coste STT sin GPU): una sola ruta de inferencia; RTF instrumentado reutilizado; batch tolerante a cola; límite de 10 min (SPEC-055) acota el peor caso.

## Checkpoints aplicables
- C2 (borrado lógico). C3 (secretos en env). C4 (criterios verificables). C8 (origen PLAN-006).
