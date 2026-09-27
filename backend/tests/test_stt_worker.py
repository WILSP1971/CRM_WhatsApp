"""Tests de `app.workers.stt_worker` — SPEC-038, ADR-007/009.

Requiere PostgreSQL real (`tests/conftest.py::postgres_engine`, con
`alembic upgrade head` ya aplicado); se SKIPEA automáticamente sin Postgres
accesible (mismo patrón que `tests/test_recording_ingest_worker.py`).

`faster-whisper`/`WhisperModel` se MOCKEA en la capa
`app.services.telefonia.stt_engine.load_model` (o directamente
`transcribe_audio_bytes`, según el test): este entorno de CI no tiene GPU ni
los pesos reales del modelo descargados/montados — verificar la LÓGICA del
worker (parseo de segmentos, idempotencia, persistencia, fallback CPU,
instrumentación de métricas) con mocks es exactamente lo que SPEC-038 espera;
la calidad real del modelo (WER, RTF real bajo carga) se mide en SPEC-042 con
infraestructura real (GPU + pesos reales).

Cubre los criterios de aceptación de SPEC-038:
  (a) transcripción produce segmentos + timestamps persistidos en
      `call_transcript` (mock del motor STT).
  (b) diarización básica (VAD/heurística) etiqueta agente/cliente cuando se
      activa, y NO lo hace (hablante=None) cuando se desactiva.
  (c) IDEMPOTENCIA: reprocesar el mismo `call_id` no duplica la
      transcripción (ni por guarda previa, ni por `IntegrityError` de la
      restricción UNIQUE de BD ante condición de carrera).
  (d) el `stt_worker` NO importa el cliente de descarga externo de telefonía
      (verificado también por `check-externos-backend.sh`, aquí por
      inspección de imports del módulo).
  (e) el RTF/latencia de cola/tasa de error se instrumentan (métricas
      Prometheus incrementadas/observadas).
  (f) fallback CPU/`medium`: `stt_engine.load_model` cae a fallback si la
      carga del modelo primario falla, y el resultado documenta
      `fallback_aplicado=True`.
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.stt_queue import SttTranscriptionJob
from app.services.telefonia import stt_engine
from app.services.telefonia.audio_store import build_audio_ref, store_audio
from app.workers.stt_worker import drain_one, process_job


def _crear_tenant(engine, nombre: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO tenants (id, nombre, slug) VALUES (:id, :nombre, :slug)"),
            {
                "id": tenant_id,
                "nombre": nombre,
                "slug": f"{nombre.lower()}-{tenant_id.hex[:8]}",
            },
        )
    return tenant_id


def _crear_call(
    engine, *, tenant_id: uuid.UUID, call_id: str, audio_ref: str, estado: str = "finalizada"
) -> uuid.UUID:
    row_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO calls (id, tenant_id, call_id, numero, direccion, "
                "duracion, estado, audio_ref) VALUES (:id, :tenant_id, :call_id, "
                ":numero, :direccion, :duracion, :estado, :audio_ref)"
            ),
            {
                "id": row_id,
                "tenant_id": tenant_id,
                "call_id": call_id,
                "numero": "3001234567",
                "direccion": "entrante",
                "duracion": 30,
                "estado": estado,
                "audio_ref": audio_ref,
            },
        )
    return row_id


def _session_factory(postgres_engine):
    def _factory() -> Session:
        return Session(postgres_engine)

    return _factory


@pytest.fixture
def audio_store_tmp(tmp_path):
    """Redirige `AUDIO_STORAGE_PATH` (settings cacheadas, singleton) a un
    directorio temporal del test — evita depender de `/audio_store` real."""
    settings = get_settings()
    original = settings.audio_storage_path
    settings.audio_storage_path = str(tmp_path)
    yield tmp_path
    settings.audio_storage_path = original


@pytest.fixture
def stt_settings_defaults():
    """Restaura los flags de diarización/VAD tras cada test (algunos tests
    los mutan explícitamente)."""
    settings = get_settings()
    original_diar = settings.stt_diarization_enabled
    original_vad = settings.stt_vad_filter_enabled
    yield settings
    settings.stt_diarization_enabled = original_diar
    settings.stt_vad_filter_enabled = original_vad


def _fake_segment(start: float, end: float, text: str) -> MagicMock:
    seg = MagicMock()
    seg.start = start
    seg.end = end
    seg.text = text
    return seg


def _fake_transcription_info(*, language: str = "es", duration: float = 12.0) -> MagicMock:
    info = MagicMock()
    info.language = language
    info.duration = duration
    return info


def _mock_whisper_model(segments, info, *, transcribe_side_effect=None):
    """Construye un mock de `WhisperModel` cuyo `.transcribe()` devuelve
    `(segments, info)` (mismo shape que la librería real, ver
    `faster_whisper.transcribe.WhisperModel.transcribe`)."""
    model = MagicMock()
    if transcribe_side_effect is not None:
        model.transcribe.side_effect = transcribe_side_effect
    else:
        model.transcribe.return_value = (segments, info)
    return model


@pytest.fixture(autouse=True)
def _reset_stt_engine_cache():
    """El modelo STT se cachea en el módulo (`_modelo_cacheado`) para no
    recargarlo en cada job — se resetea entre tests para que el mock de un
    test no contamine al siguiente."""
    stt_engine._modelo_cacheado = None
    yield
    stt_engine._modelo_cacheado = None


# ---------------------------------------------------------------------------
# (a) transcripción produce segmentos + timestamps persistidos
# ---------------------------------------------------------------------------


def test_process_job_persists_segments_and_updates_call_estado(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    tenant_id = _crear_tenant(postgres_engine, "TenantSttHappy")
    call_id = f"call-stt-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-en-claro-de-prueba-stt")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    segments = [
        _fake_segment(0.0, 2.5, "Hola, buenas tardes."),
        _fake_segment(2.5, 5.0, "Quisiera consultar mi cita."),
    ]
    info = _fake_transcription_info(language="es", duration=5.0)
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id))

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT segmentos, idioma, modelo_stt FROM call_transcripts "
                "WHERE call_id = :call_id"
            ),
            {"call_id": call_row_id},
        ).fetchone()
        call_row = conn.execute(
            sa.text("SELECT estado FROM calls WHERE id = :id"), {"id": call_row_id}
        ).fetchone()

    assert row is not None, "Debe persistirse un call_transcript (RF-01)"
    assert row.idioma == "es"
    assert row.modelo_stt.startswith("faster-whisper/")
    assert len(row.segmentos) == 2
    assert row.segmentos[0]["inicio"] == 0.0
    assert row.segmentos[0]["fin"] == 2.5
    assert row.segmentos[0]["texto"] == "Hola, buenas tardes."
    assert "hablante" in row.segmentos[0]

    assert call_row.estado == "transcrita", "La Call debe marcarse transcrita (RF-01)"


# ---------------------------------------------------------------------------
# (b) diarización básica opcional (VAD/heurística agente-cliente)
# ---------------------------------------------------------------------------


def test_process_job_diarization_enabled_labels_alternating_turns(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    stt_settings_defaults.stt_diarization_enabled = True
    stt_settings_defaults.stt_diarization_silence_gap_seconds = 1.0

    tenant_id = _crear_tenant(postgres_engine, "TenantSttDiar")
    call_id = f"call-diar-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-diarizacion")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    # Segmento 1 y 2 pegados (gap 0.2s < umbral) -> mismo hablante.
    # Segmento 3 con silencio largo (gap 2s > umbral) -> cambia de turno.
    segments = [
        _fake_segment(0.0, 2.0, "Buenas, CRM WhatsApp le atiende."),
        _fake_segment(2.2, 4.0, "En qué le puedo ayudar."),
        _fake_segment(6.0, 8.0, "Quiero cancelar mi cita."),
    ]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id))

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT segmentos FROM call_transcripts WHERE call_id = :call_id"),
            {"call_id": call_row_id},
        ).fetchone()

    hablantes = [s["hablante"] for s in row.segmentos]
    assert hablantes[0] == hablantes[1], "Gap corto: mismo turno (misma frase)"
    assert hablantes[1] != hablantes[2], "Gap largo: cambia el turno (heurística de silencio)"
    assert set(hablantes) == {"agente", "cliente"}


def test_process_job_diarization_disabled_leaves_hablante_none(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    stt_settings_defaults.stt_diarization_enabled = False

    tenant_id = _crear_tenant(postgres_engine, "TenantSttNoDiar")
    call_id = f"call-nodiar-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-sin-diarizacion")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    segments = [_fake_segment(0.0, 3.0, "Mensaje sin diarizar.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id))

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT segmentos FROM call_transcripts WHERE call_id = :call_id"),
            {"call_id": call_row_id},
        ).fetchone()

    assert row.segmentos[0]["hablante"] is None


# ---------------------------------------------------------------------------
# (c) IDEMPOTENCIA por call_id
# ---------------------------------------------------------------------------


def test_process_job_duplicate_call_id_does_not_duplicate_transcript(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    tenant_id = _crear_tenant(postgres_engine, "TenantSttDedup")
    call_id = f"call-dedup-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-dedup")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    segments = [_fake_segment(0.0, 1.0, "Hola.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id))

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(job, session_factory=_session_factory(postgres_engine))
        # Reprocesar el MISMO job (reintento/redelivery) no debe duplicar.
        process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM call_transcripts WHERE call_id = :call_id"),
            {"call_id": call_row_id},
        ).scalar_one()

    assert count == 1, "Reprocesar el mismo call_id NO debe duplicar la transcripción (RF-03)"


def test_process_job_race_condition_integrity_error_is_handled(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """Simula la condición de carrera: `_transcript_exists` no ve el registro
    (aún no comiteado por otro worker) pero el INSERT choca con la
    restricción UNIQUE de BD -> debe manejarse como `IntegrityError`, sin
    propagar la excepción."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttRace")
    call_id = f"call-race-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-race")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    # Pre-existe ya un call_transcript para ese call_id (otro worker "ganó
    # la carrera" justo antes de que process_job compruebe _transcript_exists).
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO call_transcripts (id, tenant_id, call_id, segmentos, "
                "idioma, modelo_stt) VALUES (:id, :tenant_id, :call_id, "
                "'[]'::jsonb, 'es', 'faster-whisper/large-v3')"
            ),
            {"id": uuid.uuid4(), "tenant_id": tenant_id, "call_id": call_row_id},
        )

    segments = [_fake_segment(0.0, 1.0, "Hola de nuevo.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id))

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ), patch(
        "app.workers.stt_worker._transcript_exists",
        return_value=False,
    ):
        # No debe lanzar: el IntegrityError de la restricción UNIQUE se
        # captura y trata como idempotencia (no como error).
        process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM call_transcripts WHERE call_id = :call_id"),
            {"call_id": call_row_id},
        ).scalar_one()

    assert count == 1, "La condición de carrera no debe crear una segunda fila"


