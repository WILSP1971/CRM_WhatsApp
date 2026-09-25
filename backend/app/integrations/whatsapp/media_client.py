"""Cliente httpx de descarga de media entrante — WhatsApp Business Cloud API
(Graph API) — SPEC-054 (F1), ADR-006/ADR-007/ADR-009.

Decisión de diseño (documentada, ver SPEC-054 §"Alcance IN"/1): la descarga
vive en un archivo HERMANO de `graph_client.py` (`media_client.py`), NO como
método añadido a `GraphApiClient`, porque:
  - `GraphApiClient` está tipado/documentado exclusivamente como transporte
    de ENVÍO saliente (POST `/messages`, SPEC-029); mezclar aquí un flujo de
    dos GETs distintos (resolver URL temporal + descargar binario) habría
    diluido ese contrato ya auditado y probado.
  - Ambos módulos SÍ comparten la MISMA validación de host
    (`graph_client._validate_graph_host`, reutilizada por import directo, NO
    reimplementada) y el MISMO patrón de reintentos con backoff
    (`_post_with_retries` inspira `_get_with_retries` de este módulo, con la
    salvedad de que aquí ambos GETs deben revalidar host antes de conectar).
  - Sigue viviendo exclusivamente en `app/integrations/whatsapp/`: el único
    módulo autorizado a que `graph.facebook.com` aparezca en su código
    (`check-externos-backend.sh`, sección 7, ADR-006/SPEC-024). Cero egress
    nuevo: mismo host, mismo token, un verbo GET adicional.

Este módulo también contiene la función de ORQUESTACIÓN
(`download_and_store_voice_note`) que aplica idempotencia (ADR-007),
persiste el binario cifrado vía `audio_store.store_audio` (SPEC-035, SIN
cambios) y escribe `Message.audio_ref`/`Message.mime_type` (columna
`messages.mime_type`, migración `a2fd6d06f701`, corrección post-revisión de
WOLVERINE: antes se logueaba y se perdía). `Message.audio_duracion_seg`
permanece SIEMPRE `None` en este flujo: el endpoint de resolución de media
de Graph API usado aquí (`GET /<version>/<media-id>`) no provee duración en
su respuesta (solo `url`/`mime_type`/`sha256`/`file_size`, ver
`MediaMetadata`) — no es un olvido, no hay ninguna fuente de este dato en el
flujo de descarga actual (ver comentario en `app/models/message.py`).
`Message.transcripcion_estado` se deja intacto en el camino feliz (queda
"pendiente" para que SPEC-055/056 lo consuman) y solo se sobrescribe a
"error" en los caminos de fallo. Esta función SÍ importa
`app.models.message`/`app.services.telefonia.audio_store` (permitido: no son
Ollama/IA/`app.workers`, ver sección 8 de `check-externos-backend.sh`) pero
JAMÁS es importada por `app.workers.stt_worker` ni por ningún módulo de IA
(RF-05 SPEC-054, ADR-009: el STT nunca descarga, solo lee del almacén ya
poblado por este módulo).

CHECKPOINT SENSIBLE (ADR-006, RF-01 SPEC-054): AMBOS GETs (resolución de la
URL temporal y descarga del binario) validan el host EXACTO
`graph.facebook.com` con la MISMA `_validate_graph_host` de `graph_client.py`
ANTES de abrir cualquier conexión — un host distinto en cualquiera de los
dos pasos aborta con `GraphApiHostError` sin llegar a `client.get(...)`.

CHECKPOINT C3 (secretos): el `access_token` (Bearer) viaja SOLO en el header
`Authorization` de ambos GETs; nunca se incluye en logs (`structlog` aquí
jamás recibe el token como campo) ni en mensajes de excepción.

Nota P5 (transcodificación OGG/Opus, verificado al implementar esta SPEC):
las notas de voz de WhatsApp llegan típicamente en OGG/Opus. Se revisó el
código real de `faster_whisper` (dependencia `app/services/telefonia/
stt_engine.py`, SPEC-038): `faster_whisper/audio.py::decode_audio` decodifica
el audio de entrada con PyAV (`av.open(input_file, ...)`), que EMBEBE FFmpeg
y soporta nativamente cualquier contenedor/codec que FFmpeg soporte,
incluido OGG/Opus, SIN requerir FFmpeg instalado aparte en el sistema
(`requirements.txt` fija `faster-whisper==1.0.3`, que declara `av<13,>=11.0`
como dependencia transitiva). `transcribe_audio_bytes` pasa el audio
directamente como `io.BytesIO(audio_bytes)` a `WhisperModel.transcribe(...)`,
que internamente invoca ese `decode_audio`. CONCLUSIÓN: NO se necesita un
paso de transcodificación previa (ni aquí ni en SPEC-056) — el binario OGG/
Opus descargado y descifrado por este módulo puede pasarse tal cual al motor
STT. Este módulo, en consecuencia, NO añade ninguna dependencia de `ffmpeg`
ni invoca subprocesos de conversión.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.whatsapp.graph_client import (
    GraphApiError,
    GraphApiHostError,
    _validate_graph_host,
)
from app.models.message import Message
from app.services.telefonia import audio_store

logger = structlog.get_logger(__name__)

_ALLOWED_GRAPH_HOST = "graph.facebook.com"
_DEFAULT_BASE_URL = f"https://{_ALLOWED_GRAPH_HOST}"

# Mismo criterio de reintento que `graph_client._post_with_retries` (RF-04
# de SPEC-029, reutilizado aquí para RNF-05 de SPEC-054): 429 (rate limit) y
# cualquier 5xx se consideran transitorios; un 4xx distinto (p.ej. 404 media
# no encontrado, 401 token inválido) es definitivo y no se reintenta. Una URL
# temporal expirada (R-67) normalmente se manifiesta como 4xx/5xx del propio
# CDN de Meta al intentar el segundo GET — se trata con el mismo esquema de
# reintento acotado.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class MediaDownloadError(RuntimeError):
    """Error definitivo al resolver/descargar el media (4xx no reintentable,
    respuesta sin `url` esperada, etc.). No se debe reintentar."""


class MediaDownloadTransientError(RuntimeError):
    """Error transitorio (429/5xx) tras agotar los reintentos con backoff
    (RNF-05): el llamador debe marcar la descarga como fallida
    (`transcripcion_estado="error"`), NUNCA reintentar desde fuera de este
    cliente."""


@dataclass(frozen=True)
class MediaMetadata:
    """Resultado de resolver la URL temporal de un media (paso 1, GET
    `/<version>/<media-id>`)."""

    url: str
    mime_type: str | None
    sha256: str | None
    file_size: int | None


@dataclass(frozen=True)
class DownloadedMedia:
    """Binario descargado (paso 2) junto con los metadatos ya resueltos."""

    content: bytes
    mime_type: str | None


class GraphMediaClient:
    """Cliente tipado para la descarga de media entrante (notas de voz de
    WhatsApp, RF-01/RF-02 SPEC-054).

    Reutiliza EXACTAMENTE `_validate_graph_host` de `graph_client.py` (mismo
    criterio de allowlist por código, ADR-006) — no hay una segunda
    implementación de la validación de host en todo el backend.
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

    def _headers(self) -> dict[str, str]:
        # CHECKPOINT C3: el token nunca se loguea; esta función es la ÚNICA
        # que lo materializa en un header, y su valor de retorno no se pasa
        # jamás a `logger.*` en este módulo.
        return {"Authorization": f"Bearer {self._access_token}"}

    def _sleep_backoff(self, attempt: int) -> None:
        if self._backoff_base_seconds <= 0:
            return
        time.sleep(self._backoff_base_seconds * (2 ** (attempt - 1)))

    def _get_with_retries(
        self, url: str, *, headers: dict[str, str], correlation_key: str
    ) -> httpx.Response:
        """GET con reintentos idempotentes ante 429/5xx (RNF-05), MISMO
        patrón que `graph_client._post_with_retries`. Revalida el host de
        `url` ANTES de emitir cualquier request — un host distinto de
        `graph.facebook.com` aborta con `GraphApiHostError` sin abrir
        conexión (RF-01, defensa en profundidad: se valida tanto en la
        construcción de la URL fija del paso 1 como en la URL temporal,
        potencialmente en otro subdominio de Meta, del paso 2)."""
        _validate_graph_host(url)

        last_exc: Exception | None = None
        client = self._get_client()
        owns_client = self._client is None
        try:
            for attempt in range(1, self._max_retries + 1):
                try:
                    response = client.get(url, headers=headers)
                except httpx.TimeoutException as exc:
                    last_exc = exc
                    logger.warning(
                        "whatsapp_media_download_timeout",
                        attempt=attempt,
                        max_retries=self._max_retries,
                        correlation_key=correlation_key,
                    )
                    self._sleep_backoff(attempt)
                    continue
                except httpx.HTTPError as exc:
                    last_exc = exc
                    logger.warning(
                        "whatsapp_media_download_network_error",
                        attempt=attempt,
                        max_retries=self._max_retries,
                        correlation_key=correlation_key,
                        error_type=type(exc).__name__,
                    )
                    self._sleep_backoff(attempt)
                    continue

                if response.status_code == 200:
                    return response

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    logger.warning(
                        "whatsapp_media_download_retryable_error",
                        attempt=attempt,
                        max_retries=self._max_retries,
                        status_code=response.status_code,
                        correlation_key=correlation_key,
                    )
                    last_exc = MediaDownloadTransientError(
                        f"Descarga de media respondió {response.status_code} "
                        f"(intento {attempt}/{self._max_retries})"
                    )
                    self._sleep_backoff(attempt)
                    continue

                # Error definitivo (4xx no reintentable, p.ej. 404 media
                # expirado/no encontrado, 401 token inválido): no se
                # reintenta. NUNCA se incluye el body de la respuesta en el
                # log (C2/C3, minimización).
                logger.error(
                    "whatsapp_media_download_permanent_error",
                    status_code=response.status_code,
                    correlation_key=correlation_key,
                )
                raise MediaDownloadError(
                    f"Descarga de media respondió {response.status_code} "
                    "(no reintentable)"
                )
        finally:
            if owns_client:
                client.close()

        logger.error(
            "whatsapp_media_download_retries_exhausted",
            max_retries=self._max_retries,
            correlation_key=correlation_key,
        )
        raise MediaDownloadTransientError(
            f"Se agotaron los {self._max_retries} reintentos descargando "
            "media (429/5xx/timeout, posible URL temporal expirada R-67)"
        ) from last_exc

    def resolve_media_metadata(self, media_id: str) -> MediaMetadata:
        """Paso 1 (RF-01): `GET graph.facebook.com/<version>/<media-id>` —
        resuelve la URL temporal de descarga y el `mime_type` (si Meta lo
        provee). El host de la URL construida se valida ANTES de conectar
        (misma defensa en profundidad que `graph_client._messages_url`)."""
        url = f"{self._base_url}/{self._api_version}/{media_id}"
        _validate_graph_host(url)

        response = self._get_with_retries(
            url, headers=self._headers(), correlation_key=media_id
        )
        try:
            data: dict[str, Any] = response.json()
            temp_url = data["url"]
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphApiError(
                "Respuesta de Graph API sin 'url' esperada al resolver media"
            ) from exc

        return MediaMetadata(
            url=temp_url,
            mime_type=data.get("mime_type"),
            sha256=data.get("sha256"),
            file_size=data.get("file_size"),
        )

    def download_binary(self, metadata: MediaMetadata) -> DownloadedMedia:
        """Paso 2 (RF-01): `GET <url-temporal>` con `Authorization: Bearer
        <token>` — descarga el binario. Se ejecuta INMEDIATAMENTE tras
        `resolve_media_metadata` (minimiza la ventana de expiración de la
        URL temporal, R-67). El host de la URL temporal (que Meta puede
        servir desde otro subdominio de su CDN) se valida con el MISMO
        criterio EXACTO `graph.facebook.com` — si no coincide, aborta antes
        de conectar (RF-01)."""
        response = self._get_with_retries(
            metadata.url, headers=self._headers(), correlation_key=metadata.url
        )
        return DownloadedMedia(content=response.content, mime_type=metadata.mime_type)

    def fetch_media(self, media_id: str) -> DownloadedMedia:
        """Orquesta los dos GETs (RF-01) en secuencia inmediata (R-67).

        Si no se inyectó un `httpx.Client` externo (`self._client is None`,
        caso real de producción), ambos GETs reutilizan la MISMA conexión
        httpx (abierta una única vez aquí y cerrada al final) en vez de
        abrir/cerrar un cliente por cada GET — evita el costo de un segundo
        handshake TLS hacia el mismo host justo en la ventana crítica en la
        que la URL temporal puede expirar (R-67)."""
        if self._client is not None:
            metadata = self.resolve_media_metadata(media_id)
            return self.download_binary(metadata)

        owned_client = httpx.Client(timeout=self._timeout_seconds)
        original_client = self._client
        self._client = owned_client
        try:
            metadata = self.resolve_media_metadata(media_id)
            return self.download_binary(metadata)
        finally:
            self._client = original_client
            owned_client.close()


