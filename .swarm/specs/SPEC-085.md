# SPEC-085 — Datos del canal Instagram (`instagram_accounts` + `resolve_tenant_by_instagram_account_id`) + egress acotado extendido + secretos `INSTAGRAM_*` + ampliación de ADR-006 (F0) 🔴 SENSIBLE

- Estado: CERRADA · Responsable: BLACK PANTHER · Colaboran/revisan: BLACK WIDOW (egress/secretos), WOLVERINE (allowlist CI/no-regresión), DOCTOR STRANGE (ADR-006 ampliado) · Prioridad: ALTA · Tipo: DATOS/INFRA/SEGURIDAD · Fase: F0
- Deriva de: PLAN-012 (F0, §2.IN.2/5/6, §3.2 N-2/N-3/N-4, §3.3, §3.4, §4 tabla F0, §5, §6 R-111/R-113/R-114/R-117, §7 CE-116/CE-118/CE-120, §11.1) · Clasificación: SENSIBLE (`.no-externo`) · **No depende de fases previas de PLAN-012 (habilita todo el canal)** · Consume/espeja `backend/app/models/whatsapp_account.py`, la migración de `resolve_tenant_by_phone_number_id` (`54c75efefe3c`), `backend/app/core/config.py` (`_require_strong_secret`, bloque WhatsApp `config.py:176–239`), `backend/check-externos-backend.sh` (sección 7), `.env.example` (bloque WhatsApp), ADR-004/006/007/008 · **Habilita SPEC-086..091**

## Objetivo

Crear la **capa de datos y de arranque del canal Instagram** espejando el canal WhatsApp ya en producción, sin rediseñar nada del dominio: (1) tabla `instagram_accounts` (espejo exacto de `whatsapp_accounts`, bajo RLS `ENABLE+FORCE`, borrado lógico `activo=False`), (2) función SQL `resolve_tenant_by_instagram_account_id(text)` (`SECURITY DEFINER`, `STABLE`, solo lectura, `search_path` fijo, `REVOKE ... FROM PUBLIC` + `GRANT EXECUTE` a `omnicore_app`), siguiendo EXACTAMENTE el patrón de `resolve_tenant_by_phone_number_id` (ADR-008), (3) migración Alembic **aditiva** (no destructiva), (4) documentar la **nota de diseño de idempotencia reutilizando `messages.wamid`** para el `mid` de Instagram (Q4=A, PLAN-012 §3.4), (5) extender la **allowlist por ruta** de `check-externos-backend.sh` a `app/integrations/instagram/` para `graph.facebook.com`, (6) secretos `INSTAGRAM_*` con el **mismo fail-fast** de `config.py` + placeholders en `.env.example`, y (7) **ampliar ADR-006** (el envío de Instagram va al mismo host `graph.facebook.com` ya autorizado — no es egress nuevo, es la misma excepción acotada de transporte a Meta extendida a un segundo módulo de conector).

## Contexto

Verificado en el repo (fuente de verdad, no asunciones — 2026-10-03):
- **CERO datos/routing de Instagram hoy.** `app/integrations/` solo tiene `whatsapp/` y `pbx/`; no existe `instagram_accounts`, ni función de routing de IG, ni secretos `INSTAGRAM_*`.
- **`whatsapp_accounts` es la plantilla EXACTA** (`backend/app/models/whatsapp_account.py`): hereda `TimestampMixin, TenantMixin, SoftDeleteMixin`; `phone_number_id String(64) UNIQUE index`, `display_phone_number`, `etiqueta`; RLS `ENABLE+FORCE` (es `TENANT_SCOPED`, un tenant nunca enumera los números de otro); baja = `activo=False` (nunca DELETE físico, C2).
- **La resolución pre-tenant NO se hace con SELECT directo** (devolvería 0 filas bajo RLS sin `app.tenant_id` fijado, fail-closed con el rol `omnicore_app` NOSUPERUSER NOBYPASSRLS, ADR-008): se invoca una función `SECURITY DEFINER` propiedad del owner. `resolve_tenant_by_phone_number_id(text)` (migración `54c75efefe3c`, ADR-008) es la plantilla: `LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public`, `SELECT tenant_id ... WHERE phone_number_id = :p AND activo LIMIT 1`, `REVOKE ALL ... FROM PUBLIC`, `GRANT EXECUTE ... TO omnicore_app`. Invocada por el worker con `SELECT resolve_tenant_by_...()` en su propia transacción de solo lectura (`whatsapp_inbound_worker._resolve_tenant_id`, líneas 206–219).
- **El dominio ya admite `canal="instagram"` SIN migración de datos:** `Conversation.canal` es `String(50)` libre; `app/schemas/conversation.py:15` ya incluye `"instagram"` en `CANALES_VALIDOS`. `Message.wamid` es `String(128)` UNIQUE nullable — clave de idempotencia reutilizable (Q4=A, §3.4).
- **Egress acotado (ADR-006, `check-externos-backend.sh` sección 7):** `GRAPH_ALLOWED_MODULES=("app/integrations/whatsapp")` — `graph.facebook.com` SOLO dentro de ese módulo; las secciones 8-9 verifican que WhatsApp no importa IA ni la IA importa `httpx`. Un módulo nuevo `app/integrations/instagram/` exige **añadir `app/integrations/instagram` a `GRAPH_ALLOWED_MODULES`** y replicar las verificaciones 8-9 para el módulo de IG.
- **Fail-fast de secretos (`config.py`):** `_require_strong_secret` (líneas 661–699) exige secreto robusto fuera de `development` (obligatorio, no débil, ≥`_MIN_SECRET_LENGTH`, `ConfigurationError` al arrancar si no se cumple). El bloque WhatsApp (`config.py:176–239`) usa este helper para `WHATSAPP_APP_SECRET`/`WHATSAPP_VERIFY_TOKEN`/`WHATSAPP_TOKEN` y lee por `os.getenv` los no-secretos (`WHATSAPP_API_VERSION` default `v21.0`, etc.). El host queda SIEMPRE fijo en código (allowlist), la versión es configurable.

