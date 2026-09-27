"""
Capa de servicio de agregación de métricas de NEGOCIO (`analytics_service`,
SPEC-062, PLAN-007 F0): conversaciones (volumen/canal/estado/serie diaria),
tiempos de respuesta (TPR y respuesta promedio, derivados de `messages`) y
tasa de conversión (`cerradas/totales`, Q1(a) del Lead — cero dominio
nuevo). Opcionalmente, asistencia IA (% de `rag_drafts` aprobados +
distribución de `messages.sentimiento`), leída de columnas ya persistidas.

RLS — el punto más crítico de este módulo (léase el docstring completo
antes de tocar cualquier función de aquí, es el hallazgo de bug recurrente
más documentado en este proyecto):

Este servicio es invocado desde un endpoint HTTP (SPEC-063), donde el
`tenant_id` YA viene fijado por `get_tenant_db` (`SET LOCAL app.tenant_id`
con el valor firmado en el JWT, ANTES del handler). A diferencia de los
jobs de mantenimiento (`app.services.retention_service.run_retention_job`,
`app.services.telefonia.call_retention_service.run_call_retention_job`),
que SÍ recorren tenants y fijan la sesión por su cuenta (porque corren
fuera del ciclo de request/response, sin un tenant único ya resuelto), las
funciones de este módulo:

  - reciben una `Session` YA con `app.tenant_id` fijado — NUNCA la fijan
    ellas mismas (`set_tenant_session` NO se llama aquí);
  - NUNCA recorren tenants (no hay equivalente a `_active_tenant_ids`);
  - NUNCA aceptan ni usan un parámetro `tenant_id` explícito para filtrar
    manualmente `WHERE tenant_id = ...` — eso sería redundante en el mejor
    caso y, en el peor, un despiste que reintroduce el bug de bypass de
    RLS si alguna vez se usa con una sesión de rol owner/superusuario.

El aislamiento cross-tenant es 100% responsabilidad de la política RLS de
la sesión recibida (`app/db/rls.py`): `conversations`, `messages` y
`rag_drafts` están en `TENANT_SCOPED_TABLES` con RLS ENABLE+FORCE
(ADR-004/ADR-008); el rol de aplicación `omnicore_app` es `NOSUPERUSER
NOBYPASSRLS`, así que una sesión sin `app.tenant_id` fijado ve CERO filas
por diseño (fail-closed). Si esta sesión llega desde un rol owner/
superusuario (p.ej. `postgres_engine` en los tests), NO habrá aislamiento
— PostgreSQL nunca aplica RLS a superusuarios/BYPASSRLS, ni con FORCE ROW
LEVEL SECURITY. Por eso los tests de este módulo ejercen las funciones con
el fixture `app_engine` (rol `omnicore_app`), nunca con `postgres_engine`
(rol owner, se usa solo para el bootstrap de datos de los fixtures).

Todas las funciones son puras/testeables de forma aislada (RF-05): reciben
una `Session` + parámetros primitivos, devuelven estructuras de datos
(`dataclasses` congeladas) — sin tocar HTTP/request, sin efectos
secundarios, sin abrir/cerrar transacciones propias.

Borrado lógico (C2): todo conteo filtra `Conversation.activo.is_(True)` /
`Message.activo.is_(True)` / `RagDraft.activo.is_(True)` — un registro
soft-deleted nunca aporta a un agregado. `anonymized_at` (HABEAS DATA,
SPEC-021) no aplica directamente a estas tablas (vive en `contacts`), pero
como la respuesta de este servicio SIEMPRE son agregados (conteos,
promedios, tasas) y jamás PII individual, no hay riesgo de reintroducir un
dato ya anonimizado: los mensajes/conversaciones de un contacto anonimizado
siguen contando en los totales (igual que cualquier otra fila activa), sin
exponer ningún campo identificante.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import Float, and_, cast, func, or_, select
from sqlalchemy import true as sa_true
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.message import Message
from app.models.rag_draft import RagDraft

# Remitentes considerados "saliente" (agente humano o IA) — ambos cuentan
# IGUAL para efectos de tiempos de respuesta (§Alcance IN de SPEC-062: "no
# las trates distinto salvo que quieras exponer un desglose opcional
# adicional, no es requerido" — este servicio no lo expone, mantiene el
# cálculo simple; si una fase futura lo requiere, se añade como un campo
# adicional sin romper el contrato actual).
_REMITENTES_SALIENTE = ("agente", "ia")
_REMITENTE_ENTRANTE = "contacto"


# ---------------------------------------------------------------------------
# Estructuras de datos devueltas (dataclasses congeladas — solo lectura,
# nunca se mutan tras construirse; documentan la forma exacta del contrato
# que SPEC-063 puede serializar a JSON sin transformación adicional).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConversacionesPorCanal:
    canal: str
    total: int
    abiertas: int
    cerradas: int


@dataclass(frozen=True)
class SerieDiariaPunto:
    fecha: date
    total: int


@dataclass(frozen=True)
class ConversationMetrics:
    """Resultado de `get_conversation_metrics`."""

    total: int
    abiertas: int
    cerradas: int
    por_canal: list[ConversacionesPorCanal] = field(default_factory=list)
    serie_diaria: list[SerieDiariaPunto] = field(default_factory=list)


@dataclass(frozen=True)
class ResponseTimeMetrics:
    """Resultado de `get_response_time_metrics`.

    - `primera_respuesta_promedio_seg`: promedio del tiempo de primera
      respuesta (TPR) SOLO sobre las conversaciones que tuvieron al menos
      una respuesta saliente tras su primer mensaje entrante. `None` si
      ninguna conversación del rango tuvo primera respuesta (nunca 0 — ver
      docstring de `get_response_time_metrics`).
    - `respuesta_promedio_seg`: promedio de TODAS las diferencias
      entrante→siguiente-saliente (una por cada bloque de entrantes
      consecutivos que tuvo respuesta posterior), sobre todas las
      conversaciones con al menos una respuesta. `None` si no hay ninguna
      diferencia calculable en el rango.
    - `conversaciones_con_respuesta`: cuántas conversaciones del rango
      aportaron al menos una diferencia entrante→saliente (denominador
      real usado para los promedios de esta estructura).
    """

    primera_respuesta_promedio_seg: float | None
    respuesta_promedio_seg: float | None
    conversaciones_con_respuesta: int


@dataclass(frozen=True)
class ConversionMetrics:
    """Resultado de `get_conversion_rate`.

    `tasa` es `None` (nunca `0`) cuando `totales == 0`: `0` sugeriría "0%
    de conversión" (hay datos, pero ninguno convirtió), mientras que
    `None`/`null` comunica honestamente "no hay datos en este rango para
    calcular una tasa" — distinción explícita pedida por SPEC-062/RF-03.
    """

    tasa: float | None
    cerradas: int
    totales: int


@dataclass(frozen=True)
class SentimientoDistribucion:
    positivo: int
    neutral: int
    negativo: int
    sin_clasificar: int


@dataclass(frozen=True)
class AiAssistanceMetrics:
    """Resultado (opcional, RF-04) de `get_ai_assistance_metrics`."""

    pct_drafts_aprobados: float | None
    conversaciones_con_draft_aprobado: int
    conversaciones_total: int
    sentimiento: SentimientoDistribucion


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _rango_a_datetime(desde: date, hasta: date) -> tuple[datetime, datetime]:
    """Convierte un rango de `date` `[desde, hasta]` (inclusive) a límites
    `datetime` medio-abiertos `[inicio, fin)` para comparar contra columnas
    `TIMESTAMPTZ` (`created_at`) sin perder la parte del día `hasta` (un
    filtro `created_at <= hasta` con `hasta` como `date` trunca a
    medianoche y excluiría todo lo ocurrido durante ESE día)."""
    inicio = datetime.combine(desde, datetime.min.time())
    fin_exclusivo = datetime.combine(hasta, datetime.min.time()) + timedelta(days=1)
    return inicio, fin_exclusivo


def _rango_condiciones(desde: date, hasta: date, columna):
    inicio, fin_exclusivo = _rango_a_datetime(desde, hasta)
    return and_(columna >= inicio, columna < fin_exclusivo)


def _filtro_canal(canal: str | None):
    if canal is None:
        return None
    return Conversation.canal == canal


def _aplicar_filtro_canal(stmt, canal: str | None):
    condicion = _filtro_canal(canal)
    if condicion is not None:
        stmt = stmt.where(condicion)
    return stmt


# ---------------------------------------------------------------------------
# 1. Volumen de conversaciones
# ---------------------------------------------------------------------------


def get_conversation_metrics(
    db: Session,
    *,
    desde: date,
    hasta: date,
    canal: str | None = None,
) -> ConversationMetrics:
    """Volumen de conversaciones ACTIVAS (soft-delete excluido, C2) del
    tenant de la sesión, con `created_at` dentro de `[desde, hasta]`
    (inclusive, en fecha calendario) — la ventana se define sobre
    `Conversation.created_at`, NUNCA sobre `updated_at` (PLAN-007 §3.3,
    fijado para evitar ambigüedad).

    Devuelve total/abiertas/cerradas, desglose por canal (mismo criterio,
    agrupado) y una serie diaria que SIEMPRE cubre el rango completo día a
    día — un día sin ninguna conversación aparece con `total=0`, no se omite
    de la lista (criterio explícito de SPEC-062).

    Si se pasa `canal`, todos los desgloses (incl. la serie diaria) quedan
    acotados a ese canal — `por_canal` en ese caso tendrá como mucho una
    entrada (la de `canal`).
    """
    condicion_rango = _rango_condiciones(desde, hasta, Conversation.created_at)
    base_where = [Conversation.activo.is_(True), condicion_rango]
    filtro_canal = _filtro_canal(canal)
    if filtro_canal is not None:
        base_where.append(filtro_canal)

    # --- Totales + abiertas/cerradas -------------------------------------
    totales_stmt = select(
        func.count(Conversation.id).label("total"),
        func.count(Conversation.id)
        .filter(Conversation.estado == "abierta")
        .label("abiertas"),
        func.count(Conversation.id)
        .filter(Conversation.estado == "cerrada")
        .label("cerradas"),
    ).where(*base_where)
    fila_totales = db.execute(totales_stmt).one()
    total = int(fila_totales.total or 0)
    abiertas = int(fila_totales.abiertas or 0)
    cerradas = int(fila_totales.cerradas or 0)

    # --- Desglose por canal ------------------------------------------------
    por_canal_stmt = (
        select(
            Conversation.canal.label("canal"),
            func.count(Conversation.id).label("total"),
            func.count(Conversation.id)
            .filter(Conversation.estado == "abierta")
            .label("abiertas"),
            func.count(Conversation.id)
            .filter(Conversation.estado == "cerrada")
            .label("cerradas"),
        )
        .where(*base_where)
        .group_by(Conversation.canal)
        .order_by(Conversation.canal)
    )
    por_canal = [
        ConversacionesPorCanal(
            canal=row.canal,
            total=int(row.total or 0),
            abiertas=int(row.abiertas or 0),
            cerradas=int(row.cerradas or 0),
        )
        for row in db.execute(por_canal_stmt).all()
    ]

    # --- Serie diaria -------------------------------------------------------
    # `date_trunc('day', created_at)` agrupa por día calendario en la zona
    # horaria de la sesión (UTC en este proyecto, ver `app/db/session.py`);
    # se castea a `date` en Python (vía `.date()`) para el relleno de días
    # sin datos, que se hace en Python (más simple/legible que un
    # `generate_series` SQL para el volumen esperado de este dashboard).
    dia_columna = func.date_trunc("day", Conversation.created_at).label("dia")
    serie_stmt = (
        select(
            dia_columna,
            func.count(Conversation.id).label("total"),
        )
        .where(*base_where)
        .group_by(dia_columna)
    )
    conteos_por_dia: dict[date, int] = {
        row.dia.date(): int(row.total or 0) for row in db.execute(serie_stmt).all()
    }

    serie_diaria: list[SerieDiariaPunto] = []
    cursor = desde
    while cursor <= hasta:
        serie_diaria.append(
            SerieDiariaPunto(fecha=cursor, total=conteos_por_dia.get(cursor, 0))
        )
        cursor = cursor + timedelta(days=1)

    return ConversationMetrics(
        total=total,
        abiertas=abiertas,
        cerradas=cerradas,
        por_canal=por_canal,
        serie_diaria=serie_diaria,
    )


# ---------------------------------------------------------------------------
# 2. Tiempos de respuesta (TPR + respuesta promedio)
# ---------------------------------------------------------------------------


def get_response_time_metrics(
    db: Session,
    *,
    desde: date,
    hasta: date,
    canal: str | None = None,
) -> ResponseTimeMetrics:
    """Tiempo de primera respuesta (TPR) y tiempo de respuesta promedio,
    derivados de `messages`, para las conversaciones ACTIVAS del tenant con
    `created_at` en `[desde, hasta]` (mismo filtro de rango/canal que
    `get_conversation_metrics`).

    Definición exacta (PLAN-007 §3.3 / SPEC-062, no reinterpretar):

    - Se recorre la secuencia de `Message.activo=True` de cada conversación
      ordenada por `created_at`. Un "bloque de entrantes consecutivos"
      empieza en todo mensaje `remitente="contacto"` cuyo mensaje anterior
      (en esa misma conversación) NO es un entrante (o no existe uno
      anterior). Para cada inicio de bloque se busca el PRIMER mensaje
      saliente (`remitente` in `agente`/`ia`) posterior — la diferencia
      `saliente.created_at - entrante.created_at` es UNA "respuesta"; NO se
      genera una diferencia por cada entrante del bloque, solo una por
      bloque (si varios entrantes seguidos preceden a la misma respuesta).
    - El primer inicio de bloque de TODA la conversación (el primer
      entrante) define el TPR de esa conversación, si tuvo respuesta.
    - Casos límite (verificados por tests, no inventar otra cosa):
        * Conversación SIN ninguna respuesta saliente → EXCLUIDA de ambos
          promedios (no cuenta como 0, no rompe el cálculo).
        * Conversación con SOLO mensajes salientes (sin ningún entrante) →
          excluida (no hay bloque entrante que abra un cálculo).
        * Respuesta de "agente" y de "ia" cuentan IGUAL como saliente.

    Implementación (revisada DOS veces tras hallazgos de THOR, medidos con
    EXPLAIN ANALYZE contra un tenant sintético de 2.500 conversaciones /
    ~87.500 mensajes en 30 días — ver PLAN-007/SPEC-062 seguimiento de
    performance):

    Iteración 1 (versión original): window functions (`LAG`/`MIN` `OVER`)
    GLOBALES sobre TODOS los mensajes de TODAS las conversaciones del rango
    a la vez (particionadas por `conversation_id`, pero evaluadas en un
    único `Sort` de todo el conjunto). Con el volumen de arriba, ese `Sort`
    global degradaba a `external merge` en disco (~890ms, escalado
    claramente superlineal) — el índice
    `ix_messages_conversation_id_created_at` EXISTÍA pero un plan con un
    único `Hash Join` + `Sort` global sobre todas las conversaciones a la
    vez no podía aprovecharlo como acceso ya ordenado.

    Iteración 2 (primer intento de corrección, con `JOIN LATERAL` simple):
    se movieron las MISMAS 2 window functions (`LAG` + `MIN(...) OVER (ROWS
    BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING)`) dentro de un `JOIN
    LATERAL` por conversación (`Select.lateral()`), eliminando el `Sort`
    GLOBAL — pero el tiempo total NO mejoró de forma significativa (~830-
    910ms): confirmado con `EXPLAIN ANALYZE` que el costo dominante NO era
    el `Sort` (trivial, 25kB en memoria, 35 filas por conversación) sino el
    overhead intrínseco de PostgreSQL en evaluar 2 nodos `WindowAgg`
    genéricos POR CADA una de las 2.500 iteraciones del `Nested Loop`
    externo (~0.35ms de overhead fijo por loop, independiente de I/O).

    Iteración 3 (la actual, la que corrige el hallazgo de THOR de verdad):
    se sustituye la SEGUNDA window function (`MIN(created_at) OVER (ROWS
    BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING)`, que buscaba "el primer
    saliente desde aquí en adelante" evaluando la partición completa) por
    un SEGUNDO `LATERAL` anidado con `ORDER BY created_at LIMIT 1` — sin
    ninguna window function — que Postgres resuelve con un simple `Index
    Scan` + `Limit` sobre `ix_messages_conversation_id_created_at`
    (`conversation_id = ... AND created_at > ...`, ya ordenado, se detiene
    en la primera fila). Solo queda UNA window function (`LAG`, para
    detectar "inicio de bloque entrante") + `ROW_NUMBER()` para el orden
    dentro de la conversación. Medido: ~443-461ms — mejora de ~2x sobre la
    iteración 2 y sobre la original, y ya NO hay ningún `Sort`/`external
    merge` en disco en ningún volumen probado.

    La SEMÁNTICA es IDÉNTICA en las 3 iteraciones (esto es una optimización
    de EJECUCIÓN, nunca de lógica de negocio) — verificado con los mismos
    13 tests de `tests/test_analytics_service.py` sin modificar sus asserts
    en ninguna de las 3 iteraciones:

      1. `conversaciones_ids_subq`: conversaciones activas del tenant/rango
         /canal (sin cambios en las 3 iteraciones).
      2. LATERAL externo (`entrantes_lateral`, correlacionado con
         `conversaciones_ids_subq.c.id`): TODOS los mensajes activos de ESA
         conversación, con `LAG(remitente) OVER (ORDER BY created_at)` (sin
         `PARTITION BY`: el LATERAL ya acotó a una sola conversación),
         filtrado a "inicio de bloque entrante" (`remitente='contacto'` y
         el remitente anterior NO es entrante, o no existe uno anterior).
      3. LATERAL interno (`saliente_lateral`, correlacionado con
         `conversaciones_ids_subq.c.id` Y con el `created_at` del entrante
         del LATERAL externo): el PRIMER mensaje saliente
         (`remitente` in `agente`/`ia`) con `created_at` posterior al del
         entrante — `ORDER BY created_at LIMIT 1`, sin window function.
         Una conversación/bloque sin ningún saliente posterior simplemente
         no produce fila en este LATERAL (equivalente exacto al caso límite
         "sin respuesta": implementado por AUSENCIA de fila, igual que
         antes lo era por `saliente_ts IS NULL` descartado en el filtro).
      4. El resultado (una fila por respuesta encontrada, con su
         `delta_seg` en segundos y su `ROW_NUMBER() OVER (ORDER BY
         entrante.created_at)` para distinguir la primera respuesta de la
         conversación del resto de idas-y-vueltas) se agrega en un único
         `SELECT` final con `COUNT`/`AVG`/`FILTER`, igual que siempre.

    Nota de implementación (restricción de PostgreSQL que sigue aplicando):
    una window function no puede referenciarse directamente en `WHERE` en
    el mismo nivel de `SELECT` en que se calcula — de ahí que el filtro de
    "inicio de bloque entrante" (que depende de `LAG`) se aplique en un
    nivel de subconsulta separado, DENTRO del propio LATERAL externo.
    """
    condicion_rango = _rango_condiciones(desde, hasta, Conversation.created_at)
    conversaciones_where = [Conversation.activo.is_(True), condicion_rango]
    filtro_canal = _filtro_canal(canal)
    if filtro_canal is not None:
        conversaciones_where.append(filtro_canal)

    conversaciones_ids_subq = (
        select(Conversation.id.label("id")).where(*conversaciones_where).subquery()
    )

    es_saliente = Message.remitente.in_(_REMITENTES_SALIENTE)

    # --- LATERAL externo: mensajes ENTRANTES que son "inicio de bloque" ----
    # Acotado por la correlación externa
    # `Message.conversation_id == conversaciones_ids_subq.c.id` (ver el
    # `.where(...)` + `.correlate(...)` de abajo). Solo UNA window function
    # (`LAG`), sin `PARTITION BY` (el LATERAL ya acota a una sola
    # conversación) — esto es lo que permite a Postgres resolver `ORDER BY
    # Message.created_at` con un Index Scan YA ORDENADO sobre
    # `ix_messages_conversation_id_created_at`, en vez de un `Sort` propio.
    lag_remitente = func.lag(Message.remitente).over(order_by=Message.created_at)

    # Nivel 1 (dentro del LATERAL externo): columnas anotadas para TODOS los
    # mensajes activos de ESTA conversación, sin filtrar todavía — no se
    # puede filtrar por una window function en el mismo nivel en que se
    # calcula.
    mensajes_anotados_stmt = (
        select(
            Message.created_at.label("created_at"),
            Message.remitente.label("remitente"),
            lag_remitente.label("remitente_anterior"),
        )
        .where(
            Message.activo.is_(True),
            Message.conversation_id == conversaciones_ids_subq.c.id,
        )
        # `.correlate(conversaciones_ids_subq)` es IMPRESCINDIBLE aquí (no es
        # cosmético): sin él, SQLAlchemy no reconoce que
        # `conversaciones_ids_subq` referenciada en el `WHERE` de arriba es
        # la MISMA instancia que la del `FROM` externo (`respuestas_subq`,
        # más abajo) — en su lugar, renderiza una SEGUNDA copia
        # independiente de `conversaciones_ids_subq` dentro de este `FROM`,
        # sin relación real con la fila externa (un `CROSS JOIN` disfrazado,
        # confirmado con `SAWarning: cartesian product` y un resultado
        # numéricamente incorrecto al probarlo contra Postgres real: la
        # correlación externa se perdía y el LATERAL dejaba de estar
        # acotado a una sola conversación). Con `.correlate(...)`
        # explícito, la subconsulta queda correlacionada correctamente con
        # `conversaciones_ids_subq.c.id` de la fila actual del `FROM`
        # externo — el comportamiento LATERAL real que se necesita.
        .correlate(conversaciones_ids_subq)
    )
    mensajes_anotados_subq = mensajes_anotados_stmt.subquery()

    # Nivel 2 (dentro del LATERAL externo): filtra "inicio de bloque
    # entrante" (`remitente='contacto'` y el remitente anterior NO es
    # entrante, o no existe uno anterior) — idéntico criterio de siempre,
    # SIN el filtro de "tuvo respuesta" (eso ahora lo decide, por ausencia
    # de fila, el LATERAL interno de abajo).
    inicio_bloque_entrante = and_(
        mensajes_anotados_subq.c.remitente == _REMITENTE_ENTRANTE,
        or_(
            mensajes_anotados_subq.c.remitente_anterior.is_(None),
            mensajes_anotados_subq.c.remitente_anterior != _REMITENTE_ENTRANTE,
        ),
    )
    entrantes_lateral = (
        select(mensajes_anotados_subq.c.created_at.label("entrante_ts"))
        .select_from(mensajes_anotados_subq)
        .where(inicio_bloque_entrante)
        .lateral("entrantes_lateral")
    )

    # --- LATERAL interno: el PRIMER saliente posterior a CADA entrante -----
    # Correlacionado con la conversación (`conversaciones_ids_subq.c.id`) Y
    # con `entrantes_lateral.c.entrante_ts` (el `created_at` del entrante
    # que abrió el bloque). `ORDER BY created_at LIMIT 1` — SIN ninguna
    # window function: Postgres resuelve esto con un Index Scan sobre
    # `ix_messages_conversation_id_created_at` que se detiene en la primera
    # fila que cumple `created_at > entrante_ts` (confirmado con
    # `EXPLAIN ANALYZE`: `Limit` + `Index Scan`, costo ~0.005ms por
    # ejecución). Este es el cambio clave de la iteración 3: reemplaza el
    # costoso `MIN(...) OVER (ROWS BETWEEN CURRENT ROW AND UNBOUNDED
    # FOLLOWING)` de la iteración 2 por un acceso directo ya acotado.
    saliente_lateral = (
        select(Message.created_at.label("saliente_ts"))
        .where(
            Message.activo.is_(True),
            Message.conversation_id == conversaciones_ids_subq.c.id,
            es_saliente,
            Message.created_at > entrantes_lateral.c.entrante_ts,
        )
        .correlate(conversaciones_ids_subq, entrantes_lateral)
        .order_by(Message.created_at)
        .limit(1)
        .lateral("saliente_lateral")
    )

    delta_seg = cast(
        func.extract(
            "epoch",
            saliente_lateral.c.saliente_ts - entrantes_lateral.c.entrante_ts,
        ),
        Float,
    )

    # `conversaciones_ids_subq
    #    CROSS JOIN LATERAL entrantes_lateral
    #    CROSS JOIN LATERAL saliente_lateral`:
    # por cada conversación del rango, por cada inicio de bloque entrante,
    # se busca su siguiente saliente. Los `ON true` (`sa_true()`) son el
    # equivalente de un `CROSS JOIN LATERAL` puro en SQLAlchemy Core — la
    # correlación real ya la hacen `mensajes_anotados_stmt`/
    # `saliente_lateral` arriba. Un bloque entrante SIN respuesta posterior
    # simplemente no produce fila de `saliente_lateral` (implementa el caso
    # límite "sin respuesta" por AUSENCIA de fila, sin necesitar un
    # `LEFT JOIN` ni un filtro `IS NOT NULL` adicional); una conversación
    # con SOLO mensajes salientes nunca genera fila de `entrantes_lateral`
    # (implementa "solo salientes" de la misma forma, sin cambios respecto a
    # las iteraciones anteriores).
    respuestas_subq = (
        select(
            conversaciones_ids_subq.c.id.label("conversation_id"),
            delta_seg.label("delta_seg"),
            func.row_number()
            .over(
                partition_by=conversaciones_ids_subq.c.id,
                order_by=entrantes_lateral.c.entrante_ts,
            )
            .label("orden_en_conversacion"),
        )
        .select_from(conversaciones_ids_subq)
        .join(entrantes_lateral, sa_true())
        .join(saliente_lateral, sa_true())
        .subquery()
    )

    resumen_stmt = select(
        func.count(respuestas_subq.c.delta_seg).label("n_respuestas"),
        func.avg(respuestas_subq.c.delta_seg).label("respuesta_promedio_seg"),
        func.count(respuestas_subq.c.delta_seg)
        .filter(respuestas_subq.c.orden_en_conversacion == 1)
        .label("n_primeras_respuestas"),
        func.avg(respuestas_subq.c.delta_seg)
        .filter(respuestas_subq.c.orden_en_conversacion == 1)
        .label("primera_respuesta_promedio_seg"),
        func.count(func.distinct(respuestas_subq.c.conversation_id)).label(
            "conversaciones_con_respuesta"
        ),
    )
    resumen = db.execute(resumen_stmt).one()

    respuesta_promedio = resumen.respuesta_promedio_seg
    primera_respuesta_promedio = resumen.primera_respuesta_promedio_seg

    return ResponseTimeMetrics(
        primera_respuesta_promedio_seg=(
            float(primera_respuesta_promedio)
            if primera_respuesta_promedio is not None
            else None
        ),
        respuesta_promedio_seg=(
            float(respuesta_promedio) if respuesta_promedio is not None else None
        ),
        conversaciones_con_respuesta=int(resumen.conversaciones_con_respuesta or 0),
    )


# ---------------------------------------------------------------------------
# 3. Tasa de conversión
# ---------------------------------------------------------------------------


def get_conversion_rate(
    db: Session,
    *,
    desde: date,
    hasta: date,
    canal: str | None = None,
) -> ConversionMetrics:
    """Tasa de conversión = conversaciones cerradas / conversaciones totales
    en el rango (Q1(a) del Lead, PLAN-007 — `Conversation.estado="cerrada"`,
    cero dominio nuevo). Mismo universo de conversaciones que
    `get_conversation_metrics` (activas, rango sobre `created_at`, filtro de
    canal opcional).

    Si `totales == 0` la tasa es `None`, NUNCA `0` NI una división por cero:
    `0` comunicaría "0% de conversión" (hay conversaciones pero ninguna
    cerró), mientras que en un rango sin ninguna conversación no hay dato
    del que calcular una tasa — `None`/`null` es la respuesta honesta
    (decisión documentada en SPEC-062/RF-03, criterio de aceptación
    explícito)."""
    metrics = get_conversation_metrics(db, desde=desde, hasta=hasta, canal=canal)
    if metrics.total == 0:
        tasa = None
    else:
        tasa = metrics.cerradas / metrics.total
    return ConversionMetrics(tasa=tasa, cerradas=metrics.cerradas, totales=metrics.total)


# ---------------------------------------------------------------------------
# 4. (Opcional, RF-04) Asistencia IA
# ---------------------------------------------------------------------------


def get_ai_assistance_metrics(
    db: Session,
    *,
    desde: date,
    hasta: date,
    canal: str | None = None,
) -> AiAssistanceMetrics | None:
    """% de conversaciones del rango con al menos un `RagDraft` en
    `estado="aprobado"` (SPEC-019) + distribución de `Message.sentimiento`
    (SPEC-018) de los mensajes del rango. Ambas señales se leen de columnas
    YA persistidas — sin inferencia de IA nueva (RNF-01/ADR-003/005).

    Universo de conversaciones: el mismo que `get_conversation_metrics`
    (activas, `created_at` en rango, canal opcional). `pct_drafts_aprobados`
    es `None` (no `0`) si `conversaciones_total == 0`, mismo criterio que
    `get_conversion_rate` (sin división por cero, sin "0%" engañoso).

    La distribución de sentimiento cuenta `Message.activo=True` cuyo
    `created_at` cae en el rango (independientemente de si su conversación
    quedó excluida por canal — el sentimiento es una señal del MENSAJE, se
    filtra por canal vía `Conversation.canal` con un JOIN, igual que el
    resto de funciones, para mantener el mismo contrato `canal` en las 4
    funciones)."""
    condicion_rango_conv = _rango_condiciones(desde, hasta, Conversation.created_at)
    conversaciones_where = [Conversation.activo.is_(True), condicion_rango_conv]
    filtro_canal = _filtro_canal(canal)
    if filtro_canal is not None:
        conversaciones_where.append(filtro_canal)

    conversaciones_ids_subq = (
        select(Conversation.id).where(*conversaciones_where).subquery()
    )

    conversaciones_total = int(
        db.execute(select(func.count()).select_from(conversaciones_ids_subq)).scalar()
        or 0
    )

    con_draft_aprobado_stmt = (
        select(func.count(func.distinct(RagDraft.conversation_id)))
        .select_from(RagDraft)
        .join(
            conversaciones_ids_subq,
            conversaciones_ids_subq.c.id == RagDraft.conversation_id,
        )
        .where(RagDraft.activo.is_(True), RagDraft.estado == "aprobado")
    )
    conversaciones_con_draft_aprobado = int(
        db.execute(con_draft_aprobado_stmt).scalar() or 0
    )

    if conversaciones_total == 0:
        pct_drafts_aprobados = None
    else:
        pct_drafts_aprobados = conversaciones_con_draft_aprobado / conversaciones_total

    condicion_rango_msg = _rango_condiciones(desde, hasta, Message.created_at)
    sentimiento_stmt = (
        select(
            func.count(Message.id)
            .filter(Message.sentimiento == "positivo")
            .label("positivo"),
            func.count(Message.id)
            .filter(Message.sentimiento == "neutral")
            .label("neutral"),
            func.count(Message.id)
            .filter(Message.sentimiento == "negativo")
            .label("negativo"),
            func.count(Message.id)
            .filter(Message.sentimiento.is_(None))
            .label("sin_clasificar"),
        )
        .select_from(Message)
        .join(
            conversaciones_ids_subq,
            conversaciones_ids_subq.c.id == Message.conversation_id,
        )
        .where(Message.activo.is_(True), condicion_rango_msg)
    )
    fila_sentimiento = db.execute(sentimiento_stmt).one()

    return AiAssistanceMetrics(
        pct_drafts_aprobados=pct_drafts_aprobados,
        conversaciones_con_draft_aprobado=conversaciones_con_draft_aprobado,
        conversaciones_total=conversaciones_total,
        sentimiento=SentimientoDistribucion(
            positivo=int(fila_sentimiento.positivo or 0),
            neutral=int(fila_sentimiento.neutral or 0),
            negativo=int(fila_sentimiento.negativo or 0),
            sin_clasificar=int(fila_sentimiento.sin_clasificar or 0),
        ),
    )
