"""Motor de síntesis TTS 100% local — Piper TTS 1.8.0 (SPEC-067/069, ADR-014).

Este módulo encapsula:
  1. La carga (perezosa, cacheada en proceso — "warm", nunca por CLI/petición,
     ver Adenda SPEC-067) del modelo Piper (`es_ES-davefx-medium`,
     `use_cuda=False`) desde `PIPER_VOICE_DIR` (pesos por volumen, montado en
     `docker-compose.yml`, sin descarga en runtime — mismo criterio que
     `whisper_models`/ADR-009).
  2. `normalize_text`: normalización BÁSICA del guion antes de sintetizar
     (Adenda SPEC-067, vinculante): expande cifras a palabras y separa
     siglas en letras — ninguna voz evaluada pronuncia bien cifras/siglas en
     crudo. Documentado con sus limitaciones conocidas (ver docstring de la
     función).
  3. `synthesize_to_ogg_opus`: sintetiza el guion (ya normalizado) a WAV con
     Piper y transcodifica a OGG/Opus con `ffmpeg` (subprocess local, R-88) —
     formato de nota de voz de WhatsApp.

CHECKPOINT SENSIBLE (RNF-01, ADR-005/009/012): este módulo NUNCA importa
`httpx` ni `app/integrations/whatsapp/` — la única entrada es el texto del
guion (ya aprobado/congelado por el llamador); la única biblioteca de
inferencia es `piper` (paquete `piper-tts`), que corre 100% local sobre los
pesos montados por volumen; la única invocación de proceso externo es
`ffmpeg` (binario del sistema, sin red). Cero llamadas de red se ejecutan en
el camino de código real de este módulo.

Límite de longitud sintetizable (Adenda SPEC-067, R-83 preventivo): un guion
que excede `Settings.respuesta_tts_max_chars` (~650-800 caracteres, rango
probado) NO se sintetiza — `SynthesizableTextTooLongError` se propaga para
que el llamador (`tts_worker`) marque `tts_estado="error"` sin intentar la
inferencia, evitando arriesgar el techo de latencia sin evidencia medida.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

# Nombre de la voz decidido por evidencia (ADR-014 decisión 4, SPEC-067):
# única combinación motor+voz que cumple el techo <=10s en las 8 categorías
# de guion probadas. Mantenido como constante (no configurable por env, a
# diferencia de `Settings.piper_voice` que SÍ lo es) para que el nombre del
# fichero de pesos esperado (`<voz>.onnx`/`<voz>.onnx.json`) sea explícito en
# el código — `Settings.piper_voice` es la fuente de verdad real, esta
# constante documenta el valor esperado.
VOZ_DEFAULT = "es_ES-davefx-medium"

# Números romanos comunes en guiones de atención (siglas de sección/orden),
# deliberadamente NO expandidos (ver limitaciones en `normalize_text`).


class TtsEngineError(RuntimeError):
    """Fallo irrecuperable al cargar el modelo TTS o al sintetizar/transcodificar."""


class SynthesizableTextTooLongError(TtsEngineError):
    """El guion excede el límite sintetizable configurado (Adenda SPEC-067,
    R-83 preventivo) — no se intenta la síntesis."""


@dataclass(frozen=True)
class SynthesisResult:
    ogg_opus_bytes: bytes
    texto_normalizado: str
    modelo_tts: str  # p.ej. "piper/es_ES-davefx-medium"
    tiempo_sintesis_segundos: float
    tiempo_transcodificacion_segundos: float

    @property
    def tiempo_total_segundos(self) -> float:
        return self.tiempo_sintesis_segundos + self.tiempo_transcodificacion_segundos


# ---------------------------------------------------------------------------
# Normalización de texto (Adenda SPEC-067, vinculante)
# ---------------------------------------------------------------------------

_UNIDADES = [
    "cero",
    "uno",
    "dos",
    "tres",
    "cuatro",
    "cinco",
    "seis",
    "siete",
    "ocho",
    "nueve",
]
_DIEZ_A_DIECINUEVE = [
    "diez",
    "once",
    "doce",
    "trece",
    "catorce",
    "quince",
    "dieciséis",
    "diecisiete",
    "dieciocho",
    "diecinueve",
]
_DECENAS = [
    "",
    "",
    "veinte",
    "treinta",
    "cuarenta",
    "cincuenta",
    "sesenta",
    "setenta",
    "ochenta",
    "noventa",
]
_CENTENAS = [
    "",
    "ciento",
    "doscientos",
    "trescientos",
    "cuatrocientos",
    "quinientos",
    "seiscientos",
    "setecientos",
    "ochocientos",
    "novecientos",
]


def _numero_a_palabras(n: int) -> str:
    """Convierte un entero (0..999_999) a palabras en español, suficiente
    para cifras habituales de un guion de atención (montos, cantidades,
    horas, números de documento cortos). NO es un conversor NLP completo:
    ver limitaciones documentadas en `normalize_text`."""
    if n == 0:
        return "cero"
    if n < 0:
        return "menos " + _numero_a_palabras(-n)

    partes: list[str] = []

    if n >= 1_000_000:
        millones, resto = divmod(n, 1_000_000)
        partes.append(
            (
                "un millón"
                if millones == 1
                else f"{_numero_a_palabras(millones)} millones"
            )
        )
        n = resto

    if n >= 1000:
        miles, resto = divmod(n, 1000)
        partes.append("mil" if miles == 1 else f"{_numero_a_palabras(miles)} mil")
        n = resto

    if n >= 100:
        centena, resto = divmod(n, 100)
        partes.append("cien" if n == 100 else _CENTENAS[centena])
        n = resto

    if n >= 20:
        decena, unidad = divmod(n, 10)
        texto_decena = _DECENAS[decena]
        if unidad:
            texto_decena += f" y {_UNIDADES[unidad]}"
        partes.append(texto_decena)
    elif n >= 10:
        partes.append(_DIEZ_A_DIECINUEVE[n - 10])
    elif n > 0:
        partes.append(_UNIDADES[n])

    return " ".join(p for p in partes if p)


_RE_NUMERO = re.compile(r"\d+")
# Siglas: 2+ letras mayúsculas consecutivas (con posibles dígitos, p.ej.
# "COVID19" se trata como sigla + número por separado vía el patrón de
# número de arriba, que corre ANTES). No captura una sola mayúscula inicial
# de frase (evita separar "Hola" letra por letra).
_RE_SIGLA = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{2,}\b")


def _expandir_numero(match: "re.Match[str]") -> str:
    raw = match.group(0)
    try:
        valor = int(raw)
    except ValueError:
        return raw
    if valor > 999_999_999:
        # Fuera del rango razonable de un guion de atención — se deja tal
        # cual en vez de arriesgar una expansión gigante/incorrecta.
        return raw
    return _numero_a_palabras(valor)


def _expandir_sigla(match: "re.Match[str]") -> str:
    sigla = match.group(0)
    return " ".join(sigla)


def normalize_text(texto: str) -> str:
    """Normaliza el guion ANTES de sintetizar (Adenda SPEC-067, vinculante):
    ninguna voz evaluada (Piper/Coqui) pronuncia bien cifras/siglas en crudo.

    Transformaciones aplicadas (básicas, deliberadamente NO un NLP completo):
      1. Cifras (`\\d+`) -> expandidas a palabras en español (p.ej. "123" ->
         "ciento veintitrés"). Cubre enteros hasta 999.999.999; fuera de ese
         rango se deja tal cual (mejor pronunciar dígito a dígito por Piper
         que arriesgar una expansión incorrecta de un número extremo poco
         realista en un guion de atención).
      2. Siglas (2+ letras MAYÚSCULAS consecutivas, p.ej. "EPS", "NIT",
         "IVA") -> separadas en letras con espacios (p.ej. "EPS" -> "E P S")
         para que Piper las deletree en vez de intentar leerlas como una
         palabra.

    LIMITACIONES CONOCIDAS (documentadas, no resueltas aquí — SPEC-069 no
    requiere un NLP completo):
      - Números decimales/con separadores de miles ("1.234,56", "3.14") se
        tratan como varios enteros consecutivos separados por la puntuación
        original (no se reconstruye "mil doscientos treinta y cuatro con
        cincuenta y seis"); aceptable para el caso de uso (montos/cantidades
        aproximadas en un guion de atención), no para contabilidad exacta.
      - Números romanos (III, IV) se tratan como siglas (se deletrean), no
        como numerales.
      - No desambigua abreviaturas comunes minúsculas (p.ej. "Dr.", "Sr.");
        Piper las pronuncia tal cual (aceptable, no es una sigla en mayúscula
        sostenida).
      - Fechas/horas (`"12/09/2026"`, `"14:30"`) se normalizan cifra por
        cifra vía la regla 1 (separadas por la puntuación original), no como
        una fecha/hora hablada natural ("doce de septiembre").
      - No expande símbolos (%, $, °) a palabras — quedan tal cual en el
        texto que llega a Piper (que los ignora o los omite silenciosamente
        según su tokenizador interno; no se ha observado que rompa la
        síntesis, solo que no se locuciona el símbolo).
      - Decenas 21-29 se expanden como "veinte y —" (p.ej. "veinte y tres")
        en vez de la forma culta contraída "veintitrés"; ambas son
        inteligibles/correctas en español hablado, se documenta como
        variante estilística aceptada, no como error.
    """
    sin_numeros = _RE_NUMERO.sub(_expandir_numero, texto)
    return _RE_SIGLA.sub(_expandir_sigla, sin_numeros)


# ---------------------------------------------------------------------------
# Carga perezosa del modelo Piper (proceso persistente, Adenda SPEC-067)
# ---------------------------------------------------------------------------

_voice_lock = threading.Lock()
_voice_cache: dict[str, Any] = {}


def _voices_dir() -> Path:
    settings = get_settings()
    return Path(settings.piper_voice_dir)


def _load_voice(voice_name: str):
    """Carga (una sola vez por proceso, cacheada) el modelo Piper
    `voice_name` desde el directorio de pesos montado por volumen. Nunca
    descarga pesos en runtime — si el fichero no existe, falla explícito
    (mismo criterio de `local_files_only=True` que `stt_engine.py`)."""
    with _voice_lock:
        cached = _voice_cache.get(voice_name)
        if cached is not None:
            return cached

        try:
            from piper import PiperVoice
        except (
            ImportError
        ) as exc:  # pragma: no cover — dependencia declarada en requirements.txt
            raise TtsEngineError(
                "El paquete 'piper-tts' no está instalado en este entorno"
            ) from exc

        voices_dir = _voices_dir()
        model_path = voices_dir / f"{voice_name}.onnx"
        config_path = voices_dir / f"{voice_name}.onnx.json"
        if not model_path.exists() or not config_path.exists():
            raise TtsEngineError(
                f"Pesos de la voz Piper '{voice_name}' no encontrados en "
                f"{voices_dir} (esperados: {model_path.name}/"
                f"{config_path.name}) — deben montarse por volumen antes del "
                "arranque, nunca descargarse en runtime (ADR-009/012)."
            )

        logger.info(
            "tts_engine_loading_voice", voice=voice_name, voices_dir=str(voices_dir)
        )
        voice = PiperVoice.load(
            str(model_path), config_path=str(config_path), use_cuda=False
        )
        _voice_cache[voice_name] = voice
        return voice


def _synthesize_wav(
    texto_normalizado: str, voice_name: str, *, wav_path: Path
) -> float:
    from piper.config import SynthesisConfig

    voice = _load_voice(voice_name)
    syn_config = SynthesisConfig()
    t0 = time.perf_counter()
    with wave.open(str(wav_path), "wb") as wav_file:
        voice.synthesize_wav(texto_normalizado, wav_file, syn_config=syn_config)
    return time.perf_counter() - t0


def _transcode_to_ogg_opus(wav_path: Path, ogg_path: Path) -> float:
    """Transcodifica WAV -> OGG/Opus con `ffmpeg` local (R-88). Sin egress:
    invocación de subprocess sobre binarios en disco, ninguna red."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(wav_path),
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        str(ogg_path),
    ]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30
        )
    except FileNotFoundError as exc:
        raise TtsEngineError(
            "El binario 'ffmpeg' no está disponible en este entorno "
            "(requerido para transcodificar a OGG/Opus, R-88)"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TtsEngineError("ffmpeg excedió el timeout de transcodificación") from exc
    t1 = time.perf_counter()
    if proc.returncode != 0:
        raise TtsEngineError(
            f"ffmpeg falló transcodificando a OGG/Opus: "
            f"{proc.stderr.decode('utf-8', 'ignore')[-500:]}"
        )
    return t1 - t0


def synthesize_to_ogg_opus(
    texto: str, *, voice_name: str | None = None
) -> SynthesisResult:
    """Sintetiza `texto` (guion aprobado, sin normalizar todavía) a un clip
    OGG/Opus compatible con nota de voz de WhatsApp (RF-01/RNF-88 SPEC-069).

    Pasos: (1) valida el límite de longitud sintetizable (Adenda SPEC-067,
    sobre el texto ORIGINAL, antes de normalizar — normalizar puede alargar
    el texto al expandir cifras, así que el límite se aplica sobre lo que el
    agente realmente aprobó, no sobre una versión ya inflada); (2) normaliza
    cifras/siglas (`normalize_text`); (3) sintetiza con Piper (proceso
    persistente, modelo cargado una sola vez); (4) transcodifica a OGG/Opus
    con `ffmpeg`.

    Lanza `SynthesizableTextTooLongError` si `texto` excede
    `Settings.respuesta_tts_max_chars` — el llamador (`tts_worker`) debe
    capturarla y marcar `tts_estado="error"` sin más intentos (RF-07).
    """
    settings = get_settings()
    if len(texto) > settings.respuesta_tts_max_chars:
        raise SynthesizableTextTooLongError(
            f"Guion de {len(texto)} caracteres excede el límite sintetizable "
            f"configurado ({settings.respuesta_tts_max_chars}, Adenda "
            "SPEC-067) — no se intenta la síntesis."
        )

    texto_normalizado = normalize_text(texto)
    voice_name = voice_name or settings.piper_voice

    with tempfile.TemporaryDirectory(prefix="tts_synth_") as tmp_dir:
        wav_path = Path(tmp_dir) / "clip.wav"
        ogg_path = Path(tmp_dir) / "clip.ogg"

        try:
            tiempo_sintesis = _synthesize_wav(
                texto_normalizado, voice_name, wav_path=wav_path
            )
        except TtsEngineError:
            raise
        except (
            Exception
        ) as exc:  # noqa: BLE001 — cualquier fallo del motor es irrecuperable
            raise TtsEngineError(f"Fallo sintetizando con Piper: {exc}") from exc

        tiempo_transcodificacion = _transcode_to_ogg_opus(wav_path, ogg_path)
        ogg_bytes = ogg_path.read_bytes()

    return SynthesisResult(
        ogg_opus_bytes=ogg_bytes,
        texto_normalizado=texto_normalizado,
        modelo_tts=f"piper/{voice_name}",
        tiempo_sintesis_segundos=tiempo_sintesis,
        tiempo_transcodificacion_segundos=tiempo_transcodificacion,
    )
