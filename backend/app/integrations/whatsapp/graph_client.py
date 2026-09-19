"""Cliente httpx de envío saliente — WhatsApp Business Cloud API (Graph API)
— SPEC-029 (F4), ADR-006.

Este módulo es el ÚNICO lugar del backend autorizado a llamar a
`graph.facebook.com` PARA ENVIAR (el webhook de recepción, `webhook.py`, no
llama a Meta — solo recibe). Es transporte del canal (el texto ya fue
aprobado por un humano, SPEC-019), NUNCA inferencia: no importa `AIClient`
ni ningún módulo de `app.services.rag`/`app.workers` (auditado por
`check-externos-backend.sh`, puntos 7-9).

CHECKPOINT SENSIBLE (RNF-01 SPEC-029, allowlist por código, ADR-006): el
host de la URL base se valida contra `graph.facebook.com` EXACTO
(`urlparse().hostname`, mismo criterio defensivo que
`Settings._require_internal_ai_host` de SPEC-016) antes de emitir cualquier
request. Un host distinto (typo de configuración, URL maliciosa inyectada
por error, subdominio parecido, etc.) aborta ANTES de abrir la conexión —
nunca se confía únicamente en el firewall de red para esta garantía.

CHECKPOINT C3 (secretos): el `access_token` (Bearer) viaja SOLO en el header
`Authorization` de la request a Meta; nunca se incluye en logs (`structlog`
aquí jamás recibe el token ni el `Authorization` header como campo) ni en
mensajes de excepción.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

# Host EXACTO permitido para el transporte del canal (ADR-006/RNF-01). La
# versión de API es configurable por env (`Settings.whatsapp_api_version`);
# el host NUNCA lo es.
_ALLOWED_GRAPH_HOST = "graph.facebook.com"
_DEFAULT_BASE_URL = f"https://{_ALLOWED_GRAPH_HOST}"

# Códigos de error de Meta considerados transitorios (RF-04): 429 (rate
# limit propio de Meta) y cualquier 5xx. Un 4xx distinto de 429 se trata
# como error definitivo (p.ej. token inválido, plantilla no aprobada,
# número no habilitado) y NO se reintenta.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GraphApiHostError(RuntimeError):
    """La URL base no apunta al host permitido `graph.facebook.com`
    (CHECKPOINT SENSIBLE, allowlist por código, ADR-006/RNF-01)."""


class GraphApiError(RuntimeError):
    """Error definitivo de la Graph API (4xx no reintentable, respuesta sin
    el `wamid` esperado, etc.). No se debe reintentar."""


class GraphApiTransientError(RuntimeError):
    """Error transitorio de la Graph API (429/5xx) tras agotar los
    reintentos con backoff (RF-04, RNF-05): el llamador debe marcar el
    envío como `failed`, NUNCA duplicar el envío reintentando desde fuera de
    este cliente (la idempotencia de reintentos vive DENTRO de
    `send_text_message`/`send_template_message`)."""


@dataclass(frozen=True)
class GraphSendResult:
    """Resultado de un envío exitoso a la Graph API."""

    wamid: str
    raw: dict[str, Any]


def _validate_graph_host(base_url: str) -> str:
    """Valida que `base_url` resuelva EXACTAMENTE al host permitido.

    Comparación por `hostname` (sin puerto/esquema/credenciales embebidas),
    igual criterio que `Settings._require_internal_ai_host` (SPEC-016): un
    host distinto de `graph.facebook.com` (incluye subdominios como
    `evil.graph.facebook.com.attacker.net` o hosts vacíos/malformados)
    se RECHAZA antes de construir el cliente httpx.

    Defensa en profundidad (SPEC-032, hardening deuda SPEC-029/BLACK WIDOW):
    rechaza explícitamente URLs con userinfo embebido
    (`https://user:pass@graph.facebook.com/...`). `urlparse().hostname` ya
    ignora ese userinfo al comparar el host, así que sin esta comprobación
    una URL con credenciales incrustadas pasaría la validación igual — no es
    explotable hoy (el `base_url` es fijo en código, nunca proviene de input
    externo), pero cierra el vector por si un cambio futuro interpolara un
    valor no confiable en `base_url`/`_messages_url`.
    """
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").strip().lower()
    scheme = (parsed.scheme or "").strip().lower()
    if parsed.username is not None or parsed.password is not None:
        raise GraphApiHostError(
            f"URL base '{base_url}' contiene userinfo embebido "
            "(usuario/contraseña en la URL), no permitido (CHECKPOINT "
            "SENSIBLE, defensa en profundidad ADR-006/RNF-01)."
        )
    if hostname != _ALLOWED_GRAPH_HOST or scheme != "https":
        raise GraphApiHostError(
            f"URL base '{base_url}' no apunta al host permitido "
            f"'https://{_ALLOWED_GRAPH_HOST}' (CHECKPOINT SENSIBLE, "
            "ADR-006/RNF-01: el transporte del canal WhatsApp SOLO puede "
            "egresar hacia la Graph API de Meta por HTTPS, ningún otro "
            "dominio/esquema)."
        )
    return base_url


class GraphApiClient:
    """Cliente tipado para el envío saliente por WhatsApp Cloud API.

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
        self._access_token = access_token or settings.whatsapp_token
        self._api_version = api_version or settings.whatsapp_api_version
        self._base_url = _validate_graph_host(base_url or _DEFAULT_BASE_URL)
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.whatsapp_send_timeout_seconds
        )
        self._max_retries = (
            max_retries
            if max_retries is not None
            else settings.whatsapp_send_max_retries
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

    def _messages_url(self, phone_number_id: str) -> str:
        url = f"{self._base_url}/{self._api_version}/{phone_number_id}/messages"
        # Defensa en profundidad: revalida el host de la URL FINAL construida
        # (no solo el `base_url` de entrada) por si algún cambio futuro
        # introdujera interpolación de un valor no confiable en `base_url`.
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
        """POST con reintentos idempotentes ante 429/5xx (RF-04, RNF-05).

        Idempotencia: el `idempotency_key` (típicamente el `id` del
        `Message`/job saliente en nuestro dominio, NUNCA el `wamid` — que
        aún no existe antes de enviar) se loguea para poder correlacionar
        reintentos en auditoría; la Graph API de WhatsApp no ofrece un
        header de idempotencia propio, así que la garantía de "no duplicar"
        la sostiene el llamador (RF-04/`wa_send_worker`): un job de envío ya
        marcado `enviado`/con `wamid` persistido nunca se reencola.
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
                        "whatsapp_graph_send_timeout",
                        attempt=attempt,
                        max_retries=self._max_retries,
                        idempotency_key=idempotency_key,
                    )
                    continue
                except httpx.HTTPError as exc:
                    last_exc = exc
                    logger.warning(
                        "whatsapp_graph_send_network_error",
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
                        "whatsapp_graph_send_retryable_error",
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
                # (puede incluir metadatos del número/plantilla; C2/C3
                # minimización) — solo el status y la clave de correlación.
                logger.error(
                    "whatsapp_graph_send_permanent_error",
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
            "whatsapp_graph_send_retries_exhausted",
            max_retries=self._max_retries,
            idempotency_key=idempotency_key,
        )
        raise GraphApiTransientError(
            f"Se agotaron los {self._max_retries} reintentos ante Meta "
            "(429/5xx/timeout)"
        ) from last_exc

    def send_text_message(
        self,
        *,
        phone_number_id: str,
        to: str,
        text: str,
        idempotency_key: str,
    ) -> GraphSendResult:
        """Envía texto libre (dentro de la ventana de 24 h, RF-03 SPEC-029).

        POST a `https://graph.facebook.com/<version>/<phone_number_id>/messages`
        con `Authorization: Bearer <token>`. Devuelve el `wamid` asignado por
        Meta (`messages[0].id` de la respuesta), que el llamador persiste
        (RF-01).
        """
        url = self._messages_url(phone_number_id)
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        data = self._post_with_retries(
            url, payload=payload, idempotency_key=idempotency_key
        )
        return _extract_wamid(data)

    def send_template_message(
        self,
        *,
        phone_number_id: str,
        to: str,
        template_name: str,
        language_code: str,
        idempotency_key: str,
        parameters: list[str] | None = None,
    ) -> GraphSendResult:
        """Envía una plantilla HSM utilitaria (fuera de ventana de 24 h,
        RF-03 SPEC-029). `parameters` son los valores posicionales del
        cuerpo de la plantilla ya aprobada por Meta (opcional, plantilla
        mínima sin variables por defecto)."""
        url = self._messages_url(phone_number_id)
        template: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if parameters:
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in parameters],
                }
            ]
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": template,
        }
        data = self._post_with_retries(
            url, payload=payload, idempotency_key=idempotency_key
        )
        return _extract_wamid(data)


def _extract_wamid(data: dict[str, Any]) -> GraphSendResult:
    try:
        wamid = data["messages"][0]["id"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GraphApiError(
            "Respuesta de Graph API sin 'messages[0].id' (wamid) esperado"
        ) from exc
    return GraphSendResult(wamid=wamid, raw=data)
