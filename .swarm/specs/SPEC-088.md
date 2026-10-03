# SPEC-088 — Descarga de media de Instagram (`media_client.py`): confirmación BLOQUEANTE del host del CDN de Meta + allowlist de host por código + almacén cifrado (ADR-009) + gatillo condicional de ADR-017 (F3) 🔴 SENSIBLE

- Estado: APROBADA · Responsable: BLACK PANTHER · Colaboran/revisan: BLACK WIDOW (host/ADR/egress), WOLVERINE (allowlist CI), DOCTOR STRANGE (si el host es `graph.facebook.com`, cubierto por ADR-006 ampliado; si no, ADR-017) · Prioridad: ALTA · Tipo: BACKEND/TRANSPORTE/SEGURIDAD · Fase: F3
- Deriva de: PLAN-012 (F3, §2.IN.1.d/5, §3.2 N-6, §3.3, §4 tabla F3, §5, §6 R-115 (y R-114 parcial), §7 CE-118/CE-119(parcial), **§11.2 (decisión diferida — NO se reabre)**) · Clasificación: SENSIBLE (`.no-externo`) · **Depende de SPEC-087** (el worker encola la descarga) **y SPEC-085** (allowlist por ruta + secretos) · Espeja `backend/app/integrations/whatsapp/media_client.py` (SPEC-054, ADR-006/007/009), `_validate_graph_host` de `graph_client.py`, `app/services/telefonia/audio_store.py` (almacén cifrado) · ADR-006/009/017(condicional)

## Objetivo

Descargar los **adjuntos/imágenes** de los DMs de Instagram (Q2=B) a un **almacén cifrado en reposo** (patrón ADR-009), espejando `media_client.py` de WhatsApp, con **allowlist de host por código** (patrón `_validate_graph_host`) y la idempotencia/robustez del original. **CRÍTICO (PLAN-012 §11.2, decisión de arquitecto ya fijada, no se reabre):** el **PRIMER paso y un criterio de aceptación BLOQUEANTE** de esta SPEC es **confirmar el hostname REAL del CDN de media de Meta para Instagram contra la documentación vigente de Meta** ANTES de fijar cualquier allowlist de egress. Según el resultado: (a) si el host es `graph.facebook.com` → queda cubierto por la **ampliación de ADR-006** (SPEC-085), **sin ADR nuevo**; (b) si el host es **distinto** (p. ej. un CDN propio de Meta para IG) → esta SPEC **crea ADR-017** ("egress acotado del CDN de media de Instagram") con allowlist de host por código + entrada nueva en `check-externos-backend.sh` (`next_adr` → 18).

## Contexto

Verificado en el repo (fuente de verdad — 2026-10-03):
- **`media_client.py` de WhatsApp es la plantilla EXACTA** (SPEC-054): dos GETs (resolver URL temporal + descargar binario) con `_validate_graph_host` reutilizado por import de `graph_client.py` (NO reimplementado), reintentos backoff ante 429/5xx, `GraphApiHostError`/`MediaDownloadError`/`MediaDownloadTransientError`; `download_and_store_voice_note` orquesta: idempotencia (si `audio_ref` ya poblado → no-op), persistencia cifrada vía `audio_store.store_audio` (ADR-009), token Bearer solo en header, nunca en logs; `GraphApiHostError` se **re-propaga** (incidente de seguridad, no fallo "normal"); fallos de descarga se auditan sin propagar. El STT/IA **nunca** importa este módulo (verificado por `check-externos-backend.sh` sección 7, sub-bloque de imports prohibidos).
- **El almacén cifrado existe** (`app/services/telefonia/audio_store.py`, ADR-009): `build_audio_ref` + `store_audio` cifran el binario en reposo; `AUDIO_ENCRYPTION_KEY` con fail-fast (`config.py`). Para Instagram se reutiliza el mismo almacén cifrado (imágenes/adjuntos son dato personal; se cifran igual).
- **La duda del host (§11.2, R-115):** el CDN de media de Meta para Instagram **normalmente** usa hosts distintos de `graph.facebook.com` (dominios tipo `*.cdninstagram.com` / `scontent.*` / `lookaside.*` servidos por Meta), PERO DOCTOR STRANGE **NO pudo confirmar el hostname exacto con certeza** al redactar esta SPEC (sin acceso verificable a la documentación vigente de Meta desde el entorno de redacción; la API de Meta evoluciona). Por eso el plan **fija el procedimiento de confirmación + el gatillo del ADR**, no el host. Fijar una allowlist sobre un host no confirmado sería un riesgo de seguridad (R-114/R-115): o rompe la descarga (host equivocado) o abre un egress a un host incorrecto.
- **BLOQUEO DE META APP REVIEW (R-110):** la descarga se verifica con el simulador firmado (payloads con attachments) + cuentas de prueba; NO con media de usuarios reales hasta que Meta apruebe (Q1=B, DIFERIDO al Lead).

