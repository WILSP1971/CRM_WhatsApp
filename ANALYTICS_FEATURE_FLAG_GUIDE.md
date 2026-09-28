# Guía de Feature-Flag: Dashboard de Analítica de Negocio (SPEC-064, SPEC-066)

> Cómo activar/desactivar la vista en tiempo real del dashboard de métricas de negocio.
> Clasificación: SENSIBLE (`.no-externo`). Patrón de feature-flag reutilizable (SPEC-020).

**Responsable:** Operador / DevOps · **Reversibilidad:** 100% reversible (sin código deployado) · **Impacto:** Interfaz visual únicamente.

---

## Resumen ejecutivo

El dashboard de analítica de negocio (`AnalyticsPage.tsx`) soporta dos modos:

1. **OFF (default):** Vista mock con datos ficticios — **Entregable #1 intacto**, no requiere backend.
2. **ON:** Vista en tiempo real con datos reales del tenant — conecta a `GET /api/v1/analytics/business` (SPEC-064).

La transición es **100% reversible** via la variable de entorno de compilación `VITE_USE_REAL_API` (patrón SPEC-020). No requiere cambios de código ni re-deployment de backend.

---

## Feature-flag: `VITE_USE_REAL_API`

### Ubicación en código

Definido en `src/lib/env.ts` (único punto de lectura):

```typescript
/** Feature-flag global (SPEC-020). Default OFF: maqueta 100% mock. */
export const USE_REAL_API: boolean = readBooleanFlag(
  import.meta.env.VITE_USE_REAL_API as string | undefined,
);
```

Consumido por:
- **`AnalyticsPage.tsx`** (línea 17): condicional `USE_REAL_API ? <RealAnalyticsView /> : <MockAnalyticsView />`.
- **`useAnalyticsData.ts`:** solo hace requests a `GET /api/v1/analytics/business` si `USE_REAL_API = true`.

### Configuración: `.env.local` (desarrollo) y `.env` (build CI)

#### Desarrollo local

