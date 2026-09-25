# SPEC-046 — Conector de media en vivo (extiende SPEC-037 de grabación a stream) 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, THOR, WOLVERINE · Prioridad: ALTA · Tipo: BACKEND/TELEFONÍA · Fase: F2
- Deriva de: PLAN-005 (F2, §3.1/§3.2/§3.7, §3.5) · Clasificación: SENSIBLE (`.no-externo`) · ADR-011/ADR-012 (extiende SPEC-037)
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

**Extender** el conector PBX de #4 (SPEC-037, `app/services/telefonia/`, hoy descarga de grabaciones post-hoc) a un **`voice_gateway`** que gestiona una **sesión de media en vivo** con el PBX: **stream RTP/WebSocket bidireccional** (audio-in del usuario → red interna hacia `voice_stt`; audio-out del `voice_tts` → PBX), **declaración de voz sintética al inicio de cada llamada** (ADR-012), y **resolución de tenant desde los metadatos de la llamada**; sin mapeo de tenant → escalación/descarte auditado. El transporte de media es el **único** egress posible de la fase, acotado por allowlist al host del PBX (ADR-011); si el PBX es on-prem, sin egress nuevo.

## Contexto

SPEC-037 ya resolvió el transporte del canal de voz (descarga de grabaciones, idempotencia por `call_id`, aislamiento del audio, allowlist al PBX si externo). Esta fase **no reinventa** ese conector: lo extiende de "traer un fichero ya generado" a "mantener un stream de media en vivo". El invariante de topología (§3.2) es duro: el `voice_gateway` vive en `app` (con egress acotado) y es el **único** componente que habla con el PBX; `voice_stt`/`voice_tts`/NLU viven en `ia_internal internal:true` y reciben/entregan audio **por la red interna**, jamás por red externa ni desde el PBX. Por P-M, el PBX se asume **on-prem preferido** (Asterisk/FreeSWITCH, sin egress nuevo); si es externo, aplica egress acotado (allowlist al host del PBX de media). La declaración de voz sintética (ADR-012) es un invariante verificable: suena al inicio de **cada** llamada antes de cualquier interacción del catálogo.

## Alcance

### IN
- `voice_gateway` en la red `app` (extiende `app/services/telefonia/` de SPEC-037): establece/termina la **sesión SIP/media** con el PBX y transporta **RTP/WebSocket bidireccional** (audio-in y audio-out).
- **Puente de media a la red interna:** entrega los frames de audio-in a `voice_stt` y recibe el audio-out de `voice_tts` **por la red interna** (`ia_internal`), sin exponer el PBX a los servicios de IA ni la IA al PBX.
- **Declaración de voz sintética al inicio de cada llamada** (ADR-012): reproduce el mensaje pregrabado "está hablando con un asistente virtual" antes de cualquier turno del catálogo.
- **Resolución de tenant** desde los metadatos de la llamada (DID/número marcado/trunk/headers SIP) → `tenant_id`; **sin mapeo → escalación a humano/descarte auditado** (nunca se procesa una llamada sin tenant resuelto).
- **Registro de sesión** de la llamada en vivo (inicio/fin, tenant, estado) preparando la persistencia en `call`/`call_transcript` (SPEC-036), reutilizando la idempotencia por `call_id` de SPEC-037.
- Manejo de fin de llamada (colgado por usuario o por escalación) que cierra la sesión de media y dispara la persistencia (SPEC-051).
- Allowlist por ruta al host del PBX de media dentro del `voice_gateway` (si PBX externo, ADR-011); inerte por defecto (P-M on-prem).

### OUT
- STT streaming que consume los frames (SPEC-047); bucle de diálogo/TTS/barge-in (SPEC-048); contrato de la transferencia a humano y monitor SPA (SPEC-049); persistencia final y retención (SPEC-051); medición de latencia de red/PBX (SPEC-050).
- Despliegue completo del PBX (dial-plan, colas ACD, troncales SIP): fuera (solo el conector de media en vivo).

