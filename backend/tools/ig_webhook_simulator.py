#!/usr/bin/env python3
"""
Instagram Webhook Simulator — SPEC-091 (SENSIBLE), espejo EXACTO de
`wa_webhook_simulator.py` (SPEC-034), adaptado al formato de la Instagram
Messaging API (`object:"instagram"`, `entry[].messaging[]`, clave `mid` en
vez de `wamid`).

Genera y emite webhooks de Instagram DM con firma HMAC-SHA256 válida,
permitiendo pruebas locales del endpoint `/api/v1/instagram/webhook` (SPEC-086)
sin credenciales reales de Meta.

USO:
  python ig_webhook_simulator.py [--challenge] [--duplicate] [--attachment] [--bad-signature]

Ejemplo:
  # Emitir un webhook de mensaje de texto entrante (firma correcta)
  export INSTAGRAM_APP_SECRET=test-secret-key
  export WEBHOOK_URL=http://localhost:8000/api/v1/instagram/webhook
  python ig_webhook_simulator.py

  # Emitir un challenge (GET)
  python ig_webhook_simulator.py --challenge

  # Emitir un challenge con token INVÁLIDO (debe rechazar 403)
  python ig_webhook_simulator.py --challenge --bad-token

  # Emitir un mensaje duplicado (por mid, prueba idempotencia)
  python ig_webhook_simulator.py --duplicate

  # Emitir un mensaje con attachments (prueba persistencia de media_url, SPEC-088)
  python ig_webhook_simulator.py --attachment

  # Emitir un POST con firma inválida/ausente (debe rechazar 401, sin encolar)
  python ig_webhook_simulator.py --bad-signature
  python ig_webhook_simulator.py --no-signature

LIMITACIÓN IMPORTANTE (R-110, bloqueo de Meta App Review — ver SPEC-091 y
RUNBOOK_INSTAGRAM.md):

  Este simulador ejercita el CONTRATO DE INGESTA (firma HMAC válida, parseo
  del payload `object:"instagram"`, idempotencia por `mid`, enrutado de
  tenant por `instagram_account_id`, persistencia de `media_url` de
  attachments) contra un servidor corriendo LOCALMENTE, con placeholders
  ficticios. NO sustituye una prueba E2E con usuarios reales de Instagram:
  la Instagram Messaging API exige Meta App Review (permisos
  `instagram_manage_messages`, `instagram_basic`, `pages_messaging`) +
  cuenta IG Business vinculada + tokens reales. Sin App Review, Meta SOLO
  permite intercambiar mensajes con cuentas de rol de prueba
  (admin/tester/developer) de la propia app — nunca con usuarios reales.
  Ese paso queda DIFERIDO al Lead (ver runbook).

CHECKPOINT SENSIBLE (C3): app_secret se lee de INSTAGRAM_APP_SECRET (env).
No hay secretos concretos en este archivo; solo placeholders/env.
"""

import hashlib
import hmac
import json
import os
import sys
import time
from typing import Optional
from uuid import uuid4

import httpx


def _compute_signature(app_secret: str, raw_body: str) -> str:
    """Computa la firma HMAC-SHA256 exacta como espera `webhook.py` de
    Instagram (idéntico mecanismo al de WhatsApp: HMAC-SHA256 sobre el RAW
    body)."""
    signature_hex = hmac.new(
        app_secret.encode("utf-8"),
        raw_body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={signature_hex}"


def _get_webhook_url() -> str:
    """Lee URL del webhook desde env o retorna default local."""
    return os.getenv("WEBHOOK_URL", "http://localhost:8000/api/v1/instagram/webhook")


def _get_app_secret() -> str:
    """Lee app_secret desde env. Falla si no está definido (C3)."""
    secret = os.getenv("INSTAGRAM_APP_SECRET")
    if not secret:
        print("ERROR: INSTAGRAM_APP_SECRET no definido en env. Asigna un valor de prueba:")
        print("  export INSTAGRAM_APP_SECRET=$(openssl rand -hex 32)")
        sys.exit(1)
    return secret


def _build_message_payload(
    *,
    instagram_account_id: str,
    mid: str,
    sender_id: str,
    texto: Optional[str],
    attachments: Optional[list[dict]],
) -> dict:
    """Construye el payload crudo exacto de la Instagram Messaging API
    (`object:"instagram"`, `entry[].messaging[]`, espejo de
    `inbound_parser.py` — ver su docstring para la forma documentada)."""
    message: dict = {"mid": mid}
    if texto is not None:
        message["text"] = texto
    if attachments is not None:
        message["attachments"] = attachments

    return {
        "object": "instagram",
        "entry": [
            {
                "id": instagram_account_id,
                "time": int(time.time()),
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": instagram_account_id},
                        "timestamp": int(time.time()),
                        "message": message,
                    }
                ],
            }
        ],
    }


