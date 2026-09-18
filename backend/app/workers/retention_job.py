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

Usa la sesión "de plataforma" (`app.db.session.get_db`, sin `tenant_id` de
sesión fijado) porque recorre todos los tenants; cada fila procesada ya
lleva su propio `tenant_id` (no hay fuga cross-tenant: cada anonimización
solo toca la fila candidata, identificada por su propio id).
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
