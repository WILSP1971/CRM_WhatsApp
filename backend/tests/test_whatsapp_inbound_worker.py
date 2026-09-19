"""Tests de `app.workers.whatsapp_inbound_worker` — SPEC-027/SPEC-028, ADR-007/008.

Requiere PostgreSQL real (`tests/conftest.py::postgres_engine`) CON la
función `resolve_tenant_by_phone_number_id` (migración `54c75efefe3c`) ya
aplicada — `postgres_engine` corre `alembic upgrade head` automáticamente.
Se SKIPEA automáticamente sin Postgres accesible (mismo patrón que
`tests/test_rag_ingest_worker.py`/`tests/test_sentiment_worker.py`).
`fakeredis` para la cola de sentimiento y `FakeAIClient` (SPEC-017) para el
LLM/embeddings local: CERO llamadas externas/red real en toda la suite.

Cubre (SPEC-027):
  (a) evento con `phone_number_id` conocido -> resuelve tenant y persiste
      bajo RLS (contacto + conversación + mensaje `canal="whatsapp"`).
  (b) IDEMPOTENCIA: el MISMO `wamid` procesado dos veces -> un solo mensaje
      (segundo no-op).
  (c) `phone_number_id` desconocido -> no escribe nada, no revienta
      (descarte auditado).
  (d) aislamiento: el mensaje persistido bajo el tenant A no es visible
      consultando con RLS fijado al tenant B.
  (e) la resolución de tenant usa la función SQL `resolve_tenant_by_phone_
      number_id` (SECURITY DEFINER) y NO un SELECT directo sobre
      `whatsapp_accounts` (que fallaría/devolvería 0 filas bajo RLS con el
      rol de app sin `app.tenant_id` fijado, ADR-008).

Cubre (SPEC-028, pipeline IA local disparado desde la ingesta):
  (f) un mensaje entrante de WhatsApp encola sentimiento (SPEC-018,
      best-effort, no bloquea la persistencia).
  (g) se genera Y PERSISTE un `rag_draft` en estado `propuesto` con ≥3 citas
      trazables (SPEC-017/019), NUNCA enviado automáticamente.
  (h) modo degradado: si el LLM local no está disponible o no hay contexto
      suficiente, el mensaje sigue persistido y no se crea ningún borrador.
  (i) aislamiento por tenant del borrador generado.
  (j) cero llamadas externas: `FakeAIClient`/`fakeredis` nunca abren red.
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

from app.core.whatsapp_queue import InboundWebhookJob, enqueue_inbound_webhook_event
from app.db.session import set_tenant_session
from app.services.ai_service import AIServiceUnavailableError
from app.services.rag.ingest_service import ingest_document
from app.workers.whatsapp_inbound_worker import drain_one, process_job
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


def _crear_whatsapp_account(
    engine, tenant_id: uuid.UUID, phone_number_id: str, *, activo: bool = True
) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO whatsapp_accounts "
                "(id, tenant_id, phone_number_id, activo) "
                "VALUES (:id, :tenant_id, :pni, :activo)"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "pni": phone_number_id,
                "activo": activo,
            },
        )


def _session_factory(postgres_engine):
    def _factory() -> Session:
        return Session(postgres_engine)

    return _factory


def _inbound_job(
    *,
    phone_number_id: str,
    wamid: str,
    wa_id: str = "573001112233",
    texto: str = "hola",
) -> InboundWebhookJob:
    raw_body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "biz-1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": phone_number_id},
                                "contacts": [
                                    {"wa_id": wa_id, "profile": {"name": "Cliente"}}
                                ],
                                "messages": [
                                    {
                                        "id": wamid,
                                        "from": wa_id,
                                        "type": "text",
                                        "text": {"body": texto},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )
    return InboundWebhookJob(raw_body=raw_body)


# ---------------------------------------------------------------------------
# (a) phone_number_id conocido -> resuelve tenant y persiste bajo RLS
# ---------------------------------------------------------------------------


def test_process_job_known_phone_number_id_persists_message(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaKnownPni")
    phone_number_id = f"pni-known-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    job = _inbound_job(
        phone_number_id=phone_number_id, wamid=wamid, texto="Hola equipo"
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
                "  WHERE m.wamid = :wamid"
                ") sub"
            ),
            {"wamid": wamid},
        ).one_or_none()

    assert row is not None, "El mensaje con ese wamid debe existir"
    assert row.tenant_id == tenant_id
    assert row.remitente == "contacto"
    assert row.contenido == "Hola equipo"
    assert row.canal_conv == "whatsapp"
    assert row.wamid == wamid
    assert row.estado_entrega == "enviado"


def test_process_job_creates_contact_by_wa_id(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaContact")
    phone_number_id = f"pni-contact-{uuid.uuid4().hex[:10]}"
    wa_id = f"5730099{uuid.uuid4().hex[:5]}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    job = _inbound_job(
        phone_number_id=phone_number_id,
        wamid=f"wamid.{uuid.uuid4().hex}",
        wa_id=wa_id,
    )

    process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT tenant_id, telefono, nombre FROM contacts WHERE telefono = :wa_id"
            ),
            {"wa_id": wa_id},
        ).one_or_none()

    assert row is not None
    assert row.tenant_id == tenant_id
    assert row.nombre == "Cliente"


# ---------------------------------------------------------------------------
# (b) idempotencia: mismo wamid dos veces -> un solo mensaje
# ---------------------------------------------------------------------------


def test_process_job_duplicate_wamid_is_noop(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaDup")
    phone_number_id = f"pni-dup-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    job = _inbound_job(phone_number_id=phone_number_id, wamid=wamid)

    process_job(job, session_factory=_session_factory(postgres_engine))
    # Reentrega de Meta: mismo wamid, procesado de nuevo.
    process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid},
        ).scalar_one()

    assert count == 1, "Un wamid reentregado no debe crear un segundo mensaje"


def test_process_job_duplicate_wamid_does_not_duplicate_conversation(postgres_engine):
    """Reprocesar el mismo wamid tampoco debe crear una segunda conversación
    ni un segundo contacto (no-op completo, no solo a nivel de mensaje)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantWaDupConv")
    phone_number_id = f"pni-dupconv-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    wa_id = f"5730088{uuid.uuid4().hex[:5]}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    job = _inbound_job(phone_number_id=phone_number_id, wamid=wamid, wa_id=wa_id)

    process_job(job, session_factory=_session_factory(postgres_engine))
    process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        contacts_count = conn.execute(
            sa.text("SELECT count(*) FROM contacts WHERE telefono = :wa_id"),
            {"wa_id": wa_id},
        ).scalar_one()

    assert contacts_count == 1


