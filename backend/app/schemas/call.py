"""Esquemas de `calls`/`call_transcripts` expuestos a la SPA — SPEC-040.

Expone al frontend (ficha de llamada del módulo VoiceBot, SPEC-006) los datos
ya persistidos por SPEC-036 (`Call`/`CallTranscript`) y enriquecidos por
SPEC-038 (transcripción)/SPEC-039 (sentimiento + resumen + borrador RAG), sin
introducir ninguna tabla ni lógica de negocio nueva: este módulo solo define
la FORMA de lectura HTTP.

`audio_ref` NUNCA se expone tal cual (sería un identificador de storage
interno, C3): en su lugar `CallOut.audio_disponible` es un booleano derivado
("hay audio para reproducir sí/no") y el binario se sirve por un endpoint de
streaming aparte (`GET /calls/{id}/audio`, `app/api/calls.py`) que nunca
revela la ruta física ni la clave de cifrado.

SPEC-041 (retención/purga de audio y transcripción, extiende SPEC-021): añade
`CallTranscriptOut.anonymized_at` (informativo: `None` mientras la
transcripción no ha sido anonimizada por el job de retención,
`app.services.telefonia.call_retention_service`). `audio_disponible` sigue
reflejando "¿existe `audio_ref` hoy?" (RF-02 SPEC-040) — tras una purga por
retención, `audio_ref` queda `None` y por tanto `audio_disponible=False`
automáticamente, sin necesidad de un campo adicional en `CallOut`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.rag import CitationOut

DIRECCIONES_CALL_VALIDAS = {"entrante", "saliente"}
ESTADOS_CALL_VALIDOS = {"en_curso", "finalizada", "fallida", "transcrita"}


class CallOut(BaseModel):
    """Fila de listado — SIN transcripción/borrador (evita payloads pesados
    en `GET /calls`; el detalle completo vive en `GET /calls/{id}`)."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    call_id: str
    numero: str
    direccion: str
    duracion: int | None
    estado: str
    contact_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    resumen: str | None
    audio_disponible: bool = Field(
        description="`true` si hay un audio_ref asociado (sujeto a retención, "
        "SPEC-041); `false` si nunca hubo audio o ya fue purgado por la "
        "política de retención (ver `job` app.workers.call_retention_job)."
    )
    activo: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TranscriptSegmentOut(BaseModel):
    """Un segmento de la transcripción (`call_transcripts.segmentos`, JSONB,
    SPEC-036/038): inicio/fin en segundos, texto y hablante."""

    inicio: float
    fin: float
    texto: str
    hablante: str


class CallTranscriptOut(BaseModel):
    id: uuid.UUID
    call_id: uuid.UUID
    segmentos: list[TranscriptSegmentOut]
    idioma: str
    modelo_stt: str
    wer: float | None
    anonymized_at: datetime | None = Field(
        default=None,
        description="SPEC-041: cuándo se anonimizó el contenido por política "
        "de retención; `None` mientras la transcripción no ha sido "
        "anonimizada. Si tiene valor, `segmentos` ya contiene solo el "
        "marcador de anonimización, no el texto original.",
    )

    model_config = {"from_attributes": True}


class CallSentimentOut(BaseModel):
    """Sentimiento de la llamada (SPEC-018/039): derivado del `Message`
    sintético que materializa la transcripción (RF-04, `stt_worker`), NO una
    columna nueva en `Call`. `None` mientras el análisis de sentimiento aún
    no corrió (best-effort, asíncrono) o si no hay conversación enlazada."""

    sentimiento: str | None
    sentimiento_score: float | None


class CallRagDraftOut(BaseModel):
    """Borrador RAG propuesto sobre la llamada (SPEC-019/039): el MISMO
    borrador human-in-the-loop que ya gestiona `POST /rag/...` — aquí solo se
    expone en modo lectura para la ficha; su revisión/edición/aprobación usa
    los endpoints existentes de `app/api/rag.py` (sin duplicar lógica)."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    content: str
    content_original: str
    model: str
    citations: list[CitationOut] = Field(..., min_length=3)
    estado: str
    edited_by: str | None
    approved_by: str | None
    sent_message_id: uuid.UUID | None


class CallDetailOut(BaseModel):
    """Ficha de llamada completa (SPEC-040): llamada + transcripción +
    sentimiento + resumen + borrador citado — todo lo que necesita el
    módulo VoiceBot para dejar de mostrar datos mock."""

    call: CallOut
    transcript: CallTranscriptOut | None
    sentiment: CallSentimentOut
    rag_draft: CallRagDraftOut | None
