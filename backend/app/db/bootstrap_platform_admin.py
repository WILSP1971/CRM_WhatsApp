"""
Bootstrap del primer admin de plataforma — SPEC-075 (ADR-015 §Decisión 4,
RF-08).

Resuelve el "huevo-gallina" (¿quién crea al primer `platform_admin`?) por
seed/CLI de plataforma, NUNCA por autoregistro (coherente con Q1-B: alta
administrativa interna, sin autoregistro público). Mismo plano que
`app/db/seed.py` (engine directo, patrón `ON CONFLICT ... DO NOTHING`), pero
con credenciales leídas EXCLUSIVAMENTE de variables de entorno (C3: nunca
hardcodeadas) e idempotente (si el email ya existe, no falla ni duplica).

Variables de entorno usadas (ninguna tiene valor por defecto de producción;
sin ellas el script aborta con un mensaje claro):
  - `PLATFORM_ADMIN_BOOTSTRAP_EMAIL`:   email del primer admin de plataforma.
  - `PLATFORM_ADMIN_BOOTSTRAP_PASSWORD`: password en claro (se hashea aquí
    mismo con `hash_password`, bcrypt, antes de tocar la BD — nunca se
    persiste en claro).
  - `PLATFORM_ADMIN_BOOTSTRAP_NOMBRE`: nombre del admin (opcional, default
    "Admin de Plataforma").

Uso (mismo patrón de invocación que `seed.py`):
    DATABASE_URL=postgresql+psycopg://... \\
    PLATFORM_ADMIN_BOOTSTRAP_EMAIL=... \\
    PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=... \\
    python -m app.db.bootstrap_platform_admin
"""

from __future__ import annotations

import os
import sys
import uuid

import sqlalchemy as sa

from app.db.session import engine
from app.security.passwords import hash_password

_ENV_EMAIL = "PLATFORM_ADMIN_BOOTSTRAP_EMAIL"
_ENV_PASSWORD = "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD"
_ENV_NOMBRE = "PLATFORM_ADMIN_BOOTSTRAP_NOMBRE"
_DEFAULT_NOMBRE = "Admin de Plataforma"


def run_bootstrap() -> int:
    email = os.getenv(_ENV_EMAIL)
    password = os.getenv(_ENV_PASSWORD)
    nombre = os.getenv(_ENV_NOMBRE, _DEFAULT_NOMBRE)

    if not email or not password:
        print(
            "ERROR: faltan credenciales de bootstrap. Defina las variables de "
            f"entorno {_ENV_EMAIL} y {_ENV_PASSWORD} (CHECKPOINT C3: nunca "
            "hardcodeadas en el código).",
            file=sys.stderr,
        )
        return 2

    email_normalizado = email.strip().lower()
    password_hash = hash_password(password)

    with engine.begin() as conn:
        result = conn.execute(
            sa.text(
                "INSERT INTO platform_admins (id, email, password_hash, nombre, activo) "
                "VALUES (:id, :email, :password_hash, :nombre, true) "
                "ON CONFLICT (email) DO NOTHING "
                "RETURNING id"
            ),
            {
                "id": uuid.uuid4(),
                "email": email_normalizado,
                "password_hash": password_hash,
                "nombre": nombre,
            },
        )
        inserted_id = result.scalar_one_or_none()

    if inserted_id is None:
        print(
            f"Bootstrap idempotente: ya existía un platform_admin con email "
            f"'{email_normalizado}' (sin cambios)."
        )
    else:
        print(
            f"Bootstrap completo: platform_admin creado (id={inserted_id}, "
            f"email='{email_normalizado}')."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_bootstrap())