# ---------------------------------------------------------------------------
# (b-bis) IDEMPOTENCIA BAJO CONCURRENCIA REAL (hallazgo MAYOR de BLACK
# PANTHER en SPEC-027, pendiente de verificación por HAWKEYE en SPEC-033):
# los tests anteriores ejercen `process_job` dos veces de forma SECUENCIAL
# en el mismo hilo/conexión — eso solo prueba la guarda de aplicación
# (`_message_wamid_exists`), NUNCA la condición de carrera real entre dos
# workers/reintentos concurrentes que consultan la guarda "al mismo tiempo"
# y ambos la ven en `False` antes de que cualquiera haga commit.
#
# Este test dispara DOS HILOS con DOS CONEXIONES/Sesiones INDEPENDIENTES
# (cada una su propia `Session(postgres_engine)`, su propia transacción),
# sincronizados con una `threading.Barrier` para que ambos entren a
# `process_job` para el MISMO `wamid` lo más simultáneamente posible.
# La garantía dura esperada (ADR-007) es la restricción UNIQUE de BD
# (`uq_messages_wamid`, `app/models/message.py`): quien pierde la carrera
# debe recibir `IntegrityError`, capturado explícitamente en
# `_process_message_event` (`whatsapp_inbound_duplicate_wamid_race_
# detected`) y tratado como no-op sin propagar la excepción ni tumbar el
# hilo. Verde real = count(*) == 1 tras la concurrencia (no una carrera que
# "por suerte" no colisionó: se repite varias veces para reducir el riesgo
# de falso verde por scheduling).
# ---------------------------------------------------------------------------


