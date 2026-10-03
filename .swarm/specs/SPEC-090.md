# SPEC-090 — Seguridad del canal Instagram (auditoría BLACK WIDOW) + CERO regresión (WhatsApp y resto del backend) + badge/filtro de canal "instagram" MÍNIMO en la Bandeja (F5) 🔴 SENSIBLE

- Estado: APROBADA · Responsable: BLACK WIDOW (seguridad) · Colaboran/revisan: WOLVERINE (no-regresión), DAREDEVIL/SPIDER-MAN (badge mínimo), BLACK PANTHER, HAWKEYE · Prioridad: ALTA · Tipo: SEGURIDAD/NO-REGRESIÓN/FRONTEND-MÍNIMO · Fase: F5
- Deriva de: PLAN-012 (F5, §2.IN.5/7, §3.3, §4 tabla F5, §5, §6 R-111/R-112/R-114/R-117, §7 CE-116/CE-118/CE-120(parcial)) · Clasificación: SENSIBLE (`.no-externo`) · **Depende de SPEC-085..089** (audita/no-regresiona el conjunto) · Consume `backend/check-externos-backend.sh`, `tests/test_rls_isolation.py`/`test_auth_cross_tenant_rls.py`/`test_config_and_cors.py`, suites de WhatsApp; patrón de auditoría de SPEC-032 (WhatsApp) / SPEC-084 (PLAN-011) · ADR-004/005/006/007/008/009

## Objetivo

**Cerrar la seguridad del canal Instagram** sin que ningún aspecto del transporte nuevo haya relajado una invariante, y garantizar **CERO regresión** del canal WhatsApp y del resto del backend: (1) auditoría de BLACK WIDOW de firma HMAC obligatoria, aislamiento/allowlist de egress (ADR-006 ampliado ↔ ADR-017 si aplica), fail-fast de `INSTAGRAM_*`, cero fuga cross-tenant (RLS fijada antes de escribir), cero PII/secretos en logs, el módulo `instagram/` no importa IA, y la IA sin egress (espejo de las auditorías de SPEC-032 de WhatsApp y de SPEC-084 de PLAN-011); (2) `check-externos-backend.sh` verde con la allowlist por ruta de IG extendida; (3) **CERO regresión** de las suites de WhatsApp, RLS, egress, secretos y del resto del backend, sin modificar asserts; (4) badge/filtro de canal "instagram" **MÍNIMO** en la Bandeja omnicanal (Q5=A: la API ya acepta `canal="instagram"`, probablemente solo un cambio de frontend trivial).

## Contexto

Verificado en el repo (fuente de verdad — 2026-10-03):
- **Patrón de cierre de seguridad:** esta SPEC es la **puerta de evidencia** de seguridad del canal, análoga a SPEC-032 (auditoría de seguridad de WhatsApp) y SPEC-084 (auditoría de no-relajación de invariantes de PLAN-011). Reúne las verificaciones dispersas en SPEC-085..089 y añade la auditoría de no-relajación + la no-regresión global + el badge mínimo.
- **Invariantes a auditar (intactas):** fail-fast de secretos (`config.py:661–699`, bloque `INSTAGRAM_*` de SPEC-085), RLS multi-tenant efectiva (`omnicore_app` NOSUPERUSER NOBYPASSRLS, ADR-004/008), egress acotado (`check-externos-backend.sh` sección 7 extendida a `app/integrations/instagram/`, `ia_internal internal:true`), cifrado de media (ADR-009), firma HMAC obligatoria (SPEC-086), aislamiento IA (el módulo `instagram/` no importa Ollama/IA; la IA no importa el `httpx` de transporte de IG, secciones 8-9 replicadas).
- **Frontend (Q5=A, headless/mínimo):** la Bandeja omnicanal (SPEC-004) y la API de conversaciones ya aceptan `canal="instagram"` (`schemas/conversation.py:15`); el trabajo de UI es a lo sumo un **badge/filtro de canal** — NO una vista nueva. **Si no hay certeza del archivo frontend exacto, el implementador (DAREDEVIL/SPIDER-MAN) debe buscar el componente de la Bandeja que ya renderiza el badge de canal de WhatsApp y añadir "instagram" de forma análoga** (mínimo, sin inventar experiencia nueva).
- **BLOQUEO DE META APP REVIEW (R-110):** la auditoría se hace sobre el canal verificado con simuladores + cuentas de prueba; la activación con usuarios reales queda DIFERIDA al Lead (Q1=B). La auditoría de seguridad NO depende del tráfico real de Meta.