**Archivo:** `.env.local` (gitignore'd)

```bash
# Para ver mock (default, OFF):
# (sin VITE_USE_REAL_API, usa el default)

# Para ver datos reales (ON):
VITE_USE_REAL_API=true
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

**Cambio:** editar `.env.local`, guardar, el dev server recarga automáticamente (Vite hot reload).

**Verificación:**
```bash
cd /home/swarm/proyectos/CRM_WhatsApp
npm run dev
# Abrir http://localhost:5173 → AnalyticsPage
# Con VITE_USE_REAL_API=false: ves KPIs mock (SPEC-008)
# Con VITE_USE_REAL_API=true: ves selector de rango + datos reales
```

#### Build CI (on-prem / production)

**Archivo:** `.env` (en el host on-prem)

```bash
# Variables de frontend
VITE_USE_REAL_API=true
VITE_API_BASE_URL=https://app.tudominio.com/api/v1  # O http://localhost:8000/api/v1 en dev
```

**Build Docker:** en la imagen frontend (`Dockerfile.spa`), se ejecuta:

```bash
npm run build
# Vite lee import.meta.env.VITE_USE_REAL_API del .env del host durante compilación
# Inyecta el valor en el bundle (no es runtime, es compile-time)
```

**Cambio:** editar `.env` del host, re-hacer `docker build` de `Dockerfile.spa` (o usar `docker-compose build --no-cache spa`), re-deployar `docker compose up -d`.

---

## Modos: Mock vs. Real

### Modo OFF (Mock) — Entregable #1 intacto

**Variable:** `VITE_USE_REAL_API` ausente o falsa (`false`, `0`, vacío).

**Comportamiento visual:**
- ✓ Vista de KPIs generales (SPEC-008): "Conversaciones totales", "Revenue por Sector", "Pipeline", "CSAT Trend", etc.
- ✓ Datos ficticios de `src/mocks/kpis.json`, `src/mocks/analytics.json`, `src/mocks/sales.json`.
- ✗ No hay selector de rango de fechas.
- ✗ No hay selector de canal.
- ✗ No hay datos reales del backend.
- ✗ `useAnalyticsData` no ejecuta ningún fetch.

**Caso de uso:**
- Prototipado rápido sin backend.
- Feature disponible pero desactivada por defecto (seguridad).
- Testing del estilo y layouts sin datos.

### Modo ON (Real) — Dashboard de negocio (SPEC-064)

**Variable:** `VITE_USE_REAL_API=true`.

**Comportamiento visual:**
- ✓ Selector de rango (hoy / 7 últimos días / 30 últimos días / custom).
- ✓ Selector de canal (filtro opcional).
- ✓ KPIs en tiempo real: "Conversaciones totales", "Abiertas / cerradas", "TPR promedio", "Tasa de conversión", etc.
- ✓ Gráficos: serie diaria de conversaciones, desglose por canal, asistencia IA (si disponible).
- ✓ Estado de carga: spinner durante fetch.
- ✓ Error handling: banner de error con botón de "Reintentar" (AAA, SPEC-009).
- ✗ No hay datos ficticios.
- ✗ Requiere backend `GET /api/v1/analytics/business` disponible y autenticado.

**Caso de uso:**
- Operación on-prem: el supervisor ve las métricas en tiempo real.
- Auditoría: datos se almacenan SOLO en PostgreSQL, bajo RLS (ADR-004/008), sin caché.
- Performance: p95 latencia ≤ 1500 ms (THOR, SPEC-065).

---

## Procedimiento: Activar/Desactivar la feature-flag

### Paso 1: Editar `.env`

```bash
# En el host on-prem donde está docker-compose.yml
cd /ruta/a/CRM_WhatsApp

# Abrir .env en editor (ya debería existir, basado en .env.example)
nano .env
```

### Paso 2: Buscar o agregar la variable

```bash
# Buscar existentes:
grep VITE_USE_REAL_API .env

# Si no existe, agregar al final (o en la sección "Frontend"):
echo "" >> .env
echo "# Dashboard de Analítica (SPEC-064)" >> .env
echo "VITE_USE_REAL_API=true" >> .env
echo "VITE_API_BASE_URL=http://localhost:8000/api/v1" >> .env
```

### Paso 3: Re-compilar frontend

```bash
# Opción A: rebuild en Docker
docker-compose build --no-cache spa

# Opción B: si la imagen spa está pre-built (verify en docker-compose.yml)
# Recrear el contenedor:
docker-compose up -d spa --force-recreate
```

### Paso 4: Verificar

```bash
# Esperar a que el contenedor esté listo (healthcheck)
docker compose ps spa
# Debe mostrar "(healthy)" o "Up"

# Acceder a la SPA en navegador
curl -s http://localhost:5173 | grep -i "analytics\|conversaciones"
# O visualmente: http://localhost:5173 → ir a "Analytics" → verifica selector de rango

# Si ves el selector de rango + KPIs en tiempo real: ✓ ON
# Si ves KPIs mock (SPEC-008) sin selector: ✓ OFF
```

### Paso 5: Rollback (si es necesario)

**Revertir a mock (OFF):**

```bash
# Editar .env
nano .env
# Cambiar:
# VITE_USE_REAL_API=false

# Rebuild
docker-compose build --no-cache spa
docker-compose up -d spa --force-recreate

# Verificar
docker compose ps spa
```

**Tiempo de operación:** ~2 min (rebuild del contenedor).

---

## Variables de configuración relacionadas

### Backend

**`ANALYTICS_MAX_RANGE_DAYS`** (`.env`, default 366)

Define el máximo número de días que una query puede solicitar (query param `desde` y `hasta`). Protege contra queries runaway.

```bash
# En .env
ANALYTICS_MAX_RANGE_DAYS=366
```

Si un operador solicita un rango mayor: HTTP 422.

### Frontend

**`VITE_API_BASE_URL`** (`.env`, default `http://localhost:8000/api/v1`)

URL base del backend. Solo se usa si `VITE_USE_REAL_API=true`.

```bash
# Desarrollo local (backend en puerto 8000)
VITE_API_BASE_URL=http://localhost:8000/api/v1

# On-prem con reverse proxy
VITE_API_BASE_URL=https://app.tudominio.com/api/v1
```

**`VITE_WS_BASE_URL`** (`.env`, default `ws://localhost:8000/api/v1`)

URL base del WebSocket (fuera de alcance de SPEC-064, pero documentado para completitud).

---

## Checklist: Activar dashboard de analítica en on-prem

Usar este checklist antes de hacer público el dashboard en producción:

- [ ] **Seguridad (C3)**
  - [ ] `VITE_USE_REAL_API=true` en `.env` del host.
  - [ ] `VITE_API_BASE_URL` apunta al dominio correcto (HTTPS si es on-prem externo).
  - [ ] JWT autenticación activa: `GET /api/v1/analytics/business` requiere header `Authorization: Bearer <token>`.

- [ ] **Backend disponible**
  - [ ] `docker compose ps api` muestra "Up" o "(healthy)".
  - [ ] `curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/analytics/business?desde=2026-09-20&hasta=2026-09-27` devuelve 200 (o 422 si rango inválido).

- [ ] **Frontend compilado**
  - [ ] `docker compose ps spa` muestra "Up" o "(healthy)".
  - [ ] Acceso a `http://localhost:5173` (o dominio on-prem).
  - [ ] Página "Analytics" muestra selector de rango + datos reales (no mock).

- [ ] **RLS verificada**
  - [ ] Usuario A no ve conversaciones de tenant B (test: multi-tenant fixture).
  - [ ] Tests de SPEC-065 pasan sin error.

- [ ] **Performance verificada**
  - [ ] Latencia p95 ≤ 1500 ms (medir con `curl` o DevTools).
  - [ ] No hay queries a APIs externas (verificar con `check-externos-backend.sh`).

- [ ] **Reversibilidad**
  - [ ] Puedo cambiar `VITE_USE_REAL_API=false` y rebuild sin romper nada.
  - [ ] Mock sigue disponible si la feature se desactiva.

---

## Referencias

- **src/lib/env.ts:** definición de la variable y lectura.
- **src/pages/AnalyticsPage.tsx:** uso en componente (MockAnalyticsView vs. RealAnalyticsView).
- **src/lib/dataProvider/useAnalyticsData.ts:** hook que hace el fetch (solo si `USE_REAL_API`).
- **backend/app/api/analytics.py:** endpoint `GET /api/v1/analytics/business`.
- **SPEC-020:** patrón general de feature-flags (Entregable #1 vs. real API).
- **SPEC-064:** implementación del dashboard.
- **METRICS_ANALYTICS.md:** documentación de métricas (qué calcula cada KPI).
- **.env.example:** template con todas las variables.

---

**Última actualización:** 2026-09-28 (SPEC-066) · **Clasificación:** SENSIBLE (`.no-externo`)
