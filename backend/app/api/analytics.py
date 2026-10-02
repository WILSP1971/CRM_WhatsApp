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


@router.get(
    "/business",
    response_model=BusinessAnalyticsOut,
    summary="KPIs de negocio agregados",
    tags=["Analytics"],
)
def get_business_analytics(
    desde: date = Query(
        ...,
        description=(
            "Fecha inicial del rango (inclusive), formato ISO YYYY-MM-DD. "
            "Se evalúa sobre `Conversation.created_at` (fecha de creación de la conversación, "
            "nunca sobre `updated_at`). Máx. `ANALYTICS_MAX_RANGE_DAYS` días desde `hasta`. "
            "Ejemplo: 2026-09-20."
        ),
        example="2026-09-20",
    ),
    hasta: date = Query(
        ...,
        description=(
            "Fecha final del rango (inclusive), formato ISO YYYY-MM-DD. "
            "Debe ser >= 'desde'. El rango es cerrado: incluye conversaciones "
            "creadas durante todo el día `hasta`. "
            "Ejemplo: 2026-09-27."
        ),
        example="2026-09-27",
    ),
    canal: str | None = Query(
        default=None,
        description=(
            "Filtro opcional de canal (nulleable). Válidos: "
            + str(sorted(CANALES_VALIDOS))
            + ". "
            "Si se proporciona, todos los desgloses se acotan a ese canal. "
            "Si está ausente (None), se devuelven todas los canales."
        ),
        example=None,
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> BusinessAnalyticsOut:
    """KPIs agregados de negocio del tenant autenticado para `[desde, hasta]` (inclusive).

    ### Descripción

    Devuelve el resumen operativo de conversaciones, tiempos de respuesta, tasa de conversión
    y métricas de asistencia IA del tenant autenticado dentro del rango de fechas especificado.
    Modo on-demand: se recalcula en cada request sobre datos ya persistidos (sin caché, sin
    WebSocket de tiempo real).

    ### Métricas

    1. **Conversaciones:** volumen total, desgloses por estado (abierta/cerrada) y por canal.
       Serie diaria que cubre completamente el rango (incluyendo días sin datos como total=0).

    2. **Tiempos de respuesta:** TPR (Primera Respuesta, desde primer entrante hasta primera saliente)
       y promedio de respuesta (media de todas las diferencias entrante→saliente). Expresados en
       segundos. `null` si ninguna conversación del rango tuvo respuesta saliente.

    3. **Tasa de conversión:** cerradas / totales. Expresada como decimal [0.0, 1.0].
       `null` (no `0`) si totales=0 (ausencia de datos, no "0% de conversión").
       Definición: conversión = conversaciones con `estado='cerrada'` / conversaciones totales.
       No es un dominio nuevo (Q1(a) PLAN-007): es un cálculo sobre `Conversation.estado` ya persistido.

    4. **Asistencia IA (opcional):** % de conversaciones con >= 1 `RagDraft.estado='aprobado'`,
       y distribución de `Message.sentimiento` (positivo/neutral/negativo/sin_clasificar).

    ### Borrado lógico (C2)

    Todas las métricas excluyen registros con `is_active=False` (soft-delete).

    ### Aislamiento multi-tenant

    Aplicada RLS (Row Level Security) efectiva: el usuario solo ve datos de su tenant.

    ### Rango sin datos

    Si el rango no contiene conversaciones: devuelve 200 (no error) con todos los campos
    en 0/null (según su semántica). La serie diaria cubre el rango completo día a día.

    ### Error 422

    - `desde > hasta`: "El parámetro 'desde' no puede ser posterior a 'hasta'."
    - Rango > `ANALYTICS_MAX_RANGE_DAYS`: "El rango solicitado (...) supera el máximo permitido (...)"
    - `canal` no válido: "canal inválido: debe ser uno de [...]"

    ### Ejemplos

    **Request (rango de 7 días, sin filtro de canal):**
    ```
    GET /api/v1/analytics/business?desde=2026-09-20&hasta=2026-09-27
    ```

    **Response (200 OK):**
    ```json
    {
      "desde": "2026-09-20",
      "hasta": "2026-09-27",
      "canal": null,
      "conversaciones": {
        "total": 150,
        "abiertas": 25,
        "cerradas": 125,
        "por_canal": [
          {"canal": "whatsapp", "total": 80, "abiertas": 10, "cerradas": 70},
          {"canal": "webchat", "total": 70, "abiertas": 15, "cerradas": 55}
        ],
        "serie_diaria": [
          {"fecha": "2026-09-20", "total": 20},
          {"fecha": "2026-09-21", "total": 22},
          {"fecha": "2026-09-22", "total": 18},
          {"fecha": "2026-09-23", "total": 19},
          {"fecha": "2026-09-24", "total": 21},
          {"fecha": "2026-09-25", "total": 25},
          {"fecha": "2026-09-26", "total": 25}
        ]
      },
      "tiempos_respuesta": {
        "primera_respuesta_promedio_seg": 245.3,
        "respuesta_promedio_seg": 189.7,
        "conversaciones_con_respuesta": 140
      },
      "conversion": {
        "tasa": 0.8333,
        "cerradas": 125,
        "totales": 150
      },
      "ia_asistencia": {
        "pct_drafts_aprobados": 0.65,
        "conversaciones_con_draft_aprobado": 91,
        "conversaciones_total": 140,
        "sentimiento": {
          "positivo": 85,
          "neutral": 45,
          "negativo": 10,
          "sin_clasificar": 0
        }
      }
    }
    ```

    **Request (rango sin datos):**
    ```
    GET /api/v1/analytics/business?desde=2020-01-01&hasta=2020-01-02
    ```

    **Response (200 OK, con ceros/nulls):**
    ```json
    {
      "desde": "2020-01-01",
      "hasta": "2020-01-02",
      "canal": null,
      "conversaciones": {
        "total": 0,
        "abiertas": 0,
        "cerradas": 0,
        "por_canal": [],
        "serie_diaria": [
          {"fecha": "2020-01-01", "total": 0},
          {"fecha": "2020-01-02", "total": 0}
        ]
      },
      "tiempos_respuesta": {
        "primera_respuesta_promedio_seg": null,
        "respuesta_promedio_seg": null,
        "conversaciones_con_respuesta": 0
      },
      "conversion": {
        "tasa": null,
        "cerradas": 0,
        "totales": 0
      },
      "ia_asistencia": null
    }
    ```

    ### Referencias

    - METRICS_ANALYTICS.md: definición completa de cada métrica.
    - PLAN-007: decisiones del Lead (Q1–Q4).
    - SPEC-062/064/065: especificaciones y tests.
    - ADR-004/008: Row Level Security efectiva.
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
