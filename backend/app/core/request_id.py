"""
Correlación de peticiones por `request_id` — SPEC-021 (auditoría HABEAS DATA).

RF: "registro de acceso a datos personales... para auditoría"; para poder
reconstruir en los logs "qué pidió quién y cuándo" sin volcar el cuerpo de la
petición, cada request recibe un identificador único (UUID4) que:

  1. Se genera al entrar la petición (o se reutiliza `X-Request-ID` si el
     cliente/proxy ya lo trae, útil para trazas end-to-end con el reverse
     proxy TLS delante de la API).
  2. Se expone en la respuesta (`X-Request-ID`) para que el cliente pueda
     reportarlo en caso de incidencia.
  3. Se deja disponible para el resto del request vía `request.state.request_id`,
     que los endpoints/servicios de auditoría (`app/core/audit_log.py`) leen
     al registrar accesos a datos personales.

No contiene ni transporta datos personales; es un identificador opaco.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Asigna/propaga un `request_id` único por petición HTTP."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = (
            incoming.strip() if incoming and incoming.strip() else str(uuid.uuid4())
        )
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def get_request_id(request: Request) -> str | None:
    """Lee el `request_id` fijado por `RequestIDMiddleware` (None si no corrió)."""
    return getattr(request.state, "request_id", None)
