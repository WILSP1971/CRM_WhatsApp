"""Esquemas de respuesta del endpoint `GET /analytics/business` — SPEC-063.

Reflejan 1:1 los `dataclasses` congelados de `app.services.analytics_service`
(SPEC-062): estos schemas NO añaden ni reinterpretan ningún campo, solo dan
forma Pydantic/OpenAPI a lo que el servicio ya calculó. Ningún campo expone
PII individual (ids de contacto, contenido de mensajes, etc.) — todo aquí son
agregados (conteos/promedios/tasas), por diseño de `analytics_service`
(RF-04 SPEC-062, RF-04 SPEC-063).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class ConversacionesPorCanalOut(BaseModel):
    """Desglose de volumen de conversaciones para UN canal."""

    canal: str
    total: int
    abiertas: int
    cerradas: int

    model_config = {"from_attributes": True}


class SerieDiariaPuntoOut(BaseModel):
    """Un punto de la serie diaria de volumen de conversaciones.

    Cubre SIEMPRE el rango completo día a día — un día sin conversaciones
    aparece con `total=0`, nunca se omite (criterio de SPEC-062)."""

    fecha: date
    total: int

    model_config = {"from_attributes": True}


class ConversationMetricsOut(BaseModel):
    """Volumen de conversaciones activas del rango (soft-delete excluido)."""

    total: int
    abiertas: int
    cerradas: int
    por_canal: list[ConversacionesPorCanalOut] = Field(default_factory=list)
    serie_diaria: list[SerieDiariaPuntoOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ResponseTimeMetricsOut(BaseModel):
    """Tiempos de primera respuesta (TPR) y de respuesta promedio.

    `primera_respuesta_promedio_seg`/`respuesta_promedio_seg` son `None`
    (nunca `0`) cuando no hay ninguna conversación con respuesta en el rango
    — ver docstring de `get_response_time_metrics`."""

    primera_respuesta_promedio_seg: float | None
    respuesta_promedio_seg: float | None
    conversaciones_con_respuesta: int

    model_config = {"from_attributes": True}


class ConversionMetricsOut(BaseModel):
    """Tasa de conversión = cerradas/totales.

    `tasa` es `None` (nunca `0`) cuando `totales == 0`: comunica "sin datos
    para calcular una tasa" en vez de sugerir falsamente "0% de conversión"
    (criterio explícito de SPEC-062/RF-03)."""

    tasa: float | None
    cerradas: int
    totales: int

    model_config = {"from_attributes": True}


class SentimientoDistribucionOut(BaseModel):
    positivo: int
    neutral: int
    negativo: int
    sin_clasificar: int

    model_config = {"from_attributes": True}


class AiAssistanceMetricsOut(BaseModel):
    """Asistencia IA (opcional, RF-04 SPEC-062): % de drafts RAG aprobados +
    distribución de sentimiento, ambas leídas de columnas ya persistidas."""

    pct_drafts_aprobados: float | None
    conversaciones_con_draft_aprobado: int
    conversaciones_total: int
    sentimiento: SentimientoDistribucionOut

    model_config = {"from_attributes": True}


class BusinessAnalyticsOut(BaseModel):
    """Respuesta completa de `GET /analytics/business` (SPEC-063): un único
    bloque agregado JSON con KPIs de conversaciones, tiempos de respuesta,
    conversión y (opcional) asistencia IA — SOLO agregados del tenant
    autenticado, sin PII individual."""

    desde: date
    hasta: date
    canal: str | None = Field(
        default=None, description="Canal por el que se filtró la consulta, si alguno."
    )
    conversaciones: ConversationMetricsOut
    tiempos_respuesta: ResponseTimeMetricsOut
    conversion: ConversionMetricsOut
    ia_asistencia: AiAssistanceMetricsOut | None = Field(
        default=None,
        description="Asistencia IA (opcional, RF-04 SPEC-062): `null` si el "
        "servicio no la calculó para esta consulta.",
    )
