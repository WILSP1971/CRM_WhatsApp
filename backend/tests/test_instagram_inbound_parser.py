"""Tests de `app.integrations.instagram.inbound_parser` — SPEC-086 (F1).

Unitarios puros (sin I/O, sin Postgres, sin Redis): cubren el parseo del
payload crudo de Instagram DM (`object:"instagram"`, `entry[].messaging[]`)
a `InstagramMessageEvent`.
"""

from __future__ import annotations

import json

import pytest

from app.integrations.instagram.inbound_parser import (
    InboundEventParseError,
    InstagramDeliveryEvent,
    parse_delivery_events,
    parse_inbound_instagram_events,
)


def _payload(
    *,
    instagram_account_id="ig-biz-1",
    mid="mid.ABC",
    sender_id="ig-user-123",
    texto="hola",
    attachments=None,
):
    message: dict = {"mid": mid}
    if texto is not None:
        message["text"] = texto
    if attachments is not None:
        message["attachments"] = attachments

    return json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": instagram_account_id,
                    "time": 1700000000,
                    "messaging": [
                        {
                            "sender": {"id": sender_id},
                            "recipient": {"id": instagram_account_id},
                            "timestamp": 1700000000,
                            "message": message,
                        }
                    ],
                }
            ],
        }
    )


def test_parse_extracts_single_text_message():
    events = parse_inbound_instagram_events(_payload())

    assert len(events) == 1
    event = events[0]
    assert event.mid == "mid.ABC"
    assert event.instagram_account_id == "ig-biz-1"
    assert event.sender_id == "ig-user-123"
    assert event.tipo == "text"
    assert event.texto == "hola"
    assert event.attachments == []


def test_parse_extracts_attachment_message_without_text():
    payload = _payload(
        texto=None,
        attachments=[{"type": "image", "payload": {"url": "https://example.com/a.jpg"}}],
    )

    events = parse_inbound_instagram_events(payload)

    assert len(events) == 1
    event = events[0]
    assert event.tipo == "attachment"
    assert event.texto is None
    assert event.attachments == [
        {"type": "image", "url": "https://example.com/a.jpg"}
    ]


def test_parse_multiple_entries_and_messaging_events():
    raw = json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "ig-biz-1",
                    "messaging": [
                        {
                            "sender": {"id": "user-1"},
                            "recipient": {"id": "ig-biz-1"},
                            "message": {"mid": "mid-1", "text": "primero"},
                        },
                        {
                            "sender": {"id": "user-2"},
                            "recipient": {"id": "ig-biz-1"},
                            "message": {"mid": "mid-2", "text": "segundo"},
                        },
                    ],
                },
                {
                    "id": "ig-biz-2",
                    "messaging": [
                        {
                            "sender": {"id": "user-3"},
                            "recipient": {"id": "ig-biz-2"},
                            "message": {"mid": "mid-3", "text": "tercero"},
                        }
                    ],
                },
            ],
        }
    )

    events = parse_inbound_instagram_events(raw)

    assert [e.mid for e in events] == ["mid-1", "mid-2", "mid-3"]
    assert [e.texto for e in events] == ["primero", "segundo", "tercero"]


def test_echo_message_is_ignored_without_error():
    raw = json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "ig-biz-1",
                    "messaging": [
                        {
                            "sender": {"id": "ig-biz-1"},
                            "recipient": {"id": "user-1"},
                            "message": {
                                "mid": "mid-echo",
                                "text": "eco de mi propio envío",
                                "is_echo": True,
                            },
                        }
                    ],
                }
            ],
        }
    )

    events = parse_inbound_instagram_events(raw)

    assert events == []


