# Arnés de carga/latencia — SPEC-022 (RNF-04, THOR) + SPEC-033 (webhook WhatsApp) + SPEC-042 (RTF del STT)

Objetivos que este arnés mide (criterios de aceptación SPEC-022/SPEC-033/SPEC-042):

| Objetivo | Umbral | Escenario Locust |
| --- | --- | --- |
| p95 API no-IA | <= 200 ms | `GET /api/v1/contacts`, `GET /healthz` (`OmniCoreApiUser`) |
| p95 RAG (GPU) | <= 6 s | `POST /api/v1/rag/draft` (`OmniCoreApiUser`) |
| Degradación CPU | documentada, no un número fijo | mismo escenario RAG, contra Ollama en modo CPU |
| **p95 ACK webhook WhatsApp** | **<= 500 ms** | `POST /api/v1/whatsapp/webhook` con firma HMAC válida (`WhatsAppWebhookUser`, SPEC-026/SPEC-033) |
| **RTF del `stt_worker` bajo carga** | **<= 1.0 en GPU** (o degradación CPU documentada) | `PbxRecordingWebhookUser` genera la carga (`POST /webhooks/pbx/recordings`); el RTF se LEE de `stt_rtf` en `/metrics` tras la corrida (SPEC-042, RNF-42) — ver sección dedicada abajo |

## Escenario de carga/RTF del STT (SPEC-042, RNF-42)

`PbxRecordingWebhookUser` empuja grabaciones ficticias es-CO (fixtures WAV
sintéticos de `backend/tests/fixtures_audio/synthetic_call_audio.py` — tono/
silencio, SIN habla real ni PHI, ver el docstring de ese módulo) al webhook
`POST /webhooks/pbx/recordings` con firma HMAC-SHA256 válida
(`X-Webhook-Signature-256`, verificada por `app/integrations/pbx/webhook.py`,
SPEC-037), generando trabajos reales en la cola `stt:jobs` que uno o más
procesos `stt_worker` consumen con el modelo `faster-whisper` REAL (pesos
reales, GPU/CPU real).

**Importante:** a diferencia de `WhatsAppWebhookUser`, este escenario NO mide
el RTF directamente con Locust — el `stt_worker` es un consumidor de cola
batch, no un endpoint HTTP. Lo que Locust mide aquí es el ACK del transporte
(rápido por diseño, igual que el resto de webhooks del proyecto). El RTF real
bajo la carga generada se obtiene LEYENDO la métrica Prometheus que el propio
`stt_worker` expone:

```
locust -f backend/loadtest/locustfile.py --host http://localhost:8000 \
    --headless -u 10 -r 2 -t 3m --csv=loadtest_stt_report \
    PbxRecordingWebhookUser
```

Requiere en el backend real:
- `PBX_LINES` con al menos una fila cuyo `numero_destino` coincida con
  `LOADTEST_PBX_NUMERO_DESTINO` (mapeada a un tenant real), o
  `recording_ingest_worker` descarta el evento auditado (RF-03 SPEC-037) y
  el job nunca llega a `stt:jobs`/`stt_worker` — el ACK del webhook en sí no
  depende de esto, pero sin la línea mapeada NO hay carga real de STT.
- `LOADTEST_PBX_WEBHOOK_SECRET` = mismo `WEBHOOK_SECRET` del backend bajo
  prueba (C3, nunca un secreto de producción).

Tras la corrida (dar tiempo a que `N stt_worker` drenen `stt:jobs` —
puede tardar más que la ventana de la corrida de Locust si el RTF está
degradado, revisar `stt_queue_latency_seconds`/`stt_jobs_total` también):

```
curl -s http://localhost:8000/metrics | grep -E '^stt_rtf'
```

Leer los `_bucket`/`_sum`/`_count` del histograma `stt_rtf{model=...,
device=...}`: el p95 (`histogram_quantile(0.95, rate(stt_rtf_bucket[...]))`
en Prometheus/Grafana, o el cálculo manual sobre los buckets exportados) debe
ser `<= 1.0` en GPU (`device="cuda"`). Si el `stt_worker` corrió en modo
fallback CPU (`device="cpu"`, RNF-42/R-42), el RTF será mayor — se documenta
como degradación CPU explícita, NO se hace fallar el build en un entorno sin
GPU (mismo criterio que el escenario RAG de `OmniCoreApiUser`).

