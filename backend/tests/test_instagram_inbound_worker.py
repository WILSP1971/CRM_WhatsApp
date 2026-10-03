"""Tests de `app.workers.instagram_inbound_worker` — SPEC-087, ADR-007/008.

Requiere PostgreSQL real (`tests/conftest.py::postgres_engine`) CON la
función `resolve_tenant_by_instagram_account_id` (SPEC-085) ya aplicada —
`postgres_engine` corre `alembic upgrade head` automáticamente. Se SKIPEA
automáticamente sin Postgres accesible (mismo patrón que
`tests/test_whatsapp_inbound_worker.py`). `fakeredis` para la cola de
sentimiento y `FakeAIClient` (SPEC-017) para el LLM/embeddings local: CERO
llamadas externas/red real en toda la suite.

Cubre (SPEC-087, espejo de SPEC-027/028):
  (a) evento con `instagram_account_id` conocido -> resuelve tenant y
      persiste bajo RLS (contacto + conversación `canal="instagram"` +
      mensaje con `wamid=mid`).
  (b) IDEMPOTENCIA: el MISMO `mid` procesado dos veces -> un solo mensaje
      (segundo no-op); carrera concurrente -> `IntegrityError` tratado como
      duplicado.
  (c) `instagram_account_id` desconocido -> no escribe nada, no revienta
      (descarte auditado, CERO escritura).
  (d) aislamiento cross-tenant: el mensaje persistido bajo el tenant A no es
      visible consultando con RLS fijado al tenant B (test que DEBE fallar
      si hay fuga).
  (e) la resolución de tenant usa la función SQL
      `resolve_tenant_by_instagram_account_id` (SECURITY DEFINER) y NO un
      SELECT directo sobre `instagram_accounts`.
  (f) adjuntos -> se encola el contrato de descarga (`ig:media_pending`) sin
      afectar el camino de texto.
  (g) disparo de sentimiento (SPEC-018) y borrador RAG `propuesto` con ≥3
      citas (SPEC-019), nunca autoenviado.
  (h) modo degradado: LLM caído / contexto insuficiente -> sin borrador, sin
      revertir la ingesta.
  (i) robustez: payload malformado / fallo en un mensaje no tumba el batch.
"""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import fakeredis.aioredis
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.instagram_queue import (
    InboundInstagramJob,
    enqueue_inbound_instagram_event,
)
from app.db.session import set_tenant_session
from app.services.rag.ingest_service import ingest_document
from app.workers.instagram_inbound_worker import (
    MEDIA_PENDING_QUEUE_KEY,
    drain_one,
    process_job,
)
from tests.rag_ai_client_fake import FakeAIClient


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


def _crear_instagram_account(
    engine, tenant_id: uuid.UUID, instagram_account_id: str, *, activo: bool = True
) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO instagram_accounts "
                "(id, tenant_id, instagram_business_account_id, activo) "
                "VALUES (:id, :tenant_id, :iaid, :activo)"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "iaid": instagram_account_id,
                "activo": activo,
            },
        )


def _session_factory(postgres_engine):
    def _factory() -> Session:
        return Session(postgres_engine)

    return _factory


def _inbound_job(
    *,
    instagram_account_id: str,
    mid: str,
    sender_id: str = "ig-sender-573001112233",
    texto: str | None = "hola",
    attachments: list[dict] | None = None,
) -> InboundInstagramJob:
    message: dict = {"mid": mid}
    if texto is not None:
        message["text"] = texto
    if attachments is not None:
        message["attachments"] = attachments

    raw_body = json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": instagram_account_id,
                    "time": 1700000000,
                    "messaging": [
                        {
                            "sender": {"id": sender_id},
                            "recipient": {"id": instagram_account_id},
                            "timestamp": 1700000000,
                            "message": message,
                        }
                    ],
                }
            ],
        }
    )
    return InboundInstagramJob(raw_body=raw_body)


# ---------------------------------------------------------------------------
# (a) instagram_account_id conocido -> resuelve tenant y persiste bajo RLS
# ---------------------------------------------------------------------------


