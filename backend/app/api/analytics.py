"""Router `analytics` — métricas agregadas de NEGOCIO — SPEC-063.

Mismo patrón de seguridad que el resto de la API (`app/api/conversations.py`,
`app/api/calls.py`, SPEC-013/014): JWT (`get_current_user`) + sesión con
`app.tenant_id` ya fijado (`get_tenant_db`) -> RLS (ADR-004/ADR-008) aísla
las métricas de otros tenants a nivel de motor. Este router es DELGADO a
propósito (RF-03 SPEC-063): valida query params, delega TODA la agregación en
`app.services.analytics_service` (SPEC-062, ya probado de forma aislada
contra Postgres real) y serializa el resultado — cero SQL aquí.

Modo on-demand (Q2 del Lead, PLAN-007): cada request recalcula sobre el
rango pedido; sin caché, sin tiempo real/WebSocket (fuera de alcance
explícito de SPEC-063).

Solo lectura (RF de SPEC-063: "cualquier escritura/mutación" está OUT) y solo
agregados en la respuesta (RF-04): nunca se expone un id de contacto, el
contenido de un mensaje, ni ningún otro dato individual — los schemas de
`app/schemas/analytics.py` reflejan 1:1 los `dataclasses` de
`analytics_service`, que ya están diseñados para eso.

Rango sin datos (tenant sin conversaciones en `[desde, hasta]`) SIEMPRE
responde 200 con ceros/`None` — nunca un error 4xx/5xx: lo garantiza
`analytics_service` (ver sus docstrings sobre `None` vs `0` en tasas/
promedios); este router no reintroduce ninguna división ni validación que
pueda romper esa garantía.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_db
from app.core.config import get_settings
from app.models.user import User
from app.schemas.analytics import (
    AiAssistanceMetricsOut,
    BusinessAnalyticsOut,
    ConversacionesPorCanalOut,
    ConversationMetricsOut,
    ConversionMetricsOut,
    ResponseTimeMetricsOut,
    SentimientoDistribucionOut,
    SerieDiariaPuntoOut,
)
from app.schemas.conversation import CANALES_VALIDOS
from app.services.analytics_service import (
    conversion_rate_from_metrics,
    get_ai_assistance_metrics,
    get_conversation_metrics,
    get_response_time_metrics,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _validar_canal(canal: str | None) -> str | None:
    """Valida `canal` contra `CANALES_VALIDOS` (`app/schemas/conversation.py`,
    SPEC-014) — mismo conjunto de dominio que el resto de la API. `None`
    (sin filtro) siempre es válido."""
    if canal is not None and canal not in CANALES_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"canal inválido: debe ser uno de {sorted(CANALES_VALIDOS)}",
        )
    return canal


def _validar_rango(desde: date, hasta: date) -> None:
    """`desde <= hasta` (RF-02) y tope superior configurable de días
    inclusive (`ANALYTICS_MAX_RANGE_DAYS`, R-73 performance) — ambos casos
    422, nunca 500 ni un cálculo silenciosamente truncado."""
    if desde > hasta:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El parámetro 'desde' no puede ser posterior a 'hasta'.",
        )

    max_range_days = get_settings().analytics_max_range_days
    dias_solicitados = (hasta - desde).days + 1  # rango inclusive
    if dias_solicitados > max_range_days:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"El rango solicitado ({dias_solicitados} días) supera el "
                f"máximo permitido ({max_range_days} días). Acota 'desde'/"
                "'hasta' o realiza varias consultas por sub-rangos."
            ),
        )


def _conversation_metrics_out(metrics) -> ConversationMetricsOut:
    return ConversationMetricsOut(
        total=metrics.total,
        abiertas=metrics.abiertas,
        cerradas=metrics.cerradas,
        por_canal=[
            ConversacionesPorCanalOut(
                canal=item.canal,
                total=item.total,
                abiertas=item.abiertas,
                cerradas=item.cerradas,
            )
            for item in metrics.por_canal
        ],
        serie_diaria=[
            SerieDiariaPuntoOut(fecha=punto.fecha, total=punto.total)
            for punto in metrics.serie_diaria
        ],
    )


def _ai_assistance_out(metrics) -> AiAssistanceMetricsOut | None:
    if metrics is None:
        return None
    return AiAssistanceMetricsOut(
        pct_drafts_aprobados=metrics.pct_drafts_aprobados,
        conversaciones_con_draft_aprobado=metrics.conversaciones_con_draft_aprobado,
        conversaciones_total=metrics.conversaciones_total,
        sentimiento=SentimientoDistribucionOut(
            positivo=metrics.sentimiento.positivo,
            neutral=metrics.sentimiento.neutral,
            negativo=metrics.sentimiento.negativo,
            sin_clasificar=metrics.sentimiento.sin_clasificar,
        ),
    )


@router.get("/business", response_model=BusinessAnalyticsOut)
def get_business_analytics(
    desde: date = Query(
        ...,
        description="Fecha inicial del rango (inclusive), formato ISO "
        "YYYY-MM-DD. Se evalúa sobre `Conversation.created_at`.",
    ),
    hasta: date = Query(
        ...,
        description="Fecha final del rango (inclusive), formato ISO "
        "YYYY-MM-DD. Debe ser >= 'desde'.",
    ),
    canal: str
    | None = Query(
        default=None,
        description="Filtro opcional de canal. Debe ser uno de: "
        f"{sorted(CANALES_VALIDOS)}.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> BusinessAnalyticsOut:
    """KPIs agregados de negocio del tenant autenticado para `[desde, hasta]`
    (inclusive), opcionalmente acotados a un `canal`.

    Incluye volumen de conversaciones (total/abiertas/cerradas/por
    canal/serie diaria), tiempos de respuesta (TPR y respuesta promedio),
    tasa de conversión y asistencia IA (% de borradores RAG aprobados +
    distribución de sentimiento). Modo on-demand: se recalcula en cada
    llamada sobre datos ya persistidos, sin caché ni tiempo real.

    Un rango sin ninguna conversación devuelve 200 con todos los agregados en
    cero/`null` (nunca un error). La respuesta contiene EXCLUSIVAMENTE
    agregados: ningún id de contacto ni contenido de mensaje individual.
    """
    canal_validado = _validar_canal(canal)
    _validar_rango(desde, hasta)

    conversaciones = get_conversation_metrics(
        db, desde=desde, hasta=hasta, canal=canal_validado
    )
    tiempos_respuesta = get_response_time_metrics(
        db, desde=desde, hasta=hasta, canal=canal_validado
    )
    conversion = conversion_rate_from_metrics(conversaciones)
    ia_asistencia = get_ai_assistance_metrics(
        db, desde=desde, hasta=hasta, canal=canal_validado
    )

    return BusinessAnalyticsOut(
        desde=desde,
        hasta=hasta,
        canal=canal_validado,
        conversaciones=_conversation_metrics_out(conversaciones),
        tiempos_respuesta=ResponseTimeMetricsOut(
            primera_respuesta_promedio_seg=tiempos_respuesta.primera_respuesta_promedio_seg,
            respuesta_promedio_seg=tiempos_respuesta.respuesta_promedio_seg,
            conversaciones_con_respuesta=tiempos_respuesta.conversaciones_con_respuesta,
        ),
        conversion=ConversionMetricsOut(
            tasa=conversion.tasa,
            cerradas=conversion.cerradas,
            totales=conversion.totales,
        ),
        ia_asistencia=_ai_assistance_out(ia_asistencia),
    )
