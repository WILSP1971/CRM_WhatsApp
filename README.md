# OmniCore AI — Maqueta + Backend + IA 100% on-prem (CRM omnicanal)

**Entregable #1:** Maqueta SPA de alta fidelidad y navegable del dashboard "OmniCore AI", construida con
**React 18 + Vite + TypeScript + Tailwind CSS**.

**Entregable #2 (Fase F9):** Backend FastAPI funcional + PostgreSQL + Redis + Ollama (IA local) en Docker Compose,
con autenticación multi-tenant (RLS), RAG con citas trazables, WebChat bidireccional, y **cero llamadas a APIs externas de inferencia** (SENSIBLE).

> Proyecto **SENSIBLE** (`.no-externo`): prohibido cualquier CDN, fuente remota,
> telemetría o llamada de red en tiempo de ejecución (IA local únicamente). Ver `scripts/check-externos.sh` (SPA) y `backend/check-externos-backend.sh` (backend).

## Requisitos

- Node.js 20+
- npm 10+

## Ejecución

```bash
npm install
npm run dev       # servidor de desarrollo (http://localhost:5173)
npm run build     # build de producción (tsc -b && vite build)
npm run preview   # sirve el build de producción localmente
```

## Scripts

```bash
npm run dev             # Servidor de desarrollo (http://localhost:5173)
npm run build           # Build de producción: tsc -b && vite build
npm run preview         # Sirve el build de producción localmente
npm run lint            # ESLint (incluye reglas jsx-a11y, sin console.error)
npm run format          # Prettier (escribe)
npm run format:check    # Prettier (solo verifica)
npm run test            # Vitest: contraste WCAG AAA (32 tests) + smoke-render
npm run check:externos  # Verifica cero URLs http(s) externas en código
```

## Calidad y verificación

- **Lint sin errores** (ESLint + jsx-a11y).
- **Tests vitest: 32/32** (contraste WCAG AAA de tokens + smoke-render de las 8 páginas).
- **Cero URLs externas** en runtime (`check:externos` ✓).
- **Accesibilidad AAA** verificada: contraste ≥7:1, motion-reduce, roles ARIA, foco visible.
- **Lighthouse CI** en pipeline (GitHub Actions): Accessibility ≥90, Performance ≥90.

## Módulos (6 espacios omnicanal)

1. **Bandeja unificada** — Conversaciones, llamadas, mensajes en un feed único (SPEC-004).
2. **Contactos 360°** — Ficha completa con histórico de interacciones (SPEC-004).
3. **Centro RAG** — Búsqueda semántica + documentos (SPEC-005, representación).
4. **VoiceBot** — Integración VoIP + transcripción simulada (SPEC-006, representación).
5. **Sync ERP** — Sincronización de datos con sistemas externos (SPEC-008).
6. **Flujos automatizados** — Reglas y automatización de conversaciones (SPEC-008).
7. **Analítica multisectorial** — Dashboard de KPIs por sector (SPEC-008).

Todos los datos son **100% mock** (fixtures JSON en `src/mocks/`). Ningún módulo realiza llamadas
externas. Tema claro/oscuro con toggle en el menú de perfil (header).

## Sensibilidad del proyecto

Proyecto clasificado **SENSIBLE** (`.no-externo`):
- Cero CDN, cero telemetría, cero recurso externo en runtime.
- Datos ficticios; sin PII real, sin backend real, sin IA/LLM real.
- Tipografía Inter self-hosted vía `@font-face` (fallback `system-ui` si `.woff2` no se
  agregó localmente; ver `public/fonts/README.md`).
- Verificación: `npm run check:externos` (exit 0 = verde, script `scripts/check-externos.sh`).
- Build CI: nunca descarga dependencias externas en runtime ni en tiempo de compilación.

## Estructura del proyecto