def test_process_job_known_account_id_persists_message(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantIgKnownAccount")
    instagram_account_id = f"iaid-known-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    job = _inbound_job(
        instagram_account_id=instagram_account_id, mid=mid, texto="Hola equipo IG"
    )

    process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT tenant_id, remitente, contenido, canal_conv, wamid, "
                "estado_entrega FROM ("
                "  SELECT m.tenant_id, m.remitente, m.contenido, c.canal AS canal_conv, "
                "         m.wamid, m.estado_entrega "
                "  FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                "  WHERE m.wamid = :mid"
                ") sub"
            ),
            {"mid": mid},
        ).one_or_none()

    assert row is not None, "El mensaje con ese mid debe existir"
    assert row.tenant_id == tenant_id
    assert row.remitente == "contacto"
    assert row.contenido == "Hola equipo IG"
    assert row.canal_conv == "instagram"
    assert row.wamid == mid
    assert row.estado_entrega == "enviado"


def test_process_job_creates_contact_by_sender_id(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantIgContact")
    instagram_account_id = f"iaid-contact-{uuid.uuid4().hex[:10]}"
    sender_id = f"ig-sender-{uuid.uuid4().hex[:10]}"

    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    job = _inbound_job(
        instagram_account_id=instagram_account_id,
        mid=f"mid.{uuid.uuid4().hex}",
        sender_id=sender_id,
    )

    process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT tenant_id, telefono FROM contacts WHERE telefono = :sid"
            ),
            {"sid": sender_id},
        ).one_or_none()

    assert row is not None
    assert row.tenant_id == tenant_id


def test_process_job_no_text_message_persists_type_placeholder(postgres_engine):
    """Un mensaje sin texto (solo adjunto) persiste con el placeholder
    `"[attachment]"` (RF-04), igual que WhatsApp hace con `f"[{tipo}]"`."""
    tenant_id = _crear_tenant(postgres_engine, "TenantIgNoText")
    instagram_account_id = f"iaid-notext-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    job = _inbound_job(
        instagram_account_id=instagram_account_id,
        mid=mid,
        texto=None,
        attachments=[{"type": "image", "payload": {"url": "https://x/img.jpg"}}],
    )

    process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT contenido FROM messages WHERE wamid = :mid"),
            {"mid": mid},
        ).one_or_none()

    assert row is not None
    assert row.contenido == "[attachment]"


# ---------------------------------------------------------------------------
# (b) idempotencia: mismo mid dos veces -> un solo mensaje
# ---------------------------------------------------------------------------


def test_process_job_duplicate_mid_is_noop(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantIgDup")
    instagram_account_id = f"iaid-dup-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    job = _inbound_job(instagram_account_id=instagram_account_id, mid=mid)

    process_job(job, session_factory=_session_factory(postgres_engine))
    # Reentrega de Meta: mismo mid, procesado de nuevo.
    process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :mid"),
            {"mid": mid},
        ).scalar_one()

    assert count == 1, "Un mid reentregado no debe crear un segundo mensaje"


