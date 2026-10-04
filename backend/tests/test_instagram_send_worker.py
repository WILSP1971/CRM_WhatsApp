"""Tests de `app.workers.instagram_send_worker` — SPEC-089 (F4), ADR-006
ampliado.

MARCADO PARA CI (requiere PostgreSQL real, `tests/conftest.py::
postgres_engine`): se SKIPEA automáticamente sin Postgres accesible. Un
`GraphApiClient` FALSO (`_FakeGraphClient`, subclase mínima sin `httpx`
real) inyectado vía `graph_client=...`: CERO llamadas de red real en toda la
suite (el transporte real ya se cubre con mocks de `httpx.MockTransport` en
`tests/test_instagram_graph_client.py`).

Cubre los criterios de aceptación de SPEC-089 relativos al worker/disparo:
  (a) un mensaje YA aprobado se envía dentro de la ventana estándar (24h,
      sin tag) y el `mid` devuelto queda persistido en `messages.wamid`.
  (b) envío entre 24h y 7 días -> aplica el tag `HUMAN_AGENT`.
  (c) envío a más de 7 días -> BLOQUEADO, `estado_entrega="failed"`, SIN
      invocar al cliente Graph (RF-03).
  (d) reintento/redelivery de un mensaje que YA tiene `wamid` -> no-op
      (idempotencia RF-06), el fake NO se invoca de nuevo.
  (e) error transitorio agotado del cliente Graph -> `estado_entrega=
      "failed"`, sin propagar la excepción (el worker no revienta).
  (f) `_resolve_send_tag` (función pura): verificación directa de las 3
      franjas de ventana.
  (g) sin job en la cola -> nada se procesa (no hay disparo automático).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.instagram_outbound_queue import InstagramOutboundSendJob
from app.integrations.instagram.graph_client import (
    INSTAGRAM_HUMAN_AGENT_TAG,
    GraphApiTransientError,
    GraphSendResult,
)
from app.workers import instagram_send_worker


class _FakeGraphClient:
    """Doble de `GraphApiClient`: NUNCA importa/usa `httpx`. Registra las
    llamadas para que los tests verifiquen tag/texto sin tocar la Graph API
    real."""

    def __init__(
        self, *, mid: str = "mid.FAKE", raise_error: Exception | None = None
    ):
        self.mid = mid
        self.raise_error = raise_error
        self.calls: list[dict] = []

    def send_message(self, **kwargs) -> GraphSendResult:
        self.calls.append(kwargs)
        if self.raise_error:
            raise self.raise_error
        return GraphSendResult(mid=self.mid, raw={"message_id": self.mid})


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


def _crear_instagram_account(engine, tenant_id: uuid.UUID, account_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO instagram_accounts "
                "(id, tenant_id, instagram_business_account_id, activo) "
                "VALUES (:id, :tenant_id, :iaid, true)"
            ),
            {"id": uuid.uuid4(), "tenant_id": tenant_id, "iaid": account_id},
        )


def _crear_contacto(engine, tenant_id: uuid.UUID, sender_id: str) -> uuid.UUID:
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
                "nombre": "Contacto IG Aprobado",
                "telefono": sender_id,
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
                "VALUES (:id, :tenant_id, :contact_id, 'instagram', 'abierta')"
            ),
            {"id": conversation_id, "tenant_id": tenant_id, "contact_id": contact_id},
        )
    return conversation_id


def _crear_mensaje_inbound(
    engine, tenant_id: uuid.UUID, conversation_id: uuid.UUID, *, created_at: datetime
) -> None:
    """Simula el último mensaje ENTRANTE del contacto (base de la ventana de
    mensajería de Instagram, RF-03)."""
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


def _job(*, tenant_id, conversation_id, message_id) -> InstagramOutboundSendJob:
    return InstagramOutboundSendJob(
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
# (f) `_resolve_send_tag` — función pura, las 3 franjas de ventana.
# ---------------------------------------------------------------------------


def test_resolve_send_tag_within_24h_returns_none():
    now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    last_inbound_at = now - timedelta(hours=1)
    assert instagram_send_worker._resolve_send_tag(last_inbound_at, now) is None


def test_resolve_send_tag_between_24h_and_7d_returns_human_agent_tag():
    now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    last_inbound_at = now - timedelta(days=2)
    assert (
        instagram_send_worker._resolve_send_tag(last_inbound_at, now)
        == INSTAGRAM_HUMAN_AGENT_TAG
    )


def test_resolve_send_tag_exactly_24h_boundary_returns_none():
    now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    last_inbound_at = now - timedelta(hours=24)
    assert instagram_send_worker._resolve_send_tag(last_inbound_at, now) is None


def test_resolve_send_tag_exactly_7d_boundary_returns_human_agent_tag():
    now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    last_inbound_at = now - timedelta(days=7)
    assert (
        instagram_send_worker._resolve_send_tag(last_inbound_at, now)
        == INSTAGRAM_HUMAN_AGENT_TAG
    )


def test_resolve_send_tag_beyond_7d_raises_window_blocked():
    now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    last_inbound_at = now - timedelta(days=7, hours=1)
    with pytest.raises(instagram_send_worker.WindowBlockedError):
        instagram_send_worker._resolve_send_tag(last_inbound_at, now)


def test_resolve_send_tag_without_prior_inbound_raises_window_blocked():
    now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(instagram_send_worker.WindowBlockedError):
        instagram_send_worker._resolve_send_tag(None, now)


# ---------------------------------------------------------------------------
# (a) Envío dentro de ventana estándar (24h) -> sin tag
# ---------------------------------------------------------------------------


def test_process_job_within_24h_sends_without_tag_and_persists_mid(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantIgSendWindow")
    _crear_instagram_account(
        postgres_engine, tenant_id, f"iba-{uuid.uuid4().hex[:8]}"
    )
    contact_id = _crear_contacto(postgres_engine, tenant_id, "ig-sender-window")
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
    fake_client = _FakeGraphClient(mid=f"mid.WITHIN-WINDOW-{uuid.uuid4().hex[:10]}")

    instagram_send_worker.process_job(
        _job(
            tenant_id=tenant_id, conversation_id=conversation_id, message_id=message_id
        ),
        session_factory=_session_factory(postgres_engine),
        graph_client=fake_client,
    )

    assert len(fake_client.calls) == 1
    assert fake_client.calls[0]["tag"] is None
    row = _leer_mensaje(postgres_engine, message_id)
    assert row.wamid == fake_client.mid
    assert row.estado_entrega == "enviado"


# ---------------------------------------------------------------------------
# (b) Envío entre 24h y 7 días -> aplica tag HUMAN_AGENT
# ---------------------------------------------------------------------------


def test_process_job_between_24h_and_7d_sends_with_human_agent_tag(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantIgSendTag")
    _crear_instagram_account(
        postgres_engine, tenant_id, f"iba-{uuid.uuid4().hex[:8]}"
    )
    contact_id = _crear_contacto(postgres_engine, tenant_id, "ig-sender-tag")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    _crear_mensaje_inbound(
        postgres_engine,
        tenant_id,
        conversation_id,
        created_at=datetime.now(timezone.utc) - timedelta(days=3),
    )
    message_id = _crear_mensaje_aprobado(
        postgres_engine, tenant_id, conversation_id, contenido="Seguimiento de tu caso."
    )
    fake_client = _FakeGraphClient(mid=f"mid.TAGGED-{uuid.uuid4().hex[:10]}")

    instagram_send_worker.process_job(
        _job(
            tenant_id=tenant_id, conversation_id=conversation_id, message_id=message_id
        ),
        session_factory=_session_factory(postgres_engine),
        graph_client=fake_client,
    )

    assert len(fake_client.calls) == 1
    assert fake_client.calls[0]["tag"] == INSTAGRAM_HUMAN_AGENT_TAG
    row = _leer_mensaje(postgres_engine, message_id)
    assert row.wamid == fake_client.mid
    assert row.estado_entrega == "enviado"


# ---------------------------------------------------------------------------
# (c) Envío a más de 7 días -> bloqueado, failed, sin llamar a Meta
# ---------------------------------------------------------------------------


def test_process_job_beyond_7d_blocks_as_failed_without_calling_graph_api(
    postgres_engine,
):
    tenant_id = _crear_tenant(postgres_engine, "TenantIgSendBlocked")
    _crear_instagram_account(
        postgres_engine, tenant_id, f"iba-{uuid.uuid4().hex[:8]}"
    )
    contact_id = _crear_contacto(postgres_engine, tenant_id, "ig-sender-blocked")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    _crear_mensaje_inbound(
        postgres_engine,
        tenant_id,
        conversation_id,
        created_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    message_id = _crear_mensaje_aprobado(
        postgres_engine, tenant_id, conversation_id, contenido="Mensaje bloqueado."
    )
    fake_client = _FakeGraphClient()

    instagram_send_worker.process_job(
        _job(
            tenant_id=tenant_id, conversation_id=conversation_id, message_id=message_id
        ),
        session_factory=_session_factory(postgres_engine),
        graph_client=fake_client,
    )

    assert fake_client.calls == []
    row = _leer_mensaje(postgres_engine, message_id)
    assert row.wamid is None
    assert row.estado_entrega == "failed"


# ---------------------------------------------------------------------------
# (d) Idempotencia: mensaje YA con mid (wamid) -> no-op, fake NO invocado
# ---------------------------------------------------------------------------


def test_process_job_already_sent_message_is_noop(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantIgSendIdempotent")
    _crear_instagram_account(
        postgres_engine, tenant_id, f"iba-{uuid.uuid4().hex[:8]}"
    )
    contact_id = _crear_contacto(postgres_engine, tenant_id, "ig-sender-idem")
    conversation_id = _crear_conversacion(postgres_engine, tenant_id, contact_id)
    message_id = _crear_mensaje_aprobado(
        postgres_engine, tenant_id, conversation_id, contenido="Ya enviado."
    )
    mid_ya_enviado = f"mid.YA-ENVIADO-{uuid.uuid4().hex[:10]}"
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE messages SET wamid = :mid WHERE id = :id"),
            {"mid": mid_ya_enviado, "id": message_id},
        )
    fake_client = _FakeGraphClient()

    instagram_send_worker.process_job(
        _job(
            tenant_id=tenant_id, conversation_id=conversation_id, message_id=message_id
        ),
        session_factory=_session_factory(postgres_engine),
        graph_client=fake_client,
    )

    assert fake_client.calls == []
    row = _leer_mensaje(postgres_engine, message_id)
    assert row.wamid == mid_ya_enviado


# ---------------------------------------------------------------------------
# (e) Error transitorio agotado -> failed, sin propagar excepción
# ---------------------------------------------------------------------------


def test_process_job_transient_error_marks_failed_without_raising(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantIgSendTransientError")
    _crear_instagram_account(
        postgres_engine, tenant_id, f"iba-{uuid.uuid4().hex[:8]}"
    )
    contact_id = _crear_contacto(postgres_engine, tenant_id, "ig-sender-transient")
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

    instagram_send_worker.process_job(
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
# (g) Sin job en la cola -> nada se procesa (no hay disparo automático)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_one_empty_queue_returns_false_no_send_attempted():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    result = await instagram_send_worker.drain_one(redis_client, timeout_seconds=0)

    assert result is False
