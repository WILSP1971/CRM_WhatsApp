# SPEC-081 — Rate-limiting GENERAL de API por IP/endpoint sobre el Redis ya presente (`slowapi` o equivalente, pinneado `==`): cubre webhooks públicos (WhatsApp/PBX) + endpoints REST + `/rag/draft`, respuesta 429 controlada, COEXISTE con el `LoginRateLimiter` existente (no lo sustituye), umbrales con holgura para ráfagas legítimas de WhatsApp/PBX sin romper el ACK rápido ni la validación HMAC/idempotencia (ADR-007); latencia de tráfico legítimo validada por THOR 🔴 SENSIBLE

- Estado: CERRADA — implementado por CAPTAIN AMERICA: diseño híbrido (`SlowAPIMiddleware` para el límite general transversal + `PathRateLimiter` propio, mismo patrón INCR+EXPIRE que `LoginRateLimiter`, para webhooks WhatsApp/PBX y `/rag/draft`) tras descubrir y evitar una incompatibilidad real de `slowapi` con `from __future__ import annotations` (convención del proyecto) que habría roto el arranque. Dos bugs reales encontrados y corregidos durante la implementación: (1) `SlowAPIMiddleware` sobrescribía el `Retry-After` del `LoginRateLimiter` — resuelto eximiendo la ruta de login del middleware general; (2) fail-open ante caída de Redis (sin eso, 28 tests rompían con Redis caído) — corregido con el mismo criterio de "fail-open auditable" de SPEC-013. Umbrales: 60/min default, 20/min `/rag/draft`, 300/min webhooks (holgura para ráfagas de Meta/PBX, ADR-007 respetado). Auditoría de BLACK WIDOW: `LoginRateLimiter` intacto, sin bypass de HMAC. Suite completa: 778 passed, cero regresión. · Responsable: CAPTAIN AMERICA · Colaboran/revisan: THOR, HAWKEYE, BLACK WIDOW, WOLVERINE · Prioridad: ALTA · Tipo: BACKEND/SEGURIDAD/ANTI-ABUSO · Fase: F1
- Deriva de: PLAN-011 (F1, §1 H-2, §2.IN.2, §3.4, §4, §5, §6 R-105 (top), §7 CE-106, §9, §10 · R-105 · CE-106) · Clasificación: SENSIBLE (`.no-externo`) · Consume `backend/app/security/rate_limit.py` (`LoginRateLimiter`, SPEC-013), el Redis ya presente (`docker-compose.yml`), `backend/app/main.py` (montaje de middleware), los webhooks de WhatsApp/PBX y `/rag/draft`, ADR-007 (idempotencia/HMAC de webhooks) · Independiente de SPEC-080 a nivel de código (solo coordinación de archivos) · Prerequisito conceptual de SPEC-084

## Objetivo

Cerrar el hueco de que hoy **solo existe rate-limiting de login**: añadir un **rate-limiting GENERAL de API por IP/endpoint**, self-hosted sobre el **Redis ya presente** (p. ej. `slowapi` + backend Redis, o equivalente, **pinneado con `==`**), que proteja los **webhooks públicos (WhatsApp/PBX)**, los **endpoints REST** y **`/rag/draft`** contra abuso/DoS, devolviendo un **429 controlado** al exceder el límite por IP/endpoint. El nuevo control **COEXISTE** con el `LoginRateLimiter` existente (SPEC-013): lo **complementa, no lo sustituye**. Los umbrales se calibran con **holgura para ráfagas legítimas** de WhatsApp/PBX, sin romper el **ACK rápido** del webhook ni la **validación de firma HMAC / idempotencia** (ADR-007), de modo que tráfico legítimo **NUNCA** reciba 429. La latencia del tráfico legítimo la valida **THOR**. Es trabajo **aditivo**: no toca la lógica de negocio ni el aislamiento/egress.

## Contexto