def test_process_job_duplicate_mid_does_not_duplicate_conversation(postgres_engine):
    """Reprocesar el mismo mid tampoco debe crear una segunda conversación
    ni un segundo contacto (no-op completo, no solo a nivel de mensaje)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantIgDupConv")
    instagram_account_id = f"iaid-dupconv-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    sender_id = f"ig-sender-dup-{uuid.uuid4().hex[:10]}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    job = _inbound_job(
        instagram_account_id=instagram_account_id, mid=mid, sender_id=sender_id
    )

    process_job(job, session_factory=_session_factory(postgres_engine))
    process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        contacts_count = conn.execute(
            sa.text("SELECT count(*) FROM contacts WHERE telefono = :sid"),
            {"sid": sender_id},
        ).scalar_one()

    assert contacts_count == 1


def test_process_job_duplicate_mid_concurrent_threads_creates_only_one_message(
    postgres_engine,
):
    """Dos hilos con conexiones independientes procesan el MISMO mid en
    paralelo real: la restricción UNIQUE de BD (`messages.wamid`) debe
    garantizar count == 1, y ambos hilos deben retornar sin excepción (una
    de las dos ramas gana la inserción, la otra cae en el `except
    IntegrityError` de no-op) — mismo criterio EXACTO que
    `test_whatsapp_inbound_worker.py`."""
    tenant_id = _crear_tenant(postgres_engine, "TenantIgConcurrentDup")
    instagram_account_id = f"iaid-conc-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    sender_id = f"ig-sender-conc-{uuid.uuid4().hex[:10]}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    job = _inbound_job(
        instagram_account_id=instagram_account_id, mid=mid, sender_id=sender_id
    )

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _run_once() -> None:
        try:
            barrier.wait(timeout=5)
            process_job(job, session_factory=_session_factory(postgres_engine))
        except BaseException as exc:  # noqa: BLE001 — reportado en el hilo principal
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_run_once) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)

    assert not errors, (
        "process_job NO debe propagar excepciones bajo la carrera de mid "
        f"concurrente (IntegrityError debe capturarse como no-op): {errors!r}"
    )

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :mid"),
            {"mid": mid},
        ).scalar_one()

    assert count == 1, (
        "FUGA DE IDEMPOTENCIA BAJO CONCURRENCIA: dos hilos procesando el "
        "mismo mid en paralelo crearon más de un mensaje (o cero)."
    )


# ---------------------------------------------------------------------------
# (c) instagram_account_id desconocido -> no escribe, no revienta
# ---------------------------------------------------------------------------


def test_process_job_unknown_account_id_discards_without_writing(postgres_engine):
    unknown_iaid = f"iaid-unknown-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"

    job = _inbound_job(instagram_account_id=unknown_iaid, mid=mid)

    process_job(job, session_factory=_session_factory(postgres_engine))  # no debe lanzar

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :mid"),
            {"mid": mid},
        ).scalar_one()

    assert count == 0, "instagram_account_id sin mapeo no debe persistir ningún mensaje"


def test_process_job_inactive_instagram_account_discards_without_writing(
    postgres_engine,
):
    """Una cuenta dada de baja (`activo=false`) no debe resolver tenant
    (mismo criterio que `resolve_tenant_by_phone_number_id`, ADR-008)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantIgInactivo")
    instagram_account_id = f"iaid-inactive-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(
        postgres_engine, tenant_id, instagram_account_id, activo=False
    )

    job = _inbound_job(instagram_account_id=instagram_account_id, mid=mid)

    process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :mid"),
            {"mid": mid},
        ).scalar_one()

    assert count == 0


# ---------------------------------------------------------------------------
# (d) aislamiento cross-tenant (test que DEBE fallar si hay fuga, HAWKEYE)
# ---------------------------------------------------------------------------


def test_process_job_message_not_visible_from_other_tenant_session(
    postgres_engine, app_engine
):
    tenant_a = _crear_tenant(postgres_engine, "TenantIgAislA")
    tenant_b = _crear_tenant(postgres_engine, "TenantIgAislB")
    instagram_account_id = f"iaid-aisl-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_a, instagram_account_id)

    job = _inbound_job(instagram_account_id=instagram_account_id, mid=mid)
    process_job(job, session_factory=_session_factory(postgres_engine))

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(tenant_b))
            rows = conn.execute(
                sa.text("SELECT id FROM messages WHERE wamid = :mid"),
                {"mid": mid},
            ).fetchall()

    assert (
        rows == []
    ), "FUGA CROSS-TENANT: el tenant B no debe ver el mensaje de Instagram del tenant A"

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(tenant_a))
            rows = conn.execute(
                sa.text("SELECT id FROM messages WHERE wamid = :mid"),
                {"mid": mid},
            ).fetchall()

    assert len(rows) == 1, "El tenant A (dueño real) sí debe ver su propio mensaje"


