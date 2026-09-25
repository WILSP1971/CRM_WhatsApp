#!/usr/bin/env python3
"""
Verificador de RTF (Real-Time Factor) para STT bajo carga.

Lee el histograma Prometheus stt_rtf desde http://localhost:8000/metrics,
calcula el p95 real mediante interpolación sobre los buckets,
y falla si:
  (a) no hay datos de stt_rtf para device="cuda", o
  (b) el p95 supera el umbral RNF-42 (1.0).

Uso:
  python3 verify_stt_rtf.py [--threshold 1.0] [--metrics-url http://localhost:8000/metrics]
"""

import sys
import re
from typing import Dict, List, Tuple, Optional
import argparse


def parse_prometheus_histogram(metrics_text: str, metric_name: str, device: str = "cuda") -> Optional[Dict[str, float]]:
    """
    Parsea un histograma Prometheus del formato de texto expuesto.

    Busca líneas como:
      stt_rtf_bucket{device="cuda",le="0.1"} 5
      stt_rtf_bucket{device="cuda",le="0.5"} 15
      stt_rtf_bucket{device="cuda",le="1.0"} 42
      stt_rtf_bucket{device="cuda",le="+Inf"} 50
      stt_rtf_sum{device="cuda"} 25.3
      stt_rtf_count{device="cuda"} 50

    Retorna un dict:
      {
        "buckets": [(le_value, count), ...],  # Sorted by le_value
        "sum": float,
        "count": int,
      }

    O None si no se encuentran buckets para ese device.
    """
    pattern = rf'{metric_name}_bucket{{.*?device="{device}".*?le="([^"]+)"\}}\s+([\d.]+)'
    sum_pattern = rf'{metric_name}_sum{{.*?device="{device}".*?\}}\s+([\d.]+)'
    count_pattern = rf'{metric_name}_count{{.*?device="{device}".*?\}}\s+(\d+)'

    buckets = []
    sum_val = None
    count_val = None

    for line in metrics_text.split('\n'):
        if line.startswith('#'):
            continue

        # Parsear buckets
        match = re.search(pattern, line)
        if match:
            le_str, count_str = match.groups()
            try:
                le = float(le_str) if le_str != '+Inf' else float('inf')
                count = float(count_str)
                buckets.append((le, count))
            except ValueError:
                continue

        # Parsear sum
        match = re.search(sum_pattern, line)
        if match:
            sum_val = float(match.group(1))

        # Parsear count
        match = re.search(count_pattern, line)
        if match:
            count_val = int(match.group(1))

    if not buckets:
        return None

    # Ordenar buckets por le
    buckets.sort(key=lambda x: x[0])

    return {
        "buckets": buckets,
        "sum": sum_val,
        "count": count_val,
    }


def calculate_p95_from_histogram(histogram: Dict) -> Optional[float]:
    """
    Calcula el percentil 95 (p95) a partir del histograma Prometheus.

    Usa interpolación lineal entre buckets:
      1. Encuentra el bucket donde cumulative_count >= 0.95 * total_count
      2. Interpola linealmente entre ese bucket y el anterior

    Retorna el valor del p95, o None si no es posible calcular.
    """
    buckets = histogram.get("buckets", [])
    count = histogram.get("count")

    if not buckets or not count or count == 0:
        return None

    target = 0.95 * count

    # Buscar el bucket donde cumulative_count >= target
    cumulative = 0.0
    for i, (le, bucket_count) in enumerate(buckets):
        prev_cumulative = cumulative
        cumulative += bucket_count

        if cumulative >= target:
            # Interpolación lineal entre el bucket anterior y el actual
            if i == 0 or le == float('inf'):
                # Si es el primer bucket o +Inf, retornar le sin interpolar
                return le if le != float('inf') else buckets[-2][0] if len(buckets) > 1 else None

            prev_le, prev_bucket_count = buckets[i - 1]

            # Evitar división por cero
            if bucket_count == prev_bucket_count:
                return le

            # Interpolación: p95 = prev_le + (le - prev_le) * (target - prev_cumulative) / (cumulative - prev_cumulative)
            if cumulative == prev_cumulative:
                return le

            p95 = prev_le + (le - prev_le) * (target - prev_cumulative) / (cumulative - prev_cumulative)
            return p95

    # Si llegamos aquí, retornar el último bucket (le)
    return buckets[-1][0] if buckets[-1][0] != float('inf') else None


