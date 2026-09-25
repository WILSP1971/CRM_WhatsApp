# SPEC-038 — Worker STT `faster-whisper` es-CO + diarización básica (batch, sin egress) 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, THOR, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: CRÍTICA · Tipo: IA/BACKEND · Fase: F3
- Deriva de: PLAN-004 (F3, §3.1/§3.3) · Clasificación: SENSIBLE (`.no-externo`) · ADR-009
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Implementar el **`stt_worker`** batch que consume el trabajo STT (`stt:jobs`), transcribe el audio con **`faster-whisper` es-CO** (`large-v3`, **fallback CPU/`medium`**), produce **segmentos + timestamps** y **diarización básica opcional** (VAD agente/cliente), persiste en `call_transcript` (SPEC-036), instrumenta el **RTF**, es **idempotente por `call_id`** y corre **100% local sin egress** (ADR-009). Núcleo técnico y ruta crítica dura de la fase.

## Contexto

Se replica el patrón worker de los Entregables #2/#3 (`rag_ingest_worker`/`sentiment_worker`). El `stt_worker` vive en `ia_internal internal:true` (SPEC-035, ADR-009): recibe el audio desde el **almacén cifrado on-prem**, no por red externa, y **jamás** alcanza internet ni el PBX. Por SUP-44, el dimensionamiento por defecto es **GPU ≥16 GB** con `large-v3` (RTF ≤ 1.0 objetivo en GPU batch), con fallback **CPU `medium`** de RTF degradado documentado; el modelo/idioma son parametrizables por env (SPEC-035).

## Alcance

### IN
- Consumo de `stt:jobs`; carga de pesos por volumen (sin `pull` en runtime); transcripción es-CO con `large-v3` (fallback `medium`/`whisper.cpp` en CPU).
- Salida con **segmentos + timestamps** (`inicio`, `fin`, `texto`) y **diarización básica opcional** por VAD (etiqueta `agente`/`cliente`).
- Persistencia en `call_transcript` (SPEC-036) con idioma, modelo STT y (opcional) WER de referencia; actualización de estado en `call`.
- **Reintentos idempotentes por `call_id`**: reprocesar no duplica la transcripción.
- Instrumentación del **RTF** (real-time factor), latencia de cola batch y tasa de error, exportadas a `/metrics`.
- N `stt_worker` escalables; VAD para saltar silencios.

### OUT
- Enriquecimiento IA (sentimiento/resumen/borrador) sobre la transcripción (SPEC-039).
- Ingesta/almacenamiento del audio (SPEC-037); esquema de datos (SPEC-036).
- Carga/medición formal de RTF bajo carga (SPEC-042, THOR).

## Dependencias
- Depende de SPEC-037 (audio almacenado + trabajo encolado) y SPEC-036 (`call_transcript`). Produce la transcripción que consume SPEC-039. Se ancla en ADR-009 (STT local) y ADR-005 (aislamiento IA).

## Requisitos funcionales
- RF-01 El `stt_worker` transcribe audio es-CO con `faster-whisper` y persiste segmentos + timestamps.
- RF-02 La diarización básica opcional (VAD) separa turnos agente/cliente cuando está activada.
- RF-03 Reprocesar el mismo `call_id` no crea una segunda transcripción (idempotencia).
- RF-04 El modelo/idioma y el fallback CPU son parametrizables por env.

## Requisitos no funcionales
- RNF-41 STT 100% local en `ia_internal internal:true`; sin egress; audio desde el almacén on-prem.
- RNF-42 **RTF ≤ 1.0 objetivo en GPU** con `large-v3` (medición formal en SPEC-042); fallback CPU `medium` con RTF degradado **documentado**.
- RNF-48 WER es-CO documentado sobre set de prueba (SPEC-042); el human-in-the-loop absorbe errores.

## Criterios de aceptación (verificables)
- [ ] Una grabación es-CO ficticia se transcribe con `faster-whisper` local produciendo segmentos + timestamps en `call_transcript`.
- [ ] La diarización básica (VAD) etiqueta turnos agente/cliente cuando se activa.
- [ ] Reprocesar el mismo `call_id` **no** duplica la transcripción (test de idempotencia).
- [ ] **Cero** llamadas a STT de terceros ni a internet: captura de red muestra salida pública nula desde `stt_worker`; intento de egress **falla** (timeout/deny).
- [ ] `check-externos-backend.sh` en verde; el `stt_worker` no importa el cliente de descarga del PBX.
- [ ] El RTF, la latencia de cola y la tasa de error se exportan a `/metrics`.
- [ ] El fallback CPU/`medium` produce transcripción válida con RTF degradado documentado.

## Notas de seguridad (C2/C3)
- C2: la transcripción respeta borrado lógico; sin DELETE físico (purga por retención en SPEC-041).
- C3: config de modelo/pesos/cifrado SOLO en env; nunca en repo/logs.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (sin egress): el STT es 100% local en `ia_internal internal:true` (ADR-009). El audio (dato personal/posible PHI) y la inferencia **jamás salen** del host. STT/TTS de terceros PROHIBIDOS. La prueba de egress vacío desde el `stt_worker` es evidencia obligatoria del DoD (CE-41).

## Riesgos
- R-41 (audio/inferencia a terceros): STT/IA en `ia_internal`; prueba de egress vacío + captura de red (SPEC-042).
- R-42 (RTF/GPU): batch tolerante a cola; `large-v3` GPU / fallback CPU; N workers; medición THOR (SPEC-042).
- R-46 (idempotencia): reintentos idempotentes por `call_id` (ADR-007).
- R-48 (WER es-CO): `large-v3` es-CO base; WER documentado; diarización; human-in-the-loop absorbe errores.

## Checkpoints aplicables
- C2 (borrado lógico). C3 (secretos en env). C4 (criterios verificables). C8 (origen PLAN-004).