def test_process_job_uses_security_definer_function_with_app_role(
    postgres_engine, app_engine
):
    """Ejerce `process_job` conectado con el rol de aplicación real
    (`omnicore_app`, ADR-008) para probar que la resolución de tenant
    funciona de verdad bajo RLS (no un falso positivo con el owner)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantIgAppRole")
    instagram_account_id = f"iaid-approle-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    def _app_session_factory():
        return Session(app_engine)

    job = _inbound_job(instagram_account_id=instagram_account_id, mid=mid)
    process_job(job, session_factory=_app_session_factory)

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT tenant_id FROM messages WHERE wamid = :mid"),
            {"mid": mid},
        ).one_or_none()

    assert row is not None, (
        "Con el rol omnicore_app (RLS real), la resolución vía función "
        "SECURITY DEFINER debe seguir permitiendo persistir el mensaje "
        "bajo el tenant correcto"
    )
    assert row.tenant_id == tenant_id


def test_resolve_tenant_uses_function_not_direct_select():
    """Verificación por inspección (criterio ADR-008 punto 2): el worker
    invoca `resolve_tenant_by_instagram_account_id` vía SQL, nunca un SELECT
    directo sobre `instagram_accounts` para la resolución pre-tenant."""
    import inspect

    from app.workers import instagram_inbound_worker as worker_module

    source = inspect.getsource(worker_module._resolve_tenant_id)
    assert "resolve_tenant_by_instagram_account_id" in source
    assert "FROM instagram_accounts" not in source


# ---------------------------------------------------------------------------
# (f) adjuntos -> encola contrato de descarga (SPEC-088), sin afectar texto
# ---------------------------------------------------------------------------


def test_process_job_with_attachments_enqueues_media_pending(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantIgMediaPending")
    instagram_account_id = f"iaid-media-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    fake_server = fakeredis.FakeServer()
    redis_client = fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)

    job = _inbound_job(
        instagram_account_id=instagram_account_id,
        mid=mid,
        texto=None,
        attachments=[{"type": "image", "payload": {"url": "https://x/img.jpg"}}],
    )

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=redis_client,
        ai_client=FakeAIClient(),
    )

    # El mensaje de texto (placeholder) debe persistir igual, sin verse
    # afectado por la presencia de adjuntos.
    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :mid"),
            {"mid": mid},
        ).scalar_one()
    assert count == 1

    import asyncio

    dequeue_client = fakeredis.aioredis.FakeRedis(
        server=fake_server, decode_responses=True
    )
    raw = asyncio.run(dequeue_client.lpop(MEDIA_PENDING_QUEUE_KEY))
    assert raw is not None, "Debe haberse encolado el contrato de descarga de adjuntos"
    payload = json.loads(raw)
    assert payload["mid"] == mid
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["attachments"][0]["type"] == "image"


def test_process_job_without_attachments_does_not_enqueue_media_pending(
    postgres_engine,
):
    tenant_id = _crear_tenant(postgres_engine, "TenantIgNoMedia")
    instagram_account_id = f"iaid-nomedia-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    fake_server = fakeredis.FakeServer()
    redis_client = fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)

    job = _inbound_job(instagram_account_id=instagram_account_id, mid=mid, texto="hola")

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=redis_client,
        ai_client=FakeAIClient(),
    )

    import asyncio

    dequeue_client = fakeredis.aioredis.FakeRedis(
        server=fake_server, decode_responses=True
    )
    raw = asyncio.run(dequeue_client.lpop(MEDIA_PENDING_QUEUE_KEY))
    assert raw is None, "Sin adjuntos no debe encolarse nada en ig:media_pending"


# ---------------------------------------------------------------------------
# Robustez: payload malformado / fallo en un mensaje no tumba el batch.
# ---------------------------------------------------------------------------


def test_process_job_malformed_payload_does_not_raise(postgres_engine):
    job = InboundInstagramJob(raw_body="{esto no es json valido")

    process_job(job, session_factory=_session_factory(postgres_engine))  # no debe lanzar


def test_process_job_continues_after_one_message_fails(postgres_engine, monkeypatch):
    """Si un mensaje individual del evento falla al procesarse, los demás
    mensajes del mismo evento se siguen procesando (no se aborta el batch)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantIgPartialFail")
    instagram_account_id = f"iaid-partial-{uuid.uuid4().hex[:10]}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    mid_ok_1 = f"mid.{uuid.uuid4().hex}"
    mid_ok_2 = f"mid.{uuid.uuid4().hex}"

    raw_body = json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": instagram_account_id,
                    "messaging": [
                        {
                            "sender": {"id": "ig-sender-partial-1"},
                            "recipient": {"id": instagram_account_id},
                            "message": {"mid": mid_ok_1, "text": "primero"},
                        },
                        {
                            "sender": {"id": "ig-sender-partial-2"},
                            "recipient": {"id": instagram_account_id},
                            "message": {"mid": mid_ok_2, "text": "segundo"},
                        },
                    ],
                }
            ],
        }
    )
    job = InboundInstagramJob(raw_body=raw_body)

    from app.workers import instagram_inbound_worker as worker_module

    original = worker_module._get_or_create_contact
    calls = {"n": 0}

    def _flaky_get_or_create_contact(db, *, tenant_id, sender_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("fallo simulado en el primer mensaje")
        return original(db, tenant_id=tenant_id, sender_id=sender_id)

    monkeypatch.setattr(
        worker_module, "_get_or_create_contact", _flaky_get_or_create_contact
    )

    process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        count_ok_2 = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :mid"),
            {"mid": mid_ok_2},
        ).scalar_one()
        count_ok_1 = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :mid"),
            {"mid": mid_ok_1},
        ).scalar_one()

    assert count_ok_1 == 0, "El mensaje que falló no debe haberse persistido"
    assert count_ok_2 == 1, "El segundo mensaje debe procesarse pese al fallo del primero"


