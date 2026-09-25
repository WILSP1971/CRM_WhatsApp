# SPEC-044 — Infra de voz en vivo + GPU compartida priorizada + auditoría de egress 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: QUICKSILVER · Colaboran: BLACK PANTHER, THOR, BLACK WIDOW, WOLVERINE, HAWKEYE · Prioridad: CRÍTICA · Tipo: INFRA/SEGURIDAD · Fase: F0
- Deriva de: PLAN-005 (F0, §0, §3.2/§3.3/§3.6/§3.7/§3.8) · Clasificación: SENSIBLE (`.no-externo`) · ADR-011/ADR-012 (reafirma ADR-005/ADR-009/ADR-010)
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Habilitar la infraestructura del VoiceBot en vivo: los servicios **`voice_stt`**, **`voice_tts`** y **NLU de intent** en la red `ia_internal internal:true` (**sin egress**), un **`voice_gateway`** en la red `app` cuyo único egress —si el PBX de media es externo— es una **allowlist por ruta al host del PBX** (ADR-011); el **mecanismo de prioridad de GPU** del VoiceBot en vivo sobre el `stt_worker` batch de #4 (pausa/despriorización + fracción de VRAM reservada); los **pesos de STT liviano + Piper + banco de audios pregrabados montados por volumen** (sin `pull` en runtime); un **reverse proxy TLS/WSS** que expone SOLO el path del gateway; el **`.env.example`** con las vars de la fase; y la evolución de **`check-externos-backend.sh`** para prohibir TTS de terceros y aplicar allowlist por ruta al host del PBX de media.

## Contexto

El Entregable #4 dejó la IA/STT batch aislada en `ia_internal internal:true` (ADR-005/ADR-009) y consolidó el patrón de egress acotado como transporte (ADR-006/ADR-010). Esta fase añade el **bucle de voz en vivo** sobre esa infra, con dos condiciones estructurales vinculantes del Lead (P1/P3, §0 del PLAN-005): (a) catálogo cerrado, ningún LLM generativo en vivo; (b) **GPU compartida** con el `stt_worker` batch de #4, sin GPU dedicada. Esta SPEC es la puerta de F0 donde se materializa la **restricción dura de GPU** (§3.6.3): el arbitraje de la GPU física única entre voz en vivo (prioritaria) y batch (despriorizable) es el entregable central de INFRA. El `voice_stt`/`voice_tts`/NLU **heredan** el aislamiento de la IA (se añaden a `ia_internal`, nunca a `app`); el audio en vivo llega desde el `voice_gateway` por la red interna, nunca desde internet ni el PBX. Por P-M (PBX on-prem preferido), la topología por defecto **no abre egress nuevo**; la allowlist del `voice_gateway` al host del PBX de media se entrega **inerte**, activable solo si el Lead confirma PBX externo (cambio sensible → C6).

## Alcance

### IN
- `docker-compose`: `voice_stt`, `voice_tts` y NLU de intent en `ia_internal internal:true` (sin ruta a internet ni al PBX), junto a `ia`/`stt_worker` batch/`rag_worker`/`sentiment_worker`.
- `voice_gateway` en la red `app`; egress restringido por **allowlist por ruta** al **único host del PBX de media/SIP**; entregado **inerte** por defecto (P-M on-prem). Puede pertenecer también a `ia_internal` para dialogar con voz/NLU por la red interna, **sin** que eso dé al STT/TTS/IA ruta a `app`.
- **Mecanismo de prioridad de GPU** (ADR-011): (a) señal (lock/flag en Redis) que hace que el `stt_worker` batch **suspenda/reduzca** su consumo de GPU mientras haya ≥1 llamada en vivo activa y **reanude** al liberarse; (b) **fracción de VRAM reservada** para el proceso de voz en vivo. Parámetros por env.
- Pesos de STT liviano (`distil-whisper`/`faster-whisper` `small`/`medium` cuantizado) + voces **Piper** es-CO + **banco de audios pregrabados** del catálogo, todos montados por **volumen**; sin descarga de modelos en runtime.
- Reverse proxy **TLS/WSS** (Caddy/Nginx/Traefik) que expone SOLO el path del `voice_gateway` (SIP/WS de media); nunca STT/TTS/NLU/IA ni BD ni `/metrics`.
- `check-externos-backend.sh` evolucionado: mantiene `FORBIDDEN_URLS`/`FORBIDDEN_SDKS` de #2/#3/#4 (inferencia + STT de terceros) y **añade TTS de terceros** (Google TTS, AWS Polly, ElevenLabs, Azure Speech, OpenAI TTS, Coqui-cloud, PlayHT, Deepgram TTS…) como prohibidos; **allowlist por ruta** con el host del PBX de media permitido SOLO dentro del `voice_gateway` (`app/services/telefonia/`), si el PBX es externo.
- `.env.example` con vars de la fase como placeholders: modelo STT en vivo y cuantización, límite de concurrencia `C`, umbral de confianza de intent, fracción de VRAM reservada, flag Piper↔pregrabado, host/credenciales del PBX de media (si externo), TLS/WSS.
- Firewall a nivel host que garantiza voz/IA sin egress y —si aplica— que solo el `voice_gateway` salga y SOLO al host del PBX de media.

### OUT
- Catálogo de intents y NLU determinista (SPEC-045); conector de media en vivo y su sesión SIP/media (SPEC-046); lógica del `voice_stt` streaming (SPEC-047); bucle de diálogo/TTS/barge-in (SPEC-048); escalación/monitor SPA (SPEC-049).
- Fijación empírica de `C` y medición de latencia/contención bajo carga (SPEC-050); barrido de seguridad consolidado, persistencia y retención (SPEC-051).

