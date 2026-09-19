"""Tests de `app.services.message_service.update_delivery_status` — SPEC-032
(hardening deuda SPEC-030, BLACK PANTHER).

Unitarios puros (sin Postgres real): `Message` se instancia en memoria (no
se persiste), y `db` se dobla con un stub mínimo (`flush`/`refresh` no-op)
porque `update_delivery_status` solo los invoca cuando SÍ cambia el estado —
suficiente para verificar el contrato de la función sin una sesión real.

Cubre:
  (a) progresión monotónica normal (caso ya cubierto implícitamente por
      otros tests de integración, aquí como control);
  (b) `failed` es terminal: una vez el mensaje está `failed`, CUALQUIER
      llamada posterior (incluyendo un status "más avanzado" como `leido`)
      es no-op — el mensaje NUNCA se "revive", sin depender de que el
      caller (p.ej. `whatsapp_inbound_worker`) filtre antes de invocar.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.models.message import ESTADO_ENTREGA_FAILED, Message
from app.services.message_service import update_delivery_status


def _fake_message(estado_entrega: str) -> Message:
    message = Message()
    message.estado_entrega = estado_entrega
    return message


def _fake_db() -> MagicMock:
    db = MagicMock()
    db.flush.return_value = None
    db.refresh.return_value = None
    return db


# ---------------------------------------------------------------------------
# (a) Progresión monotónica normal (control)
# ---------------------------------------------------------------------------


def test_progression_enviado_to_entregado_updates_state():
    db = _fake_db()
    message = _fake_message("enviado")

    result = update_delivery_status(db, message, "entregado")

    assert result.estado_entrega == "entregado"
    db.flush.assert_called_once()


def test_progression_does_not_go_backwards():
    db = _fake_db()
    message = _fake_message("leido")

    result = update_delivery_status(db, message, "entregado")

    assert result.estado_entrega == "leido"
    db.flush.assert_not_called()


def test_invalid_estado_entrega_raises_value_error():
    db = _fake_db()
    message = _fake_message("enviado")

    with pytest.raises(ValueError):
        update_delivery_status(db, message, "no-es-un-estado-valido")


# ---------------------------------------------------------------------------
# (b) `failed` es TERMINAL: no-op ante cualquier llamada posterior.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("estado_entrante", ["enviado", "entregado", "leido"])
def test_failed_message_is_never_revived_by_any_subsequent_status(estado_entrante):
    """Hardening SPEC-032: un mensaje `failed` NUNCA cambia de estado, ni
    siquiera si llega un status "más avanzado" como `leido` (p.ej. reentrega
    desordenada de Meta tras el fallo)."""
    db = _fake_db()
    message = _fake_message(ESTADO_ENTREGA_FAILED)

    result = update_delivery_status(db, message, estado_entrante)

    assert result.estado_entrega == ESTADO_ENTREGA_FAILED
    db.flush.assert_not_called()
    db.refresh.assert_not_called()


def test_failed_message_update_is_idempotent_across_multiple_calls():
    db = _fake_db()
    message = _fake_message(ESTADO_ENTREGA_FAILED)

    update_delivery_status(db, message, "leido")
    update_delivery_status(db, message, "entregado")
    update_delivery_status(db, message, "enviado")

    assert message.estado_entrega == ESTADO_ENTREGA_FAILED
    db.flush.assert_not_called()
