"""
Seed ficticio con ≥2 tenants aislados (SPEC-012, criterio de aceptación) y
routing ficticio de WhatsApp por tenant (SPEC-025, para el simulador).

Uso:
    DATABASE_URL=postgresql+psycopg://... python -m app.db.seed

Inserta datos vía el engine directo (rol de owner de BD), sin fijar
`app.tenant_id` — esto es intencional: el seed es una operación de plataforma
(provisioning), no una operación de un tenant autenticado. La comprobación de
que los datos quedan realmente aislados por RLS se hace en
`tests/test_rls_isolation.py` (fijando `app.tenant_id` de sesión).

Todos los datos son ficticios (sin PII real, sin `phone_number_id`/tokens
reales de Meta), acorde a la clasificación SENSIBLE del proyecto
(`.no-externo`).
"""

import uuid

import sqlalchemy as sa

from app.db.session import engine

SEED_TENANTS = [
    {
        "id": uuid.uuid4(),
        "nombre": "Clínica Demo Norte",
        "slug": "clinica-demo-norte",
        "contacto": {"nombre": "Contacto Ficticio Norte", "telefono": "3001112222"},
        "whatsapp_phone_number_id": "000000000000001",
    },
    {
        "id": uuid.uuid4(),
        "nombre": "Clínica Demo Sur",
        "slug": "clinica-demo-sur",
        "contacto": {"nombre": "Contacto Ficticio Sur", "telefono": "3003334444"},
        "whatsapp_phone_number_id": "000000000000002",
    },
]


def run_seed() -> None:
    with engine.begin() as conn:
        for tenant in SEED_TENANTS:
            conn.execute(
                sa.text(
                    "INSERT INTO tenants (id, nombre, slug) VALUES (:id, :nombre, :slug) "
                    "ON CONFLICT (slug) DO NOTHING"
                ),
                {
                    "id": tenant["id"],
                    "nombre": tenant["nombre"],
                    "slug": tenant["slug"],
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO contacts (id, tenant_id, nombre, telefono) "
                    "VALUES (:id, :tenant_id, :nombre, :telefono) "
                    "ON CONFLICT (tenant_id, telefono) DO NOTHING"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant["id"],
                    "nombre": tenant["contacto"]["nombre"],
                    "telefono": tenant["contacto"]["telefono"],
                },
            )
            # Routing ficticio de WhatsApp (SPEC-025): phone_number_id de
            # prueba -> tenant de prueba, para el simulador del webhook
            # (SPEC-026/027). Sin secretos/tokens reales (C3).
            conn.execute(
                sa.text(
                    "INSERT INTO whatsapp_accounts "
                    "(id, tenant_id, phone_number_id, display_phone_number, etiqueta) "
                    "VALUES (:id, :tenant_id, :phone_number_id, :display_phone_number, "
                    ":etiqueta) "
                    "ON CONFLICT (phone_number_id) DO NOTHING"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant["id"],
                    "phone_number_id": tenant["whatsapp_phone_number_id"],
                    "display_phone_number": "+000000000",
                    "etiqueta": f"Número demo — {tenant['nombre']}",
                },
            )
    print(
        f"Seed completo: {len(SEED_TENANTS)} tenants ficticios con datos disjuntos "
        "y routing de WhatsApp ficticio."
    )


if __name__ == "__main__":
    run_seed()
