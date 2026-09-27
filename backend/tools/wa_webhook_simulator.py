#!/usr/bin/env python3
"""
WhatsApp Webhook Simulator — SPEC-034, SPEC-061 (SENSIBLE)

Genera y emite webhooks de WhatsApp Business Cloud API con firma HMAC-SHA256
válida, permitiendo pruebas locales del endpoint `/api/v1/whatsapp/webhook`
sin credenciales reales de Meta.

USO:
  python wa_webhook_simulator.py [--challenge] [--duplicate] [--status] [--audio] [--audio-duplicate]

Ejemplo:
  # Emitir un webhook de mensaje entrante (firma correcta)
  export WHATSAPP_APP_SECRET=test-secret-key
  export WEBHOOK_URL=http://localhost:8000/api/v1/whatsapp/webhook
  python wa_webhook_simulator.py

  # Emitir un challenge (GET)
  python wa_webhook_simulator.py --challenge

  # Emitir un mensaje duplicado (por wamid)
  python wa_webhook_simulator.py --duplicate

  # Emitir un callback de status de mensaje enviado
  python wa_webhook_simulator.py --status

  # Emitir una nota de voz (SPEC-061, F5)
  python wa_webhook_simulator.py --audio

  # Emitir una nota de voz duplicada (prueba idempotencia)
  python wa_webhook_simulator.py --audio-duplicate

LIMITACIÓN IMPORTANTE (R-41, RNF-41):
  Este simulador ejercita el CONTRATO DE INGESTA (firma HMAC válida, parseo
  de payload, idempotencia por wamid, creación del Message(tipo="audio"))
  contra un servidor corriendo localmente. El `media_id` que emite es un
  PLACEHOLDER FICTICIO — la descarga REAL desde `graph.facebook.com` (paso
  posterior, `app.integrations.whatsapp.media_client.download_and_store_voice_note`,
  SPEC-054) fallará contra un servidor real de Meta porque ese `media_id` no
  existe en la realidad.

  Para demostrar el ciclo COMPLETO (descarga + transcripción real de una nota
  de voz) se requiere:
    (a) Credenciales reales de Meta con un `media_id` real que apunta a un
        audio verdadero en la Nube (fuera del alcance "sin egress" de este
        simulador), o
    (b) Un servidor de desarrollo con un doble/mock del cliente HTTP de
        descarga inyectado (exactamente lo que la suite de `pytest` ya hace
        en `backend/tests/test_whatsapp_inbound_worker.py`, que SÍ valida el
        ciclo e2e en local sin egress real, con un cliente HTTP falso).

  Este simulador es apropiado para validar: estructura del webhook,
  idempotencia por wamid, límite de duración, contrato del `destino` de
  `stt:jobs` (comportamiento local antes de la descarga). No es apropiado
  para validar la descarga real desde Meta — ese paso requiere credenciales
  reales o un mock en los tests automatizados.

CHECKPOINT SENSIBLE (C3): app_secret se lee de WHATSAPP_APP_SECRET (env).
No hay secretos concretos en este archivo; solo placeholders/env.
"""

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime
from typing import Optional
from uuid import uuid4

import httpx