def test_status_callback_without_message_is_ignored_without_error():
    """Callbacks de `delivery`/`read` no traen `message`; se ignoran sin
    reventar (son responsabilidad de SPEC-089, no de este parser)."""
    raw = json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "ig-biz-1",
                    "messaging": [
                        {
                            "sender": {"id": "ig-biz-1"},
                            "recipient": {"id": "user-1"},
                            "delivery": {"mids": ["mid-1"], "watermark": 1700000000},
                        }
                    ],
                }
            ],
        }
    )

    events = parse_inbound_instagram_events(raw)

    assert events == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["entry"][0]["messaging"][0]["message"].pop("mid"),
        lambda d: d["entry"][0]["messaging"][0].pop("sender"),
        lambda d: d["entry"][0]["messaging"][0].pop("recipient"),
    ],
)
def test_incomplete_messaging_event_is_ignored_without_error(mutate):
    data = json.loads(_payload())
    mutate(data)

    events = parse_inbound_instagram_events(json.dumps(data))

    assert events == []


def test_invalid_json_raises_parse_error():
    with pytest.raises(InboundEventParseError):
        parse_inbound_instagram_events("{not-valid-json")


def test_missing_entry_key_raises_parse_error():
    with pytest.raises(InboundEventParseError):
        parse_inbound_instagram_events(json.dumps({"object": "instagram"}))


def test_wrong_object_value_raises_parse_error():
    with pytest.raises(InboundEventParseError):
        parse_inbound_instagram_events(
            json.dumps({"object": "whatsapp_business_account", "entry": []})
        )


def test_empty_entry_list_returns_no_events():
    events = parse_inbound_instagram_events(json.dumps({"object": "instagram", "entry": []}))

    assert events == []


# ---------------------------------------------------------------------------
# `parse_delivery_events` — SPEC-089, conciliación de statuses de ENVÍO.
# ---------------------------------------------------------------------------


def _delivery_payload(
    *, instagram_account_id="ig-biz-1", sender_id="ig-user-123", mids=None
):
    return json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": instagram_account_id,
                    "time": 1700000000,
                    "messaging": [
                        {
                            "sender": {"id": sender_id},
                            "recipient": {"id": instagram_account_id},
                            "delivery": {
                                "mids": mids if mids is not None else ["mid.OUT1"],
                                "watermark": 1700000000,
                            },
                        }
                    ],
                }
            ],
        }
    )


def test_parse_delivery_events_extracts_mids_and_account_id():
    events = parse_delivery_events(
        _delivery_payload(instagram_account_id="ig-biz-42", mids=["mid.A", "mid.B"])
    )

    assert events == [
        InstagramDeliveryEvent(mids=["mid.A", "mid.B"], instagram_account_id="ig-biz-42")
    ]


def test_parse_delivery_events_ignores_message_events():
    # Un evento de MENSAJE entrante (sin "delivery") no debe aparecer aquí.
    events = parse_delivery_events(_payload())

    assert events == []


def test_parse_inbound_instagram_events_ignores_delivery_events():
    # Y viceversa: un callback `delivery` no debe colarse como mensaje entrante.
    events = parse_inbound_instagram_events(_delivery_payload())

    assert events == []


def test_parse_delivery_events_ignores_read_callbacks():
    payload = json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "ig-biz-1",
                    "time": 1700000000,
                    "messaging": [
                        {
                            "sender": {"id": "ig-user-123"},
                            "recipient": {"id": "ig-biz-1"},
                            "read": {"watermark": 1700000000},
                        }
                    ],
                }
            ],
        }
    )

    events = parse_delivery_events(payload)

    assert events == []


def test_parse_delivery_events_without_mids_is_ignored():
    payload = json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "ig-biz-1",
                    "messaging": [
                        {
                            "sender": {"id": "ig-user-123"},
                            "recipient": {"id": "ig-biz-1"},
                            "delivery": {"watermark": 1700000000},
                        }
                    ],
                }
            ],
        }
    )

    events = parse_delivery_events(payload)

    assert events == []


def test_parse_delivery_events_invalid_json_raises_parse_error():
    with pytest.raises(InboundEventParseError):
        parse_delivery_events("{not-valid-json")


def test_parse_delivery_events_wrong_object_raises_parse_error():
    with pytest.raises(InboundEventParseError):
        parse_delivery_events(
            json.dumps({"object": "whatsapp_business_account", "entry": []})
        )
