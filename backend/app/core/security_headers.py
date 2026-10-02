"""
Middleware de cabeceras de seguridad HTTP — SPEC-021 (TLS/tránsito, HABEAS DATA),
endurecido por SPEC-083 (PLAN-011 F3, materialización de D-1 §11.2, ADR-016).

Complementa la política CORS ya endurecida (SPEC-013, `app/main.py`) con las
cabeceras de seguridad estándar recomendadas para una API servida detrás de
terminación TLS (RF "API/WebChat/SPA sirven por TLS/WSS"):

- `Strict-Transport-Security` (HSTS): instruye al navegador a NUNCA volver a
  intentar HTTP plano con este host una vez ha visto HTTPS (fuerza HTTPS del
  lado cliente). Solo tiene sentido si la conexión YA llegó por TLS (lo hace
  el proxy/terminador TLS delante de la API, ver `docker-compose.yml`/
  `Caddyfile` — la API en sí no termina TLS, es responsabilidad del
  reverse-proxy en despliegue on-prem, QUICKSILVER). `max-age=31536000`
  (1 año) + `includeSubDomains`, SIN `preload` (requiere registro manual en
  la lista de precarga de navegadores, fuera de alcance; posible
  endurecimiento futuro). Es inocua sobre HTTP plano en desarrollo: el
  navegador solo la respeta sobre una respuesta HTTPS real.
- `X-Content-Type-Options: nosniff`: evita que el navegador reinterprete el
  `Content-Type` declarado (mitiga ataques de sniffing/XSS).
- `X-Frame-Options: DENY`: evita que la API se embeba en un `<iframe>` de
  otro origen (defensa en profundidad contra clickjacking; la API es JSON,
  no HTML, pero `/docs`/`/redoc` sí renderizan HTML).
- `Referrer-Policy: no-referrer`: evita filtrar la URL (que puede incluir
  tokens/ids de recursos) al navegar hacia fuera.
- `Content-Security-Policy`: **ESTRICTA GLOBAL** (`default-src 'self'`, SIN
  `'unsafe-inline'`) para TODA la API (`/api/*`, `/metrics`, `/healthz`,
  etc.) — D-1 resuelta por el arquitecto (PLAN-011 §11.2, ADR-016; NO se
  reabre): el `'unsafe-inline'` que existía antes SOLO era necesario para
  que Swagger UI (`/docs`) y ReDoc (`/redoc`) renderizaran estilos/JS
  inline. La resolución correcta NO es relajar la CSP de toda la API por
  dos rutas de documentación: en producción, Swagger/ReDoc se DESHABILITAN
  (`docs_url=None`/`redoc_url=None` en `app/main.py`, fuera de
  `development`) — reduce superficie para un backend con PHI potencial
  (ADR-009) — y mientras siguen activos en desarrollo, reciben una CSP
  propia relajada SOLO para esas 2 rutas (ver `_DOCS_CSP_OVERRIDE` abajo),
  nunca aplicada al resto de la API.
- `Permissions-Policy`: deshabilita APIs de navegador sensibles no usadas
  por esta API (cámara, micrófono, geolocalización).

CHECKPOINT: estas cabeceras son metadatos de seguridad, no contienen PII ni
secretos; no hay excepción de auditoría aplicable.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# HSTS: 1 año + subdominios (D-1, PLAN-011 §11.2 — valor del
# `DEPLOYMENT_CHECKLIST.md`, la fuente de verdad más estricta). Sin
# `preload`: requiere registro manual en la lista de precarga de
# navegadores, fuera de alcance de esta SPEC; posible endurecimiento futuro.
_HSTS_MAX_AGE_SECONDS = 31536000

# CSP estricta global: sin 'unsafe-inline' en ningún directiva. Aplica a
# TODA la API salvo la excepción acotada de /docs//redoc (ver abajo).
_STRICT_CSP = (
    "default-src 'self'; img-src 'self' data:; "
    "style-src 'self'; script-src 'self'; "
    "frame-ancestors 'none'"
)

# Excepción ACOTADA solo para /docs y /redoc (Swagger UI/ReDoc, que inyectan
# estilos/JS inline): se aplica ÚNICAMENTE cuando esas rutas siguen activas
# (desarrollo; en producción están deshabilitadas por completo en
# `app/main.py`, `docs_url=None`/`redoc_url=None`, fuera de `development` —
# preferencia documentada en D-1/PLAN-011 §11.2). Ninguna otra ruta de la
# API recibe esta CSP relajada.
_DOCS_CSP_OVERRIDE = (
    "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "frame-ancestors 'none'"
)
_DOCS_PATHS = ("/docs", "/redoc")

_SECURITY_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": (
        f"max-age={_HSTS_MAX_AGE_SECONDS}; includeSubDomains"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": _STRICT_CSP,
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Añade cabeceras de seguridad estándar a toda respuesta HTTP.

    CSP estricta global (sin `'unsafe-inline'`) salvo excepción acotada para
    `/docs`/`/redoc` (D-1, PLAN-011 §11.2) — en producción esas rutas están
    deshabilitadas por completo (`app/main.py`), así que la excepción solo
    tiene efecto práctico en `development`.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        is_docs_route = request.url.path in _DOCS_PATHS
        for header, value in _SECURITY_HEADERS.items():
            if header == "Content-Security-Policy" and is_docs_route:
                response.headers[header] = _DOCS_CSP_OVERRIDE
            else:
                response.headers.setdefault(header, value)
        return response
