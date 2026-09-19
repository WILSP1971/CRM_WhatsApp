# ESTADO — CRM_WhatsApp / OmniCore AI

> Última actualización: 2026-09-16 · Responsable del último avance: IRON MAN (orquestación) · CAPTAIN AMERICA (fixes a11y) · HAWKEYE (QA) · QUICKSILVER (CI/repo/publicación)

## Resumen

Maqueta de alta fidelidad navegable (SPA) del CRM omnicanal **OmniCore AI**. PLAN-001 aprobado.
Las 10 SPECs (SPEC-001 … SPEC-010) están **CERRADAS**: los 6 módulos funcionan en tema claro/oscuro,
el build compila, no hay llamadas externas y el contraste cumple WCAG AAA (verificado con test
matemático 32/32). Repo versionado en GitHub, CI configurado, README mejorado, publicado en
https://github.com/WILSP1971/CRM_WhatsApp.

Proyecto clasificado **SENSIBLE** (`.no-externo`): datos 100% ficticios, sin backend, sin IA/LLM
real, sin integraciones vivas, cero recursos externos en runtime.

## Estado de SPECs

| SPEC     | Título                                         | Estado    | Fase |
| -------- | ---------------------------------------------- | --------- | ---- |
| SPEC-001 | Scaffolding, tooling y estructura del proyecto | CERRADA   | F0   |
| SPEC-002 | Design system: tokens, temas y primitivas UI   | CERRADA   | F1   |
| SPEC-003 | Layout global y navegación SPA                 | CERRADA   | F2   |
| SPEC-004 | Bandeja omnicanal unificada                    | CERRADA   | F3   |
| SPEC-005 | Panel lateral RAG en vivo (representación)     | CERRADA   | F4   |
| SPEC-006 | VoiceBot + telefonía VoIP (representación)     | CERRADA   | F5   |
| SPEC-007 | Sector Comercial / E-Commerce (prioritario)    | CERRADA   | F6   |
| SPEC-008 | Sectores de referencia + analítica             | CERRADA   | F6   |
| SPEC-009 | Accesibilidad, performance y QA                | CERRADA   | F7   |
| SPEC-010 | Repo, CI y documentación                       | CERRADA   | F8   |

## Revisión y QA (fase SPEC-009)

- **DAREDEVIL** (frontend): detectó 3 bloqueantes de contraste/motion → corregidos.
- **HAWKEYE** (QA): tabla de contraste matemática; harness de tests **vitest 32/32**
  (contraste AAA de tokens + smoke-render de las 8 páginas sin `console.error`);
  `.lighthouserc.json` con umbrales (Lighthouse/axe reales pendientes en CI con Chromium).
- **WOLVERINE** (calidad): sin bloqueantes; `formatDuration` duplicada → consolidada en `src/lib/format.ts`.
- **BLACK WIDOW** (seguridad): **APTO** — cero externos, sin secretos, PII ficticia, sin `dangerouslySetInnerHTML`/`eval`.

## Correcciones aplicadas por CAPTAIN AMERICA (bloqueantes AAA)

- Tokens `--color-chart-*` dedicados para series Recharts (≥7:1 en ambos temas) + `strokeDasharray`/marcador por serie.
- Tokens `--color-badge-*-text`; badges `success/warning/danger/ai` ≥7:1 en ambos temas.
- `--color-text-muted`, `--color-accent-indigo-strong` (oscuro) y `--color-accent-cyan-strong` (claro) ajustados a ≥7:1.
- `motion-reduce:animate-none` en RAG (panel/draft/suggestion/citation) y `VoiceBotStatusWidget`, más red de seguridad global en `globals.css`.

## Verificaciones ejecutadas (IRON MAN, sobre estado final)

- `npm run test`: **32/32** (contraste + smoke).
- `npm run build` (tsc -b && vite build): **exit 0**.
- `npm run lint`: **0 errores** (1 warning preexistente de react-refresh en `src/lib/theme.tsx`, no bloqueante).
- `npm run check:externos`: **exit 0** (sin URLs externas).

## Lighthouse CI — resultado final (escritorio 1920×1080, 3 corridas)

