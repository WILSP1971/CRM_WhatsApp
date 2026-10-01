"""
CLI interno de alta de tenant + primer admin — SPEC-075 (ADR-015, RF-07).

Invoca el MISMO `tenant_provisioning_service.provision_tenant` que usa
`POST /platform/tenants`, sin pasar por HTTP ni requerir un token de
plataforma: pensado para el equipo interno de confianza (alta administrativa,
Q1-B de ADR-015), mismo plano que `app/db/seed.py` (engine directo, patrón
`SessionLocal` en vez del engine Core porque el servicio necesita un ORM
`Session` para `set_tenant_session`/insertar `User`).

Uso (mismo patrón de invocación que `seed.py`, "python -m"):
    DATABASE_URL=postgresql+psycopg://... python -m app.db.provision_tenant \\
        --nombre "Clínica Demo Este" \\
        --slug clinica-demo-este \\
        --admin-email admin@clinica-demo-este.test \\
        --admin-nombre "Admin Demo Este" \\
        [--admin-password <password>]

Credenciales (C3): `--admin-password` es OPCIONAL por argumento; si se omite,
se lee de la variable de entorno `PROVISION_TENANT_ADMIN_PASSWORD` (nunca
hardcodeada en el código ni en el historial de shell si se usa la env var).
Si ninguna de las dos está presente, el CLI aborta con un mensaje claro (no
genera ni acepta una contraseña por defecto insegura).
"""

from __future__ import annotations

import argparse
import os
import sys

from app.db.session import SessionLocal
from app.services.tenant_provisioning_service import (
    EmailCollisionError,
    InvalidFieldError,
    InvalidPasswordError,
    InvalidSlugError,
    SlugCollisionError,
    TenantProvisioningError,
    provision_tenant,
)

_ENV_ADMIN_PASSWORD = "PROVISION_TENANT_ADMIN_PASSWORD"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Alta interna de un tenant nuevo + su primer admin (SPEC-075)."
    )
    parser.add_argument(
        "--nombre", required=True, help="Nombre del tenant (sede/clínica)."
    )
    parser.add_argument(
        "--slug",
        required=True,
        help="Slug único del tenant (minúsculas, dígitos y guiones).",
    )
    parser.add_argument(
        "--admin-email", required=True, help="Email del primer admin del tenant."
    )
    parser.add_argument(
        "--admin-nombre", required=True, help="Nombre del primer admin del tenant."
    )
    parser.add_argument(
        "--admin-password",
        default=None,
        help=(
            "Password del primer admin. Si se omite, se lee de la variable "
            f"de entorno {_ENV_ADMIN_PASSWORD} (recomendado, evita dejar el "
            "secreto en el historial de shell)."
        ),
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    admin_password = args.admin_password or os.getenv(_ENV_ADMIN_PASSWORD)
    if not admin_password:
        print(
            f"ERROR: falta la contraseña del admin. Use --admin-password o "
            f"defina la variable de entorno {_ENV_ADMIN_PASSWORD} (CHECKPOINT "
            "C3: nunca hardcodeada).",
            file=sys.stderr,
        )
        return 2

    db = SessionLocal()
    try:
        resultado = provision_tenant(
            db,
            nombre=args.nombre,
            slug=args.slug,
            admin_email=args.admin_email,
            admin_password=admin_password,
            admin_nombre=args.admin_nombre,
        )
    except (InvalidSlugError, InvalidPasswordError, InvalidFieldError) as exc:
        print(f"ERROR de validación: {exc}", file=sys.stderr)
        return 2
    except (SlugCollisionError, EmailCollisionError) as exc:
        print(f"ERROR de colisión: {exc}", file=sys.stderr)
        return 1
    except TenantProvisioningError as exc:  # defensa en profundidad
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(
        f"Tenant aprovisionado: tenant_id={resultado.tenant_id} "
        f"slug={resultado.slug} admin_user_id={resultado.admin_user_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
