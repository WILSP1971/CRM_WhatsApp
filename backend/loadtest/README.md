# Arnés de carga/latencia — SPEC-022 (RNF-04, THOR)

Objetivos que este arnés mide (criterios de aceptación SPEC-022):

| Objetivo | Umbral | Escenario Locust |
| --- | --- | --- |
| p95 API no-IA | <= 200 ms | `GET /api/v1/contacts`, `GET /healthz` |
| p95 RAG (GPU) | <= 6 s | `POST /api/v1/rag/draft` |
| Degradación CPU | documentada, no un número fijo | mismo escenario RAG, contra Ollama en modo CPU |

Herramienta elegida: **Locust** (Python, mismo lenguaje que el backend,
sin dependencias de runtime nuevas — ver `requirements-loadtest.txt`,
instalado SOLO para esta prueba, nunca en la imagen del backend).

## Qué se ejecutó en este sandbox (HAWKEYE, sin Docker)

- Se validó el `locustfile.py` con `locust --help`/`--dry-run` cuando el
  paquete está disponible localmente (no hay backend/Postgres/Ollama vivos
  en este sandbox: `docker`/`docker compose up` da permission denied, no
  hay daemon accesible).
- **No se ejecutó una corrida real contra el backend** porque no hay un
  proceso `uvicorn` + Postgres + Redis + Ollama levantados aquí. Esto NO es
  opcional: sin ellos no hay latencia real que medir (mockear el LLM
  invalidaría la medición de RNF-04).

## Qué debe correr en CI / entorno real (checklist)

1. `docker compose up -d db redis ia api` (o equivalente en el runner de CI
   con `services:`), esperar `/healthz` y `/readyz` en verde.
2. `alembic upgrade head` (ya lo hace el fixture `postgres_engine` de
   pytest; en CI se ejecuta aparte contra el mismo Postgres).
3. Sembrar datos de carga:
   `DATABASE_URL=... python -m loadtest.seed_loadtest_user`
4. (Para medir el p95 RAG real) Ingerir al menos un documento del tenant de
   carga vía `POST /api/v1/documents` + `POST /api/v1/rag/documents/{id}/ingest`
   y esperar a que el worker RAG procese la cola — si no, `/rag/draft`
   devuelve 404 "sin contexto" y ese escenario no genera muestras de
   latencia útiles (fallo esperado y documentado, no oculto).
5. Ejecutar:
   ```
   pip install -r backend/requirements-loadtest.txt
   locust -f backend/loadtest/locustfile.py --host http://localhost:8000 \
       --headless -u 20 -r 5 -t 2m --csv=loadtest_report
   ```
6. Leer `loadtest_report_stats.csv`:
   - Fila `GET /api/v1/contacts` → columna `95%` debe ser <= 200 (ms).
   - Fila `POST /api/v1/rag/draft` → columna `95%` debe ser <= 6000 (ms) en
     GPU. Si el runner de Ollama es CPU-only (como suele ser un runner de
     GitHub Actions estándar, sin GPU), este número será mayor — se
     documenta como "degradación CPU" en el resumen del job de CI
     (`$GITHUB_STEP_SUMMARY`), NO se hace fallar el build por este umbral en
     un runner sin GPU (ver `ci-load-smoke` en `backend-ci.yml`, que corre
     este escenario con `continue-on-error: true` y solo publica el
     resultado como evidencia).
7. Adjuntar `loadtest_report_stats.csv`/`loadtest_report_failures.csv` como
   artefacto del job para trazabilidad (THOR revisa el número real, no un
   resumen editorializado).

## Métricas complementarias

`GET /metrics` (Prometheus, ver `app/core/metrics.py`) expone
`ai_request_duration_seconds{operation="chat"|"embed"}` con los mismos
buckets alineados al umbral de 6 s — permite verificar el p95 en producción
sin depender de Locust (`histogram_quantile(0.95,
rate(ai_request_duration_seconds_bucket{operation="chat"}[5m]))` en
Prometheus/Grafana).