def _compute_signature(app_secret: str, raw_body: str) -> str:
    """Computa la firma HMAC-SHA256 exacta como espera webhook.py.

    Args:
        app_secret: Secreto de la aplicación (env WHATSAPP_APP_SECRET)
        raw_body: Payload JSON como string (bytes raw)

    Returns:
        Cadena de firma: 'sha256=<hexdigest>'
    """
    signature_hex = hmac.new(
        app_secret.encode("utf-8"),
        raw_body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={signature_hex}"


def _get_webhook_url() -> str:
    """Lee URL del webhook desde env o retorna default local."""
    return os.getenv("WEBHOOK_URL", "http://localhost:8000/api/v1/whatsapp/webhook")


def _get_app_secret() -> str:
    """Lee app_secret desde env. Falla si no está definido (C3)."""
    secret = os.getenv("WHATSAPP_APP_SECRET")
    if not secret:
        print("ERROR: WHATSAPP_APP_SECRET no definido en env. Asigna un valor de prueba:")
        print("  export WHATSAPP_APP_SECRET=$(openssl rand -hex 32)")
        sys.exit(1)
    return secret


def emit_webhook_message(
    webhook_url: str,
    app_secret: str,
    phone_number_id: str = "1234567890",
    wamid: Optional[str] = None,
    text_content: str = "Hola, ¿cuál es el estado de mi pedido?",
    from_phone: str = "+34600123456",
) -> httpx.Response:
    """Emite un webhook de mensaje entrante con firma válida.

    Args:
        webhook_url: URL del webhook (ej. http://localhost:8000/api/v1/whatsapp/webhook)
        app_secret: Secreto de la app (para calcular firma HMAC)
        phone_number_id: ID del número de WhatsApp receptor (default: placeholder)
        wamid: ID único del mensaje (genera uno nuevo si es None)
        text_content: Contenido del mensaje
        from_phone: Número del remitente

    Returns:
        Response de httpx tras POST
    """
    wamid = wamid or str(uuid4())

    # Payload exacto que emite Meta (estructura de Graph API)
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID_PLACEHOLDER",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "34600999888",
                                "phone_number_id": phone_number_id,
                            },
                            "messages": [
                                {
                                    "from": from_phone,
                                    "id": wamid,
                                    "timestamp": str(int(time.time())),
                                    "type": "text",
                                    "text": {
                                        "body": text_content,
                                    },
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
                "timestamp": int(time.time()),
            }
        ],
    }

    # Serializar sin espacios (JSON compacto, como Meta lo envía)
    raw_body = json.dumps(payload, separators=(",", ":"))

    # Computar firma HMAC-SHA256
    signature = _compute_signature(app_secret, raw_body)

    print(f"\n📨 Emitiendo webhook de mensaje entrante...")
    print(f"  URL: {webhook_url}")
    print(f"  wamid: {wamid}")
    print(f"  phone_number_id: {phone_number_id}")
    print(f"  from_phone: {from_phone}")
    print(f"  content: {text_content[:60]}...")
    print(f"  X-Hub-Signature-256: {signature[:20]}...")

    # POST al webhook
    try:
        resp = httpx.post(
            webhook_url,
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
            },
            timeout=10,
        )
        print(f"  Respuesta: {resp.status_code}")
        if resp.status_code != 200:
            print(f"  Body: {resp.text[:200]}")
        return resp
    except Exception as e:
        print(f"  ✗ Error: {e}")
        raise


def emit_webhook_duplicate(
    webhook_url: str,
    app_secret: str,
    wamid: str,
    phone_number_id: str = "1234567890",
) -> httpx.Response:
    """Emite un webhook duplicado (mismo wamid) para probar idempotencia (SPEC-027/ADR-007).

    Args:
        webhook_url: URL del webhook
        app_secret: Secreto de la app
        wamid: ID del mensaje a duplicar
        phone_number_id: ID del número

    Returns:
        Response de httpx tras POST
    """
    print(f"\n📨 Emitiendo webhook DUPLICADO (prueba idempotencia)...")
    print(f"  wamid: {wamid} (idéntico al anterior)")

    return emit_webhook_message(
        webhook_url,
        app_secret,
        phone_number_id=phone_number_id,
        wamid=wamid,
        text_content="[DUPLICADO] Este mensaje ya fue procesado",
    )


def emit_webhook_status(
    webhook_url: str,
    app_secret: str,
    wamid: str,
    status: str = "delivered",
    phone_number_id: str = "1234567890",
) -> httpx.Response:
    """Emite un webhook de cambio de status (SPEC-030).

    Simula Meta notificando que un mensaje enviado cambió de status
    (sent → delivered → read).

    Args:
        webhook_url: URL del webhook
        app_secret: Secreto de la app
        wamid: ID del mensaje enviado
        status: Estado ('sent', 'delivered', 'read', 'failed')
        phone_number_id: ID del número

    Returns:
        Response de httpx tras POST
    """
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID_PLACEHOLDER",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "34600999888",
                                "phone_number_id": phone_number_id,
                            },
                            "statuses": [
                                {
                                    "id": wamid,
                                    "status": status,
                                    "timestamp": str(int(time.time())),
                                    "recipient_id": "+34600123456",
                                }
                            ],
                        },
                        "field": "message_status",
                    }
                ],
                "timestamp": int(time.time()),
            }
        ],
    }

    raw_body = json.dumps(payload, separators=(",", ":"))
    signature = _compute_signature(app_secret, raw_body)

    print(f"\n📨 Emitiendo webhook de STATUS...")
    print(f"  URL: {webhook_url}")
    print(f"  wamid: {wamid}")
    print(f"  status: {status}")
    print(f"  X-Hub-Signature-256: {signature[:20]}...")

    try:
        resp = httpx.post(
            webhook_url,
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
            },
            timeout=10,
        )
        print(f"  Respuesta: {resp.status_code}")
        return resp
    except Exception as e:
        print(f"  ✗ Error: {e}")
        raise


