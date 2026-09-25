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
proyecto).

CORRECCIÓN RLS (mismo hallazgo BLACK PANTHER que SPEC-041, ver
`app.services.telefonia.call_retention_service`): a diferencia de lo que
decía una versión anterior de este docstring, este servicio **NO** puede
operar con una sesión "de plataforma" sin `tenant_id` fijado. `contacts` está
en `TENANT_SCOPED_TABLES` (`app/db/rls.py`) con RLS ENABLE+FORCE
(ADR-004/ADR-008); el rol de aplicación `omnicore_app` es `NOSUPERUSER
NOBYPASSRLS`, así que una sesión sin `app.tenant_id` fijado ve CERO filas por
diseño (fail-closed, ver
`tests/test_rls_isolation.py::test_session_without_tenant_sees_zero_rows`) —
con el bug anterior, `find_retention_candidates` SIEMPRE devolvía una lista
vacía en producción real y el job nunca anonimizaba nada (violaba el RF en
silencio).

Corrección aplicada: `run_retention_job` ahora recorre los tenants ACTIVOS
uno por uno (`tenants` no lleva `tenant_id` propio — es la entidad raíz, no
está en `TENANT_SCOPED_TABLES`, así que listarla no requiere RLS) y, para
cada tenant, fija `app.tenant_id` con `set_tenant_session()` (`SET LOCAL`, se
descarta solo al hacer COMMIT/ROLLBACK) ANTES de buscar/anonimizar los
candidatos de ESE tenant — mismo patrón que
`app.services.telefonia.call_retention_service.run_call_retention_job`
(SPEC-041) y que `app/workers/whatsapp_inbound_worker.py`/`stt_worker.py`.
Cada anonimización individual corre en su propia transacción (`with
db.begin(): ...`), con COMMIT inmediato tras esa fila (no al final del
batch), para acotar a una sola fila la ventana de inconsistencia ante una
caída del proceso a mitad de una corrida — idempotente en cualquier caso
(`anonymized_at` ya seteado evita reprocesar la fila en la siguiente corrida).

Queda documentado y auditado vía `app.core.audit_log` (acción `anonymize`,
sin volcar el dato anonimizado).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit_log import log_personal_data_access
from app.core.config import get_settings
from app.db.session import set_tenant_session
from app.models.contact import Contact
from app.models.tenant import Tenant
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


def _active_tenant_ids(db: Session) -> list[str]:
    """Lista los ids de tenants ACTIVOS (`tenants.activo = True`).

    `tenants` NO está en `TENANT_SCOPED_TABLES` (`app/db/rls.py`) — es la
    entidad raíz del aislamiento multi-tenant, no lleva `tenant_id` propio y
    por lo tanto no tiene RLS habilitado. Listarla no requiere
    `set_tenant_session()` (mismo criterio que `two_tenants_with_data` en
    `tests/conftest.py`, que puebla `tenants` sin fijar `app.tenant_id`;
    mismo patrón que `app.services.telefonia.call_retention_service`)."""
    return [
        str(tenant_id)
        for tenant_id in db.scalars(
            select(Tenant.id).where(Tenant.activo.is_(True))
        ).all()
    ]


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

    CORRECCIÓN RLS (mismo hallazgo BLACK PANTHER que SPEC-041 — ver
    docstring del módulo): `contacts` tiene RLS ENABLE+FORCE, así que la
    consulta de candidatos DEBE correr con `app.tenant_id` fijado para ese
    tenant. Se recorre cada tenant ACTIVO (`_active_tenant_ids`) y, dentro de
    cada iteración, se fija `set_tenant_session(db, tenant_id)` DENTRO de una
    transacción explícita (`with db.begin(): ...`, `SET LOCAL` vigente hasta
    el COMMIT/ROLLBACK de ESA transacción) ANTES de buscar/anonimizar los
    candidatos de ESE tenant.

    Transaccionalidad: cada anonimización INDIVIDUAL corre en su PROPIA
    transacción, que se cierra (COMMIT) INMEDIATAMENTE después de esa fila —
    no al final del batch. Así, si el proceso muere a mitad de una corrida,
    la ventana de inconsistencia queda acotada a UNA sola fila en vuelo,
    nunca a un batch completo. Autosanable en cualquier caso: la siguiente
    corrida vuelve a intentar esa fila justo donde quedó (idempotencia,
    `anonymized_at`).
    """
    settings = get_settings()
    days = (
        retention_days if retention_days is not None else settings.data_retention_days
    )
    is_enabled = enabled if enabled is not None else settings.enable_data_anonymization

    anonymized_ids: list[str] = []
    candidates_found = 0

    for tenant_id in _active_tenant_ids(db):
        with db.begin():
            set_tenant_session(db, tenant_id)
            candidates = find_retention_candidates(db, retention_days=days)
        candidates_found += len(candidates)

        if not is_enabled:
            # Dry-run: ni siquiera se abre una transacción de escritura para
            # este tenant, solo se cuentan los candidatos encontrados.
            continue

        for contact in candidates:
            contact_id = str(contact.id)
            with db.begin():
                set_tenant_session(db, tenant_id)
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

    return RetentionRunResult(
        dry_run=not is_enabled,
        retention_days=days,
        candidates_found=candidates_found,
        anonymized_contact_ids=anonymized_ids,
    )