## Alcance

### IN
- **Modelo `app/models/instagram_account.py`** (`InstagramAccount`), espejo de `WhatsappAccount`: hereda `TimestampMixin, TenantMixin, SoftDeleteMixin`; `instagram_business_account_id String(64) NOT NULL UNIQUE index` (clave de routing, N-2), `username/display_name String | None` (informativo), `etiqueta String(255) | None` (administración). RLS `ENABLE+FORCE` (entidad `TENANT_SCOPED`, mismo criterio que `whatsapp_accounts`). Baja lógica `activo=False` (C2).
- **Función SQL `resolve_tenant_by_instagram_account_id(p_instagram_business_account_id text) RETURNS uuid`** — copia literal del patrón de `resolve_tenant_by_phone_number_id` (ADR-008): `LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public`, de solo lectura, acotada a una fila (`instagram_business_account_id = :p AND activo = true LIMIT 1`), propiedad del rol owner, `REVOKE ALL ON FUNCTION ... FROM PUBLIC` + `GRANT EXECUTE ON FUNCTION ... TO omnicore_app`.
- **Migración Alembic aditiva** (no destructiva, no toca `messages`/`whatsapp_accounts`/`conversations`): crea `instagram_accounts` con sus índices/UNIQUE + RLS `ENABLE+FORCE` + política de aislamiento por `tenant_id` (mismo estilo que `whatsapp_accounts`) + la función `SECURITY DEFINER` + sus GRANT/REVOKE. `downgrade` revierte sin tocar datos de otras tablas.
- **Nota de diseño de idempotencia (§3.4, Q4=A)** documentada en el docstring del modelo y en un comentario junto a `Message.wamid`: la columna `messages.wamid` pasa a representar el **"id de mensaje del canal externo" genérico** (WhatsApp guarda `wamid`, Instagram guarda `mid`); NO se renombra ni se añade columna (decisión de arquitecto, §3.4); sin colisión semántica porque los espacios de id de ambos canales no se solapan en la práctica y la UNIQUE es la garantía dura (ADR-007). BLACK PANTHER valida que **ningún código asume formato de WhatsApp al leer la columna** (R-113).
- **Allowlist por ruta de IG en `check-externos-backend.sh`:** añadir `app/integrations/instagram` a `GRAPH_ALLOWED_MODULES` (sección 7); replicar las verificaciones 8-9 para el módulo de IG (el módulo `instagram/` NO importa Ollama/IA/`app.services.rag`/`app.workers`; la IA NO importa el `httpx` de transporte de IG). El script sigue verde.
- **Secretos `INSTAGRAM_*` en `config.py`** (bloque nuevo, espejo del de WhatsApp, `config.py:176–239`): `INSTAGRAM_APP_SECRET` (HMAC de `X-Hub-Signature-256`) y `INSTAGRAM_VERIFY_TOKEN` (challenge GET) vía `_require_strong_secret`; `INSTAGRAM_PAGE_ACCESS_TOKEN` (Bearer de la Graph API de IG) vía `_require_strong_secret`; `INSTAGRAM_BUSINESS_ACCOUNT_ID` (fallback, `os.getenv`, no secreto fuerte); `INSTAGRAM_API_VERSION` (`os.getenv`, default alineado con `whatsapp_api_version`, p.ej. `v21.0`; el HOST queda FIJO en código, nunca configurable). `.env.example` con placeholders (sin secretos reales), espejo del bloque WhatsApp (`.env.example:253–293`).
- **Ampliación de ADR-006** (editada por DOCTOR STRANGE en ESTA SPEC): el egress de transporte a `graph.facebook.com` abarca ahora WhatsApp **e** Instagram; se añade `app/integrations/instagram/` a la allowlist por ruta; NO es una decisión de egress nueva (misma excepción acotada de transporte a Meta, no inferencia) → **no consume `next_adr`** (PLAN-012 §11.1). Ver "Notas de ADR" abajo.

