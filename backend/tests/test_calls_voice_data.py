"""
Tests de SPEC-036 — Datos de voz: `calls` / `call_transcripts` + RLS efectiva
+ idempotencia por `call_id`:

  1. `calls.call_id` tiene restricción de unicidad POR TENANT (RF-02,
     ADR-007) — base de idempotencia del conector de ingesta (SPEC-037,
     fuera de alcance aquí).
  2. `call_transcripts` referencia a `calls` y almacena segmentos con
     inicio/fin/texto/hablante + idioma/modelo STT (RF-02).
  3. `calls`/`call_transcripts` son tenant-scoped y están bajo RLS
     ENABLE+FORCE: un tenant no lee las llamadas/transcripciones de otro
     (RNF-47, R-47) — ejercido con el rol de aplicación NO-superusuario
     `omnicore_app` (ADR-008), no con el owner/superusuario (falso positivo).
  4. Borrado lógico (C2): `activo=false` no elimina la fila; las consultas
     de vigentes lo excluyen.
  5. `calls` enlaza opcionalmente a `conversations` (`canal="voz"`) y a
     `contacts` sin romper el contrato existente de esas tablas (RF-04).

Requiere PostgreSQL real (fixtures de `tests/conftest.py`, SPEC-012/ADR-008).
Si no hay Postgres accesible, se SKIPEAN explícitamente (no se marcan como
aprobados en falso) — correrán en CI contra el `db` del docker-compose.yml.
"""

import json
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.db.rls import TENANT_SCOPED_TABLES
from app.db.session import set_tenant_session


def _insert_conversation(conn, tenant_id, contact_id, canal="voz"):
    conversation_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO conversations (id, tenant_id, contact_id, canal) "
            "VALUES (:id, :tenant_id, :contact_id, :canal)"
        ),
        {
            "id": conversation_id,
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "canal": canal,
        },
    )
    return conversation_id


def _insert_call(
    conn,
    tenant_id,
    call_id_str,
    *,
    conversation_id=None,
    contact_id=None,
    numero="3009998888",
    direccion="entrante",
    estado="finalizada",
    audio_ref=None,
):
    row_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO calls "
            "(id, tenant_id, call_id, numero, direccion, estado, "
            "conversation_id, contact_id, audio_ref) "
            "VALUES (:id, :tenant_id, :call_id, :numero, :direccion, :estado, "
            ":conversation_id, :contact_id, :audio_ref)"
        ),
        {
            "id": row_id,
            "tenant_id": tenant_id,
            "call_id": call_id_str,
            "numero": numero,
            "direccion": direccion,
            "estado": estado,
            "conversation_id": conversation_id,
            "contact_id": contact_id,
            "audio_ref": audio_ref,
        },
    )
    return row_id


# ---------------------------------------------------------------------------
# RF-02: unicidad de calls.call_id (por tenant, idempotencia ADR-007)
# ---------------------------------------------------------------------------


def test_calls_call_id_unique_per_tenant(postgres_engine, two_tenants_with_data):
    """Criterio de aceptación: `call_id` tiene restricción de unicidad — un
    conector de ingesta que reentrega el mismo `call_id` para el mismo
    tenant no puede insertar una segunda fila (idempotencia, ADR-007)."""
    data = two_tenants_with_data
    call_id_str = f"call-dup-{uuid.uuid4().hex[:12]}"

    with postgres_engine.begin() as conn:
        _insert_call(conn, data["tenant_a_id"], call_id_str)

    with pytest.raises(IntegrityError):
        with postgres_engine.begin() as conn:
            _insert_call(conn, data["tenant_a_id"], call_id_str)


def test_calls_call_id_can_repeat_across_different_tenants(
    postgres_engine, two_tenants_with_data
):
    """La unicidad de `call_id` es POR TENANT (no global): dos tenants
    distintos pueden tener, en teoría, el mismo `call_id` de su respectivo
    conector sin colisionar entre sí."""
    data = two_tenants_with_data
    call_id_str = f"call-shared-{uuid.uuid4().hex[:12]}"

    with postgres_engine.begin() as conn:
        _insert_call(conn, data["tenant_a_id"], call_id_str)
        # No debe lanzar IntegrityError: mismo call_id, tenant distinto.
        _insert_call(conn, data["tenant_b_id"], call_id_str)

    with postgres_engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT tenant_id FROM calls WHERE call_id = :call_id"),
            {"call_id": call_id_str},
        ).fetchall()
    assert {r.tenant_id for r in rows} == {data["tenant_a_id"], data["tenant_b_id"]}


