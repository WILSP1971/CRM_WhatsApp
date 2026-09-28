#!/usr/bin/env python3
"""Mide latencia Piper (voz es_ES-davefx-medium) BAJO carga CPU sintetica
concurrente (proxy de STT batch+RAG+sentimiento, ver notas_instalacion.md).
Compara contra la linea base 'warm' sin contencion (bench_piper_warm.py)."""
import json
import time
import statistics
import wave
from pathlib import Path
from piper import PiperVoice
from piper.config import SynthesisConfig

BASE = Path(__file__).resolve().parent.parent
GUIONES_PATH = BASE / "scripts_guiones" / "banco_guiones.json"
VOICES_DIR = BASE / "voices" / "piper"
OUT_DIR = BASE / "audio_out" / "piper_concurrente"
RESULTS_PATH = BASE / "resultados" / "piper_latencia_concurrente.json"

VOZ = "es_ES-davefx-medium"
N_REPS = 5

def main():
    guiones = json.loads(GUIONES_PATH.read_text())["guiones"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = VOICES_DIR / f"{VOZ}.onnx"
    config_path = VOICES_DIR / f"{VOZ}.onnx.json"

    print(f"Cargando {VOZ} bajo carga CPU concurrente...", flush=True)
    t0 = time.perf_counter()
    voice = PiperVoice.load(str(model_path), config_path=str(config_path), use_cuda=False)
    print(f"  carga modelo: {time.perf_counter()-t0:.3f}s", flush=True)
    syn_config = SynthesisConfig()

    resultados = {"motor": "piper", "voz": VOZ, "condicion": "CON carga CPU sintetica concurrente (3 procesos, proxy STT/RAG/sentimiento)", "guiones": {}}

    for g in guiones:
        gid, texto, categoria = g["id"], g["texto"], g["categoria"]
        out_wav = OUT_DIR / f"{gid}.wav"
        synth_times = []
        for rep in range(N_REPS):
            t0 = time.perf_counter()
            with wave.open(str(out_wav), "wb") as wav_file:
                voice.synthesize_wav(texto, wav_file, syn_config=syn_config)
            synth_times.append(time.perf_counter() - t0)
        resultados["guiones"][gid] = {
            "categoria": categoria, "chars": len(texto),
            "synth_s": synth_times,
            "synth_media": statistics.mean(synth_times),
            "synth_mediana": statistics.median(synth_times),
        }
        print(f"  {gid:12s} ({categoria:6s}): synth media={statistics.mean(synth_times):.3f}s mediana={statistics.median(synth_times):.3f}s", flush=True)

    RESULTS_PATH.write_text(json.dumps(resultados, indent=2, ensure_ascii=False))
    print(f"Guardado en {RESULTS_PATH}")

if __name__ == "__main__":
    main()