def test_process_job_duplicate_wamid_concurrent_threads_creates_only_one_message(
    postgres_engine,
):
    """Dos hilos con conexiones independientes procesan el MISMO wamid en
    paralelo real: la restricción UNIQUE de BD debe garantizar count == 1,
    y ambos hilos deben retornar sin excepción (una de las dos ramas gana la
    inserción, la otra cae en el `except IntegrityError` de no-op)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantWaConcurrentDup")
    phone_number_id = f"pni-conc-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    wa_id = f"5730077{uuid.uuid4().hex[:5]}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    job = _inbound_job(phone_number_id=phone_number_id, wamid=wamid, wa_id=wa_id)

    # Barrera de 2: cada hilo abre su PROPIA Session/conexión (no comparte
    # nada con el otro hilo, igual que dos procesos worker reales) y espera
    # a que el otro también esté listo, para maximizar la ventana de carrera
    # justo antes/durante la comprobación de idempotencia + insert.
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _run_once() -> None:
        try:
            barrier.wait(timeout=5)
            process_job(job, session_factory=_session_factory(postgres_engine))
        except (
            BaseException
        ) as exc:  # noqa: BLE001 — capturado para reportar en el hilo principal
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_run_once) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)

    assert not errors, (
        "process_job NO debe propagar excepciones bajo la carrera de wamid "
        f"concurrente (IntegrityError debe capturarse como no-op): {errors!r}"
    )

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid},
        ).scalar_one()

    assert count == 1, (
        "FUGA DE IDEMPOTENCIA BAJO CONCURRENCIA: dos hilos procesando el "
        "mismo wamid en paralelo crearon más de un mensaje (o cero) — la "
        "restricción UNIQUE de BD + el manejo de IntegrityError no están "
        "garantizando la idempotencia real ante condiciones de carrera."
    )

    with postgres_engine.connect() as conn:
        contacts_count = conn.execute(
            sa.text("SELECT count(*) FROM contacts WHERE telefono = :wa_id"),
            {"wa_id": wa_id},
        ).scalar_one()
        conversations_count = conn.execute(
            sa.text(
                "SELECT count(*) FROM conversations WHERE contact_id IN "
                "(SELECT id FROM contacts WHERE telefono = :wa_id)"
            ),
            {"wa_id": wa_id},
        ).scalar_one()

    assert contacts_count == 1, "La carrera no debe duplicar el contacto"
    assert conversations_count == 1, "La carrera no debe duplicar la conversación"


# ---------------------------------------------------------------------------
# (c) phone_number_id desconocido -> no escribe, no revienta
# ---------------------------------------------------------------------------


def test_process_job_unknown_phone_number_id_discards_without_writing(postgres_engine):
    unknown_pni = f"pni-unknown-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"

    job = _inbound_job(phone_number_id=unknown_pni, wamid=wamid)

    process_job(
        job, session_factory=_session_factory(postgres_engine)
    )  # no debe lanzar

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid},
        ).scalar_one()

    assert count == 0, "phone_number_id sin mapeo no debe persistir ningún mensaje"


def test_process_job_inactive_whatsapp_account_discards_without_writing(
    postgres_engine,
):
    """Una cuenta dada de baja (`activo=false`) no debe resolver tenant
    (mismo criterio que `resolve_tenant_by_phone_number_id`, ADR-008)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantWaInactivo")
    phone_number_id = f"pni-inactive-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id, activo=False)

    job = _inbound_job(phone_number_id=phone_number_id, wamid=wamid)

    process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid},
        ).scalar_one()

    assert count == 0


# ---------------------------------------------------------------------------
# (d) aislamiento cross-tenant
# ---------------------------------------------------------------------------


def test_process_job_message_not_visible_from_other_tenant_session(
    postgres_engine, app_engine
):
    tenant_a = _crear_tenant(postgres_engine, "TenantWaAislA")
    tenant_b = _crear_tenant(postgres_engine, "TenantWaAislB")
    phone_number_id = f"pni-aisl-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_a, phone_number_id)

    job = _inbound_job(phone_number_id=phone_number_id, wamid=wamid)
    process_job(job, session_factory=_session_factory(postgres_engine))

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(tenant_b))
            rows = conn.execute(
                sa.text("SELECT id FROM messages WHERE wamid = :wamid"),
                {"wamid": wamid},
            ).fetchall()

    assert (
        rows == []
    ), "FUGA CROSS-TENANT: el tenant B no debe ver el mensaje del tenant A"

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(tenant_a))
            rows = conn.execute(
                sa.text("SELECT id FROM messages WHERE wamid = :wamid"),
                {"wamid": wamid},
            ).fetchall()

    assert len(rows) == 1, "El tenant A (dueño real) sí debe ver su propio mensaje"


# ---------------------------------------------------------------------------
# (e) la resolución usa la función SECURITY DEFINER, no un SELECT directo
# ---------------------------------------------------------------------------


