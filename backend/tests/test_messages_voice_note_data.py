"""
Tests de SPEC-053 — Extensión aditiva de `messages` para la nota de voz de
WhatsApp (`tipo="audio"` + `audio_ref`, ADR-013):

  1. `messages.contenido` es NULLABLE tras la migración (807a0756643c): un
     `Message(tipo="audio", contenido=None)` se inserta sin violar constraint
     (RF-01/criterio de aceptación).
  2. `messages.tipo`/`audio_ref`/`transcripcion_estado`/`audio_duracion_seg`
     existen como columnas nullable y aceptan los valores documentados en
     `app/models/message.py` (RF-01/RF-04).
  3. Sin regresión del canal de texto (RNF-64, R-70): un `Message(tipo=
     "texto")` sigue poblando `contenido` con normalidad.
  4. RLS efectiva (RNF-47, R-47): con el rol de aplicación NO-superusuario
     `omnicore_app` (ADR-008), un tenant no lee el `Message`/`audio_ref` de
     audio de otro tenant — ejercido con `app_engine`, NUNCA con
     `postgres_engine` (mismo patrón que `test_calls_voice_data.py`, tras el
     hallazgo BLACK PANTHER de ADR-008/SPEC-041 de que ejercer RLS con el
     rol owner/superusuario produce falsos positivos).
  5. Borrado lógico (C2): `activo=false` no elimina la fila del `Message` de
     audio; las consultas de vigentes lo excluyen.
  6. NO se crea/toca ninguna tabla `call`/`call_transcript` (ADR-013): la
     nota de voz vive exclusivamente en `messages`.

Requiere PostgreSQL real (fixtures de `tests/conftest.py`, SPEC-012/ADR-008).
Si no hay Postgres accesible, se SKIPEAN explícitamente (no se marcan como
aprobados en falso) — correrán en CI contra el `db` del docker-compose.yml.
"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.db.rls import TENANT_SCOPED_TABLES
from app.db.session import set_tenant_session
from app.models.message import (
    TIPOS_MENSAJE_VALIDOS,
    TRANSCRIPCION_ESTADOS_VALIDOS,
)


def _insert_conversation(conn, tenant_id, contact_id, canal="whatsapp"):
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


def _insert_audio_message(
    conn,
    tenant_id,
    conversation_id,
    *,
    wamid=None,
    audio_ref="demo/audio-test.enc",
    transcripcion_estado="pendiente",
    audio_duracion_seg=9,
    remitente="contacto",
):
    row_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO messages "
            "(id, tenant_id, conversation_id, remitente, contenido, tipo, "
            "audio_ref, transcripcion_estado, audio_duracion_seg, wamid) "
            "VALUES (:id, :tenant_id, :conversation_id, :remitente, NULL, "
            "'audio', :audio_ref, :transcripcion_estado, :audio_duracion_seg, "
            ":wamid)"
        ),
        {
            "id": row_id,
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "remitente": remitente,
            "audio_ref": audio_ref,
            "transcripcion_estado": transcripcion_estado,
            "audio_duracion_seg": audio_duracion_seg,
            "wamid": wamid or f"wamid.audio-{uuid.uuid4().hex[:16]}",
        },
    )
    return row_id


def _insert_text_message(conn, tenant_id, conversation_id, *, contenido="hola"):
    row_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO messages "
            "(id, tenant_id, conversation_id, remitente, contenido, tipo) "
            "VALUES (:id, :tenant_id, :conversation_id, 'contacto', "
            ":contenido, 'texto')"
        ),
        {
            "id": row_id,
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "contenido": contenido,
        },
    )
    return row_id


# ---------------------------------------------------------------------------
# RF-01: contenido nullable + tipo/audio_ref/transcripcion_estado/duracion
# ---------------------------------------------------------------------------


def test_message_audio_with_null_contenido_inserts_without_violating_constraint(
    postgres_engine, two_tenants_with_data
):
    """Criterio de aceptación: un `Message(tipo="audio", contenido=None)` se
    inserta sin violar constraint (RF-01, relajación de `contenido` a
    NULLABLE)."""
    data = two_tenants_with_data

    with postgres_engine.begin() as conn:
        conversation_id = _insert_conversation(
            conn, data["tenant_a_id"], data["contact_a_id"]
        )
        message_id = _insert_audio_message(
            conn, data["tenant_a_id"], conversation_id
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT contenido, tipo, audio_ref, transcripcion_estado, "
                "audio_duracion_seg FROM messages WHERE id = :id"
            ),
            {"id": message_id},
        ).fetchone()

    assert row is not None
    assert row.contenido is None
    assert row.tipo == "audio"
    assert row.audio_ref == "demo/audio-test.enc"
    assert row.transcripcion_estado == "pendiente"
    assert row.audio_duracion_seg == 9


def test_tipo_and_transcripcion_estado_valores_validos_documentados():
    """Las constantes de valores válidos existen y coinciden con la SPEC
    (RF-01/RF-04): mismo patrón que `SENTIMIENTOS_VALIDOS`/
    `ESTADOS_ENTREGA_VALIDOS` ya documentado en el modelo."""
    assert TIPOS_MENSAJE_VALIDOS == {"texto", "audio"}
    assert TRANSCRIPCION_ESTADOS_VALIDOS == {
        "pendiente",
        "ok",
        "descartada_por_duracion",
        "error",
    }


# ---------------------------------------------------------------------------
# RF-03/RNF-64/R-70: sin regresión del canal de texto
# ---------------------------------------------------------------------------


def test_message_texto_sigue_poblando_contenido_sin_regresion(
    postgres_engine, two_tenants_with_data
):
    """Un `Message(tipo="texto")` sigue poblando `contenido` con normalidad
    tras la relajación de la columna a NULLABLE (RNF-64, R-70: no hay
    regresión del canal de texto de WhatsApp #3)."""
    data = two_tenants_with_data

    with postgres_engine.begin() as conn:
        conversation_id = _insert_conversation(
            conn, data["tenant_a_id"], data["contact_a_id"]
        )
        message_id = _insert_text_message(
            conn,
            data["tenant_a_id"],
            conversation_id,
            contenido="Quisiera confirmar mi cita",
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT contenido, tipo, audio_ref FROM messages WHERE id = :id"
            ),
            {"id": message_id},
        ).fetchone()

    assert row.contenido == "Quisiera confirmar mi cita"
    assert row.tipo == "texto"
    assert row.audio_ref is None


