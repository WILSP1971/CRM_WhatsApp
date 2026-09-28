#!/usr/bin/env python3
"""Genera tabla de resultados consolidada (CSV + Markdown) desde los JSON
de benchmark warm de Piper y Coqui, comparando contra el techo 5-10s."""
import json
import csv
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RES = BASE / "resultados"

piper = json.loads((RES / "piper_latencia_warm.json").read_text())
coqui = json.loads((RES / "coqui_latencia_warm.json").read_text())

rows = []
for voz, data in piper["voces"].items():
    for gid, g in data["guiones"].items():
        rows.append({
            "motor": "piper", "voz": voz, "guion": gid, "categoria": g["categoria"],
            "chars": g["chars"], "synth_media_s": round(g["synth_media"], 3),
            "synth_p95_s": round(g["synth_p95"], 3),
            "transcode_s": round(g["transcode_s"], 3) if g["transcode_s"] else None,
            "e2e_media_s": round(g["e2e_media"], 3), "e2e_p95_s": round(g["e2e_p95"], 3),
            "cumple_techo_5s": g["e2e_p95"] <= 5.0, "cumple_techo_10s": g["e2e_p95"] <= 10.0,
        })

for gid, g in coqui["guiones"].items():
    if "error" in g:
        continue
    rows.append({
        "motor": "coqui (es/css10/vits)", "voz": "css10-vits-default", "guion": gid,
        "categoria": g["categoria"], "chars": g["chars"],
        "synth_media_s": round(g["synth_media"], 3), "synth_p95_s": round(g["synth_p95"], 3),
        "transcode_s": round(g["transcode_s"], 3) if g["transcode_s"] else None,
        "e2e_media_s": round(g["e2e_media"], 3), "e2e_p95_s": round(g["e2e_p95"], 3),
        "cumple_techo_5s": g["e2e_p95"] <= 5.0, "cumple_techo_10s": g["e2e_p95"] <= 10.0,
    })

csv_path = RES / "tabla_resultados_consolidada.csv"
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

md_path = RES / "tabla_resultados_consolidada.md"
with open(md_path, "w") as f:
    f.write("# Tabla de resultados consolidada — SPEC-067 (THOR)\n\n")
    f.write("Modo 'warm': modelo cargado UNA VEZ (representativo de un worker persistente), ")
    f.write("5 repeticiones por guion, incluye transcodificacion a OGG/Opus con ffmpeg 7.0.2 estatico.\n\n")
    f.write("| Motor | Voz | Guion | Categoria | Chars | Synth media (s) | E2E media (s) | E2E p95 (s) | Cumple <=5s | Cumple <=10s |\n")
    f.write("|---|---|---|---|---|---|---|---|---|---|\n")
    for r in rows:
        f.write(f"| {r['motor']} | {r['voz']} | {r['guion']} | {r['categoria']} | {r['chars']} | "
                 f"{r['synth_media_s']} | {r['e2e_media_s']} | {r['e2e_p95_s']} | "
                 f"{'si' if r['cumple_techo_5s'] else 'NO'} | {'si' if r['cumple_techo_10s'] else 'NO'} |\n")

print(f"CSV: {csv_path}")
print(f"MD: {md_path}")
print(f"\n{len(rows)} filas")