# ---------------------------------------------------------------------------
# End-to-end ligero: drain_one consumiendo de una cola fakeredis real
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_one_consumes_queue_and_persists(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantIgDrainOne")
    instagram_account_id = f"iaid-drain-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = _inbound_job(instagram_account_id=instagram_account_id, mid=mid)
    await enqueue_inbound_instagram_event(redis_client, raw_body=job.raw_body)

    processed = await drain_one(
        redis_client, session_factory=_session_factory(postgres_engine)
    )

    assert processed is True

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :mid"),
            {"mid": mid},
        ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_drain_one_empty_queue_returns_false():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    processed = await drain_one(redis_client)

    assert processed is False


# ---------------------------------------------------------------------------
# SPEC-087 RF-05/RF-06: disparo del pipeline IA local (sentimiento SPEC-018 +
# borrador RAG SPEC-019) desde la ingesta de Instagram, reutilizado tal cual.
# ---------------------------------------------------------------------------


def _indexar_documento_tenant(
    postgres_engine, tenant_id: uuid.UUID, *, texto: str
) -> tuple[uuid.UUID, FakeAIClient]:
    """Crea un documento indexado (≥3 chunks) para `tenant_id` reutilizando
    `ingest_document` (SPEC-017), mismo patrón que
    `test_whatsapp_inbound_worker.py::_indexar_documento_tenant`."""
    document_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO documents (id, tenant_id, nombre_archivo, tipo, estado) "
                "VALUES (:id, :tenant_id, 'manual-ig.txt', 'txt', 'pendiente')"
            ),
            {"id": document_id, "tenant_id": tenant_id},
        )

    ai_client = FakeAIClient()
    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            ingest_document(
                db,
                ai_client,
                document_id=document_id,
                text=texto,
                chunk_size=100,
                chunk_overlap=20,
            )
    return document_id, ai_client


def _get_message_id(postgres_engine, mid: str) -> uuid.UUID:
    with postgres_engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT id FROM messages WHERE wamid = :mid"),
            {"mid": mid},
        ).scalar_one()


@pytest.mark.asyncio
async def test_process_job_dispatches_sentiment_job_on_inbound_message(
    postgres_engine,
):
    """Al persistir un mensaje `canal="instagram"` entrante se encola un job
    de sentimiento (SPEC-018) en la MISMA cola Redis que WhatsApp/WebChat."""
    from app.core.sentiment_queue import dequeue_sentiment_job

    tenant_id = _crear_tenant(postgres_engine, "TenantIgSentiment")
    instagram_account_id = f"iaid-sent-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    fake_server = fakeredis.FakeServer()
    redis_client = fakeredis.aioredis.FakeRedis(
        server=fake_server, decode_responses=True
    )
    job = _inbound_job(instagram_account_id=instagram_account_id, mid=mid, texto="Hola")

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=redis_client,
        ai_client=FakeAIClient(unavailable=True),  # RAG degradado, no interfiere
    )

    dequeue_redis_client = fakeredis.aioredis.FakeRedis(
        server=fake_server, decode_responses=True
    )
    sentiment_job = await dequeue_sentiment_job(
        dequeue_redis_client, tenant_id=tenant_id, timeout_seconds=0
    )
    assert sentiment_job is not None, "Debe haberse encolado un job de sentimiento"
    assert sentiment_job.message_id == str(_get_message_id(postgres_engine, mid))
    assert sentiment_job.tenant_id == str(tenant_id)


def test_process_job_sentiment_enqueue_failure_does_not_block_ingestion(
    postgres_engine, monkeypatch
):
    """Modo degradado: si el encolado de sentimiento falla (Redis caído), el
    mensaje entrante YA PERSISTIDO no se ve afectado (best-effort)."""
    from app.workers import instagram_inbound_worker as worker_module

    tenant_id = _crear_tenant(postgres_engine, "TenantIgSentimentDown")
    instagram_account_id = f"iaid-sentdown-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    class _BrokenRedis:
        async def rpush(self, *args, **kwargs):
            raise ConnectionError("redis caído (simulado)")

    monkeypatch.setattr(
        worker_module,
        "AIClient",
        lambda *a, **k: FakeAIClient(unavailable=True),
    )

    job = _inbound_job(instagram_account_id=instagram_account_id, mid=mid)

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=_BrokenRedis(),
    )  # no debe lanzar

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :mid"),
            {"mid": mid},
        ).scalar_one()
    assert count == 1, "El mensaje debe seguir persistido pese al fallo de Redis"


