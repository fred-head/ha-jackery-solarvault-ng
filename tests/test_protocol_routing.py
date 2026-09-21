"""Direct tests for pure protocol topic, envelope and route decisions."""

import json

import pytest

from custom_components.jackery.protocol.routing import (
    MessageRoute,
    TopicInfo,
    exclude_serial_from_child_arrays,
    is_host_message_body,
    parse_envelope,
    parse_topic,
    route_message_type,
    subdevice_serial,
)


@pytest.mark.parametrize(
    ("message_type", "route", "metadata", "generic_children"),
    [
        (23, MessageRoute.TYPE_23, True, False),
        (101, MessageRoute.TYPE_101, False, False),
        (102, MessageRoute.TYPE_102, False, False),
        (106, MessageRoute.TYPE_106, True, True),
        (107, MessageRoute.TYPE_107, True, True),
        (123, MessageRoute.TYPE_123, False, False),
        (2, MessageRoute.GENERIC, True, True),
        (25, MessageRoute.GENERIC, True, True),
        (1, MessageRoute.GENERIC, False, True),
        (999, MessageRoute.GENERIC, False, True),
        (None, MessageRoute.GENERIC, False, True),
        ("107", MessageRoute.GENERIC, False, True),
        ([], MessageRoute.GENERIC, False, True),
        ({}, MessageRoute.GENERIC, False, True),
        (106.0, MessageRoute.TYPE_106, True, True),
    ],
)
def test_route_message_type_contract(
    message_type,
    route,
    metadata,
    generic_children,
):
    decision = route_message_type(message_type)
    assert decision.message_type == message_type
    assert decision.route is route
    assert decision.captures_host_metadata is metadata
    assert decision.refreshes_generic_children is generic_children


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("lab.+/hb/device/HOST/status", TopicInfo("HOST", "status")),
        ("lab.+/hb/device/FOREIGN/event", TopicInfo("FOREIGN", "event")),
        ("labZZ/hb/device/HOST/status", None),
        ("xlab.+/hb/device/HOST/status", None),
        ("lab.+/hb/device//status", None),
        ("lab.+/hb/device/HOST/action", None),
        ("lab.+/hb/device/HOST/status/extra", None),
    ],
)
def test_parse_topic_is_literal_and_anchored(topic, expected):
    assert parse_topic("lab.+/hb", topic) == expected


@pytest.mark.parametrize(
    ("body_serial", "expected"),
    [
        (None, True),
        ("system", True),
        ("HOST", True),
        ("CHILD", False),
        ([], False),
        ({}, False),
    ],
)
def test_host_body_decision(body_serial, expected):
    assert is_host_message_body({"deviceSn": body_serial}, "HOST") is expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"deviceSn": "DEVICE", "sn": "FALLBACK"}, "DEVICE"),
        ({"deviceSn": "", "sn": "FALLBACK"}, "FALLBACK"),
        ({"sn": "DEVICE"}, "DEVICE"),
        ({"deviceSn": 17, "sn": "FALLBACK"}, None),
        ({"deviceSn": [], "sn": "FALLBACK"}, "FALLBACK"),
        ({"deviceSn": ""}, None),
        ({}, None),
    ],
)
def test_subdevice_serial_preserves_existing_precedence(payload, expected):
    assert subdevice_serial(payload) == expected


def test_parse_nested_envelope_and_bytes():
    parsed = parse_envelope(b'{"type":107,"body":{"soc":0,"future":1}}')
    assert parsed is not None
    assert parsed.raw_data == {"type": 107, "body": {"soc": 0, "future": 1}}
    assert parsed.body == {"soc": 0, "future": 1}
    assert parsed.decision.route is MessageRoute.TYPE_107


def test_parse_flat_envelope_uses_existing_normalization_boundary():
    parsed = parse_envelope(
        '{"type":25,"eventId":0,"token":"secret","batSoc":0,"future":1}'
    )
    assert parsed is not None
    assert parsed.body == {"batSoc": 0, "future": 1}
    assert parsed.raw_data["token"] == "secret"
    assert parsed.decision.route is MessageRoute.GENERIC


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        "null",
        "7",
        '{"type":2,"body":[]}',
        '{"type":2,"body":"bad"}',
        '{"type":2,"body":7}',
        '{"type":101,"body":null}',
    ],
)
def test_parse_unsupported_envelope_shapes(payload):
    assert parse_envelope(payload) is None


def test_parse_missing_body_retains_empty_generic_body():
    parsed = parse_envelope('{"type":2}')
    assert parsed is not None
    assert parsed.body == {}
    assert parsed.decision.route is MessageRoute.GENERIC


def test_invalid_json_remains_caller_visible():
    with pytest.raises(json.JSONDecodeError):
        parse_envelope("{")


def test_child_array_sanitizing_preserves_existing_shapes_without_mutation():
    body = {
        "plugs": {"bad": "container"},
        "cts": None,
        "collectors": [
            7,
            {"sn": "GOOD", "devType": 4},
            {"sn": 17, "devType": 4},
            {"future": 1},
        ],
        "soc": 0,
    }
    envelope = {"type": 2, "body": body}

    parsed = parse_envelope(json.dumps(envelope))

    assert parsed is not None
    assert parsed.body == {
        "cts": None,
        "collectors": [
            {"sn": "GOOD", "devType": 4},
            {"future": 1},
        ],
        "soc": 0,
    }
    assert envelope["body"] is body
    assert body["plugs"] == {"bad": "container"}


def test_child_array_serial_exclusion_is_exact_and_does_not_mutate_input():
    body = {
        "plugs": [
            {"deviceSn": "HOST"},
            {"deviceSn": "host"},
            {"sn": "CHILD"},
        ],
        "future": 1,
    }

    filtered = exclude_serial_from_child_arrays(body, "HOST")

    assert filtered == {
        "plugs": [{"deviceSn": "host"}, {"sn": "CHILD"}],
        "future": 1,
    }
    assert body["plugs"] == [
        {"deviceSn": "HOST"},
        {"deviceSn": "host"},
        {"sn": "CHILD"},
    ]


def test_malformed_message_type_remains_generic_without_hashing():
    parsed = parse_envelope('{"type":[],"body":{"future":1}}')
    assert parsed is not None
    assert parsed.decision.route is MessageRoute.GENERIC
    assert parsed.body == {"future": 1}
