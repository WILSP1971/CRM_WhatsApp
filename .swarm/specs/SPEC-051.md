# SPEC-051 — Seguridad del vector voz/TTS + persistencia de la llamada en vivo + retención (reutiliza #4) 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: BLACK WIDOW · Colaboran: BLACK PANTHER, CAPTAIN AMERICA, HAWKEYE, WOLVERINE · Prioridad: CRÍTICA · Tipo: SEGURIDAD/BACKEND · Fase: F7
- Deriva de: PLAN-005 (F7, §3.5/§3.7/§3.8, §1 reúso #4) · Clasificación: SENSIBLE (`.no-externo`) · ADR-011/ADR-012 (reutiliza SPEC-036/041, ADR-009)
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Cerrar el vector de seguridad de la voz en vivo y su ciclo de vida de datos: **barrido BLACK WIDOW del vector TTS/voz sintética**, **`check-externos-backend.sh` en verde** (TTS de terceros prohibido), **prueba de egress vacío** desde voz/IA (y —si PBX externo— egress solo al host del PBX de media); **persistencia de la llamada en vivo** en `call`/`call_transcript` (SPEC-036) al colgar, con **recomputo batch de la transcripción de calidad** (`large-v3` de #4, SPEC-039) sin inferencia externa; y **retención/anonimización** (SPEC-041/ADR-009) aplicada al audio en vivo, a la transcripción y al audio TTS si se persiste (por defecto **no**, P-N).

## Contexto

Esta SPEC es transversal (se diseña desde F0 y **cierra** auditando todo) y **reutiliza** la infraestructura de datos de #4 sin reinventarla: `call`/`call_transcript` (SPEC-036), retención/anonimización (SPEC-041/ADR-009) y enriquecimiento batch (SPEC-039). El vector **nuevo** respecto a #4 es el **TTS de salida** (ADR-012): superficie de audio sintético y contenido que la empresa dice. La política por defecto (P-N) es **no persistir** el audio TTS (solo la transcripción textual de lo que dijo el bot), reduciendo superficie; si se persiste, aplica la retención de #4. Al colgar, la llamada en vivo queda en `call`/`call_transcript` (idempotente por `call_id`) y aparece en la ficha de llamada de #4 (SPEC-040); la transcripción "de calidad" puede recomputarse en batch con `large-v3` (SPEC-039) sobre el audio en vivo, sin coste en vivo y sin egress.

## Alcance

### IN
- **Barrido de seguridad** del vector voz/TTS: revisión de que `voice_stt`/`voice_tts`/NLU no tienen egress, que el `voice_gateway` es el único con transporte al PBX, y que la declaración de voz sintética (ADR-012) es un invariante.
- **`check-externos-backend.sh` verde:** TTS de terceros prohibido (test negativo que **falla** la build); allowlist por ruta al host del PBX de media solo en el `voice_gateway`; ningún dominio en manifiestos de `ia_internal`.
- **Prueba de egress vacío:** intento de salida desde `voice_stt`/`voice_tts`/NLU/`ia`/`stt_worker` batch **falla** (timeout/deny) con captura de red; (si PBX externo) el `voice_gateway` alcanza SOLO el host del PBX de media.
- **Persistencia de la llamada en vivo:** al colgar, `call` (metadatos, intents detectados, transferencias) y `call_transcript` (segmentos de la transcripción en vivo + timestamps) se persisten por `call_id` (idempotente, SPEC-036), bajo RLS efectiva por tenant (ADR-008); aparece en la ficha de #4 (SPEC-040).
- **Recomputo batch opcional de la transcripción de calidad** con `large-v3` de #4 (SPEC-039) sobre el audio en vivo, sin inferencia externa; enriquecimiento (sentimiento/resumen) reutilizando SPEC-039.
- **Retención/anonimización** (SPEC-041/ADR-009) aplicada al audio en vivo, a la transcripción y —si se persiste— al audio TTS; por defecto el audio TTS **no** se persiste (P-N).
- **Aislamiento cross-tenant** verificado: la llamada en vivo/transcripción no es legible por otro tenant (test que **falla** por RLS).

### OUT
- Medición de latencia/carga (SPEC-050); implementación del bucle/escalación (SPEC-048/049); simulador y runbook (SPEC-052).

## Dependencias
- Depende de SPEC-044 (infra/egress), SPEC-046 (fin de llamada/handoff), SPEC-047/048 (transcripción en vivo/TTS), SPEC-036 (`call`/`call_transcript`), SPEC-041 (retención/anonimización) y SPEC-039 (enriquecimiento batch). Se ancla en ADR-009 (STT local + retención), ADR-011 (egress acotado), ADR-012 (TTS local + no persistir audio).

## Requisitos funcionales
- RF-01 `check-externos-backend.sh` en verde con TTS de terceros prohibido y allowlist por ruta al PBX de media solo en el `voice_gateway`.
- RF-02 La prueba de egress vacío desde voz/IA falla toda salida pública; (si PBX externo) solo el `voice_gateway` alcanza el host del PBX.
- RF-03 La llamada en vivo se persiste en `call`/`call_transcript` (idempotente por `call_id`, RLS efectiva) y aparece en la ficha de #4 al colgar.
- RF-04 La retención/anonimización de #4 aplica al audio en vivo/transcripción/TTS; por defecto el audio TTS no se persiste.
- RF-05 Un test cross-tenant sobre la llamada en vivo/transcripción **falla** por RLS.

## Requisitos no funcionales
- RNF-51 Cero audio/inferencia/TTS a terceros (prueba de egress vacío + `check-externos` verde).
- RNF-47 Aislamiento multi-tenant con rol app no-superusuario (ADR-008).
- RNF-07 Suites #1-#4 verdes; cobertura backend del canal de voz en vivo ≥ 80%.

## Criterios de aceptación (verificables)
- [ ] `check-externos-backend.sh` en verde; test negativo (insertar `elevenlabs`/`aws-polly`/`azure.*speech`/`openai.*audio.*speech`/`google.*texttospeech`) **falla** la build.
- [ ] Prueba de egress: salida desde `voice_stt`/`voice_tts`/NLU/`ia`/`stt_worker` batch **falla**; (si PBX externo) el `voice_gateway` alcanza SOLO el host del PBX de media (captura de red); (si on-prem) cero egress público.
- [ ] Al colgar, la llamada en vivo queda en `call`/`call_transcript` (segmentos + timestamps + intents + transferencias) por `call_id` idempotente y aparece en la ficha de #4 (SPEC-040).
- [ ] Recomputo batch opcional de la transcripción de calidad con `large-v3` (SPEC-039) sin inferencia externa (verificado).
- [ ] Retención/anonimización (SPEC-041/ADR-009) aplicada al audio en vivo/transcripción; por defecto el audio TTS **no** se persiste (P-N); si se persiste, se retiene/anonimiza igual.
- [ ] Test cross-tenant: una llamada en vivo/transcripción de otro tenant **falla** por RLS con el rol app no-superusuario (ADR-008).
- [ ] La declaración de voz sintética (ADR-012) es un invariante verificado; cobertura backend ≥ 80%; suites #1-#4 verdes.

## Notas de seguridad (C2/C3)
- C3: claves de cifrado del almacén (heredadas de #4), credenciales del PBX de media (si externo) y tokens SOLO en env/secret manager con fail-fast `${VAR:?}`; nunca en repo/logs.
- C2: `call`/`call_transcript` con borrado lógico; la purga por retención (SPEC-041) es lógica/anonimizante, no expone datos.
- C6: habilitar egress del PBX externo o persistir el audio TTS = cambio sensible → aprobación del Lead + notificación Telegram.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: esta SPEC **prueba y cierra** el invariante de la fase (ADR-011/ADR-012): voz/IA sin salida; audio/TTS nunca a terceros; (si PBX externo) transporte de media solo al host del PBX. La prueba de egress vacío + `check-externos` verde son evidencia obligatoria del DoD. El audio en vivo/transcripción/TTS son dato personal (posible PHI): cifrado, retención y acceso auditado (ADR-009).

## Riesgos
- R-54 (audio/inferencia/TTS a terceros): egress vacío + `check-externos` verde + captura de red.
- R-55 (voz sintética/deepfake): declaración obligatoria verificada (ADR-012); TTS local no clonado.
- R-59 (egress del PBX de media): allowlist por ruta; test negativo que **falla** la build.
- R-60 (fuga cross-tenant): RLS efectiva (ADR-008); test cross-tenant que **falla**.
- R-61 (regresión #4): persistencia aditiva; suites #1-#4 verdes.

## Checkpoints aplicables
- C2 (borrado lógico/purga por retención). C3 (secretos en env). C4 (criterios verificables). C6 (cambio sensible: egress PBX / persistir TTS, aprobación + Telegram). C8 (origen PLAN-005).
