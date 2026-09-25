# SPEC-035 — Infra STT local + almacén de audio cifrado + auditoría de egress 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: QUICKSILVER · Colaboran: BLACK PANTHER, BLACK WIDOW, WOLVERINE, HAWKEYE · Prioridad: CRÍTICA · Tipo: INFRA/SEGURIDAD · Fase: F0
- Deriva de: PLAN-004 (F0, §3.2/§3.3/§3.4/§3.5) · Clasificación: SENSIBLE (`.no-externo`) · ADR-009/ADR-010
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Habilitar la infraestructura de la Fase 4: un **`stt_worker`** de STT 100% local en la red `ia_internal internal:true` (**sin egress**), un **almacén de audio cifrado en reposo** on-prem (volumen/MinIO), los **pesos de Whisper montados por volumen** (sin `pull` en runtime), un **reverse proxy TLS** que expone SOLO el path del webhook de grabaciones, y la **evolución de `check-externos-backend.sh`** para prohibir STT/TTS de terceros y aplicar una allowlist por ruta al único host del PBX (solo si el PBX es externo, ADR-010).

## Contexto

El Entregable #2 dejó la IA aislada en `ia_internal internal:true` (ADR-005) y el Entregable #3 introdujo el patrón de egress acotado como transporte (ADR-006). Esta fase añade **audio como dato personal (posible PHI)**: el STT debe ser local y sin salida. El `stt_worker` **hereda** el aislamiento de la IA (se añade a `ia_internal`, nunca a `app`); recibe el audio desde el almacén cifrado on-prem, jamás por red externa. Si el PBX es externo, la única salida nueva es la descarga de la grabación desde `api`/`recording_fetch_worker`, acotada al host del PBX (ADR-010). Por SUP-42 (PBX preferido on-prem) la topología por defecto **no abre egress nuevo**; la ruta del `recording_fetch_worker` + allowlist se entrega inerte, activable solo si el Lead confirma PBX externo.

## Alcance

### IN
- `docker-compose`: `stt_worker` en la red `ia_internal internal:true` (sin ruta a internet ni al PBX), junto a `ia`/`rag_worker`/`sentiment_worker`.
- Almacén de audio **cifrado en reposo** on-prem: volumen cifrado local o MinIO en red interna con cifrado de objeto; sin exposición pública; permisos mínimos.
- Pesos de `faster-whisper` (`large-v3`, fallback `medium`) montados por **volumen**; sin descarga de modelos en runtime.
- (Solo si PBX externo, ADR-010) `recording_fetch_worker` en la red `app` con egress restringido por allowlist al único host del PBX; entregado inerte por defecto (SUP-42 on-prem).
- Reverse proxy TLS (Caddy/Nginx/Traefik) que expone SOLO el path del webhook de grabaciones; nunca STT/IA ni BD. Si la ingesta es por spool, un watcher local sin puerto expuesto.
- `check-externos-backend.sh` evolucionado: mantiene `FORBIDDEN_URLS`/`FORBIDDEN_SDKS` de inferencia; **añade** STT/TTS de terceros (Google STT, AWS Transcribe, OpenAI Whisper API, Deepgram, AssemblyAI, Azure Speech, etc.) como prohibidos; **nueva allowlist de transporte** con el host del PBX permitido SOLO dentro del módulo del conector (`app/services/telefonia/` o `app/integrations/pbx/`) si el PBX es externo.
- `.env.example` con vars de la fase como placeholders (modelo/idioma STT, ruta de pesos, clave de cifrado del almacén, retención, y —si PBX externo— host/credenciales del PBX y `verify_token`/firma del webhook).
- Firewall a nivel host que garantiza STT/IA sin egress y, si aplica, que solo `api`/`recording_fetch_worker` salgan y SOLO al host del PBX.

### OUT
- Entidades `call`/`call_transcript` (SPEC-036), conector de ingesta (SPEC-037), lógica del `stt_worker` (SPEC-038).
- Barrido de seguridad consolidado y pruebas de egress (SPEC-041/SPEC-042).

