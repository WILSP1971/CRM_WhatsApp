"""
Retención/anonimización de audio y transcripción de llamadas — SPEC-041
(extiende SPEC-021, HABEAS DATA/GDPR-like; ADR-009).

Servicio de mantenimiento que corre FUERA del ciclo de request/response,
recorre TODOS los tenants ACTIVOS y puede ejecutarse en modo "dry-run" antes
de habilitar la purga real (`ENABLE_CALL_RETENTION_PURGE`, `Settings`).

IMPORTANTE (corrección RLS, ver más abajo): a diferencia de
`app.services.retention_service` (SPEC-021, contactos, que sigue usando una
sesión "de plataforma" sin `tenant_id` fijado), este servicio SÍ fija
`app.tenant_id` por cada tenant antes de consultar/escribir `calls`/
`call_transcripts`, porque esas tablas tienen RLS ENABLE+FORCE (a diferencia
de una lectura ingenua, sin RLS fijado el rol de aplicación no ve ninguna
fila — ver docstring extendido más abajo).

Umbral de retención — decisión de diseño (global, no por tenant): la SPEC-041
deja abierto "cada tenant con su propio umbral, o un umbral global" y pide
decidir y documentar. Se decide GLOBAL (una sola `AUDIO_RETENTION_DAYS`/
`CALL_TRANSCRIPT_RETENTION_DAYS` por despliegue), igual que
`DATA_RETENTION_DAYS` de SPEC-021 (que ya es global, sin columna por-tenant en
`tenants`) — coherente con el resto de la política de retención del proyecto,
sin introducir un modelo de configuración por tenant que ningún otro
mecanismo de esta base de código tiene todavía. Si en el futuro un tenant
necesita un umbral distinto (p.ej. cliente de salud con retención más
estricta), es una ampliación de schema (`tenants.audio_retention_days`) fuera
de este alcance — el propio `run_call_retention_job` acepta overrides
explícitos de días por si se quiere invocar el job por tenant con distintos
parámetros sin cambiar el modelo de datos.

Orden de operaciones por llamada candidata (C2 SIEMPRE primero):
  1. Si `Call.activo` es `True`, se pasa a `False` (borrado lógico, C2) ANTES
     de tocar el audio/transcripción — nunca se purga/anonimiza contenido de
     una llamada que la aplicación aún considera "activa" sin antes darla de
     baja lógicamente.
  2. Si hay `audio_ref` y la retención de AUDIO venció: se purga FÍSICAMENTE
     el blob (`app.services.telefonia.audio_store.purge_audio`), se limpia
     `Call.audio_ref` y se marca `Call.audio_purged_at` (idempotencia: una
     llamada con `audio_purged_at` ya seteado NUNCA vuelve a ser candidata).
  3. Si hay `CallTranscript` activa y la retención de TRANSCRIPCIÓN venció:
     se anonimiza `segmentos` (sobrescrito por un marcador no identificante,
     mismo criterio que `erase_contact_personal_data`) y se marca
     `anonymized_at` (idempotencia: una transcripción con `anonymized_at` ya
     seteado nunca se vuelve a procesar). Si la acción configurada es
     `"purge"` en vez de `"anonymize"`, además se aplica borrado lógico
     explícito de la transcripción (`activo=False`) — el contenido igual se
     sobrescribe (SPEC-041 no define una forma de "purga total" de un JSONB
     distinta de vaciar su contenido identificante).

Cada purga/anonimización queda registrada vía `app.core.audit_log` (acción
`"purge"` para el audio, `"anonymize"` para la transcripción) — el propio job
de mantenimiento es un "acceso" a datos personales tanto como un endpoint de
lectura (RF-03 SPEC-041: "cada acceso a audio/transcripción queda
registrado"), así que se audita igual que `app/api/calls.py` (SPEC-040).

CORRECCIÓN RLS (hallazgo BLACK PANTHER, bloqueante): a diferencia de lo que
decía una versión anterior de este docstring, este servicio **NO** puede
operar con una sesión "de plataforma" sin `tenant_id` fijado. `calls` y
`call_transcripts` están en `TENANT_SCOPED_TABLES` (`app/db/rls.py`) con RLS
ENABLE+FORCE (ADR-004/ADR-008); el rol de aplicación `omnicore_app` es
`NOSUPERUSER NOBYPASSRLS`, así que una sesión sin `app.tenant_id` fijado ve
CERO filas por diseño (fail-closed, ver
`tests/test_rls_isolation.py::test_session_without_tenant_sees_zero_rows`) —
con el bug anterior, `find_audio_retention_candidates`/
`find_transcript_retention_candidates` SIEMPRE devolvían listas vacías en
producción real y el job nunca purgaba nada (violaba RF-02 en silencio).

Corrección aplicada: `run_call_retention_job` ahora recorre los tenants
ACTIVOS uno por uno (`tenants` no lleva `tenant_id` propio — es la entidad
raíz, no está en `TENANT_SCOPED_TABLES`, así que listarla no requiere RLS) y,
para cada tenant, fija `app.tenant_id` con `set_tenant_session()` (`SET
LOCAL`, se descarta solo al hacer COMMIT/ROLLBACK) ANTES de buscar/purgar los
candidatos de AUDIO y TRANSCRIPCIÓN de ESE tenant — mismo patrón que
`app/workers/whatsapp_inbound_worker.py`/`stt_worker.py`/`wa_send_worker.py`.

CORRECCIÓN GEMELA APLICADA: `app/services/retention_service.py` /
`app/workers/retention_job.py` (SPEC-021, contactos) compartían EXACTAMENTE
el mismo defecto — abrían `SessionLocal()` sin `set_tenant_session()` y por
lo tanto tampoco purgaban nada en producción real. Se corrigieron con el
mismo patrón descrito arriba (recorrido de tenants activos, `set_tenant_
session()` por tenant, commit por fila) inmediatamente después de detectarse
este hallazgo en la revisión de SPEC-041.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit_log import log_personal_data_access
from app.core.config import get_settings
from app.db.session import set_tenant_session
from app.models.call import Call
from app.models.call_transcript import CallTranscript
from app.models.tenant import Tenant
from app.services.telefonia.audio_store import AudioStoreError, purge_audio

# Marcador no identificante usado al anonimizar la transcripción (no es un
# dato personal real, es una constante de dominio, mismo criterio que
# `_ANONYMIZED_NAME` de `app.services.privacy_service`).
_ANONYMIZED_SEGMENTOS = [
    {
        "inicio": 0,
        "fin": 0,
        "texto": "[Transcripción anonimizada por política de retención]",
        "hablante": "sistema",
    }
]


@dataclass(frozen=True)
class CallRetentionRunResult:
    """Resultado de una corrida del job de retención de audio/transcripción."""

    dry_run: bool
    audio_retention_days: int
    transcript_retention_days: int
    audio_candidates_found: int
    transcript_candidates_found: int
    purged_audio_call_ids: list[str] = field(default_factory=list)
    anonymized_transcript_ids: list[str] = field(default_factory=list)


def _cutoff(retention_days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=retention_days)


def find_audio_retention_candidates(
    db: Session, *, retention_days: int | None = None
) -> list[Call]:
    """Llamadas con audio vigente (`audio_ref` no nulo, aún no purgado) cuyo
    `created_at` supera la ventana de retención de AUDIO."""
    settings = get_settings()
    days = (
        retention_days if retention_days is not None else settings.audio_retention_days
    )
    cutoff = _cutoff(days)

    return list(
        db.scalars(
            select(Call).where(
                Call.audio_ref.is_not(None),
                Call.audio_purged_at.is_(None),
                Call.created_at < cutoff,
            )
        ).all()
    )


def find_transcript_retention_candidates(
    db: Session, *, retention_days: int | None = None
) -> list[CallTranscript]:
    """Transcripciones vigentes (no anonimizadas) cuyo `created_at` supera la
    ventana de retención de TRANSCRIPCIÓN."""
    settings = get_settings()
    days = (
        retention_days
        if retention_days is not None
        else settings.call_transcript_retention_days
    )
    cutoff = _cutoff(days)

    return list(
        db.scalars(
            select(CallTranscript).where(
                CallTranscript.anonymized_at.is_(None),
                CallTranscript.created_at < cutoff,
            )
        ).all()
    )


def _ensure_soft_deleted(call: Call) -> None:
    """Borrado lógico (C2) SIEMPRE antes de purgar/anonimizar contenido."""
    if call.activo:
        call.activo = False


def _purge_call_audio(db: Session, call: Call) -> bool:
    """Purga físicamente el blob de audio de una llamada candidata y
    actualiza la fila. Idempotente: si `audio_ref` ya es `None` o
    `audio_purged_at` ya está seteado, no hace nada (no debería llegar aquí
    por el filtro de `find_audio_retention_candidates`, pero se revalida por
    seguridad defensiva).

    NOTA (`AUDIO_RETENTION_ACTION`, hallazgo BLACK PANTHER): esta función
    SIEMPRE purga físicamente el blob de audio, sin importar el valor
    configurado en `settings.audio_retention_action` ("purge"/"anonymize") —
    esa variable HOY es un NO-OP para el audio: no existe una rama de código
    que trate "anonymize" distinto de "purge" aquí. Si en el futuro se
    implementa una anonimización real del audio (p.ej. sobrescribir el blob
    con silencio/ruido en vez de borrarlo, o conservar el blob y solo marcar
    metadatos), esa lógica debe añadirse explícitamente en esta función; no
    asumir que configurar `AUDIO_RETENTION_ACTION=anonymize` ya tiene efecto
    — ver también el comentario extendido en `app/core/config.py` junto a
    `audio_retention_action`.
    """
    if call.audio_ref is None or call.audio_purged_at is not None:
        return False

    _ensure_soft_deleted(call)

    audio_ref = call.audio_ref
    try:
        purge_audio(audio_ref=audio_ref)
    except AudioStoreError:
        # `purge_audio()` NO lanza `AudioStoreError` cuando el blob ya no
        # existe (ese caso se modela como retorno `False`, no como
        # excepción) — así que este `except` NO cubre "el archivo ya fue
        # purgado por una corrida anterior" (corrección del comentario
        # anterior, que afirmaba lo contrario y podía inducir a un
        # mantenedor a pensar que este bloque absorbe reintentos de forma
        # segura). Lo que SÍ llega aquí es un fallo de E/S genuino (permiso
        # denegado, disco solo-lectura, ruta fuera del árbol esperado,
        # etc.). Se marca la fila como purgada de todas formas (mismo
        # criterio que el resto de la función: nunca dejar `audio_ref`
        # apuntando a un blob en estado indeterminado) y se RELANZA la
        # excepción sin silenciarla, para que la corrida falle visiblemente
        # y el operador investigue la causa de E/S real.
        call.audio_ref = None
        call.audio_purged_at = datetime.now(timezone.utc)
        raise

    call.audio_ref = None
    call.audio_purged_at = datetime.now(timezone.utc)
    return True


def _anonymize_call_transcript(db: Session, transcript: CallTranscript) -> bool:
    """Anonimiza el contenido de una transcripción candidata. Idempotente:
    si `anonymized_at` ya está seteado, no hace nada."""
    if transcript.anonymized_at is not None:
        return False

    settings = get_settings()
    transcript.segmentos = _ANONYMIZED_SEGMENTOS
    transcript.anonymized_at = datetime.now(timezone.utc)
    if settings.call_transcript_retention_action == "purge":
        transcript.activo = False
    return True


def _active_tenant_ids(db: Session) -> list[str]:
    """Lista los ids de tenants ACTIVOS (`tenants.activo = True`).

    `tenants` NO está en `TENANT_SCOPED_TABLES` (`app/db/rls.py`) — es la
    entidad raíz del aislamiento multi-tenant, no lleva `tenant_id` propio y
    por lo tanto no tiene RLS habilitado. Listarla no requiere
    `set_tenant_session()` (mismo criterio que `two_tenants_with_data` en
    `tests/conftest.py`, que puebla `tenants` sin fijar `app.tenant_id`)."""
    return [
        str(tenant_id)
        for tenant_id in db.scalars(
            select(Tenant.id).where(Tenant.activo.is_(True))
        ).all()
    ]


def run_call_retention_job(
    db: Session,
    *,
    audio_retention_days: int | None = None,
    transcript_retention_days: int | None = None,
    enabled: bool | None = None,
) -> CallRetentionRunResult:
    """Ejecuta la política de retención de audio/transcripción de llamadas.

    - `audio_retention_days`/`transcript_retention_days`/`enabled` sobrescriben
      `Settings` si se pasan explícitamente (tests, o invocación manual con
      un umbral distinto al de entorno — p.ej. para aplicar un umbral
      distinto a un tenant específico, ver docstring del módulo).
    - En modo dry-run (`enabled=False`, default de
      `ENABLE_CALL_RETENTION_PURGE`) NO escribe nada: solo reporta cuántos
      candidatos encontró, para auditar el impacto antes de habilitar la
      purga real.
    - Idempotente: ejecutarlo dos veces seguidas en modo habilitado no
      duplica trabajo ni falla — la segunda corrida encuentra 0 candidatos
      porque `audio_purged_at`/`anonymized_at` ya quedaron marcados.

    CORRECCIÓN RLS (hallazgo BLACK PANTHER, bloqueante — ver docstring del
    módulo): `calls`/`call_transcripts` tienen RLS ENABLE+FORCE, así que las
    consultas de candidatos DEBEN correr con `app.tenant_id` fijado para ese
    tenant. Se recorre cada tenant ACTIVO (`_active_tenant_ids`) y, dentro de
    cada iteración, se fija `set_tenant_session(db, tenant_id)` DENTRO de una
    transacción explícita (`with db.begin(): ...`, `SET LOCAL` vigente hasta
    el COMMIT/ROLLBACK de ESA transacción) ANTES de buscar/purgar los
    candidatos de AUDIO y TRANSCRIPCIÓN de ESE tenant — mismo patrón que
    `whatsapp_inbound_worker.py`/`stt_worker.py`/`sentiment_worker.py`.

    Transaccionalidad (hallazgo BLACK WIDOW/WOLVERINE/BLACK PANTHER): cada
    purga/anonimización INDIVIDUAL corre en su PROPIA transacción (`with
    db.begin(): set_tenant_session(...); _purge_call_audio(...)`), que se
    cierra (COMMIT) INMEDIATAMENTE después de esa fila — no al final del
    batch. Así, si el proceso muere a mitad de una corrida, la ventana de
    inconsistencia (blob físico ya borrado pero fila de BD sin actualizar)
    queda acotada a UNA sola fila en vuelo, nunca a un batch completo.
    Autosanable en cualquier caso: la siguiente corrida vuelve a intentar esa
    fila justo donde quedó (idempotencia, `audio_purged_at`/`anonymized_at`).
    """
    settings = get_settings()
    audio_days = (
        audio_retention_days
        if audio_retention_days is not None
        else settings.audio_retention_days
    )
    transcript_days = (
        transcript_retention_days
        if transcript_retention_days is not None
        else settings.call_transcript_retention_days
    )
    is_enabled = enabled if enabled is not None else settings.enable_call_retention_purge

    purged_audio_ids: list[str] = []
    anonymized_transcript_ids: list[str] = []
    audio_candidates_found = 0
    transcript_candidates_found = 0

    # Ver `app.services.retention_service.run_retention_job` (mismo defecto,
    # mismo fix): `_active_tenant_ids(db)` deja una transacción implícita
    # (autobegin) abierta; sin cerrarla, el primer `with db.begin():` del
    # bucle falla con `InvalidRequestError` contra Postgres real.
    tenant_ids = _active_tenant_ids(db)
    db.rollback()

    for tenant_id in tenant_ids:
        with db.begin():
            set_tenant_session(db, tenant_id)
            audio_candidates = find_audio_retention_candidates(
                db, retention_days=audio_days
            )
            transcript_candidates = find_transcript_retention_candidates(
                db, retention_days=transcript_days
            )
            # Los ids se extraen AQUÍ DENTRO, mientras la transacción sigue
            # abierta (mismo hallazgo que `app.services.retention_service`):
            # al salir de este `with`, el COMMIT expira (`expire_on_commit=
            # True` por defecto) las instancias de `Call`/`CallTranscript`
            # cargadas arriba. Iterar sobre esos objetos DESPUÉS y acceder a
            # sus atributos (incluido `.id`) dispara un refresh implícito ya
            # sin `app.tenant_id` fijado (se descartó al cerrar la
            # transacción), y RLS lo interpreta como "la fila ya no existe"
            # (`sqlalchemy.orm.exc.ObjectDeletedError`/`DetachedInstanceError`,
            # confirmado contra Postgres real). Se trabaja solo con ids
            # (valores planos) fuera de esta transacción, y cada fila se
            # vuelve a leer con `db.get(...)` DENTRO de su propia transacción
            # (con el tenant ya fijado), en vez de reutilizar/mergear el
            # objeto expirado.
            audio_candidate_ids = [c.id for c in audio_candidates]
            transcript_candidate_ids = [t.id for t in transcript_candidates]
        audio_candidates_found += len(audio_candidate_ids)
        transcript_candidates_found += len(transcript_candidate_ids)

        if not is_enabled:
            # Dry-run: ni siquiera se abre una transacción de escritura para
            # este tenant, solo se cuentan los candidatos encontrados.
            continue

        for call_id in audio_candidate_ids:
            call_id_str = str(call_id)
            with db.begin():
                set_tenant_session(db, tenant_id)
                call = db.get(Call, call_id)
                _purge_call_audio(db, call)
            purged_audio_ids.append(call_id_str)
            log_personal_data_access(
                action="purge",
                resource="calls_audio",
                resource_id=call_id_str,
                tenant_id=tenant_id,
                user_id=None,
                user_email=None,
                request_id=None,
                extra={"trigger": "call_retention_job"},
            )

        for transcript_id in transcript_candidate_ids:
            transcript_id_str = str(transcript_id)
            with db.begin():
                set_tenant_session(db, tenant_id)
                transcript = db.get(CallTranscript, transcript_id)
                _anonymize_call_transcript(db, transcript)
            anonymized_transcript_ids.append(transcript_id_str)
            log_personal_data_access(
                action="anonymize",
                resource="call_transcripts",
                resource_id=transcript_id_str,
                tenant_id=tenant_id,
                user_id=None,
                user_email=None,
                request_id=None,
                extra={"trigger": "call_retention_job"},
            )

    return CallRetentionRunResult(
        dry_run=not is_enabled,
        audio_retention_days=audio_days,
        transcript_retention_days=transcript_days,
        audio_candidates_found=audio_candidates_found,
        transcript_candidates_found=transcript_candidates_found,
        purged_audio_call_ids=purged_audio_ids,
        anonymized_transcript_ids=anonymized_transcript_ids,
    )
