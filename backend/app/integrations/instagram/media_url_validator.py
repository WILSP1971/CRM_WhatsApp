"""Validación de FORMA de la URL del CDN de media de Instagram DM — SPEC-088.

CHECKPOINT SENSIBLE (defensa en profundidad, RF-03 SPEC-088): antes de
persistir una referencia de media (`messages.media_url`/`media_type`), se
valida en memoria que la URL entregada por Meta en el payload del webhook
(`attachments[].payload.url`, SPEC-086) es sintácticamente una URL `https`
cuyo host es EXACTAMENTE `lookaside.fbsbx.com` (sin subdominios no
autorizados, p.ej. `evil.lookaside.fbsbx.com.attacker.net`) y sin userinfo
embebido (`https://user:pass@lookaside.fbsbx.com/...`).

Mismo criterio/estilo que `_validate_graph_host` de
`app.integrations.whatsapp.graph_client` (comparación por `urlparse().
hostname`, rechazo de userinfo), pero para un host DISTINTO y, a diferencia
de aquella función, esta NUNCA abre ninguna conexión: es pura validación de
cadena, no un cliente HTTP. No existe (y está PROHIBIDO crear, ver
SPEC-088 §Alcance OUT) ningún `media_client.py` de Instagram que haga un GET
a esta URL — el único consumidor real es el navegador del agente humano
(render bajo demanda desde el cliente, RF-06).

Si la URL no pasa la validación, el llamador (`instagram_inbound_worker`)
audita con `logger.warning` SOLO metadatos (`instagram_account_id`/`mid`/
`message_id`) — NUNCA la URL completa, que contiene una `signature`/
`asset_id` (credencial de acceso temporal, C2/RNF-C2) — y no persiste la
referencia; el mensaje de texto, si lo hay, se persiste igual (ver
`instagram_inbound_worker._process_message_event`).
"""

from __future__ import annotations

from urllib.parse import urlparse

# Host EXACTO permitido para la referencia de media de DMs de Instagram
# (SPEC-088, hallazgo de investigación cruzada de producción — ver "NOTA DE
# REVISIÓN POST-APROBACIÓN" de SPEC-088). Distinto de `graph.facebook.com`
# (ADR-006, usado para el transporte de ENVÍO de WhatsApp/Instagram).
ALLOWED_MEDIA_CDN_HOST = "lookaside.fbsbx.com"


def is_valid_instagram_media_url(url: str | None) -> bool:
    """`True` si `url` es sintácticamente una URL `https` cuyo host es
    EXACTAMENTE `lookaside.fbsbx.com`, sin userinfo embebido.

    Pura validación de cadena (`urllib.parse`), SIN abrir ninguna conexión
    de red — no es un egress, es una comprobación de forma en memoria (ver
    docstring del módulo). `None`/cadena vacía/URL malformada -> `False`,
    sin lanzar excepción (robustez: un payload inesperado de Meta no debe
    tumbar la ingesta del mensaje).
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.username is not None or parsed.password is not None:
        return False

    scheme = (parsed.scheme or "").strip().lower()
    hostname = (parsed.hostname or "").strip().lower()

    return scheme == "https" and hostname == ALLOWED_MEDIA_CDN_HOST