Verificado en PLAN-011 §1.4/§3.4 y en el repo (fuente de verdad, no asunciones — 2026-10-02):
- **Rate-limiting GENERAL AUSENTE.** El único rate-limiting es el de login (`backend/app/security/rate_limit.py`, `LoginRateLimiter`, SPEC-013, por intentos fallidos, modo estricto Redis fuera de dev). **NO** hay `slowapi`/`fastapi-limiter` en `requirements.txt` (0 coincidencias) ni límite por IP/endpoint para el resto de la API (webhooks WhatsApp/PBX, endpoints REST, `/rag/draft`). Caddy tampoco aplica rate-limiting.
- **Dos capas, no una (§3.4):** CAPA 1 = `LoginRateLimiter` (existente, se conserva, por intentos fallidos de login). CAPA 2 = este rate-limit general por IP/endpoint sobre el Redis ya presente. Se reutiliza el **mismo Redis** del compose (sin nuevo servicio, sin egress nuevo).
- **Cuidado con los webhooks (R-105, top):** WhatsApp/PBX pueden emitir **ráfagas legítimas** (p. ej. entregas en lote de Meta); el límite debe ser por IP/endpoint con **umbrales holgados** que no descarten entregas válidas. El rate-limit **NUNCA** rechaza de forma que rompa el **ACK rápido** del webhook ni la **validación de firma HMAC/idempotencia** (ADR-007): un 429 indebido a Meta/PBX provocaría reintentos, pérdida de entregas o rotura de idempotencia. Se coordina con el camino de ACK existente (exención/holgura específica para los endpoints de webhook).
- **`requirements.txt` 100% pinneado con `==`** (invariante del proyecto): la nueva dependencia de rate-limiting se pinnea con `==` (sin rangos abiertos), coherente con el escaneo reproducible de SPEC-082.
- **Umbrales candidatos, confirmables en la aprobación (PLAN-011 §12.2):** los req/min por IP/endpoint y la holgura de webhooks son candidatos en esta SPEC, calibrados para ráfagas legítimas; el Lead puede ajustarlos al aprobar sin cambiar el alcance.

## Alcance

### IN
- **Middleware/dependencia de rate-limit GENERAL por IP/endpoint** (`slowapi` o equivalente, pinneado `==`) con **backend en el Redis ya presente**, montado en `backend/app/main.py`, cubriendo: webhooks públicos (WhatsApp/PBX), endpoints REST y `/rag/draft`.
- **Respuesta 429 controlada** (cuerpo/headers adecuados, p. ej. `Retry-After`) al exceder el límite por IP/endpoint.
- **Coexistencia explícita con `LoginRateLimiter`:** ambos controles conviven; el nuevo **no reemplaza** ni debilita el de login; el orden de ejecución no rompe el flujo de login.
- **Holgura/exención de webhooks (R-105):** umbrales específicos para los endpoints de webhook que absorben ráfagas legítimas de WhatsApp/PBX; el rate-limit no interfiere con el ACK rápido ni con la validación HMAC/idempotencia (ADR-007) — no rechaza antes de forma que rompa la idempotencia.
- **Dependencia pinneada `==`** en `requirements.txt` (sin regresión a rangos abiertos).

### OUT
- **Contenedores/Dockerfile de producción** → SPEC-080 (F0). **Escaneo CI/Dependabot** → SPEC-082 (F2). **Firewall/puertos/TLS/headers** → SPEC-083 (F3). **Pruebas consolidadas + docs** → SPEC-084 (F4).
- **Sustituir o rediseñar el `LoginRateLimiter`** → PROHIBIDO; se conserva intacto y se complementa.
- **Rate-limiting en Caddy** como mecanismo principal → se implementa en el backend sobre el Redis existente (Caddy solo proxya webhooks hoy); no se traslada el control a la capa de proxy.
- **Reimplementar HMAC/idempotencia de webhooks** (ADR-007) → se consume intacto; el rate-limit se coordina con él, no lo rediseña.
- **CD/staging** (Q3=A) y **backups** (Q6=A, DIFERIDOS) → fuera de alcance (ver PLAN-011 §2 OUT / PLAN-010 §13); no se mencionan como entregable.

## Dependencias
- Consume `backend/app/security/rate_limit.py` (`LoginRateLimiter`), el **Redis ya presente** (no se añade servicio), `backend/app/main.py` (montaje), los endpoints de webhook (WhatsApp/PBX) y `/rag/draft`, y ADR-007 (idempotencia/HMAC) **sin rediseño**. **Independiente de SPEC-080 a nivel de código**; solo comparte con SPEC-080/081 la **validación de latencia de THOR** y puede correr en paralelo. Depende del Redis existente, no de F0. **Prerequisito conceptual de SPEC-084** (que prueba el 429 y la ráfaga legítima).

## Requisitos funcionales
- RF-01 Existe un rate-limit GENERAL por IP/endpoint sobre el **Redis ya presente** que cubre webhooks públicos (WhatsApp/PBX), endpoints REST y `/rag/draft`; exceder el límite → **429 controlado** (CE-106).
- RF-02 El control **coexiste** con el `LoginRateLimiter` existente sin sustituirlo ni debilitarlo; el flujo de login sigue intacto (CE-106).
- RF-03 Los **webhooks legítimos** (ráfaga de WhatsApp/PBX) **NO** reciben 429: umbrales con holgura/exención para esos endpoints; el límite no rompe el ACK rápido ni la validación HMAC/idempotencia (ADR-007) (CE-106, R-105).
- RF-04 La dependencia de rate-limiting se pinnea con `==` en `requirements.txt` (sin rangos abiertos).
- RF-05 Umbrales por IP/endpoint **configurables** (candidatos en la SPEC, ajustables por el Lead en la aprobación); valores por defecto calibrados para ráfagas legítimas.

