#!/usr/bin/env python3
"""
SPEC-067 (THOR) - Benchmark de latencia Piper TTS, CPU-only.

Mide, por guion y por voz:
  - tiempo de sintesis (wall clock, subprocess piper CLI)
  - tiempo de transcodificacion a OGG/Opus con ffmpeg (si esta disponible)
  - tamano de archivo WAV/OGG resultante

Uso:
  .venv/bin/python tests/perf/tts_viability/scripts/bench_piper.py

Requiere: piper-tts instalado en backend/.venv, voces .onnx descargadas en
tests/perf/tts_viability/voices/piper/.
"""

import json
import subprocess
import time
import shutil
import statistics
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
GUIONES_PATH = BASE / "scripts_guiones" / "banco_guiones.json"
VOICES_DIR = BASE / "voices" / "piper"
OUT_DIR = BASE / "audio_out" / "piper"
RESULTS_PATH = BASE / "resultados" / "piper_latencia.json"

VOCES = [
    "es_MX-ald-medium",
    "es_MX-claude-high",
    "es_AR-daniela-high",
    "es_ES-davefx-medium",
]

FFMPEG = shutil.which("ffmpeg")


def synth_piper(
    piper_bin: Path, model_path: Path, config_path: Path, texto: str, out_wav: Path
) -> float:
    """Ejecuta piper CLI, retorna tiempo de sintesis en segundos."""
    cmd = [
        str(piper_bin),
        "-m",
        str(model_path),
        "-c",
        str(config_path),
        "-f",
        str(out_wav),
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        input=texto.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    t1 = time.perf_counter()
    if proc.returncode != 0:
        raise RuntimeError(f"piper fallo: {proc.stderr.decode('utf-8', 'ignore')}")
    return t1 - t0


def transcode_ogg(in_wav: Path, out_ogg: Path) -> float:
    """Transcodifica a OGG/Opus con ffmpeg, retorna tiempo en segundos. -1 si ffmpeg no disponible."""
    if not FFMPEG:
        return -1.0
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
        raise RuntimeError(f"ffmpeg fallo: {proc.stderr.decode('utf-8', 'ignore')}")
    return t1 - t0


def main():
    piper_bin = BASE.parent.parent.parent / ".venv" / "bin" / "piper"
    # backend/tests/perf/tts_viability/scripts -> backend/.venv/bin/piper
    piper_bin = Path("/home/swarm/proyectos/CRM_WhatsApp/backend/.venv/bin/piper")
    assert piper_bin.exists(), f"No se encontro binario piper en {piper_bin}"

    guiones = json.loads(GUIONES_PATH.read_text())["guiones"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"ffmpeg disponible: {bool(FFMPEG)} ({FFMPEG})")
    resultados = {"motor": "piper", "ffmpeg_disponible": bool(FFMPEG), "voces": {}}

    for voz in VOCES:
        model_path = VOICES_DIR / f"{voz}.onnx"
        config_path = VOICES_DIR / f"{voz}.onnx.json"
        if not model_path.exists():
            print(f"[SKIP] voz {voz}: modelo no encontrado")
            continue

        print(f"\n=== Voz: {voz} ===")
        voz_out_dir = OUT_DIR / voz
        voz_out_dir.mkdir(parents=True, exist_ok=True)
        resultados["voces"][voz] = {"guiones": {}}

        for g in guiones:
            gid, texto, categoria = g["id"], g["texto"], g["categoria"]
            out_wav = voz_out_dir / f"{gid}.wav"
            out_ogg = voz_out_dir / f"{gid}.ogg"

            # 3 repeticiones para media/mediana/p95 (spike, no need for cientos)
            synth_times = []
            transcode_times = []
            for rep in range(3):
                t_synth = synth_piper(
                    piper_bin, model_path, config_path, texto, out_wav
                )
                synth_times.append(t_synth)
                if rep == 0:
                    t_transc = transcode_ogg(out_wav, out_ogg)
                    if t_transc >= 0:
                        transcode_times.append(t_transc)

            wav_size = out_wav.stat().st_size if out_wav.exists() else 0
            ogg_size = out_ogg.stat().st_size if out_ogg.exists() else 0

            total_e2e = [
                s + (transcode_times[0] if transcode_times else 0) for s in synth_times
            ]

            resultados["voces"][voz]["guiones"][gid] = {
                "categoria": categoria,
                "chars": len(texto),
                "synth_s": synth_times,
                "synth_media": statistics.mean(synth_times),
                "synth_mediana": statistics.median(synth_times),
                "transcode_s": transcode_times[0] if transcode_times else None,
                "e2e_s": total_e2e,
                "e2e_media": statistics.mean(total_e2e),
                "wav_bytes": wav_size,
                "ogg_bytes": ogg_size,
            }
            print(
                f"  {gid:12s} ({categoria:6s}, {len(texto):3d} chars): "
                f"synth media={statistics.mean(synth_times):.3f}s  "
                f"e2e media={statistics.mean(total_e2e):.3f}s"
            )

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(resultados, indent=2, ensure_ascii=False))
    print(f"\nResultados guardados en {RESULTS_PATH}")


if __name__ == "__main__":
    main()
