"""
Registro de acceso a datos personales (auditoría HABEAS DATA) — SPEC-021.

RF: "Todo acceso a datos personales queda registrado (auditoría HABEAS
DATA)". Este módulo centraliza el registro estructurado (`structlog`, mismo
pipeline JSON que el resto del backend, ver `app/main.py`) de accesos a
entidades que contienen datos personales de contacto (actualmente:
`contacts`, y por extensión `conversations`/`messages` vinculados a un
contacto vía `contact_360`).

Qué se registra (metadatos de acceso, NUNCA el dato personal en sí):
  - Mensaje/evento del log: siempre `"personal_data_access"` (permite filtrar
    en el sistema de logs/SIEM sin parsear texto libre). Se pasa como
    argumento POSICIONAL a `structlog` (`logger.info("personal_data_access",
    ...)`), que internamente lo mapea a la clave `event` del registro JSON
    final — por eso el payload de este módulo NUNCA debe incluir también una
    clave `event` explícita (colisionaría: "got multiple values for
    argument 'event'"). Quien quiera filtrar por tipo de evento debe usar el
    campo `event` que ya emite `structlog` de forma automática.
  - `request_id`: correlación con la petición HTTP (ver
    `app/core/request_id.py`) para poder reconstruir "qué pidió quién" sin
    volcar el cuerpo de la petición/respuesta.
  - `tenant_id`, `user_id`, `user_email`: quién accede (email es identificador
    de cuenta del AGENTE, no del contacto/titular; no es el dato personal que
    se protege aquí, es la identidad de quien audita el acceso — práctica
    estándar de auditoría).
  - `resource`, `resource_id`: QUÉ se accedió (tabla + id), nunca el
    contenido (nombre, teléfono, email, mensajes) del contacto.
  - `action`: verbo de la operación (`read`, `list`, `export`, `erase`,
    `anonymize`, `create`, `update`, `delete_logical`).
  - `timestamp`: ISO-8601 (añadido automáticamente por el procesador
    `TimeStamper` de `structlog`, configurado en `app/main.py`).

CHECKPOINT (C3/BLACK WIDOW): esta función NUNCA debe recibir como argumento
un campo de dato personal crudo (nombre, teléfono, email de contacto,
contenido de mensaje) ni un secreto/token. Los tests
(`tests/test_audit_log.py`) verifican que el log resultante no contiene
dichos valores.
"""

from __future__ import annotations

import structlog

_audit_logger = structlog.get_logger("audit.personal_data")

# Acciones válidas — lista cerrada para evitar valores libres que puedan
# terminar filtrando datos por error (p.ej. pasar un mensaje como "action").
VALID_ACTIONS = frozenset(
    {
        "create",
        "read",
        "list",
        "update",
        "delete_logical",
        "export",
        "erase",
        "anonymize",
    }
)


def log_personal_data_access(
    *,
    action: str,
    resource: str,
    resource_id: str | None,
    tenant_id: str | None,
    user_id: str | None,
    user_email: str | None = None,
    request_id: str | None = None,
    extra: dict[str, str | int | bool] | None = None,
) -> None:
    """Registra un acceso a datos personales (auditoría HABEAS DATA).

    `extra` es para metadatos NO sensibles adicionales (p.ej. `count` en un
    `list`, o `channel` en un mensaje) — nunca debe incluirse aquí un campo
    de dato personal (se documenta en el docstring del módulo; la
    responsabilidad de no pasar PII es de quien llama).
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"Acción de auditoría no reconocida: {action!r}")

    # NOTA: NO incluir aquí una clave "event" — el primer argumento
    # posicional de `_audit_logger.info(...)` ya es el `event` del registro
    # structlog; duplicarlo como kwarg provoca
    # "got multiple values for argument 'event'" (bug corregido, ver docstring).
    payload: dict[str, str | int | bool | None] = {
        "action": action,
        "resource": resource,
        "resource_id": resource_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "user_email": user_email,
        "request_id": request_id,
    }
    if extra:
        payload.update(extra)

    _audit_logger.info("personal_data_access", **payload)