```
src/
  components/ui/    Primitivas accesibles: Button, Card, Badge, Input, Tabs, Tooltip
  layout/            Sidebar, Header, TenantSwitcher, NotificationsCenter, UserMenu...
  pages/             Páginas de cada módulo (placeholder hasta sus SPECs funcionales)
  routes/            AppRouter (react-router-dom)
  hooks/             Hooks compartidos (p. ej. estado del sidebar)
  lib/               Utilidades: theme, cn, tipos, navegación, búsqueda mock
  mocks/             Fixtures JSON ficticias (contactos, conversaciones, llamadas, KPIs...)
  styles/            tokens.css (design tokens), fonts.css (Inter self-hosted), globals.css
public/
  fonts/             Aquí se copian los .woff2 de Inter (ver public/fonts/README.md)
scripts/
  check-externos.sh  Verificación "cero llamadas externas"
```

## Sistema de diseño (resumen — SPEC-002)

Los tokens viven como CSS variables en `src/styles/tokens.css` y se exponen a Tailwind
en `tailwind.config.ts` (cero color/spacing/radio hardcodeado en componentes).

- **Paleta:** fondo azul marino/pizarra profundo, acentos índigo eléctrico y cian
  (estados de IA), tarjetas gris claro/neutro, estados esmeralda/ámbar/coral.
- **Tipografía:** Inter, self-hosted vía `@font-face` en `src/styles/fonts.css`
  (fallback a `system-ui` si los `.woff2` locales aún no se agregaron; ver
  `public/fonts/README.md`). Prohibido Google Fonts / CDN.
- **Radios:** 12–16px (`--radius-md` a `--radius-xl`).
- **Sombras:** suaves, para profundidad sutil (`--shadow-sm/md/lg`).
- **Glassmorphism:** clase utilitaria `.glass-surface` — SIEMPRE con una capa de fondo
  casi opaca (`--surface-glass-solid`) detrás del `backdrop-filter: blur(...)`, para
  garantizar contraste WCAG AAA (≥7:1) incluso bajo el vidrio (checkpoint R-02).
- **Temas:** oscuro (por defecto) y claro, alternables con el toggle del menú de
  perfil (header). Persisten en `localStorage` y se aplican antes del primer paint
  (script inline en `index.html`) para evitar parpadeo (FOUC).
- **Primitivas UI:** `Button`, `Card`, `Badge`, `Input`, `Tabs`, `Tooltip` en
  `src/components/ui/`, construidas sobre Radix UI (dependencia de build local, sin
  llamadas de red en runtime), con foco visible y roles ARIA.

## Layout y navegación (resumen — SPEC-003)

- Sidebar plegable (persistente durante la sesión) con los 7 espacios: Bandeja
  unificada, Contactos 360°, Centro de llamadas VoiceBot, Centro RAG, Sync ERP,
  Flujos automatizados y Analítica multisectorial.
- Header con búsqueda semántica simulada (categorías: Contactos, Conversaciones,
  Documentos RAG), widget de estado del VoiceBot, selector de inquilino/empresa,
  centro de notificaciones y menú de perfil (incluye el toggle de tema).
- Routing SPA con `react-router-dom`; cada módulo aún no implementado muestra una
  página de marcador de posición que indica en qué SPEC se desarrollará.

## Despliegue on-prem (Entregable #2, SPEC-023)

### Guías de operación

**Lectura recomendada en orden:**

1. **[`OPERACION.md`](./OPERACION.md)** — Guía de despliegue local con Docker Compose
   - Requisitos previos (hardware GPU/CPU recomendado, RAM, almacenamiento)
   - Preparación del entorno (secretos fuertes en `.env`, validation)
   - Arranque de servicios y healthchecks
   - Descarga de modelos Ollama (qwen2.5 + nomic-embed-text)
   - Migraciones de BD, seed inicial
   - Verificación de "cero externos" (auditoría SENSIBLE)
   - Parada ordenada