def test_process_job_uses_security_definer_function_with_app_role(
    postgres_engine, app_engine
):
    """Ejerce `process_job` conectado con el rol de aplicación real
    (`omnicore_app`, ADR-008) para probar que la resolución de tenant
    funciona de verdad bajo RLS (no un falso positivo con el owner)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantWaAppRole")
    phone_number_id = f"pni-approle-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    def _app_session_factory():
        return Session(app_engine)

    job = _inbound_job(phone_number_id=phone_number_id, wamid=wamid)
    process_job(job, session_factory=_app_session_factory)

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT tenant_id FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid},
        ).one_or_none()

    assert row is not None, (
        "Con el rol omnicore_app (RLS real), la resolución vía función "
        "SECURITY DEFINER debe seguir permitiendo persistir el mensaje "
        "bajo el tenant correcto"
    )
    assert row.tenant_id == tenant_id


def test_resolve_tenant_uses_function_not_direct_select():
    """Verificación por inspección (criterio ADR-008 punto 2): el worker
    invoca `resolve_tenant_by_phone_number_id` vía SQL, nunca un SELECT
    directo sobre `whatsapp_accounts` para la resolución pre-tenant."""
    import inspect

    from app.workers import whatsapp_inbound_worker as worker_module

    source = inspect.getsource(worker_module._resolve_tenant_id)
    assert "resolve_tenant_by_phone_number_id" in source
    assert "FROM whatsapp_accounts" not in source


# ---------------------------------------------------------------------------
# Robustez (RNF-05 / hallazgo M-1 BLACK WIDOW): fallo en un evento no tumba
# el worker ni bloquea eventos siguientes.
# ---------------------------------------------------------------------------


def test_process_job_malformed_payload_does_not_raise(postgres_engine):
    job = InboundWebhookJob(raw_body="{esto no es json valido")

    process_job(
        job, session_factory=_session_factory(postgres_engine)
    )  # no debe lanzar


def test_process_job_continues_after_one_message_fails(postgres_engine, monkeypatch):
    """Si un mensaje individual del evento falla al procesarse, los demás
    mensajes del mismo evento se siguen procesando (no se aborta el batch)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantWaPartialFail")
    phone_number_id = f"pni-partial-{uuid.uuid4().hex[:10]}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    wamid_ok_1 = f"wamid.{uuid.uuid4().hex}"
    wamid_ok_2 = f"wamid.{uuid.uuid4().hex}"

    raw_body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "biz-1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": phone_number_id},
                                "contacts": [{"wa_id": "573001110001"}],
                                "messages": [
                                    {
                                        "id": wamid_ok_1,
                                        "from": "573001110001",
                                        "type": "text",
                                        "text": {"body": "primero"},
                                    },
                                    {
                                        "id": wamid_ok_2,
                                        "from": "573001110002",
                                        "type": "text",
                                        "text": {"body": "segundo"},
                                    },
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )
    job = InboundWebhookJob(raw_body=raw_body)

    from app.workers import whatsapp_inbound_worker as worker_module

    original = worker_module._get_or_create_contact
    calls = {"n": 0}

    def _flaky_get_or_create_contact(db, *, tenant_id, wa_id, contact_name):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("fallo simulado en el primer mensaje")
        return original(db, tenant_id=tenant_id, wa_id=wa_id, contact_name=contact_name)

    monkeypatch.setattr(
        worker_module, "_get_or_create_contact", _flaky_get_or_create_contact
    )

    process_job(job, session_factory=_session_factory(postgres_engine))

    with postgres_engine.connect() as conn:
        count_ok_2 = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid_ok_2},
        ).scalar_one()
        count_ok_1 = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid_ok_1},
        ).scalar_one()

    assert count_ok_1 == 0, "El mensaje que falló no debe haberse persistido"
    assert (
        count_ok_2 == 1
    ), "El segundo mensaje debe procesarse pese al fallo del primero"


# ---------------------------------------------------------------------------
# End-to-end ligero: drain_one consumiendo de una cola fakeredis real
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_one_consumes_queue_and_persists(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaDrainOne")
    phone_number_id = f"pni-drain-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = _inbound_job(phone_number_id=phone_number_id, wamid=wamid)
    await enqueue_inbound_webhook_event(redis_client, raw_body=job.raw_body)

    processed = await drain_one(
        redis_client, session_factory=_session_factory(postgres_engine)
    )

    assert processed is True

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid},
        ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_drain_one_empty_queue_returns_false():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    processed = await drain_one(redis_client)

    assert processed is False


# ---------------------------------------------------------------------------
# SPEC-028: disparo del pipeline IA local (sentimiento SPEC-018 + borrador
# RAG SPEC-019) desde la ingesta de WhatsApp.
# ---------------------------------------------------------------------------


def _indexar_documento_tenant(
    postgres_engine, tenant_id: uuid.UUID, *, texto: str
) -> tuple[uuid.UUID, FakeAIClient]:
    """Crea un documento indexado (≥3 chunks) para `tenant_id` reutilizando
    `ingest_document` (SPEC-017), MISMO patrón que
    `tests/test_rag_draft_service.py::_crear_tenant_con_documento_indexado`,
    para que `generate_rag_draft` tenga contexto real recuperable."""
    document_id = uuid.uuid4()
    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO documents (id, tenant_id, nombre_archivo, tipo, estado) "
                "VALUES (:id, :tenant_id, 'manual-wa.txt', 'txt', 'pendiente')"
            ),
            {"id": document_id, "tenant_id": tenant_id},
        )

    ai_client = FakeAIClient()
    with Session(postgres_engine) as db:
        with db.begin():
            set_tenant_session(db, str(tenant_id))
            ingest_document(
                db, ai_client, document_id=document_id, text=texto, chunk_size=100
            )
    return document_id, ai_client


def _get_message_id(postgres_engine, wamid: str) -> uuid.UUID:
    with postgres_engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT id FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid},
        ).scalar_one()


# (f) mensaje entrante de WhatsApp dispara sentimiento (best-effort, no bloquea)


