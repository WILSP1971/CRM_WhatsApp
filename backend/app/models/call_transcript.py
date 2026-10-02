"""Modelo `call_transcripts` — transcripción segmentada de una llamada (SPEC-036).

Persiste el resultado de la transcripción STT de una `Call` (el worker que
puebla estos datos es SPEC-038, fuera de alcance aquí; esta SPEC solo define
la entidad y su forma). Cada fila es 1:1 (o 1:N si se decide reintentar con
otro modelo) con una `Call`.

Decisión de diseño (ambigüedad de la SPEC, documentada — DOCTOR STRANGE no
especificó "JSON vs tabla separada" para `segmentos`): se modela `segmentos`
como **JSONB** (`list[{inicio, fin, texto, hablante}]`), replicando el mismo
patrón ya usado en `rag_drafts.citations` (SPEC-019, lista de objetos
trazables persistida como JSONB) en vez de una tabla `call_transcript_segment`
separada. Motivos:
  - Los segmentos se escriben una sola vez, en bloque, por el worker STT
    (SPEC-038) al terminar de transcribir — no se consultan/filtran
    individualmente por columna (no hay caso de uso de "buscar el segmento
    con hablante=X" a nivel SQL en el alcance actual).
  - Evita una tabla adicional con su propio `tenant_id`/RLS/FK para una
    estructura que siempre se lee/escribe completa junto a su `call_transcript`
    padre — menor superficie para esta SPEC (solo datos, RNF-07 sin
    regresión) y coherente con el patrón ya aceptado en el Entregable #3.
  - Si SPEC-038/039 necesitan más adelante consultar segmentos individuales
    (p.ej. búsqueda de texto dentro de un segmento a escala), se puede
    extraer a tabla propia en una migración aditiva posterior sin romper este
    contrato (el campo JSONB se mantiene o se deprecía con un aviso).

Es TRANSACCIONAL con `tenant_id` propio y por eso lleva **RLS ENABLE+FORCE**
(ADR-004/ADR-008, RNF-47): el audio/transcripción es PHI potencial (ADR-009).

Borrado lógico (C2): igual que `Call`, sin DELETE físico (la purga por
retención es SPEC-041).

`anonymized_at` (SPEC-041, mismo patrón que `contacts.anonymized_at` de
SPEC-021): timestamp de cuándo el job de retención
(`app.services.telefonia.call_retention_service`) sobrescribió `segmentos`
con un marcador no identificante (acción "anonymize" de la política, en vez
de purga total). `None` mientras la transcripción no ha sido anonimizada.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin

# Claves obligatorias de cada elemento de `segmentos` (RF: "inicio/fin/texto/
# hablante" por segmento). Documentado aquí como contrato del campo JSONB;
# la validación de forma (si se requiere a nivel de aplicación) es
# responsabilidad del worker que puebla esta tabla (SPEC-038).
SEGMENTO_CLAVES_REQUERIDAS = {"inicio", "fin", "texto", "hablante"}


class CallTranscript(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "call_transcripts"
    __table_args__ = (UniqueConstraint("call_id", name="uq_call_transcripts_call_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )  # referencia a la llamada transcrita; UNIQUE (1 transcripción vigente
    # por llamada en el alcance actual)
    segmentos: Mapped[list] = mapped_column(
        JSONB, nullable=False
    )  # lista de {inicio, fin, texto, hablante} por segmento (ver
    # SEGMENTO_CLAVES_REQUERIDAS)
    idioma: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # código de idioma detectado/forzado (p.ej. "es", "es-CO")
    modelo_stt: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # identificador del modelo STT usado (p.ej. "faster-whisper/large-v3")
    wer: Mapped[float | None] = mapped_column(
        Numeric(precision=5, scale=4), nullable=True
    )  # Word Error Rate opcional [0,1], None si no se calculó
    anonymized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # SPEC-041: cuándo se anonimizó el contenido de `segmentos` por
    # retención; None mientras no se ha anonimizado