Run GitHub Actions [`35057890871`](https://github.com/WILSP1971/CRM_WhatsApp/actions/runs/35057890871), commit `efa1d2c`.

| Categoría      | Score | Gate  |
| -------------- | ----- | ----- |
| Performance    | 100   | ≥90 ✅ |
| Accessibility  | 98    | ≥90 ✅ |
| Best Practices | 92    | ✅     |
| SEO            | 100   | ✅     |

Métricas: FCP 0.5s · LCP 0.5s · TTI 0.5s · **TBT 0 ms** · **CLS 0** · Speed Index 0.5s.

**Optimización de Performance (THOR → CAPTAIN AMERICA):** 80 → 100.
- `vite.config.ts`: `manualChunks` (vendor-react / vendor-ui) + `build.target: es2020`; entry propio 345 KB → 72 KB.
- Plugin local `inlineCssPlugin` (`transformIndexHtml`): CSS de entrada inline como `<style>`, elimina el `<link rel=stylesheet>` render-blocking (~670 ms), sin recursos externos.
- `.lighthouserc.json`: corregido a throttling de **escritorio** (CPU 1×) acorde al target; el config previo aplicaba throttling móvil sobre form-factor desktop, hundiendo/variando el score (58/80/80).

## Notas / riesgos abiertos

- **Inter self-hosted**: `.woff2` no incluidos (sin descargas externas en este entorno); fallback `system-ui`.
  Procedimiento en `public/fonts/README.md` para añadirlos localmente (nunca vía CDN).
- **Lighthouse**: ejecutado en CI (ver sección de resultados). **axe** real por navegador queda como checklist manual (el harness de contraste vitest 32/32 cubre AAA de tokens).
- **`npm audit`**: 2 moderadas en `react-router-dom` 6.x (runtime) y high/critical en `vite`/`vitest`
  que solo afectan el dev-server local, no el build de producción. Valorar upgrade en SPEC futura.

## Entregable #1 — COMPLETADO

**SPEC-010 (QUICKSILVER) — CERRADA**:
- Repo versionado con `git init` (rama `main`), archivos en 10 commits.
- README mejorado con secciones de Scripts, módulos (6 espacios), sensibilidad SENSIBLE, y AAA.
- `.gitignore` validado: no suben `node_modules`, `dist`, `.env*`, `*.tsbuildinfo`, `coverage`.
- CI workflow (`.github/workflows/ci.yml`) en cada push/PR: build + lint + check:externos + test + Lighthouse CI (continue-on-error).
- Publicado en https://github.com/WILSP1971/CRM_WhatsApp (visibilidad PUBLIC).
- Verificaciones finales: `npm run build` ✓, `npm run check:externos` ✓, `npm run test` 32/32 ✓.

## Próximos pasos (fuera de alcance SPEC-010)

1. ✅ CI en GitHub Actions verde (build + lint + test + check:externos + Lighthouse).
2. ✅ Lighthouse ejecutado (Performance 100, A11y 98, BP 92, SEO 100). Pendiente opcional: axe real por navegador.
3. (Opcional) Fase funcional futura: backend/integraciones/IA con modelos locales/self-hosted (respetando `.no-externo`).

## Deuda técnica registrada (revisión BLACK PANTHER)

- **SPEC-015 (WebChat) — robustez WS** (MAYOR, no bloqueante, para hardening/SPEC-022):
  1. `app/api/ws_chat.py` `_forward_redis_to_socket`: envolver `pubsub.listen()` en try/except con log y cierre/reintento (evitar conexión zombie si Redis cae).
  2. Backpressure/timeout en `websocket.send_text` (desconectar cliente lento).
  3. Reconciliación si falla el 2º write de `estado_entrega` (mensaje queda "enviado").
- **SPEC-015/022 — verificación dura**: HAWKEYE debe ejecutar `tests/test_ws_chat_integration.py` (y los skipped de 012/013/014) contra Postgres+Redis reales (docker-compose) antes del cierre definitivo (criterio R-23 aislamiento cross-tenant end-to-end).
- **MENOR transversal**: `app/main.py` `/healthz` usa `os.popen("date -Iseconds")` → cambiar a `datetime.now(timezone.utc).isoformat()`.
- **SPEC-018 (sentimiento)** (MAYOR, no bloqueante): (1) docstring de migración `b478b79c2111` dice `server_default="0"` pero el código usa `nullable=True` sin default → corregir comentario; (2) añadir `CheckConstraint` en `Message.sentimiento` (defensa en profundidad, hoy depende de single-writer).
- **SPEC-020 (integración SPA)** (MENOR, flag ON): `sendOutgoingMessage` (useConversationsData) usa fallback REST con `void sendMessage(...)` sin capturar el error → envío perdido en silencio si falla; propagar al `error` del hook.
- **MENOR recurrente** `app/main.py` `/healthz` usa `os.popen("date -Iseconds")` (flagged por PANTHER 014/015 y WIDOW 021) → cambiar a `datetime.now(timezone.utc).isoformat()`. Trivial, pendiente pasada de limpieza.
- **SPEC-021 (BAJO)**: export/erase autorizan a cualquier agente autenticado del tenant (no exigen rol admin); endurecer a rol admin en fase futura (aislamiento por tenant sí garantizado por RLS).

## Entregable #2 — Fase Funcional (PLAN-002) — IMPLEMENTADO (EN_VERIFICACION)

Fecha: 2026-09-18. Las 13 SPECs (SPEC-011..023) implementadas, revisadas y en EN_VERIFICACION.
Backend FastAPI + PostgreSQL16/pgvector + Redis + Ollama (IA 100% local), workers rag/sentiment/retention.

| SPEC | Título | Revisión |
| ---- | ------ | -------- |
| 011 | Infra + Docker Compose + CI | IRON MAN (egress `internal:true` verificado; corrigió masquerade) |
| 012 | Datos + RLS FORCE | IRON MAN (21 sentencias RLS, test aislamiento CI) |
| 013 | Auth multi-tenant 🔴 | BLACK WIDOW (fix ALTO: fail-fast de secretos) |
| 014 | API core + OpenAPI | BLACK PANTHER (apta) |
| 015 | WebChat WebSocket | BLACK PANTHER (apta; 3 MAYOR robustez → deuda) |
| 016 | IA local + egress 🔴 | BLACK WIDOW (guard host interno no evadible; IRON MAN quitó leak) |
| 017 | RAG local (≥3 citas) | BLACK PANTHER (fix BLOQUEANTE: cola Redis+worker) |
| 018 | Sentimiento LLM local | BLACK PANTHER (apta) |
| 019 | Human-in-the-loop | BLACK PANTHER (fix BLOQUEANTE: carrera doble envío → transición atómica) |
| 020 | Integración SPA feature-flag | DAREDEVIL (apta; flag OFF = maqueta intacta 59/59) |
| 021 | Seguridad + datos personales 🔴 | BLACK WIDOW (HABEAS DATA OK; fix bug auditoría) |
| 022 | Pruebas + carga + observabilidad | HAWKEYE (200 passed; /metrics; Locust; CI con Postgres/Redis) |
| 023 | Docs + runbook + deploy 🔴 | BLACK WIDOW (fix CRÍTICO: secretos concretos en docs → placeholders) |

ADRs: ADR-003 (LLM/embeddings locales), ADR-004 (RLS pool-model), ADR-005 (egress bloqueado).
Estado backend (sandbox, sin daemon Postgres/Redis/Ollama): pytest 200 passed / 71 skipped / 0 failed,
coverage 69% (gate ≥80% en CI con los skipped corriendo), black/flake8 limpios, check-externos-backend APROBADO,
docker compose config VÁLIDO, `ia_internal internal:true`.

Cierre a CERRADA pendiente de: correr el pipeline CI contra Postgres/Redis/Ollama reales (los 71 tests skipped,
coverage ≥80%, cross-tenant RLS end-to-end, egress real, p95 RAG con Locust). Deploy real a prod requiere OK del Lead.
Deuda técnica registrada arriba (robustez WS 015, os.popen /healthz, CheckConstraint sentimiento, etc.).
- **SPEC-026 (webhook WhatsApp)** (MEDIO, no bloqueante): M-1 `webhook.py` `enqueue_inbound_webhook_event` sin try/except → si Redis cae, 500 rompe el ACK 200 y Meta reintenta (tormenta); envolver + timeout y política de reintento. M-2 sin límite de tamaño de body → configurar `client_max_body_size` en el proxy TLS (SPEC-034). B-1 replay: dedup por wamid llega en SPEC-027.
- **Deuda transversal de workers** (MAYOR, no bloqueante, PANTHER SPEC-027): `run_worker_loop` de TODOS los workers (rag_ingest/sentiment/whatsapp_inbound) sin try/except+backoff exponencial ante caída de Redis/Postgres → riesgo crash-loop bajo degradación. Endurecer en una pasada de hardening (o SPEC-033).
- **SPEC-027 (MAYOR)**: falta test de CONCURRENCIA real del mismo `wamid` (dos hilos/conexiones → count==1). El código maneja IntegrityError; añadir test en SPEC-033/HAWKEYE con Postgres real.
- **SPEC-028 (MENOR, perf)**: la generación del borrador RAG corre INLINE en la ingesta de WhatsApp → acopla la latencia de ingesta al p95 (~6s) del LLM. Considerar encolar la generación a un worker aparte (patrón rag_ingest_worker) en una pasada de optimización.
- **SPEC-029 (MENOR, robustez)**: `_validate_graph_host` (graph_client.py) debería rechazar explícitamente userinfo embebido (`parsed.username/password`) por defensa en profundidad (no explotable hoy: base_url fijo). Endurecer en pasada de hardening.
- **SPEC-030 (MAYOR, robustez)**: `message_service.update_delivery_status` no trata `failed` como terminal internamente (la terminalidad hoy depende de la guarda del `whatsapp_inbound_worker`). Endurecer: que `update_delivery_status` haga no-op si el mensaje ya está `failed`, para que ningún caller futuro lo "reviva". Bajo esfuerzo.
- **SPEC-032 (MEDIO, def. en profundidad)**: `check-externos-backend.sh` verif.9 no cubre `app/services/ai_service.py` (importa httpx, corre en `api` con egress). No es fuga (config.py valida host interno fail-fast + ia_internal internal:true), pero extender el escáner para exigir que todo httpx fuera de integrations/whatsapp apunte a host interno. B-1: `failed` no está en el dict `orden` de update_delivery_status (manejado por no-op terminal, frágil ante refactor).
- **CI backend — BLOQUEANTE corregido (HAWKEYE SPEC-033 + IRON MAN)**: `DB_PASSWORD` en `backend-ci.yml` tenía 20 chars < 32 exigidos por `_require_strong_secret` con `ENVIRONMENT=test` → `Settings()` abortaba y el CI (jobs test/load-smoke) nunca habría arrancado. Corregido a ≥32 chars (37) en DATABASE_URL/DB_PASSWORD/POSTGRES_PASSWORD; verificado que `Settings()` ya no aborta y YAML válido.

## Entregable #3 — Canal WhatsApp Business API (PLAN-003) — IMPLEMENTADO (EN_VERIFICACION)

Fecha: 2026-09-19. Las 11 SPECs (SPEC-024..034) implementadas, revisadas y en EN_VERIFICACION.
Canal WhatsApp Cloud API (Meta) end-to-end reutilizando el pipeline del #2 (persistencia → sentimiento local
→ RAG ≥3 citas → borrador human-in-the-loop → envío por Graph API). Meta = SOLO transporte; IA 100% local.