2. **[`RUNBOOK.md`](./RUNBOOK.md)** — Operación y troubleshooting 24x7
   - Arranque/parada ordenado y startup completo tras apagón
   - Healthchecks detallados (5 comandos rápidos)
   - Backups de PostgreSQL (manual y automático con cron)
   - Restauración desde backup
   - Rotación de secretos (DB_PASSWORD, JWT_SECRET_KEY, CORS_ORIGINS)
   - **Respuesta a incidentes comunes:**
     - Redis caído → restart o limpiar caché
     - PostgreSQL caído → restart o restaurar backup
     - Ollama no responde (timeout, OOM) → restart, cambiar modelo a Q4
     - Worker RAG/sentimiento se queda atascado → restart, ver logs
     - API en loop de crashes → validar .env, dependencias, config
   - Procedimiento de rollback (downgrade migraciones, cambio de imagen)
   - Verificación de egress bloqueado (SENSIBLE, red `ia_internal` con `internal: true`)
   - Verificación de aislamiento multi-tenant (RLS, test cross-tenant debe fallar)
   - Logs y observabilidad (JSON estructurado, métricas Prometheus)
   - Escenarios de degradación (sin GPU → CPU Q4, poco almacenamiento, tráfico alto)

3. **[`DEPLOYMENT_CHECKLIST.md`](./DEPLOYMENT_CHECKLIST.md)** — Pre-flight para producción
   - Fase 1: Secretos (C3) — fuertes, en secret manager, no en código
   - Fase 2: Red y firewall — `ia_internal` con `internal: true`, puertos restringidos
   - Fase 3: TLS/HTTPS — reverse proxy (Nginx/Traefik), certificado válido
   - Fase 4: BD (C2) — borrado lógico, migraciones reversibles, backups, retención HABEAS DATA
   - Fase 5: Modelos locales — descargados y verificados, fallback CPU Q4 documentado
   - Fase 6: Observabilidad — healthz, logs JSON, métricas Prometheus, alertas
   - Fase 7: Multi-tenant y RLS — activo, inyección de tenant_id, test cross-tenant
   - Fase 8: Integración SPA — feature flag `VITE_USE_REAL_API`, CORS allowlist
   - Fase 9: Pruebas de carga (THOR) — p95 dentro de SLA (200 ms REST, 6 s RAG GPU)
   - Fase 10: Documentación — OPERACION.md, RUNBOOK.md, EXAMPLES_OPENAPI.md
   - Fase 11: Aprobación del Lead (C6) — antes de Phase 12
   - Fase 12: Deploy ejecutado — notificación Telegram, pasos ordenados, monitoreo 24 h
   - Fase 13: Cierre de SPEC-023 — documentar fecha/versión, marcar como CERRADA

4. **[`EXAMPLES_OPENAPI.md`](./EXAMPLES_OPENAPI.md)** — Ejemplos de API ejecutables
   - Health checks (`/healthz`, `/readyz`)
   - Autenticación (login con JWT)
   - Conversaciones (CRUD)
   - Mensajes y WebChat (WebSocket bidireccional)
   - Contactos (CRUD)
   - RAG — Borrador con ≥3 citas trazables (source, excerpt, similarityScore)
   - Análisis de sentimiento (clasificación con LLM local)
   - Derechos de datos (HABEAS DATA) — export/erase
   - Métricas (Prometheus)
   - Todos los ejemplos con request/response reales

### Makefile de operación

Comando rápido para tareas comunes (sin escribir `docker compose` a mano):

```bash
make help                   # Listar todos los targets
make setup                  # Preparar .env y validar compose
make up                     # Arrancar (docker compose up -d)
make down                   # Parar servicios (volúmenes persisten)
make clean                  # Remover todo (CUIDADO: borra datos)
make health                 # Verificar salud de BD, Redis, Ollama, API
make migrate                # Ejecutar migraciones (alembic upgrade head)
make seed                   # Sembrar datos ficticios (tenant demo)
make models                 # Descargar modelos Ollama (qwen2.5 + embeddings)
make models-q4              # Descargar modelo Q4 (CPU)
make backup                 # Backup de PostgreSQL
make restore                # Restaurar desde backup
make test-egress            # Verificar egress bloqueado
make check-externos         # Auditoría de "cero externos"
make logs                   # Ver logs en tiempo real (todos)
make logs-api               # Ver logs de la API
make stats                  # Estadísticas de recursos
make shell-api              # Shell en contenedor API
make shell-db               # psql en contenedor DB
```

