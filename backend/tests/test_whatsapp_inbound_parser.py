"""Tests de `app.integrations.whatsapp.inbound_parser` — SPEC-027.

Unitarios puros (sin I/O, sin Postgres, sin Redis): cubren el parseo del
payload crudo de WhatsApp Cloud API a `InboundMessageEvent`.
"""

from __future__ import annotations

import json

import pytest

from app.integrations.whatsapp.inbound_parser import (
    InboundEventParseError,
    parse_inbound_message_events,
    parse_status_events,
)


def _payload(
    *,
    phone_number_id="123456",
    wamid="wamid.ABC",
    wa_id="573001112233",
    tipo="text",
    texto="hola",
    contact_name="Cliente Test",
):
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "biz-1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "phone_number_id": phone_number_id,
                                    "display_phone_number": "+57 300 000 0000",
                                },
                                "contacts": [
                                    {"wa_id": wa_id, "profile": {"name": contact_name}}
                                ],
                                "messages": [
                                    {
                                        "id": wamid,
                                        "from": wa_id,
                                        "timestamp": "1700000000",
                                        "type": tipo,
                                        **(
                                            {"text": {"body": texto}}
                                            if tipo == "text"
                                            else {}
                                        ),
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )


def test_parse_extracts_single_text_message():
    events = parse_inbound_message_events(_payload())

    assert len(events) == 1
    event = events[0]
    assert event.wamid == "wamid.ABC"
    assert event.phone_number_id == "123456"
    assert event.wa_id == "573001112233"
    assert event.tipo == "text"
    assert event.texto == "hola"
    assert event.contact_name == "Cliente Test"


def test_parse_non_text_message_has_none_texto():
    events = parse_inbound_message_events(_payload(tipo="image", texto=None))

    assert len(events) == 1
    assert events[0].tipo == "image"
    assert events[0].texto is None


def test_parse_ignores_statuses_field():
    raw = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "biz-1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "123456"},
                                "statuses": [
                                    {"id": "wamid.STATUS", "status": "delivered"}
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )

    events = parse_inbound_message_events(raw)

    assert events == []


def test_parse_ignores_changes_with_other_field():
    raw = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "biz-1",
                    "changes": [{"field": "account_alerts", "value": {}}],
                }
            ],
        }
    )

    events = parse_inbound_message_events(raw)

    assert events == []


def test_parse_multiple_messages_same_event():
    raw = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "biz-1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "123456"},
                                "contacts": [{"wa_id": "573001112233"}],
                                "messages": [
                                    {
                                        "id": "wamid.1",
                                        "from": "573001112233",
                                        "type": "text",
                                        "text": {"body": "hola"},
                                    },
                                    {
                                        "id": "wamid.2",
                                        "from": "573001112233",
                                        "type": "text",
                                        "text": {"body": "adios"},
                                    },
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )

    events = parse_inbound_message_events(raw)

    assert [e.wamid for e in events] == ["wamid.1", "wamid.2"]


def test_parse_missing_phone_number_id_ignores_change():
    raw = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "biz-1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {},
                                "messages": [
                                    {
                                        "id": "wamid.1",
                                        "from": "573001112233",
                                        "type": "text",
                                        "text": {"body": "hola"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )

    events = parse_inbound_message_events(raw)

    assert events == []


def test_parse_malformed_json_raises_parse_error():
    with pytest.raises(InboundEventParseError):
        parse_inbound_message_events("{esto no es json")


def test_parse_missing_entry_key_raises_parse_error():
    with pytest.raises(InboundEventParseError):
        parse_inbound_message_events(
            json.dumps({"object": "whatsapp_business_account"})
        )


# ---------------------------------------------------------------------------
# parse_status_events — SPEC-030
# ---------------------------------------------------------------------------


def _status_payload(
    *,
    phone_number_id="123456",
    wamid="wamid.OUT.1",
    status="delivered",
    errors=None,
):
    value = {
        "metadata": {"phone_number_id": phone_number_id},
        "statuses": [
            {
                "id": wamid,
                "status": status,
                "timestamp": "1700000000",
                **({"errors": errors} if errors is not None else {}),
            }
        ],
    }
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {"id": "biz-1", "changes": [{"field": "messages", "value": value}]}
            ],
        }
    )


def test_parse_status_events_extracts_delivered():
    events = parse_status_events(_status_payload(status="delivered"))

    assert len(events) == 1
    event = events[0]
    assert event.wamid == "wamid.OUT.1"
    assert event.phone_number_id == "123456"
    assert event.status == "delivered"
    assert event.error_titles == []


def test_parse_status_events_extracts_failed_with_error_titles():
    events = parse_status_events(
        _status_payload(
            status="failed",
            errors=[{"code": 131026, "title": "Message undeliverable"}],
        )
    )

    assert len(events) == 1
    assert events[0].status == "failed"
    assert events[0].error_titles == ["Message undeliverable"]


def test_parse_status_events_ignores_messages_field():
    """El parser de statuses ignora `value.messages[]` (SPEC-027, no es su
    responsabilidad) — separación estricta entre ambos parsers."""
    raw = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "biz-1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "123456"},
                                "messages": [
                                    {
                                        "id": "wamid.IN.1",
                                        "from": "573001112233",
                                        "type": "text",
                                        "text": {"body": "hola"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )

    events = parse_status_events(raw)

    assert events == []


def test_parse_status_events_multiple_statuses_same_event():
    raw = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "biz-1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "123456"},
                                "statuses": [
                                    {"id": "wamid.OUT.1", "status": "sent"},
                                    {"id": "wamid.OUT.1", "status": "delivered"},
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )

    events = parse_status_events(raw)

    assert [e.status for e in events] == ["sent", "delivered"]


def test_parse_status_events_missing_phone_number_id_ignores_change():
    raw = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "biz-1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {},
                                "statuses": [
                                    {"id": "wamid.OUT.1", "status": "delivered"}
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )

    events = parse_status_events(raw)

    assert events == []


def test_parse_status_events_incomplete_status_is_skipped():
    raw = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "biz-1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "123456"},
                                "statuses": [{"status": "delivered"}],  # sin "id"
                            },
                        }
                    ],
                }
            ],
        }
    )

    events = parse_status_events(raw)

    assert events == []


def test_parse_status_events_malformed_json_raises_parse_error():
    with pytest.raises(InboundEventParseError):
        parse_status_events("{esto no es json")


def test_parse_status_events_missing_entry_key_raises_parse_error():
    with pytest.raises(InboundEventParseError):
        parse_status_events(json.dumps({"object": "whatsapp_business_account"}))