# ---------------------------------------------------------------------------
# RF-02: call_transcripts referencia a calls + forma de los segmentos
# ---------------------------------------------------------------------------


def test_call_transcripts_references_call_and_stores_segments(
    postgres_engine, two_tenants_with_data
):
    """`call_transcripts` referencia a `calls` (FK) y almacena segmentos con
    inicio/fin/texto/hablante, además de idioma/modelo STT (RF-02)."""
    data = two_tenants_with_data
    call_id_str = f"call-transcript-{uuid.uuid4().hex[:12]}"

    with postgres_engine.begin() as conn:
        call_row_id = _insert_call(conn, data["tenant_a_id"], call_id_str)

        segmentos = [
            {"inicio": 0.0, "fin": 2.5, "texto": "Hola", "hablante": "agente"},
            {
                "inicio": 2.6,
                "fin": 5.0,
                "texto": "Buenos días",
                "hablante": "contacto",
            },
        ]
        conn.execute(
            sa.text(
                "INSERT INTO call_transcripts "
                "(id, tenant_id, call_id, segmentos, idioma, modelo_stt, wer) "
                "VALUES (:id, :tenant_id, :call_id, :segmentos, :idioma, "
                ":modelo_stt, :wer)"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": data["tenant_a_id"],
                "call_id": call_row_id,
                "segmentos": json.dumps(segmentos),
                "idioma": "es",
                "modelo_stt": "faster-whisper/large-v3",
                "wer": "0.0500",
            },
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT segmentos, idioma, modelo_stt, wer FROM call_transcripts "
                "WHERE call_id = :call_id"
            ),
            {"call_id": call_row_id},
        ).fetchone()

    assert row is not None
    assert row.idioma == "es"
    assert row.modelo_stt == "faster-whisper/large-v3"
    assert float(row.wer) == pytest.approx(0.05)
    stored_segments = row.segmentos
    assert len(stored_segments) == 2
    for segment in stored_segments:
        assert {"inicio", "fin", "texto", "hablante"} <= set(segment.keys())
    assert stored_segments[0]["hablante"] == "agente"
    assert stored_segments[1]["hablante"] == "contacto"


def test_call_transcripts_call_id_unique(postgres_engine, two_tenants_with_data):
    """Una `call` tiene a lo sumo una transcripción vigente (UNIQUE en
    `call_transcripts.call_id`, guarda referencial 1:1 con `calls`)."""
    data = two_tenants_with_data
    call_id_str = f"call-one-transcript-{uuid.uuid4().hex[:10]}"

    with postgres_engine.begin() as conn:
        call_row_id = _insert_call(conn, data["tenant_a_id"], call_id_str)
        conn.execute(
            sa.text(
                "INSERT INTO call_transcripts "
                "(id, tenant_id, call_id, segmentos, idioma, modelo_stt) "
                "VALUES (:id, :tenant_id, :call_id, :segmentos, 'es', 'demo')"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": data["tenant_a_id"],
                "call_id": call_row_id,
                "segmentos": json.dumps([]),
            },
        )

    with pytest.raises(IntegrityError):
        with postgres_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO call_transcripts "
                    "(id, tenant_id, call_id, segmentos, idioma, modelo_stt) "
                    "VALUES (:id, :tenant_id, :call_id, :segmentos, 'es', 'demo')"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": data["tenant_a_id"],
                    "call_id": call_row_id,
                    "segmentos": json.dumps([]),
                },
            )


# ---------------------------------------------------------------------------
# RF-04: enlace opcional a conversations/contacts sin romper el contrato
# ---------------------------------------------------------------------------


def test_calls_links_optionally_to_conversation_and_contact(
    postgres_engine, two_tenants_with_data
):
    """Una `call` puede enlazar a una `conversation` (`canal="voz"`) y a un
    `contact` existentes, reutilizando el contrato ya establecido por esas
    tablas (RF-04), sin requerirlo (ambos son NULLABLE)."""
    data = two_tenants_with_data

    with postgres_engine.begin() as conn:
        conversation_id = _insert_conversation(
            conn, data["tenant_a_id"], data["contact_a_id"], canal="voz"
        )
        call_row_id = _insert_call(
            conn,
            data["tenant_a_id"],
            f"call-linked-{uuid.uuid4().hex[:10]}",
            conversation_id=conversation_id,
            contact_id=data["contact_a_id"],
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT conversation_id, contact_id FROM calls WHERE id = :id"),
            {"id": call_row_id},
        ).fetchone()
    assert row.conversation_id == conversation_id
    assert row.contact_id == data["contact_a_id"]


