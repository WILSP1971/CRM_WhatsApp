"""Generador de audio SINTÉTICO (WAV, PCM 16-bit mono) para pruebas de voz —
SPEC-042.

CHECKPOINT DE DECISIÓN PRAGMÁTICA (HAWKEYE, documentada explícitamente porque
la SPEC-042 depende nominalmente del "simulador de grabaciones" de SPEC-043,
que AÚN NO está implementado — es la siguiente fase, F8 de PLAN-004):

  - Este módulo NO es el simulador formal/documentado de grabaciones que
    exige SPEC-043 (webhook realista, firma HMAC, catálogo de escenarios,
    runbook, etc.) — eso queda fuera de alcance aquí (regla dura de
    SPEC-042 §OUT: "implementación del simulador en sí (SPEC-043)").
  - Es SOLO un generador MÍNIMO y ad-hoc de bytes de audio WAV VÁLIDOS
    (cabecera RIFF/WAVE correcta, PCM 16-bit) para poder ejercitar el
    pipeline de ingesta -> almacenamiento cifrado -> cola STT -> worker STT
    con datos que "parecen" un archivo de audio real en cuanto a FORMATO,
    sin serlo en cuanto a CONTENIDO.
  - El contenido es un tono sintético (onda senoidal) + tramos de silencio,
    generado con el módulo estándar `wave` de Python (sin `numpy`, que no
    está instalado en este sandbox) — NO es habla real. `faster-whisper`
    real (no mockeado) transcribiría este audio como silencio o ruido, no
    como texto es-CO con significado.
  - Por eso el WER "real" (Word Error Rate midiendo la precisión del modelo
    STT real transcribiendo habla real es-CO) NO se puede medir de forma
    honesta con estos ficheros: medir WER real requiere (a) audio con VOZ
    HUMANA real hablando es-CO (o TTS de alta calidad, que tampoco está
    disponible/aprobado aquí) y (b) una transcripción de referencia
    ("ground truth") hecha por un humano o fuente confiable. Ver
    `tests/test_stt_wer.py` para la implementación del CÁLCULO de WER (la
    función en sí, que SÍ se puede probar y ejecutar con texto conocido) y
    el reporte de HAWKEYE para el detalle de esta limitación.
  - Cuando SPEC-043 construya el simulador formal, puede reutilizar/ampliar
    este generador (mismo criterio que indicó el Lead: "se construirá
    después reutilizando lo que tú hagas aquí si aplica").

ACTUALIZACIÓN (WOLVERINE, corrección de hallazgo bloqueante en revisión de
SPEC-043): el simulador formal (`tools/pbx_recording_simulator.py`) SÍ
reutiliza este generador — las funciones de bajo nivel (`tone_samples`,
`silence_samples`, `build_wav_bytes`, `is_valid_wav`) se extrajeron al módulo
neutral `app/services/telefonia/synthetic_audio.py`, del que este fichero
ahora importa (en vez de definirlas aquí), eliminando la duplicación entre
`tests/` y `tools/`.

Todos los ficheros generados son EFÍMEROS/ficticios: sin datos personales,
sin PHI, sin voces reales (C3, cero secretos; alcance IN de SPEC-042: "set de
audios ficticios es-CO").
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.telefonia.synthetic_audio import (
    build_wav_bytes as _build_wav_bytes,
)
from app.services.telefonia.synthetic_audio import is_valid_wav  # noqa: F401 (reexport)
from app.services.telefonia.synthetic_audio import (
    silence_samples as _silence_samples,
)
from app.services.telefonia.synthetic_audio import (
    tone_samples as _tone_samples,
)

# `is_valid_wav` se reexporta deliberadamente desde este módulo (consumido
# por `tests/test_stt_e2e_synthetic_audio.py`) para no romper el import
# público existente tras la extracción a `app.services.telefonia.
# synthetic_audio` (ver docstring del módulo, "ACTUALIZACIÓN").
__all__ = ["SyntheticCallFixture", "build_synthetic_call_fixtures", "is_valid_wav"]


@dataclass(frozen=True)
class SyntheticCallFixture:
    """Un fichero de audio sintético + los metadatos ficticios de la llamada
    es-CO que lo acompañarían en un escenario de ingesta real (SPEC-037)."""

    nombre: str
    call_id: str
    numero: str
    direccion: str
    duracion_segundos: float
    descripcion: str
    audio_bytes: bytes


def _turno_agente_cliente_wav() -> bytes:
    """Simula ALTERNANCIA DE TURNOS (agente/cliente) con silencios largos
    entre tonos de frecuencia distinta — mismo patrón que ejercita la
    heurística de diarización básica de `stt_engine._diarizar_segmentos`
    (gaps de silencio > `STT_DIARIZATION_SILENCE_GAP_SECONDS`)."""
    frames = bytearray()
    frames += _tone_samples(duration_seconds=2.0, frequency_hz=220.0)  # "agente"
    frames += _silence_samples(duration_seconds=2.0)  # gap largo -> cambia turno
    frames += _tone_samples(duration_seconds=2.5, frequency_hz=440.0)  # "cliente"
    frames += _silence_samples(duration_seconds=0.3)  # gap corto -> mismo turno
    frames += _tone_samples(duration_seconds=1.5, frequency_hz=440.0)  # sigue "cliente"
    return _build_wav_bytes(bytes(frames))


def build_synthetic_call_fixtures() -> list[SyntheticCallFixture]:
    """Construye el set de 2-5 fixtures ficticias es-CO que exige el alcance
    IN de SPEC-042 ("Set de audios ficticios es-CO"). Metadatos (número,
    dirección, duración, call_id) con forma realista de una llamada
    colombiana, pero enteramente ficticios (sin PHI, C3)."""
    return [
        SyntheticCallFixture(
            nombre="llamada_entrante_corta",
            call_id="fixture-call-entrante-001",
            numero="+573001112233",
            direccion="entrante",
            duracion_segundos=3.0,
            descripcion="Tono único corto (simula un saludo breve).",
            audio_bytes=_build_wav_bytes(
                _tone_samples(duration_seconds=3.0, frequency_hz=330.0)
            ),
        ),
        SyntheticCallFixture(
            nombre="llamada_saliente_con_turnos",
            call_id="fixture-call-saliente-002",
            numero="+573109998877",
            direccion="saliente",
            duracion_segundos=8.3,
            descripcion=(
                "Tonos alternados con silencios (simula turnos agente/"
                "cliente) — ejercita la heurística de diarización básica."
            ),
            audio_bytes=_turno_agente_cliente_wav(),
        ),
        SyntheticCallFixture(
            nombre="llamada_entrante_con_silencio_inicial",
            call_id="fixture-call-entrante-003",
            numero="+573201234567",
            direccion="entrante",
            duracion_segundos=5.0,
            descripcion="Silencio inicial (simula espera en línea) + tono.",
            audio_bytes=_build_wav_bytes(
                _silence_samples(duration_seconds=1.5)
                + _tone_samples(duration_seconds=3.5, frequency_hz=280.0)
            ),
        ),
        SyntheticCallFixture(
            nombre="llamada_muy_corta",
            call_id="fixture-call-corta-004",
            numero="+573157654321",
            direccion="entrante",
            duracion_segundos=0.8,
            descripcion="Llamada muy corta (caso límite: casi sin contenido).",
            audio_bytes=_build_wav_bytes(
                _tone_samples(duration_seconds=0.8, frequency_hz=500.0)
            ),
        ),
        SyntheticCallFixture(
            nombre="llamada_saliente_larga",
            call_id="fixture-call-saliente-005",
            numero="+573012223344",
            direccion="saliente",
            duracion_segundos=15.0,
            descripcion="Llamada más larga (caso de carga/RTF, ver locustfile).",
            audio_bytes=_build_wav_bytes(
                _tone_samples(duration_seconds=7.0, frequency_hz=350.0)
                + _silence_samples(duration_seconds=1.0)
                + _tone_samples(duration_seconds=7.0, frequency_hz=470.0)
            ),
        ),
    ]


# `is_valid_wav` se reexporta (import arriba) desde
# `app.services.telefonia.synthetic_audio` — usada por los tests para
# confirmar que el fixture es un audio válido en cuanto a FORMATO antes de
# ejercitar el pipeline.
