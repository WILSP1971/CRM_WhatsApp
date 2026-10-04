"""Cliente httpx de envío saliente — Instagram Messaging API (Graph API) —
SPEC-089 (F4), ADR-006 ampliado.

Este módulo es el ÚNICO lugar del backend autorizado a llamar a
`graph.facebook.com` PARA ENVIAR por el canal Instagram DM (el webhook de
recepción, `webhook.py`, y el parser, `inbound_parser.py`, NUNCA llaman a
Meta — solo reciben/interpretan). Es transporte del canal (el texto ya fue
aprobado por un humano, SPEC-019), NUNCA inferencia: no importa `AIClient`
ni ningún módulo de `app.services.rag`/`app.workers` (auditado por
`check-externos-backend.sh`, verificación 8 extendida a Instagram).

Espejo ESTRUCTURAL de `app.integrations.whatsapp.graph_client` (SPEC-029):
MISMO host (`graph.facebook.com`, ADR-006 ampliado por SPEC-085), MISMA
allowlist por código (`_validate_graph_host`), MISMO patrón de backoff
(`_post_with_retries`) y MISMA regla de que el token Bearer SOLO se
materializa en `_headers()` y nunca se loguea (C3). La única diferencia
estructural real es la FORMA del endpoint/payload de envío (Instagram
Messaging API, no WhatsApp Cloud API) y que este cliente NO tiene
`send_template_message` (Instagram no tiene plantillas HSM, N-5 SPEC-089) —
en su lugar, `send_message` acepta un `tag` opcional (`HUMAN_AGENT`,
confirmado contra la documentación vigente de Meta, ver
`app.services.instagram.messaging_window` para la lógica de ventana/tag).

CHECKPOINT SENSIBLE (RNF-EGRESS-ACOTADO SPEC-089, allowlist por código,
ADR-006 ampliado): el host de la URL base se valida contra
`graph.facebook.com` EXACTO (`urlparse().hostname`) antes de emitir
cualquier request. Un host distinto aborta ANTES de abrir la conexión.

CHECKPOINT C3 (secretos): el `access_token`
(`Settings.instagram_page_access_token`, Bearer) viaja SOLO en el header
`Authorization` de la request a Meta; nunca se incluye en logs (`structlog`
aquí jamás recibe el token ni el header `Authorization` como campo) ni en
mensajes de excepción.

Decisión de diseño (forma del endpoint/body, documentada por no haber un
archivo de WhatsApp 100% idéntico a espejar — SPEC-089 §1 lo pide
explícito): la Instagram Messaging API (vía Graph API de Meta) expone el
envío de DMs bajo
`POST https://graph.facebook.com/<version>/me/messages` (o, equivalentemente,
`/<instagram_business_account_id>/messages` — este cliente usa el segundo
patrón, análogo al `/<phone_number_id>/messages` de WhatsApp, porque en
multi-tenant el emisor real es la cuenta de Instagram Business del tenant,
nunca un alias genérico `me` que dependería de qué token esté activo en el
proceso) con body
`{"recipient": {"id": <sender_id>}, "message": {"text": <texto>},
"tag": "HUMAN_AGENT"}` (el campo `tag` se omite por completo cuando el envío
cae dentro de la ventana estándar de 24h, RF-03 SPEC-089) y
`Authorization: Bearer <INSTAGRAM_PAGE_ACCESS_TOKEN>`. La respuesta exitosa
tiene la forma `{"recipient_id": "...", "message_id": "<mid>"}` (DISTINTA de
la forma `{"messages": [{"id": "<wamid>"}]}` de WhatsApp) — `_extract_mid`
lee `message_id` en vez de `messages[0].id`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

# Host EXACTO permitido para el transporte del canal (ADR-006 ampliado,
# SPEC-085/089) — MISMO host ya autorizado para WhatsApp, ningún egress
# nuevo. La versión de API es configurable por env
# (`Settings.instagram_api_version`); el host NUNCA lo es.
_ALLOWED_GRAPH_HOST = "graph.facebook.com"
_DEFAULT_BASE_URL = f"https://{_ALLOWED_GRAPH_HOST}"

# Códigos de error de Meta considerados transitorios (RF-04): 429 (rate
# limit propio de Meta) y cualquier 5xx. Un 4xx distinto de 429 se trata
# como error definitivo (p.ej. token inválido, destinatario fuera de
# ventana, política de message tag violada) y NO se reintenta.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Message tag ÚNICO soportado por la Instagram Messaging API (investigación
# ya confirmada contra la documentación vigente de Meta, ver contexto de
# SPEC-089): extiende la ventana de mensajería a 7 días, pero SOLO cuando un
# agente humano real está respondiendo un caso de soporte en curso (nunca
# marketing/promoción, nunca un sistema automatizado). La lógica de CUÁNDO
# aplicar este tag vive en `app.workers.instagram_send_worker._resolve_send_tag`,
# NO en este cliente (separación transporte/orquestación, mismo criterio que
# `wa_send_worker`/`graph_client` de WhatsApp).
INSTAGRAM_HUMAN_AGENT_TAG = "HUMAN_AGENT"


class GraphApiHostError(RuntimeError):
    """La URL base no apunta al host permitido `graph.facebook.com`
    (CHECKPOINT SENSIBLE, allowlist por código, ADR-006 ampliado)."""


class GraphApiError(RuntimeError):
    """Error definitivo de la Graph API (4xx no reintentable, respuesta sin
    el `message_id` esperado, etc.). No se debe reintentar."""


class GraphApiTransientError(RuntimeError):
    """Error transitorio de la Graph API (429/5xx) tras agotar los
    reintentos con backoff (RF-04): el llamador debe marcar el envío como
    `failed`, NUNCA duplicar el envío reintentando desde fuera de este
    cliente (la idempotencia de reintentos vive DENTRO de `send_message`)."""


@dataclass(frozen=True)
class GraphSendResult:
    """Resultado de un envío exitoso a la Graph API de Instagram."""

    mid: str
    raw: dict[str, Any]


def _validate_graph_host(base_url: str) -> str:
    """Valida que `base_url` resuelva EXACTAMENTE al host permitido.

    Espejo EXACTO de `app.integrations.whatsapp.graph_client.
    _validate_graph_host` (mismo criterio defensivo, mismo host): comparación
    por `hostname` (sin puerto/esquema/credenciales embebidas); un host
    distinto de `graph.facebook.com` (incluye subdominios como
    `evil.graph.facebook.com.attacker.net` o hosts vacíos/malformados) se
    RECHAZA antes de construir el cliente httpx. Rechaza explícitamente URLs
    con userinfo embebido (`https://user:pass@graph.facebook.com/...`).
    """
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").strip().lower()
    scheme = (parsed.scheme or "").strip().lower()
    if parsed.username is not None or parsed.password is not None:
        raise GraphApiHostError(
            f"URL base '{base_url}' contiene userinfo embebido "
            "(usuario/contraseña en la URL), no permitido (CHECKPOINT "
            "SENSIBLE, defensa en profundidad ADR-006 ampliado)."
        )
    if hostname != _ALLOWED_GRAPH_HOST or scheme != "https":
        raise GraphApiHostError(
            f"URL base '{base_url}' no apunta al host permitido "
            f"'https://{_ALLOWED_GRAPH_HOST}' (CHECKPOINT SENSIBLE, "
            "ADR-006 ampliado: el transporte del canal Instagram SOLO puede "
            "egresar hacia la Graph API de Meta por HTTPS, ningún otro "
            "dominio/esquema)."
        )
    return base_url


class GraphApiClient:
    """Cliente tipado para el envío saliente por Instagram Messaging API.

    El `base_url` proviene EXCLUSIVAMENTE del host fijo `graph.facebook.com`
    (validado en `__init__`) salvo que se inyecte explícitamente en tests —
    incluso inyectado, pasa por la MISMA validación de host (no hay atajo).
    """

    def __init__(
        self,
        *,
        access_token: str | None = None,
        api_version: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        backoff_base_seconds: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        settings = get_settings()
        self._access_token = access_token or settings.instagram_page_access_token
        self._api_version = api_version or settings.instagram_api_version
        self._base_url = _validate_graph_host(base_url or _DEFAULT_BASE_URL)
        # Reutiliza los MISMOS defaults de timeouts/reintentos que WhatsApp
        # (`Settings.whatsapp_send_*`, SPEC-029): ambos clientes hablan con
        # el mismo host/infraestructura de Meta, y no hay evidencia (ni SPEC)
        # que justifique una política de reintentos distinta por canal — en
        # vez de introducir variables de entorno `INSTAGRAM_SEND_*`
        # duplicadas sin un motivo real, se comparte la fuente de verdad.
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.whatsapp_send_timeout_seconds
        )
        self._max_retries = (
            max_retries if max_retries is not None else settings.whatsapp_send_max_retries
        )
        self._backoff_base_seconds = (
            backoff_base_seconds
            if backoff_base_seconds is not None
            else settings.whatsapp_send_backoff_base_seconds
        )
        self._client = client

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self._timeout_seconds)

    def _messages_url(self, instagram_business_account_id: str) -> str:
        url = (
            f"{self._base_url}/{self._api_version}/"
            f"{instagram_business_account_id}/messages"
        )
        # Defensa en profundidad: revalida el host de la URL FINAL construida
        # (no solo el `base_url` de entrada), mismo criterio que WhatsApp.
        _validate_graph_host(url)
        return url

    def _headers(self) -> dict[str, str]:
        # CHECKPOINT C3: el token nunca se loguea; esta función es la ÚNICA
        # que lo materializa en un header, y su valor de retorno no se pasa
        # jamás a `logger.*` en este módulo.
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def _post_with_retries(
        self, url: str, *, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        """POST con reintentos idempotentes ante 429/5xx (RF-04).

        Idempotencia: el `idempotency_key` (típicamente el `id` del
        `Message`/job saliente en nuestro dominio, NUNCA el `mid` — que aún
        no existe antes de enviar) se loguea para poder correlacionar
        reintentos en auditoría; la Instagram Messaging API no ofrece un
        header de idempotencia propio, así que la garantía de "no duplicar"
        la sostiene el llamador (`instagram_send_worker`): un job de envío ya
        marcado `enviado`/con `mid` persistido (en `messages.wamid`, §3.4)
        nunca se reencola.
        """
        last_exc: Exception | None = None
        client = self._get_client()
        owns_client = self._client is None
        try:
            for attempt in range(1, self._max_retries + 1):
                try:
                    response = client.post(url, headers=self._headers(), json=payload)
                except httpx.TimeoutException as exc:
                    last_exc = exc
                    logger.warning(
                        "instagram_graph_send_timeout",
                        attempt=attempt,
                        max_retries=self._max_retries,
                        idempotency_key=idempotency_key,
                    )
                    continue
                except httpx.HTTPError as exc:
                    last_exc = exc
                    logger.warning(
                        "instagram_graph_send_network_error",
                        attempt=attempt,
                        max_retries=self._max_retries,
                        idempotency_key=idempotency_key,
                        error_type=type(exc).__name__,
                    )
                    continue

                if response.status_code == 200:
                    return response.json()

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    logger.warning(
                        "instagram_graph_send_retryable_error",
                        attempt=attempt,
                        max_retries=self._max_retries,
                        status_code=response.status_code,
                        idempotency_key=idempotency_key,
                    )
                    last_exc = GraphApiTransientError(
                        f"Graph API respondió {response.status_code} "
                        f"(intento {attempt}/{self._max_retries})"
                    )
                    continue

                # Error definitivo (4xx no reintentable): no se reintenta.
                # NUNCA se incluye el body de la respuesta de Meta en el log
                # (puede incluir metadatos del destinatario/cuenta; C2/C3
                # minimización) — solo el status y la clave de correlación.
                logger.error(
                    "instagram_graph_send_permanent_error",
                    status_code=response.status_code,
                    idempotency_key=idempotency_key,
                )
                raise GraphApiError(
                    f"Graph API respondió {response.status_code} (no reintentable)"
                )
        finally:
            if owns_client:
                client.close()

        # Reintentos agotados ante errores transitorios (RF-04): el
        # llamador debe marcar el envío como `failed`, no reintentar de
        # nuevo desde fuera de este cliente.
        logger.error(
            "instagram_graph_send_retries_exhausted",
            max_retries=self._max_retries,
            idempotency_key=idempotency_key,
        )
        raise GraphApiTransientError(
            f"Se agotaron los {self._max_retries} reintentos ante Meta "
            "(429/5xx/timeout)"
        ) from last_exc

    def send_message(
        self,
        *,
        instagram_business_account_id: str,
        recipient_id: str,
        text: str,
        idempotency_key: str,
        tag: str | None = None,
    ) -> GraphSendResult:
        """Envía un DM de texto por la Instagram Messaging API.

        `tag` (RF-03 SPEC-089, ventana propia de IG): `None` cuando el envío
        cae dentro de la ventana estándar de 24h (el campo `tag` se OMITE
        por completo del body, no se envía como cadena vacía);
        `INSTAGRAM_HUMAN_AGENT_TAG` ("HUMAN_AGENT") cuando el envío ocurre
        entre 24h y 7 días desde el último mensaje del contacto, bajo las
        condiciones de uso legítimo documentadas en el módulo de ventana
        (`app.services.instagram.messaging_window`). Resolver si aplica o no
        el tag es responsabilidad del LLAMADOR (`instagram_send_worker`),
        NUNCA de este cliente — igual separación transporte/orquestación que
        WhatsApp.

        POST a
        `https://graph.facebook.com/<version>/<instagram_business_account_id>/messages`
        con `Authorization: Bearer <token>`. Devuelve el `mid` asignado por
        Meta (`message_id` de la respuesta), que el llamador persiste en
        `messages.wamid` (§3.4, columna genérica de id de mensaje externo).
        """
        url = self._messages_url(instagram_business_account_id)
        payload: dict[str, Any] = {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
        }
        if tag:
            payload["tag"] = tag
        data = self._post_with_retries(
            url, payload=payload, idempotency_key=idempotency_key
        )
        return _extract_mid(data)


def _extract_mid(data: dict[str, Any]) -> GraphSendResult:
    try:
        mid = data["message_id"]
    except (KeyError, TypeError) as exc:
        raise GraphApiError(
            "Respuesta de Graph API sin 'message_id' (mid) esperado"
        ) from exc
    if not isinstance(mid, str) or not mid:
        raise GraphApiError(
            "Respuesta de Graph API con 'message_id' vacío o de tipo inesperado"
        )
    return GraphSendResult(mid=mid, raw=data)
