"""Modelo `instagram_accounts` — routing `instagram_business_account_id ->
tenant_id` del canal Instagram DM (SPEC-085, espejo de SPEC-025/ADR-007).

Resuelve, para un `instagram_business_account_id` de Instagram Business
(cuenta de Instagram profesional/Creator vinculada a una Página de Meta), a
qué tenant pertenece. Es la base del enrutado multi-tenant del webhook de
Instagram: el worker de ingesta (SPEC-087, fuera de alcance aquí) DEBE
resolver el tenant vía esta tabla y fijar `app.tenant_id` de sesión (RLS,
ADR-004) ANTES de escribir ningún `message`/`conversation`/`contact`.

Es una entidad TRANSACCIONAL con `tenant_id` propio (1 fila = 1 cuenta de
Instagram Business dada de alta para 1 tenant) y por eso lleva **RLS
ENABLE+FORCE** igual que el resto de `TENANT_SCOPED_TABLES` (mismo criterio
que `whatsapp_accounts`, SPEC-025 RF-01/RNF-04, ADR-007 punto 2): un tenant
nunca debe poder leer/enumerar las cuentas de Instagram de otro tenant vía la
API de administración multi-tenant.

Mecanismo real de la resolución pre-tenant (ADR-008, mismo patrón que
`whatsapp_accounts`): el runtime de api/workers se conecta con el rol de
aplicación `omnicore_app` (NOSUPERUSER NOBYPASSRLS) — NO con el rol
`postgres`/owner — por lo que RLS (ENABLE+FORCE, ADR-004) SÍ se aplica
siempre, incluida esta tabla. La resolución
`instagram_business_account_id -> tenant_id` ANTES de fijar `app.tenant_id`
de sesión NO se hace con un SELECT directo (que devolvería 0 filas
fail-closed sin tenant fijado), sino invocando la función
`resolve_tenant_by_instagram_account_id(text)` (SQL, `SECURITY DEFINER`,
`STABLE`, propietaria del rol privilegiado/owner, creada en la migración de
esta SPEC) — copia literal del patrón de `resolve_tenant_by_phone_number_id`
(migración `54c75efefe3c`, ADR-008). Esa función se ejecuta con los
privilegios de su propietario (owner), no con los del invocador, así que
puede leer `instagram_accounts` sin `app.tenant_id` fijado; el rol de
aplicación solo tiene `GRANT EXECUTE` sobre ELLA (`REVOKE ... FROM PUBLIC`),
nunca `BYPASSRLS` general. Es de solo lectura, acotada a una única fila
(`instagram_business_account_id`, `activo = true`) y con `search_path` fijo
para evitar secuestro. El webhook (SPEC-087, fuera de alcance aquí) la
invoca, obtiene el `tenant_id`, y RECIÉN ENTONCES fija `app.tenant_id` (RLS)
para el resto de la transacción.

Nota de diseño de idempotencia (SPEC-085 §3.4, Q4=A, NO reabrir): Instagram
identifica cada mensaje entrante/saliente con un `mid` (no un `wamid`). Esta
SPEC NO añade una columna nueva ni renombra ninguna existente: el `mid` de
Instagram se persiste en la columna YA EXISTENTE `messages.wamid`
(`String(128)` UNIQUE nullable), que pasa a representar el "id de mensaje
del canal externo" genérico — WhatsApp guarda su `wamid`, Instagram guarda
su `mid`, en la misma columna. No hay colisión semántica porque los espacios
de id de ambos canales no se solapan en la práctica y la restricción UNIQUE
es la garantía dura de idempotencia (ADR-007) independientemente del canal
de origen. Ver también el comentario junto a `Message.wamid`
(`app/models/message.py`).

Borrado lógico (C2): dar de baja una cuenta de Instagram es `activo=False`,
nunca un DELETE físico (evita perder la trazabilidad de a qué tenant
perteneció una cuenta).
"""

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin


class InstagramAccount(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "instagram_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    instagram_business_account_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )  # id de cuenta de Instagram Business (Meta), UNIQUE global (RF-01)
    username: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # @usuario de Instagram, informativo, opcional
    display_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # nombre para mostrar de la cuenta, informativo, opcional
    etiqueta: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # nombre descriptivo de la cuenta para administración (opcional)
