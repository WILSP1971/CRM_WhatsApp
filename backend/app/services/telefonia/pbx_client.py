"""Cliente de descarga de grabaciones desde un PBX EXTERNO (SPEC-037, ADR-010).

Egress ACOTADO, transporte puro (NO inferencia, NO envío de audio a un
tercero de IA): usado exclusivamente por
`app/workers/recording_fetch_worker.py` cuando `PBX_EXTERNAL_ENABLED=true`
(SUP-42: por defecto el PBX es on-prem y este módulo nunca se ejercita en el
camino feliz). Inerte por defecto.

Reglas duras (ADR-010, verificadas por `check-externos-backend.sh` sección
11):
- El host del PBX (`PBX_EXTERNAL_HOST`) SOLO puede usarse en este módulo
  (`app/services/telefonia/`) — fuera de él, falla el CI.
- Este módulo NUNCA importa nada de `app/services/rag`, `AIClient`, Ollama ni
  ningún cliente de inferencia — es transporte, no procesamiento.
- El `stt_worker`/módulos de IA NUNCA importan este módulo (verificado en CI):
  reciben el audio del almacén cifrado on-prem (`audio_store.py`), jamás por
  descarga directa.

Notas de seguridad (C3):
- `PBX_EXTERNAL_AUTH_TOKEN` viene EXCLUSIVAMENTE de `Settings` (env);
  nunca se hardcodea ni se loguea.
- El host se valida EXACTO contra `settings.pbx_external_host` (sin
  comodines/subdominios) antes de cualquier petición — mismo criterio de
  validación de host fijo que ya usa el conector de WhatsApp (ADR-006) para
  su propio host de envío.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


class PbxDownloadError(RuntimeError):
    """Fallo al descargar la grabación desde el PBX externo (red/HTTP)."""


class PbxHostNotAllowedError(RuntimeError):
    """La URL de descarga no apunta al host del PBX configurado (ADR-010)."""


def _validate_recording_url(recording_url: str) -> None:
    """Valida que `recording_url` apunte EXACTAMENTE al host del PBX externo
    configurado (`PBX_EXTERNAL_HOST`) — rechaza cualquier otro host/dominio,
    incluidos subdominios (`evil.<host>.attacker.net`) o URLs sin host
    (mismo criterio de validación de host fijo que ya usa el conector de
    WhatsApp, ADR-006)."""
    settings = get_settings()
    if not settings.pbx_external_enabled:
        raise PbxHostNotAllowedError(
            "PBX_EXTERNAL_ENABLED=false: descarga de PBX externo deshabilitada "
            "(SUP-42, topología on-prem por defecto)."
        )
    if not settings.pbx_external_host:
        raise PbxHostNotAllowedError(
            "PBX_EXTERNAL_HOST no configurado; no se puede validar el destino "
            "de la descarga (C3)."
        )

    parsed = urlparse(recording_url)
    host = (parsed.hostname or "").strip().lower()
    allowed_host = settings.pbx_external_host.strip().lower()
    if host != allowed_host:
        raise PbxHostNotAllowedError(
            f"URL de descarga apunta a un host no permitido "
            f"(esperado exactamente '{allowed_host}', ADR-010)."
        )
    if parsed.scheme != "https":
        raise PbxHostNotAllowedError(
            f"Esquema de URL no soportado para la descarga: {parsed.scheme!r} "
            "(SOLO 'https' está permitido, mismo criterio que "
            "`graph_client._validate_graph_host`, ADR-006/ADR-010: la "
            "descarga de audio -dato personal/posible PHI- nunca viaja en "
            "claro por HTTP)."
        )


def download_recording(*, recording_url: str, timeout_seconds: float = 30.0) -> bytes:
    """Descarga el fichero de audio desde el PBX externo, EGRESS ACOTADO
    (ADR-010): valida el host exacto antes de la petición, autentica con
    `PBX_EXTERNAL_AUTH_TOKEN` (Bearer) si está configurado, y jamás sigue
    redirecciones automáticamente (evita que el PBX comprometido redirija la
    petición a otro host y burle la allowlist)."""
    _validate_recording_url(recording_url)
    settings = get_settings()

    headers = {}
    if settings.pbx_external_auth_token:
        headers["Authorization"] = f"Bearer {settings.pbx_external_auth_token}"

    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
            response = client.get(recording_url, headers=headers)
            response.raise_for_status()
            return response.content
    except httpx.HTTPError as exc:
        logger.error(
            "pbx_recording_download_failed",
            host=settings.pbx_external_host,
            exc_info=True,
        )
        raise PbxDownloadError(
            f"Fallo al descargar la grabación del PBX externo: {exc}"
        ) from exc
