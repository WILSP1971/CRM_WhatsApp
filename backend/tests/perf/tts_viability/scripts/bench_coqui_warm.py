#!/usr/bin/env python3
"""
SPEC-067 (THOR) - Benchmark de latencia Coqui TTS, CPU-only, modo "warm".

Carga el modelo UNA VEZ (como un worker persistente) y mide tiempo de
sintesis + transcodificacion OGG/Opus por guion, con el modelo monolingue
espanol tts_models/es/css10/vits (arquitectura VITS, comparable a Piper,
sin overhead de multi-lingue/multi-speaker de XTTS que es mucho mas pesado
para CPU-only).

IMPORTANTE (pinning de entorno, ver notas_instalacion.md):
  Debe ejecutarse con el interprete de tests/perf/tts_viability/.venv_coqui
  (venv AISLADO del venv del backend), con:
    torch==2.14.0+cpu, torchaudio==2.11.0+cpu, transformers==4.57.1 (yanked
    pero funcional), coqui-tts==0.27.5 (con extra [codec] -> torchcodec).
"""

import json
import os
import subprocess
import time
import statistics
from pathlib import Path

os.environ.setdefault("COQUI_TOS_AGREED", "1")

BASE = Path(__file__).resolve().parent.parent
GUIONES_PATH = BASE / "scripts_guiones" / "banco_guiones.json"
TTS_HOME = BASE / "voices" / "coqui"
OUT_DIR = BASE / "audio_out" / "coqui_warm"
RESULTS_PATH = BASE / "resultados" / "coqui_latencia_warm.json"
FFMPEG = str(next(BASE.glob("tools/ffmpeg-*-static/ffmpeg"), "ffmpeg"))

os.environ["TTS_HOME"] = str(TTS_HOME)

MODEL_NAME = "tts_models/es/css10/vits"
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
    from TTS.api import TTS

    print(f"ffmpeg binario usado: {FFMPEG}", flush=True)
    guiones = json.loads(GUIONES_PATH.read_text())["guiones"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"=== Cargando modelo Coqui {MODEL_NAME} (warm) ===", flush=True)
    t_load0 = time.perf_counter()
    tts = TTS(model_name=MODEL_NAME, progress_bar=False, gpu=False)
    t_load1 = time.perf_counter()
    print(f"  tiempo de carga del modelo: {t_load1 - t_load0:.3f}s", flush=True)

    resultados = {
        "motor": "coqui-tts",
        "version_paquete": "0.27.5",
        "modelo": MODEL_NAME,
        "modo": "warm (modelo cargado 1 vez)",
        "n_reps": N_REPS,
        "carga_modelo_s": t_load1 - t_load0,
        "guiones": {},
    }

    for g in guiones:
        gid, texto, categoria = g["id"], g["texto"], g["categoria"]
        out_wav = OUT_DIR / f"{gid}.wav"
        out_ogg = OUT_DIR / f"{gid}.ogg"

        synth_times = []
        transcode_times = []
        try:
            for rep in range(N_REPS):
                t0 = time.perf_counter()
                tts.tts_to_file(text=texto, file_path=str(out_wav))
                t1 = time.perf_counter()
                synth_times.append(t1 - t0)
                if rep == 0:
                    transcode_times.append(transcode_ogg(out_wav, out_ogg))
        except Exception as e:
            print(f"  {gid}: ERROR {e}", flush=True)
            resultados["guiones"][gid] = {
                "categoria": categoria,
                "chars": len(texto),
                "error": str(e),
            }
            continue

        e2e = [s + transcode_times[0] for s in synth_times]
        wav_size = out_wav.stat().st_size
        ogg_size = out_ogg.stat().st_size if out_ogg.exists() else 0

        resultados["guiones"][gid] = {
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
            f"transcode={transcode_times[0]:.3f}s | e2e media={statistics.mean(e2e):.3f}s p95={p95(e2e):.3f}s",
            flush=True,
        )

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(resultados, indent=2, ensure_ascii=False))
    print(f"\nResultados guardados en {RESULTS_PATH}")


if __name__ == "__main__":
    main()
