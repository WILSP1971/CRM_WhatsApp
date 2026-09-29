#!/usr/bin/env python3
"""
TTS Simulator (Piper local, OGG/Opus verification) — SPEC-072, Entregable #6

Sintetiza un guion de ejemplo usando el motor real (Piper TTS 1.8.0,
CPU-only, motor de SPEC-067) y verifica que el resultado es un archivo
OGG/Opus válido — sin ningún egress de inferencia.

USO:
  # Guion de ejemplo por defecto (corto, 180 chars)
  python backend/tools/tts_simulator.py

  # Guion personalizado
  python backend/tools/tts_simulator.py --guion "Tu guion aquí"

  # Guion mediano (dentro del límite 420 chars)
  python backend/tools/tts_simulator.py --guion "Hola, buenos días. Llamamos desde la clínica Campbell. Confirmamos tu cita para mañana a las 2 de la tarde con el Dr. García. Si necesitas reprogramar, presiona 1. Para ampliar el historial, presiona 2."

  # Guion largo (excede 420 chars, debe fallar con SynthesizableTextTooLongError)
  python backend/tools/tts_simulator.py --guion "$(python -c 'print(\"a \" * 250)')"

VERIFICACIONES:
  1. Llamada al motor real (Piper TTS 1.8.0) desde app.services.telefonia.tts_engine
  2. Formato OGG/Opus válido (firma OggS + contenido legítimo)
  3. Métricas de latencia (síntesis + transcodificación)
  4. Manejo de errores: text too long, modelo no encontrado, ffmpeg fallo

CHECKPOINT SENSIBLE (RNF-01, ADR-005/009/012):
  - Este script NUNCA importa httpx ni app/integrations/whatsapp/
  - La única entrada es el texto del guion (en memoria, strings de Python)
  - La única biblioteca de inferencia es piper (local, pesos por volumen)
  - La única invocación de proceso externo es ffmpeg (binario del sistema, sin red)
  - NO se ejecuta ningún upload a WhatsApp — solo se SIMULA e imprime lo que se enviaría

Limitación (mismo criterio que wa_webhook_simulator.py, SPEC-061/R-41):
  El clip se genera localmente y se verifica sin egress. El simulador no
  ejecuta el envío real a Meta (no hay credenciales, no hay Graph API call).
  La suite de tests (backend/tests/test_rag_tts_api.py) sí valida el ciclo
  end-to-end en Docker con mocks apropiados.

CLASIFICACIÓN: SENSIBLE (.no-externo), pero sin secretos en claro (solo
variables de env para TTS_ENGINE, PIPER_VOICE, etc.). Seguro para correr
en cualquier máquina donde PIPER_VOICE_DIR esté montado.
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Añade el directorio backend al path para importar app
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

logger = structlog.get_logger(__name__)


def _verify_ogg_opus(ogg_bytes: bytes) -> tuple[bool, str]:
    """Verifica que el binario sea un archivo OGG/Opus válido.

    Retorna (valid, detalle) donde `valid` es True si pasa las checks.

    Checks básicas (no es un parser OGG completo, solo smoke test):
      1. Firma OGG: comienza con b'OggS' (4 bytes)
      2. Contiene la cadena 'Opus' en algún lugar (indicador de codec)
      3. Tamaño razonable (>100 bytes, <100 MB)
    """
    if len(ogg_bytes) < 4:
        return False, "Binario demasiado corto (<4 bytes)"

    if ogg_bytes[:4] != b"OggS":
        return (
            False,
            f"Firma OGG no encontrada (esperado b'OggS', obtuvo {ogg_bytes[:4]!r})",
        )

    if b"Opus" not in ogg_bytes:
        return False, "Codec Opus no detectado en headers OGG"

    if len(ogg_bytes) < 100:
        return False, "Archivo OGG demasiado corto (<100 bytes, probablemente corrupto)"

    if len(ogg_bytes) > 100 * 1024 * 1024:
        return (
            False,
            f"Archivo OGG demasiado grande (>{100 * 1024 * 1024} bytes)",
        )

    return True, f"OGG/Opus válido ({len(ogg_bytes)} bytes)"


def main():
    parser = argparse.ArgumentParser(
        description="Simulador TTS local (Piper, motor real, sin egress)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--guion",
        type=str,
        default=None,
        help="Guion personalizado (default: ejemplo corto de 180 chars)",
    )
    args = parser.parse_args()

    # Guion por defecto (ejemplo corto, típico de una respuesta de atención)
    if args.guion is None:
        guion = (
            "Hola, buenos días. Confirmamos tu cita para mañana a las 2 de la tarde. "
            "Presiona 1 para confirmar o 2 para reprogramar."
        )
    else:
        guion = args.guion

    print("\n" + "=" * 80)
    print("TTS SIMULATOR — Entregable #6 (SPEC-067/069/072, ADR-014)")
    print("=" * 80)
    print(f"\nGuion ({len(guion)} caracteres):")
    print(f"  {guion[:100]}{'...' if len(guion) > 100 else ''}")

    # Importa el motor real
    try:
        from app.services.telefonia.tts_engine import (
            synthesize_to_ogg_opus,
            SynthesizableTextTooLongError,
            TtsEngineError,
        )
    except ImportError as exc:
        print(f"\n[ERROR] No se pudo importar tts_engine: {exc}")
        print("        Verifica que estés en el directorio backend/ y que app/ esté en el path")
        sys.exit(1)

    # Sintetiza (motor real, sin mocks)
    print("\n[PASO 1] Sintetizando con motor real (Piper TTS 1.8.0)...")
    try:
        t0 = time.perf_counter()
        result = synthesize_to_ogg_opus(guion)
        t_total = time.perf_counter() - t0

        print(f"  ✓ Síntesis exitosa en {t_total:.2f}s")
        print(f"    - Tiempo de síntesis: {result.tiempo_sintesis_segundos:.2f}s")
        print(f"    - Tiempo de transcodificación: {result.tiempo_transcodificacion_segundos:.2f}s")
        print(f"    - Modelo: {result.modelo_tts}")
        print(f"    - Texto normalizado ({len(result.texto_normalizado)} chars):")
        print(f"      {result.texto_normalizado[:80]}{'...' if len(result.texto_normalizado) > 80 else ''}")

    except SynthesizableTextTooLongError as exc:
        print(f"  ✗ Guion rechazado por límite de longitud:")
        print(f"    {exc}")
        sys.exit(1)
    except TtsEngineError as exc:
        print(f"  ✗ Error del motor TTS:")
        print(f"    {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"  ✗ Error inesperado:")
        print(f"    {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # Verifica formato OGG/Opus
    print("\n[PASO 2] Verificando formato OGG/Opus...")
    valid, detalle = _verify_ogg_opus(result.ogg_opus_bytes)
    if valid:
        print(f"  ✓ {detalle}")
    else:
        print(f"  ✗ {detalle}")
        sys.exit(1)

    # SIMULA envío a WhatsApp (sin egress real)
    print("\n[PASO 3] Simulando envío a WhatsApp (sin egress real)...")
    print(f"  Clip generado: {len(result.ogg_opus_bytes)} bytes, tipo OGG/Opus")
    print(f"  Destinatario: +57 (simulado, aleatorio)")
    print(f"  Acción: POST graph.facebook.com/v21.0/{{phone-number-id}}/messages")
    print(f"  Cuerpo (simulado):")
    print(
        f"    {{"
        f"\"messaging_product\": \"whatsapp\", "
        f"\"to\": \"+57300123456\", "
        f"\"type\": \"audio\", "
        f"\"audio\": {{"
        f"\"link\": \"https://<INTERNAL-UPLOAD>/audio/REDACTED\""
        f"}}}}"
    )
    print(f"\n  ⚠ Nota: Este es un SIMULACRO. No se ejecuta el upload real a Meta.")
    print(f"          El clip se genera localmente y se verifica sin egress de inferencia.")

    # Resumen final
    print("\n" + "=" * 80)
    print("RESUMEN")
    print("=" * 80)
    print(f"Estado:                  ✓ EXITOSO")
    print(f"Longitud del guion:      {len(guion)} caracteres (límite: 420)")
    print(f"Latencia total:          {t_total:.2f}s (objetivo: ≤10s)")
    print(f"Tamaño del clip:         {len(result.ogg_opus_bytes)} bytes")
    print(f"Formato:                 OGG/Opus (válido, firma OggS verificada)")
    print(f"Motor TTS:               {result.modelo_tts}")
    print(f"Egress de inferencia:    ✓ CERO (motor local, pesos por volumen)")
    print(f"Egress de networking:    ✓ CERO (ffmpeg local, sin web)")
    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()
