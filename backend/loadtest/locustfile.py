"""Arnés de carga/latencia — SPEC-022 (RNF-04, coordinado con THOR) +
SPEC-033 (webhook WhatsApp, RNF-02: p95 ACK <= 500 ms).

Mide los objetivos de rendimiento contra un backend REAL (API + Postgres +
Redis + Ollama vivos, p.ej. `docker compose up`, o el entorno de CI con
services):

  1. **p95 API no-IA <= 200 ms** (SPEC-022): `login` + lecturas de
     `/api/v1/contacts` (CRUD que NO llama al LLM).
  2. **p95 RAG <= 6 s (GPU)** / degradación CPU documentada (SPEC-022):
     `POST /api/v1/rag/draft`, que sí atraviesa el LLM local (Ollama).
  3. **p95 ACK del webhook <= 500 ms** (SPEC-026/SPEC-033): `POST
     /api/v1/whatsapp/webhook` con firma HMAC-SHA256 VÁLIDA (misma firma que
     calcula Meta, `X-Hub-Signature-256` sobre el RAW body) — el ACK debe
     ser rápido porque el webhook solo valida+encola en Redis (SPEC-026); el
     procesamiento real ocurre async en `whatsapp_inbound_worker` (SPEC-027)
     y NO cuenta para este umbral.

No corre contra ninguna API de inferencia externa de terceros: `HOST` debe
apuntar SIEMPRE al backend interno (por defecto `http://localhost:8000`,
o el servicio `api` de `docker-compose.yml` en CI). Este arnés NO hace
ninguna llamada de red fuera del propio backend bajo prueba (verificado por
`check-externos-backend.sh`, que también escanea `loadtest/`).

Uso local (requiere backend real levantado, fuera de este sandbox):

    locust -f backend/loadtest/locustfile.py --host http://localhost:8000 \
        --headless -u 20 -r 5 -t 2m --csv=loadtest_report

Uso local SOLO para el escenario de webhook (SPEC-033, RNF-02):

    LOADTEST_WHATSAPP_APP_SECRET=<mismo WHATSAPP_APP_SECRET del backend> \
    locust -f backend/loadtest/locustfile.py --host http://localhost:8000 \
        --headless -u 20 -r 5 -t 1m --csv=loadtest_webhook_report \
        WhatsAppWebhookUser

Luego revisar `loadtest_report_stats.csv`/`loadtest_webhook_report_stats.csv`:
columna `95%` de la fila `POST /api/v1/rag/draft` debe ser <= 6000 (ms) en
GPU; `GET /api/v1/contacts` <= 200 (ms); `POST /api/v1/whatsapp/webhook`
(firma válida) <= 500 (ms).

Variables de entorno (todas opcionales, con defaults seguros para CI):
  - LOADTEST_TENANT_SLUG / LOADTEST_EMAIL / LOADTEST_PASSWORD: credenciales
    de un usuario de prueba ya sembrado (ver `loadtest/seed_loadtest_user.py`
    o el fixture de CI). Si el login falla, el usuario Locust se detiene
    (no genera tráfico "de mentira" contra endpoints protegidos).
  - LOADTEST_RAG_QUERY: pregunta usada contra `/rag/draft` (debe tener
    contexto ingerido previamente para no recibir 404 por falta de citas).
  - LOADTEST_WHATSAPP_APP_SECRET: DEBE coincidir con el `WHATSAPP_APP_SECRET`
    real del backend bajo prueba (mismo secreto de CI/entorno, NUNCA un
    valor de producción — C3). Sin él, `WhatsAppWebhookUser` no puede firmar
    y se detiene (no genera tráfico "de mentira" contra un endpoint que
    exige HMAC válido, mismo criterio que el login del resto de usuarios).
  - LOADTEST_WHATSAPP_PHONE_NUMBER_ID: `phone_number_id` a usar en el
    payload simulado (debe existir en `whatsapp_accounts` y estar mapeado a
    un tenant real para que el worker async no descarte el evento; el ACK
    del webhook en sí no depende de esto, pero mantiene el payload
    realista).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid

from locust import HttpUser, between, task

TENANT_SLUG = os.getenv("LOADTEST_TENANT_SLUG", "tenant-loadtest")
EMAIL = os.getenv("LOADTEST_EMAIL", "loadtest@tenant-loadtest.test")
PASSWORD = os.getenv("LOADTEST_PASSWORD", "LoadTest#2026")
RAG_QUERY = os.getenv("LOADTEST_RAG_QUERY", "¿Cuál es la política de garantía?")

WHATSAPP_APP_SECRET = os.getenv("LOADTEST_WHATSAPP_APP_SECRET")
WHATSAPP_PHONE_NUMBER_ID = os.getenv(
    "LOADTEST_WHATSAPP_PHONE_NUMBER_ID", "000000000000001"
)
WEBHOOK_PATH = "/api/v1/whatsapp/webhook"


class OmniCoreApiUser(HttpUser):
    """Simula un agente autenticado consultando la API core y pidiendo
    borradores RAG. Cada usuario Locust hace login UNA vez y reutiliza el
    JWT (igual que la SPA)."""

    wait_time = between(1, 3)
    token: str | None = None

    def on_start(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={
                "tenant_slug": TENANT_SLUG,
                "email": EMAIL,
                "password": PASSWORD,
            },
            name="POST /api/v1/auth/login",
        )
        if response.status_code == 200:
            self.token = response.json().get("access_token")
        else:
            # No generamos tráfico autenticado de mentira: si el login
            # falla (usuario de carga no sembrado), este Locust user
            # se detiene y el fallo queda visible en el reporte.
            self.environment.runner.quit()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    @task(6)
    def list_contacts(self) -> None:
        """Objetivo RNF-04: p95 API no-IA <= 200 ms."""
        self.client.get(
            "/api/v1/contacts",
            headers=self._auth_headers(),
            name="GET /api/v1/contacts",
        )

    @task(3)
    def health_check(self) -> None:
        self.client.get("/healthz", name="GET /healthz")

    @task(1)
    def rag_draft(self) -> None:
        """Objetivo RNF-04: p95 RAG <= 6 s (GPU); degradación CPU documentada.

        Baja frecuencia relativa (peso 1 vs 6+3) porque el RAG es la
        operación más costosa: en un CRM real la proporción de mensajes
        que requieren un borrador asistido por IA es minoritaria frente a
        lecturas de bandeja/CRM. Ajustar el peso si THOR define otro mix.
        """
        self.client.post(
            "/api/v1/rag/draft",
            json={"query": RAG_QUERY, "top_k": 5},
            headers=self._auth_headers(),
            name="POST /api/v1/rag/draft",
        )


def _sign_webhook_body(body: bytes, app_secret: str) -> str:
    """Misma firma que calcula Meta (y que verifica
    `app/integrations/whatsapp/webhook.py`, SPEC-026): HMAC-SHA256 sobre el
    RAW body, con el prefijo `sha256=`."""
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class WhatsAppWebhookUser(HttpUser):
    """Escenario de carga del webhook de WhatsApp — SPEC-026/SPEC-033
    (RNF-02: p95 ACK <= 500 ms).

    A diferencia de `OmniCoreApiUser`, este usuario NO se autentica con JWT
    (el webhook de Meta no usa el login de agentes): cada request lleva su
    propia firma `X-Hub-Signature-256` VÁLIDA calculada sobre el body exacto
    enviado, igual que `tests/test_whatsapp_webhook.py`. Un `wamid` distinto
    por request evita que la deduplicación (SPEC-027, async, fuera de este
    umbral) sea observable en el ACK.

    Sin `LOADTEST_WHATSAPP_APP_SECRET` configurado, este usuario se detiene
    inmediatamente (no genera tráfico "de mentira" contra un endpoint que
    exige HMAC válido) — mismo criterio de fail-fast que `OmniCoreApiUser`
    cuando el login falla.
    """

    wait_time = between(1, 2)

    def on_start(self) -> None:
        if not WHATSAPP_APP_SECRET:
            self.environment.runner.quit()

    @task
    def post_webhook_valid_signature(self) -> None:
        """Objetivo RNF-02 (SPEC-026/SPEC-033): p95 del ACK <= 500 ms.

        Mide SOLO el ACK síncrono (200 + encolado en Redis) — el
        procesamiento real del mensaje ocurre async en
        `whatsapp_inbound_worker` (SPEC-027) y no se mide aquí.
        """
        raw_body = json.dumps(
            {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "id": "loadtest-biz",
                        "changes": [
                            {
                                "field": "messages",
                                "value": {
                                    "metadata": {
                                        "phone_number_id": WHATSAPP_PHONE_NUMBER_ID
                                    },
                                    "contacts": [
                                        {
                                            "wa_id": "573000000000",
                                            "profile": {"name": "Carga Locust"},
                                        }
                                    ],
                                    "messages": [
                                        {
                                            "id": f"wamid.loadtest.{uuid.uuid4().hex}",
                                            "from": "573000000000",
                                            "type": "text",
                                            "text": {"body": "carga p95 ACK webhook"},
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ],
            }
        ).encode("utf-8")

        signature = _sign_webhook_body(raw_body, WHATSAPP_APP_SECRET)

        self.client.post(
            WEBHOOK_PATH,
            data=raw_body,
            headers={
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
            name="POST /api/v1/whatsapp/webhook (firma válida)",
        )
