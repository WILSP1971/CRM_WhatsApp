#!/usr/bin/env python
r"""Simulador de grabaciones PBX — SPEC-043.

Emite eventos ficticios de grabación (audio WAV sintético + metadatos) contra
el webhook real de grabaciones, con firma HMAC válida. Permite:

  1. **Escenario 1: Grabación simple** — Emite 1 audio ficticio con metadatos
     correctos, firmado con WEBHOOK_SECRET válido. Valida que el webhook
     responde 202.

  2. **Escenario 2: Reentrega (idempotencia)** — Emite el MISMO call_id dos
     veces. El webhook ACK ambos (202), pero el worker de ingesta debe dedup
     (registrar una sola Call/Transcript). Prueba que la idempotencia funciona.

  3. **Escenario 3: Sin mapeo de tenant** — Emite un audio con numero_destino
     que NO existe en pbx_lines (para ningún tenant). El webhook ACK (202),
     pero el worker de ingesta DEBE auditar el descarte (log, sin crash).

Uso:

    # Escenario 1: Grabación simple
    python backend/tools/pbx_recording_simulator.py \\
        --scenario simple \\
        --webhook-url http://localhost:8000 \\
        --webhook-secret <WEBHOOK_SECRET> \\
        --call-id call-001 \\
        --numero "+573001234567"

    # Escenario 2: Reentrega (mismo call_id)
    python backend/tools/pbx_recording_simulator.py \\
        --scenario redelivery \\
        --webhook-url http://localhost:8000 \\
        --webhook-secret <WEBHOOK_SECRET> \\
        --call-id call-001

    # Escenario 3: Sin mapeo de tenant
    python backend/tools/pbx_recording_simulator.py \\
        --scenario unmapped \\
        --webhook-url http://localhost:8000 \\
        --webhook-secret <WEBHOOK_SECRET> \\
        --call-id call-unmapped \\
        --numero-destino "999-no-existe"

    # --count aplica a CUALQUIER escenario (repite el envío N veces), no
    # solo a redelivery — útil también para pruebas de carga sobre "simple"
    # o "unmapped".
    python backend/tools/pbx_recording_simulator.py \\
        --scenario simple --call-id call-carga --count 5

Variables de entorno (opcional):

    WEBHOOK_SECRET: Si no se pasa --webhook-secret, usa esta var.
    WEBHOOK_URL: Si no se pasa --webhook-url, usa esta var (default: http://localhost:8000).

Verificación manual:

    # 1. Verificar que el webhook recibió la petición
    docker compose logs --tail=30 api | grep "pbx_webhook_recording_enqueued"
    # Esperado: [INFO] pbx_webhook_recording_enqueued call_id=call-001 ...

    # 2. Verificar que stt_worker transcribió
    docker compose logs --tail=30 stt_worker | grep "call_id=call-001"
    # Esperado: [INFO] Transcription complete ...

    # 3. Verificar que no hay secretos en los logs
    docker compose logs api | grep -i "webhook_secret\|auth"
    # Esperado: nada (secrets NUNCA logueados)

CHECKPOINT SENSIBLE (C3):
  - Este simulador recibe WEBHOOK_SECRET ÚNICAMENTE por CLI/env, NUNCA hardcodeado.
  - No expone la firma en logs (solo en headers HTTP, que no se loguean).
  - Audio es síntético (no datos reales/PHI) — seguro de ejecutar en desarrollo.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import httpx
except ImportError:
    print("ERROR: httpx no instalado. Instala con: pip install httpx")
    sys.exit(1)

# Permite ejecutar este script directamente (`python backend/tools/
# pbx_recording_simulator.py ...`) sin tener `backend/` ya en `sys.path`,
# para poder importar el módulo neutral de generación de audio sintético
# compartido con `tests/fixtures_audio/synthetic_call_audio.py` (SPEC-042).
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.services.telefonia.synthetic_audio import (  # noqa: E402
    build_wav_bytes as _build_wav_bytes,
)
from app.services.telefonia.synthetic_audio import (  # noqa: E402
    silence_samples as _silence_samples,
)
from app.services.telefonia.synthetic_audio import (  # noqa: E402
    tone_samples as _tone_samples,
)


@dataclass(frozen=True)
class SyntheticAudio:
    """Fichero de audio sintético + metadatos."""

    nombre: str
    call_id: str
    numero: str
    numero_destino: str
    direccion: str
    duracion_segundos: float
    descripcion: str
    audio_bytes: bytes


# --- Generación de audio sintético ---
#
# Las funciones de bajo nivel (`_tone_samples`, `_silence_samples`,
# `_build_wav_bytes`) se importan de `app.services.telefonia.synthetic_audio`
# (módulo neutral compartido con `tests/fixtures_audio/synthetic_call_audio.py`,
# SPEC-042) — ver imports al inicio del fichero. Aquí solo se componen en los
# audios concretos de cada escenario.


def _create_simple_audio(duration_seconds: float = 3.0) -> bytes:
    """Crea un audio simpla: tono único."""
    return _build_wav_bytes(_tone_samples(duration_seconds=duration_seconds, frequency_hz=330.0))


def _create_turns_audio() -> bytes:
    """Crea un audio con turnos (agente/cliente)."""
    frames = bytearray()
    frames += _tone_samples(duration_seconds=2.0, frequency_hz=220.0)
    frames += _silence_samples(duration_seconds=2.0)
    frames += _tone_samples(duration_seconds=2.5, frequency_hz=440.0)
    frames += _silence_samples(duration_seconds=0.3)
    frames += _tone_samples(duration_seconds=1.5, frequency_hz=440.0)
    return _build_wav_bytes(bytes(frames))


# --- Scenarios ---


def _scenario_simple(
    call_id: str,
    numero: str,
    numero_destino: str,
) -> SyntheticAudio:
    """Escenario 1: Grabación simple con metadatos correctos."""
    return SyntheticAudio(
        nombre="simple_call",
        call_id=call_id,
        numero=numero,
        numero_destino=numero_destino,
        direccion="entrante",
        duracion_segundos=3.0,
        descripcion="Tono simple (simulador escenario 1)",
        audio_bytes=_create_simple_audio(3.0),
    )


def _scenario_redelivery(call_id: str) -> SyntheticAudio:
    """Escenario 2: Reentrega del mismo call_id (prueba idempotencia)."""
    return SyntheticAudio(
        nombre="redelivery_call",
        call_id=call_id,
        numero="+573109876543",
        numero_destino="000-test-line",
        direccion="saliente",
        duracion_segundos=8.3,
        descripcion="Reentrega con turnos (escenario 2, idempotencia)",
        audio_bytes=_create_turns_audio(),
    )


def _scenario_unmapped(call_id: str, numero_destino: str) -> SyntheticAudio:
    """Escenario 3: Sin mapeo de tenant (numero_destino no existe)."""
    return SyntheticAudio(
        nombre="unmapped_call",
        call_id=call_id,
        numero="+573201112233",
        numero_destino=numero_destino,
        direccion="entrante",
        duracion_segundos=2.5,
        descripcion=(
            "Audio con numero_destino sin mapeo (escenario 3, descarte auditado)"
        ),
        audio_bytes=_create_simple_audio(2.5),
    )


# --- Firma y envío ---


def _sign_audio(audio_bytes: bytes, webhook_secret: str) -> str:
    """Calcula firma HMAC-SHA256 sobre audio crudo (mismo formato que webhook.py)."""
    digest = hmac.new(
        webhook_secret.encode("utf-8"),
        audio_bytes,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _post_recording(
    webhook_url: str,
    audio: SyntheticAudio,
    webhook_secret: str,
) -> tuple[int | None, str]:
    """POST del audio al webhook, devuelve (status_code, response_text).

    Si hay un error de conexión/timeout/HTTP (p. ej. backend no levantado),
    NO propaga el traceback crudo: devuelve `(None, "<mensaje de error>")`
    para que el llamador lo reporte de forma amigable (ver README_PBX_
    SIMULATOR.md § "Status: (connection error)").
    """
    signature = _sign_audio(audio.audio_bytes, webhook_secret)

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{webhook_url}/webhooks/pbx/recordings",
                data={
                    "call_id": audio.call_id,
                    "numero": audio.numero,
                    "numero_destino": audio.numero_destino,
                    "direccion": audio.direccion,
                    "duracion": str(int(audio.duracion_segundos)),
                },
                files={"file": (f"{audio.nombre}.wav", audio.audio_bytes, "audio/wav")},
                headers={"X-Webhook-Signature-256": signature},
            )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as e:
        return None, f"(connection error) {e}"

    return response.status_code, response.text


# --- CLI ---


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulador de grabaciones PBX (SPEC-043)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:

  # Escenario 1: Grabación simple
  python backend/tools/pbx_recording_simulator.py \\
      --scenario simple --call-id test-001 --numero "+573001234567"

  # Escenario 2: Reentrega (idempotencia)
  python backend/tools/pbx_recording_simulator.py \\
      --scenario redelivery --call-id test-001 --count 2

  # Escenario 3: Sin mapeo
  python backend/tools/pbx_recording_simulator.py \\
      --scenario unmapped --call-id test-unmapped \\
      --numero-destino "999-no-existe"

  # --count aplica a CUALQUIER escenario (no solo redelivery), p. ej. carga
  # sobre el escenario simple:
  python backend/tools/pbx_recording_simulator.py \\
      --scenario simple --call-id test-carga --count 5
""",
    )

    parser.add_argument(
        "--scenario",
        choices=["simple", "redelivery", "unmapped"],
        required=True,
        help="Escenario a ejecutar",
    )

    parser.add_argument(
        "--webhook-url",
        default=os.getenv("WEBHOOK_URL", "http://localhost:8000"),
        help="URL base del webhook (default: env WEBHOOK_URL o http://localhost:8000)",
    )

    parser.add_argument(
        "--webhook-secret",
        default=os.getenv("WEBHOOK_SECRET"),
        help="WEBHOOK_SECRET (default: env WEBHOOK_SECRET)",
    )

    parser.add_argument(
        "--call-id",
        default="simulator-test",
        help="call_id para el evento (default: simulator-test)",
    )

    parser.add_argument(
        "--numero",
        default="+573001234567",
        help="Número de origen (default: +573001234567)",
    )

    parser.add_argument(
        "--numero-destino",
        default="000-test-line",
        help="Número destino / pbx_line (default: 000-test-line)",
    )

    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help=(
            "Repeticiones del envío (aplica a CUALQUIER escenario, útil "
            "para reentrega/carga, default: 1)"
        ),
    )

    args = parser.parse_args()

    if not args.webhook_secret:
        print("ERROR: WEBHOOK_SECRET no configurado.")
        print("  Pasa --webhook-secret o establece env WEBHOOK_SECRET")
        sys.exit(1)

    if args.count < 1:
        parser.error("--count debe ser >= 1")

    print("[*] Simulador PBX Recording — SPEC-043")
    print(f"    Escenario: {args.scenario}")
    print(f"    Webhook: {args.webhook_url}")
    if args.count > 1:
        print(f"    Repeticiones: {args.count}")
    print()

    any_failure = False

    for i in range(args.count):
        prefix = f"    [{i + 1}/{args.count}] " if args.count > 1 else "    "

        if args.scenario == "simple":
            audio = _scenario_simple(args.call_id, args.numero, args.numero_destino)
            print("[*] Enviando grabación simple")
            print(f"{prefix}call_id: {audio.call_id}")
            print(f"{prefix}numero: {audio.numero}")
            print(f"{prefix}numero_destino: {audio.numero_destino}")
            print(f"{prefix}duracion: {audio.duracion_segundos}s")

            status, resp = _post_recording(args.webhook_url, audio, args.webhook_secret)
            ok = status == 202
            print(f"[{'✓' if ok else '✗'}] Status: {status if status is not None else '(connection error)'}")
            if status is None:
                print(f"    ✗ Error de conexión: {resp}")
                any_failure = True
            elif not ok:
                print(f"    Response: {resp}")
                any_failure = True
            else:
                print("[*] ✓ Grabación encolada (ACK 202)")

        elif args.scenario == "redelivery":
            if i == 0:
                print(f"[*] Reenviando grab con mismo call_id {args.count} veces (prueba idempotencia)")
            audio = _scenario_redelivery(args.call_id)
            print(f"{prefix}call_id: {audio.call_id}")
            status, resp = _post_recording(args.webhook_url, audio, args.webhook_secret)
            ok = status == 202
            print(f"        Status: {status if status is not None else '(connection error)'} {'✓' if ok else '✗'}")
            if status is None:
                print(f"        Error de conexión: {resp}")
                any_failure = True
            elif not ok:
                print(f"        Response: {resp}")
                any_failure = True

        elif args.scenario == "unmapped":
            audio = _scenario_unmapped(args.call_id, args.numero_destino)
            print("[*] Enviando grab con numero_destino sin mapeo (descarte auditado)")
            print(f"{prefix}call_id: {audio.call_id}")
            print(f"{prefix}numero_destino: {audio.numero_destino} (NO EXISTS)")
            status, resp = _post_recording(args.webhook_url, audio, args.webhook_secret)
            ok = status == 202
            print(f"[{'✓' if ok else '✗'}] Status: {status if status is not None else '(connection error)'}")
            if status is None:
                print(f"    ✗ Error de conexión: {resp}")
                any_failure = True
            elif not ok:
                print(f"    Response: {resp}")
                any_failure = True
            else:
                print("[*] ✓ Encolada pero será descartada por worker (auditado en logs)")

    print()
    print("[*] Simulación completa. Revisar logs:")
    print("    docker compose logs --tail=30 api | grep pbx_webhook")
    print("    docker compose logs --tail=30 stt_worker | grep call_id")

    sys.exit(1 if any_failure else 0)


if __name__ == "__main__":
    main()