# ---------------------------------------------------------------------------
# (d) el worker no importa el cliente de descarga externo (telefonía)
# ---------------------------------------------------------------------------


def test_stt_worker_module_does_not_import_forbidden_modules():
    """Verifica el IMPORT real (AST) del módulo, no menciones en
    prosa/documentación — el `stt_worker` NUNCA debe importar el cliente de
    descarga externo de telefonía, httpx ni requests."""
    import ast
    import inspect

    from app.workers import stt_worker as worker_module

    source = inspect.getsource(worker_module)
    tree = ast.parse(source)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)

    assert not any("pbx_client" in name for name in imported_names)
    assert not any(name == "httpx" or name.startswith("httpx.") for name in imported_names)
    assert not any(name == "requests" or name.startswith("requests.") for name in imported_names)


def test_stt_engine_module_does_not_import_forbidden_modules():
    """Verifica el IMPORT real (no menciones en prosa/documentación) del
    cliente de descarga externo de telefonía ni de httpx."""
    import ast
    import inspect

    source = inspect.getsource(stt_engine)
    tree = ast.parse(source)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)

    assert not any("pbx_client" in name for name in imported_names)
    assert not any(name == "httpx" or name.startswith("httpx.") for name in imported_names)


# ---------------------------------------------------------------------------
# (e) instrumentación de métricas: RTF, latencia de cola, tasa de error
# ---------------------------------------------------------------------------


def test_process_job_observes_rtf_and_increments_ok_counter(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    tenant_id = _crear_tenant(postgres_engine, "TenantSttMetrics")
    call_id = f"call-metrics-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-metricas")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    segments = [_fake_segment(0.0, 1.0, "Hola.")]
    info = _fake_transcription_info(duration=4.0)
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id))

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ), patch(
        "app.workers.stt_worker.observe_stt_rtf"
    ) as mock_rtf, patch(
        "app.workers.stt_worker.increment_stt_jobs"
    ) as mock_counter, patch(
        "app.workers.stt_worker.observe_stt_queue_latency"
    ) as mock_latency:
        process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            enqueued_at_epoch_seconds=1000.0,
        )

    mock_rtf.assert_called_once()
    _, kwargs = mock_rtf.call_args
    assert kwargs["rtf"] >= 0

    mock_counter.assert_any_call(resultado="ok")
    mock_latency.assert_called_once()


