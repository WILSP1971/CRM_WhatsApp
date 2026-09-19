"""
FastAPI application entry point — OmniCore AI backend (SPEC-011)
Infraestructura base con healthcheck, OpenAPI y placeholder para endpoints.
"""

import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
import structlog

from app.api.ai import router as ai_router
from app.api.auth import router as auth_router
from app.api.contact_360 import router as contact_360_router
from app.api.contacts import router as contacts_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.messages import router as messages_router
from app.api.rag import router as rag_router
from app.api.tenants import router as tenants_router
from app.api.privacy import router as privacy_router
from app.api.ws_chat import router as ws_chat_router
from app.integrations.whatsapp.webhook import router as whatsapp_webhook_router
from app.core.metrics import observe_http_request, render_latest
from app.core.redis_client import close_redis_client
from app.core.request_id import RequestIDMiddleware
from app.core.security_headers import SecurityHeadersMiddleware

# Configuración de logging estructurado
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Leer configuración desde variables de entorno
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
API_PORT = int(os.getenv("API_PORT", 8000))

# CORS (BLACK WIDOW, SPEC-013 MEDIO-1): allowlist explícita desde env, NUNCA
# comodín "*" combinado con `allow_credentials=True` (la especificación CORS
# prohíbe esa combinación por buen motivo: expondría cualquier origen a
# credenciales/cookies/Authorization). En development, si no se define
# `CORS_ORIGINS`, se usa una allowlist local fija (no un comodín). Fuera de
# development, `CORS_ORIGINS` vacío deshabilita credenciales en vez de
# abrir el comodín.
_cors_origins_raw = os.getenv("CORS_ORIGINS", "").strip()
if _cors_origins_raw:
    CORS_ORIGINS = [
        origin.strip() for origin in _cors_origins_raw.split(",") if origin.strip()
    ]
elif ENVIRONMENT == "development":
    CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]
else:
    CORS_ORIGINS = []

# Si no hay ningún origen permitido (p.ej. producción sin CORS_ORIGINS
# configurado), NUNCA se habilitan credenciales con comodín: se deshabilita
# `allow_credentials` y se sirve una allowlist vacía (bloquea CORS en vez de
# abrir `allow_origins=["*"]`).
CORS_ALLOW_CREDENTIALS = bool(CORS_ORIGINS)
if not CORS_ORIGINS:
    logger.warning(
        "CORS_ORIGINS vacío fuera de development: CORS deshabilitado "
        "(sin credenciales ni comodín) por seguridad (C3/BLACK WIDOW)."
    )


# Lifespan: inicialización y cleanup
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ejecuta al iniciar y detener la aplicación."""
    logger.info("FastAPI application starting", environment=ENVIRONMENT)
    yield
    await close_redis_client()
    logger.info("FastAPI application shutting down")


# Crear aplicación FastAPI
app = FastAPI(
    title="OmniCore AI Backend",
    description="API del CRM omnicanal con IA local (SENSIBLE: .no-externo)",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Middleware CORS (allowlist explícita; nunca "*" + credenciales, ver arriba)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cabeceras de seguridad (HSTS/CSP/nosniff/etc.) y correlación por
# request-id para auditoría HABEAS DATA (SPEC-021). El orden de
# `add_middleware` en Starlette es LIFO en ejecución: se añaden después de
# CORS para que se apliquen a TODAS las respuestas, incluidas las de error.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Mide latencia/conteo de cada petición HTTP para `/metrics` (SPEC-022,
    RNF-06). Usa la ruta con *template* (p.ej. `/api/v1/contacts/{id}`), NO
    la URL con valores reales, para no generar cardinalidad no acotada ni
    filtrar identificadores (tenant/contacto) en un backend de métricas
    potencialmente compartido entre tenants."""
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path_template = getattr(route, "path", request.url.path)
    observe_http_request(
        method=request.method,
        path=path_template,
        status_code=response.status_code,
        duration_seconds=time.perf_counter() - start,
    )
    return response