| SPEC | Título | Revisión |
| ---- | ------ | -------- |
| 024 | Infra egress acotado (IA aislada) 🔴 | IRON MAN (fix: app_workers tenía egress → topología corregida) |
| 025 | Datos WhatsApp + routing + wamid | BLACK PANTHER (fix BLOQUEANTE: app corría como superusuario → RLS no aplicaba; ADR-008: rol omnicore_app + SECURITY DEFINER) |
| 026 | Webhook HMAC 🔴 | BLACK WIDOW (firma no evadible, sin fuga timing) |
| 027 | Ingesta idempotente + enrutado | BLACK PANTHER (fix BLOQUEANTE: cola Redis+worker real) → idempotencia wamid |
| 028 | Disparo pipeline IA local | BLACK PANTHER (human-in-the-loop intacto, modo degradado) |
| 029 | Envío Graph API 🔴 | BLACK WIDOW (host allowlist no evadible, sin redirects, tokens/PII protegidos) |
| 030 | Statuses (sent/delivered/read/failed) | BLACK PANTHER (RLS por wamid, monotónico, failed terminal) |
| 031 | Integración SPA feature-flag WhatsApp | DAREDEVIL (flag OFF = maqueta intacta) |
| 032 | Seguridad + egress 🔴 | BLACK WIDOW (VEREDICTO FINAL: excepción .no-externo respetada, IA aislada, guardarraíl anti-regresión) |
| 033 | Pruebas + carga | HAWKEYE (test concurrencia wamid, carga webhook p95≤500ms; fix BLOQUEANTE CI: DB_PASSWORD<32) |
| 034 | Docs + runbook + deploy + simulador 🔴 | BLACK WIDOW (sin secretos concretos; simulador firmado local) |

ADRs: ADR-006 (excepción egress transporte WhatsApp con IA aislada), ADR-007 (idempotencia wamid/enrutado), ADR-008 (rol app no-superusuario + SECURITY DEFINER → RLS efectiva).
Hallazgo transversal mayor: la app corría como superusuario Postgres (RLS no se aplicaba en runtime, afectaba a toda la Fase 2) → CORREGIDO con ADR-008. Egress a Meta acotado por topología (solo api/wa_send_worker) + allowlist por ruta + guardarraíl.
Estado (sandbox, sin daemon): pytest 296 passed / 121 skipped / 0 failed, black/flake8 limpios, check-externos APROBADO, docker compose config VÁLIDO, ia_internal internal:true, guardarraíl de egress 11/11.
Cierre a CERRADA pendiente de CI real (Postgres/Redis/Ollama): tests skipped en verde, cobertura ≥80%, p95 ACK webhook, concurrencia wamid, egress real. Deploy a prod requiere OK del Lead + notificación.