def test_message_texto_sin_contenido_sigue_siendo_invalido_a_nivel_de_app(
    postgres_engine, two_tenants_with_data
):
    """La relajación de `contenido` a NULLABLE es a nivel de esquema (para
    permitir el `Message(tipo="audio")` sin transcripción todavía); a nivel
    de esquema puro un `Message(tipo="texto", contenido=NULL)` también
    podría insertarse (SQL puro no impone la regla de negocio) — se deja
    constancia explícita de que la validación semántica "texto siempre trae
    contenido" es responsabilidad de la capa de servicio (SPEC-028/055, fuera
    de alcance de esta SPEC de datos), no del esquema."""
    data = two_tenants_with_data

    with postgres_engine.begin() as conn:
        conversation_id = _insert_conversation(
            conn, data["tenant_a_id"], data["contact_a_id"]
        )
        row_id = uuid.uuid4()
        conn.execute(
            sa.text(
                "INSERT INTO messages "
                "(id, tenant_id, conversation_id, remitente, contenido, tipo) "
                "VALUES (:id, :tenant_id, :conversation_id, 'contacto', NULL, "
                "'texto')"
            ),
            {
                "id": row_id,
                "tenant_id": data["tenant_a_id"],
                "conversation_id": conversation_id,
            },
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT contenido FROM messages WHERE id = :id"),
            {"id": row_id},
        ).fetchone()
    assert row.contenido is None


# ---------------------------------------------------------------------------
# RNF-47/R-47: RLS efectiva cross-tenant sobre el Message de audio
# ---------------------------------------------------------------------------