def emit_webhook_message(
    webhook_url: str,
    app_secret: str,
    *,
    instagram_account_id: str = "IG_ACCOUNT_ID_PLACEHOLDER",
    mid: Optional[str] = None,
    texto: str = "Hola, ¿tienen disponible el producto en talla M?",
    sender_id: str = "ig-sender-9988776655",
    attachments: Optional[list[dict]] = None,
) -> httpx.Response:
    """Emite un webhook de mensaje entrante (texto o con adjuntos) con firma
    HMAC-SHA256 válida.

    Args:
        webhook_url: URL del webhook (ej. http://localhost:8000/api/v1/instagram/webhook)
        app_secret: Secreto de la app (para calcular firma HMAC)
        instagram_account_id: `recipient.id` — cuenta IG Business receptora (placeholder)
        mid: id único del mensaje (genera uno nuevo si es None)
        texto: contenido del mensaje (None si solo attachments)
        sender_id: identificador del usuario de Instagram remitente
        attachments: lista opcional de `{"type": ..., "payload": {"url": ...}}`

    Returns:
        Response de httpx tras POST
    """
    mid = mid or f"mid.{uuid4().hex}"

    payload = _build_message_payload(
        instagram_account_id=instagram_account_id,
        mid=mid,
        sender_id=sender_id,
        texto=texto,
        attachments=attachments,
    )

    # Serializar sin espacios (JSON compacto, como Meta lo envía)
    raw_body = json.dumps(payload, separators=(",", ":"))
    signature = _compute_signature(app_secret, raw_body)

    print(f"\n📨 Emitiendo webhook de Instagram DM (mensaje entrante)...")
    print(f"  URL: {webhook_url}")
    print(f"  mid: {mid}")
    print(f"  instagram_account_id (recipient): {instagram_account_id}")
    print(f"  sender_id: {sender_id}")
    if texto:
        print(f"  texto: {texto[:60]}")
    if attachments:
        print(f"  attachments: {attachments}")
    print(f"  X-Hub-Signature-256: {signature[:28]}...")

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
    mid: str,
    *,
    instagram_account_id: str = "IG_ACCOUNT_ID_PLACEHOLDER",
    sender_id: str = "ig-sender-9988776655",
) -> httpx.Response:
    """Emite un webhook duplicado (mismo `mid`) para probar idempotencia
    (espejo de `wamid` en WhatsApp, SPEC-087/ADR-007)."""
    print(f"\n📨 Emitiendo webhook DUPLICADO (prueba idempotencia por mid)...")
    print(f"  mid: {mid} (idéntico al anterior)")

    return emit_webhook_message(
        webhook_url,
        app_secret,
        instagram_account_id=instagram_account_id,
        mid=mid,
        sender_id=sender_id,
        texto="[DUPLICADO] Este mensaje ya fue procesado",
    )