**Qué se ejecutó en este sandbox (HAWKEYE, sin GPU/Postgres/Redis reales):**
se validó que `locustfile.py` PARSEA e IMPORTA correctamente
(`locust -f backend/loadtest/locustfile.py --list` lista
`PbxRecordingWebhookUser`) y que reutiliza los mismos fixtures WAV validados
por `backend/tests/test_stt_e2e_synthetic_audio.py`. **No se ejecutó una
corrida real** — no hay `stt_worker`/GPU/Postgres/Redis vivos aquí; el RTF
real bajo carga queda pendiente de medición en CI/entorno real con GPU
(checklist siguiente).

## Escenario de webhook (SPEC-033, RNF-02)

`WhatsAppWebhookUser` firma cada request con HMAC-SHA256 sobre el RAW body
(igual que Meta / `tests/test_whatsapp_webhook.py`), usando
`LOADTEST_WHATSAPP_APP_SECRET` (debe coincidir con el `WHATSAPP_APP_SECRET`
real del backend bajo prueba — nunca un secreto de producción, C3). Mide
SOLO el ACK síncrono (200 + encolado en `wa:inbound`); el procesamiento
async (`whatsapp_inbound_worker`, SPEC-027) queda fuera del umbral por
diseño (SPEC-026 RNF-02: el ACK debe ser rápido precisamente porque no
espera al procesamiento).

Ejecutar SOLO este escenario (aislado del resto, para no mezclar el ACK del
webhook con la latencia del login/RAG en el mismo CSV):

```
LOADTEST_WHATSAPP_APP_SECRET=$WHATSAPP_APP_SECRET \
LOADTEST_WHATSAPP_PHONE_NUMBER_ID=000000000000001 \
locust -f backend/loadtest/locustfile.py --host http://localhost:8000 \
    --headless -u 20 -r 5 -t 1m --csv=loadtest_webhook_report \
    WhatsAppWebhookUser
```

Leer `loadtest_webhook_report_stats.csv`: columna `95%` de la fila
`POST /api/v1/whatsapp/webhook (firma válida)` debe ser <= 500 (ms).

Sin `LOADTEST_WHATSAPP_APP_SECRET`, `WhatsAppWebhookUser` se detiene de
inmediato (fail-fast, no genera tráfico contra un endpoint que exige HMAC
válido) — igual que `OmniCoreApiUser` cuando el login falla.

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
8. (SPEC-042, RTF del STT) `docker compose up -d stt_worker` con los pesos
   reales de `faster-whisper` montados por volumen (`STT_MODEL_DIR`,
   ADR-009); sembrar `pbx_lines` con `numero_destino` mapeado a un tenant
   real; ejecutar el escenario `PbxRecordingWebhookUser` (ver sección
   dedicada arriba); leer `stt_rtf` en `/metrics` tras dar tiempo a que
   `stt_worker` drene `stt:jobs`; adjuntar el resultado
   (`loadtest_stt_report_stats.csv` + el scrape de `/metrics`) como
   evidencia de RNF-42, igual criterio de "no ocultar degradación CPU" que
   el escenario RAG.

## Métricas complementarias

`GET /metrics` (Prometheus, ver `app/core/metrics.py`) expone
`ai_request_duration_seconds{operation="chat"|"embed"}` con los mismos
buckets alineados al umbral de 6 s — permite verificar el p95 en producción
sin depender de Locust (`histogram_quantile(0.95,
rate(ai_request_duration_seconds_bucket{operation="chat"}[5m]))` en
Prometheus/Grafana).

También expone `stt_rtf{model,device}` (histograma), `stt_queue_latency_seconds`
(histograma) y `stt_jobs_total{resultado}` (contador ok/error/duplicado) —
SPEC-038/042, RNF-42 — sin label de `tenant_id` (ver "Observabilidad por
tenant" en el reporte de HAWKEYE de SPEC-042 para la evaluación explícita de
por qué no se añadió y qué trade-off implica añadirlo).