# ============================================================================
# AUTENTICACIÓN Y MULTI-TENANT (SPEC-013)
# ============================================================================
app.include_router(auth_router, prefix="/api/v1")

# ============================================================================
# API CORE REST — tenants/contactos/conversaciones/mensajes/documentos
# + contacto 360° (SPEC-014)
# ============================================================================
app.include_router(tenants_router, prefix="/api/v1")
app.include_router(contacts_router, prefix="/api/v1")
app.include_router(contact_360_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(messages_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")

# ============================================================================
# DERECHOS DEL TITULAR (HABEAS DATA/GDPR-like) — export/erase de datos
# personales de un contacto, con auditoría de acceso (SPEC-021, SENSIBLE)
# ============================================================================
app.include_router(privacy_router, prefix="/api/v1")

# ============================================================================
# CANAL WEBCHAT — WebSocket bidireccional + Redis pub/sub (SPEC-015)
# ============================================================================
app.include_router(ws_chat_router, prefix="/api/v1")

# ============================================================================
# IA LOCAL SELF-HOSTED — diagnóstico de Ollama interno (SPEC-016, SENSIBLE)
# ============================================================================
app.include_router(ai_router, prefix="/api/v1")

# ============================================================================
# PIPELINE RAG LOCAL — ingesta, recuperación pgvector y borrador citado
# (SPEC-017, SENSIBLE: embeddings/generación SOLO vía AIClient interno)
# ============================================================================
app.include_router(rag_router, prefix="/api/v1")

# ============================================================================
# CANAL WHATSAPP — webhook de recepción: challenge GET + firma HMAC-SHA256 +
# ACK rápido (SPEC-026, SENSIBLE: borde de entrada con Meta, ADR-006). NO
# hace llamadas salientes a la Graph API (eso es el envío, SPEC-029); solo
# valida y encola para el worker de ingesta (SPEC-027).
# ============================================================================
app.include_router(whatsapp_webhook_router, prefix="/api/v1")

# ============================================================================
# HEALTH CHECK ENDPOINTS (SPEC-011 RF-02)
# ============================================================================


@app.get("/healthz", tags=["Health"])
async def health_check():
    """
    Health check endpoint — verifica estado de servicios.
    Retorna 200 si todo está OK.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "environment": ENVIRONMENT,
            "timestamp": os.popen("date -Iseconds").read().strip(),
        },
    )


@app.get("/readyz", tags=["Health"])
async def readiness_check():
    """Readiness probe — verifica si la API está lista para recibir tráfico."""
    return JSONResponse(
        status_code=200,
        content={"ready": True},
    )


# ============================================================================
# MÉTRICAS PROMETHEUS (SPEC-022 RNF-06)
# ============================================================================


@app.get("/metrics", tags=["Observability"])
async def metrics():
    """Expone métricas en formato Prometheus: latencia/conteo HTTP
    (`http_request_duration_seconds`, `http_requests_total`) y latencia del
    servicio de IA local (`ai_request_duration_seconds`, usada por THOR para
    verificar el p95 RAG de RNF-04). No expone PII ni datos de tenants."""
    payload, content_type = render_latest()
    return Response(content=payload, media_type=content_type)


# ============================================================================
# RUTA RAÍZ
# ============================================================================


@app.get("/", tags=["Root"])
async def root():
    """Endpoint raíz — redirige a /docs."""
    return {
        "message": "OmniCore AI Backend — Entregable #2",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


# ============================================================================
# EXCEPTION HANDLERS
# ============================================================================


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Manejador genérico de excepciones."""
    logger.error("Unhandled exception", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )


# ============================================================================
# STARTUP / SHUTDOWN LOGGING
# ============================================================================


@app.on_event("startup")
async def startup_event():
    logger.info(
        "Application startup complete",
        port=API_PORT,
        environment=ENVIRONMENT,
    )


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutdown")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=API_PORT,
    )
