"""Tests de `app.workers.sentiment_worker` — SPEC-018.

Requiere PostgreSQL real (`tests/conftest.py::postgres_engine`); se SKIPEA
automáticamente sin Postgres accesible (mismo patrón que
`tests/test_rag_ingest_worker.py`, SPEC-017). `AIClient` MOCKEADO (nunca se
llama al LLM real).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.sentiment_queue import SentimentJob
from app.workers.sentiment_worker import TenantMismatchError, process_job


class _FakeChatResult:
    def __init__(self, content: str):
        self.content = content
        self.model = "qwen2.5-fake"
        self.raw: dict = {}


class _FakeSentimentAIClient:
    """`AIClient` mockeado: nunca abre red, responde una etiqueta fija o
    falla/devuelve basura según el escenario de prueba."""

    def __init__(self, *, response: str | None = None, unavailable: bool = False):
        self._response = response or '{"sentimiento": "positivo", "score": 0.9}'
        self._unavailable = unavailable

    def chat(self, messages, *, model=None, temperature=0.2, stream=False):
        if self._unavailable:
            from app.services.ai_service import AIServiceUnavailableError

            raise AIServiceUnavailableError("servicio de IA no disponible (fake)")
        return _FakeChatResult(self._response)


def _crear_tenant(postgres_engine, nombre: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO tenants (id, nombre, slug) VALUES (:id, :nombre, :slug)"
            ),
            {
                "id": tenant_id,
                "nombre": nombre,
                "slug": f"{nombre.lower()}-{tenant_id.hex[:8]}",
            },
        )
    return tenant_id


def _crear_contacto(postgres_engine, tenant_id: uuid.UUID) -> uuid.UUID:
    contact_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO contacts (id, tenant_id, nombre, telefono) VALUES "
                "(:id, :tenant_id, :nombre, :telefono)"
            ),
            {
                "id": contact_id,
                "tenant_id": tenant_id,
                "nombre": "Contacto de prueba",
                "telefono": f"300{contact_id.int % 10_000_000:07d}",
            },
        )
    return contact_id


def _crear_conversacion(
    postgres_engine, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conversations (id, tenant_id, contact_id, canal, estado) "
                "VALUES (:id, :tenant_id, :contact_id, 'webchat', 'abierta')"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "contact_id": contact_id,
            },
        )
    return conversation_id


def _crear_mensaje(
    postgres_engine,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    contenido: str = "Muchas gracias por la ayuda, excelente atención!",
    activo: bool = True,
) -> uuid.UUID:
    message_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO messages "
                "(id, tenant_id, conversation_id, remitente, contenido, activo) "
                "VALUES (:id, :tenant_id, :conversation_id, 'contacto', :contenido, "
                ":activo)"
            ),
            {
                "id": message_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "contenido": contenido,
                "activo": activo,
            },
        )
    return message_id


def _session_factory(postgres_engine):
    def _factory() -> Session:
        return Session(postgres_engine)

    return _factory


def test_process_job_classifies_and_persists_sentiment(postgres_engine):
    """(a) Caso feliz: clasifica y persiste sentimiento + score."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSentimiento")
    contact_id = _crear_contacto(postgres_engine, tenant_id)
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    message_id = _crear_mensaje(postgres_engine, tenant_id, conversation_id)

    job = SentimentJob(tenant_id=str(tenant_id), message_id=str(message_id))

    process_job(
        job,
        ai_client=_FakeSentimentAIClient(
            response='{"sentimiento": "positivo", "score": 0.93}'
        ),
        session_factory=_session_factory(postgres_engine),
    )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT sentimiento, sentimiento_score FROM messages WHERE id = :id"
            ),
            {"id": message_id},
        ).one()

    assert row.sentimiento == "positivo"
    assert float(row.sentimiento_score) == 0.93


