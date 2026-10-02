"""Motor de transcripción STT 100% local — `faster-whisper` (SPEC-038, ADR-009).

Este módulo encapsula:
  1. La carga (perezosa, cacheada en proceso) del modelo `faster-whisper`
     desde `STT_MODEL_DIR` (pesos por volumen, `local_files_only=True` —
     BLINDADO contra cualquier intento de `pull`/descarga en runtime, R-41),
     con **fallback automático a CPU/`STT_FALLBACK_MODEL`** si la carga en
     `STT_DEVICE` (típicamente `cuda`) falla (driver/CUDA ausente, OOM, pesos
     del modelo principal no montados) — RNF-42, R-42.
  2. `transcribe_audio_bytes`: transcribe audio en memoria (bytes ya
     descifrados por `audio_store.load_audio`, SPEC-037) y devuelve
     segmentos con `inicio`/`fin`/`texto`/`hablante` + metadatos (idioma,
     duración, modelo/dispositivo realmente usado, RTF).
  3. `_diarizar_segmentos`: diarización BÁSICA opcional por heurística de
     turnos sobre el VAD de `faster-whisper` (ver docstring de la función
     para la decisión de diseño completa, RF-02).

CHECKPOINT SENSIBLE (RNF-41, ADR-009): este módulo NUNCA importa `httpx` ni
`app/services/telefonia/pbx_client.py` — la única entrada es `audio_bytes` en
memoria, ya obtenidos por el llamador desde el almacén cifrado on-prem
(`audio_store.load_audio`); la única biblioteca de inferencia es
`faster_whisper`, que corre 100% local sobre los pesos montados por volumen.
Nota de auditoría: `faster_whisper.utils` importa `requests` de forma
TRANSITIVA (solo la usa internamente en su función `download_model`, que
este módulo JAMÁS invoca) — se instancia `WhisperModel` siempre con
`local_files_only=True`, que hace fallar la carga en vez de intentar
`pull`/descarga si los pesos no están ya en `STT_MODEL_DIR` (R-41). Cero
llamadas de red se ejecutan en el camino de código real de este módulo.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any

import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

# Etiquetas de hablante de la diarización básica (RF-02). Documentadas aquí
# como el contrato de `segmentos[i]["hablante"]` que persiste `stt_worker`.
HABLANTE_AGENTE = "agente"
HABLANTE_CLIENTE = "cliente"
HABLANTE_DESCONOCIDO = None


class SttEngineError(RuntimeError):
    """Fallo irrecuperable al cargar el modelo STT o al transcribir."""


@dataclass(frozen=True)
class TranscriptionSegment:
    inicio: float
    fin: float
    texto: str
    hablante: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "inicio": self.inicio,
            "fin": self.fin,
            "texto": self.texto,
            "hablante": self.hablante,
        }


@dataclass(frozen=True)
class TranscriptionResult:
    segmentos: list[TranscriptionSegment]
    idioma: str
    modelo_stt: str  # p.ej. "faster-whisper/large-v3" o "faster-whisper/medium"
    duracion_audio_segundos: float
    tiempo_proceso_segundos: float
    device_usado: str
    fallback_aplicado: bool = False

    @property
    def rtf(self) -> float:
        """Real-Time Factor: tiempo de proceso / duración del audio (RNF-42).
        Si la duración reportada es 0 (audio vacío/degenerado), se devuelve
        el tiempo de proceso tal cual para no dividir por cero."""
        if self.duracion_audio_segundos <= 0:
            return self.tiempo_proceso_segundos
        return self.tiempo_proceso_segundos / self.duracion_audio_segundos

    def segmentos_como_dicts(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.segmentos]


@dataclass
class _LoadedModel:
    model: Any
    model_name: str
    device: str
    compute_type: str
    fallback_aplicado: bool


# Caché en proceso del modelo cargado — cargar `large-v3` toma segundos/
# minutos; NO se recarga por cada job (un `stt_worker` es un proceso
# de larga duración, mismo patrón que `AIClient` reutilizando conexión).
_modelo_cacheado: _LoadedModel | None = None


def _construir_whisper_model(
    *, model_name: str, device: str, compute_type: str, model_dir: str
) -> Any:
    """Instancia `faster_whisper.WhisperModel` con `local_files_only=True`
    (R-41: blindaje contra `pull`/descarga en runtime — el modelo DEBE existir
    ya en `model_dir`, montado por volumen en deployment, SPEC-035). Import
    perezoso (dentro de la función) para que el resto del proceso pueda
    arrancar/testearse incluso si `faster-whisper`/`ctranslate2` no están
    instalados en el entorno (p.ej. sandbox de CI sin GPU/paquete pesado)."""
    from faster_whisper import WhisperModel  # import perezoso, ver docstring

    return WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=model_dir,
        local_files_only=True,
    )


def load_model(*, force_reload: bool = False) -> _LoadedModel:
    """Carga (o reutiliza del caché) el modelo STT configurado por env.

    Intenta primero `STT_MODEL`/`STT_DEVICE` (p.ej. `large-v3`/`cuda`). Si
    la carga falla (excepción de `ctranslate2`/CUDA: driver ausente, OOM,
    pesos no montados) o si `STT_DEVICE` ya es `cpu` explícitamente, cae a
    `STT_FALLBACK_MODEL`/`STT_FALLBACK_DEVICE` (`medium`/`cpu` por defecto) —
    RNF-42, R-42. El fallback se documenta en el resultado
    (`fallback_aplicado`) para que quede trazable en `call_transcript`/logs.
    """
    global _modelo_cacheado
    if _modelo_cacheado is not None and not force_reload:
        return _modelo_cacheado

    settings = get_settings()
    device_configurado = settings.stt_device.strip().lower()

    if device_configurado != "cpu":
        try:
            model = _construir_whisper_model(
                model_name=settings.stt_model,
                device=settings.stt_device,
                compute_type=settings.stt_compute_type,
                model_dir=settings.stt_model_dir,
            )
            _modelo_cacheado = _LoadedModel(
                model=model,
                model_name=settings.stt_model,
                device=settings.stt_device,
                compute_type=settings.stt_compute_type,
                fallback_aplicado=False,
            )
            logger.info(
                "stt_engine_model_loaded",
                model=settings.stt_model,
                device=settings.stt_device,
            )
            return _modelo_cacheado
        except Exception:  # noqa: BLE001 — cualquier fallo de carga -> fallback CPU
            logger.error(
                "stt_engine_primary_model_load_failed_falling_back_to_cpu",
                model=settings.stt_model,
                device=settings.stt_device,
                fallback_model=settings.stt_fallback_model,
                fallback_device=settings.stt_fallback_device,
                exc_info=True,
            )

    # Fallback CPU (RNF-42/R-42): documentado explícitamente, RTF degradado
    # esperado y aceptado (medición formal en SPEC-042).
    try:
        model = _construir_whisper_model(
            model_name=settings.stt_fallback_model,
            device=settings.stt_fallback_device,
            compute_type=settings.stt_fallback_compute_type,
            model_dir=settings.stt_model_dir,
        )
    except Exception as exc:  # noqa: BLE001
        raise SttEngineError(
            "No se pudo cargar ni el modelo STT primario ni el de fallback "
            f"({settings.stt_fallback_model}/{settings.stt_fallback_device}): {exc}"
        ) from exc

    _modelo_cacheado = _LoadedModel(
        model=model,
        model_name=settings.stt_fallback_model,
        device=settings.stt_fallback_device,
        compute_type=settings.stt_fallback_compute_type,
        fallback_aplicado=device_configurado != "cpu",
    )
    logger.warning(
        "stt_engine_fallback_model_loaded",
        model=settings.stt_fallback_model,
        device=settings.stt_fallback_device,
    )
    return _modelo_cacheado


def _diarizar_segmentos(
    segmentos: list[TranscriptionSegment],
    *,
    silence_gap_seconds: float,
) -> list[TranscriptionSegment]:
    """Diarización BÁSICA opcional (RF-02): etiqueta `agente`/`cliente` por
    heurística de ALTERNANCIA DE TURNOS sobre los huecos de silencio que ya
    detectó el VAD de `faster-whisper` entre segmentos consecutivos.

    Decisión de diseño (documentada, la SPEC pide explícitamente "básica", no
    un modelo de diarización dedicado tipo pyannote):
      - `faster-whisper` no diariza por locutor (no hay embeddings de voz);
        lo único que da gratis es el corte de segmentos por VAD (silencios).
      - Sin audio estéreo separado por canal (no garantizado en el formato
        de grabación del PBX, SPEC-037 no lo especifica), no existe una señal
        de canal fiable para atribuir un segmento a agente/cliente.
      - Heurística elegida: SIEMPRE arranca hablando el que INICIA la
        llamada (se asume `agente` para el primer segmento — en un centro de
        contacto entrante/saliente, quien contesta/origina el flujo suele
        ser el agente; documentado como asunción explícita, ajustable si
        SPEC-039/negocio define lo contrario) y se ALTERNA el turno cada vez
        que el hueco de silencio entre el fin de un segmento y el inicio del
        siguiente supera `silence_gap_seconds` (configurable,
        `STT_DIARIZATION_SILENCE_GAP_SECONDS`, default 1.5s) — un silencio
        prolongado es la señal más barata y robusta de cambio de turno en
        una llamada de voz sin diarización real.
      - Si el hueco es corto (< umbral), se asume que el mismo hablante
        continúa (p.ej. una pausa natural dentro de la misma frase).
      - Es una aproximación deliberadamente simple: el RF-02 solo exige
        "diarización básica opcional" activable/desactivable, no exactitud
        de nivel forense — el WER/calidad real de la diarización quedan para
        medición formal fuera de este alcance (SPEC-042) y el
        human-in-the-loop absorbe errores de atribución de turno (R-48).

    Si `segmentos` está vacío, se devuelve tal cual (no-op).
    """
    if not segmentos:
        return segmentos

    resultado: list[TranscriptionSegment] = []
    hablante_actual = HABLANTE_AGENTE
    previo_fin: float | None = None

    for segmento in segmentos:
        if (
            previo_fin is not None
            and (segmento.inicio - previo_fin) > silence_gap_seconds
        ):
            hablante_actual = (
                HABLANTE_CLIENTE
                if hablante_actual == HABLANTE_AGENTE
                else HABLANTE_AGENTE
            )
        resultado.append(
            TranscriptionSegment(
                inicio=segmento.inicio,
                fin=segmento.fin,
                texto=segmento.texto,
                hablante=hablante_actual,
            )
        )
        previo_fin = segmento.fin

    return resultado


def transcribe_audio_bytes(
    audio_bytes: bytes,
    *,
    diarization_enabled: bool | None = None,
) -> TranscriptionResult:
    """Transcribe audio (bytes en memoria, YA descifrado por el llamador) con
    el modelo STT cargado (`load_model`, con fallback CPU automático).

    Usa el VAD integrado de `faster-whisper` (`vad_filter=True`, RF "VAD para
    saltar silencios") si `STT_VAD_FILTER_ENABLED` está activo. Aplica la
    diarización básica (`_diarizar_segmentos`) si `diarization_enabled` (o,
    si no se pasa explícito, `STT_DIARIZATION_ENABLED` de settings) es
    `True` — activable/desactivable sin tocar código (RF-04).

    NUNCA escribe el audio en claro a disco: `faster-whisper` acepta un
    fichero-like en memoria (`io.BytesIO`), evitando un intermedio en el
    filesystem del audio descifrado.
    """
    settings = get_settings()
    diarizar = (
        settings.stt_diarization_enabled
        if diarization_enabled is None
        else diarization_enabled
    )

    loaded = load_model()

    inicio_proceso = time.perf_counter()
    try:
        segments_iter, info = loaded.model.transcribe(
            io.BytesIO(audio_bytes),
            language=settings.stt_language,
            vad_filter=settings.stt_vad_filter_enabled,
        )

        # `faster-whisper` devuelve `segments_iter` como GENERADOR PEREZOSO:
        # la inferencia real ocurre al ITERARLO, no en la llamada anterior a
        # `.transcribe()` — por eso la construcción de la lista de segmentos
        # también debe quedar dentro de este mismo `try` (si no, un fallo de
        # runtime/CTranslate2 durante la inferencia se propagaría crudo en
        # vez de traducirse a `SttEngineError`, ver correcciones SPEC-038).
        segmentos = [
            TranscriptionSegment(
                inicio=float(seg.start), fin=float(seg.end), texto=seg.text.strip()
            )
            for seg in segments_iter
        ]
    except (
        Exception
    ) as exc:  # noqa: BLE001 — cualquier fallo de inferencia -> SttEngineError
        raise SttEngineError(
            f"Fallo durante la inferencia STT ({loaded.model_name}/{loaded.device}): {exc}"
        ) from exc
    tiempo_proceso = time.perf_counter() - inicio_proceso

    if diarizar:
        segmentos = _diarizar_segmentos(
            segmentos,
            silence_gap_seconds=settings.stt_diarization_silence_gap_seconds,
        )

    idioma = getattr(info, "language", None) or settings.stt_language
    duracion_audio = float(getattr(info, "duration", 0.0) or 0.0)

    modelo_stt = f"faster-whisper/{loaded.model_name}"

    return TranscriptionResult(
        segmentos=segmentos,
        idioma=idioma,
        modelo_stt=modelo_stt,
        duracion_audio_segundos=duracion_audio,
        tiempo_proceso_segundos=tiempo_proceso,
        device_usado=loaded.device,
        fallback_aplicado=loaded.fallback_aplicado,
    )