def test_process_job_uses_real_job_enqueued_timestamp_in_production_path(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """Corrección WOLVERINE/BLACK PANTHER (SPEC-038): en el camino REAL de
    producción (`drain_one` -> `process_job` SIN pasar
    `enqueued_at_epoch_seconds` explícito, como hace el worker real), la
    latencia de cola debe calcularse con el timestamp REAL de encolado del
    propio mensaje (`job.enqueued_at_epoch_seconds`, poblado por
    `enqueue_stt_job`/`SttTranscriptionJob` en el momento real de encolado),
    no con un valor ausente/aproximado."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttQueueLatency")
    call_id = f"call-latency-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-latencia-cola")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    segments = [_fake_segment(0.0, 1.0, "Hola.")]
    info = _fake_transcription_info(duration=4.0)
    fake_model = _mock_whisper_model(segments, info)

    # Job "encolado" hace 5 segundos (simulado) -- construcción explícita del
    # dataclass con `enqueued_at_epoch_seconds` en el pasado, exactamente
    # como quedaría poblado por `enqueue_stt_job` en producción real.
    hace_5_segundos = time.time() - 5.0
    job = SttTranscriptionJob(
        call_id=str(call_row_id),
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        enqueued_at_epoch_seconds=hace_5_segundos,
    )

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ), patch(
        "app.workers.stt_worker.observe_stt_queue_latency"
    ) as mock_latency:
        # SIN pasar enqueued_at_epoch_seconds -- exactamente como lo invoca
        # drain_one() en el camino real de producción.
        process_job(job, session_factory=_session_factory(postgres_engine))

    mock_latency.assert_called_once()
    (latencia_observada,), _ = mock_latency.call_args
    assert latencia_observada >= 5.0, (
        "La latencia observada debe reflejar el timestamp REAL de encolado "
        "del job, no un valor ausente/aproximado en el momento de extracción"
    )


def test_process_job_duplicate_increments_duplicado_counter(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    tenant_id = _crear_tenant(postgres_engine, "TenantSttMetricsDup")
    call_id = f"call-metricsdup-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-metricas-dup")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    segments = [_fake_segment(0.0, 1.0, "Hola.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)
    job = SttTranscriptionJob(call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id))

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(job, session_factory=_session_factory(postgres_engine))

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ), patch("app.workers.stt_worker.increment_stt_jobs") as mock_counter:
        process_job(job, session_factory=_session_factory(postgres_engine))

    mock_counter.assert_called_once_with(resultado="duplicado")


def test_process_job_transcription_error_increments_error_counter(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    tenant_id = _crear_tenant(postgres_engine, "TenantSttError")
    call_id = f"call-error-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-error")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    job = SttTranscriptionJob(call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id))

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        side_effect=RuntimeError("fallo simulado de carga GPU/CPU"),
    ), patch("app.workers.stt_worker.increment_stt_jobs") as mock_counter:
        process_job(job, session_factory=_session_factory(postgres_engine))

    mock_counter.assert_called_once_with(resultado="error")

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM call_transcripts WHERE call_id = :call_id"),
            {"call_id": call_row_id},
        ).scalar_one()
    assert count == 0, "Un fallo de transcripción NO debe persistir nada"


def test_process_job_inference_failure_is_translated_and_handled_cleanly(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """Corrección WOLVERINE/BLACK PANTHER (SPEC-038): un fallo de
    `faster-whisper` DURANTE la inferencia real (no en la carga del modelo)
    debe: (a) traducirse a `SttEngineError`, (b) ser manejado limpiamente por
    `process_job` sin dejar `calls.estado` inconsistente ni propagar la
    excepción cruda, (c) incrementar `stt_jobs_total{resultado="error"}`,
    (d) loguearse con los identificadores de negocio (`call_id`/`tenant_id`/
    `job_id`).

    `faster-whisper` devuelve un GENERADOR PEREZOSO de segmentos: el fallo se
    simula con `transcribe_side_effect` (ya soportado por `_mock_whisper_model`)
    para que reviente al LLAMAR a `.transcribe()` (cubre también el caso de
    fallo en la propia llamada, antes de iterar el generador)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttInferError")
    call_id = f"call-infererr-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-inferencia-corrupta")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    def _transcribe_side_effect(*_args, **_kwargs):
        raise RuntimeError("fallo simulado de CTranslate2 durante la inferencia")

    fake_model = _mock_whisper_model(
        segments=None, info=None, transcribe_side_effect=_transcribe_side_effect
    )

    job = SttTranscriptionJob(call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id))

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ), patch("app.workers.stt_worker.increment_stt_jobs") as mock_counter, patch(
        "app.workers.stt_worker.logger"
    ) as mock_logger:
        # No debe propagar la excepción cruda de faster-whisper: process_job
        # la captura como SttEngineError y termina limpiamente.
        process_job(job, session_factory=_session_factory(postgres_engine))

    # (c) métrica de error incrementada.
    mock_counter.assert_called_once_with(resultado="error")

    # (d) log estructurado con los identificadores de negocio.
    mock_logger.error.assert_any_call(
        "stt_job_transcription_failed",
        call_id=job.call_id,
        tenant_id=job.tenant_id,
        job_id=job.job_id,
        exc_info=True,
    )

    # (b) ni transcript persistido ni `calls.estado` mutado a "transcrita".
    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM call_transcripts WHERE call_id = :call_id"),
            {"call_id": call_row_id},
        ).scalar_one()
        call_row = conn.execute(
            sa.text("SELECT estado FROM calls WHERE id = :id"), {"id": call_row_id}
        ).fetchone()

    assert count == 0, "Un fallo DURANTE la inferencia NO debe persistir ningún transcript"
    assert call_row.estado == "finalizada", "calls.estado no debe mutar ante un fallo de inferencia"


# ---------------------------------------------------------------------------
# (f) fallback CPU/medium
# ---------------------------------------------------------------------------


def test_load_model_falls_back_to_cpu_when_primary_device_load_fails(stt_settings_defaults):
    settings = stt_settings_defaults
    settings.stt_device = "cuda"
    settings.stt_model = "large-v3"
    settings.stt_fallback_model = "medium"
    settings.stt_fallback_device = "cpu"

    fake_cpu_model = MagicMock()

    call_log = []

    def _side_effect(*, model_name, device, compute_type, model_dir):
        call_log.append((model_name, device))
        if device == "cuda":
            raise RuntimeError("CUDA no disponible en este host (simulado)")
        return fake_cpu_model

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        side_effect=_side_effect,
    ):
        loaded = stt_engine.load_model()

    assert loaded.device == "cpu"
    assert loaded.model_name == "medium"
    assert loaded.fallback_aplicado is True
    assert call_log == [("large-v3", "cuda"), ("medium", "cpu")]


def test_load_model_uses_primary_device_when_available(stt_settings_defaults):
    settings = stt_settings_defaults
    settings.stt_device = "cuda"
    settings.stt_model = "large-v3"

    fake_gpu_model = MagicMock()

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_gpu_model,
    ):
        loaded = stt_engine.load_model()

    assert loaded.device == "cuda"
    assert loaded.model_name == "large-v3"
    assert loaded.fallback_aplicado is False


def test_load_model_raises_when_both_primary_and_fallback_fail(stt_settings_defaults):
    settings = stt_settings_defaults
    settings.stt_device = "cuda"

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        side_effect=RuntimeError("ni GPU ni CPU disponibles (simulado)"),
    ):
        with pytest.raises(stt_engine.SttEngineError):
            stt_engine.load_model()


def test_transcribe_audio_bytes_reports_fallback_and_degraded_rtf(stt_settings_defaults):
    """El fallback CPU/medium produce una transcripción válida; el RTF puede
    estar degradado (más lento que tiempo real) y debe quedar documentado en
    el resultado (`fallback_aplicado=True`), sin bloquear el pipeline."""
    settings = stt_settings_defaults
    settings.stt_device = "cuda"
    settings.stt_fallback_model = "medium"
    settings.stt_fallback_device = "cpu"

    segments = [_fake_segment(0.0, 3.0, "Transcripción vía fallback CPU.")]
    info = _fake_transcription_info(duration=3.0)
    fake_cpu_model = _mock_whisper_model(segments, info)

    def _side_effect(*, model_name, device, compute_type, model_dir):
        if device == "cuda":
            raise RuntimeError("GPU no disponible (simulado)")
        return fake_cpu_model

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        side_effect=_side_effect,
    ):
        resultado = stt_engine.transcribe_audio_bytes(b"audio-en-claro-fallback")

    assert resultado.fallback_aplicado is True
    assert resultado.device_usado == "cpu"
    assert resultado.modelo_stt == "faster-whisper/medium"
    assert len(resultado.segmentos) == 1
    assert resultado.segmentos[0].texto == "Transcripción vía fallback CPU."
    assert resultado.rtf >= 0


# ---------------------------------------------------------------------------
# drain_one: extrae de la cola y delega en process_job
# ---------------------------------------------------------------------------


def test_drain_one_returns_false_on_empty_queue():
    import asyncio

    import fakeredis.aioredis

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    result = asyncio.run(drain_one(fake_redis, timeout_seconds=0))
    assert result is False


# ---------------------------------------------------------------------------
# SPEC-039: enriquecimiento IA local sobre la transcripción (reutiliza
# SPEC-017/018/019, mismo patrón que SPEC-028 en whatsapp_inbound_worker).
#
# Requiere PostgreSQL real (skip automático sin Postgres, ver docstring del
# módulo). `fakeredis` para la cola de sentimiento y `FakeAIClient` (SPEC-017)
# para el LLM/embeddings local: CERO llamadas externas/red real.
#
# Cubre:
#   (g) la transcripción encola sentimiento (SPEC-018, best-effort) sobre un
#       Message materializado a partir del texto transcrito.
#   (h) se genera un resumen (LLM local, SPEC-039) y se persiste en
#       `calls.resumen`.
#   (i) se genera Y PERSISTE un rag_draft `propuesto` con ≥3 citas trazables
#       (SPEC-017/019) para la conversación de voz de la llamada.
#   (j) modo degradado: LLM no disponible / sin contexto -> no rompe la
#       transcripción ya persistida.
#   (k) aislamiento por tenant del borrador generado.
#   (l) nada se envía/aprueba automáticamente (estado `propuesto`).
# ---------------------------------------------------------------------------

import fakeredis as _fakeredis  # noqa: E402
import fakeredis.aioredis as _fakeredis_aioredis  # noqa: E402
from sqlalchemy.orm import Session as _Session  # noqa: E402