Ejemplo de workflow típico:

```bash
make setup          # Preparar entorno (primera vez)
make up             # Arrancar
make health         # Verificar salud
make migrate        # Migraciones
make seed           # Datos iniciales
make models         # Descargar modelos (esperar 20–45 min)
make test-egress    # Verificar egress bloqueado
make check-externos # Auditoría SENSIBLE
# Listo para usar: curl http://localhost:8000/healthz
```

### Arquitectura de referencia

```
┌─────────────────────────────────────────────────────────────────┐
│                  HOST ON-PREM (Docker Compose)                   │
│                                                                   │
│  ┌──────────────┐        ┌────────────────────┐                 │
│  │ SPA (React)  │──HTTPS─│  Reverse Proxy     │ ◄──Internet     │
│  │ +Vue/Vite    │        │  (Nginx/Traefik)   │                 │
│  │ feature-flag │        │  TLS termination   │                 │
│  └──────────────┘        └─────┬──────────────┘                 │
│                                 │ (red interna)                 │
│  ┌──────────────┐               │                               │
│  │ API FastAPI  │◄──────────────┘                               │
│  │ JWT + RLS    │                                               │
│  │ WebSocket WS │  ◄──────────────┐                             │
│  └──┬──────┬────┘                  │                             │
│     │      │ (SQL + RLS)           │ (pub/sub)                  │
│  ┌──▼──────▼─────────────────────┐ │                            │
│  │ PostgreSQL 16 + pgvector       │ │                            │
│  │ RLS por tenant_id              │ │                            │
│  │ Borrado lógico (C2)            │ │                            │
│  │ Migraciones versionadas        │ │                            │
│  └───────────────────────────────┘ │                            │
│                                     │                            │
│  ┌──────────────────────────────┐  │                            │
│  │ Redis 7 (caché + colas)      │◄─┘                            │
│  │ AOF persistence              │                               │
│  │ Pub/sub WebChat              │                               │
│  └──────────────────────────────┘                               │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │        RED `ia_internal` (internal: true)                  │ │
│  │        EGRESS BLOQUEADO A INTERNET                         │ │
│  │                                                             │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │ Ollama (IA local)                                    │  │ │
│  │  │ - qwen2.5:7b-instruct (LLM)                         │  │ │
│  │  │ - nomic-embed-text (embeddings)                     │  │ │
│  │  │ - Modelo Q4 (fallback CPU)                          │  │ │
│  │  │ ⛔ SIN salida a internet (política .no-externo)    │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │                                                             │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │ Workers asíncronos (mismo host)                      │  │ │
│  │  │ - rag_ingest_worker (ingesta + chunking + embeddings)   │ │
│  │  │ - sentiment_worker (análisis de sentimiento)        │  │ │
│  │  │ - retention_job (anonimización, HABEAS DATA)        │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  Observabilidad:                                                │
│  - Logs estructurados (JSON, structlog)                         │
│  - /healthz, /readyz (health checks)                           │
│  - /metrics (Prometheus)                                        │
│  - X-Request-ID (trazas)                                       │
│                                                                   │
│  Seguridad (C2/C3):                                             │
│  - JWT en Authorization header (sin exposición)               │
│  - DB_PASSWORD, JWT_SECRET_KEY en secret manager (no .env)   │
│  - Borrado lógico (is_active flag) — nunca DELETE físico     │
│  - Auditoría de acceso (logs con tenant_id/user_id/action)  │
│  - TLS en tránsito (reverse proxy)                           │
│  - Datos personales: cifrado en reposo, retención configurable │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Próximos pasos (Fase 3+, fuera de Entregable #2)

- SPEC-024+: VoIP/VoiceBot con Whisper (STT) y TTS local
- Integración con canales reales: WhatsApp Business API, Instagram DM, Messenger (WABA/BSP)
- ERP real: sincronización bidireccional de inventario/pedidos/órdenes
- Escalado horizontal: Kubernetes, multi-nodo, HA, carga distribuida
- Detección avanzada de intención (más allá de sentimiento)
- Automatización de workflows y campañas
