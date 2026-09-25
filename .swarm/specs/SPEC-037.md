# SPEC-037 — Conector de ingesta de grabaciones (transporte) + almacenamiento cifrado + idempotencia por `call_id` 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, THOR, WOLVERINE · Prioridad: ALTA · Tipo: BACKEND/INTEGRACIÓN · Fase: F2
- Deriva de: PLAN-004 (F2, §3.1/§3.3/§3.5) · Clasificación: SENSIBLE (`.no-externo`) · ADR-010/ADR-007
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Recibir la grabación de la llamada (fichero WAV/OGG) + metadatos (número, dirección, duración, `call_id`, tenant) desde el PBX vía **webhook o watcher de spool**, con **ACK rápido** e **idempotencia por `call_id`** (ADR-007), **almacenar el audio cifrado on-prem** (SPEC-035) y **encolar el trabajo STT** en Redis. Si el PBX es externo y solo notifica una URL, un **`recording_fetch_worker`** dedicado descarga el audio con egress acotado al host del PBX (ADR-010), **nunca** el STT/IA.

## Contexto

Se replica el patrón cola Redis + worker de los Entregables #2/#3 (`wa_inbound_worker`, `rag_ingest_worker`, `sentiment_worker`) y el patrón de webhook con ACK rápido + idempotencia del canal WhatsApp (SPEC-026/027). Por SUP-42, el PBX se asume **on-prem** que entrega **fichero por webhook/spool**: en ese caso **no hay egress nuevo** y el `recording_fetch_worker` es innecesario. Si el Lead confirma PBX externo, se activa la descarga acotada (ADR-010). El resto del pipeline es agnóstico de esa decisión.

## Alcance

### IN
- Endpoint de webhook (tras el reverse proxy TLS, SPEC-035) o watcher de spool que recibe fichero + metadatos; validación de `verify_token`/firma si el PBX lo soporta.
- **ACK rápido** al PBX; procesamiento diferido; **dedup por `call_id`** (guarda en worker + unicidad en BD de SPEC-036).
- Resolución de tenant desde metadatos; **descarte auditado sin persistir contenido** si no hay mapeo de tenant (patrón ADR-007).
- Almacenamiento del audio en el **almacén cifrado on-prem** (SPEC-035) y registro de `call` (SPEC-036) con `audio_ref`.
- Encolado del trabajo STT (`stt:jobs`) para el `stt_worker` (SPEC-038).
- (Solo si PBX externo, ADR-010) `recording_fetch_worker` en `app` que descarga el audio con `httpx` + allowlist al host del PBX; jamás el STT/IA.

### OUT
- Transcripción en sí (SPEC-038); enriquecimiento IA (SPEC-039).
- Definición del esquema `call`/`call_transcript` (SPEC-036, reutilizada) y de la infra/allowlist (SPEC-035).

## Dependencias
- Depende de SPEC-036 (`call`/`call_id`/almacenamiento) y SPEC-035 (infra/almacén cifrado/allowlist). Es la puerta de ingesta de F3. Se ancla en ADR-007 (idempotencia) y ADR-010 (egress PBX externo, si aplica).

## Requisitos funcionales
- RF-01 El conector recibe fichero + metadatos y responde con ACK rápido.
- RF-02 Un reenvío del PBX con el mismo `call_id` no crea una segunda llamada/trabajo STT.
- RF-03 Sin mapeo de tenant → descarte auditado sin persistir contenido de audio.
- RF-04 El audio se almacena cifrado on-prem y se encola el trabajo STT.
- RF-05 (Si PBX externo) la descarga la hace solo `recording_fetch_worker` y solo al host del PBX.

## Requisitos no funcionales
- RNF-46 Idempotencia robusta por `call_id` (BD + worker).
- RNF-41 El STT/IA nunca descarga del PBX ni alcanza internet; el audio se le entrega desde el almacén on-prem.
- RNF-02 ACK del webhook bajo carga con p95 acotado (medido en SPEC-042/THOR).