def test_calls_conversation_and_contact_are_optional(
    postgres_engine, two_tenants_with_data
):
    """Una `call` sin conversación/contacto enlazados (aún) es válida —
    campos NULLABLE (RF-04, no rompe el flujo de ingesta antes de resolver
    el contacto)."""
    data = two_tenants_with_data

    with postgres_engine.begin() as conn:
        call_row_id = _insert_call(
            conn, data["tenant_a_id"], f"call-unlinked-{uuid.uuid4().hex[:10]}"
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT conversation_id, contact_id FROM calls WHERE id = :id"),
            {"id": call_row_id},
        ).fetchone()
    assert row.conversation_id is None
    assert row.contact_id is None


# ---------------------------------------------------------------------------
# RNF-47 / R-47: calls y call_transcripts son tenant-scoped y están bajo RLS
# ---------------------------------------------------------------------------


def test_calls_and_call_transcripts_are_tenant_scoped_tables():
    """`calls`/`call_transcripts` están registradas como tablas tenant-scoped
    (misma fuente de verdad que usa la migración de RLS y los tests de
    aislamiento, evitando que la lista se desincronice)."""
    assert "calls" in TENANT_SCOPED_TABLES
    assert "call_transcripts" in TENANT_SCOPED_TABLES


@pytest.mark.parametrize("table", ["calls", "call_transcripts"])
def test_calls_rls_enabled_and_forced(postgres_engine, table):
    """Criterio de aceptación: RLS ENABLE + FORCE en `calls`/`call_transcripts`
    (igual que el resto de `TENANT_SCOPED_TABLES`, ADR-004/ADR-008)."""
    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE relname = :table"
            ),
            {"table": table},
        ).fetchone()
    assert row is not None, f"{table} no existe"
    row_security_enabled, row_security_forced = row
    assert row_security_enabled is True, f"{table}: RLS no está ENABLE"
    assert row_security_forced is True, f"{table}: RLS no está FORCE"


def test_calls_cross_tenant_isolation(
    postgres_engine, app_engine, two_tenants_with_data
):
    """Criterio de aceptación (RNF-47/R-47): una sesión de tenant A, con el
    rol de aplicación NO-superusuario `omnicore_app` (ADR-008), NO lee las
    `calls` de otro tenant, aunque el SELECT no filtre por `tenant_id`. Debe
    fallar por RLS, no por lógica de aplicación. Con `postgres_engine`
    (owner/superusuario) este test pasaría por accidente (falso positivo,
    hallazgo BLACK PANTHER replicado en ADR-008)."""
    data = two_tenants_with_data
    call_a = f"call-cross-a-{uuid.uuid4().hex[:10]}"
    call_b = f"call-cross-b-{uuid.uuid4().hex[:10]}"

    with postgres_engine.begin() as conn:
        _insert_call(conn, data["tenant_a_id"], call_a)
        _insert_call(conn, data["tenant_b_id"], call_b)

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(data["tenant_a_id"]))
            rows = conn.execute(sa.text("SELECT call_id FROM calls")).fetchall()
            visible = {r.call_id for r in rows}

    assert call_a in visible, "El tenant A debe ver su propia llamada"
    assert (
        call_b not in visible
    ), "FUGA CROSS-TENANT: el tenant A puede ver una llamada del tenant B"


def test_calls_cross_tenant_direct_select_by_id_returns_zero_rows(
    postgres_engine, app_engine, two_tenants_with_data
):
    """Un intento directo de leer, por `id`, la llamada de otro tenant
    (conociendo su UUID) devuelve 0 filas — RLS bloquea por predicado
    `tenant_id`, no por falta de un `WHERE` explícito en la app."""
    data = two_tenants_with_data
    call_b_str = f"call-direct-b-{uuid.uuid4().hex[:10]}"

    with postgres_engine.begin() as conn:
        call_b_row_id = _insert_call(conn, data["tenant_b_id"], call_b_str)

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(data["tenant_a_id"]))
            rows = conn.execute(
                sa.text("SELECT id FROM calls WHERE id = :id"),
                {"id": call_b_row_id},
            ).fetchall()

    assert rows == [], (
        "FUGA CROSS-TENANT: el tenant A pudo leer directamente, por id, una "
        "llamada del tenant B"
    )