def emit_webhook_challenge(
    webhook_url: str,
    verify_token: str = "test-verify-token",
) -> httpx.Response:
    """Emite un GET de challenge (suscripción del webhook a Meta).

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
            assert resp.text == challenge_token, "el cuerpo debe ser EXACTO el challenge"
        else:
            print(f"  ✗ Challenge RECHAZADO (status: {resp.status_code})")
        return resp
    except Exception as e:
        print(f"  ✗ Error: {e}")
        raise


def emit_webhook_bad_signature(
    webhook_url: str,
    *,
    signature: Optional[str] = "sha256=" + "0" * 64,
) -> httpx.Response:
    """Emite un POST con firma inválida (o ausente si `signature=None`) —
    debe rechazarse con 401 SIN encolar (criterio de aceptación SPEC-091)."""
    raw_body = json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "IG_ACCOUNT_ID_PLACEHOLDER",
                    "messaging": [
                        {
                            "sender": {"id": "ig-sender-badsig"},
                            "recipient": {"id": "IG_ACCOUNT_ID_PLACEHOLDER"},
                            "message": {"mid": f"mid.{uuid4().hex}", "text": "no debería colarse"},
                        }
                    ],
                }
            ],
        },
        separators=(",", ":"),
    )

    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
        print(f"\n📨 Emitiendo POST con firma INVÁLIDA (debe rechazarse)...")
        print(f"  X-Hub-Signature-256: {signature[:28]}... (incorrecta a propósito)")
    else:
        print(f"\n📨 Emitiendo POST SIN cabecera de firma (debe rechazarse)...")

    try:
        resp = httpx.post(webhook_url, content=raw_body, headers=headers, timeout=10)
        print(f"  Respuesta: {resp.status_code}")
        return resp
    except Exception as e:
        print(f"  ✗ Error: {e}")
        raise


def main():
    """Punto de entrada: analiza flags y emite webhook(s) apropiado(s)."""
    webhook_url = _get_webhook_url()

    print(f"\n{'='*70}")
    print(f"Instagram Webhook Simulator — SPEC-091 (SENSIBLE)")
    print(f"{'='*70}")
    print(f"\nConfiguración:")
    print(f"  Webhook URL: {webhook_url}")

    args = sys.argv[1:]

    if "--challenge" in args:
        app_secret = None  # challenge no requiere app_secret
        if "--bad-token" in args:
            resp = emit_webhook_challenge(webhook_url, verify_token="token-incorrecto-a-proposito")
            sys.exit(0 if resp.status_code == 403 else 1)
        resp = emit_webhook_challenge(webhook_url)
        sys.exit(0 if resp.status_code == 200 else 1)

    elif "--bad-signature" in args:
        resp = emit_webhook_bad_signature(webhook_url, signature="sha256=" + "0" * 64)
        if resp.status_code == 401:
            print(f"\n✓ Correctamente RECHAZADO (401) — firma inválida detectada")
            sys.exit(0)
        else:
            print(f"\n✗ FALLO: se esperaba 401, se obtuvo {resp.status_code}")
            sys.exit(1)

    elif "--no-signature" in args:
        resp = emit_webhook_bad_signature(webhook_url, signature=None)
        if resp.status_code == 401:
            print(f"\n✓ Correctamente RECHAZADO (401) — firma ausente detectada")
            sys.exit(0)
        else:
            print(f"\n✗ FALLO: se esperaba 401, se obtuvo {resp.status_code}")
            sys.exit(1)

    elif "--duplicate" in args:
        app_secret = _get_app_secret()
        print(f"  App Secret: {app_secret[:20]}... (desde INSTAGRAM_APP_SECRET env)")
        print(f"\n[PASO 1] Emitiendo mensaje inicial...")
        mid = f"mid.{uuid4().hex}"
        resp1 = emit_webhook_message(webhook_url, app_secret, mid=mid)

        if resp1.status_code == 200:
            time.sleep(1)
            print(f"\n[PASO 2] Emitiendo DUPLICADO del mismo mid...")
            resp2 = emit_webhook_duplicate(webhook_url, app_secret, mid)

            if resp2.status_code == 200:
                print(f"\n✓ Ambos webhooks aceptados (200).")
                print(f"  Verificar SPEC-087: debe haber solo 1 Message en BD (dedup por mid)")
                sys.exit(0)
            else:
                print(f"\n✗ Duplicado rechazado (status: {resp2.status_code})")
                sys.exit(1)
        else:
            print(f"\n✗ Inicial rechazado (status: {resp1.status_code})")
            sys.exit(1)

    elif "--attachment" in args:
        app_secret = _get_app_secret()
        print(f"  App Secret: {app_secret[:20]}... (desde INSTAGRAM_APP_SECRET env)")
        mid = f"mid.{uuid4().hex}"
        cdn_url = (
            "https://lookaside.fbsbx.com/ig_messaging_cdn/"
            f"?asset_id={uuid4().hex[:12]}&signature=simulado-{uuid4().hex[:16]}"
        )
        resp = emit_webhook_message(
            webhook_url,
            app_secret,
            mid=mid,
            texto=None,
            attachments=[{"type": "image", "payload": {"url": cdn_url}}],
        )

        if resp.status_code == 200:
            print(f"\n✓ Webhook de adjunto ACEPTADO (200 OK)")
            print(f"  Verificar SPEC-088: messages.media_url == '{cdn_url}'")
            print(f"  Verificar SPEC-088: messages.media_type == 'image'")
            print(
                "  LIMITACIÓN: la URL es un PLACEHOLDER ficticio del CDN de Meta "
                "(lookaside.fbsbx.com con forma válida), NO un recurso real "
                "descargable — SPEC-088 (F3, rediseñada) solo persiste la URL, "
                "nunca descarga el binario, así que esto basta para validar el "
                "contrato completo sin egress."
            )
        else:
            print(f"\n✗ Error inesperado: {resp.status_code}")
            print(f"  {resp.text[:200]}")

        sys.exit(0 if resp.status_code == 200 else 1)

    else:
        # Default: emitir un mensaje de texto simple con firma válida
        app_secret = _get_app_secret()
        print(f"  App Secret: {app_secret[:20]}... (desde INSTAGRAM_APP_SECRET env)")
        mid = f"mid.{uuid4().hex}"
        resp = emit_webhook_message(webhook_url, app_secret, mid=mid)

        if resp.status_code == 200:
            print(f"\n✓ Webhook ACEPTADO (200 OK)")
            print(f"  Verificar que el evento se encoló en Redis: ig:inbound")
        elif resp.status_code == 401:
            print(f"\n✗ Webhook RECHAZADO (401 Unauthorized)")
            print(f"  → Firma HMAC no coincide (app_secret incorrecto?)")
        else:
            print(f"\n✗ Error inesperado: {resp.status_code}")
            print(f"  {resp.text[:200]}")

        sys.exit(0 if resp.status_code == 200 else 1)


if __name__ == "__main__":
    main()
