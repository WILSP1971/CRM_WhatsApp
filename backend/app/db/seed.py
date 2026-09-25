"""
Seed ficticio con ≥2 tenants aislados (SPEC-012, criterio de aceptación),
routing ficticio de WhatsApp por tenant (SPEC-025, para el simulador), una
llamada + transcripción ficticias del canal de voz (SPEC-036) y una nota de
voz ficticia de WhatsApp modelada como `Message(tipo="audio")` (SPEC-053,
ADR-013 — NUNCA como `call`/`call_transcript`).

Uso:
    DATABASE_URL=postgresql+psycopg://... python -m app.db.seed

Inserta datos vía el engine directo (rol de owner de BD), sin fijar
`app.tenant_id` — esto es intencional: el seed es una operación de plataforma
(provisioning), no una operación de un tenant autenticado. La comprobación de
que los datos quedan realmente aislados por RLS se hace en
`tests/test_rls_isolation.py` (fijando `app.tenant_id` de sesión).

Todos los datos son ficticios (sin PII real, sin `phone_number_id`/tokens
reales de Meta, sin audio real ni transcripciones reales), acorde a la
clasificación SENSIBLE del proyecto (`.no-externo`).
"""

import json
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
        "pbx_numero_destino": "6011234500",
    },
    {
        "id": uuid.uuid4(),
        "nombre": "Clínica Demo Sur",
        "slug": "clinica-demo-sur",
        "contacto": {"nombre": "Contacto Ficticio Sur", "telefono": "3003334444"},
        "whatsapp_phone_number_id": "000000000000002",
        "pbx_numero_destino": "6019876500",
    },
]


def run_seed() -> None:
    with engine.begin() as conn:
        for index, tenant in enumerate(SEED_TENANTS):
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
            contact_id = uuid.uuid4()
            conn.execute(
                sa.text(
                    "INSERT INTO contacts (id, tenant_id, nombre, telefono) "
                    "VALUES (:id, :tenant_id, :nombre, :telefono) "
                    "ON CONFLICT (tenant_id, telefono) DO NOTHING"
                ),
                {
                    "id": contact_id,
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

            # Routing ficticio de telefonía/PBX (SPEC-037): numero_destino de
            # prueba -> tenant de prueba, para el simulador del conector de
            # ingesta de grabaciones. Sin credenciales/host de PBX reales (C3).
            conn.execute(
                sa.text(
                    "INSERT INTO pbx_lines "
                    "(id, tenant_id, numero_destino, etiqueta) "
                    "VALUES (:id, :tenant_id, :numero_destino, :etiqueta) "
                    "ON CONFLICT (numero_destino) DO NOTHING"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant["id"],
                    "numero_destino": tenant["pbx_numero_destino"],
                    "etiqueta": f"Línea demo — {tenant['nombre']}",
                },
            )

            # Llamada + transcripción ficticias del canal de voz (SPEC-036),
            # solo para el primer tenant de la lista (basta para demostrar el
            # contrato de datos; no es necesario duplicarlo en ambos).
            if index == 0:
                _seed_call_ficticia(conn, tenant["id"], contact_id)
                _seed_whatsapp_nota_voz_ficticia(conn, tenant["id"], contact_id)

    print(
        f"Seed completo: {len(SEED_TENANTS)} tenants ficticios con datos disjuntos, "
        "routing de WhatsApp ficticio, una llamada+transcripción ficticia de voz y "
        "una nota de voz ficticia de WhatsApp (Message tipo=audio, SPEC-053)."
    )


def _seed_call_ficticia(conn: sa.Connection, tenant_id: uuid.UUID, contact_id: uuid.UUID) -> None:
    """Inserta una llamada ficticia + su transcripción de ejemplo (SPEC-036).

    Sin audio real (`audio_ref` es un placeholder de referencia, no un
    binario ni una ruta a un archivo existente) y sin texto de transcripción
    real (frases de ejemplo genéricas), acorde a C3/clasificación SENSIBLE.
    """
    conversation_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO conversations (id, tenant_id, contact_id, canal, estado) "
            "VALUES (:id, :tenant_id, :contact_id, 'voz', 'cerrada') "
            "ON CONFLICT DO NOTHING"
        ),
        {"id": conversation_id, "tenant_id": tenant_id, "contact_id": contact_id},
    )

    call_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO calls "
            "(id, tenant_id, call_id, numero, direccion, duracion, estado, "
            "conversation_id, contact_id, audio_ref) "
            "VALUES (:id, :tenant_id, :call_id, :numero, :direccion, :duracion, "
            ":estado, :conversation_id, :contact_id, :audio_ref) "
            "ON CONFLICT (tenant_id, call_id) DO NOTHING"
        ),
        {
            "id": call_id,
            "tenant_id": tenant_id,
            "call_id": "demo-call-000000001",
            "numero": "3001112222",
            "direccion": "entrante",
            "duracion": 42,
            "estado": "transcrita",
            "conversation_id": conversation_id,
            "contact_id": contact_id,
            "audio_ref": "demo/audio-ficticio-000000001.enc",
        },
    )

    segmentos = json.dumps(
        [
            {
                "inicio": 0.0,
                "fin": 3.2,
                "texto": "Hola, buenos días, ¿en qué le puedo ayudar?",
                "hablante": "agente",
            },
            {
                "inicio": 3.5,
                "fin": 8.1,
                "texto": "Quisiera confirmar mi cita de mañana, por favor.",
                "hablante": "contacto",
            },
        ]
    )
    conn.execute(
        sa.text(
            "INSERT INTO call_transcripts "
            "(id, tenant_id, call_id, segmentos, idioma, modelo_stt) "
            "VALUES (:id, :tenant_id, :call_id, :segmentos, :idioma, :modelo_stt) "
            "ON CONFLICT (call_id) DO NOTHING"
        ),
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "call_id": call_id,
            "segmentos": segmentos,
            "idioma": "es",
            "modelo_stt": "faster-whisper/demo-ficticio",
        },
    )