def test_call_transcripts_cross_tenant_isolation(
    postgres_engine, app_engine, two_tenants_with_data
):
    """Igual que `calls`, pero para `call_transcripts`: el tenant A no lee
    las transcripciones del tenant B (rol `omnicore_app`, ADR-008)."""
    data = two_tenants_with_data

    with postgres_engine.begin() as conn:
        call_a_row_id = _insert_call(
            conn, data["tenant_a_id"], f"call-t-a-{uuid.uuid4().hex[:10]}"
        )
        call_b_row_id = _insert_call(
            conn, data["tenant_b_id"], f"call-t-b-{uuid.uuid4().hex[:10]}"
        )
        conn.execute(
            sa.text(
                "INSERT INTO call_transcripts "
                "(id, tenant_id, call_id, segmentos, idioma, modelo_stt) "
                "VALUES (:id, :tenant_id, :call_id, :segmentos, 'es', 'demo')"
            ),
            [
                {
                    "id": uuid.uuid4(),
                    "tenant_id": data["tenant_a_id"],
                    "call_id": call_a_row_id,
                    "segmentos": json.dumps([{"texto": "secreto tenant A"}]),
                },
                {
                    "id": uuid.uuid4(),
                    "tenant_id": data["tenant_b_id"],
                    "call_id": call_b_row_id,
                    "segmentos": json.dumps([{"texto": "secreto tenant B"}]),
                },
            ],
        )

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(data["tenant_a_id"]))
            rows = conn.execute(
                sa.text("SELECT segmentos FROM call_transcripts")
            ).fetchall()
            visible_texts = {seg["texto"] for r in rows for seg in r.segmentos}

    assert "secreto tenant A" in visible_texts
    assert "secreto tenant B" not in visible_texts, (
        "FUGA CROSS-TENANT: el tenant A puede leer la transcripción del " "tenant B"
    )


def test_calls_session_without_tenant_sees_zero_rows(
    postgres_engine, app_engine, two_tenants_with_data
):
    """Fail-closed (ADR-004): sin `app.tenant_id` fijado, una sesión con el
    rol de aplicación (`app_engine`, ADR-008) no ve ninguna `call`."""
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        _insert_call(conn, data["tenant_a_id"], f"call-noauth-{uuid.uuid4().hex[:10]}")

    with app_engine.connect() as conn:
        with conn.begin():
            conn.execute(sa.text("RESET app.tenant_id"))
            rows = conn.execute(sa.text("SELECT id FROM calls")).fetchall()
            assert rows == [], "Sesión sin tenant fijado no debe ver ninguna llamada"


# ---------------------------------------------------------------------------
# C2: borrado lógico de calls / call_transcripts
# ---------------------------------------------------------------------------


def test_calls_soft_delete_no_physical_delete(postgres_engine, two_tenants_with_data):
    """C2: dar de baja una llamada es `activo=False`, la fila permanece
    (nunca DELETE físico); las consultas de "vigentes" excluyen inactivas."""
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        call_row_id = _insert_call(
            conn, data["tenant_a_id"], f"call-baja-{uuid.uuid4().hex[:10]}"
        )
        conn.execute(
            sa.text("UPDATE calls SET activo = false WHERE id = :id"),
            {"id": call_row_id},
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT activo FROM calls WHERE id = :id"),
            {"id": call_row_id},
        ).fetchone()
        vigentes = conn.execute(
            sa.text("SELECT id FROM calls WHERE id = :id AND activo = true"),
            {"id": call_row_id},
        ).fetchall()

    assert row is not None, "El borrado lógico no debe eliminar la fila (C2)"
    assert row.activo is False
    assert vigentes == [], "Las consultas de vigentes deben excluir inactivas"


def test_call_transcripts_soft_delete_no_physical_delete(
    postgres_engine, two_tenants_with_data
):
    """C2 aplicado también a `call_transcripts`."""
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        call_row_id = _insert_call(
            conn, data["tenant_a_id"], f"call-t-baja-{uuid.uuid4().hex[:10]}"
        )
        transcript_id = uuid.uuid4()
        conn.execute(
            sa.text(
                "INSERT INTO call_transcripts "
                "(id, tenant_id, call_id, segmentos, idioma, modelo_stt) "
                "VALUES (:id, :tenant_id, :call_id, :segmentos, 'es', 'demo')"
            ),
            {
                "id": transcript_id,
                "tenant_id": data["tenant_a_id"],
                "call_id": call_row_id,
                "segmentos": json.dumps([]),
            },
        )
        conn.execute(
            sa.text("UPDATE call_transcripts SET activo = false WHERE id = :id"),
            {"id": transcript_id},
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT activo FROM call_transcripts WHERE id = :id"),
            {"id": transcript_id},
        ).fetchone()
        vigentes = conn.execute(
            sa.text("SELECT id FROM call_transcripts WHERE id = :id AND activo = true"),
            {"id": transcript_id},
        ).fetchall()

    assert row is not None, "El borrado lógico no debe eliminar la fila (C2)"
    assert row.activo is False
    assert vigentes == [], "Las consultas de vigentes deben excluir inactivas"
