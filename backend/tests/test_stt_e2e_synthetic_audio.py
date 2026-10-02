"""Test STT e2e con el set de audios SINTÉTICOS es-CO — SPEC-042 (CE-41).

Ejercita el pipeline COMPLETO de voz con bytes de audio REALES (WAV válido,
ver `tests/fixtures_audio/synthetic_call_audio.py`), a diferencia de
`tests/test_stt_worker.py` (que usa placeholders `bytes` arbitrarios tipo
`b"audio-en-claro-de-prueba-stt"` como "audio" — válidos para probar la
LÓGICA del worker, pero no ficheros WAV reales):

    ingesta (audio_store.store_audio) -> cifrado en reposo -> descifrado
    (audio_store.load_audio) -> STT (mock de faster-whisper, como en
    SPEC-038: no hay GPU/pesos reales en este sandbox) -> persistencia de
    `call_transcript` con segmentos+timestamps -> `calls.estado="transcrita"`.

Cubre explícitamente el criterio CE-41 de SPEC-042: "una grabación es-CO
ficticia se transcribe con segmentos + timestamps; WER documentado".

LIMITACIÓN DOCUMENTADA (ver también el docstring de
`synthetic_call_audio.py` y el reporte de HAWKEYE): el modelo `faster-whisper`
real sigue MOCKEADO aquí (no hay GPU/pesos en este sandbox, mismo criterio
que el resto de SPEC-038/042) y el audio de las fixtures es SINTÉTICO
(tono/silencio, sin habla real) — por lo que el WER que se documenta en este
test es SOBRE UN PAR DE TEXTOS DE EJEMPLO (referencia ficticia vs. hipótesis
simulada del mock), NO una medición de la precisión real del modelo
`faster-whisper` transcribiendo voz humana real es-CO. Medir WER real
requeriría: (a) un corpus de audio con HABLA humana real es-CO (o TTS de
calidad aprobado), (b) una transcripción de referencia humana, y (c) GPU/CPU
real ejecutando `faster-whisper` sin mock — ninguna de las tres está
disponible en este sandbox.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.stt_queue import SttTranscriptionJob
from app.services.telefonia import stt_engine
from app.services.telefonia.audio_store import build_audio_ref, load_audio, store_audio
from app.services.telefonia.wer import compute_wer
from app.workers.stt_worker import process_job
from tests.fixtures_audio.synthetic_call_audio import (
    build_synthetic_call_fixtures,
    is_valid_wav,
)


def _crear_tenant(engine, nombre: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO tenants (id, nombre, slug) VALUES (:id, :nombre, :slug)"
            ),
            {
                "id": tenant_id,
                "nombre": nombre,
                "slug": f"{nombre.lower()}-{tenant_id.hex[:8]}",
            },
        )
    return tenant_id


def _crear_call(
    engine,
    *,
    tenant_id: uuid.UUID,
    call_id: str,
    audio_ref: str,
    estado: str = "finalizada",
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


def _fake_segment(start: float, end: float, text: str) -> MagicMock:
    seg = MagicMock()
    seg.start = start
    seg.end = end
    seg.text = text
    return seg


def _fake_transcription_info(
    *, language: str = "es", duration: float = 12.0
) -> MagicMock:
    info = MagicMock()
    info.language = language
    info.duration = duration
    return info


def _mock_whisper_model(segments, info) -> MagicMock:
    model = MagicMock()
    model.transcribe.return_value = (segments, info)
    return model


@pytest.fixture
def audio_store_tmp(tmp_path):
    from app.core.config import get_settings

    settings = get_settings()
    original = settings.audio_storage_path
    settings.audio_storage_path = str(tmp_path)
    yield tmp_path
    settings.audio_storage_path = original


@pytest.fixture(autouse=True)
def _reset_stt_engine_cache():
    stt_engine._modelo_cacheado = None
    yield
    stt_engine._modelo_cacheado = None


# ---------------------------------------------------------------------------
# (0) Las fixtures son WAV válidos (verificable SIN Postgres/GPU).
# ---------------------------------------------------------------------------


def test_all_synthetic_fixtures_are_valid_wav_audio():
    fixtures = build_synthetic_call_fixtures()
    assert 2 <= len(fixtures) <= 5, "SPEC-042 pide un set de 2-5 ficheros"
    for fixture in fixtures:
        assert is_valid_wav(
            fixture.audio_bytes
        ), f"El fixture '{fixture.nombre}' no es un WAV válido"
        assert (
            len(fixture.audio_bytes) > 44
        ), "Debe tener frames más allá de la cabecera RIFF"


def test_synthetic_fixtures_have_realistic_es_co_call_metadata():
    """Metadatos con forma realista de una llamada colombiana (prefijo +57),
    completamente ficticios (C3, sin PHI)."""
    fixtures = build_synthetic_call_fixtures()
    for fixture in fixtures:
        assert fixture.numero.startswith("+57")
        assert fixture.direccion in ("entrante", "saliente")
        assert fixture.duracion_segundos > 0
        assert fixture.call_id


# ---------------------------------------------------------------------------
# (1) e2e: ingesta (audio real WAV) -> almacén cifrado -> STT (mock del
#     modelo) -> persistencia de segmentos+timestamps.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_index", range(len(build_synthetic_call_fixtures())))
def test_stt_e2e_with_synthetic_wav_fixture_persists_segments_and_timestamps(
    postgres_engine, audio_store_tmp, fixture_index
):
    """CE-41: cada fixture del set ficticio es-CO atraviesa el pipeline
    completo (almacenamiento cifrado real + descifrado real + persistencia
    real en Postgres) y produce una `call_transcript` con segmentos +
    timestamps. El propio `faster-whisper` sigue mockeado (SPEC-038: sin
    GPU/pesos en este sandbox), pero el AUDIO en sí es un WAV real que pasa
    por cifrado/descifrado real — a diferencia de los placeholders de
    `test_stt_worker.py`."""
    fixture = build_synthetic_call_fixtures()[fixture_index]
    tenant_id = _crear_tenant(postgres_engine, f"TenantE2E{fixture_index}")
    call_id_str = f"{fixture.call_id}-{uuid.uuid4().hex[:6]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id_str)

    # Ingesta real: se almacena CIFRADO el WAV sintético (no un placeholder).
    store_audio(audio_ref=audio_ref, audio_bytes=fixture.audio_bytes)

    # Confirma que el almacén cifrado en reposo NO contiene el audio en
    # claro (mismo criterio que test_recording_ingest_worker.py, aquí sobre
    # un WAV real en vez de bytes arbitrarios).
    stored_files = list(audio_store_tmp.rglob("*.enc"))
    assert len(stored_files) == 1
    on_disk_bytes = stored_files[0].read_bytes()
    assert fixture.audio_bytes not in on_disk_bytes

    # Descifrado real: `load_audio` debe devolver EXACTAMENTE los bytes WAV
    # originales (round-trip de cifrado íntegro sobre audio real).
    decrypted = load_audio(audio_ref=audio_ref)
    assert decrypted == fixture.audio_bytes
    assert is_valid_wav(decrypted)

    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id_str, audio_ref=audio_ref
    )

    segments = [
        _fake_segment(0.0, 2.0, "Buenas tardes, CRM WhatsApp le atiende."),
        _fake_segment(2.2, 4.5, "En que le puedo colaborar el dia de hoy."),
    ]
    info = _fake_transcription_info(duration=fixture.duracion_segundos)
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id)
    )

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

    assert (
        row is not None
    ), f"Debe persistirse call_transcript para '{fixture.nombre}' (CE-41)"
    assert row.idioma == "es"
    assert row.modelo_stt.startswith("faster-whisper/")
    assert len(row.segmentos) == 2
    for segmento in row.segmentos:
        assert {"inicio", "fin", "texto", "hablante"} <= set(segmento.keys())
        assert (
            segmento["fin"] > segmento["inicio"]
        ), "Cada segmento debe traer timestamps válidos"
    assert call_row.estado == "transcrita"


def test_stt_e2e_zero_third_party_stt_calls_during_pipeline(
    postgres_engine, audio_store_tmp
):
    """CE-41/RNF-41: durante el e2e con audio real, el ÚNICO objeto invocado
    para "transcribir" es el mock inyectado localmente (nunca una librería
    HTTP de terceros) — complementa
    `test_stt_worker.py::test_stt_engine_module_does_not_import_forbidden_modules`
    (AST de imports) con una verificación de comportamiento en tiempo de
    ejecución: se parchea `httpx.Client.send` (el punto único por el que
    CUALQUIER llamada HTTP saliente de `httpx`, la librería que usaría un
    cliente de terceros, pasa) para que un intento real de egress HTTP
    reviente el test. Deliberadamente NO se parchea `socket.socket.connect` a
    nivel de proceso (interferiría con las conexiones REALES y legítimas a
    Postgres/Redis que este mismo test usa vía `postgres_engine`/
    `session_factory`) — el invariante que importa aquí es "cero HTTP a
    terceros", no "cero sockets", y ese es exactamente el vector que
    `httpx`/`requests` usarían para hablar con un STT/TTS/LLM externo."""
    fixture = build_synthetic_call_fixtures()[0]
    tenant_id = _crear_tenant(postgres_engine, "TenantE2ENoEgress")
    call_id_str = f"{fixture.call_id}-{uuid.uuid4().hex[:6]}"
    audio_ref = build_audio_ref(tenant_id=tenant_id, call_id=call_id_str)
    store_audio(audio_ref=audio_ref, audio_bytes=fixture.audio_bytes)
    call_row_id = _crear_call(
        postgres_engine, tenant_id=tenant_id, call_id=call_id_str, audio_ref=audio_ref
    )

    segments = [_fake_segment(0.0, 1.0, "hola")]
    info = _fake_transcription_info(duration=fixture.duracion_segundos)
    fake_model = _mock_whisper_model(segments, info)

    job = SttTranscriptionJob(
        call_id=str(call_row_id), audio_ref=audio_ref, tenant_id=str(tenant_id)
    )

    def _http_egress_forbidden(*_args, **_kwargs):
        raise AssertionError(
            "Se intentó una petición HTTP REAL (httpx) durante el pipeline "
            "STT (RNF-41: cero audio/inferencia a terceros)"
        )

    with patch(
        "app.services.telefonia.stt_engine._construir_whisper_model",
        return_value=fake_model,
    ), patch("httpx.Client.send", side_effect=_http_egress_forbidden), patch(
        "httpx.AsyncClient.send", side_effect=_http_egress_forbidden
    ):
        process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM call_transcripts WHERE call_id = :call_id"),
            {"call_id": call_row_id},
        ).scalar_one()
    assert count == 1, "El e2e debió completarse SIN ninguna llamada HTTP real"


# ---------------------------------------------------------------------------
# (2) WER documentado — CE-41. Ver limitación en el docstring del módulo.
# ---------------------------------------------------------------------------


def test_wer_documented_for_synthetic_fixture_reference_pair():
    """CE-41 "WER documentado": se calcula y se deja registrado (vía
    aserciones explícitas, no solo prosa) el WER de un PAR de ejemplo
    (referencia ficticia es-CO vs. hipótesis simulada de un mock STT) —
    representa el FORMATO/cálculo del reporte de WER que se aplicaría a un
    corpus real. Ver la limitación documentada en el módulo: esto NO mide la
    precisión real de `faster-whisper` (no hay habla real en las fixtures ni
    GPU real en este sandbox)."""
    referencia = "buenas tardes crm whatsapp le atiende en que le puedo colaborar"
    hipotesis_simulada = "buenas tardes crm whatsapp le atiende en que le puedo ayudar"

    resultado = compute_wer(referencia, hipotesis_simulada)

    assert resultado.reference_word_count == 11
    assert resultado.substitutions == 1  # "colaborar" -> "ayudar"
    assert resultado.wer == pytest.approx(1 / 11)
    # Documentado como el "reporte de WER" de esta suite (ver reporte de
    # HAWKEYE para el número consolidado y su limitación).