## Alcance

### IN
- **PASO 0 (BLOQUEANTE, antes de escribir cualquier allowlist):** confirmar el hostname REAL del CDN de media de Meta para Instagram contra la **documentación vigente de Meta** (Instagram Messaging API / Handling Attachments). Registrar el host confirmado y la referencia de la documentación en el PR/commit de esta SPEC (evidencia auditable). **No se escribe ninguna allowlist hasta tener esta confirmación.**
- **`app/integrations/instagram/media_client.py`** (espejo de `whatsapp/media_client.py`): descarga del/los adjunto(s) referenciados en `event.attachments[].url` (SPEC-086) con **allowlist de host por código** (función de validación por `hostname`/`scheme=https`/sin userinfo, mismo criterio EXACTO que `_validate_graph_host`), reintentos backoff ante 429/5xx, token Bearer (`INSTAGRAM_PAGE_ACCESS_TOKEN`) solo en header y nunca en logs; orquestador `download_and_store_instagram_media` con idempotencia (no-op si ya descargado), persistencia cifrada vía `audio_store`/almacén cifrado equivalente (ADR-009), `GraphApiHostError`-equivalente re-propagado como incidente, fallos de descarga auditados sin propagar.
- **Allowlist de host según PASO 0:**
  - **Caso (a) host = `graph.facebook.com`:** reutiliza `_validate_graph_host`/la allowlist de la sección 7 (ya extendida a `app/integrations/instagram/` por SPEC-085) — **sin ADR nuevo** (cubierto por ADR-006 ampliado).
  - **Caso (b) host distinto:** define la allowlist de host por código para ESE host confirmado (patrón `_validate_graph_host`, host EXACTO, `https`, sin userinfo/subdominios no autorizados) + **nueva entrada en `check-externos-backend.sh`** (nueva sección "allowlist por ruta del CDN de media de Instagram", espejo estructural de la sección 7, SOLO dentro de `app/integrations/instagram/`, y verificación de que STT/IA NO lo importan) + **crear ADR-017** (ver "Notas de ADR").
- **Enganche desde el worker de ingesta (SPEC-087):** el worker encola/invoca la descarga tras persistir el `Message`; la media queda cifrada en reposo; el camino de texto no se ve afectado.

### OUT
- Notas de voz entrantes de IG (Q2=C, OUT de la V1) — no se toca el pipeline STT.
- Envío saliente/statuses (SPEC-089).
- **Decidir el host sin confirmarlo** (PROHIBIDO, §11.2): el host se confirma contra la doc de Meta, no se adivina.

## Dependencias
- **Depende de SPEC-087** (el worker encola la descarga tras persistir) y **SPEC-085** (allowlist por ruta de `app/integrations/instagram/`, secreto `INSTAGRAM_PAGE_ACCESS_TOKEN`). Reutiliza `audio_store`/almacén cifrado (ADR-009) y el patrón `_validate_graph_host`. Es la fase de **mayor incertidumbre** (host del CDN → posible ADR-017). Puede correr en paralelo a SPEC-089 tras SPEC-087.