## Criterios de aceptación (verificables)
- [ ] El webhook/watcher recibe fichero + metadatos y responde ACK rápido; el audio queda cifrado en el almacén on-prem.
- [ ] Un reenvío con el mismo `call_id` **no** crea doble `call` ni doble trabajo STT (test de reentrega).
- [ ] Un evento sin mapeo de tenant produce **descarte auditado** y **cero** persistencia de contenido.
- [ ] Se crea `call` (SPEC-036) con `audio_ref` y se encola el trabajo en `stt:jobs`.
- [ ] (Si PBX externo) la descarga sale SOLO desde `recording_fetch_worker` y SOLO al host del PBX; un intento de descarga desde el STT/IA **falla** la build (`check-externos`).
- [ ] `check-externos-backend.sh` en verde; sin STT/TTS de terceros; host del PBX solo en el módulo del conector.

## Notas de seguridad (C2/C3)
- C2: la `call` respeta borrado lógico; el descarte sin mapeo no persiste contenido.
- C3: `verify_token`/firma/credenciales del PBX SOLO en env; nunca en repo/logs.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el audio se almacena **cifrado on-prem y nunca va a un tercero**. EXCEPCIÓN ACOTADA solo si el PBX es externo (ADR-010): la descarga es transporte, permitido SOLO desde `api`/`recording_fetch_worker` y SOLO al host del PBX; el STT/IA jamás obtiene esa ruta. Cambio sensible → aprobación del Lead + notificación Telegram (C6) si se habilita egress externo.

## Riesgos
- R-45 (egress del PBX): allowlist por ruta al host del PBX (ADR-010); STT/IA nunca importan el cliente de descarga; test negativo (SPEC-042).
- R-46 (idempotencia por `call_id`): dedup BD + worker; test de reentrega (SPEC-042).
- R-47 (cross-tenant): resolución de tenant + descarte auditado sin mapeo; RLS al persistir (ADR-008).
- R-43 (cifrado del audio): almacenamiento cifrado on-prem (SPEC-035).

## Checkpoints aplicables
- C2 (borrado lógico / descarte sin persistir). C3 (secretos en env). C4 (criterios verificables). C6 (egress externo si aplica). C8 (origen PLAN-004).

## Nota de diferimiento formal (post-revisión BLACK WIDOW/BLACK PANTHER/WOLVERINE)

El Lead decidió explícitamente **diferir** la implementación de la variante
"PBX notifica solo una URL" (en vez de adjuntar el fichero de audio) del
webhook de ingesta — es decir, la rama que, al recibir esa notificación,
encolaría en `recording_fetch_queue` (`recording:fetch:jobs`) para que
`recording_fetch_worker` descargue el audio (ADR-010).

- Esta rama **NO se implementa** en esta fase: el webhook actual
  (`app/integrations/pbx/webhook.py` o equivalente) atiende únicamente el
  camino feliz por defecto (SUP-42, PBX **on-prem** que entrega el fichero
  directamente).
- El código de transporte relacionado (`app/services/telefonia/pbx_client.py`,
  `app/workers/recording_fetch_worker.py`,
  `app/core/recording_fetch_queue.py`) queda como **capacidad lista pero
  inerte**: sin productor activo que encole en `recording:fetch:jobs` hoy
  (consistente con SUP-42 — el `recording_fetch_worker` vive bajo
  `profiles: ["pbx-externo"]` en `docker-compose.yml` y no se levanta con
  `docker compose up` por defecto).
- Activar el productor (la rama del webhook que encola en
  `recording_fetch_queue`) queda diferido a una **fase posterior**, sujeta a
  **aprobación explícita del Lead**, cuando se confirme un PBX externo real
  (`PBX_EXTERNAL_ENABLED=true`) — en ese momento se formalizará como SPEC
  independiente (o ampliación de esta), con su propio checkpoint C6 (egress
  externo, notificación Telegram) y revisión de seguridad dedicada.
- Hasta entonces, `recording_fetch_worker`/`pbx_client.py` siguen cubiertos
  por tests unitarios (`tests/test_pbx_client.py`) y por el guardarraíl de
  egress (`check-externos-backend.sh` §11,
  `tests/test_check_externos_pbx_allowlist_guardrail.py`,
  `tests/test_egress_topology_guardrail.py`), pero no se ejercitan end-to-end
  porque no hay productor real en el camino feliz actual.