## Alcance

### IN
- **Auditoría de seguridad (BLACK WIDOW, criterio top):**
  - **Firma HMAC obligatoria:** `POST` sin firma / con firma inválida → 401 sin encolar; HMAC sobre el RAW body antes de parsear (SPEC-086). Test de firma válida/inválida/ausente verde.
  - **Egress acotado:** `graph.facebook.com` (+ CDN de media de IG si aplica, ADR-017) aparece SOLO dentro de `app/integrations/instagram/`; el módulo IG NO importa Ollama/IA/`app.services.rag`/`app.workers`; la IA NO importa el `httpx` de transporte de IG; `check-externos-backend.sh` verde sin relajar la allowlist.
  - **Fail-fast de `INSTAGRAM_*`:** arranque fuera de development sin los secretos → `ConfigurationError`.
  - **Cero fuga cross-tenant:** RLS fijada antes de escribir (SPEC-087); descarte auditado sin mapeo; función `SECURITY DEFINER` acotada; `SELECT` cross-tenant con `omnicore_app` → 0 filas.
  - **Cero PII/secretos en logs:** grep de que ni los `INSTAGRAM_*`, ni el token Bearer, ni el header de firma, ni el contenido del DM, ni datos del contacto aparecen en logs.
  - **ADR coherente:** ADR-006 ampliado presente (SPEC-085); ADR-017 presente SOLO si SPEC-088 confirmó host distinto; ninguno relajó ADR-005.
- **`check-externos-backend.sh` verde** con la allowlist por ruta de IG extendida (secciones 7/8/9 replicadas para `instagram/`).
- **CERO regresión:** suites de WhatsApp (recepción/ingesta/envío/statuses/media), `test_rls_isolation`/`test_auth_cross_tenant_rls`/`test_config_and_cors`, egress y secretos **verdes sin modificar asserts**; colas `ig:inbound`/envío de IG separadas de las de WhatsApp; migración aditiva (SPEC-085) no destructiva.
- **Badge/filtro de canal "instagram" MÍNIMO** en la Bandeja omnicanal (Q5=A): localizar el componente que renderiza el badge de canal de WhatsApp y añadir "instagram" análogamente; sin vista/experiencia nueva. Si el frontend ya muestra el canal de forma genérica, verificar que "instagram" se renderiza/filtra correctamente y documentar que no se requiere cambio.

### OUT
- **Implementar** datos/webhook/worker/media/envío (SPEC-085..089) → aquí se **auditan/no-regresionan**, no se implementan.
- **Trabajo de UI dedicado** para Instagram (vista/experiencia propia) → PROHIBIDO (Q5=A).
- **Relajar cualquier invariante** (RLS/egress/secretos/PHI/HMAC) para "hacer pasar" una prueba → PROHIBIDO.
- Las pruebas/simulador/runbook/deploy (SPEC-091).

## Dependencias
- **Depende de SPEC-085..089** (audita y no-regresiona el conjunto). Reutiliza `check-externos-backend.sh`, las suites de RLS/CORS/egress/secretos y las de WhatsApp. **Cierra la seguridad del canal**; precede a SPEC-091 (pruebas/deploy). Ruta crítica: transversal desde F0/F1, se cierra tras F1–F4.

## Requisitos funcionales
- RF-01 Auditoría BLACK WIDOW: firma HMAC obligatoria, egress acotado, fail-fast `INSTAGRAM_*`, cero fuga cross-tenant, cero PII/secretos en logs, IG no importa IA, IA sin egress (CE-116/CE-118).
- RF-02 `check-externos-backend.sh` verde con la allowlist por ruta de IG; un `graph.facebook.com`/CDN de media sembrado fuera de `instagram/` **falla** la build (CE-118).
- RF-03 CERO regresión: suites de WhatsApp/RLS/CORS/egress/secretos verdes sin modificar asserts (CE-120).
- RF-04 Badge/filtro de canal "instagram" MÍNIMO en la Bandeja (Q5=A); sin vista nueva.

