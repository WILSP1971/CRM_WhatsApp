#!/usr/bin/env python3
"""Genera carga CPU sintetica en background para simular STT/RAG/sentimiento
concurrentes (proxy, ver notas_instalacion.md sobre por que no se pudieron
correr los workers reales de STT/RAG/sentimiento en este sandbox)."""

import multiprocessing as mp
import time
import sys


def burn(seconds):
    end = time.time() + seconds
    x = 0
    while time.time() < end:
        x = (x * 1234567 + 89) % 999999937
        for _ in range(2000):
            x = (x * 31 + 7) % 999999937


if __name__ == "__main__":
    n_workers = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    procs = [mp.Process(target=burn, args=(seconds,)) for _ in range(n_workers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