## Dependencias
- Depende de SPEC-044 (infra `voice_gateway`/redes/allowlist) y SPEC-037 (conector PBX de #4, a extender). Prerequisito de SPEC-047/048. Se ancla en ADR-011 (egress acotado del PBX de media) y ADR-012 (declaración de voz sintética). Reutiliza SPEC-036 (`call`/`call_transcript`, idempotencia por `call_id`).

## Requisitos funcionales
- RF-01 El `voice_gateway` establece una sesión de media en vivo con el PBX (RTP/WebSocket bidireccional) y la termina limpiamente.
- RF-02 Los frames de audio-in llegan a `voice_stt` y el audio-out de `voice_tts` vuelve al PBX, todo por la red interna (la IA nunca habla con el PBX).
- RF-03 Al inicio de cada llamada se reproduce la declaración de voz sintética (ADR-012).
- RF-04 El tenant se resuelve desde los metadatos de la llamada; sin mapeo → escalación/descarte auditado.
- RF-05 (Si PBX externo) el transporte de media sale SOLO al host del PBX desde el `voice_gateway`.

## Requisitos no funcionales
- RNF-51 El audio/STT/TTS/IA nunca salen del host; el `voice_gateway` es el único con egress y solo al PBX de media (ADR-011).
- RNF-54 La declaración de voz sintética es un invariante: no hay ruta de código que inicie el diálogo del catálogo sin haberla emitido.
- RNF-07 Reproducible on-prem; suites #1-#4 verdes; el conector extiende SPEC-037 sin regresión.

## Criterios de aceptación (verificables)
- [ ] Con el simulador de llamada en vivo (SPEC-052), el `voice_gateway` establece y cierra una sesión de media bidireccional; el audio-in llega a `voice_stt` y el audio-out de `voice_tts` vuelve, por la red interna.
- [ ] La declaración de voz sintética se reproduce al inicio de cada llamada **antes** de cualquier turno del catálogo (test verificable).
- [ ] Una llamada con metadatos de tenant válidos resuelve el `tenant_id`; una sin mapeo → escalación/descarte **auditado** (no se procesa).
- [ ] (Si PBX externo) captura de red: el `voice_gateway` alcanza SOLO el host del PBX de media; ningún otro dominio; `voice_stt`/`voice_tts`/NLU/IA sin egress.
- [ ] (Si PBX on-prem, por defecto) **cero** egress público en la captura de red.
- [ ] El `voice_gateway` NO importa/invoca STT/TTS/IA directamente (solo por red interna/cola): introducir esa importación **falla** la build (`check-externos-backend.sh`).
- [ ] El fin de llamada cierra la sesión de media y deja la llamada lista para persistir por `call_id` (idempotente, SPEC-036/037).

## Notas de seguridad (C2/C3)
- C3: credenciales/tokens del PBX de media y claves TLS/WSS SOLO en env/secret manager con fail-fast `${VAR:?}`; nunca en repo/logs.
- C2: el registro de la llamada usa borrado lógico (hereda `call`/`call_transcript`, SPEC-036).

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el transporte de media es el **único** egress de la fase (ADR-011), y solo si el PBX es externo. El audio/STT/TTS/IA nunca salen; el `voice_gateway` es el único que habla con el PBX y jamás importa STT/TTS/IA. Habilitar egress externo = cambio sensible → aprobación del Lead + Telegram (C6).

## Riesgos
- R-59 (egress del PBX de media): allowlist por ruta al host del PBX en el `voice_gateway` (ADR-011); PBX on-prem preferido sin egress nuevo (P-M); test negativo (SPEC-051).
- R-54 (audio a terceros): el `voice_gateway` transporta media, no infiere; STT/TTS/IA aislados en `ia_internal`.
- R-55 (voz sintética engañosa): declaración obligatoria al inicio de cada llamada (ADR-012).
- R-60 (fuga cross-tenant): resolución de tenant desde metadatos + escalación/descarte sin mapeo; `call`/`call_transcript` con RLS efectiva (ADR-008).

## Checkpoints aplicables
- C3 (secretos en env). C4 (criterios verificables). C6 (cambio sensible: media en vivo/egress PBX, aprobación + Telegram). C8 (origen PLAN-005).
