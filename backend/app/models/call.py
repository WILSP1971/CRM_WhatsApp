"""Modelo `calls` — metadatos de llamadas del canal de voz (SPEC-036, ADR-007/ADR-008).

Extiende el dominio (ya agnóstico de canal, `conversations.canal` es
`String(50)`) para soportar la voz/telefonía sin rediseñarlo: una llamada
enlaza opcionalmente a una `Conversation` (`canal="voz"`/`"telefonia"`) y a
un `Contact`, reutilizando el contrato existente (RF-04).

Idempotencia (ADR-007, mismo patrón que `messages.wamid` de SPEC-025):
`call_id` es el identificador estable de la llamada entregado por el
conector de telefonía (SPEC-037, fuera de alcance aquí) y lleva restricción
de **unicidad a nivel de BD** para que una reentrega del mismo evento no cree
una segunda fila (RF-02).

`audio_ref` (opcional, SPEC-035): solo el campo de referencia al almacén de
audio cifrado ya provisto por la infraestructura de SPEC-035 — SIN lógica de
storage/descarga/purga en esta SPEC (eso es SPEC-037/038/041).

`resumen` (opcional, SPEC-039): resumen de la llamada generado por el LLM
local (`app.services.call_summary_service.generate_call_summary`) a partir
del texto completo de `call_transcripts`, tras persistir la transcripción
(`stt_worker`, SPEC-038). Se modela como un campo simple en `Call` (mismo
criterio ya usado para `audio_ref`: relación 1:1 con la llamada, sin caso de
uso de múltiples resúmenes históricos por llamada en el alcance actual) en
vez de una tabla nueva — coherente con RNF-07 (sin regresión, mínima
superficie nueva). `None` mientras la llamada no tiene transcripción, o si el
LLM local no estuvo disponible al intentar resumir (modo degradado, R-21).

Es una entidad TRANSACCIONAL con `tenant_id` propio y por eso lleva **RLS
ENABLE+FORCE** igual que el resto de `TENANT_SCOPED_TABLES` (ADR-004/ADR-008):
un tenant nunca debe poder leer/enumerar las llamadas de otro tenant. Dado
que el audio/transcripción es potencialmente PHI (ADR-009), el aislamiento
por RLS efectiva (rol de aplicación no-superusuario `omnicore_app`) es la
base del control de acceso cross-tenant (RNF-47).

Borrado lógico (C2): dar de baja una llamada es `activo=False`, nunca un
DELETE físico (la política de retención/purga se define en SPEC-041).

`audio_purged_at` (SPEC-041, extiende SPEC-021): timestamp de cuándo el job
de retención (`app.services.telefonia.call_retention_service`) purgó
FÍSICAMENTE el blob de audio del almacén cifrado y limpió `audio_ref`. El
borrado lógico (`activo=False`) SIEMPRE ocurre antes (C2) — esta columna solo
marca el paso adicional de purga física del audio.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin

# Direcciones válidas de la llamada (RF-01).
DIRECCIONES_CALL_VALIDAS = {"entrante", "saliente"}

# Estados válidos de la llamada (RF-01). `en_curso`/`finalizada` cubren el
# ciclo de vida de la llamada en sí; `transcrita` se reserva para cuando el
# worker STT (SPEC-038, fuera de alcance aquí) puebla `call_transcript`.
ESTADOS_CALL_VALIDOS = {"en_curso", "finalizada", "fallida", "transcrita"}


class Call(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "calls"
    __table_args__ = (
        UniqueConstraint("tenant_id", "call_id", name="uq_calls_tenant_call_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    call_id: Mapped[str] = mapped_column(
        String(128), nullable=False
    )  # id estable de la llamada (conector de telefonía, SPEC-037) — UNIQUE
    # por tenant, base de idempotencia (ADR-007, RF-02)
    numero: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # número remoto (E.164/local) del contacto en la llamada
    direccion: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # "entrante" | "saliente"
    duracion: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # duración en segundos, None mientras la llamada está en curso
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en_curso"
    )  # "en_curso" | "finalizada" | "fallida" | "transcrita"
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )  # enlace opcional al mismo bus de conversación que un mensaje de texto
    # (canal="voz"/"telefonia", RF-04); None si aún no se enlazó
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )  # enlace opcional al contacto (RF-04); None si el número no resolvió
    # a un contacto conocido
    audio_ref: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # referencia (no la ruta física ni el binario) al almacén de audio
    # cifrado de SPEC-035; sin lógica de storage en esta SPEC
    resumen: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # resumen LLM local de la llamada (SPEC-039); None si aún no se generó
    # o si el LLM local estuvo indisponible (modo degradado, R-21)
    audio_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # SPEC-041: cuándo se purgó físicamente el audio por retención; None
    # mientras no se ha purgado (nunca hubo audio, o sigue vigente)