from app.db.session import set_tenant_session as _set_tenant_session  # noqa: E402
from app.services.rag.ingest_service import ingest_document as _ingest_document  # noqa: E402
from tests.rag_ai_client_fake import FakeAIClient  # noqa: E402


def _indexar_documento_tenant_stt(postgres_engine, tenant_id: uuid.UUID, *, texto: str):
    """MISMO patrón que
    `test_whatsapp_inbound_worker.py::_indexar_documento_tenant`: indexa un
    documento (≥3 chunks) para que `generate_rag_draft` tenga contexto real
    recuperable."""
    document_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO documents (id, tenant_id, nombre_archivo, tipo, estado) "
                "VALUES (:id, :tenant_id, 'manual-voz.txt', 'txt', 'pendiente')"
            ),
            {"id": document_id, "tenant_id": tenant_id},
        )

    ai_client = FakeAIClient()
    with _Session(postgres_engine) as db:
        with db.begin():
            _set_tenant_session(db, str(tenant_id))
            _ingest_document(
                db,
                ai_client,
                document_id=document_id,
                text=texto,
                chunk_size=100,
                chunk_overlap=20,
            )
    return document_id, ai_client


def test_process_job_dispatches_sentiment_job_on_transcript(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """Al persistir `call_transcript` se materializa un `Message` entrante y
    se encola sentimiento (SPEC-018) en la MISMA cola Redis que WebChat/
    WhatsApp — sin worker de sentimiento nuevo."""
    from app.core.sentiment_queue import dequeue_sentiment_job

    tenant_id = _crear_tenant(postgres_engine, "TenantSttSentiment")
    call_id = f"call-sentiment-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-sentimiento")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    segments = [_fake_segment(0.0, 2.0, "Estoy muy molesto con el servicio.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id)
    )
    # `FakeServer` compartido + un cliente por loop (ver docstring en
    # `tests/test_rag_api.py::fake_redis`): `process_job` toca este redis
    # DENTRO de su propio `asyncio.run()` interno
    # (`_schedule_sentiment_best_effort`); si el test reutiliza el MISMO
    # objeto `FakeRedis` en su propio `asyncio.run(dequeue_sentiment_job(...))`
    # de más abajo, revienta con `RuntimeError: ... is bound to a different
    # event loop` (confirmado contra Postgres real).
    fake_server = _fakeredis.FakeServer()
    redis_client = _fakeredis_aioredis.FakeRedis(server=fake_server, decode_responses=True)

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
            ai_client=FakeAIClient(unavailable=True),  # RAG/resumen degradado
        )

    with postgres_engine.connect() as conn:
        message_row = conn.execute(
            sa.text(
                "SELECT id FROM messages WHERE tenant_id = :tenant_id "
                "AND contenido = 'Estoy muy molesto con el servicio.'"
            ),
            {"tenant_id": tenant_id},
        ).one_or_none()
    assert message_row is not None, "Debe materializarse un Message con el texto transcrito"

    import asyncio

    dequeue_redis_client = _fakeredis_aioredis.FakeRedis(
        server=fake_server, decode_responses=True
    )
    sentiment_job = asyncio.run(
        dequeue_sentiment_job(
            dequeue_redis_client, tenant_id=tenant_id, timeout_seconds=0
        )
    )
    assert sentiment_job is not None, "Debe haberse encolado un job de sentimiento"
    assert sentiment_job.message_id == str(message_row.id)
    assert sentiment_job.tenant_id == str(tenant_id)


def test_process_job_generates_call_summary(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """Se genera un resumen (LLM local) y se persiste en `calls.resumen`."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttResumen")
    call_id = f"call-resumen-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-resumen")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    segments = [_fake_segment(0.0, 2.0, "Quisiera cancelar mi cita de mañana.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id)
    )
    redis_client = _fakeredis_aioredis.FakeRedis(decode_responses=True)
    ai_client = FakeAIClient(chat_response="Cliente solicita cancelar su cita.")

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
            ai_client=ai_client,
        )

    with postgres_engine.connect() as conn:
        call_row = conn.execute(
            sa.text("SELECT resumen FROM calls WHERE id = :id"), {"id": call_row_id}
        ).fetchone()

    assert call_row.resumen == "Cliente solicita cancelar su cita."


def test_process_job_creates_proposed_rag_draft_with_citations_for_call(
    postgres_engine, app_engine, audio_store_tmp, stt_settings_defaults
):
    """Se genera Y PERSISTE un borrador RAG `propuesto` con ≥3 citas
    trazables para la conversación de voz de la llamada — nunca aprobado ni
    enviado automáticamente (SPEC-019)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttDraft")
    call_id = f"call-draft-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-draft")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    texto = (
        "Horario de atención: lunes a viernes de 8am a 6pm. "
        "Política de reembolsos: 30 días calendario desde la compra. "
        "Canal de soporte prioritario: WhatsApp Business verificado. "
        "Garantía extendida disponible para productos electrónicos. "
    ) * 5
    document_id, ai_client = _indexar_documento_tenant_stt(
        postgres_engine, tenant_id, texto=texto
    )

    segments = [_fake_segment(0.0, 2.0, "¿Cuál es el horario de atención?")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id)
    )
    redis_client = _fakeredis_aioredis.FakeRedis(decode_responses=True)

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(
            job,
            # CORRECCIÓN (bug encontrado contra Postgres real): `retrieve_top_k`
            # no filtra manualmente por tenant_id (depende 100% de RLS, ver
            # `retrieval_service.py`). Con `postgres_engine` (rol owner,
            # SIEMPRE exento de RLS) la recuperación veía chunks de OTROS
            # tenants acumulados en la BD compartida de tests y citaba el
            # documento equivocado — debe usarse `app_engine` (rol
            # `omnicore_app`, ADR-008).
            session_factory=_session_factory(app_engine),
            redis_client=redis_client,
            ai_client=ai_client,
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT tenant_id, estado, citations, conversation_id, "
                "sent_message_id FROM rag_drafts WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).one_or_none()

    assert row is not None, "Debe haberse persistido un rag_draft propuesto"
    assert row.tenant_id == tenant_id
    assert row.estado == "propuesto", "El borrador NUNCA se aprueba automáticamente"
    assert row.sent_message_id is None, "Nada se envía sin aprobación humana (SPEC-019)"
    assert len(row.citations) >= 3
    for citation in row.citations:
        assert citation["source"] == "manual-voz.txt"
        assert citation["excerpt"].strip() != ""
        assert 0.0 <= citation["similarityScore"] <= 1.0
        assert uuid.UUID(citation["document_id"]) == document_id


def test_process_job_ai_unavailable_degrades_without_breaking_transcript(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """R-21: si el LLM local no responde, NO se crea resumen/borrador pero la
    transcripción ya persistida (SPEC-038) no se ve afectada."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttDraftDown")
    call_id = f"call-draftdown-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-draft-down")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    segments = [_fake_segment(0.0, 2.0, "Hola, necesito ayuda.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id)
    )
    redis_client = _fakeredis_aioredis.FakeRedis(decode_responses=True)

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
            ai_client=FakeAIClient(unavailable=True),
        )  # no debe lanzar AIServiceUnavailableError

    with postgres_engine.connect() as conn:
        transcript_count = conn.execute(
            sa.text("SELECT count(*) FROM call_transcripts WHERE call_id = :call_id"),
            {"call_id": call_row_id},
        ).scalar_one()
        call_row = conn.execute(
            sa.text("SELECT estado, resumen FROM calls WHERE id = :id"),
            {"id": call_row_id},
        ).fetchone()
        draft_count = conn.execute(
            sa.text("SELECT count(*) FROM rag_drafts WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()

    assert transcript_count == 1, "La transcripción debe persistir pese al LLM caído"
    assert call_row.estado == "transcrita"
    assert call_row.resumen is None, "Sin LLM disponible no se fabrica un resumen"
    assert draft_count == 0, "Sin LLM disponible no se fabrica un borrador"


def test_process_job_insufficient_context_skips_draft_without_breaking_transcript(
    postgres_engine, app_engine, audio_store_tmp, stt_settings_defaults
):
    """Sin documentos indexados para el tenant (<3 chunks recuperables), no
    se genera el borrador pero la transcripción no se ve afectada."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttDraftSinContexto")
    call_id = f"call-draftsc-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-draft-sc")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    segments = [_fake_segment(0.0, 2.0, "Hola, necesito ayuda con mi pedido.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id)
    )
    redis_client = _fakeredis_aioredis.FakeRedis(decode_responses=True)

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(
            job,
            # CORRECCIÓN (bug encontrado contra Postgres real): con
            # `postgres_engine` (rol owner, evade RLS) esta consulta veía
            # chunks de OTROS tenants de la BD compartida de tests y SÍ
            # encontraba ≥3 "candidatos" pese a que este tenant no indexó
            # ningún documento — debe usarse `app_engine` (rol
            # `omnicore_app`, ADR-008) para que el tenant recién creado
            # (sin documentos propios) vea genuinamente 0 chunks.
            session_factory=_session_factory(app_engine),
            redis_client=redis_client,
            ai_client=FakeAIClient(),
        )

    with postgres_engine.connect() as conn:
        transcript_count = conn.execute(
            sa.text("SELECT count(*) FROM call_transcripts WHERE call_id = :call_id"),
            {"call_id": call_row_id},
        ).scalar_one()
        draft_count = conn.execute(
            sa.text("SELECT count(*) FROM rag_drafts WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()

    assert transcript_count == 1
    assert draft_count == 0


def test_process_job_rag_draft_not_visible_from_other_tenant(
    postgres_engine, app_engine, audio_store_tmp, stt_settings_defaults
):
    """Aislamiento por tenant (RLS, ADR-004): el borrador generado para el
    tenant A no debe ser visible con RLS fijado al tenant B."""
    tenant_a = _crear_tenant(postgres_engine, "TenantSttDraftAislA")
    tenant_b = _crear_tenant(postgres_engine, "TenantSttDraftAislB")
    call_id = f"call-draftaisl-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_a, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-draft-aisl")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_a, call_id=call_id, audio_ref=audio_ref
    )

    texto = (
        "Horario de atención: lunes a viernes de 8am a 6pm. "
        "Política de reembolsos: 30 días calendario desde la compra. "
        "Canal de soporte prioritario: WhatsApp Business verificado. "
    ) * 5
    _, ai_client = _indexar_documento_tenant_stt(postgres_engine, tenant_a, texto=texto)

    segments = [_fake_segment(0.0, 2.0, "horario de atención")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_a)
    )
    redis_client = _fakeredis_aioredis.FakeRedis(decode_responses=True)

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
            ai_client=ai_client,
        )

    with app_engine.connect() as conn:
        with conn.begin():
            _set_tenant_session(conn, str(tenant_b))
            rows = conn.execute(sa.text("SELECT id FROM rag_drafts")).fetchall()
    assert rows == [], "FUGA CROSS-TENANT: el tenant B no debe ver el borrador del A"

    with app_engine.connect() as conn:
        with conn.begin():
            _set_tenant_session(conn, str(tenant_a))
            rows = conn.execute(sa.text("SELECT id FROM rag_drafts")).fetchall()
    assert len(rows) == 1, "El tenant A (dueño real) sí debe ver su propio borrador"


