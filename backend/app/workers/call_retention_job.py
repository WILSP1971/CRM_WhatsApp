"""
CLI del job de retención/anonimización de audio y transcripción de llamadas
— SPEC-041 (extiende SPEC-021).

Mismo criterio que `app.workers.retention_job` (SPEC-021): la retención es un
job de **mantenimiento periódico** (naturaleza de cron, no de cola
Redis/long-running como `stt_worker`/`sentiment_worker`) — se invoca
puntualmente, corre una pasada y termina. Se documenta en `app/workers/` por
consistencia de ubicación con el resto de procesos batch del backend; su
forma de ejecución esperada es un cron/systemd-timer externo (QUICKSILVER,
fuera de alcance de código de esta SPEC) que invoque, DENTRO de un
contenedor que monte el volumen `audio_store` (p.ej. `recording_ingest_worker`
o `stt_worker` en `docker-compose.yml` — NO `api`, que no lo monta):

    docker compose exec recording_ingest_worker \
        python -m app.workers.call_retention_job

(equivalente a `DATABASE_URL=... python -m app.workers.call_retention_job`
fuera de Docker, siempre que el proceso tenga acceso de lectura/escritura al
mismo `AUDIO_STORAGE_PATH` que usó `recording_ingest_worker`/`stt_worker`
para escribir el audio).

Variables de entorno relevantes (`app.core.config.Settings`):
  - `AUDIO_RETENTION_DAYS` (default 30): antigüedad de `Call.created_at` para
    que una llamada con audio vigente sea candidata a purga física del blob.
  - `CALL_TRANSCRIPT_RETENTION_DAYS` (default 90): antigüedad de
    `CallTranscript.created_at` para que una transcripción vigente sea
    candidata a anonimización.
  - `AUDIO_RETENTION_ACTION` (default "purge"): acción sobre el audio al
    vencer.
  - `CALL_TRANSCRIPT_RETENTION_ACTION` (default "anonymize"): acción sobre la
    transcripción al vencer.
  - `ENABLE_CALL_RETENTION_PURGE` (default `false`): si es `false`, el job
    corre en modo dry-run (solo reporta candidatos, no escribe/purga nada) —
    permite auditar el impacto antes de habilitar la purga real en un
    entorno.

Abre la sesión con `app.db.session.SessionLocal` (rol de aplicación
`omnicore_app`, ADR-008), pero — CORRECCIÓN RLS, hallazgo BLACK PANTHER — NO
opera con esa sesión "a secas": `run_call_retention_job` internamente
recorre cada tenant ACTIVO y fija `app.tenant_id` (`set_tenant_session`,
`SET LOCAL`) antes de tocar `calls`/`call_transcripts`, que tienen RLS
ENABLE+FORCE (ADR-004/ADR-008). Sin ese `SET LOCAL`, el rol `omnicore_app`
(`NOSUPERUSER NOBYPASSRLS`) ve CERO filas por diseño (fail-closed) y el job
nunca encontraría candidatos — este módulo (`call_retention_job.py`) NO
necesita fijar el tenant él mismo: delega esa responsabilidad por completo
en `run_call_retention_job` (`app.services.telefonia.call_retention_service`),
que es quien itera tenant por tenant.

NOTA: `app.workers.retention_job` (SPEC-021, contactos) comparte este mismo
patrón de corrección — `run_retention_job`
(`app.services.retention_service`) también recorre cada tenant ACTIVO y fija
`app.tenant_id` por cada uno antes de tocar `contacts` (RLS ENABLE+FORCE).
"""

from __future__ import annotations

import structlog

from app.db.session import SessionLocal
from app.services.telefonia.call_retention_service import run_call_retention_job

logger = structlog.get_logger(__name__)


def main() -> None:
    db = SessionLocal()
    try:
        result = run_call_retention_job(db)
        logger.info(
            "call_retention_job_completed",
            dry_run=result.dry_run,
            audio_retention_days=result.audio_retention_days,
            transcript_retention_days=result.transcript_retention_days,
            audio_candidates_found=result.audio_candidates_found,
            transcript_candidates_found=result.transcript_candidates_found,
            purged_audio_count=len(result.purged_audio_call_ids),
            anonymized_transcript_count=len(result.anonymized_transcript_ids),
        )
        if result.dry_run:
            logger.warning(
                "call_retention_job_dry_run",
                detail=(
                    "ENABLE_CALL_RETENTION_PURGE=false: no se purgó/anonimizó "
                    "ningún audio/transcripción. Configure la variable a "
                    "'true' para aplicar la purga real."
                ),
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
