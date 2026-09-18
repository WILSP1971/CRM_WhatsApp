"""
Retención y minimización de datos personales — SPEC-021 (HABEAS DATA/GDPR-like).

RF: "Retención configurable: los datos vencidos se purgan/anonimizan según
política." Este servicio implementa la consulta/job que:

  1. Busca contactos INACTIVOS (`activo=False`, ya dados de baja lógica por
     el agente o por el propio titular vía `app.services.privacy_service`)
     cuya `updated_at` supera `DATA_RETENTION_DAYS` (env, `Settings`,
     default 90) y que aún NO están anonimizados (`anonymized_at IS NULL`).
  2. Los anonimiza (mismo mecanismo que el derecho al olvido: sobrescribe
     campos identificantes, marca `anonymized_at`) — NUNCA DELETE físico
     (C2). Solo actúa sobre contactos ya inactivos: la retención jamás
     desactiva ni toca un contacto en uso (`activo=True`).
  3. Puede ejecutarse en modo "dry-run" (reporte, no escribe) si
     `ENABLE_DATA_ANONYMIZATION=false` (default) — permite auditar qué
     purgaría el job antes de habilitarlo en un entorno.

Este servicio opera FUERA del ciclo de request/response de un usuario (es un
job de mantenimiento, ver `app/workers/` para el patrón de worker del
proyecto); se ejecuta con una sesión "de plataforma" (sin `tenant_id` de
sesión fijado) porque recorre TODOS los tenants, cada fila ya lleva su propio
`tenant_id` y RLS no aplica a un rol de servicio de mantenimiento (mismo
patrón que `app/db/seed.py`). Queda documentado y auditado vía
`app.core.audit_log` (acción `anonymize`, sin volcar el dato anonimizado).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit_log import log_personal_data_access
from app.core.config import get_settings
from app.models.contact import Contact
from app.services.privacy_service import erase_contact_personal_data


@dataclass(frozen=True)
class RetentionRunResult:
    """Resultado de una corrida del job de retención."""

    dry_run: bool
    retention_days: int
    candidates_found: int
    anonymized_contact_ids: list[str] = field(default_factory=list)


def _cutoff(retention_days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=retention_days)


def find_retention_candidates(
    db: Session, *, retention_days: int | None = None
) -> list[Contact]:
    """Contactos inactivos, no anonimizados, vencidos según la política."""
    settings = get_settings()
    days = (
        retention_days if retention_days is not None else settings.data_retention_days
    )
    cutoff = _cutoff(days)

    return list(
        db.scalars(
            select(Contact).where(
                Contact.activo.is_(False),
                Contact.anonymized_at.is_(None),
                Contact.updated_at < cutoff,
            )
        ).all()
    )


def run_retention_job(
    db: Session,
    *,
    retention_days: int | None = None,
    enabled: bool | None = None,
) -> RetentionRunResult:
    """Ejecuta la política de retención (anonimización de contactos vencidos).

    - `retention_days`/`enabled` sobrescriben `Settings` si se pasan
      explícitamente (útil para tests y para invocación manual con
      parámetros distintos a los de entorno).
    - En modo dry-run (`enabled=False`, default de `ENABLE_DATA_ANONYMIZATION`)
      NO escribe nada: solo reporta cuántos candidatos encontró, para poder
      auditar el impacto antes de habilitar la purga real.
    """
    settings = get_settings()
    days = (
        retention_days if retention_days is not None else settings.data_retention_days
    )
    is_enabled = enabled if enabled is not None else settings.enable_data_anonymization

    candidates = find_retention_candidates(db, retention_days=days)

    anonymized_ids: list[str] = []
    if is_enabled:
        for contact in candidates:
            tenant_id = str(contact.tenant_id)
            contact_id = str(contact.id)
            erase_contact_personal_data(db, contact.id)
            anonymized_ids.append(contact_id)
            log_personal_data_access(
                action="anonymize",
                resource="contacts",
                resource_id=contact_id,
                tenant_id=tenant_id,
                user_id=None,
                user_email=None,
                request_id=None,
                extra={"trigger": "retention_job"},
            )
        db.commit()

    return RetentionRunResult(
        dry_run=not is_enabled,
        retention_days=days,
        candidates_found=len(candidates),
        anonymized_contact_ids=anonymized_ids,
    )
