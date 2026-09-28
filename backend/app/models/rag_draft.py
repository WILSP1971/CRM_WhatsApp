"""Modelo `rag_drafts` — borrador RAG human-in-the-loop (SPEC-019).

Persiste el borrador generado por `generate_rag_draft` (SPEC-017) asociado a
una conversación, para que el agente humano lo revise/edite/apruebe ANTES de
que se convierta en un mensaje saliente real (`Message`, SPEC-014/015).

Máquina de estados (RF-07 SPEC-019):
    propuesto -> editado -> aprobado
              -> aprobado
    propuesto -> descartado
    editado   -> descartado

- `propuesto`: recién generado por el RAG, texto = `content_original`.
- `editado`: el agente modificó `content` (se conserva `content_original`).
- `aprobado`: acción humana explícita; a partir de aquí `sent_message_id`
  queda enlazado al `Message` saliente creado en ese mismo momento (nunca
  antes: "nada se envía sin aprobación" es el criterio central de SPEC-019).
- `descartado`: el agente decide no enviar nada; no genera ningún mensaje.

Trazabilidad (RNF-06): `created_by` (quién GENERÓ el borrador, inmutable),
`edited_by` (quién hizo la última edición, si la hubo) y `approved_by`
(quién aprobó el envío) permiten auditar el origen humano completo de todo
mensaje que salió de un borrador sin perder quién lo propuso originalmente.

Concurrencia (revisión BLACK PANTHER, hallazgo BLOQUEANTE): las transiciones
de estado (`editar`/`descartar`/`aprobar`) se ejecutan como un UPDATE
condicional atómico (`WHERE estado IN (...)`) en `draft_review_service`, NO
como "leer en Python + mutar atributos + flush". Esto evita que dos
`approve` concurrentes del mismo borrador (doble clic, doble pestaña, retry)
generen dos mensajes salientes: solo una de las transacciones logra el
UPDATE (rowcount == 1); la otra ve rowcount == 0 y falla con 409.

Respuesta de audio (TTS de salida, Entregable #6, ADR-014/SPEC-068):

- `respuesta_modo` (`RESPUESTA_MODO_VALIDOS`): opt-in (Q2-A) sobre el modo de
  la respuesta que representa este borrador. Default `"texto"` = el
  comportamiento actual e idéntico (SPEC-029/#5); el agente elige
  explícitamente `"audio"` para que, al aprobar, además del `Message` de
  texto de siempre se dispare la síntesis TTS del guion aprobado (SPEC-069,
  fuera de alcance aquí). `NOT NULL` con `server_default='texto'` para no
  romper ninguna fila existente (RNF-64).
- `tts_estado` (`TTS_ESTADO_VALIDOS`): estado de la ruta OPCIONAL "escuchar
  antes de enviar" (Q1-C) — el agente genera el clip bajo demanda para
  reproducirlo antes de aprobar. `NULL` mientras nadie la solicita
  (`"no_solicitado"` es el valor lógico por defecto, pero se deja la columna
  nullable en vez de forzar ese string en cada fila: es un campo de "estado
  de un proceso opcional", no un discriminador siempre poblado como
  `respuesta_modo`). El invariante de aprobación (ADR-014 decisión 1) NO
  depende de este campo: se puede aprobar el guion sin haber tocado nunca la
  ruta de escucha.
- `audio_salida_ref` (opcional, nullable): referencia OPACA al almacén
  cifrado de audio (mismo patrón que `messages.audio_ref`/`calls.audio_ref`,
  SPEC-035/036/053) del clip TTS de SALIDA. Por defecto `NULL` (ADR-012 §5,
  herencia: el clip TTS no se persiste por defecto, basta el guion
  aprobado); solo se puebla si una política de auditoría decide persistir el
  clip (régimen SPEC-041, cifrado). Nunca una ruta física ni un binario ni
  una URL externa (C3).

Estos tres campos son deliberadamente aditivos/nullable-friendly y NO
introducen ninguna dependencia nueva de `sent_message_id`/máquina de estados
de `estado`: son ortogonales al ciclo `propuesto→editado→aprobado/descartado`
ya existente. El servicio/worker que los popula (SPEC-069) está FUERA de
alcance de este módulo: aquí solo se define el esquema y las constantes de
valores válidos.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin

# Estados válidos del borrador (RF-07 SPEC-019).
ESTADOS_DRAFT_VALIDOS = {"propuesto", "editado", "aprobado", "descartado"}

# Estados desde los que AÚN se puede editar/aprobar/descartar (no son
# terminales). `aprobado`/`descartado` son finales: una vez ahí, el borrador
# ya no se puede mutar (se debe generar uno nuevo).
ESTADOS_DRAFT_MUTABLES = {"propuesto", "editado"}

# Modo de la respuesta (opt-in, Q2-A, ADR-014). Default "texto" = idéntico al
# comportamiento actual (SPEC-029/#5); "audio" activa la síntesis TTS del
# guion aprobado (SPEC-069, fuera de alcance de este modelo).
RESPUESTA_MODO_VALIDOS = {"texto", "audio"}
RESPUESTA_MODO_DEFAULT = "texto"

# Estados de la ruta OPCIONAL "escuchar antes de enviar" (Q1-C, ADR-014).
# `NULL` (columna nullable) mientras nadie la solicita; estos son los únicos
# valores válidos una vez que el agente pide generar el clip bajo demanda.
TTS_ESTADO_VALIDOS = {"no_solicitado", "generando", "listo", "error"}


class RagDraft(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "rag_drafts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    content_original: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # texto tal cual lo generó el RAG (nunca se sobrescribe)
    content: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # texto final vigente: original o editado por el agente
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    citations: Mapped[list] = mapped_column(
        JSONB, nullable=False
    )  # lista de citas trazables (source/excerpt/similarityScore/ids), SPEC-017
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="propuesto"
    )  # propuesto | editado | aprobado | descartado
    edited_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="RESTRICT"),
        nullable=True,
    )  # se completa SOLO al aprobar (RF: nada se envía antes de la aprobación)

    # --- Respuesta de audio (TTS de salida, Entregable #6, ADR-014/SPEC-068) ---
    respuesta_modo: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=RESPUESTA_MODO_DEFAULT
    )  # "texto" (default, opt-in) | "audio" — Q2-A
    tts_estado: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # no_solicitado | generando | listo | error — ruta "escuchar antes de enviar" (Q1-C)
    audio_salida_ref: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # referencia opaca al almacén cifrado del clip TTS; NULL salvo auditoría (ADR-012 §5)