### OUT
- `webhook.py`/`inbound_parser.py` de IG (SPEC-086), worker de ingesta (SPEC-087), `media_client.py` (SPEC-088), `graph_client.py`/worker de envío (SPEC-089) → esta SPEC solo deja los **datos, el routing, el egress y los secretos** listos.
- Cualquier egress real a Meta (esta SPEC no abre conexiones; solo prepara la allowlist y los secretos).
- Renombrar `messages.wamid` o añadir una columna de idempotencia nueva (§3.4: PROHIBIDO, se reutiliza la columna existente).
- ADR-017 (condicional, se evalúa en SPEC-088 según el host del CDN de media — §11.2).

## Dependencias
- No depende de fases previas de PLAN-012 — es la fase de arranque (F0) que **habilita** SPEC-086..091. Reutiliza el patrón de `whatsapp_accounts`/ADR-008/ADR-007/ADR-006 sin rediseñarlos. Ruta crítica: **F0 (esta) → F1 (SPEC-086) → F2 (SPEC-087) → {F3 ‖ F4} → F5 → F6**.

## Requisitos funcionales
- RF-01 `instagram_accounts` creada con `instagram_business_account_id` UNIQUE indexado, `tenant_id`, borrado lógico `activo`, RLS `ENABLE+FORCE`; un tenant NO puede leer/enumerar las cuentas de IG de otro tenant (RNF-RLS).
- RF-02 `resolve_tenant_by_instagram_account_id(text)` (`SECURITY DEFINER`, solo lectura, `search_path` fijo) resuelve el tenant de un `instagram_business_account_id` **sin** `app.tenant_id` fijado, ejecutada por `omnicore_app`; un id sin fila (o `activo=false`) devuelve `NULL`.
- RF-03 Migración Alembic aditiva aplica y revierte limpiamente contra Postgres real sin tocar datos de `messages`/`whatsapp_accounts`/`conversations`.
- RF-04 `check-externos-backend.sh` verde con `app/integrations/instagram` en la allowlist por ruta de `graph.facebook.com` y las verificaciones 8-9 replicadas para IG.
- RF-05 `INSTAGRAM_APP_SECRET`/`INSTAGRAM_VERIFY_TOKEN`/`INSTAGRAM_PAGE_ACCESS_TOKEN` con fail-fast fuera de development (`_require_strong_secret`); arranque falla si faltan fuera de development; `.env.example` con placeholders.
- RF-06 ADR-006 ampliado (texto editado) para reflejar el egress de transporte de IG sobre `graph.facebook.com`.

## Requisitos no funcionales
- RNF-RLS El aislamiento multi-tenant de `instagram_accounts` se apoya en `omnicore_app` NOSUPERUSER NOBYPASSRLS (ADR-004/008); la resolución pre-tenant es la ÚNICA excepción, acotada por la función `SECURITY DEFINER`.
- RNF-IDEMPOTENCIA-GENERICA `messages.wamid` conserva su nombre y amplía su significado conceptual (§3.4); no se renombra ni se duplica; ningún código asume formato de WhatsApp al leerla (R-113, verificado por BLACK PANTHER).
- RNF-EGRESS-NO-NUEVO El envío de IG usa el MISMO host `graph.facebook.com` ya autorizado (ADR-006); la allowlist se **extiende por ruta**, no se relaja; la IA sigue sin egress (ADR-005).
- RNF-C3 Los `INSTAGRAM_*` solo por env/secret manager; nunca en repo/logs; el token Bearer solo en el header `Authorization` (lo usará SPEC-089). El agente no genera credenciales.
- RNF-NO-REGRESION Cero regresión de WhatsApp/RLS/egress/secretos; suites verdes sin modificar asserts; migración no destructiva (R-117).