def _seed_whatsapp_nota_voz_ficticia(
    conn: sa.Connection, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> None:
    """Inserta una conversación de WhatsApp de prueba con un mensaje de texto
    y una nota de voz ficticia (SPEC-053, ADR-013).

    La nota de voz se modela como un `Message(tipo="audio")` real dentro de
    la `Conversation` de WhatsApp — NUNCA como `call`/`call_transcript`
    (ADR-013). `contenido=NULL` (aún sin transcribir, SPEC-056 fuera de
    alcance aquí) y `audio_ref` es un placeholder de referencia, sin binario
    ni ruta real, acorde a C3/clasificación SENSIBLE.
    """
    conversation_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO conversations (id, tenant_id, contact_id, canal, estado) "
            "VALUES (:id, :tenant_id, :contact_id, 'whatsapp', 'abierta') "
            "ON CONFLICT DO NOTHING"
        ),
        {"id": conversation_id, "tenant_id": tenant_id, "contact_id": contact_id},
    )

    # Mensaje de texto de control (canal WhatsApp ya existente, Entregable
    # #3): confirma que `tipo="texto"` sigue poblando `contenido` con
    # normalidad tras la relajación de constraint (RF-03).
    conn.execute(
        sa.text(
            "INSERT INTO messages "
            "(id, tenant_id, conversation_id, remitente, contenido, tipo, "
            "estado_entrega, wamid) "
            "VALUES (:id, :tenant_id, :conversation_id, 'contacto', :contenido, "
            "'texto', 'leido', :wamid) "
            "ON CONFLICT (wamid) DO NOTHING"
        ),
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "contenido": "Hola, quisiera agendar una cita para la próxima semana.",
            "wamid": "wamid.demo-texto-000000001",
        },
    )

    # Nota de voz ficticia (SPEC-053): sin contenido aún, pendiente de
    # transcripción (SPEC-056, fuera de alcance).
    conn.execute(
        sa.text(
            "INSERT INTO messages "
            "(id, tenant_id, conversation_id, remitente, contenido, tipo, "
            "audio_ref, transcripcion_estado, audio_duracion_seg, "
            "estado_entrega, wamid) "
            "VALUES (:id, :tenant_id, :conversation_id, 'contacto', NULL, "
            "'audio', :audio_ref, 'pendiente', :audio_duracion_seg, "
            "'entregado', :wamid) "
            "ON CONFLICT (wamid) DO NOTHING"
        ),
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "audio_ref": "demo/audio-ficticio-whatsapp-000000001.enc",
            "audio_duracion_seg": 12,
            "wamid": "wamid.demo-audio-000000001",
        },
    )


if __name__ == "__main__":
    run_seed()
