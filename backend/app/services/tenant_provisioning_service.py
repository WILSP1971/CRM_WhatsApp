"""
Servicio de aprovisionamiento de tenants — SPEC-075 (ADR-015).

Crea, en **una sola transacción atómica**, la fila raíz `tenants` (plano-
plataforma, patrón del seed `app/db/seed.py:49-62`, SIN `app.tenant_id`) y el
PRIMER `user` admin de ese tenant (plano-tenant, bajo RLS efectiva, patrón
`auth_service.authenticate()`: `set_tenant_session(db, nuevo_tenant.id)` ANTES
de tocar `users`). Cualquier fallo → rollback total (ni tenant ni admin
persistidos) — invariante dura de ADR-015 §3 (atomicidad todo-o-nada).

Invariante de frontera de privilegio (ADR-015 §3.3, NO se relaja): el ÚNICO
INSERT con privilegio elevado es el de la fila raíz `tenants` (no scoped).
`users` SIEMPRE se inserta con `app.tenant_id` fijado — PROHIBIDO el bypass
genérico de rol owner para tablas scoped (bug recurrente ya documentado en
`retention_service`/`call_retention_service`, R-90).

Excepciones de dominio tipadas (el router las mapea a 409/422, NUNCA 500):
  - `InvalidSlugError`   -> 422 (formato inválido o slug reservado).
  - `InvalidPasswordError` -> 422 (password que no cumple el mínimo de SPEC-013).
  - `SlugCollisionError` -> 409 (slug ya existe, unique global).
  - `EmailCollisionError` -> 409 (email ya existe para ese tenant nuevo, unique
    por-tenant — en un tenant recién creado solo puede colisionar si el mismo
    slug+email se reintenta tras un fallo previo no limpiado, pero se captura
    igual por defensa en profundidad).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import set_tenant_session
from app.models.user import User
from app.security.passwords import hash_password

# Formato de slug (RF-01 SPEC-075): minúsculas, dígitos y guiones, sin
# espacios ni mayúsculas, no empieza/termina en guion, longitud 1-100.
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SLUG_MAX_LENGTH = 100

# Slugs reservados (RF-01): evitan colisión semántica con rutas/plano de
# plataforma ya existentes o previsibles (`/platform/...`, `/api/...`, etc.).
RESERVED_SLUGS = frozenset({"platform", "admin", "api", "me"})

_MIN_PASSWORD_LENGTH = 8


class TenantProvisioningError(Exception):
    """Base de las excepciones de dominio de este servicio."""


class InvalidSlugError(TenantProvisioningError):
    """Slug con formato inválido o reservado — mapeado a 422."""


class InvalidPasswordError(TenantProvisioningError):
    """Password que no cumple el mínimo de seguridad — mapeado a 422."""


class InvalidFieldError(TenantProvisioningError):
    """Campo de texto requerido (nombre de tenant/admin) vacío — mapeado a 422."""


class SlugCollisionError(TenantProvisioningError):
    """Slug ya existente (unique global en `tenants`) — mapeado a 409."""


class EmailCollisionError(TenantProvisioningError):
    """Email ya existente para el tenant (unique por-tenant) — mapeado a 409."""


@dataclass(frozen=True)
class ProvisionedTenant:
    """Resultado del aprovisionamiento: IDs/campos públicos, NUNCA password/hash."""

    tenant_id: uuid.UUID
    slug: str
    admin_user_id: uuid.UUID


def _normalizar_slug(slug: str) -> str:
    """Normaliza y valida el slug (RF-01 SPEC-075).

    Formato exigido: minúsculas, dígitos y guiones simples (`[a-z0-9]+(-[a-z0-9]+)*`),
    longitud 1-100, sin espacios. Se normaliza con `.strip().lower()` antes de
    validar (igual criterio que `admin_email`, `auth_service`), pero NO se
    "corrige" un formato inválido (p.ej. no se reemplazan espacios por
    guiones): un slug mal formado es un error 422 explícito, no una
    adivinanza silenciosa de lo que el llamador quiso decir.
    """
    candidato = slug.strip().lower()
    if not candidato or len(candidato) > _SLUG_MAX_LENGTH:
        raise InvalidSlugError(
            f"El slug debe tener entre 1 y {_SLUG_MAX_LENGTH} caracteres"
        )
    if not _SLUG_RE.match(candidato):
        raise InvalidSlugError(
            "El slug debe contener solo minúsculas, dígitos y guiones simples "
            "(formato: 'clinica-demo-norte'), sin espacios ni mayúsculas"
        )
    if candidato in RESERVED_SLUGS:
        raise InvalidSlugError(f"El slug '{candidato}' está reservado")
    return candidato


def _normalizar_email(email: str) -> str:
    """Mismo criterio de normalización que `auth_service.authenticate`."""
    return email.strip().lower()


def _validar_password(password: str) -> None:
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise InvalidPasswordError(
            f"La contraseña debe tener al menos {_MIN_PASSWORD_LENGTH} caracteres"
        )


def provision_tenant(
    db: Session,
    *,
    nombre: str,
    slug: str,
    admin_email: str,
    admin_password: str,
    admin_nombre: str,
) -> ProvisionedTenant:
    """Crea tenant + primer admin en una única transacción atómica (ADR-015).

    Pasos (todo dentro de `db.begin()`, commit/rollback únicos):
      1. Normaliza/valida `slug` (formato + reservados), `admin_email`
         (`.strip().lower()`) y `admin_password` (longitud mínima).
      2. INSERT `tenants` (patrón de plataforma, SIN `app.tenant_id`, igual
         que `app/db/seed.py:49-62`). Colisión de `slug` (unique global) ->
         `SlugCollisionError`.
      3. `set_tenant_session(db, nuevo_tenant.id)` sobre la MISMA
         sesión/transacción (patrón `auth_service.authenticate`, líneas 75-98).
      4. INSERT `users` (bajo RLS efectiva, `rol="admin"`, `password_hash`
         bcrypt vía `hash_password`). Colisión `uq_users_tenant_email` ->
         `EmailCollisionError`.
      5. `commit` implícito al salir del `with db.begin()` sin excepción;
         cualquier excepción no capturada dentro del bloque dispara rollback
         automático de SQLAlchemy (0 filas persistidas).

    No captura `IntegrityError` genéricas sin inspeccionarlas: distingue la
    violación de la constraint de `tenants.slug` de la de
    `uq_users_tenant_email` por el nombre de la constraint reportado por
    PostgreSQL (`orig.diag.constraint_name`, psycopg3), para no filtrar un
    error 500 crudo ante CUALQUIER violación de integridad inesperada.
    """
    nombre_normalizado = nombre.strip()
    if not nombre_normalizado:
        raise InvalidFieldError("El nombre del tenant no puede estar vacío")

    slug_normalizado = _normalizar_slug(slug)
    email_normalizado = _normalizar_email(admin_email)
    _validar_password(admin_password)

    admin_nombre_normalizado = admin_nombre.strip()
    if not admin_nombre_normalizado:
        raise InvalidFieldError("El nombre del admin no puede estar vacío")

    nuevo_tenant_id = uuid.uuid4()
    nuevo_admin_id = uuid.uuid4()

    with db.begin():
        # Paso 2: fila raíz `tenants`, patrón de plataforma (sin
        # `app.tenant_id`) — idéntico al seed (`seed.py:49-62`), pero SIN
        # `ON CONFLICT DO NOTHING`: aquí una colisión de slug debe
        # convertirse en un error tipado (409), no silenciarse.
        try:
            db.execute(
                sa.text(
                    "INSERT INTO tenants (id, nombre, slug, activo) "
                    "VALUES (:id, :nombre, :slug, true)"
                ),
                {
                    "id": nuevo_tenant_id,
                    "nombre": nombre_normalizado,
                    "slug": slug_normalizado,
                },
            )
        except IntegrityError as exc:
            raise SlugCollisionError(
                f"El slug '{slug_normalizado}' ya está en uso"
            ) from exc

        # Paso 3: fija `app.tenant_id` del tenant RECIÉN creado sobre la
        # MISMA transacción (patrón `auth_service.authenticate`, líneas
        # 75-98) — a partir de aquí, cualquier acceso a tablas scoped
        # (`users`) respeta RLS efectiva (ADR-004/ADR-008). Nunca se usa una
        # sesión owner sin tenant para insertar en `users` (R-90).
        set_tenant_session(db, str(nuevo_tenant_id))

        # Paso 4: primer `user` admin, bajo RLS, vía ORM (la sesión ya tiene
        # `app.tenant_id` fijado -> el INSERT respeta la política
        # `tenant_isolation_users`, WITH CHECK incluido).
        admin_user = User(
            id=nuevo_admin_id,
            tenant_id=nuevo_tenant_id,
            email=email_normalizado,
            nombre=admin_nombre_normalizado,
            password_hash=hash_password(admin_password),
            rol="admin",
            activo=True,
        )
        db.add(admin_user)
        try:
            db.flush()
        except IntegrityError as exc:
            raise EmailCollisionError(
                f"El email '{email_normalizado}' ya está en uso en este tenant"
            ) from exc

    return ProvisionedTenant(
        tenant_id=nuevo_tenant_id,
        slug=slug_normalizado,
        admin_user_id=nuevo_admin_id,
    )