## Dependencias
- Depende de SPEC-011 (infra base), SPEC-024 (patrón egress acotado + `check-externos`), SPEC-035 (infra STT local + almacén cifrado + aislamiento IA) y ADR-005/ADR-009. Habilita toda la ruta crítica de la fase. Se ancla en ADR-011 (GPU compartida priorizada + egress PBX de media) y ADR-012 (TTS local).

## Requisitos funcionales
- RF-01 `docker compose up` levanta el stack con `voice_stt`/`voice_tts`/NLU en `ia_internal` sin egress y `voice_gateway` en `app` con allowlist (inerte por defecto) al host del PBX de media.
- RF-02 El mecanismo de prioridad de GPU existe y es configurable: con ≥1 llamada en vivo activa el `stt_worker` batch se despriorza/pausa; reanuda al liberarse; la voz tiene fracción de VRAM reservada.
- RF-03 El reverse proxy TLS/WSS expone únicamente el path del `voice_gateway`.
- RF-04 `check-externos-backend.sh` prohíbe TTS de terceros en todo el código y permite el host del PBX de media solo dentro del `voice_gateway` (si externo).
- RF-05 Pesos STT liviano + voces Piper + banco de audios pregrabados montados por volumen (sin `pull` en runtime).

## Requisitos no funcionales
- RNF-51 Voz/IA 100% local: `voice_stt`/`voice_tts`/NLU/`ia`/`stt_worker` batch sin ruta a internet ni al PBX (ADR-011 §8).
- RNF-52 GPU física única compartida y priorizada; sin GPU dedicada (ADR-011 §1-§2).
- RNF-07 Portabilidad on-prem: todo reproducible con `docker compose up` sin internet de inferencia; suites #1-#4 verdes.

## Criterios de aceptación (verificables)
- [ ] `docker compose up` levanta el stack; `voice_stt`/`voice_tts`/NLU en `ia_internal internal:true`; pesos/voces/audios por volumen (sin `pull` en runtime).
- [ ] Un intento de egress desde `voice_stt`/`voice_tts`/NLU/`ia`/`stt_worker` batch a IP/dominio público **falla** (timeout/deny).
- [ ] El mecanismo de prioridad de GPU está presente y activable: al marcar "llamada en vivo activa" el `stt_worker` batch reduce/suspende consumo de GPU; al desmarcar, reanuda (verificación funcional; la medición bajo carga es SPEC-050).
- [ ] La fracción de VRAM reservada para la voz en vivo es configurable por env y se aplica al arrancar.
- [ ] `check-externos-backend.sh` en verde: **TTS de terceros prohibido** en todo el código (test negativo: insertar `elevenlabs`/`aws-polly`/`azure.*speech`/`openai.*audio.*speech`/`google.*texttospeech` **falla** la build).
- [ ] (Si PBX de media externo) el `voice_gateway` alcanza SOLO el host del PBX; el host del PBX fuera del `voice_gateway` **falla** la build; `voice_stt`/`voice_tts`/NLU/IA que importen el cliente de transporte de media **fallan** la build.
- [ ] (Si PBX on-prem, por defecto) **cero** egress público en la captura de red.
- [ ] El reverse proxy TLS/WSS expone solo el path del `voice_gateway` (no `/metrics`, no STT/TTS/NLU/IA, no BD).
- [ ] `.env.example` contiene las vars de la fase como placeholders; ningún secreto real en repo.

## Notas de seguridad (C2/C3)
- C3: fracción de VRAM/límite `C`/umbrales no son secretos, pero credenciales del PBX de media (si externo), claves TLS y tokens SOLO en env/secret manager con fail-fast `${VAR:?}`; nunca en repo/logs.
- C2: no aplica creación de entidades; se preserva el borrado lógico del resto del stack.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: **audio, STT, TTS e inferencia jamás salen del host** (ADR-005/ADR-009/ADR-011/ADR-012). `voice_stt`/`voice_tts`/NLU viven en `ia_internal internal:true`. EXCEPCIÓN ACOTADA solo si el PBX de media es externo (ADR-011 §7): egress permitido SOLO desde `voice_gateway` y SOLO al host del PBX de media (transporte de media, no inferencia, no audio-a-terceros). Habilitar egress externo = cambio sensible → aprobación explícita del Lead + notificación Telegram (C6).

## Riesgos
- R-54 (audio/inferencia/TTS a terceros): invariante de topología §3.2; voz/IA en `ia_internal`; STT/TTS de terceros prohibidos en CI; firewall host DROP; prueba de egress vacío (SPEC-051).
- R-52 (contención de GPU): mecanismo de prioridad + fracción de VRAM reservada (ADR-011); instrumentación de contención se completa en SPEC-050.
- R-59 (egress del PBX de media): allowlist por ruta al host del PBX en el `voice_gateway` (ADR-011); preferible PBX on-prem sin egress nuevo (P-M); test negativo (SPEC-051).
- R-61 (regresión en #4): el mecanismo de prioridad no rompe el batch (reanuda tras la voz); migraciones/infra aditivas; suites #1-#4 verdes.

## Checkpoints aplicables
- C3 (secretos en env). C4 (criterios verificables). C6 (cambio sensible: voz en vivo/egress PBX de media, aprobación + Telegram). C8 (origen PLAN-005).
