# SPEC-054 — Descarga de media de WhatsApp (transporte, sin egress nuevo) + almacenamiento cifrado 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, THOR, WOLVERINE · Prioridad: ALTA · Tipo: BACKEND/INTEGRACIÓN · Fase: F1
- Deriva de: PLAN-006 (F1, §2.2/§3.2/§3.3) · Clasificación: SENSIBLE (`.no-externo`) · ADR-006/ADR-007/ADR-009
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Añadir la capacidad de **descargar el binario de una nota de voz de WhatsApp** desde la Graph API de Meta y **almacenarlo cifrado on-prem** (`audio_store.py`, SPEC-035), persistiendo una `audio_ref` opaca en el `Message` de audio (SPEC-053). La descarga vive **exclusivamente en `app/integrations/whatsapp/`** (mismo módulo que ya envía, `graph_client.py`), con salida **SOLO** al host ya permitido `graph.facebook.com` (ADR-006/SPEC-024): **cero egress nuevo** — solo un verbo GET adicional sobre el host y el token ya autorizados. El `stt_worker`/IA **nunca** descarga (recibe el audio del almacén, ADR-009).

## Contexto

`graph_client.py` es hoy el único lugar autorizado a llamar a `graph.facebook.com` (validación de host EXACTA por `urlparse().hostname`, allowlist por código, ADR-006). Solo **envía** (POST a `/messages`). La descarga de media de WhatsApp requiere **dos GET** al mismo host: (1) `GET graph.facebook.com/<version>/<media-id>` para resolver la URL temporal y el `mime_type`; (2) `GET <url-temporal>` (también host de Meta) con el `Authorization: Bearer <token>` para bajar el binario. Se reutiliza el mismo cliente/validación de host (`_validate_graph_host`) y el mismo manejo de secretos (token solo en header, nunca en logs, C3). El almacén cifrado `audio_store.py` (SPEC-035) ya cifra en reposo y devuelve una `audio_ref` opaca: es el mismo `store_audio`/`load_audio` que usa la voz telefónica, sin excepción.

## Alcance

### IN
- Función de descarga en `app/integrations/whatsapp/` (nueva `media_client.py` o método hermano en `graph_client.py`): resuelve la URL temporal del media (`GET graph.facebook.com/<version>/<media-id>`) y descarga el binario (`GET <url-temporal>` con token), validando que **ambos** hosts sean EXACTAMENTE `graph.facebook.com` (misma `_validate_graph_host`, allowlist por código, ADR-006) antes de abrir cualquier conexión. Un host distinto **aborta** (reutiliza `GraphApiHostError`).
- Reintento acotado con backoff ante URL temporal expirada (R-67) o 429/5xx (mismo patrón de reintentos idempotentes de `graph_client._post_with_retries`); descarga el binario **inmediatamente** tras resolver la URL para minimizar la ventana de expiración.
- Almacenamiento del binario en `audio_store.py` **cifrado on-prem** (SPEC-035) → obtención de `audio_ref` opaca → persistencia en `messages.audio_ref` (SPEC-053) bajo RLS del tenant.
- **Idempotencia (ADR-007, sin nada nuevo):** no re-descargar si `messages.audio_ref` ya existe para ese `Message`/`wamid` (guarda de reentrega); un segundo webhook del mismo `wamid` no vuelve a bajar el binario.
- Persistencia del `mime_type` y (si Meta la provee) la duración en los campos opcionales del `Message` (SPEC-053, `audio_duracion_seg`); errores de descarga **auditados** (`transcripcion_estado="error"` cuando la descarga falla en definitiva, sin bloquear el hilo del worker de ingesta).
- (P5, verificado al implementar) Si `stt_engine.py`/`faster-whisper` no ingiere OGG/Opus directamente, la transcodificación local (ffmpeg, sin egress) se decide y ubica aquí o en SPEC-056 — ver §"Nota P5" abajo.

### OUT
- Reconocimiento de `type=="audio"` en el parser y encolado en `stt:jobs` (SPEC-055).
- Transcripción y sink de escritura (SPEC-056); enriquecimiento (SPEC-057); retención del `audio_ref` (SPEC-058, extiende SPEC-041).
- Media de WhatsApp que no sea audio (imágenes/documentos/vídeo).

## Dependencias
- Depende de SPEC-053 (`messages.audio_ref`) y reutiliza SPEC-035 (almacén cifrado) y SPEC-024/ADR-006 (host `graph.facebook.com` ya permitido). Es un prerequisito de SPEC-055 (ingesta). Se ancla en ADR-006 (transporte WhatsApp), ADR-007 (idempotencia `wamid`) y ADR-009 (audio cifrado, STT no descarga).

