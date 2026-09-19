"""Tests de `app.workers.wa_send_worker` — SPEC-029 (F4), ADR-006.

MARCADO PARA CI (requiere PostgreSQL real, `tests/conftest.py::
postgres_engine`, mismo patrón que `test_whatsapp_inbound_worker.py`): se
SKIPEA automáticamente sin Postgres accesible. `fakeredis` para la cola de
envío y un `GraphApiClient` FALSO (`_FakeGraphClient`, subclase mínima sin
`httpx` real) inyectado vía `graph_client=...`: CERO llamadas de red real en
toda la suite (ningún test aquí construye un `httpx.Client` real ni toca
`graph.facebook.com`; el transporte real ya se cubre con mocks de
`httpx.MockTransport` en `tests/test_whatsapp_graph_client.py`).

Cubre los criterios de aceptación de SPEC-029 relativos al worker/disparo:
  (a) un mensaje YA aprobado (creado como si `approve_and_send` lo hubiera
      persistido) se "envía" (el fake registra la llamada) y el `wamid`
      devuelto queda persistido en `messages.wamid`.
  (b) el envío NUNCA se dispara si no hay un job en la cola — es decir, no
      existe ningún camino automático: `process_job` solo actúa sobre un
      job explícito ya encolado tras la aprobación (se verifica que
      `enqueue_outbound_send` es la única forma de generar ese job, ver
      `tests/test_rag_draft_review_api.py` para el disparo end-to-end desde
      el endpoint de aprobación).
  (c) dentro de la ventana de 24h -> texto libre (`send_text_message`
      invocado); fuera de ventana con plantilla configurada -> plantilla
      (`send_template_message` invocado); fuera de ventana SIN plantilla ->
      bloqueado, `estado_entrega="failed"`, SIN invocar al cliente Graph.
  (d) reintento/redelivery de un mensaje que YA tiene `wamid` -> no-op
      (idempotencia RF-04), el fake NO se invoca de nuevo.
  (e) error transitorio agotado del cliente Graph -> `estado_entrega=
      "failed"`, sin propagar la excepción (el worker no revienta).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.whatsapp_outbound_queue import OutboundSendJob
from app.integrations.whatsapp.graph_client import (
    GraphApiTransientError,
    GraphSendResult,
)
from app.workers import wa_send_worker


class _FakeGraphClient:
    """Doble de `GraphApiClient`: NUNCA importa/usa `httpx`. Registra las
    llamadas para que los tests verifiquen texto-libre vs. plantilla sin
    tocar la Graph API real."""

    def __init__(
        self, *, wamid: str = "wamid.FAKE", raise_error: Exception | None = None
    ):
        self.wamid = wamid
        self.raise_error = raise_error
        self.text_calls: list[dict] = []
        self.template_calls: list[dict] = []

    def send_text_message(self, **kwargs) -> GraphSendResult:
        self.text_calls.append(kwargs)
        if self.raise_error:
            raise self.raise_error
        return GraphSendResult(wamid=self.wamid, raw={"messages": [{"id": self.wamid}]})

    def send_template_message(self, **kwargs) -> GraphSendResult:
        self.template_calls.append(kwargs)
        if self.raise_error:
            raise self.raise_error
        return GraphSendResult(wamid=self.wamid, raw={"messages": [{"id": self.wamid}]})


def _session_factory(postgres_engine):
    def _factory() -> Session:
        return Session(postgres_engine)

    return _factory


def _crear_tenant(engine, nombre: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    with engine.begin() as conn:
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


def _crear_whatsapp_account(engine, tenant_id: uuid.UUID, phone_number_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO whatsapp_accounts "
                "(id, tenant_id, phone_number_id, activo) "
                "VALUES (:id, :tenant_id, :pni, true)"
            ),
            {"id": uuid.uuid4(), "tenant_id": tenant_id, "pni": phone_number_id},
        )


def _crear_contacto(engine, tenant_id: uuid.UUID, telefono: str) -> uuid.UUID:
    contact_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO contacts (id, tenant_id, nombre, telefono) "
                "VALUES (:id, :tenant_id, :nombre, :telefono)"
            ),
            {
                "id": contact_id,
                "tenant_id": tenant_id,
                "nombre": "Contacto Aprobado",
                "telefono": telefono,
            },
        )
    return contact_id


def _crear_conversacion(
    engine, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conversations (id, tenant_id, contact_id, canal, estado) "
                "VALUES (:id, :tenant_id, :contact_id, 'whatsapp', 'abierta')"
            ),
            {"id": conversation_id, "tenant_id": tenant_id, "contact_id": contact_id},
        )
    return conversation_id


def _crear_mensaje_inbound(
    engine, tenant_id: uuid.UUID, conversation_id: uuid.UUID, *, created_at: datetime
) -> None:
    """Simula el último mensaje ENTRANTE del contacto (base de la ventana de
    24h, RF-03)."""
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO messages "
                "(id, tenant_id, conversation_id, remitente, contenido, "
                " estado_entrega, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :conversation_id, 'contacto', "
                "        'hola, necesito ayuda', 'enviado', :created_at, :created_at)"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "created_at": created_at,
            },
        )


def _crear_mensaje_aprobado(
    engine, tenant_id: uuid.UUID, conversation_id: uuid.UUID, *, contenido: str
) -> uuid.UUID:
    """Simula el `Message` YA persistido por `approve_and_send` (SPEC-019):
    el worker de envío nunca crea este mensaje, solo lo transporta."""
    message_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO messages "
                "(id, tenant_id, conversation_id, remitente, contenido, estado_entrega) "
                "VALUES (:id, :tenant_id, :conversation_id, 'agente', :contenido, 'enviado')"
            ),
            {
                "id": message_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "contenido": contenido,
            },
        )
    return message_id


def _job(*, tenant_id, conversation_id, message_id) -> OutboundSendJob:
    return OutboundSendJob(
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        message_id=str(message_id),
    )


def _leer_mensaje(engine, message_id: uuid.UUID):
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT wamid, estado_entrega FROM messages WHERE id = :id"),
            {"id": message_id},
        ).one()


# ---------------------------------------------------------------------------
# (a) Envío dentro de ventana (texto libre) -> wamid persistido
# ---------------------------------------------------------------------------


def test_process_job_within_window_sends_text_and_persists_wamid(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaSendWindow")
    _crear_whatsapp_account(postgres_engine, tenant_id, f"pni-{uuid.uuid4().hex[:8]}")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573001112233")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    _crear_mensaje_inbound(
        postgres_engine,
        tenant_id,
        conversation_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    message_id = _crear_mensaje_aprobado(
        postgres_engine, tenant_id, conversation_id, contenido="Su pedido está listo."
    )
    fake_client = _FakeGraphClient(wamid="wamid.WITHIN-WINDOW")

    wa_send_worker.process_job(
        _job(
            tenant_id=tenant_id, conversation_id=conversation_id, message_id=message_id
        ),
        session_factory=_session_factory(postgres_engine),
        graph_client=fake_client,
    )

    assert len(fake_client.text_calls) == 1
    assert fake_client.template_calls == []
    row = _leer_mensaje(postgres_engine, message_id)
    assert row.wamid == "wamid.WITHIN-WINDOW"
    assert row.estado_entrega == "enviado"


# ---------------------------------------------------------------------------
# (c) Fuera de ventana, CON plantilla configurada -> usa plantilla
# ---------------------------------------------------------------------------


def test_process_job_outside_window_with_template_uses_template(
    postgres_engine, monkeypatch
):
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("WHATSAPP_TEMPLATE_NAME", "ventana_utilitaria")
    monkeypatch.setenv("WHATSAPP_TEMPLATE_LANGUAGE", "es")
    get_settings.cache_clear()

    tenant_id = _crear_tenant(postgres_engine, "TenantWaSendTemplate")
    _crear_whatsapp_account(postgres_engine, tenant_id, f"pni-{uuid.uuid4().hex[:8]}")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573001112244")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    _crear_mensaje_inbound(
        postgres_engine,
        tenant_id,
        conversation_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    message_id = _crear_mensaje_aprobado(
        postgres_engine, tenant_id, conversation_id, contenido="Recordatorio de cita."
    )
    fake_client = _FakeGraphClient(wamid="wamid.TEMPLATE-OK")

    try:
        wa_send_worker.process_job(
            _job(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message_id=message_id,
            ),
            session_factory=_session_factory(postgres_engine),
            graph_client=fake_client,
        )
    finally:
        get_settings.cache_clear()

    assert fake_client.text_calls == []
    assert len(fake_client.template_calls) == 1
    assert fake_client.template_calls[0]["template_name"] == "ventana_utilitaria"
    row = _leer_mensaje(postgres_engine, message_id)
    assert row.wamid == "wamid.TEMPLATE-OK"


# ---------------------------------------------------------------------------
# (c) Fuera de ventana, SIN plantilla -> bloqueado, failed, sin llamar a Meta
# ---------------------------------------------------------------------------


def test_process_job_outside_window_without_template_blocks_as_failed(
    postgres_engine, monkeypatch
):
    from app.core.config import get_settings

    monkeypatch.delenv("WHATSAPP_TEMPLATE_NAME", raising=False)
    get_settings.cache_clear()

    tenant_id = _crear_tenant(postgres_engine, "TenantWaSendNoTemplate")
    _crear_whatsapp_account(postgres_engine, tenant_id, f"pni-{uuid.uuid4().hex[:8]}")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573001112255")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    _crear_mensaje_inbound(
        postgres_engine,
        tenant_id,
        conversation_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    message_id = _crear_mensaje_aprobado(
        postgres_engine, tenant_id, conversation_id, contenido="Mensaje bloqueado."
    )
    fake_client = _FakeGraphClient()

    try:
        wa_send_worker.process_job(
            _job(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message_id=message_id,
            ),
            session_factory=_session_factory(postgres_engine),
            graph_client=fake_client,
        )
    finally:
        get_settings.cache_clear()

    assert fake_client.text_calls == []
    assert fake_client.template_calls == []
    row = _leer_mensaje(postgres_engine, message_id)
    assert row.wamid is None
    assert row.estado_entrega == "failed"


# ---------------------------------------------------------------------------
# (d) Idempotencia: mensaje YA con wamid -> no-op, fake NO invocado
# ---------------------------------------------------------------------------


def test_process_job_already_sent_message_is_noop(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaSendIdempotent")
    _crear_whatsapp_account(postgres_engine, tenant_id, f"pni-{uuid.uuid4().hex[:8]}")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573001112266")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    message_id = _crear_mensaje_aprobado(
        postgres_engine, tenant_id, conversation_id, contenido="Ya enviado."
    )
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE messages SET wamid = :wamid WHERE id = :id"),
            {"wamid": "wamid.YA-ENVIADO", "id": message_id},
        )
    fake_client = _FakeGraphClient()

    wa_send_worker.process_job(
        _job(
            tenant_id=tenant_id, conversation_id=conversation_id, message_id=message_id
        ),
        session_factory=_session_factory(postgres_engine),
        graph_client=fake_client,
    )

    assert fake_client.text_calls == []
    assert fake_client.template_calls == []
    row = _leer_mensaje(postgres_engine, message_id)
    assert row.wamid == "wamid.YA-ENVIADO"


# ---------------------------------------------------------------------------
# (e) Error transitorio agotado -> failed, sin propagar excepción
# ---------------------------------------------------------------------------


def test_process_job_transient_error_marks_failed_without_raising(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaSendTransientError")
    _crear_whatsapp_account(postgres_engine, tenant_id, f"pni-{uuid.uuid4().hex[:8]}")
    contact_id = _crear_contacto(postgres_engine, tenant_id, "573001112277")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    _crear_mensaje_inbound(
        postgres_engine,
        tenant_id,
        conversation_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    message_id = _crear_mensaje_aprobado(
        postgres_engine, tenant_id, conversation_id, contenido="Falla transitoria."
    )
    fake_client = _FakeGraphClient(
        raise_error=GraphApiTransientError("429 agotado tras reintentos")
    )

    wa_send_worker.process_job(
        _job(
            tenant_id=tenant_id, conversation_id=conversation_id, message_id=message_id
        ),
        session_factory=_session_factory(postgres_engine),
        graph_client=fake_client,
    )

    row = _leer_mensaje(postgres_engine, message_id)
    assert row.wamid is None
    assert row.estado_entrega == "failed"


# ---------------------------------------------------------------------------
# (b) Sin job en la cola -> nada se procesa (no hay disparo automático)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_one_empty_queue_returns_false_no_send_attempted():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    result = await wa_send_worker.drain_one(redis_client, timeout_seconds=0)

    assert result is False