@pytest.mark.asyncio
async def test_process_job_dispatches_sentiment_job_on_inbound_message(
    postgres_engine,
):
    """Al persistir un mensaje `canal="whatsapp"` entrante se encola un job
    de sentimiento (SPEC-018) en la MISMA cola Redis que WebChat/REST."""
    from app.core.sentiment_queue import dequeue_sentiment_job

    tenant_id = _crear_tenant(postgres_engine, "TenantWaSentiment")
    phone_number_id = f"pni-sent-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = _inbound_job(phone_number_id=phone_number_id, wamid=wamid, texto="Hola")

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=redis_client,
        ai_client=FakeAIClient(unavailable=True),  # RAG degradado, no interfiere
    )

    sentiment_job = await dequeue_sentiment_job(
        redis_client, tenant_id=tenant_id, timeout_seconds=0
    )
    assert sentiment_job is not None, "Debe haberse encolado un job de sentimiento"
    assert sentiment_job.message_id == str(_get_message_id(postgres_engine, wamid))
    assert sentiment_job.tenant_id == str(tenant_id)


def test_process_job_sentiment_enqueue_failure_does_not_block_ingestion(
    postgres_engine, monkeypatch
):
    """Modo degradado (c): si el encolado de sentimiento falla (Redis caído),
    el mensaje entrante YA PERSISTIDO no se ve afectado (best-effort)."""
    from app.workers import whatsapp_inbound_worker as worker_module

    tenant_id = _crear_tenant(postgres_engine, "TenantWaSentimentDown")
    phone_number_id = f"pni-sentdown-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    class _BrokenRedis:
        async def rpush(self, *args, **kwargs):
            raise ConnectionError("redis caído (simulado)")

    monkeypatch.setattr(
        worker_module,
        "AIClient",
        lambda *a, **k: FakeAIClient(unavailable=True),
    )

    job = _inbound_job(phone_number_id=phone_number_id, wamid=wamid)

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=_BrokenRedis(),
    )  # no debe lanzar

    with postgres_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid},
        ).scalar_one()
    assert count == 1, "El mensaje debe seguir persistido pese al fallo de Redis"


# (g) se genera/persiste el borrador RAG en estado propuesto, con ≥3 citas


def test_process_job_creates_proposed_rag_draft_with_citations(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaDraft")
    phone_number_id = f"pni-draft-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    texto = (
        "Horario de atención: lunes a viernes de 8am a 6pm. "
        "Política de reembolsos: 30 días calendario desde la compra. "
        "Canal de soporte prioritario: WhatsApp Business verificado. "
        "Garantía extendida disponible para productos electrónicos. "
    ) * 5
    document_id, ai_client = _indexar_documento_tenant(
        postgres_engine, tenant_id, texto=texto
    )

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = _inbound_job(
        phone_number_id=phone_number_id,
        wamid=wamid,
        texto="¿Cuál es el horario de atención?",
    )

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
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
        assert citation["source"] == "manual-wa.txt"
        assert citation["excerpt"].strip() != ""
        assert 0.0 <= citation["similarityScore"] <= 1.0
        assert uuid.UUID(citation["document_id"]) == document_id


# (h) modo degradado: LLM no disponible / sin contexto -> no rompe la ingesta