## Requisitos funcionales
- RF-01 (BLOQUEANTE) El host del CDN de media de Meta para Instagram se **confirma contra la documentación vigente de Meta ANTES** de fijar la allowlist; la confirmación + la referencia quedan registradas (evidencia auditable).
- RF-02 `media_client.py` descarga el/los adjunto(s) con allowlist de host por código (host EXACTO confirmado, `https`, sin userinfo); un host distinto aborta con error antes de abrir conexión.
- RF-03 La media se cifra en reposo (ADR-009); idempotencia: una reentrega del mismo adjunto/mensaje NO vuelve a descargar.
- RF-04 Token Bearer solo en el header `Authorization`; jamás en logs ni en mensajes de excepción (C3); fallos auditados sin contenido ni URL sensible en claro.
- RF-05 Según PASO 0: caso (a) sin ADR nuevo (ADR-006 ampliado); caso (b) ADR-017 creado + nueva entrada en `check-externos-backend.sh`.
- RF-06 El STT/IA NO importa `media_client.py` de IG (verificación activa en `check-externos-backend.sh`, espejo de la de WhatsApp, SPEC-054).

## Requisitos no funcionales
- RNF-HOST-CONFIRMADO Ninguna allowlist de egress se fija sobre un host no confirmado (R-114/R-115); la confirmación es un gate duro.
- RNF-CIFRADO La media se cifra en reposo (ADR-009); descifrado solo en el borde autorizado; retención según la política existente.
- RNF-C3 `INSTAGRAM_PAGE_ACCESS_TOKEN` solo desde `Settings`, solo en header, nunca en logs.
- RNF-EGRESS-ACOTADO El egress de media vive SOLO en `app/integrations/instagram/`; la IA sigue sin egress (ADR-005); `check-externos-backend.sh` verde.
- RNF-NO-REGRESION Cero regresión del `media_client.py` de WhatsApp ni del STT (R-117).

## Criterios de aceptación (verificables)
- [ ] **(BLOQUEANTE)** El host del CDN de media de IG está confirmado contra la doc vigente de Meta, con la referencia registrada en el PR/commit, ANTES de cualquier allowlist (RF-01).
- [ ] La descarga usa allowlist de host por código (host EXACTO confirmado); un host distinto/subdominio no autorizado/esquema `http`/userinfo embebido aborta antes de conectar (CE-118).
- [ ] La media queda cifrada en reposo (ADR-009); una reentrega del mismo adjunto no re-descarga (idempotencia).
- [ ] Caso (a) host = `graph.facebook.com`: `check-externos-backend.sh` verde con la allowlist de la sección 7 (ya extendida); **sin ADR nuevo** (CE-118).
- [ ] Caso (b) host distinto: **ADR-017 presente** (egress acotado del CDN de media de IG) + nueva sección en `check-externos-backend.sh` (SOLO en `app/integrations/instagram/`) verde; `next_adr` → 18 (CE-118).
- [ ] El STT/IA NO importa `media_client.py` de IG (verificación activa del script).
- [ ] Grep de logs: el token Bearer y las URLs temporales con credenciales no aparecen en logs (C3).

