"""Métricas Prometheus — SPEC-022 (RNF-06 observabilidad).

Expone `GET /metrics` en formato de texto Prometheus (`prometheus_client`,
ya declarado en `requirements.txt`). Cubre:

  1. `http_requests_total` / `http_request_duration_seconds`: latencia y
     conteo de TODAS las peticiones HTTP, con `tenant_id` NO incluido como
     label (cardinalidad no acotada / fuga de datos entre tenants en un
     backend de métricas compartido — se usa `path`/`method`/`status_code`
     únicamente, igual que hacen los logs estructurados con `trace_id` para
     lo específico de la petición).
  2. `ai_request_duration_seconds`: latencia de las llamadas al servicio de
     IA local (Ollama) por operación (`chat`/`embed`), la métrica que THOR
     usa para verificar el objetivo RNF-04 (p95 RAG ≤ 6 s GPU).

No se instrumenta ningún cliente externo: el único emisor de
`ai_request_duration_seconds` es `app.services.ai_service.AIClient`
(CHECKPOINT SENSIBLE, `.no-externo`), que solo habla con el host interno
validado en `app/core/config.py`.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

# Registro dedicado (evita colisiones al recargar módulos en tests, algo que
# el registro global `prometheus_client.REGISTRY` no tolera bien cuando
# `importlib.reload` se usa en la suite, p.ej. `test_ai_config_egress.py`).
REGISTRY = CollectorRegistry()

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Número total de peticiones HTTP procesadas por la API",
    labelnames=("method", "path", "status_code"),
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "Duración de las peticiones HTTP (segundos), excluye WebSocket",
    labelnames=("method", "path"),
    registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10),
)

AI_REQUEST_DURATION_SECONDS = Histogram(
    "ai_request_duration_seconds",
    "Duración de las llamadas al servicio de IA local (Ollama) por operación",
    labelnames=("operation", "model"),
    registry=REGISTRY,
    # Buckets alineados al objetivo RNF-04 (p95 RAG <= 6s en GPU) con
    # cobertura para degradación documentada en CPU (varios minutos).
    buckets=(0.1, 0.25, 0.5, 1, 2, 3, 4, 5, 6, 8, 10, 20, 30, 60),
)

AI_REQUEST_ERRORS_TOTAL = Counter(
    "ai_request_errors_total",
    "Errores al hablar con el servicio de IA local, por operación y tipo",
    labelnames=("operation", "error_type"),
    registry=REGISTRY,
)


def render_latest() -> tuple[bytes, str]:
    """Devuelve `(payload, content_type)` listo para la respuesta HTTP de `/metrics`."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


@contextmanager
def observe_ai_request(operation: str, model: str) -> Iterator[None]:
    """Mide la duración de una llamada al servicio de IA local y la registra
    en `ai_request_duration_seconds{operation, model}`. Registra el error en
    `ai_request_errors_total` (sin ocultar la excepción) si la llamada falla.
    """
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        AI_REQUEST_ERRORS_TOTAL.labels(
            operation=operation, error_type=type(exc).__name__
        ).inc()
        raise
    finally:
        AI_REQUEST_DURATION_SECONDS.labels(operation=operation, model=model).observe(
            time.perf_counter() - start
        )


def observe_http_request(
    *, method: str, path: str, status_code: int, duration_seconds: float
) -> None:
    """Registra una petición HTTP completada en las métricas de latencia/conteo."""
    HTTP_REQUESTS_TOTAL.labels(
        method=method, path=path, status_code=str(status_code)
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=path).observe(
        duration_seconds
    )