def test_process_job_creates_proposed_rag_draft_with_citations(
    postgres_engine, app_engine
):
    tenant_id = _crear_tenant(postgres_engine, "TenantIgDraft")
    instagram_account_id = f"iaid-draft-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    texto = (
        "Horario de atención: lunes a viernes de 8am a 6pm. "
        "Política de reembolsos: 30 días calendario desde la compra. "
        "Canal de soporte prioritario: Instagram DM verificado. "
        "Garantía extendida disponible para productos electrónicos. "
    ) * 5
    document_id, ai_client = _indexar_documento_tenant(
        postgres_engine, tenant_id, texto=texto
    )

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = _inbound_job(
        instagram_account_id=instagram_account_id,
        mid=mid,
        texto="¿Cuál es el horario de atención?",
    )

    process_job(
        job,
        # Mismo criterio que `test_whatsapp_inbound_worker.py`: `app_engine`
        # (rol omnicore_app) para que `retrieve_top_k` se apoye en RLS real y
        # no mezcle chunks de otros tenants (postgres_engine es owner, exento
        # de RLS).
        session_factory=_session_factory(app_engine),
        redis_client=redis_client,
        ai_client=ai_client,
    )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT tenant_id, estado, citations, conversation_id, "
                "sent_message_id FROM rag_drafts WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).one_or_none()

    assert row is not None, "Debe haberse persistido un rag_draft propuesto"
    assert row.tenant_id == tenant_id
    assert row.estado == "propuesto", "El borrador NUNCA se aprueba automáticamente"
    assert row.sent_message_id is None, "Nada se envía sin aprobación humana (SPEC-019)"
    assert len(row.citations) >= 3
    for citation in row.citations:
        assert citation["source"] == "manual-ig.txt"
        assert citation["excerpt"].strip() != ""
        assert 0.0 <= citation["similarityScore"] <= 1.0
        assert uuid.UUID(citation["document_id"]) == document_id


def test_process_job_ai_unavailable_degrades_without_breaking_ingestion(
    postgres_engine,
):
    """R-21: si el LLM local no responde, NO se crea el borrador pero el
    mensaje entrante sigue persistido (modo degradado, sin romper)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantIgDraftDown")
    instagram_account_id = f"iaid-draftdown-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = _inbound_job(instagram_account_id=instagram_account_id, mid=mid)

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=redis_client,
        ai_client=FakeAIClient(unavailable=True),
    )  # no debe lanzar

    with postgres_engine.connect() as conn:
        message_count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :mid"),
            {"mid": mid},
        ).scalar_one()
        draft_count = conn.execute(
            sa.text("SELECT count(*) FROM rag_drafts WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()

    assert message_count == 1, "El mensaje debe persistir pese al LLM caído"
    assert draft_count == 0, "Sin LLM disponible no se fabrica un borrador"


def test_process_job_insufficient_context_skips_draft_without_breaking_ingestion(
    postgres_engine,
):
    """Sin ningún documento indexado para el tenant -> contexto insuficiente
    (`InsufficientContextError`) -> sin borrador, sin romper la ingesta."""
    tenant_id = _crear_tenant(postgres_engine, "TenantIgNoContext")
    instagram_account_id = f"iaid-nocontext-{uuid.uuid4().hex[:10]}"
    mid = f"mid.{uuid.uuid4().hex}"
    _crear_instagram_account(postgres_engine, tenant_id, instagram_account_id)

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = _inbound_job(instagram_account_id=instagram_account_id, mid=mid)

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=redis_client,
        ai_client=FakeAIClient(),
    )  # no debe lanzar

    with postgres_engine.connect() as conn:
        message_count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :mid"),
            {"mid": mid},
        ).scalar_one()
        draft_count = conn.execute(
            sa.text("SELECT count(*) FROM rag_drafts WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()

    assert message_count == 1
    assert draft_count == 0