def test_messages_audio_cross_tenant_isolation(
    postgres_engine, app_engine, two_tenants_with_data
):
    """Criterio de aceptación: una sesión de tenant A, con el rol de
    aplicación NO-superusuario `omnicore_app` (ADR-008), NO lee el
    `Message`/`audio_ref` de audio de tenant B, aunque el SELECT no filtre
    por `tenant_id`. Debe fallar por RLS, no por lógica de aplicación. Con
    `postgres_engine` (owner/superusuario) este test pasaría por accidente
    (falso positivo, hallazgo BLACK PANTHER replicado en ADR-008)."""
    data = two_tenants_with_data

    with postgres_engine.begin() as conn:
        conversation_a = _insert_conversation(
            conn, data["tenant_a_id"], data["contact_a_id"]
        )
        conversation_b = _insert_conversation(
            conn, data["tenant_b_id"], data["contact_b_id"]
        )
        _insert_audio_message(
            conn,
            data["tenant_a_id"],
            conversation_a,
            audio_ref="tenant-a/audio-secreto.enc",
        )
        _insert_audio_message(
            conn,
            data["tenant_b_id"],
            conversation_b,
            audio_ref="tenant-b/audio-secreto.enc",
        )

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(data["tenant_a_id"]))
            rows = conn.execute(
                sa.text(
                    "SELECT audio_ref FROM messages WHERE tipo = 'audio'"
                )
            ).fetchall()
            visible_refs = {r.audio_ref for r in rows}

    assert "tenant-a/audio-secreto.enc" in visible_refs, (
        "El tenant A debe ver su propia nota de voz"
    )
    assert "tenant-b/audio-secreto.enc" not in visible_refs, (
        "FUGA CROSS-TENANT: el tenant A puede leer el audio_ref de la nota "
        "de voz del tenant B"
    )


def test_messages_audio_cross_tenant_direct_select_by_id_returns_zero_rows(
    postgres_engine, app_engine, two_tenants_with_data
):
    """Un intento directo de leer, por `id`, el `Message` de audio de otro
    tenant (conociendo su UUID) devuelve 0 filas — RLS bloquea por
    predicado `tenant_id`, no por falta de un `WHERE` explícito en la app."""
    data = two_tenants_with_data

    with postgres_engine.begin() as conn:
        conversation_b = _insert_conversation(
            conn, data["tenant_b_id"], data["contact_b_id"]
        )
        message_b_id = _insert_audio_message(
            conn, data["tenant_b_id"], conversation_b
        )

    with app_engine.connect() as conn:
        with conn.begin():
            set_tenant_session(conn, str(data["tenant_a_id"]))
            rows = conn.execute(
                sa.text("SELECT id FROM messages WHERE id = :id"),
                {"id": message_b_id},
            ).fetchall()

    assert rows == [], (
        "FUGA CROSS-TENANT: el tenant A pudo leer directamente, por id, el "
        "Message de audio del tenant B"
    )


def test_messages_session_without_tenant_sees_zero_audio_rows(
    postgres_engine, app_engine, two_tenants_with_data
):
    """Fail-closed (ADR-004): sin `app.tenant_id` fijado, una sesión con el
    rol de aplicación (`app_engine`, ADR-008) no ve ningún `Message` de
    audio."""
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        conversation_a = _insert_conversation(
            conn, data["tenant_a_id"], data["contact_a_id"]
        )
        _insert_audio_message(conn, data["tenant_a_id"], conversation_a)

    with app_engine.connect() as conn:
        with conn.begin():
            conn.execute(sa.text("RESET app.tenant_id"))
            rows = conn.execute(
                sa.text("SELECT id FROM messages WHERE tipo = 'audio'")
            ).fetchall()
            assert rows == [], (
                "Sesión sin tenant fijado no debe ver ningún Message de audio"
            )


