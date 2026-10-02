"""
Tests de `app.services.analytics_service` (SPEC-062, PLAN-007 F0) contra
PostgreSQL real.

Mismo patrón que `tests/test_call_retention_service.py`/
`tests/test_retention_service.py`: requiere el `db` de `docker-compose.yml`
con el esquema aplicado vía Alembic; si no hay Postgres accesible se
SKIPEAN automáticamente (ver `tests/conftest.py::postgres_engine`).

RLS (crítico, ver docstring de `app.services.analytics_service`): estas
funciones se EJERCEN aquí con el fixture `app_engine` (rol de aplicación
NO-superusuario `omnicore_app`, ADR-008 — el mismo rol con el que corre el
endpoint real de SPEC-063), NUNCA con `postgres_engine` (rol owner,
SIEMPRE exento de RLS por regla fija de PostgreSQL incluso con FORCE ROW
LEVEL SECURITY). `postgres_engine` se usa SOLO para el bootstrap de datos
de los fixtures (`_insert_conversation`/`_insert_message`/`_insert_draft`),
fuera de cualquier RLS a propósito — igual que en el resto de la suite.

Qué se verifica (criterios de aceptación de SPEC-062):
  1. Conversaciones: total/por canal/por estado/serie diaria correctos;
     días sin datos aparecen como 0; conversaciones inactivas (soft-delete)
     excluidas; filtro por canal funciona.
  2. Tiempos de respuesta: cada caso límite (sin respuesta, solo salientes,
     múltiples entrantes seguidos, respuesta de agente, respuesta de ia).
  3. Conversión: `totales=0` -> `None` (nunca 0/excepción); caso normal.
  4. RLS real: tenant A nunca agrega datos de tenant B.
  5. Asistencia IA (opcional, implementada): % drafts aprobados +
     distribución de sentimiento.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.session import set_tenant_session
from app.services.analytics_service import (
    get_ai_assistance_metrics,
    get_conversation_metrics,
    get_conversion_rate,
    get_response_time_metrics,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers de bootstrap (SQL directo vía `postgres_engine`, fuera de RLS a
# propósito — mismo patrón que `tests/test_call_retention_service.py`).
# ---------------------------------------------------------------------------


def _insert_conversation(
    engine,
    *,
    tenant_id,
    contact_id,
    canal="whatsapp",
    estado="abierta",
    created_at=None,
    activo=True,
):
    conversation_id = uuid.uuid4()
    created_at = created_at or datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conversations "
                "(id, tenant_id, contact_id, canal, estado, activo, "
                " created_at, updated_at) "
                "VALUES (:id, :tenant_id, :contact_id, :canal, :estado, "
                " :activo, :created_at, :created_at)"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "contact_id": contact_id,
                "canal": canal,
                "estado": estado,
                "activo": activo,
                "created_at": created_at,
            },
        )
    return conversation_id


def _insert_message(
    engine,
    *,
    tenant_id,
    conversation_id,
    remitente,
    created_at,
    contenido="hola",
    activo=True,
    sentimiento=None,
):
    message_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO messages "
                "(id, tenant_id, conversation_id, remitente, contenido, tipo, "
                " activo, estado_entrega, sentimiento, wamid, created_at, "
                " updated_at) "
                "VALUES (:id, :tenant_id, :conversation_id, :remitente, "
                " :contenido, 'texto', :activo, 'enviado', :sentimiento, "
                " :wamid, :created_at, :created_at)"
            ),
            {
                "id": message_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "remitente": remitente,
                "contenido": contenido,
                "activo": activo,
                "sentimiento": sentimiento,
                "wamid": f"wamid.analytics-test-{uuid.uuid4().hex[:16]}",
                "created_at": created_at,
            },
        )
    return message_id


def _insert_rag_draft(
    engine,
    *,
    tenant_id,
    conversation_id,
    estado="aprobado",
    activo=True,
):
    draft_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO rag_drafts "
                "(id, tenant_id, conversation_id, query, content_original, "
                " content, model, citations, estado, activo, created_at, "
                " updated_at) "
                "VALUES (:id, :tenant_id, :conversation_id, :query, "
                " :content_original, :content, :model, :citations, :estado, "
                " :activo, now(), now())"
            ),
            {
                "id": draft_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "query": "consulta de prueba",
                "content_original": "respuesta original",
                "content": "respuesta original",
                "model": "modelo-test",
                "citations": "[]",
                "estado": estado,
                "activo": activo,
            },
        )
    return draft_id


def _session_with_tenant(engine, tenant_id) -> Session:
    """Sesión ORM con `app.tenant_id` fijado (`SET LOCAL`) dentro de una
    transacción explícita, usando `app_engine` (rol `omnicore_app`,
    ADR-008) — ejerce RLS real, mismo patrón que
    `tests/test_call_retention_service.py::_session_with_tenant`."""
    session = Session(engine)
    session.begin()
    set_tenant_session(session, str(tenant_id))
    return session


def _dt(d: date, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC)


# ---------------------------------------------------------------------------
# 1. Volumen de conversaciones
# ---------------------------------------------------------------------------


def test_conversation_metrics_total_por_canal_por_estado_y_serie_diaria(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]

    hoy = date.today()
    ayer = hoy - timedelta(days=1)
    hace_3_dias = hoy - timedelta(days=3)  # día SIN conversaciones (serie=0)

    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal="whatsapp",
        estado="abierta",
        created_at=_dt(hoy),
    )
    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal="whatsapp",
        estado="cerrada",
        created_at=_dt(hoy, hour=14),
    )
    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal="webchat",
        estado="cerrada",
        created_at=_dt(ayer),
    )
    # Soft-deleted: NUNCA debe contar en ningún agregado.
    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal="whatsapp",
        estado="abierta",
        created_at=_dt(hoy),
        activo=False,
    )
    # Fuera de rango (antes de `desde`): no debe contarse.
    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal="whatsapp",
        estado="abierta",
        created_at=_dt(hoy - timedelta(days=10)),
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        metrics = get_conversation_metrics(session, desde=hace_3_dias, hasta=hoy)
        session.rollback()

    assert metrics.total == 3
    assert metrics.abiertas == 1
    assert metrics.cerradas == 2

    por_canal = {p.canal: p for p in metrics.por_canal}
    assert por_canal["whatsapp"].total == 2
    assert por_canal["whatsapp"].abiertas == 1
    assert por_canal["whatsapp"].cerradas == 1
    assert por_canal["webchat"].total == 1
    assert por_canal["webchat"].cerradas == 1

    serie_por_fecha = {p.fecha: p.total for p in metrics.serie_diaria}
    assert serie_por_fecha[hace_3_dias] == 0  # día sin datos = 0, no se omite
    assert serie_por_fecha[hoy - timedelta(days=2)] == 0
    assert serie_por_fecha[ayer] == 1
    assert serie_por_fecha[hoy] == 2
    # El rango completo está representado día a día (4 días: hace_3_dias..hoy).
    assert len(metrics.serie_diaria) == 4


def test_conversation_metrics_filtra_por_canal(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]
    hoy = date.today()

    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal="whatsapp",
        created_at=_dt(hoy),
    )
    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        canal="webchat",
        created_at=_dt(hoy),
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        metrics = get_conversation_metrics(
            session, desde=hoy, hasta=hoy, canal="webchat"
        )
        session.rollback()

    assert metrics.total == 1
    assert [p.canal for p in metrics.por_canal] == ["webchat"]


# ---------------------------------------------------------------------------
# 2. Tiempos de respuesta — casos límite
# ---------------------------------------------------------------------------


def test_conversacion_sin_respuesta_se_excluye_del_promedio(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]
    hoy = date.today()

    conv_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=contact_id, created_at=_dt(hoy)
    )
    # Solo un mensaje entrante, sin respuesta posterior alguna.
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="contacto",
        created_at=_dt(hoy, hour=9),
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        metrics = get_response_time_metrics(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert metrics.conversaciones_con_respuesta == 0
    assert metrics.primera_respuesta_promedio_seg is None
    assert metrics.respuesta_promedio_seg is None


def test_conversacion_solo_salientes_se_excluye(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]
    hoy = date.today()

    conv_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=contact_id, created_at=_dt(hoy)
    )
    # Solo mensajes salientes, ningún entrante -> ningún bloque que abrir.
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="agente",
        created_at=_dt(hoy, hour=9),
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="agente",
        created_at=_dt(hoy, hour=10),
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        metrics = get_response_time_metrics(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert metrics.conversaciones_con_respuesta == 0
    assert metrics.primera_respuesta_promedio_seg is None
    assert metrics.respuesta_promedio_seg is None


def test_multiples_entrantes_seguidos_cuentan_como_un_solo_bloque(
    app_engine, postgres_engine, two_tenants_with_data
):
    """3 entrantes seguidos + 1 saliente: debe generar UNA sola diferencia
    (desde el PRIMER entrante del bloque hasta el saliente), no 3."""
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]
    hoy = date.today()

    conv_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=contact_id, created_at=_dt(hoy)
    )
    base = _dt(hoy, hour=9, minute=0)
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="contacto",
        created_at=base,
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="contacto",
        created_at=base + timedelta(minutes=1),
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="contacto",
        created_at=base + timedelta(minutes=2),
    )
    # Respuesta 5 minutos después del PRIMER entrante del bloque (base).
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="agente",
        created_at=base + timedelta(minutes=5),
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        metrics = get_response_time_metrics(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert metrics.conversaciones_con_respuesta == 1
    # TPR y respuesta promedio coinciden (una sola conversación, un solo
    # bloque -> una sola diferencia): 5 minutos = 300 segundos, medidos
    # desde el PRIMER entrante del bloque (base), no desde el tercero.
    assert metrics.primera_respuesta_promedio_seg == 300.0
    assert metrics.respuesta_promedio_seg == 300.0


def test_respuesta_de_agente_y_de_ia_cuentan_igual_como_saliente(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]
    hoy = date.today()

    # Conversación 1: entrante -> respuesta de AGENTE (10s después).
    conv_agente = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=contact_id, created_at=_dt(hoy)
    )
    base1 = _dt(hoy, hour=8, minute=0)
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_agente,
        remitente="contacto",
        created_at=base1,
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_agente,
        remitente="agente",
        created_at=base1 + timedelta(seconds=10),
    )

    # Conversación 2: entrante -> respuesta de IA (20s después).
    conv_ia = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=contact_id, created_at=_dt(hoy)
    )
    base2 = _dt(hoy, hour=8, minute=30)
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_ia,
        remitente="contacto",
        created_at=base2,
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_ia,
        remitente="ia",
        created_at=base2 + timedelta(seconds=20),
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        metrics = get_response_time_metrics(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert metrics.conversaciones_con_respuesta == 2
    # Promedio de las dos: (10 + 20) / 2 = 15s. Ambas cuentan igual como
    # saliente, sin distinguir agente/ia.
    assert metrics.primera_respuesta_promedio_seg == 15.0
    assert metrics.respuesta_promedio_seg == 15.0


def test_multiples_idas_y_vueltas_promedian_cada_bloque(
    app_engine, postgres_engine, two_tenants_with_data
):
    """Una conversación con 2 idas y vueltas: la respuesta_promedio agrega
    AMBAS diferencias; la primera_respuesta solo la del primer bloque."""
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]
    hoy = date.today()

    conv_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=contact_id, created_at=_dt(hoy)
    )
    base = _dt(hoy, hour=7, minute=0)
    # Bloque 1: entrante -> saliente 10s después.
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="contacto",
        created_at=base,
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="agente",
        created_at=base + timedelta(seconds=10),
    )
    # Bloque 2: entrante -> saliente 30s después.
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="contacto",
        created_at=base + timedelta(minutes=5),
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="agente",
        created_at=base + timedelta(minutes=5, seconds=30),
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        metrics = get_response_time_metrics(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert metrics.conversaciones_con_respuesta == 1
    assert metrics.primera_respuesta_promedio_seg == 10.0  # solo el 1er bloque
    assert metrics.respuesta_promedio_seg == 20.0  # promedio de (10, 30)


def test_mensaje_soft_deleted_se_excluye_de_tiempos_de_respuesta(
    app_engine, postgres_engine, two_tenants_with_data
):
    """R-75 (HAWKEYE, SPEC-065): un mensaje saliente con `activo=False`
    (borrado lógico, C2) NUNCA debe contar como la respuesta de un bloque
    entrante -- `get_response_time_metrics` filtra `Message.activo.is_(True)`
    explícitamente (ver docstring del servicio); este test lo ejerce con
    datos reales: sin el filtro, esta conversación tendría TPR=10s; con el
    filtro correcto, la respuesta inactiva se ignora y la conversación
    queda SIN respuesta activa -> excluida de ambos promedios."""
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]
    hoy = date.today()

    conv_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=contact_id, created_at=_dt(hoy)
    )
    base = _dt(hoy, hour=9, minute=0)
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="contacto",
        created_at=base,
    )
    # Única respuesta disponible: SOFT-DELETED. No debe contar.
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="agente",
        created_at=base + timedelta(seconds=10),
        activo=False,
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        metrics = get_response_time_metrics(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert metrics.conversaciones_con_respuesta == 0
    assert metrics.primera_respuesta_promedio_seg is None
    assert metrics.respuesta_promedio_seg is None


def test_mensaje_soft_deleted_se_excluye_de_distribucion_de_sentimiento(
    app_engine, postgres_engine, two_tenants_with_data
):
    """R-75: `get_ai_assistance_metrics` filtra `Message.activo.is_(True)`
    también en la distribución de sentimiento -- un mensaje inactivo con
    `sentimiento='negativo'` NUNCA debe sumar al conteo."""
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]
    hoy = date.today()

    conv_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=contact_id, created_at=_dt(hoy)
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="contacto",
        created_at=_dt(hoy),
        sentimiento="positivo",
    )
    # Mensaje inactivo (soft-deleted) con sentimiento negativo: NO debe contar.
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        remitente="contacto",
        created_at=_dt(hoy, hour=10),
        sentimiento="negativo",
        activo=False,
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        metrics = get_ai_assistance_metrics(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert metrics is not None
    assert metrics.sentimiento.positivo == 1
    assert metrics.sentimiento.negativo == 0
    assert metrics.sentimiento.sin_clasificar == 0


def test_rag_draft_soft_deleted_se_excluye_del_pct_de_aprobados(
    app_engine, postgres_engine, two_tenants_with_data
):
    """R-75: `get_ai_assistance_metrics` filtra `RagDraft.activo.is_(True)`
    -- un borrador aprobado pero SOFT-DELETED no debe contar como
    "conversación con draft aprobado"."""
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]
    hoy = date.today()

    conv_id = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=contact_id, created_at=_dt(hoy)
    )
    # Único draft aprobado de la conversación: SOFT-DELETED. No debe contar.
    _insert_rag_draft(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        estado="aprobado",
        activo=False,
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        metrics = get_ai_assistance_metrics(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert metrics is not None
    assert metrics.conversaciones_total == 1
    assert metrics.conversaciones_con_draft_aprobado == 0
    assert metrics.pct_drafts_aprobados == 0.0


# ---------------------------------------------------------------------------
# 3. Conversión
# ---------------------------------------------------------------------------


def test_conversion_rate_con_totales_cero_no_lanza_excepcion(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    hoy = date.today()

    with _session_with_tenant(app_engine, tenant_id) as session:
        result = get_conversion_rate(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert result.totales == 0
    assert result.cerradas == 0
    assert result.tasa is None  # nunca 0, nunca división por cero


def test_conversion_rate_caso_normal(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]
    hoy = date.today()

    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        estado="cerrada",
        created_at=_dt(hoy),
    )
    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        estado="cerrada",
        created_at=_dt(hoy),
    )
    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        estado="abierta",
        created_at=_dt(hoy),
    )
    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        estado="abierta",
        created_at=_dt(hoy),
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        result = get_conversion_rate(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert result.totales == 4
    assert result.cerradas == 2
    assert result.tasa == 0.5


# ---------------------------------------------------------------------------
# 4. RLS real — aislamiento cross-tenant
# ---------------------------------------------------------------------------


def test_rls_tenant_a_nunca_agrega_datos_de_tenant_b(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_a_id = two_tenants_with_data["tenant_a_id"]
    tenant_b_id = two_tenants_with_data["tenant_b_id"]
    contact_a_id = two_tenants_with_data["contact_a_id"]
    contact_b_id = two_tenants_with_data["contact_b_id"]
    hoy = date.today()

    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_a_id,
        contact_id=contact_a_id,
        estado="cerrada",
        created_at=_dt(hoy),
    )
    # Tenant B: 5 conversaciones que NUNCA deben aparecer en los agregados
    # de tenant A.
    for _ in range(5):
        _insert_conversation(
            postgres_engine,
            tenant_id=tenant_b_id,
            contact_id=contact_b_id,
            estado="cerrada",
            created_at=_dt(hoy),
        )

    with _session_with_tenant(app_engine, tenant_a_id) as session:
        metrics_a = get_conversation_metrics(session, desde=hoy, hasta=hoy)
        session.rollback()

    with _session_with_tenant(app_engine, tenant_b_id) as session:
        metrics_b = get_conversation_metrics(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert metrics_a.total == 1
    assert metrics_b.total == 5


def test_rls_sesion_sin_tenant_fijado_ve_cero_filas(
    app_engine, postgres_engine, two_tenants_with_data
):
    """Fail-closed (ADR-004/ADR-008): una sesión de `app_engine` (rol
    `omnicore_app`) SIN `set_tenant_session` ve 0 filas, aunque existan
    conversaciones reales en BD — mismo patrón de test que
    `test_call_retention_service.py::test_session_without_tenant_fixed_finds_zero_candidates`.
    """
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]
    hoy = date.today()

    _insert_conversation(
        postgres_engine,
        tenant_id=tenant_id,
        contact_id=contact_id,
        estado="cerrada",
        created_at=_dt(hoy),
    )

    with Session(app_engine) as session:
        metrics = get_conversation_metrics(session, desde=hoy, hasta=hoy)

    assert metrics.total == 0


# ---------------------------------------------------------------------------
# 5. Asistencia IA (opcional, RF-04) — implementada
# ---------------------------------------------------------------------------


def test_ai_assistance_metrics_pct_drafts_aprobados_y_sentimiento(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    contact_id = two_tenants_with_data["contact_a_id"]
    hoy = date.today()

    conv_con_draft = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=contact_id, created_at=_dt(hoy)
    )
    conv_sin_draft = _insert_conversation(
        postgres_engine, tenant_id=tenant_id, contact_id=contact_id, created_at=_dt(hoy)
    )
    _insert_rag_draft(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_con_draft,
        estado="aprobado",
    )
    # Un draft "propuesto" (no aprobado) en la otra conversación: no cuenta.
    _insert_rag_draft(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_sin_draft,
        estado="propuesto",
    )

    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_con_draft,
        remitente="contacto",
        created_at=_dt(hoy),
        sentimiento="positivo",
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_con_draft,
        remitente="agente",
        created_at=_dt(hoy, hour=13),
        sentimiento=None,
    )
    _insert_message(
        postgres_engine,
        tenant_id=tenant_id,
        conversation_id=conv_sin_draft,
        remitente="contacto",
        created_at=_dt(hoy),
        sentimiento="negativo",
    )

    with _session_with_tenant(app_engine, tenant_id) as session:
        metrics = get_ai_assistance_metrics(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert metrics is not None
    assert metrics.conversaciones_total == 2
    assert metrics.conversaciones_con_draft_aprobado == 1
    assert metrics.pct_drafts_aprobados == 0.5
    assert metrics.sentimiento.positivo == 1
    assert metrics.sentimiento.negativo == 1
    assert metrics.sentimiento.sin_clasificar == 1
    assert metrics.sentimiento.neutral == 0


def test_ai_assistance_metrics_pct_none_cuando_no_hay_conversaciones(
    app_engine, postgres_engine, two_tenants_with_data
):
    tenant_id = two_tenants_with_data["tenant_a_id"]
    hoy = date.today()

    with _session_with_tenant(app_engine, tenant_id) as session:
        metrics = get_ai_assistance_metrics(session, desde=hoy, hasta=hoy)
        session.rollback()

    assert metrics is not None
    assert metrics.conversaciones_total == 0
    assert metrics.pct_drafts_aprobados is None