## Dependencias
- Depende de SPEC-011 (infra base), SPEC-024 (patrón egress acotado + `check-externos`) y ADR-005 (aislamiento IA). Habilita toda la ruta crítica de la fase. Se ancla en ADR-009 (STT local) y ADR-010 (egress PBX externo, si aplica).

## Requisitos funcionales
- RF-01 `docker compose up` levanta el stack con `stt_worker` en `ia_internal` sin egress y (si aplica) `recording_fetch_worker` en `app` con allowlist al host del PBX.
- RF-02 El almacén de audio on-prem está cifrado en reposo y sin exposición pública.
- RF-03 El reverse proxy TLS expone únicamente el path del webhook de grabaciones.
- RF-04 `check-externos-backend.sh` prohíbe STT/TTS de terceros en todo el código y permite el host del PBX solo dentro del módulo del conector (si externo).

## Requisitos no funcionales
- RNF-01 STT/IA 100% local: `stt_worker`/`ia`/`rag_worker`/`sentiment_worker` sin ruta a internet ni al PBX (RNF-41).
- RNF-43 Audio cifrado en reposo; secretos de cifrado en env (C3).
- RNF-07 Portabilidad on-prem: todo reproducible con `docker compose up` sin internet de inferencia.

## Criterios de aceptación (verificables)
- [ ] `docker compose up` levanta el stack; `stt_worker` en `ia_internal internal:true`, almacén cifrado montado, pesos Whisper por volumen (sin `pull` en runtime).
- [ ] Un intento de egress desde `stt_worker`/`ia`/`rag_worker`/`sentiment_worker` a IP/dominio público **falla** (timeout/deny).
- [ ] El almacén de audio está cifrado en reposo y no es alcanzable desde fuera del host (inspección).
- [ ] `check-externos-backend.sh` en verde: STT/TTS de terceros **prohibidos** en todo el código (test negativo: insertar `deepgram`/`assemblyai`/`transcribe` **falla** la build).
- [ ] (Si PBX externo) `api`/`recording_fetch_worker` alcanzan SOLO el host del PBX; el host del PBX fuera del módulo del conector **falla** la build; el `stt_worker`/IA que importe el cliente de descarga **falla** la build.
- [ ] (Si PBX on-prem, por defecto) **cero** egress público en la captura de red.
- [ ] El reverse proxy TLS expone solo el path del webhook (no `/metrics`, no STT/IA, no BD).
- [ ] `.env.example` contiene las vars de la fase como placeholders; ningún secreto real en repo.

## Notas de seguridad (C2/C3)
- C3: clave de cifrado del almacén, credenciales del PBX (si externo) y `verify_token`/firma SOLO en env/secret manager con fail-fast `${VAR:?}`; nunca en repo/logs.
- C2: no aplica creación de entidades; se preserva el borrado lógico del resto del stack.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: **audio e inferencia jamás salen del host** (ADR-009). El `stt_worker` vive en `ia_internal internal:true`. EXCEPCIÓN ACOTADA solo si el PBX es externo (ADR-010, análogo a ADR-006): egress permitido SOLO desde `api`/`recording_fetch_worker` y SOLO al host del PBX (transporte de descarga, no inferencia, no audio-a-terceros). Cambio sensible → aprobación explícita del Lead + notificación Telegram (C6).

## Riesgos
- R-41 (audio/inferencia a terceros): invariante de topología §3.2; STT/IA en `ia_internal`; STT/TTS de terceros prohibidos en CI; firewall host DROP; prueba de egress vacío (SPEC-042).
- R-43 (cifrado del audio): cifrado en reposo verificado; permisos mínimos; barrido BLACK WIDOW (SPEC-041).
- R-45 (egress del PBX): allowlist por ruta al host del PBX (ADR-010); preferible PBX on-prem sin egress nuevo (SUP-42); test negativo (SPEC-042).

## Checkpoints aplicables
- C3 (secretos en env). C4 (criterios verificables). C6 (cambio sensible: STT local/egress PBX, aprobación + Telegram). C8 (origen PLAN-004).