## Notas de ADR (gatillo condicional — PLAN-012 §11.2, NO se reabre)
- **DOCTOR STRANGE NO pudo confirmar el hostname del CDN de media de Instagram con certeza al redactar esta SPEC**, por lo que **NO crea ADR-017 ahora**. Se deja como instrucción EXACTA y condicional para el implementador (BLACK PANTHER, revisado por BLACK WIDOW):
  1. Ejecutar el PASO 0 (confirmar el host contra la doc vigente de Meta).
  2. **Si el host es `graph.facebook.com`** → NO crear ADR; referenciar la ampliación de ADR-006 (SPEC-085) y usar la allowlist de la sección 7 ya extendida.
  3. **Si el host es distinto** → **crear `ADR-017`** (`.swarm/adrs/ADR-017-egress-acotado-cdn-media-instagram.md`), consumiendo `next_adr: 17 → 18`, siguiendo el **mismo patrón que ADR-016** (contrato de egress/seguridad, "consume no rediseña ADR-005/006"), con esta plantilla de contenido:
     - **Cabecera:** autor DOCTOR STRANGE; proyecto; clasificación SENSIBLE; origen PLAN-012 §11.2 / SPEC-088; Estado "Aceptada" (tras aprobación del Lead del bloque); Fecha; Plan PLAN-012.
     - **Contexto:** la V1 de IG incluye media (Q2=B); el CDN de media de Meta para IG usa el host `<HOST CONFIRMADO>`, distinto de `graph.facebook.com` → borde de egress NUEVO no cubierto por ADR-006.
     - **Decisión (reglas duras):** (1) egress permitido SOLO desde `app/integrations/instagram/media_client.py` (+ el worker que lo invoca) y SOLO hacia `<HOST CONFIRMADO>` por `https`; (2) allowlist de host **por código** (patrón `_validate_graph_host`, host EXACTO, sin userinfo/subdominios) + nueva sección en `check-externos-backend.sh`; (3) la IA sigue sin egress (ADR-005, intacto); (4) la media se cifra en reposo (ADR-009); (5) el token Bearer solo en header, nunca en logs (C3).
     - **Alternativas consideradas:** asumir `graph.facebook.com` (rechazada: host no confirmado = R-114/R-115); no descargar media (rechazada: contradice Q2=B); allowlist de red sin distinción por módulo (rechazada: no impide transporte en módulos indebidos).
     - **Consecuencias:** borde de egress nuevo acotado y auditable; refuerza (no relaja) el aislamiento; `check-externos-backend.sh` verde; criterio de verificación objetivo (egress solo a `<HOST CONFIRMADO>` desde `instagram/media_client.py`; STT/IA sin egress; sin token en logs).
     - **Referencias:** PLAN-012 §11.2, SPEC-085 (ADR-006 ampliado), SPEC-088, ADR-005/006/009/016.

## Notas de seguridad (C2/C3)
- C2: errores de descarga loguean solo metadatos (`instagram_account_id`/`mid`/`message_id`), nunca el contenido ni la URL con credenciales.
- C3: 🔴 token Bearer solo en header, nunca en logs; `AUDIO_ENCRYPTION_KEY`/almacén cifrado por env con fail-fast.

## Restricción SENSIBLE / egress
- 🔴 SENSIBLE: borde de egress de media; la decisión del host (§11.2) NO se reabre — se confirma, no se adivina. La media se cifra en reposo (ADR-009), se descarga SOLO desde `app/integrations/instagram/`, con el host confirmado (cubierto por ADR-006 ampliado o ADR-017). La IA sigue sin egress (ADR-005). **Bloqueo de Meta App Review (R-110):** la descarga se verifica con el simulador firmado (attachments) + cuentas de prueba, NO con media de usuarios reales hasta que Meta apruebe (Q1=B, DIFERIDO al Lead).

## Riesgos
- R-115 (**top** — host del CDN no confirmado/cambia): PASO 0 BLOQUEANTE (confirmar contra doc de Meta) + gatillo de ADR-017; nunca se fija allowlist sobre host no confirmado.
- R-114 (egress mal extendido, parcial): allowlist de host por código SOLO en `app/integrations/instagram/`; verificación de que STT/IA no lo importan.
- R-117 (regresión de WhatsApp/STT): `media_client.py` de IG es aditivo; no toca el de WhatsApp ni el STT.
- R-110 (bloqueo de Meta App Review): verificación con simulador + cuentas de prueba; activación real diferida al Lead (C6).

## Checkpoints aplicables
- C2 (minimización en logs). C3 (token/clave de cifrado fuera de logs, 🔴 crítico). C4 (criterios verificables, con la salvedad E2E de R-110). C8 (origen PLAN-012 §11.2 / `prompt-lab/prompts/PROMPT-012-INSTAGRAM-DM.md`).