def emit_webhook_challenge(
    webhook_url: str,
    verify_token: str = "test-verify-token",
) -> httpx.Response:
    """Emite un GET de challenge (suscripción del webhook a Meta).

    Este es el challenge que Meta emite cuando configuras el webhook
    en Meta's webhook setup page. El endpoint debe devolver el
    `hub.challenge` en texto plano si el token coincide.

    Args:
        webhook_url: URL del webhook
        verify_token: Token de verificación

    Returns:
        Response de httpx tras GET
    """
    challenge_token = str(uuid4())

    print(f"\n📨 Emitiendo GET de challenge (suscripción)...")
    print(f"  URL: {webhook_url}")
    print(f"  hub.mode: subscribe")
    print(f"  hub.verify_token: {verify_token}")
    print(f"  hub.challenge: {challenge_token}")

    try:
        resp = httpx.get(
            webhook_url,
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": verify_token,
                "hub.challenge": challenge_token,
            },
            timeout=10,
        )
        print(f"  Respuesta: {resp.status_code}")
        if resp.status_code == 200:
            print(f"  ✓ Challenge OK (body: {resp.text})")
        else:
            print(f"  ✗ Challenge RECHAZADO (status: {resp.status_code})")
        return resp
    except Exception as e:
        print(f"  ✗ Error: {e}")
        raise


def emit_webhook_audio_message(
    webhook_url: str,
    app_secret: str,
    *,
    phone_number_id: str = "1234567890",
    wamid: Optional[str] = None,
    media_id: Optional[str] = None,
    mime_type: str = "audio/ogg; codecs=opus",
    duration_seconds: Optional[int] = None,
    from_phone: str = "+34600123456",
) -> httpx.Response:
    """Emite un webhook de nota de voz (mensaje con type=="audio") con firma válida.

    LIMITACIÓN (R-41, RNF-41, SPEC-061): el `media_id` es un PLACEHOLDER
    ficticio. La descarga REAL desde `graph.facebook.com` (posterior,
    `media_client.py`, SPEC-054) fallará contra un servidor real de Meta
    porque ese `media_id` no existe. Ver docstring del módulo arriba para
    detalles.

    NOTA de R-68 (duración desconocida): Meta HOY NUNCA envía duración en el
    payload real (`message["audio"]` NO tiene un campo `duration` en la
    documentación estable de Meta). El parámetro `duration_seconds` de este
    simulador existe SOLO para permitir testing del mecanismo de límite de
    duración (`VOICE_NOTE_MAX_DURATION_SECONDS`, RF-04/RF-05 SPEC-055) en
    local, inyectando una duración ficticia en el payload. En producción real,
    Meta NO envía esta duración y `event.audio_duracion_seg` será siempre
    `None` en `inbound_parser.py` — el límite se aplica en `stt_worker`
    después de decodificar el audio (SPEC-056), no en la ingesta.

    Args:
        webhook_url: URL del webhook (ej. http://localhost:8000/api/v1/whatsapp/webhook)
        app_secret: Secreto de la app (para calcular firma HMAC)
        phone_number_id: ID del número de WhatsApp receptor (default: placeholder)
        wamid: ID único del mensaje (genera uno nuevo si es None)
        media_id: ID de media de Meta (placeholder ficticio; genera uno si es None)
        mime_type: MIME type del audio (default: OGG/Opus, formato de Meta real)
        duration_seconds: Duración en segundos (SOLO para testing de límites;
                         Meta no lo envía en producción real)
        from_phone: Número del remitente

    Returns:
        Response de httpx tras POST
    """
    wamid = wamid or str(uuid4())
    media_id = media_id or str(uuid4())

    # Payload exacto que emite Meta para una nota de voz
    # (structure de `type=="audio"`, Graph API WhatsApp Cloud API)
    audio_payload = {
        "id": media_id,
        "mime_type": mime_type,
    }

    # R-68: Si `duration_seconds` es proporcionado (testing de límites),
    # inclúyelo en el payload. En producción real, Meta NO lo envía.
    if duration_seconds is not None:
        audio_payload["duration"] = duration_seconds

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID_PLACEHOLDER",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "34600999888",
                                "phone_number_id": phone_number_id,
                            },
                            "messages": [
                                {
                                    "from": from_phone,
                                    "id": wamid,
                                    "timestamp": str(int(time.time())),
                                    "type": "audio",
                                    "audio": audio_payload,
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
                "timestamp": int(time.time()),
            }
        ],
    }

    # Serializar sin espacios (JSON compacto, como Meta lo envía)
    raw_body = json.dumps(payload, separators=(",", ":"))

    # Computar firma HMAC-SHA256
    signature = _compute_signature(app_secret, raw_body)

    print(f"\n📨 Emitiendo webhook de nota de voz...")
    print(f"  URL: {webhook_url}")
    print(f"  wamid: {wamid}")
    print(f"  media_id: {media_id}")
    print(f"  mime_type: {mime_type}")
    if duration_seconds is not None:
        print(f"  duration_seconds: {duration_seconds} (ficticio, testing de límites)")
    print(f"  phone_number_id: {phone_number_id}")
    print(f"  from_phone: {from_phone}")
    print(f"  X-Hub-Signature-256: {signature[:20]}...")

    # POST al webhook
    try:
        resp = httpx.post(
            webhook_url,
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
            },
            timeout=10,
        )
        print(f"  Respuesta: {resp.status_code}")
        if resp.status_code != 200:
            print(f"  Body: {resp.text[:200]}")
        return resp
    except Exception as e:
        print(f"  ✗ Error: {e}")
        raise


