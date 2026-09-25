"""Modelo `pbx_lines` — routing `numero_destino -> tenant_id` del canal de
telefonía/voz (SPEC-037, ADR-007, mismo patrón que `whatsapp_accounts`
SPEC-025/ADR-007).

El conector de ingesta de grabaciones (SPEC-037, `app/integrations/pbx/
webhook.py`) recibe metadatos de la llamada (número, dirección, duración,
`call_id`) pero el PBX/troncal puede enviar el número DESTINO (línea/DID de
la clínica/tenant que recibió o cursó la llamada) en vez de un `tenant_id`
explícito y verificable — igual que WhatsApp entrega un `phone_number_id`, no
un `tenant_id`. Esta tabla resuelve, para un `numero_destino` (DID/extensión/
troncal dado de alta), a qué tenant pertenece, ANTES de fijar `app.tenant_id`
de sesión (RLS, ADR-004).

Es una entidad TRANSACCIONAL con `tenant_id` propio (1 fila = 1 línea/DID de
telefonía dado de alta para 1 tenant) y por eso lleva **RLS ENABLE+FORCE**
igual que el resto de `TENANT_SCOPED_TABLES` (RNF-47, ADR-008): un tenant
nunca debe poder leer/enumerar las líneas de otro tenant.

Mecanismo real de la resolución pre-tenant (ADR-008, mismo patrón que
`resolve_tenant_by_phone_number_id`): la resolución `numero_destino ->
tenant_id` se hace invocando la función SQL `resolve_tenant_by_pbx_line(text)`
(`SECURITY DEFINER`, `STABLE`, propietaria del rol privilegiado/owner), NUNCA
con un SELECT directo bajo el rol de aplicación `omnicore_app` (que
devolvería 0 filas fail-closed sin `app.tenant_id` fijado). El conector de
ingesta (worker consumidor, SPEC-037) la invoca, obtiene el `tenant_id`, y
RECIÉN ENTONCES fija `app.tenant_id` para el resto de la transacción. Sin
mapeo -> descarte auditado, cero persistencia de audio (RF-03).

Borrado lógico (C2): dar de baja una línea es `activo=False`, nunca un DELETE
físico.
"""

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin


class PbxLine(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "pbx_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    numero_destino: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True
    )  # DID/extensión/troncal del PBX que recibe la llamada, UNIQUE global
    # (RF-03, base del enrutado — análogo a whatsapp_accounts.phone_number_id)
    etiqueta: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # nombre descriptivo de la línea para administración (opcional)
