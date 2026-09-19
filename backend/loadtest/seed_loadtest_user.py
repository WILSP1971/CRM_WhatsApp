"""Siembra el tenant/usuario/documento mínimos para `locustfile.py` —
SPEC-022 (arnés de carga) + SPEC-033 (escenario de carga del webhook
WhatsApp).

Pensado para CI (Postgres real de `services:` del workflow) o un entorno
local con `docker compose up`. Es idempotente: si el tenant/usuario/cuenta
de WhatsApp de carga ya existen, no falla (usa `ON CONFLICT DO NOTHING`).

Uso:
    DATABASE_URL=postgresql+psycopg://... python -m loadtest.seed_loadtest_user

No ingiere el documento en pgvector (eso requiere el worker RAG +
embeddings de Ollama corriendo) — solo dispone los datos de auth para que
`login` + `GET /contacts` funcionen. El escenario de `/rag/draft` en CI
puede recibir 404 "sin contexto" si no se corrió antes el ingest real; se
documenta como parte del checklist de entorno real en el README del
arnés, no bloquea el smoke de la parte no-IA (RNF-04 API <= 200ms).
"""

from __future__ import annotations

import os
import uuid

import sqlalchemy as sa

from app.security.passwords import hash_password

TENANT_SLUG = os.getenv("LOADTEST_TENANT_SLUG", "tenant-loadtest")
EMAIL = os.getenv("LOADTEST_EMAIL", "loadtest@tenant-loadtest.test")
PASSWORD = os.getenv("LOADTEST_PASSWORD", "LoadTest#2026")
# SPEC-033: phone_number_id usado por `WhatsAppWebhookUser` (locustfile.py) —
# debe existir y estar activo en `whatsapp_accounts` para que el routing
# `phone_number_id -> tenant_id` (SECURITY DEFINER, ADR-008) resuelva al
# tenant de carga cuando el worker async (fuera del umbral del ACK) procese
# el evento encolado.
WHATSAPP_PHONE_NUMBER_ID = os.getenv(
    "LOADTEST_WHATSAPP_PHONE_NUMBER_ID", "000000000000001"
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


def seed() -> None:
    engine = sa.create_engine(_database_url(), pool_pre_ping=True, future=True)
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    with engine.begin() as conn:
        existing = conn.execute(
            sa.text("SELECT id FROM tenants WHERE slug = :slug"),
            {"slug": TENANT_SLUG},
        ).fetchone()
        if existing is not None:
            tenant_id = existing.id
        else:
            conn.execute(
                sa.text(
                    "INSERT INTO tenants (id, nombre, slug) VALUES "
                    "(:id, :nombre, :slug)"
                ),
                {
                    "id": tenant_id,
                    "nombre": "Tenant de Carga (THOR)",
                    "slug": TENANT_SLUG,
                },
            )

        existing_user = conn.execute(
            sa.text("SELECT id FROM users WHERE email = :email"),
            {"email": EMAIL},
        ).fetchone()
        if existing_user is None:
            conn.execute(
                sa.text(
                    "INSERT INTO users (id, tenant_id, email, nombre, "
                    "password_hash, rol, activo, created_at, updated_at) VALUES "
                    "(:id, :tenant_id, :email, :nombre, :password_hash, :rol, "
                    "true, now(), now())"
                ),
                {
                    "id": user_id,
                    "tenant_id": tenant_id,
                    "email": EMAIL,
                    "nombre": "Usuario de Carga",
                    "password_hash": hash_password(PASSWORD),
                    "rol": "agente",
                },
            )

        # Un puñado de contactos para que `GET /api/v1/contacts` devuelva
        # una lista no vacía representativa (no relevante para RLS aquí,
        # solo para que la latencia medida incluya la serialización real).
        contacts_count = conn.execute(
            sa.text("SELECT count(*) FROM contacts WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()
        if contacts_count == 0:
            conn.execute(
                sa.text(
                    "INSERT INTO contacts (id, tenant_id, nombre, telefono) "
                    "VALUES (:id, :tenant_id, :nombre, :telefono)"
                ),
                [
                    {
                        "id": uuid.uuid4(),
                        "tenant_id": tenant_id,
                        "nombre": f"Contacto de Carga {i}",
                        "telefono": f"300000{i:04d}",
                    }
                    for i in range(20)
                ],
            )

        # Cuenta de WhatsApp del tenant de carga (SPEC-033): permite que el
        # escenario `WhatsAppWebhookUser` envíe un `phone_number_id` que
        # resuelve a un tenant real vía `resolve_tenant_by_phone_number_id`
        # (SECURITY DEFINER). `ON CONFLICT DO NOTHING` sobre `phone_number_id`
        # (UNIQUE, SPEC-025) hace el seed idempotente entre corridas de CI.
        conn.execute(
            sa.text(
                "INSERT INTO whatsapp_accounts "
                "(id, tenant_id, phone_number_id, display_phone_number, etiqueta) "
                "VALUES (:id, :tenant_id, :phone_number_id, :display_phone_number, "
                "        :etiqueta) "
                "ON CONFLICT (phone_number_id) DO NOTHING"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "phone_number_id": WHATSAPP_PHONE_NUMBER_ID,
                "display_phone_number": "+57 300 000 0000",
                "etiqueta": "Cuenta de carga (THOR/HAWKEYE)",
            },
        )

    print(f"[seed_loadtest_user] tenant_slug={TENANT_SLUG} email={EMAIL} listo.")


if __name__ == "__main__":
    seed()