def fetch_metrics(metrics_url: str) -> Optional[str]:
    """
    Descarga las métricas desde la URL especificada.
    """
    import urllib.request
    import urllib.error

    try:
        with urllib.request.urlopen(metrics_url, timeout=5) as response:
            return response.read().decode('utf-8')
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"::error::No se pudo conectar a {metrics_url}: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Verifica RTF (Real-Time Factor) para STT en GPU"
    )
    parser.add_argument(
        '--threshold',
        type=float,
        default=1.0,
        help='Umbral máximo permitido para p95 RTF (default: 1.0, RNF-42)'
    )
    parser.add_argument(
        '--metrics-url',
        type=str,
        default='http://localhost:8000/metrics',
        help='URL del endpoint /metrics (default: http://localhost:8000/metrics)'
    )
    parser.add_argument(
        '--device',
        type=str,
        default='cuda',
        help='Device a verificar (default: cuda)'
    )
    args = parser.parse_args()

    # Descargar métricas
    print(f"[*] Descargando métricas desde {args.metrics_url}...", file=sys.stderr)
    metrics_text = fetch_metrics(args.metrics_url)
    if not metrics_text:
        print(f"::error::No se pudieron obtener las métricas", file=sys.stderr)
        sys.exit(1)

    # Parsear histograma stt_rtf
    print(f"[*] Parseando histograma stt_rtf para device={args.device}...", file=sys.stderr)
    histogram = parse_prometheus_histogram(metrics_text, 'stt_rtf', device=args.device)

    if not histogram:
        print(f"::error::No se encontró NINGÚN dato stt_rtf para device={args.device}", file=sys.stderr)
        print(f"Esto indica que stt_worker no procesó ningún audio o la métrica no se expone correctamente.", file=sys.stderr)
        sys.exit(1)

    # Calcular p95
    p95 = calculate_p95_from_histogram(histogram)
    if p95 is None:
        print(f"::error::No se pudo calcular p95 del histograma", file=sys.stderr)
        sys.exit(1)

    # Imprimir resultados
    print(f"\n=== RTF Verification Results (SPEC-042, RNF-42) ===\n")
    print(f"Device: {args.device}")
    print(f"Umbral máximo (RNF-42): {args.threshold}")
    print(f"p95 RTF calculado: {p95:.4f}")
    print(f"Total de muestras: {histogram.get('count', 'N/A')}")
    if histogram.get('sum'):
        avg = histogram['sum'] / histogram['count'] if histogram['count'] > 0 else 0
        print(f"Promedio RTF: {avg:.4f}")

    # Verificar contra umbral
    if p95 > args.threshold:
        print(f"\n✗ FALLO: p95 RTF ({p95:.4f}) supera umbral ({args.threshold})")
        print(f"SPEC-042 / RNF-42 no cumplida: RTF debe ser <= {args.threshold} en GPU")

        # Escribir en GITHUB_STEP_SUMMARY
        try:
            import os
            step_summary = os.environ.get('GITHUB_STEP_SUMMARY', '')
            if step_summary:
                with open(step_summary, 'a') as f:
                    f.write(f"\n### RTF Verification — FALLIDO\n\n")
                    f.write(f"- p95 RTF: **{p95:.4f}** (umbral: {args.threshold})\n")
                    f.write(f"- Muestras: {histogram.get('count', 'N/A')}\n")
                    f.write(f"- **Estado: ✗ FALLO — RNF-42 NO CUMPLIDA**\n")
        except Exception as e:
            print(f"(Advertencia: no se pudo escribir en GITHUB_STEP_SUMMARY: {e})", file=sys.stderr)

        sys.exit(1)
    else:
        print(f"\n✓ ÉXITO: p95 RTF ({p95:.4f}) dentro del umbral ({args.threshold})")
        print(f"SPEC-042 / RNF-42 cumplida en GPU")

        # Escribir en GITHUB_STEP_SUMMARY
        try:
            import os
            step_summary = os.environ.get('GITHUB_STEP_SUMMARY', '')
            if step_summary:
                with open(step_summary, 'a') as f:
                    f.write(f"\n### RTF Verification — EXITOSO\n\n")
                    f.write(f"- p95 RTF: **{p95:.4f}** (umbral: {args.threshold})\n")
                    f.write(f"- Muestras: {histogram.get('count', 'N/A')}\n")
                    f.write(f"- **Estado: ✓ ÉXITO — RNF-42 CUMPLIDA**\n")
        except Exception as e:
            print(f"(Advertencia: no se pudo escribir en GITHUB_STEP_SUMMARY: {e})", file=sys.stderr)

        sys.exit(0)


if __name__ == '__main__':
    main()
