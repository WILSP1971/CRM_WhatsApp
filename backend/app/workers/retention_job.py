"""
CLI del job de retención/minimización de datos personales — SPEC-021.

A diferencia de `rag_ingest_worker`/`sentiment_worker` (procesos long-running
que consumen una cola Redis), la retención es un job de **mantenimiento
periódico** (naturaleza de cron, no de cola): se invoca puntualmente, corre
una pasada y termina. Se documenta aquí en `app/workers/` por consistencia de
ubicación con el resto de procesos batch del backend, pero su forma de
ejecución esperada es un cron/systemd-timer externo (QUICKSILVER, fuera de
alcance de código de esta SPEC) que invoque:

    DATABASE_URL=... python -m app.workers.retention_job

Variables de entorno relevantes (`app.core.config.Settings`):
  - `DATA_RETENTION_DAYS` (default 90): antigüedad de `updated_at` para que
    un contacto INACTIVO sea candidato a anonimización.
  - `ENABLE_DATA_ANONYMIZATION` (default `false`): si es `false`, el job
    corre en modo dry-run (solo reporta candidatos, no escribe nada) —
    permite auditar el impacto antes de habilitar la purga real en un
    entorno.

Abre la sesión con `app.db.session.SessionLocal` (rol de aplicación
`omnicore_app`, ADR-008), pero — CORRECCIÓN RLS, mismo hallazgo BLACK
PANTHER que SPEC-041 (ver `app.services.telefonia.call_retention_job`) — NO
opera con esa sesión "a secas": `run_retention_job` internamente recorre
cada tenant ACTIVO y fija `app.tenant_id` (`set_tenant_session`, `SET
LOCAL`) antes de tocar `contacts`, que tiene RLS ENABLE+FORCE
(ADR-004/ADR-008). Sin ese `SET LOCAL`, el rol `omnicore_app` (`NOSUPERUSER
NOBYPASSRLS`) ve CERO filas por diseño (fail-closed) y el job nunca
encontraría candidatos — este módulo (`retention_job.py`) NO necesita fijar
el tenant él mismo: delega esa responsabilidad por completo en
`run_retention_job` (`app.services.retention_service`), que es quien itera
tenant por tenant.
"""

from __future__ import annotations

import structlog

from app.db.session import SessionLocal
from app.services.retention_service import run_retention_job

logger = structlog.get_logger(__name__)


def main() -> None:
    db = SessionLocal()
    try:
        result = run_retention_job(db)
        logger.info(
            "retention_job_completed",
            dry_run=result.dry_run,
            retention_days=result.retention_days,
            candidates_found=result.candidates_found,
            anonymized_count=len(result.anonymized_contact_ids),
        )
        if result.dry_run:
            logger.warning(
                "retention_job_dry_run",
                detail=(
                    "ENABLE_DATA_ANONYMIZATION=false: no se escribió ningún "
                    "cambio. Configure la variable a 'true' para aplicar la "
                    "purga/anonimización real."
                ),
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