def emit_webhook_audio_duplicate(
    webhook_url: str,
    app_secret: str,
    wamid: str,
    phone_number_id: str = "1234567890",
    media_id: Optional[str] = None,
) -> httpx.Response:
    """Emite un webhook de nota de voz duplicado (mismo wamid) para probar
    idempotencia (SPEC-027/ADR-007, sin regresión al audio).

    Args:
        webhook_url: URL del webhook
        app_secret: Secreto de la app
        wamid: ID del mensaje a duplicar
        phone_number_id: ID del número
        media_id: ID de media (placeholder ficticio; genera uno si es None)

    Returns:
        Response de httpx tras POST
    """
    media_id = media_id or str(uuid4())

    print(f"\n📨 Emitiendo webhook de nota de voz DUPLICADO (prueba idempotencia)...")
    print(f"  wamid: {wamid} (idéntico al anterior)")
    print(f"  media_id: {media_id} (distinto, pero mismo wamid)")

    return emit_webhook_audio_message(
        webhook_url,
        app_secret,
        phone_number_id=phone_number_id,
        wamid=wamid,
        media_id=media_id,
    )


def main():
    """Punto de entrada: analiza flags y emite webhook(s) apropiado(s)."""
    app_secret = _get_app_secret()
    webhook_url = _get_webhook_url()

    print(f"\n{'='*70}")
    print(f"WhatsApp Webhook Simulator — SPEC-034, SPEC-061 (SENSIBLE)")
    print(f"{'='*70}")
    print(f"\nConfiguración:")
    print(f"  Webhook URL: {webhook_url}")
    print(f"  App Secret: {app_secret[:20]}... (desde WHATSAPP_APP_SECRET env)")

    if len(sys.argv) > 1 and sys.argv[1] == "--challenge":
        # Emitir solo el challenge (GET)
        resp = emit_webhook_challenge(webhook_url)
        sys.exit(0 if resp.status_code == 200 else 1)

    elif len(sys.argv) > 1 and sys.argv[1] == "--duplicate":
        # Emitir mensaje base + duplicado para probar idempotencia
        print(f"\n[PASO 1] Emitiendo mensaje inicial...")
        wamid = str(uuid4())
        resp1 = emit_webhook_message(webhook_url, app_secret, wamid=wamid)

        if resp1.status_code == 200:
            time.sleep(1)
            print(f"\n[PASO 2] Emitiendo DUPLICADO del mismo wamid...")
            resp2 = emit_webhook_duplicate(webhook_url, app_secret, wamid=wamid)

            if resp2.status_code == 200:
                print(f"\n✓ Ambos webhooks aceptados (200).")
                print(f"  Verificar SPEC-027: debe haber solo 1 mensaje en BD (dedup por wamid)")
                sys.exit(0)
            else:
                print(f"\n✗ Duplicado rechazado (status: {resp2.status_code})")
                sys.exit(1)
        else:
            print(f"\n✗ Inicial rechazado (status: {resp1.status_code})")
            sys.exit(1)

    elif len(sys.argv) > 1 and sys.argv[1] == "--status":
        # Emitir mensaje + sequence de statuses
        print(f"\n[PASO 1] Emitiendo mensaje saliente (que será enviado)...")
        # En la realidad, el usuario aprueba un draft y se encola en wa:outbound
        # Para este simulador, fingimos que el mensaje fue enviado y ahora
        # recibimos callbacks de status.
        wamid = str(uuid4())

        for status in ["sent", "delivered", "read"]:
            resp = emit_webhook_status(webhook_url, app_secret, wamid, status=status)
            if resp.status_code != 200:
                print(f"\n✗ Status '{status}' rechazado (status: {resp.status_code})")
                sys.exit(1)
            time.sleep(0.5)

        print(f"\n✓ Sequence de statuses completada (sent → delivered → read)")
        print(f"  Verificar SPEC-030: conciliación idempotente por wamid")
        sys.exit(0)

    elif len(sys.argv) > 1 and sys.argv[1] == "--audio":
        # Emitir una nota de voz simple (SPEC-061)
        wamid = str(uuid4())
        resp = emit_webhook_audio_message(webhook_url, app_secret, wamid=wamid)

        if resp.status_code == 200:
            print(f"\n✓ Webhook de nota de voz ACEPTADO (200 OK)")
            print(f"  Verificar SPEC-055: Message(tipo='audio') encolado")
            print(f"  wamid: {wamid}")
            print(
                "  Verificar contrato 'destino' de stt:jobs = "
                "'message:<id del Message creado>' (id generado por el "
                "backend, no por este simulador)"
            )
            print(f"  Limitación: media_id es ficticio (no descargable desde Meta real)")
        elif resp.status_code == 401:
            print(f"\n✗ Webhook RECHAZADO (401 Unauthorized)")
            print(f"  → Firma HMAC no coincide (app_secret incorrecto?)")
        else:
            print(f"\n✗ Error inesperado: {resp.status_code}")
            print(f"  {resp.text[:200]}")

        sys.exit(0 if resp.status_code == 200 else 1)

    elif len(sys.argv) > 1 and sys.argv[1] == "--audio-duplicate":
        # Emitir nota de voz + duplicado para probar idempotencia
        print(f"\n[PASO 1] Emitiendo nota de voz inicial...")
        wamid = str(uuid4())
        resp1 = emit_webhook_audio_message(webhook_url, app_secret, wamid=wamid)

        if resp1.status_code == 200:
            time.sleep(1)
            print(f"\n[PASO 2] Emitiendo DUPLICADO de la misma nota (mismo wamid)...")
            resp2 = emit_webhook_audio_duplicate(
                webhook_url, app_secret, wamid=wamid
            )

            if resp2.status_code == 200:
                print(f"\n✓ Ambos webhooks de audio aceptados (200).")
                print(f"  Verificar SPEC-055/ADR-007: debe haber solo 1 Message en BD (dedup por wamid)")
                print(f"  Verificar idempotencia: stt:jobs encolado solo una vez")
                sys.exit(0)
            else:
                print(f"\n✗ Duplicado rechazado (status: {resp2.status_code})")
                sys.exit(1)
        else:
            print(f"\n✗ Inicial rechazado (status: {resp1.status_code})")
            sys.exit(1)

    else:
        # Default: emitir un mensaje simple con firma válida
        wamid = str(uuid4())
        resp = emit_webhook_message(webhook_url, app_secret, wamid=wamid)

        if resp.status_code == 200:
            print(f"\n✓ Webhook ACEPTADO (200 OK)")
            print(f"  Verificar que el mensaje se encoló en Redis: wa:inbound")
        elif resp.status_code == 401:
            print(f"\n✗ Webhook RECHAZADO (401 Unauthorized)")
            print(f"  → Firma HMAC no coincide (app_secret incorrecto?)")
        else:
            print(f"\n✗ Error inesperado: {resp.status_code}")
            print(f"  {resp.text[:200]}")

        sys.exit(0 if resp.status_code == 200 else 1)


if __name__ == "__main__":
    main()
