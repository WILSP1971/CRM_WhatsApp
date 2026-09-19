"""Modelo `whatsapp_accounts` — routing `phone_number_id -> tenant_id` del
canal WhatsApp (SPEC-025, ADR-007).

Resuelve, para un `phone_number_id` de WhatsApp Business (número receptor),
a qué tenant pertenece. Es la base del enrutado multi-tenant del webhook de
WhatsApp: el worker de ingesta (SPEC-027, fuera de alcance aquí) DEBE
resolver el tenant vía esta tabla y fijar `app.tenant_id` de sesión (RLS,
ADR-004) ANTES de escribir ningún `message`/`conversation`/`contact`.

Es una entidad TRANSACCIONAL con `tenant_id` propio (1 fila = 1 número de
WhatsApp Business dado de alta para 1 tenant) y por eso lleva **RLS
ENABLE+FORCE** igual que el resto de `TENANT_SCOPED_TABLES` (SPEC-025 RF-01/
RNF-04, ADR-007 punto 2): un tenant nunca debe poder leer/enumerar los
`phone_number_id` de otro tenant vía la API de administración multi-tenant.

Esto es distinto de `tenants` (que es la tabla RAÍZ del aislamiento y por
definición no tiene un `tenant_id` "padre"): `whatsapp_accounts` SÍ pertenece
a un tenant.

Mecanismo real de la resolución pre-tenant (ADR-008, corrige el hallazgo de
BLACK PANTHER en SPEC-025): el runtime de api/workers se conecta con el rol
de aplicación `omnicore_app` (NOSUPERUSER NOBYPASSRLS) — NO con el rol
`postgres`/owner — por lo que RLS (ENABLE+FORCE, ADR-004) SÍ se aplica
siempre, incluida esta tabla. La resolución
`phone_number_id -> tenant_id` ANTES de fijar `app.tenant_id` de sesión NO se
hace con un SELECT directo (que devolvería 0 filas fail-closed sin tenant
fijado), sino invocando la función `resolve_tenant_by_phone_number_id(text)`
(SQL, `SECURITY DEFINER`, `STABLE`, propietaria del rol privilegiado/owner,
creada en la migración `54c75efefe3c`). Esa función se ejecuta con los
privilegios de su propietario (owner), no con los del invocador, así que
puede leer `whatsapp_accounts` sin `app.tenant_id` fijado; el rol de
aplicación solo tiene `GRANT EXECUTE` sobre ELLA (`REVOKE ... FROM PUBLIC`),
nunca `BYPASSRLS` general. Es de solo lectura, acotada a una única fila
(`phone_number_id`, `activo = true`) y con `search_path` fijo para evitar
secuestro. El webhook (SPEC-027, fuera de alcance aquí) la invoca, obtiene el
`tenant_id`, y RECIÉN ENTONCES fija `app.tenant_id` (RLS) para el resto de la
transacción.

Borrado lógico (C2): dar de baja un número de WhatsApp es `activo=False`,
nunca un DELETE físico (evita perder la trazabilidad de a qué tenant
perteneció un número).
"""

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin


class WhatsappAccount(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "whatsapp_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    phone_number_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )  # id de número de WhatsApp Business (Meta), UNIQUE global (RF-01)
    display_phone_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # número en formato legible (E.164/local), informativo, opcional
    etiqueta: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # nombre descriptivo del número para administración (opcional)
