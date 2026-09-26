"""Modelo `messages` — mensajes persistidos de una conversación (SPEC-012,
extendido por SPEC-015 con estado de entrega del WebChat, por SPEC-018 con
el sentimiento clasificado por el LLM local, por SPEC-025 con el `wamid`
de WhatsApp para idempotencia, por SPEC-053 con el tipo `audio` para la
nota de voz de WhatsApp (ADR-013) y por SPEC-054 con el `mime_type` del
media descargado de WhatsApp."""

import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin

# Etiquetas de sentimiento válidas (SPEC-018 RF-07).
SENTIMIENTOS_VALIDOS = {"positivo", "neutral", "negativo"}

# Estados de entrega (SPEC-015, criterio de aceptación "estados de entrega
# enviado/entregado/leído"). Progresión monotónica: enviado -> entregado ->
# leido (nunca retrocede). SPEC-025 reutiliza el mismo campo/contrato como
# estado de transporte del canal WhatsApp (RF-02): no se añade una columna
# de estado paralela, ya que el mismo vocabulario aplica ("enviado" tras el
# ACK de la API de WhatsApp, "entregado"/"leido" por los statuses del
# webhook, conciliados en SPEC-030). Se documenta aquí para que quede
# explícito en el contrato del modelo (no hay regresión, RNF-07).
ESTADOS_ENTREGA_VALIDOS = {"enviado", "entregado", "leido"}

# `failed` (SPEC-029, RF-04): estado TERMINAL propio del transporte de
# ENVÍO por Graph API (`app/workers/wa_send_worker.py`) — ni la Graph API ni
# los reintentos idempotentes lograron entregar el mensaje (429/5xx
# agotados, ventana de 24h bloqueada sin plantilla HSM, o configuración de
# envío incompleta). Deliberadamente SEPARADO de `ESTADOS_ENTREGA_VALIDOS`
# (que modela la progresión enviado -> entregado -> leido de los callbacks
# de estado, SPEC-015/030): `update_delivery_status` (progresión monotónica)
# NUNCA debe aceptar `failed` como argumento, así que no se añade a ese set;
# `wa_send_worker` asigna `message.estado_entrega = "failed"` directamente,
# fuera de esa función, exactamente una vez por mensaje que no logró
# transportarse.
ESTADO_ENTREGA_FAILED = "failed"

# Discriminador de tipo de mensaje (SPEC-053 RF-01, ADR-013). `"texto"` es el
# tipo histórico/por defecto lógico (mensajes de WhatsApp/WebChat existentes
# antes de esta SPEC); `"audio"` es una nota de voz de WhatsApp, que nace SIN
# `contenido` (None) hasta que el worker STT (SPEC-056) escribe la
# transcripción. La nota de voz vive en `messages` como un `Message` real de
# su `Conversation` — NUNCA como una entidad `call`/`call_transcript`
# (ADR-013, ver `app/models/call.py` para ese dominio distinto).
TIPOS_MENSAJE_VALIDOS = {"texto", "audio"}
TIPO_MENSAJE_TEXTO = "texto"

# Estados válidos del ciclo de vida de la transcripción de una nota de voz
# (SPEC-053 RF-04, columna `transcripcion_estado`). `None` para mensajes de
# tipo `"texto"` (el campo nunca aplica a ellos). Para `tipo="audio"`:
# "pendiente" (encolada, aún sin transcribir, SPEC-055), "ok" (transcripción
# escrita en `contenido` por el sink `message` del `stt_worker`, SPEC-056),
# "descartada_por_duracion" (excede el límite de duración de SPEC-055, nunca
# se transcribe) o "error" (el STT falló; modo degradado, no bloquea el
# mensaje ya persistido).
TRANSCRIPCION_ESTADOS_VALIDOS = {"pendiente", "ok", "descartada_por_duracion", "error"}


class Message(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("wamid", name="uq_messages_wamid"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    remitente: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # "contacto" | "agente" | "ia"
    contenido: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # NOT NULL histórico relajado a NULLABLE (SPEC-053, RF-03): un
    # `Message(tipo="audio")` nace sin contenido hasta que el STT lo escribe
    # (SPEC-056); los mensajes de texto lo siguen poblando siempre, sin
    # regresión (RNF-64)
    tipo: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # "texto" | "audio" (SPEC-053 RF-01, ADR-013), ver TIPOS_MENSAJE_VALIDOS.
    # Backfill a "texto" para las filas preexistentes en la propia migración
    # (807a0756643c); None solo sería posible en una fila insertada fuera del
    # flujo normal del servicio
    audio_ref: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # referencia opaca (no la ruta física ni el binario) al almacén de
    # audio cifrado de SPEC-035, mismo patrón que `Call.audio_ref`
    # (SPEC-036); None para mensajes de texto
    transcripcion_estado: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )  # "pendiente" | "ok" | "descartada_por_duracion" | "error" (SPEC-053
    # RF-04), ver TRANSCRIPCION_ESTADOS_VALIDOS; None para mensajes de texto
    audio_duracion_seg: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # duración en segundos de la nota de voz (SPEC-053 RF-04, límite de
    # duración aplicado en SPEC-055); None para mensajes de texto. Permanece
    # SIEMPRE None tras la descarga de SPEC-054: el endpoint de resolución de
    # media de Graph API (`GET /<version>/<media-id>`, ver
    # `media_client.resolve_media_metadata`) NO provee duración en su
    # respuesta (solo `url`/`mime_type`/`sha256`/`file_size`, verificado
    # contra la documentación de Media de WhatsApp Cloud API al implementar
    # SPEC-054) — no es un olvido, no hay hoy ninguna fuente de este dato en
    # el flujo de descarga; queda pendiente de un cálculo propio (p.ej. leer
    # la duración del contenedor OGG/Opus ya descargado) si una SPEC futura
    # lo requiere
    mime_type: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # tipo MIME del media descargado de WhatsApp (SPEC-054 RF-02, p.ej.
    # "audio/ogg; codecs=opus"), tal cual lo reporta Meta en la resolución de
    # metadata (`GraphMediaClient.resolve_media_metadata`); None para
    # mensajes de texto y para notas de voz cuya descarga falló antes de
    # resolver metadata (`transcripcion_estado="error"`)
    sentimiento: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # "positivo" | "neutral" | "negativo" (SPEC-018), None = sin clasificar
    sentimiento_score: Mapped[float | None] = mapped_column(
        Numeric(precision=4, scale=3), nullable=True
    )  # score [0,1] del LLM local (SPEC-018), None = sin clasificar
    estado_entrega: Mapped[str] = mapped_column(
        String(20), nullable=False, default="enviado"
    )  # "enviado" | "entregado" | "leido" (SPEC-015; reutilizado por SPEC-025
    # como estado de transporte de WhatsApp, ver comentario de
    # ESTADOS_ENTREGA_VALIDOS arriba)
    wamid: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # id de mensaje de WhatsApp (Meta), UNIQUE cuando no es None — base de
    # idempotencia (ADR-007). None para mensajes de otros canales (webchat).
