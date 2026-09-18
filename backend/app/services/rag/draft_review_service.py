"""Revisión human-in-the-loop del borrador RAG — SPEC-019.

Este servicio es el ÚNICO punto que persiste/transiciona un `RagDraft`
(SPEC-019) y el que decide cuándo (y solo cuándo) un borrador se convierte en
un `Message` saliente real. La generación del texto/citas es de SPEC-017
(`app.services.rag.draft_service.generate_rag_draft`); aquí solo se gestiona
el ciclo de vida humano: proponer -> [editar] -> aprobar (envía) | descartar.

RESTRICCIÓN DURA (SENSIBLE, criterio central de SPEC-019): `approve_and_send`
es la ÚNICA función de este módulo que llama a
`app.services.message_service.create_message`. Ninguna otra función de este
archivo (`create_draft`, `edit_draft`, `discard_draft`) crea o envía un
mensaje. Así, "nada se envía sin aprobación humana explícita" no depende de
una convención en el endpoint sino de que el código de envío está aislado en
una sola función invocada exclusivamente por la acción de aprobar.

Concurrencia (revisión BLACK PANTHER, hallazgo BLOQUEANTE): `edit_draft`,
`discard_draft` y `approve_and_send` transicionan el estado con un UPDATE
condicional ATÓMICO (`WHERE id = :id AND estado IN (<mutables>)`), NUNCA
leyendo el estado en Python y mutando atributos por separado. Dos requests
concurrentes sobre el MISMO borrador (doble clic, doble pestaña, retry de
red) solo pueden lograr que UNA de las dos transacciones actualice la fila
(`rowcount == 1`); la otra ve `rowcount == 0` (la fila ya no cumple el
`WHERE`, sin importar qué haya en memoria) y se traduce en
`DraftNotMutableError` -> 409, SIN haber llamado a `create_message`. El
`UPDATE` y el `create_message` de `approve_and_send` ocurren en la MISMA
transacción de sesión (`db`, sin commit intermedio): si el `UPDATE` no
afecta ninguna fila, la función retorna antes de tocar `messages`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.message import Message
from app.models.rag_draft import ESTADOS_DRAFT_MUTABLES, RagDraft
from app.services.message_service import create_message
from app.services.rag.draft_service import Citation, RagDraftResult

_REMITENTE_SALIENTE = "agente"


class DraftNotMutableError(RuntimeError):
    """El borrador ya no está en un estado mutable (aprobado/descartado, o
    fue transicionado por otra request concurrente entre lectura y escritura)."""


def _citations_to_json(citations: list[Citation]) -> list[dict]:
    return [
        {
            "source": c.source,
            "excerpt": c.excerpt,
            "similarityScore": c.similarity_score,
            "chunk_id": c.chunk_id,
            "document_id": c.document_id,
        }
        for c in citations
    ]


def create_draft(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    query: str,
    result: RagDraftResult,
    created_by: str | None,
) -> RagDraft:
    """Persiste el borrador generado por SPEC-017 en estado `propuesto`.

    NO crea ni envía ningún `Message`: solo dejas el borrador disponible para
    revisión humana (RF SPEC-019).
    """
    draft = RagDraft(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        query=query,
        content_original=result.content,
        content=result.content,
        model=result.model,
        citations=_citations_to_json(result.citations),
        estado="propuesto",
        created_by=created_by,
    )
    db.add(draft)
    db.flush()
    db.refresh(draft)
    return draft


def get_draft_activo(
    db: Session, conversation_id: uuid.UUID, draft_id: uuid.UUID
) -> RagDraft | None:
    return db.scalar(
        select(RagDraft).where(
            RagDraft.id == draft_id,
            RagDraft.conversation_id == conversation_id,
            RagDraft.activo.is_(True),
        )
    )


def _atomic_transition(
    db: Session,
    draft: RagDraft,
    *,
    values: dict,
) -> None:
    """UPDATE condicional atómico: solo transiciona `draft` si SIGUE en un
    estado mutable EN LA BASE DE DATOS en este instante (no en memoria).

    `rowcount == 0` significa que otra transacción concurrente ya transicionó
    (o descartó) este borrador entre que lo leímos y que intentamos
    escribirlo -> `DraftNotMutableError` (409), sin aplicar ningún efecto
    secundario (p.ej. `create_message`). Esto es lo que serializa dos
    `approve` concurrentes del mismo borrador en un único ganador.
    """
    result = db.execute(
        update(RagDraft)
        .where(
            RagDraft.id == draft.id,
            RagDraft.estado.in_(ESTADOS_DRAFT_MUTABLES),
        )
        .values(**values)
    )
    if result.rowcount == 0:
        raise DraftNotMutableError(
            "El borrador ya no admite esta acción: fue aprobado, descartado, "
            "o modificado por otra solicitud concurrente."
        )
    db.flush()
    db.refresh(draft)


def edit_draft(
    db: Session, draft: RagDraft, *, content: str, edited_by: str | None
) -> RagDraft:
    """El agente edita el texto final antes de aprobar (RF SPEC-019: "la
    edición del agente se conserva como texto final enviado").

    `content_original` (lo que generó el RAG) NUNCA se sobrescribe, para
    conservar el historial de qué propuso la IA vs. qué aprobó el humano.
    `created_by` (quién GENERÓ el borrador) tampoco se sobrescribe: quién
    edita se registra por separado en `edited_by` (hallazgo MAYOR, revisión
    BLACK PANTHER) para no perder el origen del borrador.
    """
    _atomic_transition(
        db,
        draft,
        values={"content": content, "estado": "editado", "edited_by": edited_by},
    )
    return draft


def discard_draft(db: Session, draft: RagDraft) -> RagDraft:
    """El agente descarta el borrador: NUNCA genera un mensaje saliente."""
    _atomic_transition(db, draft, values={"estado": "descartado"})
    return draft


def approve_and_send(
    db: Session,
    draft: RagDraft,
    *,
    approved_by: str,
) -> tuple[RagDraft, Message]:
    """ÚNICO punto donde un borrador se convierte en mensaje saliente real.

    Requiere una acción humana explícita del llamador (este método se invoca
    SOLO desde el endpoint de aprobación, nunca automáticamente al generar o
    editar). El texto enviado es `draft.content` (el final vigente: editado
    si el agente lo cambió, original si lo aprobó tal cual) — nunca se
    recalcula ni se vuelve a consultar el RAG en este paso.

    Orden de operaciones (crítico para la atomicidad, ver `_atomic_transition`):
    1. UPDATE condicional `estado -> aprobado` (falla con 409 si otra request
       ya lo transicionó). Nótese que aquí AÚN no fijamos `sent_message_id`
       porque el `Message` todavía no existe.
    2. Solo si (1) tuvo éxito, se crea el `Message` saliente.
    3. Se fija `sent_message_id`/`approved_by` en la MISMA transacción de
       sesión (sin commit intermedio entre el UPDATE de (1) y el `flush` de
       (3)): un rollback de la transacción revierte ambos pasos juntos.
    """
    _atomic_transition(
        db, draft, values={"estado": "aprobado", "approved_by": approved_by}
    )

    message = create_message(
        db,
        tenant_id=draft.tenant_id,
        conversation_id=draft.conversation_id,
        remitente=_REMITENTE_SALIENTE,
        contenido=draft.content,
        created_by=approved_by,
    )

    draft.sent_message_id = message.id
    db.flush()
    db.refresh(draft)
    return draft, message