def test_messages_is_tenant_scoped_table():
    """`messages` sigue registrada como tabla tenant-scoped tras la extensión
    de SPEC-053 (misma fuente de verdad que usa la migración de RLS y los
    tests de aislamiento, evitando que la lista se desincronice)."""
    assert "messages" in TENANT_SCOPED_TABLES


# ---------------------------------------------------------------------------
# C2: borrado lógico del Message de audio
# ---------------------------------------------------------------------------


def test_message_audio_soft_delete_no_physical_delete(
    postgres_engine, two_tenants_with_data
):
    """C2: dar de baja el `Message` de audio es `activo=False`, la fila
    permanece (nunca DELETE físico); las consultas de "vigentes" excluyen
    inactivos."""
    data = two_tenants_with_data
    with postgres_engine.begin() as conn:
        conversation_id = _insert_conversation(
            conn, data["tenant_a_id"], data["contact_a_id"]
        )
        message_id = _insert_audio_message(
            conn, data["tenant_a_id"], conversation_id
        )
        conn.execute(
            sa.text("UPDATE messages SET activo = false WHERE id = :id"),
            {"id": message_id},
        )

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT activo FROM messages WHERE id = :id"),
            {"id": message_id},
        ).fetchone()
        vigentes = conn.execute(
            sa.text(
                "SELECT id FROM messages WHERE id = :id AND activo = true"
            ),
            {"id": message_id},
        ).fetchall()

    assert row is not None, "El borrado lógico no debe eliminar la fila (C2)"
    assert row.activo is False
    assert vigentes == [], "Las consultas de vigentes deben excluir inactivos"


# ---------------------------------------------------------------------------
# ADR-013: ninguna tabla call/call_transcript se crea/toca por esta SPEC
# ---------------------------------------------------------------------------


def test_no_se_crean_ni_tocan_tablas_call_por_nota_de_voz_whatsapp(
    postgres_engine, two_tenants_with_data
):
    """ADR-013: la nota de voz de WhatsApp vive exclusivamente en `messages`.
    Insertar el `Message(tipo="audio")` no crea filas en `calls`/
    `call_transcripts` (tablas de un dominio distinto, Entregable #4,
    SPEC-036) — verificación de ausencia de acoplamiento accidental."""
    data = two_tenants_with_data

    with postgres_engine.begin() as conn:
        calls_antes = conn.execute(
            sa.text("SELECT count(*) FROM calls")
        ).scalar_one()
        transcripts_antes = conn.execute(
            sa.text("SELECT count(*) FROM call_transcripts")
        ).scalar_one()

        conversation_id = _insert_conversation(
            conn, data["tenant_a_id"], data["contact_a_id"]
        )
        _insert_audio_message(conn, data["tenant_a_id"], conversation_id)

        calls_despues = conn.execute(
            sa.text("SELECT count(*) FROM calls")
        ).scalar_one()
        transcripts_despues = conn.execute(
            sa.text("SELECT count(*) FROM call_transcripts")
        ).scalar_one()

    assert calls_despues == calls_antes
    assert transcripts_despues == transcripts_antes


# ---------------------------------------------------------------------------
# Idempotencia: unicidad de wamid también aplica a la nota de voz (ADR-007)
# ---------------------------------------------------------------------------


def test_message_audio_wamid_unique_constraint(
    postgres_engine, two_tenants_with_data
):
    """La nota de voz usa el mismo mecanismo de idempotencia por `wamid`
    (ADR-013 punto 3, sin `call_id` nuevo): una reentrega del mismo `wamid`
    no crea un segundo `Message` de audio."""
    data = two_tenants_with_data
    wamid = f"wamid.audio-dup-{uuid.uuid4().hex[:12]}"

    with postgres_engine.begin() as conn:
        conversation_id = _insert_conversation(
            conn, data["tenant_a_id"], data["contact_a_id"]
        )
        _insert_audio_message(
            conn, data["tenant_a_id"], conversation_id, wamid=wamid
        )

    with pytest.raises(IntegrityError):
        with postgres_engine.begin() as conn:
            _insert_audio_message(
                conn, data["tenant_a_id"], conversation_id, wamid=wamid
            )