## Criterios de aceptación (verificables)
- [ ] `instagram_accounts` existe con `instagram_business_account_id` UNIQUE; conectado con `omnicore_app`, un `SELECT` cross-tenant devuelve **0 filas** (CE-116, RLS real).
- [ ] `resolve_tenant_by_instagram_account_id(<id>)` ejecutada por `omnicore_app` **sin** `app.tenant_id` fijado devuelve el tenant correcto; un id inexistente/`activo=false` devuelve `NULL` (CE-116).
- [ ] El rol `omnicore_app` **no** puede ejecutar DDL ni leer `instagram_accounts` de otro tenant por SELECT directo (fail-closed sin tenant fijado).
- [ ] Migración Alembic `upgrade`/`downgrade` limpias contra Postgres real, sin tocar `messages`/`whatsapp_accounts`/`conversations` (CE-120).
- [ ] `check-externos-backend.sh` verde con `app/integrations/instagram` en la allowlist; un `graph.facebook.com` sembrado fuera de los módulos permitidos **falla** la build; el módulo IG (cuando exista) no importa IA (CE-118).
- [ ] Arranque fuera de development sin `INSTAGRAM_APP_SECRET`/`INSTAGRAM_VERIFY_TOKEN`/`INSTAGRAM_PAGE_ACCESS_TOKEN` **falla** con `ConfigurationError`; `.env.example` con placeholders, cero secretos reales (CE-120, C3).
- [ ] Nota de diseño §3.4 presente (docstring del modelo + comentario junto a `Message.wamid`); grep confirma que ningún código asume formato de WhatsApp al leer `wamid` (CE-117 preparado).
- [ ] ADR-006 contiene la ampliación (egress de transporte de IG sobre `graph.facebook.com`, allowlist por ruta de `app/integrations/instagram/`).

## Notas de ADR
- **ADR-006 se AMPLÍA en esta SPEC** (PLAN-012 §11.1): el envío/API de Instagram va al mismo `graph.facebook.com` que ADR-006 ya autoriza para WhatsApp — misma excepción acotada de transporte a Meta (no inferencia), extendida a un segundo módulo de conector. Se añade `app/integrations/instagram/` a la allowlist por ruta y se nota el alcance WhatsApp **e** Instagram. **NO consume `next_adr`**. Un ADR separado duplicaría la misma decisión arquitectónica.
- **ADR-017 NO se decide aquí** (condicional, SPEC-088, §11.2): si el CDN de media de IG resulta ser `graph.facebook.com`, queda cubierto por esta ampliación; si es distinto, SPEC-088 crea ADR-017.

## Notas de seguridad (C2/C3)
- C2: dar de baja una cuenta de IG = `activo=False` (nunca DELETE); descartes/errores loguean solo metadatos (`instagram_business_account_id`), nunca contenido de DM ni datos del contacto.
- C3: 🔴 crítico — `INSTAGRAM_*` por env/secret manager con fail-fast; cero hardcodeados; cero en logs; token Bearer solo en header (SPEC-089). El agente no genera credenciales.

## Restricción SENSIBLE / egress
- 🔴 SENSIBLE: la ampliación de ADR-006 **extiende** (por ruta) una excepción de transporte ya existente, no la relaja; la IA sigue sin egress (ADR-005, `ia_internal internal:true`). `check-externos-backend.sh` verde sin relajar la allowlist. **Bloqueo de Meta App Review (R-110):** esta SPEC es datos/infra/secretos y **no** requiere tráfico real de Meta para verificarse (migración + función + allowlist + fail-fast se prueban con Postgres/CI local); los secretos `INSTAGRAM_*` reales y la activación del canal con usuarios reales quedan DIFERIDOS al Lead cuando Meta apruebe (C6, puerta externa).

## Riesgos
- R-111 (fuga cross-tenant, parcial): función `SECURITY DEFINER` acotada + RLS `ENABLE+FORCE` en `instagram_accounts`; resolución sin bypass general.
- R-113 (idempotencia/colisión semántica de `wamid`): nota §3.4 + verificación de que ningún código asume formato WhatsApp.
- R-114 (egress mal extendido, parcial): allowlist por ruta SOLO a `app/integrations/instagram/`; verificaciones 8-9 replicadas.
- R-117 (regresión de WhatsApp): migración aditiva; cola/columna/patrón de WhatsApp intactos; suites verdes.
- R-110 (bloqueo de Meta App Review): no bloquea esta SPEC (datos/infra); activación real diferida al Lead (C6).

## Checkpoints aplicables
- C2 (borrado lógico, minimización). C3 (secretos `INSTAGRAM_*` fail-fast, 🔴 crítico). C4 (criterios verificables). C8 (origen `prompt-lab/prompts/PROMPT-012-INSTAGRAM-DM.md` / PLAN-012).