def test_process_job_uses_injected_ai_client_never_opens_real_network(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """Cero llamadas externas: el `FakeAIClient` inyectado registra sus
    propias llamadas — si el worker hubiera instanciado un `AIClient()` real
    en su lugar, estas listas seguirían vacías."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttNoEgress")
    call_id = f"call-noegress-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-noegress")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    texto = (
        "Horario de atención: lunes a viernes de 8am a 6pm. "
        "Política de reembolsos: 30 días calendario desde la compra. "
        "Canal de soporte prioritario: WhatsApp Business verificado. "
    ) * 5
    _, ai_client = _indexar_documento_tenant_stt(postgres_engine, tenant_id, texto=texto)

    segments = [_fake_segment(0.0, 2.0, "horario de atención")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id)
    )
    redis_client = _fakeredis_aioredis.FakeRedis(decode_responses=True)

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
            ai_client=ai_client,
        )

    assert ai_client.chat_calls, "El resumen/borrador debieron usar el ai_client inyectado"
    assert ai_client.embed_calls, "La recuperación RAG debió usar el ai_client inyectado"


# ---------------------------------------------------------------------------
# SPEC-056: sink parametrizado por `destino` — `_sink_call` (default/legacy,
# cero regresión) vs `_sink_message` (nuevo, ADR-013).
#
# Cubre los criterios de aceptación de SPEC-056:
#   (m) cero regresión: un job `call` (formato NUEVO, con `destino` explícito
#       "call:{id}") persiste CallTranscript + Message de voz + pipeline IA
#       exactamente igual que antes de SPEC-056 (mismos asserts que (a)/(g)).
#   (n) un job SIN `destino` en absoluto (formato legacy, `from_json` sin la
#       clave) se procesa como sink `call` sin error.
#   (o) un job `destino="message:{id}"` escribe en `messages.contenido`/
#       `transcripcion_estado="ok"`, y NO crea CallTranscript, NO crea un
#       Message nuevo, NO toca `calls` (conteos de filas antes/después).
#   (p) reprocesar el mismo job `message:{id}` ya en "ok" es no-op (no
#       re-transcribe, no re-escribe).
#   (q) `destino="message:{id}"` con `Message` inexistente se maneja
#       limpiamente (error auditado, sin excepción propagada).
# ---------------------------------------------------------------------------


def _crear_conversation_whatsapp(engine, *, tenant_id: uuid.UUID) -> uuid.UUID:
    """Contacto + conversación de canal `whatsapp`, mismo patrón mínimo que
    `tests/test_whatsapp_inbound_worker.py::_crear_conversation_con_contacto`."""
    contact_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO contacts (id, tenant_id, nombre, telefono) "
                "VALUES (:id, :tenant_id, 'Cliente WhatsApp STT', :telefono)"
            ),
            {
                "id": contact_id,
                "tenant_id": tenant_id,
                "telefono": f"57300{uuid.uuid4().hex[:7]}",
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO conversations (id, tenant_id, contact_id, canal, estado) "
                "VALUES (:id, :tenant_id, :contact_id, 'whatsapp', 'abierta')"
            ),
            {"id": conversation_id, "tenant_id": tenant_id, "contact_id": contact_id},
        )
    return conversation_id


def _crear_message_audio_pendiente(
    engine,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    audio_ref: str,
) -> uuid.UUID:
    """Crea el `Message(tipo="audio", contenido=NULL, transcripcion_estado=
    "pendiente")` que SPEC-055 deja persistido ANTES de encolar en
    `stt:jobs` — MISMO estado inicial que
    `whatsapp_inbound_worker._process_audio_message_event` produce en
    producción real."""
    message_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO messages "
                "(id, tenant_id, conversation_id, remitente, contenido, tipo, "
                " audio_ref, transcripcion_estado, estado_entrega) "
                "VALUES (:id, :tenant_id, :conversation_id, 'contacto', NULL, "
                " 'audio', :audio_ref, 'pendiente', 'enviado')"
            ),
            {
                "id": message_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "audio_ref": audio_ref,
            },
        )
    return message_id


def test_process_job_call_sink_with_explicit_destino_no_regression(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """(m) Cero regresión (RNF-62, criterio duro): un job con `destino`
    EXPLÍCITO `"call:{id}"` (formato NUEVO de SPEC-055/056, en vez de
    ausente) debe comportarse EXACTAMENTE igual que el camino legacy —
    persiste CallTranscript + marca `calls.estado="transcrita"` + materializa
    el Message de voz — mismos asserts que
    `test_process_job_persists_segments_and_updates_call_estado`."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttCallDestinoExplicito")
    call_id = f"call-destino-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-call-destino-explicito")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    segments = [_fake_segment(0.0, 2.0, "Hola, buenas tardes, destino explícito.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(call_row_id),
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        destino=f"call:{call_row_id}",
    )
    assert job.destino == f"call:{call_row_id}"

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        transcript_row = conn.execute(
            sa.text(
                "SELECT segmentos, idioma FROM call_transcripts WHERE call_id = :call_id"
            ),
            {"call_id": call_row_id},
        ).fetchone()
        call_row = conn.execute(
            sa.text("SELECT estado FROM calls WHERE id = :id"), {"id": call_row_id}
        ).fetchone()
        message_row = conn.execute(
            sa.text(
                "SELECT id FROM messages WHERE tenant_id = :tenant_id "
                "AND contenido = 'Hola, buenas tardes, destino explícito.'"
            ),
            {"tenant_id": tenant_id},
        ).one_or_none()

    assert transcript_row is not None, "Debe persistirse un call_transcript (cero regresión)"
    assert transcript_row.idioma == "es"
    assert call_row.estado == "transcrita"
    assert message_row is not None, "Debe materializarse el Message de voz (cero regresión)"


def test_process_job_legacy_json_without_destino_behaves_as_call_sink(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """(n) Un job deserializado de un JSON SIN la clave `destino` (formato
    legacy, `SttTranscriptionJob.from_json`) se procesa como sink `call` sin
    error — compatibilidad hacia atrás estricta (RF-01 SPEC-056)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttLegacyJson")
    call_id = f"call-legacy-{uuid.uuid4().hex[:10]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id)
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-legacy-json")
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id, audio_ref=audio_ref
    )

    segments = [_fake_segment(0.0, 1.0, "Mensaje legacy sin destino.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    import json as _json

    legacy_raw = _json.dumps(
        {
            "job_id": str(uuid.uuid4()),
            "call_id": str(call_row_id),
            "audio_ref": audio_ref,
            "tenant_id": str(tenant_id),
            # SIN "enqueued_at_epoch_seconds" NI "destino": formato ANTERIOR
            # a SPEC-055, tolerado por `from_json`.
        }
    )
    job = SttTranscriptionJob.from_json(legacy_raw)
    assert job.destino == f"call:{call_row_id}", (
        "El default calculado por __post_init__ debe ser call:{call_id}"
    )

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        transcript_row = conn.execute(
            sa.text("SELECT id FROM call_transcripts WHERE call_id = :call_id"),
            {"call_id": call_row_id},
        ).one_or_none()
        call_row = conn.execute(
            sa.text("SELECT estado FROM calls WHERE id = :id"), {"id": call_row_id}
        ).fetchone()

    assert transcript_row is not None, "Job legacy sin destino debe procesarse como sink call"
    assert call_row.estado == "transcrita"


def test_process_job_message_sink_updates_existing_message_without_call_artifacts(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """(o) Un job `destino="message:{id}"` escribe la transcripción en
    `messages.contenido`/`transcripcion_estado="ok"` del Message existente —
    y NO crea CallTranscript, NO crea un Message nuevo, NO toca `calls`
    (ADR-013, conteos de filas antes/después)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttMessageSink")
    conversation_id = _crear_conversation_whatsapp(postgres_engine, tenant_id=tenant_id)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=f"voz-{uuid.uuid4().hex[:10]}")
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-nota-de-voz-whatsapp")
    message_id = _crear_message_audio_pendiente(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        audio_ref=audio_ref,
    )

    with postgres_engine.connect() as conn:
        count_calls_antes = conn.execute(
            sa.text("SELECT COUNT(*) FROM calls WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).scalar_one()
        count_transcripts_antes = conn.execute(
            sa.text("SELECT COUNT(*) FROM call_transcripts WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).scalar_one()
        count_messages_antes = conn.execute(
            sa.text("SELECT COUNT(*) FROM messages WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).scalar_one()

    assert count_calls_antes == 0
    assert count_messages_antes == 1  # solo el Message(tipo="audio") pendiente

    segments = [
        _fake_segment(0.0, 1.5, "Hola, quisiera agendar una cita."),
    ]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(message_id),  # correlación transversal, SPEC-055
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        destino=f"message:{message_id}",
    )

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        message_row = conn.execute(
            sa.text(
                "SELECT contenido, transcripcion_estado, tipo FROM messages "
                "WHERE id = :id"
            ),
            {"id": message_id},
        ).fetchone()
        count_calls_despues = conn.execute(
            sa.text("SELECT COUNT(*) FROM calls WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).scalar_one()
        count_transcripts_despues = conn.execute(
            sa.text("SELECT COUNT(*) FROM call_transcripts WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).scalar_one()
        count_messages_despues = conn.execute(
            sa.text("SELECT COUNT(*) FROM messages WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).scalar_one()

    assert message_row.contenido == "Hola, quisiera agendar una cita."
    assert message_row.transcripcion_estado == "ok"
    assert message_row.tipo == "audio"

    assert count_calls_despues == count_calls_antes == 0, (
        "El sink message NUNCA debe crear una fila calls (ADR-013)"
    )
    assert count_transcripts_despues == count_transcripts_antes == 0, (
        "El sink message NUNCA debe crear un CallTranscript (ADR-013)"
    )
    assert count_messages_despues == count_messages_antes == 1, (
        "El sink message NUNCA debe crear un Message nuevo — solo ACTUALIZA "
        "el existente (ADR-013)"
    )


def test_process_job_message_sink_reprocessing_already_ok_is_noop(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """(p) Reprocesar el MISMO job `message:{id}` cuando `transcripcion_
    estado` ya es "ok" es no-op (RF-05 SPEC-056): no re-transcribe (el motor
    STT no se vuelve a invocar) y no re-escribe `contenido`."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttMessageSinkIdempotente")
    conversation_id = _crear_conversation_whatsapp(postgres_engine, tenant_id=tenant_id)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=f"voz-{uuid.uuid4().hex[:10]}")
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-nota-de-voz-idempotente")
    message_id = _crear_message_audio_pendiente(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        audio_ref=audio_ref,
    )

    segments = [_fake_segment(0.0, 1.0, "Primera transcripción.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(message_id),
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        destino=f"message:{message_id}",
    )

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(job, session_factory=_session_factory(postgres_engine))

    # Reprocesar el MISMO job: el motor STT NO debe invocarse de nuevo (el
    # mock reventaría si se llamase con side_effect de error; aquí basta con
    # verificar que el mock de conteo de llamadas no crece Y que el
    # `contenido` no cambia).
    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ), patch("app.workers.stt_worker.increment_stt_jobs") as mock_counter:
        process_job(job, session_factory=_session_factory(postgres_engine))

    mock_counter.assert_called_once_with(resultado="duplicado")
    # `.transcribe()` del modelo mockeado se invocó UNA sola vez en total (la
    # primera pasada) — el reproceso NO debe volver a invocar la inferencia.
    assert fake_model.transcribe.call_count == 1, (
        "Reprocesar un job message ya 'ok' NO debe re-invocar la inferencia STT"
    )

    with postgres_engine.connect() as conn:
        message_row = conn.execute(
            sa.text("SELECT contenido, transcripcion_estado FROM messages WHERE id = :id"),
            {"id": message_id},
        ).fetchone()
        count_messages = conn.execute(
            sa.text("SELECT COUNT(*) FROM messages WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).scalar_one()

    assert message_row.contenido == "Primera transcripción."
    assert message_row.transcripcion_estado == "ok"
    assert count_messages == 1


def test_process_job_message_sink_missing_message_row_handled_cleanly(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """(q) Un job `destino="message:{id}"` cuyo `Message` no existe (defensa,
    no debería ocurrir en producción real) se maneja limpiamente: se audita
    como error y NO propaga la excepción."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttMessageSinkFaltante")
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=f"voz-{uuid.uuid4().hex[:10]}")
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-message-inexistente")
    message_id_inexistente = uuid.uuid4()

    segments = [_fake_segment(0.0, 1.0, "Texto que nunca se persiste.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(message_id_inexistente),
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        destino=f"message:{message_id_inexistente}",
    )

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ), patch("app.workers.stt_worker.increment_stt_jobs") as mock_counter:
        # No debe propagar excepción.
        process_job(job, session_factory=_session_factory(postgres_engine))

    mock_counter.assert_called_once_with(resultado="error")


def test_process_job_invalid_message_id_in_destino_handled_cleanly(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """SPEC-060 (cobertura): un job con `destino="message:{...}"` cuyo
    sufijo NO es un UUID válido (payload/job forjado o corrupto, no debería
    ocurrir en producción real) se audita como error y NO propaga la
    excepción — mismo criterio de robustez que `stt_job_invalid_call_id`
    del sink `call` (RF-02 SPEC-056), aplicado a la rama de enrutado nueva
    del sink `message`."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttMessageIdInvalido")
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id="voz-id-invalido")
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-con-destino-corrupto")

    job = SttTranscriptionJob(
        call_id="no-se-usa-en-este-camino",
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        destino="message:no-es-un-uuid-valido",
    )

    with patch("app.workers.stt_worker.increment_stt_jobs") as mock_counter:
        # No debe propagar excepción (ValueError de uuid.UUID(...) capturada).
        process_job(job, session_factory=_session_factory(postgres_engine))

    mock_counter.assert_called_once_with(resultado="error")


def test_process_job_message_sink_inference_failure_handled_cleanly(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """SPEC-060 (cobertura): un fallo de `faster-whisper` DURANTE la
    inferencia real sobre el sink `message` (análogo a
    `test_process_job_inference_failure_is_translated_and_handled_cleanly`
    del sink `call`) debe traducirse a `SttEngineError`, manejarse
    limpiamente (sin propagar, sin dejar `Message.transcripcion_estado`
    mutado a "ok") e incrementar `stt_jobs_total{resultado="error"}`."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttMessageInferError")
    conversation_id = _crear_conversation_whatsapp(postgres_engine, tenant_id=tenant_id)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=f"voz-{uuid.uuid4().hex[:10]}")
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-inferencia-corrupta-voz")
    message_id = _crear_message_audio_pendiente(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        audio_ref=audio_ref,
    )

    def _transcribe_side_effect(*_args, **_kwargs):
        raise RuntimeError("fallo simulado de CTranslate2 durante la inferencia")

    fake_model = _mock_whisper_model(
        segments=None, info=None, transcribe_side_effect=_transcribe_side_effect
    )

    job = SttTranscriptionJob(
        call_id=str(message_id),
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        destino=f"message:{message_id}",
    )

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ), patch("app.workers.stt_worker.increment_stt_jobs") as mock_counter:
        process_job(job, session_factory=_session_factory(postgres_engine))

    mock_counter.assert_called_once_with(resultado="error")

    with postgres_engine.connect() as conn:
        message_row = conn.execute(
            sa.text(
                "SELECT contenido, transcripcion_estado FROM messages WHERE id = :id"
            ),
            {"id": message_id},
        ).fetchone()

    assert message_row.contenido is None
    assert message_row.transcripcion_estado == "pendiente"


def test_process_job_message_sink_post_transcription_race_is_handled(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """SPEC-060 (cobertura): otro worker gana la carrera y marca
    `transcripcion_estado="ok"` MIENTRAS este worker transcribía (ventana
    entre la guarda previa y la escritura final) — análogo a
    `test_process_job_race_condition_integrity_error_is_handled` del sink
    `call`. El resultado ya calculado se descarta sin re-escribir; se
    incrementa `stt_jobs_total{resultado="duplicado"}`."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttMessageRacePostTx")
    conversation_id = _crear_conversation_whatsapp(postgres_engine, tenant_id=tenant_id)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=f"voz-{uuid.uuid4().hex[:10]}")
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-race-post-transcripcion")
    message_id = _crear_message_audio_pendiente(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        audio_ref=audio_ref,
    )

    segments = [_fake_segment(0.0, 1.0, "Texto que debe descartarse.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(message_id),
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        destino=f"message:{message_id}",
    )

    # Simula que OTRO worker gana la carrera EXACTAMENTE en la ventana entre
    # la guarda previa (línea 704 del módulo, ya evaluada en `False` antes de
    # llamar a `transcribe_audio_bytes`) y la escritura final (línea 737) —
    # se marca `transcripcion_estado="ok"` justo cuando la transcripción real
    # invoca `transcribe_audio_bytes` (parcheado para escribir en BD como
    # side effect ANTES de devolver el resultado), de modo que la guarda
    # POST-transcripción (no la previa) es la que detecta la carrera.
    original_transcribe_audio_bytes = stt_engine.transcribe_audio_bytes

    def _marcar_ganador_de_la_carrera(audio_bytes):
        with postgres_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE messages SET contenido = 'Ganó otro worker.', "
                    "transcripcion_estado = 'ok' WHERE id = :id"
                ),
                {"id": message_id},
            )
        return original_transcribe_audio_bytes(audio_bytes)

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ), patch(
        "app.workers.stt_worker.transcribe_audio_bytes",
        side_effect=_marcar_ganador_de_la_carrera,
    ), patch("app.workers.stt_worker.increment_stt_jobs") as mock_counter:
        process_job(job, session_factory=_session_factory(postgres_engine))

    mock_counter.assert_called_once_with(resultado="duplicado")

    with postgres_engine.connect() as conn:
        message_row = conn.execute(
            sa.text("SELECT contenido FROM messages WHERE id = :id"),
            {"id": message_id},
        ).fetchone()

    assert message_row.contenido == "Ganó otro worker.", (
        "El resultado recién calculado NUNCA debe sobrescribir el ya "
        "persistido por el worker que ganó la carrera"
    )


def test_process_job_message_sink_dispatches_sentiment_job_on_transcript(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """SPEC-057: el sink `message` dispara sentimiento (SPEC-018) en la MISMA
    cola Redis que WhatsApp/WebChat/el sink `call` — mismo patrón que
    `test_process_job_dispatches_sentiment_job_on_transcript`, sobre el sink
    `message`. `ai_client=FakeAIClient(unavailable=True)` para no interferir
    con el disparo (best-effort) del borrador RAG en este test."""
    from app.core.sentiment_queue import dequeue_sentiment_job

    tenant_id = _crear_tenant(postgres_engine, "TenantSttMessageSentiment")
    conversation_id = _crear_conversation_whatsapp(postgres_engine, tenant_id=tenant_id)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=f"voz-{uuid.uuid4().hex[:10]}")
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-message-sentimiento")
    message_id = _crear_message_audio_pendiente(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        audio_ref=audio_ref,
    )

    segments = [_fake_segment(0.0, 2.0, "Estoy muy molesto con el servicio.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(message_id),
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        destino=f"message:{message_id}",
    )
    # `FakeServer` compartido + un cliente por loop (ver docstring en
    # `test_process_job_dispatches_sentiment_job_on_transcript`): `process_job`
    # toca este redis DENTRO de su propio `asyncio.run()` interno.
    fake_server = _fakeredis.FakeServer()
    redis_client = _fakeredis_aioredis.FakeRedis(server=fake_server, decode_responses=True)

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
            ai_client=FakeAIClient(unavailable=True),  # RAG degradado, no interfiere
        )

    import asyncio

    dequeue_redis_client = _fakeredis_aioredis.FakeRedis(
        server=fake_server, decode_responses=True
    )
    sentiment_job = asyncio.run(
        dequeue_sentiment_job(
            dequeue_redis_client, tenant_id=tenant_id, timeout_seconds=0
        )
    )
    assert sentiment_job is not None, "Debe haberse encolado un job de sentimiento"
    assert sentiment_job.message_id == str(message_id)
    assert sentiment_job.tenant_id == str(tenant_id)


def test_process_job_message_sink_creates_proposed_rag_draft_with_citations(
    postgres_engine, app_engine, audio_store_tmp, stt_settings_defaults
):
    """SPEC-057: se genera Y PERSISTE un borrador RAG `propuesto` con ≥3
    citas trazables para la conversación de WhatsApp de la nota de voz —
    mismo patrón que
    `test_process_job_creates_proposed_rag_draft_with_citations_for_call`,
    sobre el sink `message`. Usa `app_engine` (rol `omnicore_app`) para el
    `session_factory`, NO `postgres_engine` (rol owner) — el owner evade RLS
    y contamina la recuperación RAG con chunks de otros tenants de la BD
    compartida de tests (bug ya encontrado y corregido en los tests
    equivalentes del sink `call`)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttMessageDraft")
    conversation_id = _crear_conversation_whatsapp(postgres_engine, tenant_id=tenant_id)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=f"voz-{uuid.uuid4().hex[:10]}")
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-message-draft")
    message_id = _crear_message_audio_pendiente(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        audio_ref=audio_ref,
    )

    texto = (
        "Horario de atención: lunes a viernes de 8am a 6pm. "
        "Política de reembolsos: 30 días calendario desde la compra. "
        "Canal de soporte prioritario: WhatsApp Business verificado. "
        "Garantía extendida disponible para productos electrónicos. "
    ) * 5
    document_id, ai_client = _indexar_documento_tenant_stt(
        postgres_engine, tenant_id, texto=texto
    )

    segments = [_fake_segment(0.0, 2.0, "¿Cuál es el horario de atención?")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(message_id),
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        destino=f"message:{message_id}",
    )
    redis_client = _fakeredis_aioredis.FakeRedis(decode_responses=True)

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(
            job,
            # Rol `omnicore_app` (ADR-008): con `postgres_engine` (rol owner,
            # SIEMPRE exento de RLS) la recuperación vería chunks de OTROS
            # tenants acumulados en la BD compartida de tests.
            session_factory=_session_factory(app_engine),
            redis_client=redis_client,
            ai_client=ai_client,
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT tenant_id, estado, citations, conversation_id, "
                "sent_message_id FROM rag_drafts WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).one_or_none()

    assert row is not None, "Debe haberse persistido un rag_draft propuesto"
    assert row.tenant_id == tenant_id
    assert row.conversation_id == conversation_id
    assert row.estado == "propuesto", "El borrador NUNCA se aprueba automáticamente"
    assert row.sent_message_id is None, "Nada se envía sin aprobación humana (SPEC-019)"
    assert len(row.citations) >= 3
    for citation in row.citations:
        assert citation["source"] == "manual-voz.txt"
        assert citation["excerpt"].strip() != ""
        assert 0.0 <= citation["similarityScore"] <= 1.0
        assert uuid.UUID(citation["document_id"]) == document_id


def test_process_job_message_sink_rag_draft_never_auto_sent(
    postgres_engine, app_engine, audio_store_tmp, stt_settings_defaults
):
    """SPEC-057/RF-02: el borrador RAG generado a partir de una nota de voz
    de WhatsApp NUNCA se envía automáticamente — queda en `propuesto` con
    `sent_message_id is None`, exactamente como cualquier borrador de
    WhatsApp de texto (SPEC-019)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSttMessageDraftNoAutoSend")
    conversation_id = _crear_conversation_whatsapp(postgres_engine, tenant_id=tenant_id)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=f"voz-{uuid.uuid4().hex[:10]}")
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-message-no-autosend")
    message_id = _crear_message_audio_pendiente(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        audio_ref=audio_ref,
    )

    texto = (
        "Horario de atención: lunes a viernes de 8am a 6pm. "
        "Política de reembolsos: 30 días calendario desde la compra. "
        "Canal de soporte prioritario: WhatsApp Business verificado. "
        "Garantía extendida disponible para productos electrónicos. "
    ) * 5
    _document_id, ai_client = _indexar_documento_tenant_stt(
        postgres_engine, tenant_id, texto=texto
    )

    segments = [_fake_segment(0.0, 2.0, "¿Cuál es la política de reembolsos?")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(message_id),
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        destino=f"message:{message_id}",
    )
    redis_client = _fakeredis_aioredis.FakeRedis(decode_responses=True)

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        process_job(
            job,
            session_factory=_session_factory(app_engine),
            redis_client=redis_client,
            ai_client=ai_client,
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT estado, sent_message_id FROM rag_drafts WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        ).one_or_none()

    assert row is not None
    assert row.estado == "propuesto"
    assert row.sent_message_id is None


def test_process_job_message_sink_reprocessing_ok_does_not_redispatch_ai_pipeline(
    postgres_engine, audio_store_tmp, stt_settings_defaults
):
    """SPEC-057: un reproceso idempotente (`transcripcion_estado` ya "ok",
    RF-05 SPEC-056) NO vuelve a disparar sentimiento/RAG una segunda vez —
    el camino de idempotencia retorna antes de llegar al disparo del
    pipeline IA."""
    import asyncio

    from app.core.sentiment_queue import dequeue_sentiment_job

    tenant_id = _crear_tenant(postgres_engine, "TenantSttMessageNoRedispatch")
    conversation_id = _crear_conversation_whatsapp(postgres_engine, tenant_id=tenant_id)
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=f"voz-{uuid.uuid4().hex[:10]}")
    store_audio(audio_ref=audio_ref, audio_bytes=b"audio-message-no-redispatch")
    message_id = _crear_message_audio_pendiente(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        audio_ref=audio_ref,
    )

    segments = [_fake_segment(0.0, 1.0, "Primera transcripción con IA.")]
    info = _fake_transcription_info()
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(message_id),
        audio_ref=audio_ref,
        tenant_id=str(tenant_id),
        destino=f"message:{message_id}",
    )
    fake_server = _fakeredis.FakeServer()
    redis_client = _fakeredis_aioredis.FakeRedis(server=fake_server, decode_responses=True)

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ):
        # Primera pasada: transcribe y SÍ dispara el pipeline IA.
        process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
            ai_client=FakeAIClient(unavailable=True),
        )

        # Drena el job de sentimiento encolado por la primera pasada para
        # que la cola quede vacía antes de comprobar el reproceso.
        dequeue_redis_client = _fakeredis_aioredis.FakeRedis(
            server=fake_server, decode_responses=True
        )
        primer_sentiment_job = asyncio.run(
            dequeue_sentiment_job(
                dequeue_redis_client, tenant_id=tenant_id, timeout_seconds=0
            )
        )
        assert primer_sentiment_job is not None, (
            "La primera pasada SÍ debe encolar sentimiento (camino ok)"
        )

        # Reproceso del MISMO job (mensaje ya `transcripcion_estado="ok"`,
        # RF-05 SPEC-056): no debe re-disparar el pipeline IA.
        process_job(
            job,
            session_factory=_session_factory(postgres_engine),
            redis_client=redis_client,
            ai_client=FakeAIClient(unavailable=True),
        )

    dequeue_redis_client_2 = _fakeredis_aioredis.FakeRedis(
        server=fake_server, decode_responses=True
    )
    segundo_sentiment_job = asyncio.run(
        dequeue_sentiment_job(
            dequeue_redis_client_2, tenant_id=tenant_id, timeout_seconds=0
        )
    )
    assert segundo_sentiment_job is None, (
        "El reproceso idempotente NO debe volver a encolar sentimiento"
    )

    with postgres_engine.connect() as conn:
        draft_count = conn.execute(
            sa.text("SELECT count(*) FROM rag_drafts WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()
    assert draft_count == 0, (
        "En este test el RAG está degradado (ai_client unavailable); solo "
        "confirma que el reproceso no generó actividad IA adicional"
    )
