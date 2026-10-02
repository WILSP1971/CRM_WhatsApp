#!/usr/bin/env python3
"""
SPEC-067 (THOR) - Benchmark de latencia Piper TTS, CPU-only, modo "warm".

A diferencia de bench_piper.py (invoca el CLI por proceso => recarga el
modelo ONNX en cada llamada, overhead fijo ~4-5s no representativo de un
servicio real), este script carga el modelo UNA VEZ por voz (como haria
un worker persistente) y mide solo el tiempo de sintesis + transcodificacion
por guion. Esto es la medicion representativa del techo <=5-10s (Q4-b).

Requiere: piper-tts en backend/.venv, ffmpeg (estatico, descargado en
tests/perf/tts_viability/tools/) para la transcodificacion a OGG/Opus.
"""

import json
import subprocess
import time
import statistics
import wave
from pathlib import Path

from piper import PiperVoice
from piper.config import SynthesisConfig

BASE = Path(__file__).resolve().parent.parent
GUIONES_PATH = BASE / "scripts_guiones" / "banco_guiones.json"
VOICES_DIR = BASE / "voices" / "piper"
OUT_DIR = BASE / "audio_out" / "piper_warm"
RESULTS_PATH = BASE / "resultados" / "piper_latencia_warm.json"
FFMPEG = str(next(BASE.glob("tools/ffmpeg-*-static/ffmpeg"), "ffmpeg"))

VOCES = [
    "es_MX-ald-medium",
    "es_MX-claude-high",
    "es_AR-daniela-high",
    "es_ES-davefx-medium",
]

N_REPS = 5


def transcode_ogg(in_wav: Path, out_ogg: Path) -> float:
    cmd = [
        FFMPEG,
        "-y",
        "-i",
        str(in_wav),
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        str(out_ogg),
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    t1 = time.perf_counter()
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg fallo: {proc.stderr.decode('utf-8','ignore')[-500:]}"
        )
    return t1 - t0


def p95(data):
    if len(data) < 2:
        return data[0] if data else None
    s = sorted(data)
    idx = max(0, int(round(0.95 * (len(s) - 1))))
    return s[idx]


def main():
    print(f"ffmpeg binario usado: {FFMPEG}", flush=True)
    guiones = json.loads(GUIONES_PATH.read_text())["guiones"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    resultados = {
        "motor": "piper",
        "modo": "warm (modelo cargado 1 vez por voz)",
        "n_reps": N_REPS,
        "ffmpeg_usado": FFMPEG,
        "voces": {},
    }

    for voz in VOCES:
        model_path = VOICES_DIR / f"{voz}.onnx"
        config_path = VOICES_DIR / f"{voz}.onnx.json"
        if not model_path.exists():
            print(f"[SKIP] {voz}: no encontrado")
            continue

        print(f"\n=== Cargando voz {voz} (warm) ===", flush=True)
        t_load0 = time.perf_counter()
        voice = PiperVoice.load(
            str(model_path), config_path=str(config_path), use_cuda=False
        )
        t_load1 = time.perf_counter()
        print(f"  tiempo de carga del modelo: {t_load1 - t_load0:.3f}s", flush=True)

        voz_out_dir = OUT_DIR / voz
        voz_out_dir.mkdir(parents=True, exist_ok=True)
        resultados["voces"][voz] = {"carga_modelo_s": t_load1 - t_load0, "guiones": {}}
        syn_config = SynthesisConfig()

        for g in guiones:
            gid, texto, categoria = g["id"], g["texto"], g["categoria"]
            out_wav = voz_out_dir / f"{gid}.wav"
            out_ogg = voz_out_dir / f"{gid}.ogg"

            synth_times = []
            transcode_times = []
            for rep in range(N_REPS):
                t0 = time.perf_counter()
                with wave.open(str(out_wav), "wb") as wav_file:
                    voice.synthesize_wav(texto, wav_file, syn_config=syn_config)
                t1 = time.perf_counter()
                synth_times.append(t1 - t0)
                if rep == 0:
                    transcode_times.append(transcode_ogg(out_wav, out_ogg))

            e2e = [s + transcode_times[0] for s in synth_times]
            wav_size = out_wav.stat().st_size
            ogg_size = out_ogg.stat().st_size if out_ogg.exists() else 0

            resultados["voces"][voz]["guiones"][gid] = {
                "categoria": categoria,
                "chars": len(texto),
                "synth_s": synth_times,
                "synth_media": statistics.mean(synth_times),
                "synth_mediana": statistics.median(synth_times),
                "synth_p95": p95(synth_times),
                "transcode_s": transcode_times[0],
                "e2e_s": e2e,
                "e2e_media": statistics.mean(e2e),
                "e2e_mediana": statistics.median(e2e),
                "e2e_p95": p95(e2e),
                "wav_bytes": wav_size,
                "ogg_bytes": ogg_size,
            }
            print(
                f"  {gid:12s} ({categoria:6s}, {len(texto):3d} chars): "
                f"synth media={statistics.mean(synth_times):.3f}s mediana={statistics.median(synth_times):.3f}s | "
                f"transcode={transcode_times[0]:.3f}s | "
                f"e2e media={statistics.mean(e2e):.3f}s p95={p95(e2e):.3f}s",
                flush=True,
            )

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(resultados, indent=2, ensure_ascii=False))
    print(f"\nResultados guardados en {RESULTS_PATH}")


if __name__ == "__main__":
    main()