def download_and_store_voice_note(
    db: Session,
    message: Message,
    *,
    media_id: str,
    client: GraphMediaClient | None = None,
) -> Message:
    """Orquesta la descarga E2E de la nota de voz de un `Message(tipo=
    "audio")` ya persistido (RF-01/RF-02/RF-03/RF-04 SPEC-054), bajo RLS del
    tenant de la sesión (ya fijado por el llamador, mismo criterio que
    `whatsapp_inbound_worker`).

    En éxito escribe `message.audio_ref` (referencia opaca al almacén
    cifrado) y `message.mime_type` (tal cual lo reportó Meta al resolver la
    metadata, puede ser `None` si Meta no lo incluyó en la respuesta) —
    `message.transcripcion_estado` NO se toca en este camino (permanece en
    el valor que ya traía, típicamente "pendiente", para que SPEC-055/056 lo
    consuman). `message.audio_duracion_seg` nunca se puebla aquí (ver nota en
    el docstring del módulo).

    Idempotencia (RF-03, ADR-007): si `message.audio_ref` YA está poblado
    (reentrega del mismo `wamid`/evento), esta función es un no-op — NO
    vuelve a llamar a la Graph API. La guarda se evalúa ANTES de intentar
    cualquier GET.

    Fallo definitivo (RF-04): un `MediaDownloadError`/`MediaDownloadTransientError`/
    `GraphApiHostError`/`GraphApiError` se captura, se audita
    (`transcripcion_estado="error"`) y NUNCA se propaga — el llamador (futuro
    encolado de SPEC-055) no ve reventar su proceso por un fallo de descarga.

    Devuelve el `message` (ya actualizado en la sesión, sin commit — el
    llamador controla la transacción, mismo patrón que el resto del
    dominio)."""
    if message.audio_ref:
        logger.info(
            "whatsapp_media_download_skipped_already_stored",
            message_id=str(message.id),
            tenant_id=str(message.tenant_id),
        )
        return message

    media_client = client or GraphMediaClient()

    try:
        downloaded = media_client.fetch_media(media_id)
    except GraphApiHostError:
        # RF-01: host distinto de graph.facebook.com — violación de
        # seguridad, NUNCA se trata como fallo "normal" auditado con
        # transcripcion_estado="error" silencioso: se re-propaga para que
        # quede visible como incidente (allowlist por código, ADR-006).
        raise
    except (
        MediaDownloadError,
        MediaDownloadTransientError,
        GraphApiError,
    ):
        logger.error(
            "whatsapp_media_download_failed_marking_error",
            message_id=str(message.id),
            tenant_id=str(message.tenant_id),
            exc_info=True,
        )
        message.transcripcion_estado = "error"
        db.flush()
        return message

    audio_ref = audio_store.build_audio_ref(
        tenant_id=message.tenant_id, call_id=str(message.id)
    )
    try:
        audio_store.store_audio(audio_ref=audio_ref, audio_bytes=downloaded.content)
    except audio_store.AudioStoreError:
        logger.error(
            "whatsapp_media_store_failed_marking_error",
            message_id=str(message.id),
            tenant_id=str(message.tenant_id),
            exc_info=True,
        )
        message.transcripcion_estado = "error"
        db.flush()
        return message

    message.audio_ref = audio_ref
    message.mime_type = downloaded.mime_type
    db.flush()

    logger.info(
        "whatsapp_media_download_and_store_succeeded",
        message_id=str(message.id),
        tenant_id=str(message.tenant_id),
        mime_type=downloaded.mime_type,
    )
    return message