## Requisitos funcionales
- RF-01 La función resuelve la URL temporal del media y descarga el binario **solo** desde `graph.facebook.com` (ambos GET validados por host EXACTO).
- RF-02 El binario se almacena **cifrado on-prem** (`audio_store.py`) y su `audio_ref` opaca se persiste en `messages.audio_ref` bajo RLS.
- RF-03 Reentrega del mismo `wamid`/`Message`: si `audio_ref` ya existe, **no** se re-descarga (idempotencia, ADR-007).
- RF-04 Un fallo de descarga (URL expirada tras reintentos, 4xx definitivo) se **audita** (`transcripcion_estado="error"`) sin reventar el worker de ingesta.
- RF-05 La descarga la ejecuta **solo** el módulo `app/integrations/whatsapp/`; el `stt_worker`/IA nunca importa ni ejecuta esta función.

## Requisitos no funcionales
- RNF-41 **Cero egress nuevo:** único host de salida `graph.facebook.com`, mismo módulo ya autorizado (ADR-006). `check-externos-backend.sh` sigue verde sin allowlist nueva; solo verifica que la descarga viva **dentro** del módulo WhatsApp y **no** en `stt_worker`/IA.
- RNF-43 El binario se cifra en reposo (SPEC-035) desde el primer instante; nunca se persiste en claro en disco.
- RNF-05 Reintentos idempotentes con backoff acotado; un fallo transitorio no duplica descargas ni bloquea el loop.

## Criterios de aceptación (verificables)
- [ ] Con un `media-id` ficticio y un doble-GET simulado a `graph.facebook.com`, la función descarga el binario y lo almacena **cifrado**; `messages.audio_ref` queda poblado.
- [ ] Un intento de resolver/descargar desde un host distinto de `graph.facebook.com` **aborta** (`GraphApiHostError`) antes de abrir la conexión (test de allowlist por código).
- [ ] Reentrega del mismo `wamid` con `audio_ref` ya presente **no** re-descarga (test de idempotencia).
- [ ] Una URL temporal expirada dispara reintento con backoff; si falla en definitiva, se marca `transcripcion_estado="error"` auditado sin reventar (test de fallo controlado).
- [ ] El binario está **cifrado en reposo** (inspección del almacén); no accesible en claro.
- [ ] `check-externos-backend.sh` en verde; la función de descarga **no** se importa desde `stt_worker`/`ia`/workers de IA (grep/guardarraíl de egress); único host `graph.facebook.com`.
- [ ] El `access_token` viaja solo en el header `Authorization`; **nunca** aparece en logs ni en mensajes de excepción (C3).

## Notas de seguridad (C2/C3)
- C2: el `audio_ref` respeta borrado lógico del `Message` (SPEC-053); la purga física del blob es de SPEC-058.
- C3: `whatsapp_token` SOLO desde `Settings` (env); nunca en repo/logs; el token no se incluye en ningún `logger.*` (mismo criterio que `graph_client`).

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el audio (dato personal / posible PHI) se almacena **cifrado on-prem y nunca va a un tercero**. La descarga es **transporte** ya cubierto por ADR-006/SPEC-024 (host `graph.facebook.com`, módulo WhatsApp): **NO es egress nuevo**, no requiere ADR de egress (a diferencia de ADR-010). El `stt_worker`/IA jamás obtiene esta ruta (ADR-009). Cualquier host distinto está PROHIBIDO por código.

## Nota P5 (transcodificación OGG/Opus)
- Las notas de voz de WhatsApp llegan típicamente en **OGG/Opus**. Al implementar se **verifica** si `stt_engine.py`/`faster-whisper` ingiere OGG/Opus directamente (vía ffmpeg, dependencia habitual del stack STT). Si **sí**, no se añade paso de transcodificación. Si **no**, se añade un paso de **decodificación local (ffmpeg), sin egress**, ubicado antes de encolar/transcribir (aquí o en SPEC-056). La decisión y su ubicación quedan documentadas en la SPEC implementada; en ningún caso introduce salida externa.

## Riesgos
- R-61 (audio/inferencia a terceros): descarga solo a `graph.facebook.com` desde el módulo WhatsApp; STT/IA nunca descarga; guardarraíl de egress (SPEC-060).
- R-63 (cifrado del audio): `audio_store.py` cifrado sin excepción (SPEC-035); permisos mínimos.
- R-65 (idempotencia `wamid`): no re-descargar si `audio_ref` existe (ADR-007); test de reentrega.
- R-67 (URL temporal expira): descarga inmediata tras resolver; reintento con backoff; fallo definitivo auditado.

## Checkpoints aplicables
- C2 (borrado lógico). C3 (secretos en env). C4 (criterios verificables). C8 (origen PLAN-006). (Sin C6: no hay egress nuevo — mismo host ya autorizado.)
