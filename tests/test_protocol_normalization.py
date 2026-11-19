"""Direct tests for the pure protocol normalization boundary."""

import pytest

from custom_components.jackery.protocol.normalization import (
    extract_flat_body,
    normalize_payload_fields,
)


@pytest.mark.parametrize(
    ("alias", "canonical", "value"),
    [
        ("gridBuyPw", "gridInPw", 300),
        ("gridSellPw", "gridOutPw", 120),
        ("workModel", "workMode", 4),
    ],
)
def test_each_wire_alias_populates_its_canonical_field(alias, canonical, value):
    result = normalize_payload_fields({alias: value})
    assert result == {alias: value, canonical: value}


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("gridBuyPw", "gridInPw"),
        ("gridSellPw", "gridOutPw"),
        ("workModel", "workMode"),
    ],
)
def test_explicit_canonical_zero_wins_over_alias(alias, canonical):
    result = normalize_payload_fields({alias: 9, canonical: 0})
    assert result[canonical] == 0
    assert result[alias] == 9


def test_null_canonical_is_filled_by_non_null_alias():
    result = normalize_payload_fields({"gridInPw": None, "gridBuyPw": 25})
    assert result == {"gridInPw": 25, "gridBuyPw": 25}


def test_null_alias_does_not_create_missing_canonical_field():
    result = normalize_payload_fields({"gridBuyPw": None})
    assert result == {"gridBuyPw": None}
    assert "gridInPw" not in result


def test_missing_and_unknown_fields_are_preserved_in_a_new_shallow_copy():
    nested = {"vendor": "value"}
    payload = {"unknown": nested}
    result = normalize_payload_fields(payload)
    assert result == payload
    assert result is not payload
    assert result["unknown"] is nested


def test_normalization_does_not_mutate_caller_input_and_retains_alias():
    payload = {"workModel": 7}
    result = normalize_payload_fields(payload)
    assert payload == {"workModel": 7}
    assert result == {"workModel": 7, "workMode": 7}


@pytest.mark.parametrize("value", [0, None])
def test_flat_status_recognition_uses_key_presence(value):
    assert extract_flat_body({"type": 25, "pvPw": value}) == {"pvPw": value}


@pytest.mark.parametrize(
    "raw_data",
    [
        {"type": 25, "workModel": 4},
        {"type": 25, "gridBuyPw": 100},
        {"type": 23, "inEgy": 10},
        {"type": 101, "cts": []},
    ],
)
def test_unrecognized_flat_shapes_remain_empty(raw_data):
    assert extract_flat_body(raw_data) == {}


def test_flat_body_strips_all_metadata_and_preserves_other_payload_fields():
    raw_data = {
        "type": 2,
        "eventId": 0,
        "messageId": 1234,
        "ts": 1,
        "deviceType": 3,
        "token": "secret",
        "softver": "1.0",
        "body": None,
        "soc": 0,
        "unknown": "retained",
    }
    assert extract_flat_body(raw_data) == {"soc": 0, "unknown": "retained"}


def test_flat_body_extraction_does_not_mutate_input():
    raw_data = {"type": 2, "batSoc": 88}
    before = dict(raw_data)
    result = extract_flat_body(raw_data)
    assert raw_data == before
    assert result is not raw_data