def test_process_job_unparseable_response_does_not_persist_sentiment(postgres_engine):
    """(b) Parsing robusto: respuesta rara del LLM -> fallback, sin romper y
    sin persistir una etiqueta inventada (el mensaje queda sin clasificar)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantRespuestaRara")
    contact_id = _crear_contacto(postgres_engine, tenant_id)
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    message_id = _crear_mensaje(postgres_engine, tenant_id, conversation_id)

    job = SentimentJob(tenant_id=str(tenant_id), message_id=str(message_id))

    process_job(
        job,
        ai_client=_FakeSentimentAIClient(response="no puedo ayudarte con eso"),
        session_factory=_session_factory(postgres_engine),
    )  # no debe lanzar

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT sentimiento, sentimiento_score FROM messages WHERE id = :id"
            ),
            {"id": message_id},
        ).one()

    assert row.sentimiento is None
    assert row.sentimiento_score is None


def test_process_job_rejects_forged_tenant_id_mismatch(postgres_engine):
    """(c) Aislamiento por tenant: un job forjado con tenant_id que no
    coincide con el dueño real del mensaje se rechaza sin fijar RLS."""
    tenant_real = _crear_tenant(postgres_engine, "TenantRealSentimiento")
    tenant_atacante = _crear_tenant(postgres_engine, "TenantAtacanteSentimiento")
    contact_id = _crear_contacto(postgres_engine, tenant_real)
    conversation_id = _crear_conversacion(postgres_engine, tenant_real, contact_id)
    message_id = _crear_mensaje(postgres_engine, tenant_real, conversation_id)

    job_forjado = SentimentJob(
        tenant_id=str(tenant_atacante), message_id=str(message_id)
    )

    try:
        process_job(
            job_forjado,
            ai_client=_FakeSentimentAIClient(),
            session_factory=_session_factory(postgres_engine),
        )
        raised = False
    except TenantMismatchError:
        raised = True

    assert raised, "Un job con tenant_id no coincidente debe ser rechazado"

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT sentimiento FROM messages WHERE id = :id"),
            {"id": message_id},
        ).one()
    assert (
        row.sentimiento is None
    ), "Un job rechazado por tenant_id no coincidente no debe alterar el mensaje"


def test_process_job_degraded_ai_unavailable_does_not_raise(postgres_engine):
    """(d) Modo degradado: si el LLM falla, no bloquea/rompe el worker; el
    mensaje simplemente queda sin sentimiento clasificado."""
    tenant_id = _crear_tenant(postgres_engine, "TenantIACaida")
    contact_id = _crear_contacto(postgres_engine, tenant_id)
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    message_id = _crear_mensaje(postgres_engine, tenant_id, conversation_id)

    job = SentimentJob(tenant_id=str(tenant_id), message_id=str(message_id))

    process_job(
        job,
        ai_client=_FakeSentimentAIClient(unavailable=True),
        session_factory=_session_factory(postgres_engine),
    )  # no debe lanzar

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT sentimiento FROM messages WHERE id = :id"),
            {"id": message_id},
        ).one()
    assert row.sentimiento is None


def test_process_job_unknown_message_does_not_raise(postgres_engine):
    """Un job que referencia un mensaje inexistente no propaga excepción."""
    tenant_id = _crear_tenant(postgres_engine, "TenantSinMensaje")
    job = SentimentJob(tenant_id=str(tenant_id), message_id=str(uuid.uuid4()))

    process_job(
        job,
        ai_client=_FakeSentimentAIClient(),
        session_factory=_session_factory(postgres_engine),
    )  # no debe lanzar


def test_process_job_skips_inactive_message(postgres_engine):
    """C2: un mensaje con borrado lógico no se reclasifica."""
    tenant_id = _crear_tenant(postgres_engine, "TenantMensajeInactivo")
    contact_id = _crear_contacto(postgres_engine, tenant_id)
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    message_id = _crear_mensaje(
        postgres_engine, tenant_id, conversation_id, activo=False
    )

    job = SentimentJob(tenant_id=str(tenant_id), message_id=str(message_id))

    process_job(
        job,
        ai_client=_FakeSentimentAIClient(),
        session_factory=_session_factory(postgres_engine),
    )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT sentimiento FROM messages WHERE id = :id"),
            {"id": message_id},
        ).one()
    assert row.sentimiento is None