## Requisitos no funcionales
- RNF-NO-RELAJA-INVARIANTE (criterio top) Ningún aspecto del canal IG relajó fail-fast de secretos, RLS, CORS, egress (`check-externos-backend.sh`/`ia_internal`) ni cifrado de media (ADR-009); la allowlist se extendió por ruta, no se relajó; el aislamiento IA se refuerza.
- RNF-NO-REGRESION Cero regresión del canal WhatsApp ni del resto del backend; suites verdes sin modificar asserts.
- RNF-FRONTEND-MINIMO Solo badge/filtro de canal; sin vista/experiencia nueva (Q5=A).
- RNF-C3 Cero secretos/PII en tests/fixtures/logs; credenciales de prueba ficticias; el agente no genera credenciales.

## Criterios de aceptación (verificables)
- [ ] **Auditoría BLACK WIDOW:** firma HMAC obligatoria (401 sin firma válida sin encolar); egress SOLO en `instagram/`; fail-fast `INSTAGRAM_*`; RLS antes de escribir; cero PII/secretos en logs; IG no importa IA; IA sin egress; ADR-006 ampliado (y ADR-017 si aplica) presente (CE-116/CE-118).
- [ ] `check-externos-backend.sh` verde con la allowlist por ruta de IG; test negativo (transporte fuera de `instagram/`) **falla** la build (CE-118).
- [ ] Suites de WhatsApp/RLS/CORS/egress/secretos **verdes sin modificar asserts**; `ig:inbound`/envío de IG separados de WhatsApp; migración no destructiva (CE-120).
- [ ] Un `SELECT` cross-tenant sobre `instagram_accounts`/mensajes de IG con `omnicore_app` → 0 filas; descarte sin mapeo auditado sin escritura (CE-116).
- [ ] La Bandeja muestra/filtra el canal "instagram" (badge mínimo); sin vista nueva; la API ya lo acepta (Q5=A).
- [ ] Grep: ni `INSTAGRAM_*`, ni token Bearer, ni header de firma, ni contenido de DM, ni datos del contacto en logs (C2/C3).

## Notas de seguridad (C2/C3)
- C2: minimización verificada (logs solo con metadatos); borrado lógico; badge sin exponer datos sensibles.
- C3: 🔴 cero secretos en el repo/tests/logs; credenciales de prueba ficticias; el agente no genera credenciales.

## Restricción SENSIBLE / egress
- 🔴 SENSIBLE: esta SPEC es la **puerta de evidencia de seguridad** del canal IG. Un aspecto del transporte que relajara la allowlist de egress, rompiera el aislamiento `ia_internal`, debilitara el fail-fast de secretos, el cifrado de media (ADR-009) o la firma HMAC sería una **REGRESIÓN de seguridad** disfrazada de funcionalidad. `check-externos-backend.sh` verde sin relajar la allowlist; `graph.facebook.com` (ADR-006 ampliado) y el CDN de media (ADR-017 si aplica) acotados a `instagram/`. **Sin ADR nuevo en esta SPEC.** **Bloqueo de Meta App Review (R-110):** la auditoría se hace sobre el canal verificado con simuladores + cuentas de prueba; la activación con usuarios reales queda DIFERIDA al Lead (C6).

## Riesgos
- R-111/R-112/R-114 (**cierre de seguridad**): esta SPEC verifica las mitigaciones de cross-tenant, firma HMAC y egress acotado mediante la auditoría + el test negativo + el barrido de logs.
- R-117 (regresión de WhatsApp/resto del backend): no-regresión global, suites verdes sin modificar asserts.
- R-110 (bloqueo de Meta App Review): la auditoría no depende de tráfico real; activación diferida al Lead (C6).

## Checkpoints aplicables
- C2 (minimización/borrado lógico). C3 (cero secretos/PII en logs/tests, 🔴 crítico). C4 (criterios verificables). C8 (origen PLAN-012 / `prompt-lab/prompts/PROMPT-012-INSTAGRAM-DM.md`).
