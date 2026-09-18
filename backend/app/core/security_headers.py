"""
Middleware de cabeceras de seguridad HTTP — SPEC-021 (TLS/tránsito, HABEAS DATA).

Complementa la política CORS ya endurecida (SPEC-013, `app/main.py`) con las
cabeceras de seguridad estándar recomendadas para una API servida detrás de
terminación TLS (RF "API/WebChat/SPA sirven por TLS/WSS"):

- `Strict-Transport-Security` (HSTS): instruye al navegador a NUNCA volver a
  intentar HTTP plano con este host una vez ha visto HTTPS (fuerza HTTPS del
  lado cliente). Solo tiene sentido si la conexión YA llegó por TLS (lo hace
  el proxy/terminador TLS delante de la API, ver `docker-compose.yml` y
  `README.md` — la API en sí no termina TLS, es responsabilidad del
  reverse-proxy en despliegue on-prem, QUICKSILVER). Se añade siempre porque
  es inocua sobre HTTP plano en desarrollo (el navegador solo la respeta
  sobre una respuesta HTTPS) y evita "olvidarla" en producción.
- `X-Content-Type-Options: nosniff`: evita que el navegador reinterprete el
  `Content-Type` declarado (mitiga ataques de sniffing/XSS).
- `X-Frame-Options: DENY`: evita que la API se embeba en un `<iframe>` de
  otro origen (defensa en profundidad contra clickjacking; la API es JSON,
  no HTML, pero `/docs`/`/redoc` sí renderizan HTML).
- `Referrer-Policy: no-referrer`: evita filtrar la URL (que puede incluir
  tokens/ids de recursos) al navegar hacia fuera.
- `Content-Security-Policy`: restringe orígenes de recursos; para una API
  JSON + Swagger UI se usa una política conservadora (`default-src 'self'`)
  que no rompe `/docs`.
- `Permissions-Policy`: deshabilita APIs de navegador sensibles no usadas
  por esta API (cámara, micrófono, geolocalización).

CHECKPOINT: estas cabeceras son metadatos de seguridad, no contienen PII ni
secretos; no hay excepción de auditoría aplicable.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# HSTS: 180 días + subdominios. No se usa `preload` porque requiere registro
# manual en la lista de precarga de navegadores (fuera de alcance de esta
# SPEC; se documenta como posible endurecimiento futuro).
_HSTS_MAX_AGE_SECONDS = 15552000

_SECURITY_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": (
        f"max-age={_HSTS_MAX_AGE_SECONDS}; includeSubDomains"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'"
    ),
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Añade cabeceras de seguridad estándar a toda respuesta HTTP."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response
