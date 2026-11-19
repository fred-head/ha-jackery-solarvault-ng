"""The public identity encoding contract, including delimiter collisions."""

import pytest

from custom_components.jackery.identity import (
    child_device_identifier,
    child_unique_id,
    http_unique_id,
    parse_child_device_identifier,
    parse_child_unique_id,
)


@pytest.mark.parametrize("serial,encoded", [
    ("123456", "123456"), ("lower_CASE", "lower_CASE"), ("A:B", "A%3AB"),
    ("A%B", "A%25B"), ("x/y?#", "x%2Fy%3F%23"), ("Ä 空", "%C3%84%20%E7%A9%BA"),
    (" spaced ", "%20spaced%20"), ("A%3AB", "A%253AB"),
])
def test_identity_components_are_encoded_once(serial, encoded):
    identifier = f"child:{encoded}:{encoded}"
    uid = f"jackery_{identifier}:ct:importenergy"
    assert child_device_identifier(serial, serial) == identifier
    assert child_unique_id(serial, serial, "ct", "importenergy") == uid
    assert parse_child_device_identifier(identifier) == (serial, serial)
    assert parse_child_unique_id(uid) == (serial, serial, "ct", "importenergy")


def test_component_boundaries_do_not_collide():
    pairs = [("A:B", "C"), ("A", "B:C"), ("A%3AB", "C"), ("a", "B:C"), ("A_B", "C"), ("A", "B_C")]
    assert len({child_device_identifier(*pair) for pair in pairs}) == len(pairs)
    assert len({child_unique_id(*pair, "plug", "power") for pair in pairs}) == len(pairs)


@pytest.mark.parametrize("identifier", ["sub_A", "child:A%3aB:C", "child:A:B:C", "child::B", "child:A:%XX"])
def test_noncanonical_device_identifiers_are_not_accepted(identifier):
    assert parse_child_device_identifier(identifier) is None


def test_http_normal_ids_stay_stable_and_ambiguous_pairs_are_separate():
    assert http_unique_id("HOST", "lower_123", "frequency") == "jackery_HOST_http_sm_lower_123_frequency"
    assert http_unique_id("A_http_sm_B", "C", "frequency") != http_unique_id("A", "B_http_sm_C", "frequency")
    assert http_unique_id("A", "B_http_sm_C", "frequency") == "jackery_child:A:B_http_sm_C:http:frequency"