## Requisitos no funcionales
- RNF-NO-DESCARTA-LEGITIMO (R-105, top) El tráfico legítimo (ráfaga de webhooks WhatsApp/PBX, agente humano activo) **no recibe 429**; el 429 solo dispara ante abuso real; la idempotencia (ADR-007) no se rompe.
- RNF-LATENCIA (THOR) El rate-limit **no degrada la latencia** del tráfico legítimo; THOR valida que el camino caliente (lookup en Redis) es despreciable frente a RNF de latencia de la API.
- RNF-COEXISTENCIA El nuevo control **no debilita** el `LoginRateLimiter` (SPEC-013); ambos conviven; cero regresión del flujo de login.
- RNF-ADITIVO Aditivo: reutiliza el Redis existente (sin servicio nuevo, sin egress nuevo); no toca la lógica de negocio ni el aislamiento `ia_internal`.
- RNF-C3 Ninguna credencial de Redis hardcodeada; conexión por env (como ya hace el proyecto); cero secretos en logs; el agente no genera credenciales.

## Criterios de aceptación (verificables)
- [ ] Un cliente que excede el límite por IP/endpoint recibe **429** en una prueba controlada (webhook/REST/`/rag/draft`) (CE-106).
- [ ] Una **ráfaga legítima** de webhooks WhatsApp/PBX (dentro de umbrales holgados) **NO** recibe 429; el ACK rápido y la validación HMAC/idempotencia (ADR-007) siguen funcionando (CE-106, R-105).
- [ ] El `LoginRateLimiter` sigue operativo e intacto; el nuevo control **coexiste** sin sustituirlo (CE-106).
- [ ] THOR valida que la latencia del tráfico legítimo **no se degrada** con el rate-limit activo.
- [ ] La dependencia de rate-limiting está pinneada con `==`; `requirements.txt` sigue 100% `==`; `check-externos-backend.sh` verde sin relajar allowlist; sin secretos en el repo/logs.

## Notas de seguridad (C3/C6)
- C3: la conexión a Redis va por env (patrón vigente del proyecto); ninguna credencial hardcodeada, ninguna en logs, ninguna generada por el agente.
- C6: **aplicar/activar el rate-limiting general en un entorno real de producción es un cambio sensible** → requiere **aprobación explícita del Lead + notificación** antes de desplegar (un umbral mal calibrado podría descartar webhooks de Meta/PBX). Esta SPEC entrega el artefacto versionado con umbrales candidatos; no lo activa en producción.

## Restricción SENSIBLE / egress
- 🔴 SENSIBLE (sin egress nuevo): protege endpoints públicos (webhooks WhatsApp/PBX) de un backend con PHI potencial bajo RLS multi-tenant. El riesgo central (R-105) es que un umbral mal calibrado **descarte tráfico legítimo** (ráfaga de webhooks válidos) → mensajes perdidos, 429 a Meta/PBX, **pérdida de idempotencia** (ADR-007) — eso sería una **REGRESIÓN de datos/entregas**, no una mejora. Reutiliza el Redis ya presente (sin servicio ni egress nuevo); `graph.facebook.com` (ADR-006) no se toca; `ia_internal` intacto; `check-externos-backend.sh` verde sin relajar allowlist. **Sin ADR nuevo** (el único ADR de la fase es el de firewall de host, SPEC-083/ADR-016).

## Riesgos
- R-105 (**el rate-limiting general descarta tráfico legítimo**): una ráfaga de webhooks WhatsApp/PBX válidos (o un agente humano activo) recibe 429 → mensajes perdidos, 429 a Meta/PBX, pérdida de idempotencia. Mitigación: umbrales por IP/endpoint calibrados para ráfagas legítimas; holgura/exención para webhooks; el límite no rompe el ACK rápido ni la validación HMAC/idempotencia (ADR-007); prueba de que tráfico legítimo NO recibe 429 (THOR latencia + HAWKEYE) (CE-106). **TOP del plan junto con R-103.**

## Checkpoints aplicables
- C3 (secretos: conexión a Redis por env; cero hardcodeadas, cero en logs, cero generadas por el agente). C4 (criterios verificables — 429 controlado + ráfaga legítima sin 429). C6 (activar el rate-limiting en el entorno real = cambio sensible → aprobación del Lead + notificación antes de desplegar). C8 (origen `prompt-lab/prompts/PROMPT-011-HARDENING-PRODUCCION.md`).