def test_process_job_ai_unavailable_degrades_without_breaking_ingestion(
    postgres_engine,
):
    """R-21: si el LLM local no responde, NO se crea el borrador pero el
    mensaje entrante sigue persistido (modo degradado, sin 500/romper)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantWaDraftDown")
    phone_number_id = f"pni-draftdown-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = _inbound_job(phone_number_id=phone_number_id, wamid=wamid)

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=redis_client,
        ai_client=FakeAIClient(unavailable=True),
    )  # no debe lanzar AIServiceUnavailableError

    with postgres_engine.connect() as conn:
        message_count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid},
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
    """Sin documentos indexados para el tenant (<3 chunks recuperables), no
    se genera el borrador pero la ingesta del mensaje no se ve afectada."""
    tenant_id = _crear_tenant(postgres_engine, "TenantWaDraftSinContexto")
    phone_number_id = f"pni-draftsc-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = _inbound_job(phone_number_id=phone_number_id, wamid=wamid)

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=redis_client,
        ai_client=FakeAIClient(),
    )

    with postgres_engine.connect() as conn:
        message_count = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid},
        ).scalar_one()
        draft_count = conn.execute(
            sa.text("SELECT count(*) FROM rag_drafts WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()

    assert message_count == 1
    assert draft_count == 0


# (i) aislamiento por tenant del borrador generado


def test_process_job_rag_draft_not_visible_from_other_tenant(
    postgres_engine, app_engine
):
    tenant_a = _crear_tenant(postgres_engine, "TenantWaDraftAislA")
    tenant_b = _crear_tenant(postgres_engine, "TenantWaDraftAislB")
    phone_number_id = f"pni-draftaisl-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_a, phone_number_id)

    texto = (
        "Horario de atención: lunes a viernes de 8am a 6pm. "
        "Política de reembolsos: 30 días calendario desde la compra. "
        "Canal de soporte prioritario: WhatsApp Business verificado. "
    ) * 5
    _, ai_client = _indexar_documento_tenant(postgres_engine, tenant_a, texto=texto)

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = _inbound_job(
        phone_number_id=phone_number_id, wamid=wamid, texto="horario de atención"
    )
    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=redis_client,
        ai_client=ai_client,
    )

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(tenant_b))
            rows = conn.execute(sa.text("SELECT id FROM rag_drafts")).fetchall()
    assert rows == [], "FUGA CROSS-TENANT: el tenant B no debe ver el borrador del A"

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(tenant_a))
            rows = conn.execute(sa.text("SELECT id FROM rag_drafts")).fetchall()
    assert len(rows) == 1, "El tenant A (dueño real) sí debe ver su propio borrador"


# (j) cero llamadas externas: FakeAIClient nunca abre red real (por construcción,
# ver tests/rag_ai_client_fake.py); se verifica aquí que el worker SOLO usa
# el `ai_client`/`redis_client` inyectados, nunca instancia un cliente propio
# cuando se le pasan dobles explícitos.


def test_process_job_uses_injected_ai_client_never_opens_real_network(
    postgres_engine,
):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaNoEgress")
    phone_number_id = f"pni-noegress-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    texto = (
        "Horario de atención: lunes a viernes de 8am a 6pm. "
        "Política de reembolsos: 30 días calendario desde la compra. "
        "Canal de soporte prioritario: WhatsApp Business verificado. "
    ) * 5
    _, ai_client = _indexar_documento_tenant(postgres_engine, tenant_id, texto=texto)

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    job = _inbound_job(
        phone_number_id=phone_number_id, wamid=wamid, texto="horario de atención"
    )

    process_job(
        job,
        session_factory=_session_factory(postgres_engine),
        redis_client=redis_client,
        ai_client=ai_client,
    )

    # El `FakeAIClient` inyectado registra sus propias llamadas: si el
    # worker hubiera instanciado un `AIClient()` real en su lugar, estas
    # listas seguirían vacías (prueba indirecta de que se usó el inyectado,
    # nunca un cliente que abriría HTTP real hacia `ia_internal`/Ollama).
    assert (
        ai_client.chat_calls
    ), "El borrador debió generarse con el ai_client inyectado"
    assert ai_client.embed_calls, "La recuperación debió usar el ai_client inyectado"


def test_ai_service_error_is_ai_service_unavailable_error_subclass():
    """Verificación por inspección: el modo degradado del worker captura
    `AIServiceError` (clase base de `ai_service.py`), que cubre tanto
    `AIServiceUnavailableError` como `AIServiceResponseError` — ningún error
    de IA local puede escapar sin ser tratado como degradado."""
    assert issubclass(AIServiceUnavailableError, Exception)


# ---------------------------------------------------------------------------
# SPEC-030 — statuses de entrega (sent/delivered/read/failed)
# ---------------------------------------------------------------------------


def _crear_conversacion_y_contacto(engine, tenant_id: uuid.UUID) -> uuid.UUID:
    contact_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO contacts (id, tenant_id, nombre, telefono) "
                "VALUES (:id, :tenant_id, 'Cliente Saliente', :telefono)"
            ),
            {
                "id": contact_id,
                "tenant_id": tenant_id,
                "telefono": f"57300{uuid.uuid4().hex[:7]}",
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO conversations (id, tenant_id, contact_id, canal, estado) "
                "VALUES (:id, :tenant_id, :contact_id, 'whatsapp', 'abierta')"
            ),
            {"id": conversation_id, "tenant_id": tenant_id, "contact_id": contact_id},
        )
    return conversation_id


def _crear_mensaje_saliente(
    engine,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    wamid: str,
    estado_entrega: str = "enviado",
) -> uuid.UUID:
    """Crea un mensaje SALIENTE (`remitente="agente"`) ya conciliado con un
    `wamid` de Meta (SPEC-029), mismo estado inicial que deja
    `wa_send_worker` tras un envío exitoso, para ejercer los callbacks de
    estado de SPEC-030 sin depender del worker de envío."""
    message_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO messages "
                "(id, tenant_id, conversation_id, remitente, contenido, "
                " estado_entrega, wamid) "
                "VALUES (:id, :tenant_id, :conversation_id, 'agente', "
                " 'mensaje saliente de prueba', :estado_entrega, :wamid)"
            ),
            {
                "id": message_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "estado_entrega": estado_entrega,
                "wamid": wamid,
            },
        )
    return message_id


def _status_job(
    *,
    phone_number_id: str,
    wamid: str,
    status: str,
    errors: list[dict] | None = None,
) -> InboundWebhookJob:
    value = {
        "metadata": {"phone_number_id": phone_number_id},
        "statuses": [
            {
                "id": wamid,
                "status": status,
                "timestamp": "1700000000",
                **({"errors": errors} if errors is not None else {}),
            }
        ],
    }
    raw_body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {"id": "biz-1", "changes": [{"field": "messages", "value": value}]}
            ],
        }
    )
    return InboundWebhookJob(raw_body=raw_body)


def _get_estado_entrega(engine, message_id: uuid.UUID) -> str:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT estado_entrega FROM messages WHERE id = :id"),
            {"id": message_id},
        ).scalar_one()


# (a) delivered/read actualiza estado_entrega del mensaje por wamid


def test_process_job_status_delivered_updates_estado_entrega(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaStatusDelivered")
    phone_number_id = f"pni-status-del-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.out.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)
    conversation_id = _crear_conversacion_y_contacto(postgres_engine, tenant_id)
    message_id = _crear_mensaje_saliente(
        postgres_engine, tenant_id, conversation_id, wamid=wamid
    )

    job = _status_job(phone_number_id=phone_number_id, wamid=wamid, status="delivered")
    process_job(job, session_factory=_session_factory(postgres_engine))

    assert _get_estado_entrega(postgres_engine, message_id) == "entregado"


def test_process_job_status_read_updates_estado_entrega(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaStatusRead")
    phone_number_id = f"pni-status-read-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.out.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)
    conversation_id = _crear_conversacion_y_contacto(postgres_engine, tenant_id)
    message_id = _crear_mensaje_saliente(
        postgres_engine,
        tenant_id,
        conversation_id,
        wamid=wamid,
        estado_entrega="entregado",
    )

    job = _status_job(phone_number_id=phone_number_id, wamid=wamid, status="read")
    process_job(job, session_factory=_session_factory(postgres_engine))

    assert _get_estado_entrega(postgres_engine, message_id) == "leido"


# (b) monotonicidad: un delivered tras un read no retrocede


def test_process_job_status_delivered_after_read_does_not_regress(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaStatusMonoton")
    phone_number_id = f"pni-status-mono-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.out.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)
    conversation_id = _crear_conversacion_y_contacto(postgres_engine, tenant_id)
    message_id = _crear_mensaje_saliente(
        postgres_engine,
        tenant_id,
        conversation_id,
        wamid=wamid,
        estado_entrega="leido",
    )

    # "delivered" reentregado/desordenado DESPUÉS de "read" ya aplicado.
    job = _status_job(phone_number_id=phone_number_id, wamid=wamid, status="delivered")
    process_job(job, session_factory=_session_factory(postgres_engine))

    assert _get_estado_entrega(postgres_engine, message_id) == "leido", (
        "Un status 'delivered' fuera de orden tras 'read' NO debe retroceder "
        "el estado (monotonicidad, R-33)"
    )


# (c) failed marca fallido + motivo (sin PII) registrado en logs


def test_process_job_status_failed_marks_message_failed(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaStatusFailed")
    phone_number_id = f"pni-status-failed-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.out.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)
    conversation_id = _crear_conversacion_y_contacto(postgres_engine, tenant_id)
    message_id = _crear_mensaje_saliente(
        postgres_engine, tenant_id, conversation_id, wamid=wamid
    )

    job = _status_job(
        phone_number_id=phone_number_id,
        wamid=wamid,
        status="failed",
        errors=[{"code": 131026, "title": "Message undeliverable"}],
    )
    process_job(job, session_factory=_session_factory(postgres_engine))

    assert _get_estado_entrega(postgres_engine, message_id) == "failed"


def test_process_job_status_failed_is_terminal_ignores_later_progress(
    postgres_engine,
):
    """Un status de progresión (`delivered`) que llega DESPUÉS de un `failed`
    ya aplicado no debe revivir el mensaje (failed es terminal, RF-02)."""
    tenant_id = _crear_tenant(postgres_engine, "TenantWaStatusFailedTerminal")
    phone_number_id = f"pni-status-failterm-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.out.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)
    conversation_id = _crear_conversacion_y_contacto(postgres_engine, tenant_id)
    message_id = _crear_mensaje_saliente(
        postgres_engine, tenant_id, conversation_id, wamid=wamid
    )

    process_job(
        _status_job(phone_number_id=phone_number_id, wamid=wamid, status="failed"),
        session_factory=_session_factory(postgres_engine),
    )
    process_job(
        _status_job(phone_number_id=phone_number_id, wamid=wamid, status="delivered"),
        session_factory=_session_factory(postgres_engine),
    )

    assert _get_estado_entrega(postgres_engine, message_id) == "failed"


# (d) status de wamid desconocido -> no-op sin romper


def test_process_job_status_unknown_wamid_is_noop(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaStatusUnknown")
    phone_number_id = f"pni-status-unk-{uuid.uuid4().hex[:10]}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)

    job = _status_job(
        phone_number_id=phone_number_id,
        wamid=f"wamid.out.nunca-existio.{uuid.uuid4().hex}",
        status="delivered",
    )

    process_job(
        job, session_factory=_session_factory(postgres_engine)
    )  # no debe lanzar


def test_process_job_status_unmapped_phone_number_id_is_noop(postgres_engine):
    unknown_pni = f"pni-status-nopni-{uuid.uuid4().hex[:10]}"

    job = _status_job(
        phone_number_id=unknown_pni,
        wamid=f"wamid.out.{uuid.uuid4().hex}",
        status="delivered",
    )

    process_job(
        job, session_factory=_session_factory(postgres_engine)
    )  # no debe lanzar


# (e) aislamiento por tenant: un wamid de otro tenant no se ve afectado


def test_process_job_status_does_not_cross_tenants(postgres_engine):
    tenant_a = _crear_tenant(postgres_engine, "TenantWaStatusAislA")
    tenant_b = _crear_tenant(postgres_engine, "TenantWaStatusAislB")
    # phone_number_id del callback pertenece al tenant B (simula un status
    # cuyo wamid, por error/colisión, no pertenece al tenant resuelto).
    phone_number_id_b = f"pni-status-aislb-{uuid.uuid4().hex[:10]}"
    _crear_whatsapp_account(postgres_engine, tenant_b, phone_number_id_b)

    wamid = f"wamid.out.{uuid.uuid4().hex}"
    conversation_id_a = _crear_conversacion_y_contacto(postgres_engine, tenant_a)
    message_id = _crear_mensaje_saliente(
        postgres_engine, tenant_a, conversation_id_a, wamid=wamid
    )

    job = _status_job(
        phone_number_id=phone_number_id_b, wamid=wamid, status="delivered"
    )
    process_job(job, session_factory=_session_factory(postgres_engine))

    assert _get_estado_entrega(postgres_engine, message_id) == "enviado", (
        "FUGA CROSS-TENANT: un status resuelto al tenant B no debe alterar "
        "un mensaje del tenant A, aunque comparta wamid"
    )


# (f) idempotencia: mismo status procesado dos veces


def test_process_job_status_duplicate_is_idempotent(postgres_engine):
    tenant_id = _crear_tenant(postgres_engine, "TenantWaStatusDup")
    phone_number_id = f"pni-status-dup-{uuid.uuid4().hex[:10]}"
    wamid = f"wamid.out.{uuid.uuid4().hex}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)
    conversation_id = _crear_conversacion_y_contacto(postgres_engine, tenant_id)
    message_id = _crear_mensaje_saliente(
        postgres_engine, tenant_id, conversation_id, wamid=wamid
    )

    job = _status_job(phone_number_id=phone_number_id, wamid=wamid, status="delivered")
    process_job(job, session_factory=_session_factory(postgres_engine))
    # Reentrega de Meta: el mismo status, procesado de nuevo.
    process_job(job, session_factory=_session_factory(postgres_engine))

    assert _get_estado_entrega(postgres_engine, message_id) == "entregado"


def test_process_job_status_batch_with_message_events_processes_both(
    postgres_engine,
):
    """Un mismo evento de webhook con `messages[]` y `statuses[]` mezclados
    (Meta puede agruparlos) procesa ambos sin que uno bloquee al otro."""
    tenant_id = _crear_tenant(postgres_engine, "TenantWaStatusMixed")
    phone_number_id = f"pni-status-mixed-{uuid.uuid4().hex[:10]}"
    _crear_whatsapp_account(postgres_engine, tenant_id, phone_number_id)
    conversation_id = _crear_conversacion_y_contacto(postgres_engine, tenant_id)
    wamid_out = f"wamid.out.{uuid.uuid4().hex}"
    message_id = _crear_mensaje_saliente(
        postgres_engine, tenant_id, conversation_id, wamid=wamid_out
    )
    wamid_in = f"wamid.in.{uuid.uuid4().hex}"

    raw_body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "biz-1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": phone_number_id},
                                "contacts": [{"wa_id": "573001110099"}],
                                "messages": [
                                    {
                                        "id": wamid_in,
                                        "from": "573001110099",
                                        "type": "text",
                                        "text": {"body": "hola"},
                                    }
                                ],
                                "statuses": [{"id": wamid_out, "status": "delivered"}],
                            },
                        }
                    ],
                }
            ],
        }
    )
    job = InboundWebhookJob(raw_body=raw_body)

    process_job(job, session_factory=_session_factory(postgres_engine))

    assert _get_estado_entrega(postgres_engine, message_id) == "entregado"
    with postgres_engine.connect() as conn:
        count_in = conn.execute(
            sa.text("SELECT count(*) FROM messages WHERE wamid = :wamid"),
            {"wamid": wamid_in},
        ).scalar_one()
    assert count_in == 1
